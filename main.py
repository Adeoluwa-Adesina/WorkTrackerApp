import tkinter as tk
from tkinter import font as tkfont # Import the font module
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
import json # For parsing supabase config
import uuid # For generating anonymous user IDs if needed before Supabase auth
import webbrowser # New import for opening web links/email clients
import urllib.parse # New import for URL encoding
import sys
import httpx # Import httpx to configure timeouts

# --- Google API Imports ---
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- ttkbootstrap Import ---
try:
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
except ImportError:
    print("ttkbootstrap not found. Please install it using 'pip install ttkbootstrap'")
    # Fallback to standard tkinter if ttkbootstrap is not available
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog, filedialog


# --- Battery Optimization: Logging Config ---
logging.basicConfig(
    filename='work_tracker.log',
    level=logging.WARNING,  # Set to INFO or DEBUG if needed
    format='%(asctime)s - %(levelname)s - %(message)s'
)
 # Import sys to get executable path

# Import Supabase client
try:
    from supabase import create_client, Client, ClientOptions
    SUPABASE_AVAILABLE = True
except ImportError:
    logging.error("Supabase Python library not found. Cloud sync functionality will be disabled. Please install it using 'pip install supabase'.")
    SUPABASE_AVAILABLE = False

# Import dateutil for robust datetime parsing if available
try:
    from dateutil.parser import parse as date_parse
    DATEUTIL_AVAILABLE = True
except ImportError:
    logging.warning("python-dateutil library not found. Datetime parsing for sync might be less robust. Install with 'pip install python-dateutil'.")
    DATEUTIL_AVAILABLE = False


from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


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
    logging.error("Pillow (PIL) library not found. Tray icon functionality will be disabled. Please install it using 'pip install Pillow'.")


