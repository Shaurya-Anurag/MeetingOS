
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "meetingos.db"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def utc_now():
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================
# MEETING LIFECYCLE
# ============================================================

MEETING_STATUSES = {
    "uploaded",
    "transcribing",
    "analyzing",
    "validating",
    "saving",
    "ready",
    "completed_with_warnings",
    "failed",
    "cancelled",
    "needs_retry",
}

ACTIVE_STATUSES = {
    "uploaded",
    "transcribing",
    "analyzing",
    "validating",
    "saving",
}


# ============================================================
# INITIALIZATION AND MIGRATIONS
# ============================================================

def migrate_meeting_lifecycle(cursor):
    """Add lifecycle columns to existing MeetingOS databases."""
    columns = {
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(meetings)"
        ).fetchall()
    }

    migrations = {
        "original_transcript": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'ready'",
        "current_stage": "TEXT",
        "run_id": "TEXT",
        "error_message": "TEXT",
        "error_type": "TEXT",
        "warnings_json": "TEXT NOT NULL DEFAULT '[]'",
        "started_at": "TEXT",
        "updated_at": "TEXT",
        "completed_at": "TEXT",
    }

    for column, definition in migrations.items():
        if column not in columns:
            cursor.execute(
                f"ALTER TABLE meetings ADD COLUMN {column} {definition}"
            )


def initialize_database():
    with get_connection() as connection:
        cursor = connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS meetings (
                original_transcript TEXT,
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                created_at TEXT NOT NULL,
                duration_seconds REAL,
                transcript TEXT,
                speaker_data TEXT,
                intelligence_json TEXT,
                analytics_json TEXT,

                status TEXT NOT NULL DEFAULT 'ready',
                current_stage TEXT,
                run_id TEXT,
                error_message TEXT,
                error_type TEXT,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                started_at TEXT,
                updated_at TEXT,
                completed_at TEXT
            )
            """
        )

        # CREATE TABLE IF NOT EXISTS does not alter existing tables.
        migrate_meeting_lifecycle(cursor)

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


# ============================================================
# CREATE A PROCESSING RECORD
# ============================================================

def create_processing_meeting(topic, run_id=None):
    """
    Create a durable meeting record before expensive processing begins.

    Returns the new meeting ID. The caller should retain both the
    meeting ID and run ID throughout this processing attempt.
    """
    initialize_database()

    run_id = run_id or str(uuid.uuid4())
    now = utc_now()
    topic = (topic or "").strip() or "Meeting Discussion"

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO meetings (
                topic,
                created_at,
                status,
                current_stage,
                run_id,
                warnings_json,
                started_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic,
                now,
                "uploaded",
                "uploaded",
                run_id,
                "[]",
                now,
                now,
            ),
        )

        meeting_id = cursor.lastrowid

    return meeting_id


# ============================================================
# UPDATE LIFECYCLE STATE
# ============================================================


ALLOWED_TRANSITIONS = {
    "uploaded": {
        "transcribing", "failed", "cancelled", "needs_retry"
    },
    "transcribing": {
        "analyzing", "failed", "cancelled", "needs_retry"
    },
    "analyzing": {
        "validating", "failed", "cancelled", "needs_retry"
    },
    "validating": {
        "saving", "failed", "cancelled", "needs_retry"
    },
    "saving": {
        "ready", "completed_with_warnings",
        "failed", "cancelled", "needs_retry"
    },
    "needs_retry": {
        "uploaded", "transcribing", "analyzing", "cancelled"
    },
    "failed": {"uploaded", "transcribing", "analyzing"},
    "cancelled": {"uploaded", "transcribing", "analyzing"},
    "ready": set(),
    "completed_with_warnings": set(),
}


def update_meeting_lifecycle(
    meeting_id,
    status,
    *,
    current_stage=None,
    run_id=None,
    error_message=None,
    error_type=None,
    warnings=None,
):
    """Validate and persist a processing lifecycle transition."""
    if status not in MEETING_STATUSES:
        raise ValueError(f"Unsupported meeting status: {status}")

    now = utc_now()

    with get_connection() as connection:
        existing = connection.execute(
            """
            SELECT status, run_id, warnings_json
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,),
        ).fetchone()

        if existing is None:
            raise ValueError(f"Meeting {meeting_id} does not exist.")

        if run_id is not None and existing["run_id"] != run_id:
            raise ValueError(
                "This processing run is no longer current."
            )

        old_status = existing["status"]

        # Allow idempotent updates to the same status.
        if status != old_status:
            allowed = ALLOWED_TRANSITIONS.get(old_status, set())
            if status not in allowed:
                raise ValueError(
                    f"Invalid lifecycle transition: "
                    f"{old_status} -> {status}"
                )

        previous_warnings = json.loads(
            existing["warnings_json"] or "[]"
        )
        merged_warnings = (
            previous_warnings if warnings is None else warnings
        )

        completed_at = (
            now
            if status in {"ready", "completed_with_warnings"}
            else None
        )

        connection.execute(
            """
            UPDATE meetings
            SET status = ?,
                current_stage = ?,
                error_message = ?,
                error_type = ?,
                warnings_json = ?,
                updated_at = ?,
                completed_at = COALESCE(?, completed_at)
            WHERE id = ?
            """,
            (
                status,
                current_stage or status,
                error_message,
                error_type,
                json.dumps(merged_warnings, ensure_ascii=False),
                now,
                completed_at,
                meeting_id,
            ),
        )



