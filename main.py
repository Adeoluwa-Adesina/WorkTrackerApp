import tkinter as tk
import datetime
import time
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import os
import logging
import pystray
import threading
import queue
from ttkthemes import ThemedTk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from tkinter import ttk, messagebox, simpledialog, filedialog


# Configure logging
logging.basicConfig(filename='app.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logging.getLogger().addHandler(console_handler)

# Check for Pillow (PIL) library availability for tray icon
PIL_AVAILABLE = False
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    logging.error(
        "Pillow (PIL) library not found. Tray icon functionality will be disabled. Please install it using 'pip install Pillow'.")


class WorkTracker:
    """A desktop application for tracking work sessions."""

    def __init__(self, root):
        """Initialises the WorkTracker Application."""
        # Database setup - Queue for communication with DB thread
        self.db_queue = queue.Queue()
        self.db_thread = threading.Thread(target=self.db_worker, daemon=True)
        self.db_thread.start()

        # root window settings
        self.root = root
        self.root.title("Work Tracker")
        self.root.geometry("500x400")

        # Themes and Styling
        style = ttk.Style(root)
        style.configure("TButton", padding=6, font=("Arial", 11))
        style.configure("TLabel", padding=5, font=("Arial", 11))
        style.configure("TCombobox", padding=5, font=("Arial", 11))
        style.configure("TFrame", background="#f0f0f0")

        self.start_time = None
        self.is_running = False
        self.elapsed_time = 0
        self.stopwatch_running = False
        self.is_paused = False  # New state for pause functionality
        self.pause_start_time = None  # To record when pause began

        # Tray icon related attributes
        self.tray_icon = None
        self.base_tray_image = None
        self.tray_font = None
        self.last_tray_update_time = datetime.datetime.now()  # To control update frequency

        top_frame = ttk.Frame(root, padding=10, style="TFrame")
        top_frame.pack(fill="x")
        ttk.Label(top_frame, text='Category:').grid(
            row=0, column=0, padx=5, pady=5)

        self.end_time = None
        self.current_session_id = None
        self.history_window = None
        self.statistics_window = None

        # Stopwatch
        self.stopwatch_label = ttk.Label(
            root, text="00:00:00.000", font=("Arial", 14))
        self.stopwatch_label.pack(pady=5)

        # Categories
        self.category_var = tk.StringVar(root)
        self.category_dropdown = ttk.Combobox(
            top_frame, textvariable=self.category_var)  # Values set after DB init
        self.category_dropdown.grid(row=0, column=1, padx=5, pady=5)
        self.category_dropdown.bind(
            "<<ComboboxSelected>>", self.on_category_select)  # New binding

        self.add_category_button = ttk.Button(
            top_frame, text="Add Category", command=self.add_category)
        self.add_category_button.grid(row=0, column=2, padx=5, pady=5)
        self.delete_category_button = ttk.Button(
            top_frame, text="Delete Category", command=self.delete_category)
        self.delete_category_button.grid(row=0, column=3, padx=5, pady=5)
        self.rename_category_button = ttk.Button(
            top_frame, text="Rename Category", command=self.rename_category)
        self.rename_category_button.grid(row=0, column=4, padx=5, pady=5)

        # Initialize categories after db_worker has started
        self.root.after(100, self.initial_db_setup)

        # Tasks
        self.task_label = ttk.Label(root, text="Task: ")
        self.task_label.pack()
        self.task_text = tk.Text(root, height=2, width=50)
        self.task_text.pack(padx=10, pady=10)

        button_frame = ttk.Frame(root)
        button_frame.pack(pady=10)

        # Start, Pause/Resume, and Stop Buttons
        self.start_button = ttk.Button(
            button_frame, text="Start", command=self.start_session)
        self.start_button.grid(row=0, column=0, padx=5, pady=5)

        self.pause_button = ttk.Button(
            button_frame, text="Pause", command=self.toggle_pause_resume, state=tk.DISABLED)
        self.pause_button.grid(row=0, column=1, padx=5, pady=5)

        self.stop_button = ttk.Button(
            button_frame, text="Stop", command=self.stop_session, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=2, padx=5, pady=5)

        # History
        self.history_button = ttk.Button(
            button_frame, text="History", command=self.show_history)
        self.history_button.grid(
            row=0, column=3, padx=5, pady=5)  # Adjusted column

        # Statistics button
        self.statistics_button = ttk.Button(
            root, text="Statistics", command=self.show_statistics)
        self.statistics_button.pack(pady=5)

        # Menubar for settings
        self.menubar = tk.Menu(root)
        self.root.config(menu=self.menubar)

        settings_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(
            label="Set Default Category", command=self.open_default_category_settings)
        # Added Exit to menubar
        self.menubar.add_command(label="Exit", command=self.exit_app)

        self.create_tray_icon()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        logging.info("WorkTracker application initialized.")

    def initial_db_setup(self):
        """Called after a short delay to ensure DB thread is ready."""
        user_home = os.path.expanduser("~")
        app_dir = os.path.join(user_home, "WorkTracker")
        if not os.path.exists(app_dir):
            os.makedirs(app_dir)
        db_path = os.path.join(app_dir, "deep_work.db")
        self.db_queue.put(('INIT_DB', (db_path,), None, None))
        # Schedule category dropdown update and then default category load
        self.root.after(200, self.update_category_dropdown)
        self.root.after(300, self.load_default_category_setting)

    def db_worker(self):
        """Dedicated thread for Database Operations."""
        self.db = None
        while True:
            operation_type, args, kwargs, result_queue = self.db_queue.get()
            try:
                if operation_type == 'INIT_DB':
                    db_path = args[0]
                    self.db = Database(db_path)
                    self.db.create_tables()
                    logging.info(f"Database initialized at {db_path}")
                elif self.db:
                    if hasattr(self.db, operation_type):
                        method = getattr(self.db, operation_type)
                        result = method(*args, **kwargs)
                        if result_queue:
                            result_queue.put(result)
                    else:
                        logging.error(
                            f"Unknown database operation: {operation_type}")
                        if result_queue:
                            result_queue.put(None)
                else:
                    logging.warning(
                        f"Database not initialized. Skipping operation: {operation_type}")
                    if result_queue:
                        result_queue.put(None)
            except Exception as e:
                logging.error(
                    f"Database operation '{operation_type}' failed: {e}")
                if result_queue:
                    result_queue.put(None)
            finally:
                self.db_queue.task_done()

    def send_db_command(self, operation_name, args=(), kwargs=None, expect_result=False):
        """Helper to send commands to the DB thread and optionally wait for a result."""
        if kwargs is None:
            kwargs = {}
        result_queue = queue.Queue() if expect_result else None
        self.db_queue.put((operation_name, args, kwargs, result_queue))
        if expect_result:
            return result_queue.get()
        return None

    def create_tray_icon(self):
        """Creates a system tray icon with a default image and loads font for dynamic updates."""
        self.tray_icon = None

        if not PIL_AVAILABLE:
            logging.warning(
                "Tray icon creation skipped: Pillow not available.")
            messagebox.showwarning(
                "Tray Icon Error", "Failed to create system tray icon. The 'Pillow' library is not installed. Please install it using 'pip install Pillow' for full functionality.")
            return

        try:
            # Create a base image for the tray icon (e.g., a white square)
            self.base_tray_image = Image.new(
                "RGB", (16, 16), color=(255, 255, 255))
            draw = ImageDraw.Draw(self.base_tray_image)
            # Optionally draw a small 'W' or other indicator
            draw.text((2, 0), "W", fill=(0, 0, 0))  # Initial 'W'

            # Try to load a font for drawing time. Adjust path/name as needed.
            # Common font paths might vary by OS. Using a generic name.
            try:
                self.tray_font = ImageFont.truetype(
                    "arial.ttf", 10)  # Adjust size as needed
            except IOError:
                logging.warning(
                    "Could not load 'arial.ttf', using default Pillow font for tray icon.")
                self.tray_font = ImageFont.load_default()

            menu = (
                pystray.MenuItem("Open", self.show_window),
                pystray.MenuItem("Exit", self.exit_app),
            )

            self.tray_icon = pystray.Icon(
                "WorkTracker", self.base_tray_image, "WorkTracker", menu)

            # Run the tray icon in a separate thread
            # pystray.Icon.run_detached() is generally preferred for non-blocking
            # but using threading.Thread for consistency with existing pattern.
            thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            thread.start()
            logging.info("Tray icon created successfully.")
        except Exception as e:
            logging.error(
                f"Failed to create tray icon: {e}. Ensure Pillow is correctly installed and font is accessible.", exc_info=True)
            self.tray_icon = None
            messagebox.showwarning(
                "Tray Icon Error", "Failed to create system tray icon. An unexpected error occurred. Please ensure 'Pillow' library is correctly installed (pip install Pillow).")

    def _update_tray_icon_time(self, time_str):
        """Updates the tray icon with the given time string."""
        if not self.tray_icon or not PIL_AVAILABLE:
            return

        try:
            # Create a new image for each update to avoid drawing artifacts
            img = Image.new("RGB", (16, 16), color=(
                255, 255, 255))  # White background
            draw = ImageDraw.Draw(img)

            # Draw the time string. Adjust coordinates and font size for 16x16.
            # For 16x16, "MM:SS" is often more legible than "HH:MM:SS"
            # Text position might need fine-tuning based on font and string length
            text_color = (0, 0, 0)  # Black text

            # A common approach for centering text in a small icon:
            # Calculate text size
            text_width, text_height = draw.textsize(
                time_str, font=self.tray_font)
            # Calculate position to center
            x = (16 - text_width) / 2
            y = (16 - text_height) / 2

            draw.text((x, y), time_str, font=self.tray_font, fill=text_color)

            self.tray_icon.icon = img
        except Exception as e:
            logging.error(
                f"Error updating tray icon with time '{time_str}': {e}", exc_info=True)

    def show_window(self, icon=None, item=None):
        """Shows the main window."""
        self.root.deiconify()
        if self.tray_icon:
            # When window is opened, revert tray icon to base image
            if self.base_tray_image:
                self.tray_icon.icon = self.base_tray_image
            self.tray_icon.visible = False

    def hide_window(self):
        """Hides the main window and creates a tray icon."""
        self.root.withdraw()
        if self.tray_icon:
            self.tray_icon.visible = True
            # When window is hidden, start updating tray icon with time
            if self.is_running and not self.is_paused:
                # Reset timer for immediate update
                self.last_tray_update_time = datetime.datetime.now()
                self.update_stopwatch()  # Ensure stopwatch update loop is running

    def exit_app(self, icon=None, item=None):
        """Exits the application and stops any running session."""
        try:
            if self.is_running:
                self.stop_session()
            if self.tray_icon:
                self.tray_icon.stop()  # Stop the pystray icon thread
            self.root.destroy()
            self.db_queue.join()
            logging.info("Application exited from tray.")
        except Exception as e:
            logging.error(f"Error exiting application: {e}")

    def get_available_categories(self):
        """Gets categories from db."""
        all_categories = self.send_db_command(
            'get_all_categories', expect_result=True)
        if all_categories is None:
            all_categories = []
        return all_categories

    def update_category_dropdown(self):
        """Update the category dropdown with available categories."""
        available_categories = self.get_available_categories()
        self.category_dropdown['values'] = available_categories
        if available_categories:
            # If there are categories, try to set the first one or the loaded default
            if not self.category_var.get() or self.category_var.get() not in available_categories:
                self.category_var.set(available_categories[0])
        else:
            self.category_var.set("No Categories")

    def load_default_category_setting(self):
        """Loads the default category from settings and sets it in the dropdown."""
        default_category = self.send_db_command(
            'get_setting', ('default_category',), expect_result=True)
        # Get current available categories
        available_categories = self.get_available_categories()

        if default_category and default_category in available_categories:
            self.category_var.set(default_category)
            logging.info(
                f"Default category '{default_category}' loaded and set.")
        elif default_category and default_category not in available_categories:
            logging.warning(
                f"Default category '{default_category}' found in settings but no longer exists. Resetting.")
            self.send_db_command(
                'set_setting', ('default_category', None), expect_result=False)
            self.update_category_dropdown()  # Re-set to first available or "No Categories"
        else:
            logging.info("No default category setting found or it's invalid.")
            # If no default is set or it's invalid, ensure dropdown shows first available or "No Categories"
            if available_categories:
                self.category_var.set(available_categories[0])
            else:
                self.category_var.set("No Categories")

    def open_default_category_settings(self):
        """Opens a dialog to set the default category."""
        settings_dialog = tk.Toplevel(self.root)
        settings_dialog.title("Set Default Category")
        settings_dialog.transient(self.root)
        settings_dialog.grab_set()

        form_frame = ttk.Frame(settings_dialog, padding=10)
        form_frame.pack(padx=10, pady=10)

        ttk.Label(form_frame, text="Select Default Category:").grid(
            row=0, column=0, sticky="w", pady=5)

        # Get all categories from DB, plus an explicit "None" option
        current_categories = self.send_db_command(
            'get_all_categories', expect_result=True)
        category_options = ["None"] + \
            (current_categories if current_categories else [])

        self.default_category_setting_var = tk.StringVar()

        # Get current default setting from DB for pre-selection
        current_default = self.send_db_command(
            'get_setting', ('default_category',), expect_result=True)
        if current_default and current_default in category_options:
            self.default_category_setting_var.set(current_default)
        else:
            # Default to "None" if no setting or invalid
            self.default_category_setting_var.set("None")

        default_category_dropdown = ttk.Combobox(
            form_frame, textvariable=self.default_category_setting_var, values=category_options, state="readonly"
        )
        default_category_dropdown.grid(
            row=0, column=1, sticky="ew", padx=5, pady=5)

        button_frame = ttk.Frame(settings_dialog, padding=5)
        button_frame.pack(pady=10)

        save_button = ttk.Button(button_frame, text="Save",
                                 command=lambda: self.save_default_category_setting(settings_dialog))
        save_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(
            button_frame, text="Cancel", command=settings_dialog.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=5)

        settings_dialog.wait_window()

    def save_default_category_setting(self, dialog):
        """Saves the selected default category to the database."""
        selected_default = self.default_category_setting_var.get()

        # Store None if "None" is selected
        value_to_save = None if selected_default == "None" else selected_default

        success = self.send_db_command(
            'set_setting', ('default_category', value_to_save), expect_result=True)
        if success:
            messagebox.showinfo(
                "Settings Saved", "Default category setting updated.")
            self.load_default_category_setting()  # Reload to update main dropdown
            dialog.destroy()
        else:
            messagebox.showerror(
                "Error", "Failed to save default category setting.")

    def on_category_select(self, event):
        """Handles category selection."""
        selected_category = self.category_var.get()
        logging.info(f"Category selected: {selected_category}")

    def add_category(self):
        """Adds a new category"""
        try:
            new_category = simpledialog.askstring(
                "Add Category", "Enter new category name:")
            if new_category and new_category.strip():
                new_category = new_category.strip()
                success = self.send_db_command(
                    'insert_category', (new_category,), expect_result=True)
                if success:
                    self.update_category_dropdown()
                    self.category_var.set(new_category)
                    messagebox.showinfo(
                        "Success", f"Category '{new_category}' added.")
                else:
                    messagebox.showerror(
                        "Error", f"Failed to add category '{new_category}'. It might already exist.")
        except Exception as e:
            logging.error(f"Error adding category: {e}")
            messagebox.showerror(
                "Error", f"An error occurred while adding category: {e}")

    def delete_category(self):
        """Deletes the currently selected category from the database."""
        try:
            selected_category = self.category_var.get()
            if not selected_category or selected_category == "No Categories":
                messagebox.showinfo("Info", "No category selected to delete.")
                return

            if messagebox.askyesno("Confirm Delete", f"Are you sure you want to permanently delete category '{selected_category}'?\n\nAll existing sessions with this category will be set to 'Uncategorized'."):
                success = self.send_db_command(
                    'delete_category_from_db', (selected_category,), expect_result=True)
                if success:
                    self.update_category_dropdown()
                    messagebox.showinfo(
                        "Category Deleted", f"Category '{selected_category}' and its associated sessions updated to 'Uncategorized'.")
                    self.load_default_category_setting()  # Check if default category was deleted
                else:
                    messagebox.showerror(
                        "Error", f"Failed to delete category '{selected_category}'.")
        except Exception as e:
            logging.error(f"Error deleting category: {e}")
            messagebox.showerror(
                "Error", f"An error occurred while deleting category: {e}")

    def rename_category(self):
        """Renames the currently selected category in the database."""
        try:
            old_category = self.category_var.get()
            if not old_category or old_category == "No Categories":
                messagebox.showinfo("Rename Category",
                                    "Please select a category to rename.")
                return

            new_category = simpledialog.askstring(
                "Rename Category", f"Enter new name for '{old_category}':")

            if new_category and new_category.strip():
                new_category = new_category.strip()
                if old_category == new_category:
                    messagebox.showinfo(
                        "Rename Category", "Old and new category names are the same. No change made.")
                    return

                success = self.send_db_command(
                    'rename_category', (old_category, new_category), expect_result=True)
                if success:
                    self.update_category_dropdown()
                    self.category_var.set(new_category)
                    self.load_default_category_setting()  # Check if default category was renamed
                    messagebox.showinfo(
                        "Rename Category", f"Category '{old_category}' renamed to '{new_category}'.")
                else:
                    messagebox.showerror(
                        "Error", f"Failed to rename category '{old_category}'. New name might already exist.")
        except Exception as e:
            logging.error(f"Error renaming category: {e}")
            messagebox.showerror(
                "Error", f"An error occurred while renaming category: {e}")

    def update_stopwatch(self):
        """Update the stopwatch display and potentially the tray icon."""
        if self.stopwatch_running and not self.is_paused:
            current_time = datetime.datetime.now()
            elapsed = current_time - self.start_time
            self.elapsed_time = elapsed.total_seconds()

            if self.root.winfo_ismapped():
                # Update main window stopwatch every 10ms
                formatted_time = time.strftime("%H:%M:%S", time.gmtime(
                    self.elapsed_time)) + f".{int((self.elapsed_time % 1) * 1000):03}"
                self.stopwatch_label.config(text=formatted_time)
            elif self.tray_icon and self.tray_font:  # If window is hidden and tray icon exists
                # Update tray icon less frequently (e.g., every second)
                if (current_time - self.last_tray_update_time).total_seconds() >= 1:
                    minutes, seconds = divmod(int(self.elapsed_time), 60)
                    hours, minutes = divmod(minutes, 60)

                    # Format as HH:MM or MM:SS depending on duration for better legibility
                    if hours > 0:
                        tray_time_str = f"{hours:02d}:{minutes:02d}"
                    else:
                        tray_time_str = f"{minutes:02d}:{seconds:02d}"

                    self._update_tray_icon_time(tray_time_str)
                    self.last_tray_update_time = current_time

        # Schedule the next update regardless of window state or tray update
        self.root.after(10, self.update_stopwatch)

    def toggle_pause_resume(self):
        """Toggles the session between paused and resumed states."""
        if self.is_running:  # Only allow pause/resume if a session is active
            if not self.is_paused:
                # Pause the session
                self.is_paused = True
                self.stopwatch_running = False
                self.pause_start_time = datetime.datetime.now()  # Record pause start time
                self.pause_button.config(text="Resume")
                self.start_button.config(
                    state=tk.DISABLED)  # Keep start disabled
                self.stop_button.config(state=tk.NORMAL)  # Keep stop enabled

                # When paused, revert tray icon to base image (no time)
                if self.tray_icon and self.base_tray_image:
                    self.tray_icon.icon = self.base_tray_image

                logging.info("Session paused.")
            else:
                # Resume the session
                self.is_paused = False
                self.stopwatch_running = True
                # Adjust start_time to account for the pause duration
                if self.pause_start_time:
                    pause_duration = datetime.datetime.now() - self.pause_start_time
                    self.start_time += pause_duration
                    self.pause_start_time = None  # Reset pause start time
                self.pause_button.config(text="Pause")
                self.start_button.config(
                    state=tk.DISABLED)  # Keep start disabled
                self.stop_button.config(state=tk.NORMAL)  # Keep stop enabled
                self.update_stopwatch()  # Restart the stopwatch update loop
                logging.info("Session resumed.")
        else:
            messagebox.showwarning(
                "Warning", "No session is currently running to pause/resume.")

    def start_session(self):
        try:
            if self.category_var.get() == "No Categories":
                messagebox.showwarning(
                    "Warning", "Please add a category before starting a session.")
                return

            self.start_time = datetime.datetime.now()
            self.is_running = True
            self.is_paused = False  # Ensure not paused when starting
            self.pause_start_time = None  # Reset pause time

            # Enable pause and stop buttons, disable start button
            self.start_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.NORMAL)
            logging.info(
                "Buttons state updated: Start=DISABLED, Pause=NORMAL, Stop=NORMAL")

            self.stopwatch_running = True
            self.update_stopwatch()
            category = self.category_var.get()
            task = self.task_text.get("1.0", tk.END).strip()
            logging.info(
                f"Attempting to start session with category: {category}, task: {task}")

            self.current_session_id = self.send_db_command(
                'insert_session', (self.start_time, None, category, task), expect_result=True)

            if self.current_session_id is None:
                logging.error(
                    "Failed to get session ID from database. Database insertion likely failed.")
                messagebox.showerror(
                    "Error", "Failed to start session. Database error. Check app.log for details.")
                # Revert button states if DB insertion failed
                self.stopwatch_running = False
                self.is_running = False
                self.start_button.config(state=tk.NORMAL)
                self.pause_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.DISABLED)
                logging.info(
                    "Buttons state reverted due to DB error: Start=NORMAL, Pause=DISABLED, Stop=DISABLED")
                return

            logging.info(
                f"Session started successfully with category: {category}, ID: {self.current_session_id}")
        except Exception as e:
            # Log full traceback
            logging.error(f"Error starting session: {e}", exc_info=True)
            messagebox.showerror(
                "Error", f"An unexpected error occurred while starting the session: {e}. Check app.log for details.")
            # Ensure buttons are reset even for unexpected errors
            self.stopwatch_running = False
            self.is_running = False
            self.start_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            logging.info(
                "Buttons state reverted due to unexpected error: Start=NORMAL, Pause=DISABLED, Stop=DISABLED")

    def stop_session(self):
        try:
            if self.current_session_id is None:
                logging.warning(
                    "Attempted to stop session when no session was running.")
                return

            self.end_time = datetime.datetime.now()
            self.is_running = False
            self.is_paused = False  # Ensure not paused when stopping
            self.pause_start_time = None  # Reset pause time
            self.start_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.DISABLED)  # Disable pause button
            self.stop_button.config(state=tk.DISABLED)
            self.stopwatch_running = False
            task = self.task_text.get("1.0", tk.END).strip()

            self.send_db_command(
                'update_session', (self.current_session_id, self.end_time, task), expect_result=False)  # No need to expect result here

            self.task_text.delete("1.0", tk.END)
            self.display_session_duration()
            self.current_session_id = None
            logging.info("Session stopped")

            # When session stops, revert tray icon to base image
            if self.tray_icon and self.base_tray_image:
                self.tray_icon.icon = self.base_tray_image

        except Exception as e:
            logging.error(f"Error stopping session: {e}")
            messagebox.showerror(
                "Error", f"An error occurred while stopping the session: {e}")

    def display_session_duration(self):
        try:
            if self.start_time and self.end_time:
                duration = self.end_time - self.start_time
                messagebox.showinfo("Session duration",
                                    f"Session duration: {duration}")
                logging.info(f"Session duration displayed: {duration}")
            else:
                logging.warning(
                    "Cannot display duration: start or end time missing.")
        except Exception as e:
            logging.error(f"Error displaying session duration: {e}")

    def show_history(self):
        if self.history_window and tk.Toplevel.winfo_exists(self.history_window):
            self.history_window.lift()
            return
        self.history_window = tk.Toplevel(self.root)
        self.history_window.title("Work History")
        self.history_window.geometry("800x600")

        # --- Filter Frame ---
        filter_frame = ttk.Frame(self.history_window, padding=10)
        filter_frame.pack(fill="x", pady=5)

        # Date Range Filter
        ttk.Label(filter_frame, text="Date Range:").grid(
            row=0, column=0, padx=5, pady=2, sticky="w")
        self.history_date_range_var = tk.StringVar(self.history_window)
        self.history_date_range_var.set("All Time")
        date_range_options = ["All Time", "Last 7 Days",
                              "Last 30 Days", "This Month", "This Year"]
        self.history_date_range_dropdown = ttk.Combobox(
            filter_frame, textvariable=self.history_date_range_var, values=date_range_options, state="readonly"
        )
        self.history_date_range_dropdown.grid(
            row=0, column=1, padx=5, pady=2, sticky="ew")

        # Category Filter
        ttk.Label(filter_frame, text="Category:").grid(
            row=0, column=2, padx=5, pady=2, sticky="w")
        self.history_category_var = tk.StringVar(self.history_window)
        self.history_category_var.set("All")
        all_categories_for_filter = ["All"] + self.send_db_command(
            'get_all_categories', expect_result=True) + ["Uncategorized"]
        self.history_category_dropdown = ttk.Combobox(
            filter_frame, textvariable=self.history_category_var, values=all_categories_for_filter, state="readonly"
        )
        self.history_category_dropdown.grid(
            row=0, column=3, padx=5, pady=2, sticky="ew")

        # Text Search
        ttk.Label(filter_frame, text="Search:").grid(
            row=1, column=0, padx=5, pady=2, sticky="w")
        self.history_search_text_var = tk.StringVar(self.history_window)
        self.history_search_entry = ttk.Entry(
            filter_frame, textvariable=self.history_search_text_var)
        self.history_search_entry.grid(
            row=1, column=1, columnspan=2, padx=5, pady=2, sticky="ew")

        # Apply Filters Button
        apply_filters_button = ttk.Button(
            filter_frame, text="Apply Filters", command=self.update_history_display)
        apply_filters_button.grid(row=1, column=3, padx=5, pady=2, sticky="e")

        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(3, weight=1)

        # --- Treeview for History Display ---
        self.history_tree = ttk.Treeview(self.history_window, columns=(
            "ID", "Start Time", "End Time", "Category", "Notes"), show="headings")
        self.history_tree.heading("ID", text="ID")
        self.history_tree.heading("Start Time", text="Start Time")
        self.history_tree.heading("End Time", text="End Time")
        self.history_tree.heading("Category", text="Category")
        self.history_tree.heading("Notes", text="Notes")

        self.history_tree.column("ID", width=50, stretch=tk.NO)
        self.history_tree.column("Start Time", width=150, stretch=tk.NO)
        self.history_tree.column("End Time", width=150, stretch=tk.NO)
        self.history_tree.column("Category", width=100, stretch=tk.NO)
        self.history_tree.column("Notes", stretch=tk.YES)

        self.history_tree.pack(expand=True, fill="both", padx=10, pady=10)

        # --- Buttons for History Actions ---
        history_action_frame = ttk.Frame(self.history_window, padding=5)
        history_action_frame.pack(fill="x", pady=5)

        edit_session_button = ttk.Button(
            history_action_frame, text="Edit Selected Session", command=self.edit_selected_session)
        edit_session_button.pack(side=tk.RIGHT, padx=5)

        export_data_button = ttk.Button(
            history_action_frame, text="Export Data", command=self.export_data)
        export_data_button.pack(side=tk.RIGHT, padx=5)

        # Context Menu for Treeview (Right-click to edit)
        self.history_tree.bind("<Button-3>", self.show_history_context_menu)
        self.history_context_menu = tk.Menu(self.history_window, tearoff=0)
        self.history_context_menu.add_command(
            label="Edit Session", command=self.edit_selected_session)
        self.history_context_menu.add_command(
            label="Export Selected Data", command=self.export_data)

        # Initial display of history
        self.update_history_display()

    def show_history_context_menu(self, event):
        """Displays a context menu when right-clicking on the history treeview."""
        try:
            self.history_tree.selection_set(
                self.history_tree.identify_row(event.y))
            self.history_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.history_context_menu.grab_release()

    def edit_selected_session(self):
        """Opens a dialog to edit the details of the selected session."""
        selected_item = self.history_tree.focus()
        if not selected_item:
            messagebox.showinfo(
                "Edit Session", "Please select a session to edit.")
            return

        session_id = self.history_tree.item(selected_item, 'values')[0]
        session_details = self.send_db_command(
            'get_session_by_id', (session_id,), expect_result=True)

        if not session_details:
            messagebox.showerror(
                "Error", "Could not retrieve session details.")
            return

        s_id, s_start_time_str, s_end_time_str, s_category, s_notes = session_details

        edit_dialog = tk.Toplevel(self.root)
        edit_dialog.title(f"Edit Session ID: {s_id}")
        edit_dialog.transient(self.root)
        edit_dialog.grab_set()

        form_frame = ttk.Frame(edit_dialog, padding=10)
        form_frame.pack(padx=10, pady=10)

        ttk.Label(form_frame, text="Start Time (YYYY-MM-DD HH:MM:SS.ffffff):").grid(
            row=0, column=0, sticky="w", pady=2)
        self.edit_start_time_var = tk.StringVar(
            value=s_start_time_str if s_start_time_str else "")
        ttk.Entry(form_frame, textvariable=self.edit_start_time_var, width=35).grid(
            row=0, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(form_frame, text="End Time (YYYY-MM-DD HH:MM:SS.ffffff):").grid(
            row=1, column=0, sticky="w", pady=2)
        self.edit_end_time_var = tk.StringVar(
            value=s_end_time_str if s_end_time_str else "")
        ttk.Entry(form_frame, textvariable=self.edit_end_time_var, width=35).grid(
            row=1, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(form_frame, text="Category:").grid(
            row=2, column=0, sticky="w", pady=2)
        self.edit_category_var = tk.StringVar(
            value=s_category if s_category else "Uncategorized")
        edit_categories = self.send_db_command(
            'get_all_categories', expect_result=True) + ["Uncategorized"]
        self.edit_category_dropdown = ttk.Combobox(
            form_frame, textvariable=self.edit_category_var, values=edit_categories, state="readonly"
        )
        self.edit_category_dropdown.grid(
            row=2, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(form_frame, text="Notes:").grid(
            row=3, column=0, sticky="nw", pady=2)
        self.edit_notes_text = tk.Text(form_frame, height=4, width=30)
        self.edit_notes_text.grid(row=3, column=1, sticky="ew", padx=5, pady=2)
        self.edit_notes_text.insert(tk.END, s_notes if s_notes else "")

        button_frame = ttk.Frame(edit_dialog, padding=5)
        button_frame.pack(pady=10)

        save_button = ttk.Button(button_frame, text="Save Changes",
                                 command=lambda: self.save_edited_session(edit_dialog, s_id))
        save_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(
            button_frame, text="Cancel", command=edit_dialog.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=5)

        edit_dialog.wait_window()

    def save_edited_session(self, dialog, session_id):
        """Saves the edited session details to the database."""
        try:
            new_start_time_str = self.edit_start_time_var.get().strip()
            new_end_time_str = self.edit_end_time_var.get().strip()
            new_category = self.edit_category_var.get()
            new_notes = self.edit_notes_text.get("1.0", tk.END).strip()

            new_start_time = None
            new_end_time = None

            time_formats = ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']

            if new_start_time_str:
                parsed = False
                for fmt in time_formats:
                    try:
                        new_start_time = datetime.datetime.strptime(
                            new_start_time_str, fmt)
                        parsed = True
                        break
                    except ValueError:
                        continue
                if not parsed:
                    messagebox.showerror(
                        "Input Error", "Invalid Start Time format. Use Jamboree-MM-DD HH:MM:SS or Jamboree-MM-DD HH:MM:SS.ffffff")
                    return
            else:
                messagebox.showerror(
                    "Input Error", "Start Time cannot be empty.")
                return

            if new_end_time_str:
                parsed = False
                for fmt in time_formats:
                    try:
                        new_end_time = datetime.datetime.strptime(
                            new_end_time_str, fmt)
                        parsed = True
                        break
                    except ValueError:
                        continue
                if not parsed:
                    messagebox.showerror(
                        "Input Error", "Invalid End Time format. Use Jamboree-MM-DD HH:MM:SS or Jamboree-MM-DD HH:MM:SS.ffffff")
                    return

            if new_start_time and new_end_time and new_start_time > new_end_time:
                messagebox.showerror(
                    "Input Error", "Start Time cannot be after End Time.")
                return

            db_category = new_category if new_category != "Uncategorized" else None

            success = self.send_db_command(
                'update_full_session',
                (session_id, new_start_time, new_end_time, db_category, new_notes),
                expect_result=True
            )

            if success:
                messagebox.showinfo("Success", "Session updated successfully!")
                dialog.destroy()
                self.update_history_display()
            else:
                messagebox.showerror("Error", "Failed to update session.")

        except Exception as e:
            logging.error(f"Error saving edited session: {e}")
            messagebox.showerror(
                "Error", f"An error occurred while saving changes: {e}")

    def export_data(self):
        """Allows users to export filtered history data to CSV or Excel."""
        items = self.history_tree.get_children()
        if not items:
            messagebox.showinfo(
                "Export Data", "No data available in the history view to export.")
            return

        data_to_export = []
        for item in items:
            data_to_export.append(self.history_tree.item(item, 'values'))

        columns = ["ID", "Start Time", "End Time", "Category", "Notes"]
        df = pd.DataFrame(data_to_export, columns=columns)

        file_types = [
            ("CSV files", "*.csv"),
            ("Excel files", "*.xlsx"),
            ("All files", "*.*")
        ]

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=file_types,
            title="Save Work History As"
        )

        if file_path:
            try:
                if file_path.lower().endswith('.csv'):
                    df.to_csv(file_path, index=False)
                    messagebox.showinfo(
                        "Export Success", f"Data successfully exported to CSV:\n{file_path}")
                elif file_path.lower().endswith('.xlsx'):
                    df.to_excel(file_path, index=False)
                    messagebox.showinfo(
                        "Export Success", f"Data successfully exported to Excel:\n{file_path}")
                else:
                    messagebox.showerror(
                        "Export Error", "Unsupported file format. Please choose .csv or .xlsx.")
            except Exception as e:
                logging.error(f"Error exporting data: {e}")
                messagebox.showerror(
                    "Export Error", f"An error occurred during export:\n{e}")
        else:
            messagebox.showinfo("Export Cancelled", "Data export cancelled.")

    def update_history_display(self):
        """Updates the history treeview based on selected filters."""
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        date_range = self.history_date_range_var.get()
        category = self.history_category_var.get()
        search_text = self.history_search_text_var.get().strip()

        start_date = None
        end_date = None
        now = datetime.datetime.now()

        if date_range == "Last 7 Days":
            start_date = now - datetime.timedelta(days=7)
        elif date_range == "Last 30 Days":
            start_date = now - datetime.timedelta(days=30)
        elif date_range == "This Month":
            start_date = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0)
        elif date_range == "This Year":
            start_date = now.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        sessions = self.send_db_command(
            'get_filtered_sessions',
            (start_date, end_date, category, search_text),
            expect_result=True
        )

        if sessions:
            for session in sessions:
                display_session = list(session)
                if display_session[3] is None:
                    display_session[3] = "Uncategorized"
                self.history_tree.insert("", "end", values=display_session)
        else:
            messagebox.showinfo(
                "Work History", "No sessions found matching the filters.")

    def update_stopwatch(self):
        """Update the stopwatch display and potentially the tray icon."""
        if self.stopwatch_running and not self.is_paused:
            current_time = datetime.datetime.now()
            elapsed = current_time - self.start_time
            self.elapsed_time = elapsed.total_seconds()

            if self.root.winfo_ismapped():
                # Update main window stopwatch every 10ms
                formatted_time = time.strftime("%H:%M:%S", time.gmtime(
                    self.elapsed_time)) + f".{int((self.elapsed_time % 1) * 1000):03}"
                self.stopwatch_label.config(text=formatted_time)
            elif self.tray_icon and self.tray_font:  # If window is hidden and tray icon exists
                # Update tray icon less frequently (e.g., every second)
                if (current_time - self.last_tray_update_time).total_seconds() >= 1:
                    minutes, seconds = divmod(int(self.elapsed_time), 60)
                    hours, minutes = divmod(minutes, 60)

                    # Format as HH:MM or MM:SS depending on duration for better legibility
                    if hours > 0:
                        tray_time_str = f"{hours:02d}:{minutes:02d}"
                    else:
                        tray_time_str = f"{minutes:02d}:{seconds:02d}"

                    self._update_tray_icon_time(tray_time_str)
                    self.last_tray_update_time = current_time

        # Schedule the next update regardless of window state or tray update
        self.root.after(10, self.update_stopwatch)

    def start_session(self):
        try:
            if self.category_var.get() == "No Categories":
                messagebox.showwarning(
                    "Warning", "Please add a category before starting a session.")
                return

            self.start_time = datetime.datetime.now()
            self.is_running = True
            self.is_paused = False  # Ensure not paused when starting
            self.pause_start_time = None  # Reset pause time

            # Enable pause and stop buttons, disable start button
            self.start_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.NORMAL)
            logging.info(
                "Buttons state updated: Start=DISABLED, Pause=NORMAL, Stop=NORMAL")

            self.stopwatch_running = True
            self.update_stopwatch()
            category = self.category_var.get()
            task = self.task_text.get("1.0", tk.END).strip()
            logging.info(
                f"Attempting to start session with category: {category}, task: {task}")

            self.current_session_id = self.send_db_command(
                'insert_session', (self.start_time, None, category, task), expect_result=True)

            if self.current_session_id is None:
                logging.error(
                    "Failed to get session ID from database. Database insertion likely failed.")
                messagebox.showerror(
                    "Error", "Failed to start session. Database error. Check app.log for details.")
                # Revert button states if DB insertion failed
                self.stopwatch_running = False
                self.is_running = False
                self.start_button.config(state=tk.NORMAL)
                self.pause_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.DISABLED)
                logging.info(
                    "Buttons state reverted due to DB error: Start=NORMAL, Pause=DISABLED, Stop=DISABLED")
                return

            logging.info(
                f"Session started successfully with category: {category}, ID: {self.current_session_id}")
        except Exception as e:
            # Log full traceback
            logging.error(f"Error starting session: {e}", exc_info=True)
            messagebox.showerror(
                "Error", f"An unexpected error occurred while starting the session: {e}. Check app.log for details.")
            # Ensure buttons are reset even for unexpected errors
            self.stopwatch_running = False
            self.is_running = False
            self.start_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            logging.info(
                "Buttons state reverted due to unexpected error: Start=NORMAL, Pause=DISABLED, Stop=DISABLED")

    def stop_session(self):
        try:
            if self.current_session_id is None:
                logging.warning(
                    "Attempted to stop session when no session was running.")
                return

            self.end_time = datetime.datetime.now()
            self.is_running = False
            self.is_paused = False  # Ensure not paused when stopping
            self.pause_start_time = None  # Reset pause time
            self.start_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.DISABLED)  # Disable pause button
            self.stop_button.config(state=tk.DISABLED)
            self.stopwatch_running = False
            task = self.task_text.get("1.0", tk.END).strip()

            self.send_db_command(
                'update_session', (self.current_session_id, self.end_time, task), expect_result=False)  # No need to expect result here

            self.task_text.delete("1.0", tk.END)
            self.display_session_duration()
            self.current_session_id = None
            logging.info("Session stopped")

            # When session stops, revert tray icon to base image
            if self.tray_icon and self.base_tray_image:
                self.tray_icon.icon = self.base_tray_image

        except Exception as e:
            logging.error(f"Error stopping session: {e}")
            messagebox.showerror(
                "Error", f"An error occurred while stopping the session: {e}")

    def display_session_duration(self):
        try:
            if self.start_time and self.end_time:
                duration = self.end_time - self.start_time
                messagebox.showinfo("Session duration",
                                    f"Session duration: {duration}")
                logging.info(f"Session duration displayed: {duration}")
            else:
                logging.warning(
                    "Cannot display duration: start or end time missing.")
        except Exception as e:
            logging.error(f"Error displaying session duration: {e}")

    def show_statistics(self):
        """Displays the statistics window."""
        if self.statistics_window and tk.Toplevel.winfo_exists(self.statistics_window):
            self.statistics_window.lift()
            return

        self.statistics_window = tk.Toplevel(self.root)
        self.statistics_window.title("Statistics")

        all_categories_from_db = self.send_db_command(
            'get_all_categories', expect_result=True)
        if all_categories_from_db is None:
            all_categories_from_db = []
        categories = ["All"] + all_categories_from_db + ["Uncategorized"]

        view_var = tk.StringVar(self.statistics_window)
        view_var.set("Weeks")
        view_dropdown = ttk.Combobox(self.statistics_window, textvariable=view_var, values=[
                                     "Weeks", "Months", "Years"])
        view_dropdown.grid(row=0, column=0, padx=5, pady=5)

        category_var = tk.StringVar(self.statistics_window)
        category_var.set("All")
        category_dropdown = ttk.Combobox(
            self.statistics_window, textvariable=category_var, values=categories)
        category_dropdown.grid(row=0, column=1, padx=5, pady=5)

        self.scorecard_label = ttk.Label(
            self.statistics_window, text="")
        self.scorecard_label.grid(
            row=2, column=0, columnspan=2, padx=5, pady=5)

        def update_stats():
            """Updates the statistics graph and scorecard."""
            view = view_var.get()
            category = category_var.get()

            daily_average = 0.0

            all_sessions_data = self.send_db_command(
                'get_sessions', expect_result=True)

            for widget in self.statistics_window.winfo_children():
                if isinstance(widget, FigureCanvasTkAgg):
                    widget.get_tk_widget().destroy()

            if not all_sessions_data:
                messagebox.showinfo(
                    "Statistics", "No data available for the selected filters.")
                self.scorecard_label.config(
                    text=f"Average Duration ({view[:-1]}ly): {daily_average:.2f} minutes")
                return

            df = pd.DataFrame(all_sessions_data, columns=[
                              "ID", "start_time", "end_time", "category", "notes"])

            if df.empty:
                messagebox.showinfo(
                    "Statistics", "No data available for the selected filters (after DataFrame creation).")
                self.scorecard_label.config(
                    text=f"Average Duration ({view[:-1]}ly): {daily_average:.2f} minutes")
                return

            # Data preparation - Use format='mixed' for robust datetime parsing
            df['start_time'] = pd.to_datetime(df['start_time'], format='mixed')
            df['end_time'] = pd.to_datetime(df['end_time'], format='mixed')
            df['duration'] = (df['end_time'] - df['start_time']
                              ).dt.total_seconds()/60

            df['category'] = df['category'].fillna('Uncategorized')

            if category != "All":
                df = df[df['category'] == category]
                if df.empty:
                    messagebox.showinfo(
                        "Statistics", "No data available for the selected category.")
                    self.scorecard_label.config(
                        text=f"Average Duration ({view[:-1]}ly): {daily_average:.2f} minutes")
                    return

            now = datetime.datetime.now()
            grouped = pd.Series([])

            if view == "Weeks":
                start_of_week = now - datetime.timedelta(days=now.weekday())
                df_filtered = df[df['start_time'] >= start_of_week]
                df_filtered['day'] = df_filtered['start_time'].dt.day_name()
                all_days = ['Monday', 'Tuesday', 'Wednesday',
                            'Thursday', 'Friday', 'Saturday', 'Sunday']
                grouped = df_filtered.groupby(
                    'day')['duration'].sum().reindex(all_days, fill_value=0)
                daily_average = grouped.mean()

            elif view == "Months":
                df_filtered = df[(df['start_time'].dt.month == now.month) & (
                    df['start_time'].dt.year == now.year)]
                df_filtered['day'] = df_filtered['start_time'].dt.day
                days_in_month = pd.date_range(
                    start=now.replace(day=1), end=now).day
                grouped = df_filtered.groupby('day')['duration'].sum().reindex(
                    days_in_month, fill_value=0)
                daily_average = grouped.mean()

            elif view == "Years":
                df_filtered = df[df['start_time'].dt.year == now.year]
                df_filtered['month'] = df_filtered['start_time'].dt.month_name()
                all_months = ['January', 'February', 'March', 'April', 'May', 'June',
                              'July', 'August', 'September', 'October', 'November', 'December']
                grouped = df_filtered.groupby(
                    'month')['duration'].sum().reindex(all_months, fill_value=0)
                daily_average = grouped.mean()

            if not grouped.empty and grouped.sum() > 0:
                fig, ax = plt.subplots(figsize=(8, 4))
                grouped.plot(kind='bar', ax=ax)
                ax.set_ylabel("Minutes")
                ax.set_title(f"{view} Statistics for {category} Category")
                fig.tight_layout()

                canvas = FigureCanvasTkAgg(fig, master=self.statistics_window)
                canvas.draw()
                canvas.get_tk_widget().grid(row=1, column=0, columnspan=2, padx=5, pady=5)
            else:
                messagebox.showinfo(
                    "Statistics", "No work data to display for the selected period and category.")
                daily_average = 0.0

            self.scorecard_label.config(
                text=f"Average Duration ({view[:-1]}ly): {daily_average:.2f} minutes")

        update_stats()
        view_dropdown.bind("<<ComboboxSelected>>",
                           lambda event: update_stats())
        category_dropdown.bind("<<ComboboxSelected>>",
                               lambda event: update_stats())


