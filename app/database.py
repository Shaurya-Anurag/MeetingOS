import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "meetingos.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                created_at TEXT NOT NULL,
                duration_seconds REAL,
                transcript TEXT,
                speaker_data TEXT,
                intelligence_json TEXT,
                analytics_json TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER NOT NULL,
                task TEXT NOT NULL,
                owner TEXT,
                deadline TEXT,
                status TEXT NOT NULL DEFAULT 'Pending',
                evidence TEXT,
                FOREIGN KEY (meeting_id)
                    REFERENCES meetings(id)
                    ON DELETE CASCADE
            )
        """)

        connection.commit()


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized at: {DB_PATH}")