# ============================================================
# DURABLE TRANSCRIPT PERSISTENCE
# ============================================================

def save_transcription(
    meeting_id,
    transcript,
    speaker_data,
    *,
    run_id,
    duration_seconds=None,
):
    """
    Save validated transcription before running intelligence stages.

    A successful call transitions the meeting to 'analyzing'.
    """
    if not isinstance(transcript, str) or not transcript.strip():
        raise ValueError("Cannot save an empty transcript.")

    now = utc_now()

    with get_connection() as connection:
        cursor = connection.execute(
                        """
            UPDATE meetings
            SET original_transcript = COALESCE(original_transcript, transcript, ?),
                transcript = ?,
                speaker_data = ?,
                duration_seconds = COALESCE(?, duration_seconds),
                status = 'analyzing',
                current_stage = 'analyzing',
                error_message = NULL,
                error_type = NULL,
                updated_at = ?
            WHERE id = ? AND run_id = ?
            """,
            (
                transcript,
                transcript,
                json.dumps(speaker_data or {}, ensure_ascii=False),
                duration_seconds,
                now,
                meeting_id,
                run_id,
            ),
        )

        if cursor.rowcount != 1:
            raise ValueError(
                "Transcript was not saved: meeting or processing run "
                "is no longer current."
            )



def finalize_processing_meeting(
    meeting_id: int,
    *,
    run_id: str,
    topic: str,
    intelligence: dict,
    analytics: dict,
    warnings=None,
):
    """Atomically persist results and finish a lifecycle-managed meeting."""
    from datetime import timezone

    warnings = list(warnings or [])
    topic = (topic or "").strip() or "Meeting Discussion"

    if not isinstance(intelligence, dict):
        raise ValueError("Intelligence must be a dictionary.")

    if not isinstance(analytics, dict):
        raise ValueError("Analytics must be a dictionary.")

    action_items = intelligence.get("action_items", [])
    if not isinstance(action_items, list):
        raise ValueError("Action items must be a list.")

    # Validate and normalize tasks before opening the transaction.
    normalized_tasks = []
    for action in action_items:
        if not isinstance(action, dict):
            continue

        task_text = (action.get("task") or "").strip()
        if not task_text:
            continue

        evidence = action.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = []

        normalized_tasks.append({
            "task": task_text,
            "owner": action.get("owner"),
            "deadline": action.get("deadline"),
            "evidence": json.dumps(evidence, ensure_ascii=False),
        })

    final_status = (
        "completed_with_warnings" if warnings else "ready"
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection() as connection:
        cursor = connection.cursor()

        meeting = cursor.execute(
            """
            SELECT run_id, transcript, status
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,),
        ).fetchone()

        if meeting is None:
            raise ValueError(f"Meeting {meeting_id} does not exist.")

        if meeting["run_id"] != run_id:
            raise ValueError("Run ID does not match this meeting.")

        if not (meeting["transcript"] or "").strip():
            raise ValueError("Cannot finalize without a saved transcript.")

        if meeting["status"] not in {"validating", "saving"}:
            # Same-run repeat finalization is safe only if already finalized.
            if meeting["status"] in {"ready", "completed_with_warnings"}:
                return {
                    "meeting_id": meeting_id,
                    "status": meeting["status"],
                    "idempotent": True,
                }
            raise ValueError(
                f"Cannot finalize a meeting in state "
                f"{meeting['status']!r}."
            )

        cursor.execute(
            """
            UPDATE meetings
            SET status = 'saving',
                current_stage = 'saving',
                updated_at = ?
            WHERE id = ? AND run_id = ?
            """,
            (now, meeting_id, run_id),
        )

        cursor.execute(
            """
            UPDATE meetings
            SET topic = ?,
                intelligence_json = ?,
                analytics_json = ?,
                duration_seconds = ?,
                status = ?,
                current_stage = 'completed',
                warnings_json = ?,
                error_message = NULL,
                error_type = NULL,
                updated_at = ?,
                completed_at = ?
            WHERE id = ? AND run_id = ?
            """,
            (
                topic,
                json.dumps(intelligence, ensure_ascii=False),
                json.dumps(analytics, ensure_ascii=False),
                analytics.get("duration_seconds"),
                final_status,
                json.dumps(warnings, ensure_ascii=False),
                now,
                now,
                meeting_id,
                run_id,
            ),
        )

        # Reconcile tasks without resetting their existing statuses.
        existing_rows = cursor.execute(
            """
            SELECT id, task, owner, deadline, status
            FROM tasks
            WHERE meeting_id = ?
            """,
            (meeting_id,),
        ).fetchall()

        existing_by_key = {}
        for row in existing_rows:
            key = (
                (row["task"] or "").strip().casefold(),
                (row["owner"] or "").strip().casefold(),
                (row["deadline"] or "").strip().casefold(),
            )
            existing_by_key.setdefault(key, []).append(row)

        for task in normalized_tasks:
            key = (
                task["task"].casefold(),
                (task["owner"] or "").strip().casefold(),
                (task["deadline"] or "").strip().casefold(),
            )

            matches = existing_by_key.get(key, [])
            if matches:
                # Keep the task's current status; refresh its evidence.
                existing = matches.pop(0)
                cursor.execute(
                    "UPDATE tasks SET evidence = ? WHERE id = ?",
                    (task["evidence"], existing["id"]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO tasks (
                        meeting_id, task, owner, deadline, status, evidence
                    )
                    VALUES (?, ?, ?, ?, 'Pending', ?)
                    """,
                    (
                        meeting_id,
                        task["task"],
                        task["owner"],
                        task["deadline"],
                        task["evidence"],
                    ),
                )

    return {
        "meeting_id": meeting_id,
        "status": final_status,
        "idempotent": False,
    }

# ============================================================
# SAVE A COMPLETED MEETING
# ============================================================

def save_meeting(
    topic,
    transcript,
    intelligence,
    analytics,
    speaker_data=None,
):
    """
    Preserve the existing save API.

    This compatibility function creates a new completed meeting.
    The processing lifecycle should instead use create_processing_meeting,
    save_transcription, and a later transactional finalization function.
    """
    initialize_database()

    created_at = utc_now()
    topic = (topic or "").strip() or "Meeting Discussion"

    with get_connection() as connection:
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO meetings (
                topic,
                created_at,
                duration_seconds,
                transcript,
                speaker_data,
                intelligence_json,
                analytics_json,
                status,
                current_stage,
                warnings_json,
                started_at,
                updated_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic,
                created_at,
                analytics.get("duration_seconds"),
                transcript,
                json.dumps(speaker_data or {}, ensure_ascii=False),
                json.dumps(intelligence, ensure_ascii=False),
                json.dumps(analytics, ensure_ascii=False),
                "ready",
                "ready",
                "[]",
                created_at,
                created_at,
                created_at,
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
                    meeting_id,
                    task,
                    owner,
                    deadline,
                    status,
                    evidence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    meeting_id,
                    task,
                    action.get("owner"),
                    action.get("deadline"),
                    "Pending",
                    json.dumps(
                        action.get("evidence", []),
                        ensure_ascii=False,
                    ),
                ),
            )

    return meeting_id


