from __future__ import annotations

import re

from Services.Transcription import transcribe_audio
from app.analytics_service import analyze_transcript
from app.intelligence_service import generate_meeting_intelligence
from app.visual_analytics_service import extract_visual_insights
from app.database import (
    initialize_database,
    save_meeting,
    get_all_meetings,
    search_meetings,
    get_meeting,
    delete_meeting,
    get_tasks,
    get_task,
    update_task_status,
)


initialize_database()


# =========================================================
# SPEAKER DETECTION / NAME MAPPING
# =========================================================


def extract_speaker_info(transcript: str) -> dict[str, list[str]]:
    """Extract detected speakers and up to two sample utterances."""
    pattern = re.compile(
        r"\[(\d+(?:\.\d+)?)s\s*->\s*(\d+(?:\.\d+)?)s\]\s+"
        r"(SPEAKER_\d+):\s*(.*)"
    )

    speakers: dict[str, list[str]] = {}

    for line in (transcript or "").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue

        speaker = match.group(3)
        text = match.group(4).strip()
        speakers.setdefault(speaker, [])

        if text and len(speakers[speaker]) < 2:
            speakers[speaker].append(text)

    return speakers


def prepare_meeting(audio_path: str | None) -> dict:
    """
    Transcribe the recording and detect speakers.

    This function contains application logic only. UI visibility/state
    decisions are handled by app.ui.
    """
    if not audio_path:
        return {
            "ok": False,
            "transcript": "",
            "speakers": {},
            "error": "Please upload a meeting recording first.",
        }

    print("Transcribing audio and detecting speakers...")

    transcript = transcribe_audio(audio_path)
    speakers = extract_speaker_info(transcript)

    return {
        "ok": True,
        "transcript": transcript,
        "speakers": speakers,
        "error": None,
    }


def finalize_speakers(
    transcript: str,
    speakers: dict,
    speaker_confirmation: str | None,
    names: list[str | None],
) -> dict:
    """Apply optional human-provided names to the speaker-aware transcript."""
    if not transcript:
        return {
            "ok": False,
            "transcript": transcript or "",
            "error": "No meeting transcript is available.",
        }

    if speaker_confirmation == "No":
        return {
            "ok": True,
            "transcript": transcript,
            "error": None,
        }

    speaker_list = list((speakers or {}).keys())
    final_transcript = transcript

    for index, speaker in enumerate(speaker_list):
        if index >= len(names):
            break

        name = names[index]
        if name and name.strip():
            final_transcript = final_transcript.replace(
                speaker,
                name.strip(),
            )

    return {
        "ok": True,
        "transcript": final_transcript,
        "error": None,
    }


# =========================================================
# MEETING INTELLIGENCE
# =========================================================


def generate_brief(
    transcript: str,
    speakers: dict,
    topic: str | None,
) -> dict:
    """Generate and persist all R2 meeting intelligence as structured data."""
    if not transcript:
        return {
            "ok": False,
            "error": "No meeting transcript available.",
        }

    topic = (topic or "").strip() or "Meeting Discussion"

    print("Calculating analytics...")
    analytics = analyze_transcript(transcript)

    print("Generating meeting intelligence...")
    intelligence = generate_meeting_intelligence(
        topic=topic,
        transcript=transcript,
    )

    print("Extracting quantitative insights...")
    visual_insights = extract_visual_insights(transcript)
    analytics["visual_insights"] = visual_insights

    print("Saving meeting...")
    meeting_id = save_meeting(
        topic=topic,
        transcript=transcript,
        intelligence=intelligence,
        analytics=analytics,
        speaker_data=speakers,
    )
    print(f"Meeting saved with ID: {meeting_id}")

    return {
        "ok": True,
        "meeting_id": meeting_id,
        "topic": topic,
        "transcript": transcript,
        "speakers": speakers,
        "intelligence": intelligence,
        "analytics": analytics,
        "visual_insights": visual_insights,
        "error": None,
    }