class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.connect()

    def connect(self):
        """Establishes connection to the database."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            logging.info(f"Database connected at {self.db_path}")
        except sqlite3.Error as e:
            logging.error(f"Error connecting to database: {e}")
            self.conn = None
            self.cursor = None

    def create_tables(self):
        """Creates both sessions, categories, and settings tables."""
        if not self.conn:
            logging.error("Cannot create tables: No database connection.")
            return

        self.cursor.execute(
            """
                CREATE TABLE IF NOT EXISTS sessions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TEXT,
                    end_time TEXT,
                    category TEXT,
                    notes TEXT
                )
            """
        )
        logging.info("Sessions table checked/created.")

        self.cursor.execute(
            """
                CREATE TABLE IF NOT EXISTS categories(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            """
        )
        self.conn.commit()
        logging.info("Categories table checked/created.")

        # New: Create settings table for key-value pairs
        self.cursor.execute(
            """
                CREATE TABLE IF NOT EXISTS settings(
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
        )
        self.conn.commit()
        logging.info("Settings table checked/created.")

        # Insert default categories if the categories table is empty
        self.cursor.execute("SELECT COUNT(*) FROM categories")
        if self.cursor.fetchone()[0] == 0:
            default_categories = ["Work", "Skill", "School"]
            for category in default_categories:
                try:
                    self.cursor.execute(
                        "INSERT INTO categories (name) VALUES (?)", (category,))
                    self.conn.commit()
                    logging.info(
                        f"Default category '{category}' added to categories table.")
                except sqlite3.IntegrityError:
                    logging.warning(
                        f"Default category '{category}' already exists, skipping.")
                except Exception as e:
                    logging.error(
                        f"Error adding default category '{category}': {e}")
            logging.info("Default categories ensured in dedicated table.")

    def insert_session(self, start_time, end_time, category, notes):
        try:
            start_time_str = start_time.strftime(
                '%Y-%m-%d %H:%M:%S.%f') if start_time else None
            end_time_str = end_time.strftime(
                '%Y-%m-%d %H:%M:%S.%f') if end_time else None

            self.cursor.execute("""
                INSERT INTO sessions (start_time, end_time, category, notes) VALUES (?,?,?,?)
                """, (start_time_str, end_time_str, category, notes))
            self.conn.commit()
            last_id = self.cursor.lastrowid
            logging.info(f"Session inserted. ID: {last_id}")
            return last_id
        except Exception as e:
            logging.error(
                f"Error inserting session into DB: {e}", exc_info=True)
            return None

    def update_session(self, session_id, end_time, notes):
        try:
            end_time_str = end_time.strftime(
                '%Y-%m-%d %H:%M:%S.%f') if end_time else None

            self.cursor.execute("""
                UPDATE sessions
                SET end_time = ?, notes = ?
                WHERE id = ?
            """, (end_time_str, notes, session_id))
            self.conn.commit()
            logging.info(f"Session updated. ID: {session_id}")
        except Exception as e:
            logging.error(f"Error updating session: {e}")
            return False  # Indicate failure

    def update_full_session(self, session_id, start_time, end_time, category, notes):
        """Updates all fields of a session in the database."""
        try:
            start_time_str = start_time.strftime(
                '%Y-%m-%d %H:%M:%S.%f') if start_time else None
            end_time_str = end_time.strftime(
                '%Y-%m-%d %H:%M:%S.%f') if end_time else None

            self.cursor.execute("""
                UPDATE sessions
                SET start_time = ?, end_time = ?, category = ?, notes = ?
                WHERE id = ?
            """, (start_time_str, end_time_str, category, notes, session_id))
            self.conn.commit()
            logging.info(f"Full session updated. ID: {session_id}")
            return True
        except Exception as e:
            logging.error(f"Error updating full session: {e}")
            return False

    def get_session_by_id(self, session_id):
        """Gets a single session by its ID."""
        try:
            self.cursor.execute(
                "SELECT id, start_time, end_time, category, notes FROM sessions WHERE id = ?", (session_id,))
            session = self.cursor.fetchone()
            logging.info(f"Session {session_id} retrieved.")
            return session
        except Exception as e:
            logging.error(f"Error getting session by ID {session_id}: {e}")
            return None

    def get_sessions(self):
        """Gets all sessions from database."""
        try:
            self.cursor.execute(
                "SELECT id, start_time, end_time, category, notes FROM sessions")
            sessions = self.cursor.fetchall()
            logging.info("Sessions retrieved")
            return sessions
        except Exception as e:
            logging.error(f"Error getting sessions: {e}")
            return []

    def get_filtered_sessions(self, start_date=None, end_date=None, category=None, search_text=None):
        """Gets sessions from database based on filters."""
        try:
            query = "SELECT id, start_time, end_time, category, notes FROM sessions WHERE 1=1"
            params = []

            if start_date:
                query += " AND start_time >= ?"
                params.append(start_date.strftime('%Y-%m-%d %H:%M:%S.%f'))
            if end_date:
                query += " AND start_time <= ?"
                if end_date.hour == 0 and end_date.minute == 0 and end_date.second == 0:
                    end_date = end_date.replace(
                        hour=23, minute=59, second=59, microsecond=999999)
                params.append(end_date.strftime('%Y-%m-%d %H:%M:%S.%f'))

            if category and category != "All":
                if category == "Uncategorized":
                    query += " AND category IS NULL"
                else:
                    query += " AND category = ?"
                    params.append(category)

            if search_text:
                search_pattern = f"%{search_text}%"
                query += " AND (notes LIKE ? OR category LIKE ?)"
                params.append(search_pattern)
                params.append(search_pattern)

            query += " ORDER BY start_time DESC"

            self.cursor.execute(query, tuple(params))
            sessions = self.cursor.fetchall()
            logging.info(
                f"Filtered sessions retrieved. Query: {query}, Params: {params}")
            return sessions
        except Exception as e:
            logging.error(f"Error getting filtered sessions: {e}")
            return []

    def get_all_categories(self):
        """Gets all category names from the dedicated categories table."""
        try:
            self.cursor.execute("SELECT name FROM categories ORDER BY name")
            categories = [row[0] for row in self.cursor.fetchall()]
            logging.info("All categories retrieved from dedicated table.")
            return categories
        except Exception as e:
            logging.error(f"Error getting all categories: {e}")
            return []

    def insert_category(self, category_name):
        """Inserts a new category into the dedicated categories table."""
        try:
            self.cursor.execute(
                "INSERT INTO categories (name) VALUES (?)", (category_name,))
            self.conn.commit()
            logging.info(
                f"Category '{category_name}' inserted into dedicated table.")
            return True
        except sqlite3.IntegrityError:
            logging.warning(
                f"Category '{category_name}' already exists in dedicated table.")
            return False
        except Exception as e:
            logging.error(f"Error inserting category '{category_name}': {e}")
            return False

    def rename_category(self, old_category, new_category):
        """Renames a category in the categories table and updates associated sessions."""
        try:
            self.cursor.execute(
                "SELECT 1 FROM categories WHERE name = ? LIMIT 1", (new_category,))
            if self.cursor.fetchone():
                logging.warning(
                    f"Cannot rename '{old_category}' to '{new_category}': New category name already exists.")
                return False

            self.cursor.execute(
                "UPDATE categories SET name = ? WHERE name = ?", (new_category, old_category))
            self.cursor.execute(
                "UPDATE sessions SET category = ? WHERE category = ?", (new_category, old_category))
            self.conn.commit()
            logging.info(
                f"Category '{old_category}' renamed to '{new_category}' and sessions updated.")
            return True
        except Exception as e:
            logging.error(f"Error renaming category: {e}")
            return False

    def delete_category_from_db(self, category_name):
        """Deletes a category from the categories table and updates associated sessions."""
        try:
            self.cursor.execute(
                "UPDATE sessions SET category = NULL WHERE category = ?", (category_name,))
            self.cursor.execute(
                "DELETE FROM categories WHERE name = ?", (category_name,))
            self.conn.commit()
            logging.info(
                f"Category '{category_name}' deleted from categories table and sessions updated.")
            return True
        except Exception as e:
            logging.error(f"Error deleting category '{category_name}': {e}")
            return False

    def get_setting(self, key):
        """Retrieves a setting value by its key."""
        try:
            self.cursor.execute(
                "SELECT value FROM settings WHERE key = ?", (key,))
            result = self.cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logging.error(f"Error getting setting '{key}': {e}")
            return None

    def set_setting(self, key, value):
        """Inserts or updates a setting key-value pair."""
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            self.conn.commit()
            logging.info(f"Setting '{key}' set to '{value}'.")
            return True
        except Exception as e:
            logging.error(f"Error setting setting '{key}': {e}")
            return False

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            logging.info("Database connection closed.")


if __name__ == "__main__":
    root = ThemedTk(theme="arc")
    app = WorkTracker(root)
    root.mainloop()