# ============================================================
# MEETING QUERIES
# ============================================================

def get_all_meetings():
    initialize_database()

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                topic,
                created_at,
                duration_seconds,
                status,
                current_stage,
                run_id,
                error_message,
                warnings_json,
                started_at,
                updated_at,
                completed_at
            FROM meetings
            ORDER BY created_at DESC
            """
        ).fetchall()

    meetings = []

    for row in rows:
        meeting = dict(row)
        meeting["warnings"] = json.loads(
            meeting.pop("warnings_json", "[]") or "[]"
        )
        meetings.append(meeting)

    return meetings


def search_meetings(query):
    """Keyword search across meeting topic, transcript and intelligence."""
    initialize_database()
    query = (query or "").strip()

    if not query:
        return get_all_meetings()

    search_term = f"%{query}%"

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                topic,
                created_at,
                duration_seconds,
                status,
                current_stage
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

    meeting["speaker_data"] = json.loads(
        meeting["speaker_data"] or "{}"
    )
    meeting["intelligence"] = json.loads(
        meeting["intelligence_json"] or "{}"
    )
    meeting["analytics"] = json.loads(
        meeting["analytics_json"] or "{}"
    )
    meeting["warnings"] = json.loads(
        meeting.pop("warnings_json", "[]") or "[]"
    )

    return meeting


# ============================================================
# TASK QUERIES
# ============================================================

def get_tasks(meeting_id=None, status=None):
    """
    Return tasks globally or for one meeting.

    Includes meeting topic and creation time for the Task Tracker.
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
        cursor = connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        changed = cursor.rowcount

    return changed > 0


