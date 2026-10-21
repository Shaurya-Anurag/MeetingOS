import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "meetingos.db"

HOST = "127.0.0.1"
PORT = 8000


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_library_columns():
    """
    Add Meeting Library metadata to an existing MeetingOS database.

    Safe for existing databases:
    - Does not delete or rewrite meetings.
    - Adds columns only if they don't already exist.
    """

    with get_connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(meetings)"
            ).fetchall()
        }

        if "display_name" not in columns:
            connection.execute(
                "ALTER TABLE meetings ADD COLUMN display_name TEXT"
            )

        if "is_pinned" not in columns:
            connection.execute(
                "ALTER TABLE meetings ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0"
            )

        connection.commit()


def serialize_meeting(row):
    meeting = dict(row)

    if not meeting.get("display_name"):
        meeting["display_name"] = meeting["topic"]

    meeting["is_pinned"] = bool(meeting.get("is_pinned", 0))

    return meeting


def get_meetings():
    ensure_library_columns()

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                topic,
                display_name,
                created_at,
                duration_seconds,
                is_pinned
            FROM meetings
            ORDER BY is_pinned DESC, created_at DESC
            """
        ).fetchall()

    return [serialize_meeting(row) for row in rows]


def get_meeting(meeting_id):
    ensure_library_columns()

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                topic,
                display_name,
                created_at,
                duration_seconds,
                is_pinned
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,),
        ).fetchone()

    if row is None:
        return None

    return serialize_meeting(row)


def update_meeting(meeting_id, display_name=None, is_pinned=None):
    ensure_library_columns()

    fields = []
    values = []

    if display_name is not None:
        display_name = display_name.strip()

        if not display_name:
            return False

        fields.append("display_name = ?")
        values.append(display_name)

    if is_pinned is not None:
        fields.append("is_pinned = ?")
        values.append(1 if is_pinned else 0)

    if not fields:
        return False

    values.append(meeting_id)

    with get_connection() as connection:
        cursor = connection.cursor()

        cursor.execute(
            f"""
            UPDATE meetings
            SET {", ".join(fields)}
            WHERE id = ?
            """,
            tuple(values),
        )

        changed = cursor.rowcount
        connection.commit()

    return changed > 0


def delete_meeting(meeting_id):
    with get_connection() as connection:
        cursor = connection.cursor()

        cursor.execute(
            "DELETE FROM meetings WHERE id = ?",
            (meeting_id,),
        )

        deleted = cursor.rowcount
        connection.commit()

    return deleted > 0


def send_json(handler, payload, status=200):
    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    handler.send_response(status)
    handler.send_header(
        "Content-Type",
        "application/json; charset=utf-8",
    )
    handler.send_header(
        "Access-Control-Allow-Origin",
        "*",
    )
    handler.send_header(
        "Access-Control-Allow-Methods",
        "GET, PATCH, DELETE, OPTIONS",
    )
    handler.send_header(
        "Access-Control-Allow-Headers",
        "Content-Type",
    )
    handler.send_header(
        "Cache-Control",
        "no-store",
    )
    handler.send_header(
        "Content-Length",
        str(len(body)),
    )
    handler.end_headers()

    handler.wfile.write(body)


def read_json_body(handler):
    length = int(handler.headers.get("Content-Length", "0"))

    if length == 0:
        return {}

    raw = handler.rfile.read(length)

    return json.loads(raw.decode("utf-8"))


class APIHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[API] {format % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, PATCH, DELETE, OPTIONS",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type",
        )
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        try:
            if path == "/api/meetings":
                send_json(self, get_meetings())
                return

            if path.startswith("/api/meetings/"):
                raw_id = path.rsplit("/", 1)[-1]

                try:
                    meeting_id = int(raw_id)
                except ValueError:
                    send_json(
                        self,
                        {"error": "Invalid meeting ID"},
                        400,
                    )
                    return

                meeting = get_meeting(meeting_id)

                if meeting is None:
                    send_json(
                        self,
                        {"error": "Meeting not found"},
                        404,
                    )
                    return

                send_json(self, meeting)
                return

            send_json(
                self,
                {"error": "Not found"},
                404,
            )

        except Exception as exc:
            print(f"[API ERROR] {exc}")
            send_json(
                self,
                {"error": "Internal server error"},
                500,
            )

    def do_PATCH(self):
        path = urlparse(self.path).path

        if not path.startswith("/api/meetings/"):
            send_json(self, {"error": "Not found"}, 404)
            return

        raw_id = path.rsplit("/", 1)[-1]

        try:
            meeting_id = int(raw_id)
        except ValueError:
            send_json(self, {"error": "Invalid meeting ID"}, 400)
            return

        try:
            payload = read_json_body(self)

            changed = update_meeting(
                meeting_id,
                display_name=payload.get("display_name"),
                is_pinned=payload.get("is_pinned"),
            )

            if not changed:
                send_json(
                    self,
                    {"error": "Meeting not found or no valid changes"},
                    404,
                )
                return

            meeting = get_meeting(meeting_id)

            send_json(self, meeting)

        except Exception as exc:
            print(f"[API ERROR] {exc}")
            send_json(
                self,
                {"error": "Invalid request"},
                400,
            )

    def do_DELETE(self):
        path = urlparse(self.path).path

        if not path.startswith("/api/meetings/"):
            send_json(self, {"error": "Not found"}, 404)
            return

        raw_id = path.rsplit("/", 1)[-1]

        try:
            meeting_id = int(raw_id)
        except ValueError:
            send_json(self, {"error": "Invalid meeting ID"}, 400)
            return

        try:
            deleted = delete_meeting(meeting_id)

            if not deleted:
                send_json(
                    self,
                    {"error": "Meeting not found"},
                    404,
                )
                return

            send_json(
                self,
                {"success": True},
            )

        except Exception as exc:
            print(f"[API ERROR] {exc}")
            send_json(
                self,
                {"error": "Delete failed"},
                500,
            )


if __name__ == "__main__":
    ensure_library_columns()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        APIHandler,
    )

    print(f"MeetingOS API running at http://{HOST}:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping MeetingOS API...")
    finally:
        server.server_close()