# Work Tracker

This is a desktop application for tracking work sessions, allowing users to categorize their work, record tasks, and view historical data and statistics.

## Features

- **Session Tracking:** Start and stop work sessions with a precise stopwatch.
- **Category Management:**
  - Add, delete, rename, and restore work categories.
  - Categories are stored in a SQLite database.
- **Task Recording:** Record tasks performed during each session.
- **History View:** View a detailed history of all work sessions.
- **Statistics:** Visualize work session data with graphs and scorecards, showing daily averages and trends over weeks, months, or years.
- **Database Integration:** Uses SQLite for data storage, ensuring persistent data.
- **Customizable Themes:** Uses ttkthemes for a modern look and feel.

## Getting Started

### Prerequisites

- Python 3.x
- pip (Python package installer)

### Installation

1.  **Clone the repository (or download the source code):**

    ```bash
    git clone [repository URL]
    cd WorkTracker
    ```

2.  **Install the required Python packages:**

    ```bash
    pip install tkinter ttkthemes pandas matplotlib pyinstaller
    ```

### Running the Application

- **From source:**

  ```bash
  python main.py
  ```

- **As an executable (after creating with PyInstaller):**

  - Navigate to the `dist` folder created by PyInstaller.
  - Run the executable file (`main.exe` on Windows, or the appropriate file on macOS/Linux).

### Creating an Executable (PyInstaller)

1.  **Install PyInstaller:**

    ```bash
    pip install pyinstaller
    ```

2.  **Run PyInstaller:**

    ```bash
    pyinstaller --onefile --hidden-import "ttkthemes" --add-data "deep_work.db;." main.py
    ```

3.  The executable will be located in the `dist` folder.

### Database

- The application uses an SQLite database (`deep_work.db`) to store session data.
- Ensure that the database file is present in the same directory as the executable or the Python script.

### Usage

1.  **Start a Session:**
    - Select a category from the dropdown.
    - Enter a task description.
    - Click "Start."
2.  **Stop a Session:**
    - Click "Stop."
3.  **Manage Categories:**
    - Use the "Add Category," "Delete Category," "Rename Category", and "Restore Category" buttons.
4.  **View History:**
    - Click the "History" button.
5.  **View Statistics:**
    - Click the "Statistics" button.
    - Use the dropdown menus to filter the data.

### Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bug fixes or feature requests.

### License

This project is licensed under the [License Name] License.
