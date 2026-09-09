import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "meetingos.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
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
            """
        )
        connection.commit()


def save_meeting(topic, transcript, intelligence, analytics, speaker_data=None):
    initialize_database()
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO meetings (
                topic, created_at, duration_seconds, transcript,
                speaker_data, intelligence_json, analytics_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic,
                created_at,
                analytics.get("duration_seconds"),
                transcript,
                json.dumps(speaker_data or {}, ensure_ascii=False),
                json.dumps(intelligence, ensure_ascii=False),
                json.dumps(analytics, ensure_ascii=False),
            ),
        )
        meeting_id = cursor.lastrowid

        for action in intelligence.get("action_items", []):
            if not isinstance(action, dict):
                continue

            task = (action.get("task") or "").strip()
            if not task:
                continue

            cursor.execute(
                """
                INSERT INTO tasks (
                    meeting_id, task, owner, deadline, status, evidence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    meeting_id,
                    task,
                    action.get("owner"),
                    action.get("deadline"),
                    "Pending",
                    json.dumps(action.get("evidence", []), ensure_ascii=False),
                ),
            )

        connection.commit()

    return meeting_id


def get_all_meetings():
    initialize_database()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, topic, created_at, duration_seconds
            FROM meetings
            ORDER BY created_at DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def search_meetings(query):
    """Keyword search across meeting topic, transcript and structured intelligence."""
    initialize_database()
    query = (query or "").strip()

    if not query:
        return get_all_meetings()

    search_term = f"%{query}%"

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, topic, created_at, duration_seconds
            FROM meetings
            WHERE topic LIKE ?
               OR transcript LIKE ?
               OR intelligence_json LIKE ?
            ORDER BY created_at DESC
            """,
            (search_term, search_term, search_term),
        ).fetchall()

    return [dict(row) for row in rows]


def get_meeting(meeting_id):
    initialize_database()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,),
        ).fetchone()

    if row is None:
        return None

    meeting = dict(row)
    meeting["speaker_data"] = json.loads(meeting["speaker_data"] or "{}")
    meeting["intelligence"] = json.loads(meeting["intelligence_json"] or "{}")
    meeting["analytics"] = json.loads(meeting["analytics_json"] or "{}")
    return meeting


def get_tasks(meeting_id=None, status=None):
    """
    Return tasks globally or for one meeting.

    Includes meeting topic/created_at so the global Task Tracker can show
    where each task came from.
    """
    initialize_database()

    query = """
        SELECT
            t.id,
            t.meeting_id,
            t.task,
            t.owner,
            t.deadline,
            t.status,
            t.evidence,
            m.topic AS meeting_topic,
            m.created_at AS meeting_created_at
        FROM tasks AS t
        JOIN meetings AS m
            ON m.id = t.meeting_id
    """

    conditions = []
    params = []

    if meeting_id is not None:
        conditions.append("t.meeting_id = ?")
        params.append(meeting_id)

    if status is not None:
        conditions.append("t.status = ?")
        params.append(status)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY t.id DESC"

    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    tasks = []

    for row in rows:
        task = dict(row)
        task["evidence"] = json.loads(task["evidence"] or "[]")
        tasks.append(task)

    return tasks


def get_task(task_id):
    initialize_database()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                t.id,
                t.meeting_id,
                t.task,
                t.owner,
                t.deadline,
                t.status,
                t.evidence,
                m.topic AS meeting_topic,
                m.created_at AS meeting_created_at
            FROM tasks AS t
            JOIN meetings AS m
                ON m.id = t.meeting_id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()

    if row is None:
        return None

    task = dict(row)
    task["evidence"] = json.loads(task["evidence"] or "[]")
    return task


def update_task_status(task_id, status):
    allowed_statuses = {"Pending", "In Progress", "Completed"}

    if status not in allowed_statuses:
        return False

    initialize_database()

    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        changed = cursor.rowcount
        connection.commit()

    return changed > 0


def delete_meeting(meeting_id):
    initialize_database()

    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "DELETE FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        deleted = cursor.rowcount
        connection.commit()

    return deleted > 0


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized at: {DB_PATH}")