def start_meeting_retry(meeting_id: int) -> dict:
    """Start a new analysis attempt using an existing saved transcript."""
    import uuid
    from datetime import timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_run_id = str(uuid.uuid4())

    with get_connection() as connection:
        cursor = connection.cursor()

        meeting = cursor.execute(
            """
            SELECT transcript, status
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,),
        ).fetchone()

        if meeting is None:
            raise ValueError("Meeting not found.")

        if meeting["status"] not in {
            "failed",
            "needs_retry",
            "cancelled",
        }:
            raise ValueError(
                f"Cannot retry a meeting in state "
                f"{meeting['status']!r}."
            )

        if not (meeting["transcript"] or "").strip():
            raise ValueError(
                "This meeting has no saved transcript to retry. "
                "Run transcription again instead."
            )

        cursor.execute(
            """
            UPDATE meetings
            SET run_id = ?,
                status = 'analyzing',
                current_stage = 'analyzing',
                error_message = NULL,
                error_type = NULL,
                warnings_json = '[]',
                started_at = ?,
                updated_at = ?,
                completed_at = NULL
            WHERE id = ?
            """,
            (new_run_id, now, now, meeting_id),
        )

    return {
        "meeting_id": meeting_id,
        "run_id": new_run_id,
        "status": "analyzing",
    }

# ============================================================
# DELETE A MEETING
# ============================================================

def delete_meeting(meeting_id):
    initialize_database()

    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        deleted = cursor.rowcount

    return deleted > 0




def recover_stale_meetings(stale_after_minutes: int = 45) -> int:
    """Move abandoned processing jobs into a recoverable state."""
    from datetime import datetime, timedelta, timezone

    if stale_after_minutes < 1:
        raise ValueError("stale_after_minutes must be at least 1.")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=stale_after_minutes)
    now_text = now.isoformat(timespec="seconds")
    recovered = 0

    active_statuses = (
        "uploaded",
        "transcribing",
        "analyzing",
        "validating",
        "saving",
    )

    with get_connection() as connection:
        cursor = connection.cursor()
        placeholders = ",".join("?" for _ in active_statuses)

        rows = cursor.execute(
            f"""
            SELECT id, status, transcript, updated_at, started_at
            FROM meetings
            WHERE status IN ({placeholders})
            """,
            active_statuses,
        ).fetchall()

        for row in rows:
            timestamp = row["updated_at"] or row["started_at"]
            if not timestamp:
                # Old or incomplete record: treat it as abandoned.
                is_stale = True
            else:
                try:
                    parsed = datetime.fromisoformat(timestamp)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    is_stale = parsed < cutoff
                except ValueError:
                    is_stale = True

            if not is_stale:
                continue

            has_transcript = bool((row["transcript"] or "").strip())
            new_status = "needs_retry" if has_transcript else "failed"

            cursor.execute(
                """
                UPDATE meetings
                SET status = ?,
                    current_stage = 'recovery',
                    error_message = ?,
                    error_type = 'StaleProcessing',
                    updated_at = ?
                WHERE id = ?
                  AND status IN (
                      'uploaded', 'transcribing', 'analyzing',
                      'validating', 'saving'
                  )
                """,
                (
                    new_status,
                    (
                        "Processing stopped unexpectedly. "
                        "Retry analysis using the saved transcript."
                        if has_transcript
                        else
                        "Processing stopped before a transcript was saved. "
                        "Upload the recording and process it again."
                    ),
                    now_text,
                    row["id"],
                ),
            )
            recovered += cursor.rowcount

    return recovered


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized at: {DB_PATH}")
