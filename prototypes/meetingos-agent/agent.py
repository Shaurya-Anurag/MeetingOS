import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from groq import Groq


# ============================================================
# SETUP
# ============================================================

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise RuntimeError("GROQ_API_KEY is missing from .env")

client = Groq(api_key=api_key)

MODEL = "openai/gpt-oss-20b"
MAX_STEPS = 5


# ============================================================
# MOCK MEETING DATA
# ============================================================

MEETINGS = [
    {
        "id": 1,
        "title": "MeetingOS Architecture Review",
        "date": "2026-09-25",
        "participants": ["Shaurya", "Harshal", "Himakshi"],
        "decisions": [
            "The application will use SQLite for the current local version.",
            "Speaker diarization will use pyannote.",
        ],
        "action_items": [
            {
                "task": "Implement database schema",
                "owner": "Harshal",
                "status": "pending",
            },
            {
                "task": "Refine speaker UI",
                "owner": "Himakshi",
                "status": "in_progress",
            },
        ],
        "summary": (
            "The team reviewed the MeetingOS architecture, "
            "database layer and speaker diarization workflow."
        ),
    },
    {
        "id": 2,
        "title": "AI Agent Planning",
        "date": "2026-09-26",
        "participants": ["Shaurya", "Harshal"],
        "decisions": [
            "The first agent prototype will use local application tools.",
            "The prototype will include basic tool-call logging.",
        ],
        "action_items": [
            {
                "task": "Build the initial tool-calling prototype",
                "owner": "Shaurya",
                "status": "completed",
            }
        ],
        "summary": (
            "The team discussed building a small tool-using agent "
            "and evaluating its tool-selection behaviour."
        ),
    },
]


# ============================================================
# TOOLS
# ============================================================

def search_meetings(query: str) -> dict[str, Any]:
    """Search meetings by title, summary, decisions or participants."""

    query_lower = query.lower()

    results = []

    for meeting in MEETINGS:
        searchable_text = " ".join(
            [
                meeting["title"],
                meeting["summary"],
                meeting["date"],
                " ".join(meeting["participants"]),
                " ".join(meeting["decisions"]),
            ]
        ).lower()

        if query_lower in searchable_text:
            results.append(
                {
                    "id": meeting["id"],
                    "title": meeting["title"],
                    "date": meeting["date"],
                    "summary": meeting["summary"],
                }
            )

    return {
        "query": query,
        "results": results,
    }


def get_meeting(meeting_id: int) -> dict[str, Any]:
    """Return full meeting information."""

    for meeting in MEETINGS:
        if meeting["id"] == meeting_id:
            return meeting

    return {
        "error": f"Meeting {meeting_id} was not found."
    }


def get_action_items(meeting_id: int | None = None) -> dict[str, Any]:
    """Return action items, optionally restricted to one meeting."""

    items = []

    meetings = MEETINGS

    if meeting_id is not None:
        meetings = [
            meeting
            for meeting in MEETINGS
            if meeting["id"] == meeting_id
        ]

    for meeting in meetings:
        for item in meeting["action_items"]:
            items.append(
                {
                    "meeting_id": meeting["id"],
                    "meeting_title": meeting["title"],
                    **item,
                }
            )

    return {
        "action_items": items,
    }


# ============================================================
# TOOL SCHEMAS
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_meetings",
            "description": (
                "Search meeting records using a keyword or phrase. "
                "Use this when you need to discover relevant meetings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword or phrase to search for.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_meeting",
            "description": (
                "Get the full contents of a meeting when its ID is known."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "meeting_id": {
                        "type": "integer",
                        "description": "Meeting ID.",
                    }
                },
                "required": ["meeting_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_action_items",
            "description": (
                "Retrieve action items from meetings. "
                "Optionally provide a meeting ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "meeting_id": {
                        "type": ["integer", "null"],
                        "description": "Optional meeting ID.",
                    }
                },
                "required": ["meeting_id"],
            },
        },
    },
]


# ============================================================
# TOOL EXECUTION
# ============================================================

def execute_tool(name: str, arguments: str) -> dict[str, Any]:

    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return {
            "error": "Malformed JSON arguments."
        }

    try:
        if name == "search_meetings":
            return search_meetings(**args)

        if name == "get_meeting":
            return get_meeting(**args)

        if name == "get_action_items":
            return get_action_items(**args)

        return {
            "error": f"Unknown tool: {name}"
        }

    except Exception as exc:
        return {
            "error": f"Tool execution failed: {exc}"
        }


# ============================================================
# AGENT
# ============================================================

def run_agent(user_input: str) -> dict[str, Any]:

    messages = [
        {
            "role": "system",
            "content": (
                "You are a MeetingOS assistant. "
                "Use tools to retrieve meeting information. "
                "Do not invent meeting facts. "
                "If the available data does not support an answer, "
                "say that the information is unavailable. "
                "Prefer evidence from tools over assumptions."
            ),
        },
        {
            "role": "user",
            "content": user_input,
        },
    ]

    tool_calls_used = []
    start_time = time.perf_counter()

    for step in range(MAX_STEPS):

        print(f"\n--- Agent step {step + 1} ---")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0,
        )

        message = response.choices[0].message

        if not message.tool_calls:

            latency = time.perf_counter() - start_time

            return {
                "answer": message.content or "",
                "steps": step + 1,
                "tool_calls": tool_calls_used,
                "latency": round(latency, 3),
            }

        messages.append(message)

        for tool_call in message.tool_calls:

            name = tool_call.function.name
            arguments = tool_call.function.arguments

            print(f"Tool requested: {name}")
            print(f"Arguments: {arguments}")

            result = execute_tool(name, arguments)

            print(f"Tool result: {result}")

            tool_calls_used.append(
                {
                    "tool": name,
                    "arguments": arguments,
                    "result": result,
                }
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )

    latency = time.perf_counter() - start_time

    return {
        "answer": (
            "I stopped because the maximum number of agent steps "
            "was reached."
        ),
        "steps": MAX_STEPS,
        "tool_calls": tool_calls_used,
        "latency": round(latency, 3),
    }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    question = input("You: ")

    result = run_agent(question)

    print("\nAgent:", result["answer"])
    print("\n--- Run Metrics ---")
    print("Steps:", result["steps"])
    print("Tool calls:", len(result["tool_calls"]))
    print("Latency:", result["latency"], "seconds")