# =========================================================
# SAVED MEETINGS
# =========================================================


def load_saved_meeting(meeting_id: int | None) -> dict:
    """Load a saved meeting without rerunning the AI pipeline."""
    if meeting_id is None:
        return {
            "ok": False,
            "error": "Select a meeting from history first.",
        }

    meeting = get_meeting(meeting_id)
    if meeting is None:
        return {
            "ok": False,
            "error": "Meeting could not be found.",
        }

    analytics = meeting.get("analytics") or {}

    return {
        "ok": True,
        "meeting": meeting,
        "topic": meeting.get("topic") or "Meeting Discussion",
        "intelligence": meeting.get("intelligence") or {},
        "analytics": analytics,
        "visual_insights": analytics.get("visual_insights", []),
        "error": None,
    }


def remove_saved_meeting(meeting_id: int | None) -> dict:
    """Delete a saved meeting and its cascaded tasks."""
    if meeting_id is None:
        return {
            "ok": False,
            "error": "Select a meeting to delete.",
        }

    deleted = delete_meeting(meeting_id)
    if not deleted:
        return {
            "ok": False,
            "error": "Meeting could not be found.",
        }

    print(f"Meeting deleted: {meeting_id}")
    return {
        "ok": True,
        "meeting_id": meeting_id,
        "error": None,
    }


# =========================================================
# TASKS
# =========================================================


def list_tasks(status_filter: str = "All") -> list[dict]:
    """Return workspace tasks, optionally filtered by status."""
    if status_filter == "All":
        return get_tasks()
    return get_tasks(status=status_filter)


def get_selected_task(task_id: int | None) -> dict | None:
    """Return one workspace task."""
    if task_id is None:
        return None
    return get_task(task_id)


def set_task_status(task_id: int | None, status: str) -> bool:
    """Persist a task status change."""
    if task_id is None:
        return False
    return update_task_status(task_id, status)


# =========================================================
# WORKSPACE ANALYTICS DATA
# =========================================================


def workspace_analytics_data() -> dict:
    """Calculate workspace-level meeting/task metrics."""
    meetings = get_all_meetings()
    tasks = get_tasks()

    total_duration = sum((meeting["duration_seconds"] or 0) for meeting in meetings)
    average_duration = total_duration / len(meetings) if meetings else 0

    pending = sum(1 for task in tasks if task["status"] == "Pending")
    in_progress = sum(1 for task in tasks if task["status"] == "In Progress")
    completed = sum(1 for task in tasks if task["status"] == "Completed")

    total_tasks = len(tasks)
    completion_rate = completed / total_tasks * 100 if total_tasks else 0

    recent = sorted(
        meetings,
        key=lambda meeting: meeting["created_at"],
        reverse=True,
    )[:8]

    return {
        "meeting_count": len(meetings),
        "total_minutes": total_duration / 60,
        "average_duration_minutes": average_duration / 60,
        "total_tasks": total_tasks,
        "completed_tasks": completed,
        "completion_rate": completion_rate,
        "pending_tasks": pending,
        "in_progress_tasks": in_progress,
        "completed_tasks_count": completed,
        "recent_meetings": recent,
    }


# =========================================================
# APPLICATION ENTRYPOINT
# =========================================================


def create_app():
    """Build the Gradio application through the isolated UI layer."""
    from app.ui import build_app

    return build_app(
        prepare_meeting=prepare_meeting,
        finalize_speakers=finalize_speakers,
        generate_brief=generate_brief,
        load_saved_meeting=load_saved_meeting,
        remove_saved_meeting=remove_saved_meeting,
        list_tasks=list_tasks,
        get_selected_task=get_selected_task,
        set_task_status=set_task_status,
        workspace_analytics_data=workspace_analytics_data,
    )


if __name__ == "__main__":
    demo = create_app()
    demo.queue().launch()
