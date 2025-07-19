CREATE TABLE sessions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TEXT,
                    end_time TEXT,
                    category TEXT,
                    notes TEXT
                , task_id INTEGER);
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE categories(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );
CREATE TABLE settings(
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'needsAction',
                starred INTEGER DEFAULT 0,
                google_task_id TEXT,
                last_modified TEXT NOT NULL
            , deleted INTEGER DEFAULT 0);