class WorkTracker:
    """A desktop application for tracking work sessions."""

    def __init__(self, root):
        """Initialises the WorkTracker Application."""
        # Database setup - Queue for communication with DB thread
        self.db_queue = queue.Queue()
        self.db_thread = threading.Thread(target=self.db_worker, daemon=True)
        self.db_thread.start()

        # Supabase setup for cloud sync
        self.supabase_client = None
        self.supabase_user_id = None # Supabase user ID (from anonymous sign-in)
        self.display_name = None # User-set display name for leaderboard

        # Define Lagos, Nigeria timezone (WAT, UTC+1)
        self.lagos_timezone = datetime.timezone(datetime.timedelta(hours=1), 'WAT')


        # root window settings
        self.root = root
        self.root.title("Work Tracker")
        self.root.geometry("600x750")

        self.start_time = None
        self.is_running = False
        self.elapsed_time = 0
        self.stopwatch_running = False
        self.is_paused = False
        self.pause_start_time = None

        # Tray icon related attributes
        self.tray_icon = None
        self.base_tray_image = None
        self.last_tray_update_time = datetime.datetime.now()
        
        # --- Main Frame ---
        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(expand=True, fill=BOTH)

        # --- Stopwatch Display ---
        self.stopwatch_label = ttk.Label(main_frame, text="00:00:00", font=("Helvetica", 48, "bold"), bootstyle="primary")
        self.stopwatch_label.pack(pady=20)

        # --- Category Management ---
        category_frame = ttk.Labelframe(main_frame, text="Category Management", padding=15)
        category_frame.pack(fill=X, pady=10)
        
        self.category_var = tk.StringVar(root)
        self.category_dropdown = ttk.Combobox(category_frame, textvariable=self.category_var, bootstyle="info")
        self.category_dropdown.pack(side=LEFT, expand=True, fill=X, padx=(0, 10))
        self.category_dropdown.bind("<<ComboboxSelected>>", self.on_category_select)

        self.add_category_button = ttk.Button(category_frame, text="Add", command=self.add_category, bootstyle="success-outline")
        self.add_category_button.pack(side=LEFT, padx=5)
        self.rename_category_button = ttk.Button(category_frame, text="Rename", command=self.rename_category, bootstyle="warning-outline")
        self.rename_category_button.pack(side=LEFT, padx=5)
        self.delete_category_button = ttk.Button(category_frame, text="Delete", command=self.delete_category, bootstyle="danger-outline")
        self.delete_category_button.pack(side=LEFT, padx=5)


        self.end_time = None
        self.current_session_id = None
        self.history_window = None
        self.statistics_window = None


        # Initialize local DB, then categories and Supabase
        self.root.after(100, self.initial_setup)

        # --- Task Entry ---
        task_frame = ttk.Labelframe(main_frame, text="Current Task", padding=15)
        task_frame.pack(fill=BOTH, expand=True, pady=10)
        self.task_text = tk.Text(task_frame, height=4, width=50, relief="flat", bg=self.root.style.colors.inputbg, fg=self.root.style.colors.fg, insertbackground=self.root.style.colors.fg)
        self.task_text.pack(expand=True, fill=BOTH)

        # --- To-Do List ---
        self.setup_todo_list(main_frame)
        
        # --- Control Buttons ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)

        self.start_button = ttk.Button(button_frame, text="Start", command=self.start_session, bootstyle="success", width=10)
        self.start_button.pack(side=LEFT, padx=10)

        self.pause_button = ttk.Button(button_frame, text="Pause", command=self.toggle_pause_resume, state=tk.DISABLED, bootstyle="warning", width=10)
        self.pause_button.pack(side=LEFT, padx=10)

        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_session, state=tk.DISABLED, bootstyle="danger", width=10)
        self.stop_button.pack(side=LEFT, padx=10)

        # --- Menubar for settings ---
        self.menubar = ttk.Menu(root)
        self.root.config(menu=self.menubar)

        settings_menu = ttk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Set Default Category", command=self.open_default_category_settings)
        settings_menu.add_command(label="Set Display Name", command=self.open_display_name_settings)
        settings_menu.add_separator()
        settings_menu.add_command(label="Sync Daily Stats to Cloud", command=self.sync_daily_stats_to_cloud)
        
        tools_menu = ttk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="View History", command=self.show_history)
        tools_menu.add_command(label="View Statistics", command=self.show_statistics)
        tools_menu.add_command(label="Co-work with Friends", command=self.show_co_work_dialog)

        self.menubar.add_command(label="Exit", command=self.exit_app)

        self.create_tray_icon()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        logging.info("WorkTracker application initialized.")

    def initial_setup(self):
        """Called after a short delay to ensure DB thread is ready and Supabase is initialized."""
        user_home = os.path.expanduser("~")
        app_dir = os.path.join(user_home, "WorkTracker")
        if not os.path.exists(app_dir):
            os.makedirs(app_dir)
        db_path = os.path.join(app_dir, "deep_work.db")
        self.db_queue.put(('INIT_DB', (db_path,), None, None))

        # Initialize Supabase client
        self.root.after(150, self._initialize_supabase_client) # Give DB thread a head start

        # Schedule category dropdown update and then default category load and display name load
        self.root.after(200, self.update_category_dropdown)
        self.root.after(300, self.load_default_category_setting)
        self.root.after(400, self.load_display_name_setting)
        self.root.after(500, self.load_local_tasks)
        
        # Schedule the first heartbeat and subsequent heartbeats
        self.root.after(5000, self._schedule_heartbeat) # Initial call after 5 seconds


    def _initialize_supabase_client(self):
        """Initializes Supabase client and signs in anonymously."""
        if not SUPABASE_AVAILABLE:
            logging.warning("Supabase client not initialized: Library not available.")
            return

        supabase_url = None
        supabase_key = None
        
        # Determine base path for config.json (handles both dev and PyInstaller builds)
        if getattr(sys, 'frozen', False): # Check if running as a PyInstaller executable
            # If frozen, config.json is in the same directory as the executable
            base_path = sys._MEIPASS # This is the path to the temporary folder where PyInstaller extracts files
        else:
            # If not frozen, running from source, config.json is in the script's directory
            base_path = os.path.dirname(os.path.abspath(__file__))

        config_path = os.path.join(base_path, 'config.json')

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                supabase_url = config.get('SUPABASE_URL')
                supabase_key = config.get('SUPABASE_KEY')
            logging.info(f"Supabase config loaded from: {config_path}")
        except FileNotFoundError:
            logging.error(f"config.json not found at {config_path}. Cloud sync will be unavailable.")
            ttk.dialogs.Messagebox.show_warning("Supabase config.json not found. Cloud sync features will be unavailable.", "Cloud Sync Error")
            return
        except json.JSONDecodeError:
            logging.error(f"Error decoding config.json at {config_path}. Cloud sync will be unavailable.")
            ttk.dialogs.Messagebox.show_warning("Error reading config.json. Check its format. Cloud sync features will be unavailable.", "Cloud Sync Error")
            return
        except Exception as e:
            logging.error(f"Unexpected error loading config.json: {e}", exc_info=True)
            ttk.dialogs.Messagebox.show_warning("An unexpected error occurred loading config.json. Cloud sync features will be unavailable.", "Cloud Sync Error")
            return

        logging.info(f"Attempting to initialize Supabase client.")
        logging.info(f"SUPABASE_URL (from config): '{supabase_url}'")
        logging.info(f"SUPABASE_KEY (from config): '{supabase_key[:5]}...'") # Log first few chars for security

        if not supabase_url:
            logging.error("SUPABASE_URL is not set or is empty in config.json. Cloud sync will be unavailable.")
            ttk.dialogs.Messagebox.show_warning("Supabase URL not found in config.json. Cloud sync features will be unavailable.", "Cloud Sync Error")
            return
        
        if not supabase_key:
            logging.error("SUPABASE_KEY is not set or is empty in config.json. Cloud sync will be unavailable.")
            ttk.dialogs.Messagebox.show_warning("Supabase Key not found in config.json. Cloud sync features will be unavailable.", "Cloud Sync Error")
            return

        # Basic sanity check (rely on create_client for full validation)
        if not isinstance(supabase_url, str) or not supabase_url.startswith("https://"):
            logging.error(f"Supabase URL format error: '{supabase_url}'. Must be a string starting with 'https://'.")
            ttk.dialogs.Messagebox.show_warning("Invalid Supabase URL format. Please ensure SUPABASE_URL starts with 'https://'.", "Cloud Sync Error")
            return
        
        try:
            # --- Corrected Timeout Configuration ---
            # create_client will raise SupabaseException if URL or Key is truly invalid
            self.supabase_client: Client = create_client(
                supabase_url, 
                supabase_key,
            )
            logging.info("Supabase client created successfully.")

            # Ensure a local_unique_user_id exists for Supabase
            local_unique_user_id = self.send_db_command('get_setting', ('local_unique_user_id',), expect_result=True)
            if not local_unique_user_id:
                local_unique_user_id = str(uuid.uuid4())
                self.send_db_command('set_setting', ('local_unique_user_id', local_unique_user_id), expect_result=False)
                logging.info(f"Generated new local_unique_user_id: {local_unique_user_id}")
            
            self.supabase_user_id = local_unique_user_id
            logging.info(f"Supabase client initialized. Using local_unique_user_id: {self.supabase_user_id}")


        except Exception as e:
            logging.error(f"Error initializing Supabase client: {e}", exc_info=True)
            ttk.dialogs.Messagebox.show_warning(f"Failed to initialize Supabase for cloud sync: {e}. Leaderboard features will be unavailable.", "Cloud Sync Error")

    def _send_supabase_data(self, table_name, data):
        """Sends data to Supabase using the initialized client."""
        if not self.supabase_client:
            logging.warning("Cannot send data to Supabase: Client not initialized.")
            return False

        try:
            # Use upsert to insert or update the record.
            # Supabase identifies rows for upsert based on the primary key.
            # For 'leaderboard_stats', the primary key is (user_id, stat_date).
            response = self.supabase_client.table(table_name).upsert(data).execute()
            
            if response and response.data:
                logging.info(f"Data successfully upserted to Supabase table '{table_name}': {response.data}")
                return True
            else:
                logging.error(f"Failed to upsert data to Supabase table '{table_name}': {response.status_code if response else 'No response'}")
                return False

        except Exception as e:
            logging.error(f"Error sending data to Supabase table '{table_name}': {e}", exc_info=True)
            return False

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
                        logging.error(f"Unknown database operation: {operation_type}")
                        if result_queue:
                            result_queue.put(None)
                else:
                    logging.warning(f"Database not initialized. Skipping operation: {operation_type}")
                    if result_queue:
                        result_queue.put(None)
            except Exception as e:
                logging.error(f"Database operation '{operation_type}' failed: {e}")
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
        """Creates a system tray icon with a default image."""
        self.tray_icon = None

        if not PIL_AVAILABLE:
            logging.warning("Tray icon creation skipped: Pillow not available.")
            ttk.dialogs.Messagebox.show_warning("Failed to create system tray icon. The 'Pillow' library is not installed. Please install it using 'pip install Pillow' for full functionality.", "Tray Icon Error")
            return

        try:
            self.base_tray_image = Image.new("RGB", (16, 16), color=(255, 255, 255))
            draw = ImageDraw.Draw(self.base_tray_image)
            draw.text((2, 0), "W", fill=(0, 0, 0))

            menu = (
                pystray.MenuItem("Open", self.show_window),
                pystray.MenuItem("Exit", self.exit_app),
            )

            self.tray_icon = pystray.Icon(
                "WorkTracker", self.base_tray_image, "WorkTracker", menu)
            
            thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            thread.start()
            logging.info("Tray icon created successfully.")
        except Exception as e:
            logging.error(f"Failed to create tray icon: {e}. Ensure Pillow is correctly installed.", exc_info=True)
            self.tray_icon = None
            ttk.dialogs.Messagebox.show_warning("Failed to create system tray icon. An unexpected error occurred. Please ensure 'Pillow' library is correctly installed (pip install Pillow).", "Tray Icon Error")

    def show_window(self, icon=None, item=None):
        """Shows the main window."""
        self.root.deiconify()
        if self.tray_icon and self.base_tray_image:
            self.tray_icon.icon = self.base_tray_image
            self.tray_icon.visible = False

    def hide_window(self):
        """Hides the main window and creates a tray icon."""
        self.root.withdraw()
        if self.tray_icon:
            self.tray_icon.visible = True
            if self.base_tray_image:
                self.tray_icon.icon = self.base_tray_image

    def exit_app(self, icon=None, item=None):
        """Exits the application and stops any running session."""
        try:
            if self.is_running:
                self.stop_session()
            if self.tray_icon:
                self.tray_icon.stop()
            self.root.destroy()
            self.db_queue.join()
            logging.info("Application exited from tray.")
        except Exception as e:
            logging.error(f"Error exiting application: {e}")

    def get_available_categories(self, include_none=False): # Added include_none parameter
        """Gets categories from db."""
        all_categories = self.send_db_command('get_all_categories', expect_result=True)
        if all_categories is None:
            all_categories = []
        if include_none:
            return ["None"] + all_categories
        return all_categories

    def update_category_dropdown(self):
        """Update the category dropdown with available categories."""
        available_categories = self.get_available_categories()
        self.category_dropdown['values'] = available_categories
        if available_categories:
            if not self.category_var.get() or self.category_var.get() not in available_categories:
                self.category_var.set(available_categories[0])
        else:
            self.category_var.set("No Categories")

    def load_default_category_setting(self):
        """Loads the default category from settings and sets it in the dropdown."""
        default_category = self.send_db_command('get_setting', ('default_category',), expect_result=True)
        available_categories = self.get_available_categories()

        if default_category and default_category in available_categories:
            self.category_var.set(default_category)
            logging.info(f"Default category '{default_category}' loaded and set.")
        elif default_category and default_category not in available_categories:
            logging.warning(f"Default category '{default_category}' found in settings but no longer exists. Resetting.")
            self.send_db_command('set_setting', ('default_category', None), expect_result=False)
            if available_categories:
                self.category_var.set(available_categories[0])
            else:
                self.category_var.set("No Categories")
        else:
            logging.info("No default category setting found or it's invalid.")
            if available_categories:
                self.category_var.set(available_categories[0])
            else:
                self.category_var.set("No Categories")

    def open_default_category_settings(self):
        """Opens a dialog to set the default category."""
        settings_dialog = ttk.Toplevel(title="Set Default Category")
        settings_dialog.transient(self.root)
        settings_dialog.grab_set()

        form_frame = ttk.Frame(settings_dialog, padding=20)
        form_frame.pack(expand=True, fill=BOTH)

        ttk.Label(form_frame, text="Select Default Category:").grid(row=0, column=0, sticky="w", pady=5)

        current_categories = self.get_available_categories(include_none=True) # Use new parameter
        category_options = current_categories

        self.default_category_setting_var = tk.StringVar()
        
        current_default = self.send_db_command('get_setting', ('default_category',), expect_result=True)
        if current_default and current_default in category_options:
            self.default_category_setting_var.set(current_default)
        else:
            self.default_category_setting_var.set("None")

        default_category_dropdown = ttk.Combobox(
            form_frame, textvariable=self.default_category_setting_var, values=category_options, state="readonly"
        )
        default_category_dropdown.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        button_frame = ttk.Frame(form_frame)
        button_frame.grid(row=1, column=0, columnspan=2, pady=20)

        save_button = ttk.Button(button_frame, text="Save",
                                 command=lambda: self.save_default_category_setting(settings_dialog), bootstyle="success")
        save_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=settings_dialog.destroy, bootstyle="secondary")
        cancel_button.pack(side=tk.RIGHT, padx=5)

        settings_dialog.wait_window()

    def save_default_category_setting(self, dialog):
        """Saves the selected default category to the database."""
        selected_default = self.default_category_setting_var.get()
        
        value_to_save = None if selected_default == "None" else selected_default

        success = self.send_db_command('set_setting', ('default_category', value_to_save), expect_result=True)
        if success:
            ttk.dialogs.Messagebox.show_info("Default category setting updated.", "Settings Saved")
            self.load_default_category_setting()
            dialog.destroy()
        else:
            ttk.dialogs.Messagebox.show_error("Failed to save default category setting.", "Error")

    def load_display_name_setting(self):
        """Loads the display name from settings and initializes Supabase user ID if not set."""
        self.display_name = self.send_db_command('get_setting', ('display_name',), expect_result=True)
        
        # Ensure a local_unique_user_id exists for Supabase
        local_user_id = self.send_db_command('get_setting', ('local_unique_user_id',), expect_result=True)
        if not local_user_id:
            local_user_id = str(uuid.uuid4())
            self.send_db_command('set_setting', ('local_unique_user_id', local_user_id), expect_result=False)
            logging.info(f"Generated new local_unique_user_id: {local_user_id}")
        self.supabase_user_id = local_user_id # This ID is used for Supabase sync

        if not self.display_name:
            # Default display name links to the locally generated user ID
            self.display_name = f"User-{self.supabase_user_id[:8]}" 
            logging.info(f"No custom display name set. Using default: {self.display_name}")
        else:
            logging.info(f"Display name loaded: {self.display_name}")

    def open_display_name_settings(self):
        """Opens a dialog to set the user's display name."""
        display_name_dialog = ttk.Toplevel(title="Set Display Name")
        display_name_dialog.transient(self.root)
        display_name_dialog.grab_set()

        form_frame = ttk.Frame(display_name_dialog, padding=20)
        form_frame.pack(expand=True, fill=BOTH)

        ttk.Label(form_frame, text="Your Display Name for Leaderboard:").grid(row=0, column=0, sticky="w", pady=5)
        # Pre-fill with current display name, but clear default if it's the auto-generated one
        self.display_name_var = tk.StringVar(value=self.display_name if self.display_name and not self.display_name.startswith("User-") else "")
        display_name_entry = ttk.Entry(form_frame, textvariable=self.display_name_var, width=30)
        display_name_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        button_frame = ttk.Frame(form_frame)
        button_frame.grid(row=1, column=0, columnspan=2, pady=20)

        save_button = ttk.Button(button_frame, text="Save",
                                 command=lambda: self.save_display_name_setting(display_name_dialog), bootstyle="success")
        save_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=display_name_dialog.destroy, bootstyle="secondary")
        cancel_button.pack(side=tk.RIGHT, padx=5)

        display_name_dialog.wait_window()

    def save_display_name_setting(self, dialog):
        """Saves the user's display name to the database."""
        new_display_name = self.display_name_var.get().strip()
        if not new_display_name:
            ttk.dialogs.Messagebox.show_warning("Display name cannot be empty.", "Input Error")
            return

        success = self.send_db_command('set_setting', ('display_name', new_display_name), expect_result=True)
        if success:
            self.display_name = new_display_name
            ttk.dialogs.Messagebox.show_info("Display name updated.", "Settings Saved")
            dialog.destroy()
        else:
            ttk.dialogs.Messagebox.show_error("Failed to save display name.", "Error")

    def _schedule_heartbeat(self):
        """Sends a heartbeat to the cloud and reschedules itself."""
        # Ensure Supabase client is ready and user_id is available before sending heartbeats
        if self.supabase_client and self.supabase_user_id and self.display_name:
            self.send_heartbeat_to_cloud()
        else:
            logging.warning("Supabase client or user ID not ready for heartbeat. Skipping this cycle.")
        
        # Reschedule for 30 seconds later
        self.root.after(30000, self._schedule_heartbeat)

    def send_heartbeat_to_cloud(self):
        """Sends a heartbeat to the Supabase online_status table."""
        if not SUPABASE_AVAILABLE or not self.supabase_client or not self.supabase_user_id or not self.display_name:
            logging.warning("Cannot send heartbeat: Supabase not initialized or display name missing.")
            return False

        current_utc_time = datetime.datetime.now(datetime.timezone.utc)
        heartbeat_data = {
            'user_id': self.supabase_user_id,
            'display_name': self.display_name,
            'last_active_at': current_utc_time.isoformat()
        }

        logging.info(f"Sending heartbeat: {heartbeat_data}")
        success = self._send_supabase_data('online_status', heartbeat_data)

        if success:
            logging.info("Heartbeat sent to cloud successfully.")
        else:
            logging.error("Failed to send heartbeat to cloud.")
        return success

    def sync_daily_stats_to_cloud(self):
        """Calculates daily stats and uploads them to Supabase."""
        if not SUPABASE_AVAILABLE:
            ttk.dialogs.Messagebox.show_warning("Supabase library not available. Cannot sync stats.", "Cloud Sync")
            return
        if not self.supabase_client:
            ttk.dialogs.Messagebox.show_warning("Supabase client not initialized. Check logs for API key errors.", "Cloud Sync")
            return
        if not self.supabase_user_id:
             ttk.dialogs.Messagebox.show_warning("Local user ID for Supabase not generated. Try restarting the app or check logs.", "Cloud Sync")
             return

        # Prompt for display name if it's still the default UUID-based one
        if not self.display_name or self.display_name.startswith("User-"):
            response = ttk.dialogs.Messagebox.show_question("You don't have a custom display name set. Your stats will be uploaded as a generic user ID. It is highly recommended to set a custom display name for the leaderboard. Do you want to set one now?", "Display Name Recommended", buttons=["Yes", "No"])
            if response == "Yes":
                self.open_display_name_settings()
                # If name was successfully set and is no longer default, proceed with sync
                if self.display_name and not self.display_name.startswith("User-"):
                    pass
                else:
                    return # User cancelled or failed to set name
            else:
                pass # User chose to proceed with generic ID

        # --- Define 'today' based on Lagos, Nigeria timezone (WAT, UTC+1) ---
        lagos_tz = datetime.timezone(datetime.timedelta(hours=1), 'WAT')
        now_in_lagos = datetime.datetime.now(lagos_tz)
        today_in_lagos = now_in_lagos.date()

        start_of_today_in_lagos = datetime.datetime(today_in_lagos.year, today_in_lagos.month, today_in_lagos.day, 0, 0, 0, 0, tzinfo=lagos_tz)
        end_of_today_in_lagos = datetime.datetime(today_in_lagos.year, today_in_lagos.month, today_in_lagos.day, 23, 59, 59, 999999, tzinfo=lagos_tz)

        # Convert to UTC for querying SQLite (if SQLite stores naive times, this might need adjustment)
        # Assuming SQLite stores naive times as local times, we query based on local times.
        # The conversion to UTC happens when saving to SQLite and sending to Supabase.
        
        # Get all sessions for today (based on Lagos time)
        # Note: get_filtered_sessions expects naive datetimes if SQLite is naive, or timezone-aware if SQLite is timezone-aware.
        # Since we're storing UTC in SQLite, we should query with UTC datetimes for consistency.
        start_of_today_utc = start_of_today_in_lagos.astimezone(datetime.timezone.utc)
        end_of_today_utc = end_of_today_in_lagos.astimezone(datetime.timezone.utc)


        today_sessions = self.send_db_command(
            'get_filtered_sessions',
            (start_of_today_utc, end_of_today_utc, "All", None), # Filter by date, ignore category/search
            expect_result=True
        )

        if not today_sessions:
            ttk.dialogs.Messagebox.show_info("No sessions recorded today to sync.", "Cloud Sync")
            return

        # --- Calculate total duration for the day ---
        total_duration_today_minutes = 0.0
        longest_session_duration_minutes = 0.0

        for session in today_sessions:
            # session: (id, start_time_str, end_time_str, category, notes)
            try:
                # Parse stored UTC strings back to datetime objects
                if DATEUTIL_AVAILABLE:
                    start_dt = date_parse(session[1])
                    end_dt = date_parse(session[2]) if session[2] else None
                else:
                    # Fallback to trying multiple specific formats
                    parsed_start = False
                    for fmt in ['%Y-%m-%d %H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ']: # Added ISO formats
                        try:
                            # Handle potential timezone info in string
                            if 'Z' in session[1] or '+' in session[1] or '-' == session[1][-3] or '-' == session[1][-6]: # Basic check for timezone info
                                start_dt = datetime.datetime.fromisoformat(session[1])
                            else:
                                start_dt = datetime.datetime.strptime(session[1], fmt)
                            # Ensure it's timezone-aware UTC if it was naive
                            if start_dt.tzinfo is None:
                                start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
                            parsed_start = True
                            break
                        except ValueError:
                            continue
                    if not parsed_start:
                        logging.error(f"Could not parse start_time: {session[1]}")
                        continue # Skip this session

                    parsed_end = False
                    if session[2]:
                        for fmt in ['%Y-%m-%d %H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ']: # Added ISO formats
                            try:
                                if 'Z' in session[2] or '+' in session[2] or '-' == session[2][-3] or '-' == session[2][-6]:
                                    end_dt = datetime.datetime.fromisoformat(session[2])
                                else:
                                    end_dt = datetime.datetime.strptime(session[2], fmt)
                                if end_dt.tzinfo is None:
                                    end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)
                                parsed_end = True
                                break
                            except ValueError:
                                continue
                    else:
                        end_dt = None # Handle ongoing sessions
                        parsed_end = True # Mark as parsed if no end_time

                    if not parsed_end:
                        logging.error(f"Could not parse end_time: {session[2]}")
                        continue # Skip this session

                # Ensure end_time exists for duration calculation
                if end_dt:
                    duration = (end_dt - start_dt).total_seconds() / 60 # in minutes
                    total_duration_today_minutes += duration # Accumulate total duration
                    if duration > longest_session_duration_minutes:
                        longest_session_duration_minutes = duration
            except Exception as e: # Catch any other parsing or calculation errors
                logging.error(f"Error processing session for sync (ID: {session[0]}): {e}", exc_info=True)
                continue # Skip malformed or incomplete session

        daily_stats_data = {
            'user_id': self.supabase_user_id, # Use the consistent local Supabase user ID
            'display_name': self.display_name,
            'stat_date': today_in_lagos.isoformat(), # Use Lagos's calendar date
            'total_duration_minutes': round(total_duration_today_minutes, 2), # New field for total duration
            'longest_session_duration_minutes': round(longest_session_duration_minutes, 2),
            'last_synced': datetime.datetime.now(datetime.timezone.utc).isoformat() # Always sync 'last_synced' in UTC
        }

        # Send data to Supabase leaderboard_stats table
        success = self._send_supabase_data('leaderboard_stats', daily_stats_data)

        if success:
            ttk.dialogs.Messagebox.show_info("Daily statistics synced to cloud successfully!", "Cloud Sync")
            logging.info(f"Synced daily stats for {self.display_name}: {daily_stats_data}")
        else:
            ttk.dialogs.Messagebox.show_error("Failed to sync daily statistics to cloud. Check app.log.", "Cloud Sync Error")
            logging.error(f"Failed to sync daily stats for {self.display_name}")


    def on_category_select(self, event):
        """Handles category selection."""
        selected_category = self.category_var.get()
        logging.info(f"Category selected: {selected_category}")

    def add_category(self):
        """Adds a new category"""
        try:
            new_category = ttk.dialogs.dialogs.askstring("Add Category", "Enter new category name:")
            if new_category and new_category.strip():
                new_category = new_category.strip()
                success = self.send_db_command('insert_category', (new_category,), expect_result=True)
                if success:
                    self.update_category_dropdown()
                    self.category_var.set(new_category)
                    ttk.dialogs.Messagebox.show_info(f"Category '{new_category}' added.", "Success")
                else:
                    ttk.dialogs.Messagebox.show_error(f"Failed to add category '{new_category}'. It might already exist.", "Error")
        except Exception as e:
            logging.error(f"Error adding category: {e}")
            ttk.dialogs.Messagebox.show_error(f"An error occurred while adding category: {e}", "Error")

    def delete_category(self):
        """Deletes the currently selected category from the database."""
        try:
            selected_category = self.category_var.get()
            if not selected_category or selected_category == "No Categories":
                ttk.dialogs.Messagebox.show_info("No category selected to delete.", "Info")
                return

            response = ttk.dialogs.Messagebox.show_question(f"Are you sure you want to permanently delete category '{selected_category}'?\n\nAll existing sessions with this category will be set to 'Uncategorized'.", "Confirm Delete", buttons=["Yes", "No"])
            if response == "Yes":
                success = self.send_db_command('delete_category_from_db', (selected_category,), expect_result=True)
                if success:
                    self.update_category_dropdown()
                    ttk.dialogs.Messagebox.show_info(f"Category '{selected_category}' and its associated sessions updated to 'Uncategorized'.", "Category Deleted")
                    self.load_default_category_setting()
                else:
                    ttk.dialogs.Messagebox.show_error(f"Failed to delete category '{selected_category}'.", "Error")
        except Exception as e:
            logging.error(f"Error deleting category: {e}")
            ttk.dialogs.Messagebox.show_error(f"An error occurred while deleting category: {e}", "Error")

    def rename_category(self):
        """Renames the currently selected category in the database."""
        try:
            old_category = self.category_var.get()
            if not old_category or old_category == "No Categories":
                ttk.dialogs.Messagebox.show_info("Please select a category to rename.", "Rename Category")
                return

            new_category = ttk.dialogs.dialogs.askstring("Rename Category", f"Enter new name for '{old_category}':")

            if new_category and new_category.strip():
                new_category = new_category.strip()
                if old_category == new_category:
                    ttk.dialogs.Messagebox.show_info("Old and new category names are the same. No change made.", "Rename Category")
                    return

                success = self.send_db_command('rename_category', (old_category, new_category), expect_result=True)
                if success:
                    self.update_category_dropdown()
                    self.category_var.set(new_category)
                    self.load_default_category_setting()
                    ttk.dialogs.Messagebox.show_info(f"Category '{old_category}' renamed to '{new_category}'.", "Rename Category")
                else:
                    ttk.dialogs.Messagebox.show_error(f"Failed to rename category '{old_category}'. New name might already exist.", "Error")
        except Exception as e:
            logging.error(f"Error renaming category: {e}")
            ttk.dialogs.Messagebox.show_error(f"An error occurred while renaming category: {e}", "Error")

    def show_co_work_dialog(self):
        """Opens a dialog to show online users and invite them for co-work."""
        co_work_dialog = ttk.Toplevel(title="Co-work with Friends")
        co_work_dialog.transient(self.root)
        co_work_dialog.grab_set()
        co_work_dialog.geometry("400x300")

        frame = ttk.Frame(co_work_dialog, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Online Friends:").pack(pady=5)

        self.online_users_tree = ttk.Treeview(frame, columns=("Display Name",), show="headings", bootstyle="primary")
        self.online_users_tree.heading("Display Name", text="Display Name")
        self.online_users_tree.column("Display Name", width=250, stretch=tk.YES)
        self.online_users_tree.pack(fill="both", expand=True)

        action_frame = ttk.Frame(frame)
        action_frame.pack(pady=10)

        refresh_button = ttk.Button(action_frame, text="Refresh", command=self._populate_online_users, bootstyle="info-outline")
        refresh_button.pack(side=tk.LEFT, padx=5)

        invite_button = ttk.Button(action_frame, text="Invite Selected", command=self._invite_selected_user, bootstyle="success-outline")
        invite_button.pack(side=tk.LEFT, padx=5)

        self._populate_online_users() # Initial population

        co_work_dialog.wait_window()

    def _populate_online_users(self):
        """Fetches online users from Supabase and populates the Treeview."""
        for item in self.online_users_tree.get_children():
            self.online_users_tree.delete(item)

        if not SUPABASE_AVAILABLE or not self.supabase_client:
            logging.warning("Supabase not available for fetching online users.")
            self.online_users_tree.insert("", "end", values=("Cloud sync not active.",))
            return

        try:
            # Define online threshold (e.g., last 60 seconds)
            online_threshold = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=60)
            
            # Fetch online status from Supabase
            # Note: supabase-py doesn't directly support client-side filtering by timestamp in select()
            # We'll fetch all and filter client-side for simplicity, or implement RPC for server-side filter.
            # For small number of users, fetching all is fine.
            response = self.supabase_client.table('online_status').select('*').execute()

            if response and response.data:
                online_users = []
                for user_data in response.data:
                    last_active_str = user_data.get('last_active_at')
                    user_id = user_data.get('user_id')
                    display_name = user_data.get('display_name')

                    if last_active_str and user_id and display_name:
                        try:
                            # Parse last_active_at to a timezone-aware datetime object
                            last_active_dt = date_parse(last_active_str) if DATEUTIL_AVAILABLE else datetime.datetime.fromisoformat(last_active_str.replace('Z', '+00:00'))
                            
                            # Ensure it's UTC for comparison
                            if last_active_dt.tzinfo is None:
                                last_active_dt = last_active_dt.replace(tzinfo=datetime.timezone.utc)

                            # Check if active and not current user
                            if last_active_dt >= online_threshold and user_id != self.supabase_user_id:
                                online_users.append({'display_name': display_name, 'user_id': user_id})
                        except Exception as e:
                            logging.error(f"Error parsing last_active_at for user {display_name}: {e}", exc_info=True)
                            continue # Skip this user if parsing fails

                if online_users:
                    for user in online_users:
                        self.online_users_tree.insert("", "end", values=(user['display_name'],))
                else:
                    self.online_users_tree.insert("", "end", values=("No friends online right now.",))
            else:
                self.online_users_tree.insert("", "end", values=("Could not fetch online status.",))

        except Exception as e:
            logging.error(f"Error fetching online users from Supabase: {e}", exc_info=True)
            self.online_users_tree.insert("", "end", values=("Error fetching online users.",))

    def _invite_selected_user(self):
        """Invites the selected user for co-work via email."""
        selected_item = self.online_users_tree.focus()
        if not selected_item:
            ttk.dialogs.Messagebox.show_info("Please select a friend from the list to invite.", "Invite Friend")
            return

        selected_display_name = self.online_users_tree.item(selected_item, 'values')[0]
        
        # Generate Google Meet link
        meet_link = "https://meet.google.com/new" # Simplest way to get a new meeting link

        # Construct invitation message
        subject = f"Co-work Invitation from {self.display_name}"
        body = (
            f"Hey {selected_display_name},\n\n"
            f"I'm online and down for a co-work session! Join me here: {meet_link}\n\n"
            f"Let's get some work done!\n\n"
            f"Best,\n{self.display_name}"
        )

        # Use urllib.parse.quote for robust URL encoding of the body (spaces as %20)
        # Use urllib.parse.quote_plus for the subject (spaces as + is fine for subject)
        encoded_subject = urllib.parse.quote_plus(subject)
        encoded_body = urllib.parse.quote(body) # Correctly encodes spaces as %20

        # Directly open email client, removing the choice dialog
        try:
            # Mailto link with subject and body
            webbrowser.open_new_tab(f'mailto:?subject={encoded_subject}&body={encoded_body}')
            ttk.dialogs.Messagebox.show_info(f"Your email client has been opened with an invitation for {selected_display_name}. Please send it manually.", "Invitation Sent")
        except Exception as e:
            logging.error(f"Failed to open email client: {e}", exc_info=True)
            ttk.dialogs.Messagebox.show_error("Could not open email client. Please try manually.", "Error")


    def update_stopwatch(self):
        """Update the stopwatch display."""
        if self.stopwatch_running and not self.is_paused:
            current_time = datetime.datetime.now()
            elapsed = current_time - self.start_time
            self.elapsed_time = elapsed.total_seconds()

            if self.root.winfo_ismapped():
                # Round elapsed time to the nearest second for display
                rounded_elapsed_time = round(self.elapsed_time)
                formatted_time = time.strftime("%H:%M:%S", time.gmtime(rounded_elapsed_time))
                self.stopwatch_label.config(text=formatted_time)
        
        self.root.after(50, self.update_stopwatch) # Update more frequently for smoother feel, though display is per second

    def toggle_pause_resume(self):
        """Toggles the session between paused and resumed states."""
        if self.is_running:
            if not self.is_paused:
                self.is_paused = True
                self.stopwatch_running = False
                self.pause_start_time = datetime.datetime.now()
                self.pause_button.config(text="Resume")
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                
                if self.tray_icon and self.base_tray_image:
                    self.tray_icon.icon = self.base_tray_image
                
                logging.info("Session paused.")
            else:
                self.is_paused = False
                self.stopwatch_running = True
                if self.pause_start_time:
                    pause_duration = datetime.datetime.now() - self.pause_start_time
                    self.start_time += pause_duration
                    self.pause_start_time = None
                self.pause_button.config(text="Pause")
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                self.update_stopwatch()
                logging.info("Session resumed.")
        else:
            ttk.dialogs.Messagebox.show_warning("No session is currently running to pause/resume.", "Warning")

    def start_session(self):
        try:
            if self.category_var.get() == "No Categories":
                ttk.dialogs.Messagebox.show_warning("Please add a category before starting a session.", "Warning")
                return

            self.start_time = datetime.datetime.now()
            self.is_running = True
            self.is_paused = False
            self.pause_start_time = None

            self.start_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.NORMAL)
            logging.info("Buttons state updated: Start=DISABLED, Pause=NORMAL, Stop=NORMAL")

            self.stopwatch_running = True
            self.update_stopwatch()
            category = self.category_var.get()
            task = self.task_text.get("1.0", tk.END).strip()
            logging.info(f"Attempting to start session with category: {category}, task: {task}")

            self.current_session_id = self.send_db_command(
                'insert_session', (self.start_time, None, category, task), expect_result=True)

            if self.current_session_id is None:
                logging.error("Failed to get session ID from database. Database insertion likely failed.")
                ttk.dialogs.Messagebox.show_error("Failed to start session. Database error. Check app.log for details.", "Error")
                self.stopwatch_running = False
                self.is_running = False
                self.start_button.config(state=tk.NORMAL)
                self.pause_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.DISABLED)
                logging.info("Buttons state reverted due to DB error: Start=NORMAL, Pause=DISABLED, Stop=DISABLED")
                return

            logging.info(f"Session started successfully with category: {category}, ID: {self.current_session_id}")
        except Exception as e:
            logging.error(f"Error starting session: {e}", exc_info=True)
            ttk.dialogs.Messagebox.show_error(f"An unexpected error occurred while starting the session: {e}. Check app.log for details.", "Error")
            self.stopwatch_running = False
            self.is_running = False
            self.start_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            logging.info("Buttons state reverted due to unexpected error: Start=NORMAL, Pause=DISABLED, Stop=DISABLED")

    def stop_session(self):
        try:
            if self.current_session_id is None:
                logging.warning("Attempted to stop session when no session was running.")
                return

            self.end_time = datetime.datetime.now()
            self.is_running = False
            self.is_paused = False
            self.pause_start_time = None
            self.start_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            self.stopwatch_running = False
            task = self.task_text.get("1.0", tk.END).strip()

            self.send_db_command(
                'update_session', (self.current_session_id, self.end_time, task), expect_result=False)

            self.task_text.delete("1.0", tk.END)
            self.display_session_duration()
            self.current_session_id = None
            logging.info("Session stopped")

            if self.tray_icon and self.base_tray_image:
                self.tray_icon.icon = self.base_tray_image

        except Exception as e:
            logging.error(f"Error stopping session: {e}")
            ttk.dialogs.Messagebox.show_error(f"An error occurred while stopping the session: {e}", "Error")

    def display_session_duration(self):
        try:
            if self.start_time and self.end_time:
                duration = self.end_time - self.start_time
                ttk.dialogs.Messagebox.show_info(f"Session duration: {duration}", "Session duration")
                logging.info(f"Session duration displayed: {duration}")
            else:
                logging.warning("Cannot display duration: start or end time missing.")
        except Exception as e:
            logging.error(f"Error displaying session duration: {e}")

    def setup_todo_list(self, parent_frame):
        """Creates and configures the to-do list UI elements."""
        todo_frame = ttk.Labelframe(parent_frame, text="To-Do List", padding=15)
        todo_frame.pack(fill=BOTH, expand=True, pady=10, padx=5)

        # --- Header with Sync Button ---
        header_frame = ttk.Frame(todo_frame)
        header_frame.pack(fill=X, pady=(0, 10))
        
        sync_button = ttk.Button(header_frame, text="Sync with Google", bootstyle="info-outline", command=self.sync_google_tasks_placeholder)
        sync_button.pack(side=RIGHT)

        # --- Task List Display ---
        self.task_list = ttk.Treeview(todo_frame, columns=("star", "task"), show="", bootstyle="primary")
        self.task_list.pack(expand=True, fill=BOTH)
        self.task_list.column("star", width=30, anchor='center')
        self.task_list.column("task", width=450)

        # --- Add New Task Entry ---
        add_task_frame = ttk.Frame(todo_frame)
        add_task_frame.pack(fill=X, pady=(10, 0))

        self.new_task_var = tk.StringVar()
        new_task_entry = ttk.Entry(add_task_frame, textvariable=self.new_task_var, bootstyle="info")
        new_task_entry.pack(side=LEFT, expand=True, fill=X, padx=(0, 10))
        new_task_entry.bind("<Return>", self.add_local_task)
        
        add_task_button = ttk.Button(add_task_frame, text="Add Task", command=self.add_local_task, bootstyle="success")
        add_task_button.pack(side=LEFT)

        # --- Bind events ---
        self.task_list.bind("<Button-1>", self.handle_task_click)
        
        # --- Configure Tags for Styling ---
        strikethrough_font = tkfont.Font(family="Helvetica", size=10, overstrike=True)
        self.task_list.tag_configure('completed', foreground='gray', font=strikethrough_font)


    def handle_task_click(self, event):
        """Handles clicks within the task list to toggle status or starred."""
        region = self.task_list.identify("region", event.x, event.y)
        if not region:
            return

        column = self.task_list.identify_column(event.x)
        item_id = self.task_list.identify_row(event.y)

        if not item_id:
            return

        task_db_id = self.task_list.item(item_id, "tags")[0]

        if column == "#1":  # Star column
            self.toggle_task_starred(task_db_id)
        else: # Task title column (for checking off)
            self.toggle_task_status(task_db_id)

    def load_local_tasks(self):
        """Loads tasks from the local database and populates the to-do list UI."""
        for item in self.task_list.get_children():
            self.task_list.delete(item)

        tasks = self.send_db_command('get_tasks', expect_result=True)
        
        # Sort tasks: starred first, then by last modified
        tasks.sort(key=lambda x: (not x[3], x[5]), reverse=True)

        for task in tasks:
            task_id, title, status, starred, _, _ = task
            star_icon = "★" if starred else "☆"
            
            # Insert item into Treeview, using the database ID as a tag
            item = self.task_list.insert("", "end", values=(star_icon, title), tags=(task_id,))
            
            if status == 'completed':
                self.task_list.item(item, tags=(task_id, 'completed'))

    def add_local_task(self, event=None):
        """Adds a new task to the local database and updates the UI."""
        title = self.new_task_var.get().strip()
        if not title:
            return

        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        self.send_db_command('insert_task', (title, timestamp), expect_result=False)
        self.new_task_var.set("")
        self.load_local_tasks()

    def toggle_task_status(self, task_id):
        """Toggles the status of a task between 'needsAction' and 'completed'."""
        current_status = self.send_db_command('get_task_status', (task_id,), expect_result=True)
        new_status = 'completed' if current_status == 'needsAction' else 'needsAction'
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        self.send_db_command('update_task_status', (task_id, new_status, timestamp), expect_result=False)
        self.load_local_tasks()

    def toggle_task_starred(self, task_id):
        """Toggles the starred status of a task."""
        current_starred_val = self.send_db_command('get_task_starred', (task_id,), expect_result=True)
        new_starred_val = 0 if current_starred_val == 1 else 1
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        self.send_db_command('update_task_starred', (task_id, new_starred_val, timestamp), expect_result=False)
        self.load_local_tasks()
        
    def sync_google_tasks_placeholder(self):
        """Placeholder for Google Tasks sync functionality."""
        ttk.dialogs.Messagebox.show_info("Sync with Google Tasks is not yet implemented.", "Coming Soon!")

    def show_history(self):
        if self.history_window and tk.Toplevel.winfo_exists(self.history_window):
            self.history_window.lift()
            return
        self.history_window = ttk.Toplevel(title="Work History")
        self.history_window.geometry("800x600")

        filter_frame = ttk.Frame(self.history_window, padding=10)
        filter_frame.pack(fill="x", pady=5)

        ttk.Label(filter_frame, text="Date Range:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.history_date_range_var = tk.StringVar(self.history_window)
        self.history_date_range_var.set("All Time")
        date_range_options = ["All Time", "Last 7 Days", "Last 30 Days", "This Month", "This Year"]
        self.history_date_range_dropdown = ttk.Combobox(
            filter_frame, textvariable=self.history_date_range_var, values=date_range_options, state="readonly"
        )
        self.history_date_range_dropdown.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        ttk.Label(filter_frame, text="Category:").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        self.history_category_var = tk.StringVar(self.history_window)
        self.history_category_var.set("All")
        all_categories_for_filter = ["All"] + self.send_db_command('get_all_categories', expect_result=True) + ["Uncategorized"]
        self.history_category_dropdown = ttk.Combobox(
            filter_frame, textvariable=self.history_category_var, values=all_categories_for_filter, state="readonly"
        )
        self.history_category_dropdown.grid(row=0, column=3, padx=5, pady=2, sticky="ew")

        ttk.Label(filter_frame, text="Search:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.history_search_text_var = tk.StringVar(self.history_window)
        self.history_search_entry = ttk.Entry(filter_frame, textvariable=self.history_search_text_var)
        self.history_search_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=2, sticky="ew")

        # Container for the action buttons in the filter frame
        filter_button_frame = ttk.Frame(filter_frame)
        filter_button_frame.grid(row=1, column=3, padx=5, pady=2, sticky="e")

        apply_filters_button = ttk.Button(filter_button_frame, text="Apply Filters", command=self.update_history_display, bootstyle="info-outline")
        apply_filters_button.pack(side=tk.LEFT, padx=(0, 5))
        
        refresh_button = ttk.Button(filter_button_frame, text="Refresh", command=self.update_history_display, bootstyle="secondary-outline")
        refresh_button.pack(side=tk.LEFT)

        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(3, weight=1)

        self.history_tree = ttk.Treeview(self.history_window, columns=(
            "ID", "Start Time", "End Time", "Category", "Notes"), show="headings", bootstyle="primary")
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

        history_action_frame = ttk.Frame(self.history_window, padding=5)
        history_action_frame.pack(fill="x", pady=5)

        edit_session_button = ttk.Button(history_action_frame, text="Edit Selected Session", command=self.edit_selected_session, bootstyle="warning-outline")
        edit_session_button.pack(side=tk.RIGHT, padx=5)

        export_data_button = ttk.Button(history_action_frame, text="Export Data", command=self.export_data, bootstyle="primary-outline")
        export_data_button.pack(side=tk.RIGHT, padx=5)

        self.history_tree.bind("<Button-3>", self.show_history_context_menu)
        self.history_context_menu = ttk.Menu(self.history_window, tearoff=0)
        self.history_context_menu.add_command(label="Edit Session", command=self.edit_selected_session)
        self.history_context_menu.add_command(label="Export Selected Data", command=self.export_data)

        self.update_history_display()

    def show_history_context_menu(self, event):
        """Displays a context menu when right-clicking on the history treeview."""
        try:
            self.history_tree.selection_set(self.history_tree.identify_row(event.y))
            self.history_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.history_context_menu.grab_release()

    def edit_selected_session(self):
        """Opens a dialog to edit the details of the selected session."""
        selected_item = self.history_tree.focus()
        if not selected_item:
            ttk.dialogs.Messagebox.show_info("Please select a session to edit.", "Edit Session")
            return

        session_id = self.history_tree.item(selected_item, 'values')[0]
        session_details = self.send_db_command('get_session_by_id', (session_id,), expect_result=True)

        if not session_details:
            ttk.dialogs.Messagebox.show_error("Could not retrieve session details.", "Error")
            return

        s_id, s_start_time_str, s_end_time_str, s_category, s_notes = session_details

        edit_dialog = ttk.Toplevel(title=f"Edit Session ID: {s_id}")
        edit_dialog.transient(self.root)
        edit_dialog.grab_set()

        form_frame = ttk.Frame(edit_dialog, padding=20)
        form_frame.pack(expand=True, fill=BOTH)

        ttk.Label(form_frame, text="Start Time (YYYY-MM-DD HH:MM:SS):").grid(row=0, column=0, sticky="w", pady=2)
        self.edit_start_time_var = tk.StringVar(value=s_start_time_str if s_start_time_str else "")
        ttk.Entry(form_frame, textvariable=self.edit_start_time_var, width=35).grid(row=0, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(form_frame, text="End Time (YYYY-MM-DD HH:MM:SS):").grid(row=1, column=0, sticky="w", pady=2)
        self.edit_end_time_var = tk.StringVar(value=s_end_time_str if s_end_time_str else "")
        ttk.Entry(form_frame, textvariable=self.edit_end_time_var, width=35).grid(row=1, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(form_frame, text="Category:").grid(row=2, column=0, sticky="w", pady=2)
        self.edit_category_var = tk.StringVar(value=s_category if s_category else "Uncategorized")
        edit_categories = self.send_db_command('get_all_categories', expect_result=True) + ["Uncategorized"]
        self.edit_category_dropdown = ttk.Combobox(
            form_frame, textvariable=self.edit_category_var, values=edit_categories, state="readonly"
        )
        self.edit_category_dropdown.grid(row=2, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(form_frame, text="Notes:").grid(row=3, column=0, sticky="nw", pady=2)
        self.edit_notes_text = tk.Text(form_frame, height=4, width=30)
        self.edit_notes_text.grid(row=3, column=1, sticky="ew", padx=5, pady=2)
        self.edit_notes_text.insert(tk.END, s_notes if s_notes else "")

        button_frame = ttk.Frame(edit_dialog)
        button_frame.pack(pady=20)

        save_button = ttk.Button(button_frame, text="Save Changes",
                                 command=lambda: self.save_edited_session(edit_dialog, s_id), bootstyle="success")
        save_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=edit_dialog.destroy, bootstyle="secondary")
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

            # --- Robust Datetime Parsing ---
            def parse_datetime_string(dt_str, field_name):
                if not dt_str:
                    return None
                # Prefer dateutil.parser.parse if available, as it's very robust
                if DATEUTIL_AVAILABLE:
                    try:
                        return date_parse(dt_str)
                    except (ValueError, TypeError):
                        pass # Fallback to manual parsing
                
                # Fallback 1: ISO format (handles timezone from database)
                try:
                    return datetime.datetime.fromisoformat(dt_str)
                except ValueError:
                    pass

                # Fallback 2: Formats without timezone
                for fmt in ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']:
                    try:
                        return datetime.datetime.strptime(dt_str, fmt)
                    except ValueError:
                        continue
                
                # If all parsing fails
                ttk.dialogs.Messagebox.show_error(f"Invalid {field_name} format. Please use a recognized format like 'YYYY-MM-DD HH:MM:SS' or ISO 8601.", "Input Error")
                return "error"

            new_start_time = parse_datetime_string(new_start_time_str, "Start Time")
            if new_start_time == "error": return
            if not new_start_time:
                ttk.dialogs.Messagebox.show_error("Start Time cannot be empty.", "Input Error")
                return

            new_end_time = parse_datetime_string(new_end_time_str, "End Time")
            if new_end_time == "error": return
            
            if new_start_time and new_end_time and new_start_time > new_end_time:
                ttk.dialogs.Messagebox.show_error("Start Time cannot be after End Time.", "Input Error")
                return

            db_category = new_category if new_category != "Uncategorized" else None

            success = self.send_db_command(
                'update_full_session',
                (session_id, new_start_time, new_end_time, db_category, new_notes),
                expect_result=True
            )

            if success:
                ttk.dialogs.Messagebox.show_info("Session updated successfully!", "Success")
                dialog.destroy()
                self.update_history_display()
            else:
                ttk.dialogs.Messagebox.show_error("Failed to update session.", "Error")

        except Exception as e:
            logging.error(f"Error saving edited session: {e}", exc_info=True)
            ttk.dialogs.Messagebox.show_error(f"An error occurred while saving changes: {e}", "Error")


    def export_data(self):
        """Allows users to export filtered history data to CSV or Excel."""
        items = self.history_tree.get_children()
        if not items:
            ttk.dialogs.Messagebox.show_info("No data available in the history view to export.", "Export Data")
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
                    ttk.dialogs.Messagebox.show_info(f"Data successfully exported to CSV:\n{file_path}", "Export Success")
                elif file_path.lower().endswith('.xlsx'):
                    df.to_excel(file_path, index=False)
                    ttk.dialogs.Messagebox.show_info(f"Data successfully exported to Excel:\n{file_path}", "Export Success")
                else:
                    ttk.dialogs.Messagebox.show_error("Unsupported file format. Please choose .csv or .xlsx.", "Export Error")
            except Exception as e:
                logging.error(f"Error exporting data: {e}")
                ttk.dialogs.Messagebox.show_error(f"An error occurred during export:\n{e}", "Export Error")
        else:
            ttk.dialogs.Messagebox.show_info("Data export cancelled.", "Export Cancelled")

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
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif date_range == "This Year":
            start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

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
            ttk.dialogs.Messagebox.show_info("No sessions found matching the filters.", "Work History")

    def show_statistics(self):
        """Displays the statistics window."""
        if self.statistics_window and tk.Toplevel.winfo_exists(self.statistics_window):
            self.statistics_window.lift()
            return

        self.statistics_window = ttk.Toplevel(title="Statistics")
        self.statistics_window.geometry("800x600")

        all_categories_from_db = self.send_db_command('get_all_categories', expect_result=True)
        if all_categories_from_db is None:
            all_categories_from_db = []
        categories = ["All"] + all_categories_from_db + ["Uncategorized"]

        # --- Main Stats Frame ---
        stats_main_frame = ttk.Frame(self.statistics_window, padding=20)
        stats_main_frame.pack(expand=True, fill=BOTH)

        # --- Filter Controls ---
        filter_frame = ttk.Frame(stats_main_frame)
        filter_frame.pack(fill=X, pady=(0, 20))
        
        view_var = tk.StringVar(self.statistics_window)
        view_var.set("Daily")
        view_dropdown = ttk.Combobox(filter_frame, textvariable=view_var, values=[
                                     "Daily", "Weekly", "Monthly", "Yearly"], state="readonly", bootstyle="info")
        view_dropdown.pack(side=LEFT, padx=(0,10))

        category_var = tk.StringVar(self.statistics_window)
        category_var.set("All")
        category_dropdown = ttk.Combobox(
            filter_frame, textvariable=category_var, values=categories, state="readonly", bootstyle="info")
        category_dropdown.pack(side=LEFT)

        # --- Scorecard ---
        self.scorecard_label = ttk.Label(stats_main_frame, text="", font=("Helvetica", 14), bootstyle="primary")
        self.scorecard_label.pack(pady=10)
        
        # --- Chart Frame ---
        chart_frame = ttk.Frame(stats_main_frame)
        chart_frame.pack(expand=True, fill=BOTH)


        def update_stats():
            """Updates the statistics graph and scorecard."""
            view = view_var.get()
            category = category_var.get()

            daily_average = 0.0

            all_sessions_data = self.send_db_command('get_sessions', expect_result=True)

            # Clear previous chart
            for widget in chart_frame.winfo_children():
                widget.destroy()

            if not all_sessions_data:
                ttk.dialogs.Messagebox.show_info("No data available for the selected filters.", "Statistics")
                self.scorecard_label.config(text=f"Average Duration ({view}): 0 minutes")
                return

            df = pd.DataFrame(all_sessions_data, columns=["ID", "start_time", "end_time", "category", "notes"])

            if df.empty:
                ttk.dialogs.Messagebox.show_info("No data available for the selected filters (after DataFrame creation).", "Statistics")
                self.scorecard_label.config(text=f"Average Duration ({view}): 0 minutes")
                return

            # Data preparation - Use format='mixed' for robust datetime parsing and force UTC
            df['start_time'] = pd.to_datetime(df['start_time'], format='mixed', utc=True, errors='coerce')
            df['end_time'] = pd.to_datetime(df['end_time'], format='mixed', utc=True, errors='coerce')
            
            # Filter out sessions where either start_time or end_time could not be parsed (are NaT)
            # or where end_time is missing (ongoing sessions)
            df_completed = df.dropna(subset=['start_time', 'end_time']).copy()
            
            if df_completed.empty:
                ttk.dialogs.Messagebox.show_info("No completed sessions to display for the selected filters.", "Statistics")
                self.scorecard_label.config(text=f"Average Duration ({view}): 0 minutes")
                return

            df_completed.loc[:, 'duration'] = (df_completed['end_time'] - df_completed['start_time']).dt.total_seconds() / 60

            df_completed.loc[:, 'category'] = df_completed['category'].fillna('Uncategorized')

            if category != "All":
                df_completed = df_completed[df_completed['category'] == category].copy()
                if df_completed.empty:
                    ttk.dialogs.Messagebox.show_info("No completed sessions available for the selected category.", "Statistics")
                    self.scorecard_label.config(text=f"Average Duration ({view}): 0 minutes")
                    return


            # --- Crucial Fix: Ensure comparison dates are timezone-aware (UTC) ---
            # Get current time in UTC
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            
            grouped = None
            y_axis_label = "Minutes" # Default label

            if view == "Daily":
                start_of_today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                df_filtered = df_completed[df_completed['start_time'] >= start_of_today_utc].copy()
                if not df_filtered.empty:
                    df_filtered.loc[:, 'hour'] = df_filtered['start_time'].dt.hour
                    all_hours = list(range(24))
                    grouped = df_filtered.groupby('hour')['duration'].sum().reindex(all_hours, fill_value=0)
                    daily_average = grouped.mean()

            elif view == "Weekly":
                # Get start of week (Monday) in UTC
                start_of_week_utc = now_utc - datetime.timedelta(days=now_utc.weekday())
                start_of_week_utc = start_of_week_utc.replace(hour=0, minute=0, second=0, microsecond=0) # Ensure start of day
                
                df_filtered = df_completed[df_completed['start_time'] >= start_of_week_utc].copy()
                if not df_filtered.empty:
                    df_filtered.loc[:, 'day'] = df_filtered['start_time'].dt.day_name()
                    all_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    grouped = df_filtered.groupby('day')['duration'].sum().reindex(all_days, fill_value=0)
                    daily_average = grouped.mean()

            elif view == "Monthly":
                # Start of month in UTC
                start_of_month_utc = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                df_filtered = df_completed[(df_completed['start_time'] >= start_of_month_utc) & (df_completed['start_time'].dt.month == now_utc.month) & (df_completed['start_time'].dt.year == now_utc.year)].copy()
                if not df_filtered.empty:
                    df_filtered.loc[:, 'day'] = df_filtered['start_time'].dt.day
                    num_days_in_current_month = (now_utc.replace(month=now_utc.month % 12 + 1, day=1) - datetime.timedelta(days=1)).day
                    days_in_month_range = list(range(1, num_days_in_current_month + 1))
                    grouped = df_filtered.groupby('day')['duration'].sum().reindex(days_in_month_range, fill_value=0)
                    daily_average = grouped.mean()

            elif view == "Yearly":
                # Start of year in UTC
                start_of_year_utc = now_utc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                df_filtered = df_completed[df_completed['start_time'] >= start_of_year_utc].copy()
                if not df_filtered.empty:
                    df_filtered.loc[:, 'month'] = df_filtered['start_time'].dt.month_name()
                    all_months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
                    grouped = df_filtered.groupby('month')['duration'].sum().reindex(all_months, fill_value=0)
                    daily_average = grouped.mean()

            # Ensure daily_average is not NaN if grouped is empty after reindex (e.g., no data for a given period)
            if pd.isna(daily_average):
                daily_average = 0.0
            
            # New logic to switch between minutes and hours for the chart and format scorecard text
            scorecard_text = ""
            if grouped is not None and not grouped.empty and grouped.max() > 60:
                grouped = grouped / 60
                y_axis_label = "Hours"
                
                # Format scorecard for hours and minutes
                total_avg_minutes = daily_average
                avg_hours = int(total_avg_minutes // 60)
                avg_rem_minutes = int(round(total_avg_minutes % 60))
                
                hour_str = f"{avg_hours} hour" + ("s" if avg_hours != 1 else "")
                minute_str = f"{avg_rem_minutes} minute" + ("s" if avg_rem_minutes != 1 else "")

                if avg_hours > 0 and avg_rem_minutes > 0:
                    scorecard_text = f"{hour_str}, {minute_str}"
                elif avg_hours > 0:
                    scorecard_text = hour_str
                else:
                    scorecard_text = minute_str
            else:
                # Format scorecard for minutes
                scorecard_text = f"{daily_average:.2f} minutes"


            if grouped is not None and not grouped.empty and grouped.sum() > 0:
                plt.style.use('dark_background')
                fig, ax = plt.subplots(figsize=(8, 4))
                
                # Use ttkbootstrap colors
                colors = self.root.style.colors
                grouped.plot(kind='bar', ax=ax, color=colors.primary)
                
                ax.set_ylabel(y_axis_label, color=colors.fg)
                ax.set_title(f"{view} Statistics for {category} Category", color=colors.fg)
                
                fig.patch.set_facecolor(colors.bg)
                ax.set_facecolor(colors.bg)
                
                ax.tick_params(axis='x', colors=colors.fg)
                ax.tick_params(axis='y', colors=colors.fg)
                ax.spines['bottom'].set_color(colors.fg)
                ax.spines['top'].set_color(colors.fg) 
                ax.spines['right'].set_color(colors.fg)
                ax.spines['left'].set_color(colors.fg)

                fig.tight_layout()

                canvas = FigureCanvasTkAgg(fig, master=chart_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(expand=True, fill=BOTH)
            else:
                ttk.dialogs.Messagebox.show_info("No work data to display for the selected period and category.", "Statistics")
                scorecard_text = "0 minutes" # Default back to minutes if no data

            self.scorecard_label.config(text=f"Average Duration ({view}): {scorecard_text}")

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
        """Creates all necessary tables for the application."""
        if not self.conn:
            logging.error("Cannot create tables: No database connection.")
            return

        # Sessions Table
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

        # Categories Table
        self.cursor.execute(
            """
                CREATE TABLE IF NOT EXISTS categories(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            """
        )
        logging.info("Categories table checked/created.")

        # Settings Table
        self.cursor.execute(
            """
                CREATE TABLE IF NOT EXISTS settings(
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
        )
        logging.info("Settings table checked/created.")
        
        # Tasks Table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'needsAction',
                starred INTEGER DEFAULT 0,
                google_task_id TEXT,
                last_modified TEXT NOT NULL
            )
            """
        )
        logging.info("Tasks table checked/created.")

        self.conn.commit()

        # Populate default categories if table is empty
        self.cursor.execute("SELECT COUNT(*) FROM categories")
        if self.cursor.fetchone()[0] == 0:
            default_categories = ["Work", "Skill", "School"]
            for category in default_categories:
                try:
                    self.cursor.execute("INSERT INTO categories (name) VALUES (?)", (category,))
                    self.conn.commit()
                    logging.info(f"Default category '{category}' added to categories table.")
                except sqlite3.IntegrityError:
                    logging.warning(f"Default category '{category}' already exists, skipping.")
                except Exception as e:
                    logging.error(f"Error adding default category '{category}': {e}")
            logging.info("Default categories ensured in dedicated table.")


    def insert_session(self, start_time, end_time, category, notes):
        try:
            # Convert to UTC before storing
            start_time_str = start_time.astimezone(datetime.timezone.utc).isoformat() if start_time else None
            end_time_str = end_time.astimezone(datetime.timezone.utc).isoformat() if end_time else None

            self.cursor.execute("""
                INSERT INTO sessions (start_time, end_time, category, notes) VALUES (?,?,?,?)
                """, (start_time_str, end_time_str, category, notes))
            self.conn.commit()
            last_id = self.cursor.lastrowid
            logging.info(f"Session inserted. ID: {last_id}")
            return last_id
        except Exception as e:
            logging.error(f"Error inserting session into DB: {e}", exc_info=True)
            return None

    def update_session(self, session_id, end_time, notes):
        try:
            # Convert to UTC before storing
            end_time_str = end_time.astimezone(datetime.timezone.utc).isoformat() if end_time else None

            self.cursor.execute("""
                UPDATE sessions
                SET end_time = ?, notes = ?
                WHERE id = ?
            """, (end_time_str, notes, session_id))
            self.conn.commit()
            logging.info(f"Session updated. ID: {session_id}")
        except Exception as e:
            logging.error(f"Error updating session: {e}")
            return False

    def update_full_session(self, session_id, start_time, end_time, category, notes):
        """Updates all fields of a session in the database."""
        try:
            # Convert to UTC before storing
            start_time_str = start_time.astimezone(datetime.timezone.utc).isoformat() if start_time else None
            end_time_str = end_time.astimezone(datetime.timezone.utc).isoformat() if end_time else None

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
            self.cursor.execute("SELECT id, start_time, end_time, category, notes FROM sessions WHERE id = ?", (session_id,))
            session = self.cursor.fetchone()
            logging.info(f"Session {session_id} retrieved.")
            return session
        except Exception as e:
            logging.error(f"Error getting session by ID {session_id}: {e}")
            return None

    def get_sessions(self):
        """Gets all sessions from database."""
        try:
            self.cursor.execute("SELECT id, start_time, end_time, category, notes FROM sessions")
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
                # Ensure start_date is timezone-aware before converting to ISO for query
                if start_date.tzinfo is None:
                    start_date = start_date.astimezone(datetime.timezone.utc)
                query += " AND start_time >= ?"
                params.append(start_date.isoformat())
            if end_date:
                # Ensure end_date is timezone-aware before converting to ISO for query
                if end_date.tzinfo is None:
                    end_date = end_date.astimezone(datetime.timezone.utc)
                query += " AND start_time <= ?"
                if end_date.hour == 0 and end_date.minute == 0 and end_date.second == 0:
                    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                params.append(end_date.isoformat())

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
            logging.info(f"Filtered sessions retrieved. Query: {query}, Params: {params}")
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
            self.cursor.execute("INSERT INTO categories (name) VALUES (?)", (category_name,))
            self.conn.commit()
            logging.info(f"Category '{category_name}' inserted into dedicated table.")
            return True
        except sqlite3.IntegrityError:
            logging.warning(f"Category '{category_name}' already exists in dedicated table.")
            return False
        except Exception as e:
            logging.error(f"Error inserting category '{category_name}': {e}")
            return False

    def rename_category(self, old_category, new_category):
        """Renames a category in the categories table and updates associated sessions."""
        try:
            self.cursor.execute("SELECT 1 FROM categories WHERE name = ? LIMIT 1", (new_category,))
            if self.cursor.fetchone():
                logging.warning(f"Cannot rename '{old_category}' to '{new_category}': New category name already exists.")
                return False

            self.cursor.execute("UPDATE categories SET name = ? WHERE name = ?", (new_category, old_category))
            self.cursor.execute("UPDATE sessions SET category = ? WHERE category = ?", (new_category, old_category))
            self.conn.commit()
            logging.info(f"Category '{old_category}' renamed to '{new_category}' and sessions updated.")
            return True
        except Exception as e:
            logging.error(f"Error renaming category: {e}")
            return False

    def delete_category_from_db(self, category_name):
        """Deletes a category from the categories table and updates associated sessions."""
        try:
            self.cursor.execute("UPDATE sessions SET category = NULL WHERE category = ?", (category_name,))
            self.cursor.execute("DELETE FROM categories WHERE name = ?", (category_name,))
            self.conn.commit()
            logging.info(f"Category '{category_name}' deleted from categories table and sessions updated.")
            return True
        except Exception as e:
            logging.error(f"Error deleting category '{category_name}': {e}")
            return False

    def get_setting(self, key):
        """Retrieves a setting value by its key."""
        try:
            self.cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            result = self.cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logging.error(f"Error getting setting '{key}': {e}")
            return None

    def set_setting(self, key, value):
        """Inserts or updates a setting key-value pair."""
        try:
            self.cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            self.conn.commit()
            logging.info(f"Setting '{key}' set to '{value}'.")
            return True
        except Exception as e:
            logging.error(f"Error setting setting '{key}': {e}")
            return False
        
    def get_tasks(self):
        """Gets all tasks from the database."""
        try:
            self.cursor.execute("SELECT id, title, status, starred, google_task_id, last_modified FROM tasks")
            return self.cursor.fetchall()
        except Exception as e:
            logging.error(f"Error getting tasks: {e}")
            return []

    def insert_task(self, title, last_modified):
        """Inserts a new task into the database."""
        try:
            self.cursor.execute("""
                INSERT INTO tasks (title, last_modified) VALUES (?,?)
                """, (title, last_modified))
            self.conn.commit()
            return self.cursor.lastrowid
        except Exception as e:
            logging.error(f"Error inserting task: {e}")
            return None

    def get_task_status(self, task_id):
        """Gets the status of a single task."""
        try:
            self.cursor.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
            return self.cursor.fetchone()[0]
        except Exception as e:
            logging.error(f"Error getting task status for ID {task_id}: {e}")
            return None

    def get_task_starred(self, task_id):
        """Gets the starred value of a single task."""
        try:
            self.cursor.execute("SELECT starred FROM tasks WHERE id = ?", (task_id,))
            return self.cursor.fetchone()[0]
        except Exception as e:
            logging.error(f"Error getting starred status for ID {task_id}: {e}")
            return None

    def update_task_status(self, task_id, status, last_modified):
        """Updates the status of a task."""
        try:
            self.cursor.execute("UPDATE tasks SET status = ?, last_modified = ? WHERE id = ?", (status, last_modified, task_id))
            self.conn.commit()
        except Exception as e:
            logging.error(f"Error updating task status for ID {task_id}: {e}")
            
    def update_task_starred(self, task_id, starred, last_modified):
        """Updates the starred status of a task."""
        try:
            self.cursor.execute("UPDATE tasks SET starred = ?, last_modified = ? WHERE id = ?", (starred, last_modified, task_id))
            self.conn.commit()
        except Exception as e:
            logging.error(f"Error updating task starred status for ID {task_id}: {e}")        

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            logging.info("Database connection closed.")


if __name__ == "__main__":
    root = ttk.Window(themename="vapor")
    app = WorkTracker(root)
    root.mainloop()
