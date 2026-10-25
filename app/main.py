from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from app.llm_service import MODEL as INTELLIGENCE_MODEL
from app.pipeline_diagnostics import emit_event, new_run_id, stage_event
from Services.Transcription import transcribe_audio
from app.analytics_service import analyze_transcript
from app.intelligence_service import generate_meeting_intelligence
from app.visual_analytics_service import extract_visual_insights
from app.database import (
    initialize_database,
    create_processing_meeting,
    update_meeting_lifecycle,
    save_transcription,
    finalize_processing_meeting,
    get_all_meetings,
    get_meeting,
    delete_meeting,
    get_tasks,
    get_task,
    update_task_status,
    start_meeting_retry,
    recover_stale_meetings,
)


initialize_database()

recovered_count = recover_stale_meetings(stale_after_minutes=45)
if recovered_count:
    print(f"[RECOVERY] Recovered {recovered_count} stale meeting(s).")


# =========================================================
# SPEAKER DETECTION / NAME MAPPING
# =========================================================


_SPEAKER_LINE_PATTERN = re.compile(
    r"^\s*\[\s*(\d+(?:\.\d+)?)s\s*->\s*"
    r"(\d+(?:\.\d+)?)s\s*\]\s*"
    r"(SPEAKER_\d+|UNKNOWN)\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)

_SPEAKER_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])SPEAKER_\d+(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def extract_speaker_info(transcript: str) -> dict[str, list[str]]:
    """Extract speaker IDs and up to two sample utterances per speaker."""
    speakers: dict[str, list[str]] = {}

    for line in (transcript or "").splitlines():
        match = _SPEAKER_LINE_PATTERN.match(line.strip())

        if match:
            speaker = match.group(3).upper()
            utterance = match.group(4).strip()
        else:
            # Support speaker-labelled lines without timestamps.
            match = re.match(
                r"^\s*(SPEAKER_\d+|UNKNOWN)\s*:\s*(.*?)\s*$",
                line,
                re.IGNORECASE,
            )
            if not match:
                continue

            speaker = match.group(1).upper()
            utterance = match.group(2).strip()

        # UNKNOWN is not a detected speaker.
        if speaker == "UNKNOWN":
            continue

        samples = speakers.setdefault(speaker, [])
        if utterance and len(samples) < 2:
            samples.append(utterance)

    return speakers



def prepare_meeting(
    audio_path: str | None,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Create a durable meeting and persist its transcript."""
    run_id = run_id or new_run_id()
    total_start = time.perf_counter()
    meeting_id = create_processing_meeting("Meeting Discussion", run_id=run_id)
    current_stage = "audio_ingestion"

    def fail(message: str, exc: Exception | None = None) -> dict[str, Any]:
        try:
            update_meeting_lifecycle(
                meeting_id,
                "failed",
                current_stage=current_stage,
                run_id=run_id,
                error_message=message,
                error_type=type(exc).__name__ if exc else None,
            )
        except Exception:
            pass

        emit_event(
            run_id,
            "prepare_meeting",
            "failed",
            duration_ms=(time.perf_counter() - total_start) * 1000,
            meeting_id=meeting_id,
            error_type=type(exc).__name__ if exc else None,
            metadata={"failed_stage": current_stage},
        )
        return {
            "ok": False,
            "meeting_id": meeting_id,
            "run_id": run_id,
            "transcript": "",
            "speakers": {},
            "error": message,
        }

    if not audio_path:
        return fail("Please upload a meeting recording first.")

    path = Path(audio_path)
    try:
        file_exists = path.is_file()
        file_size = path.stat().st_size if file_exists else 0
    except OSError as exc:
        return fail("Could not access the uploaded recording.", exc)

    if not file_exists or not file_size:
        return fail("The uploaded recording is missing or empty.")

    emit_event(
        run_id,
        "audio_ingestion",
        "success",
        meeting_id=meeting_id,
        metadata={"file_extension": path.suffix.lower(), "file_size_bytes": file_size},
    )

    try:
        current_stage = "transcribing"
        update_meeting_lifecycle(
            meeting_id,
            "transcribing",
            current_stage=current_stage,
            run_id=run_id,
        )

        with stage_event(
            run_id,
            "transcription_and_diarization",
            metadata={"file_extension": path.suffix.lower()},
        ) as stage:
            transcript = transcribe_audio(audio_path, run_id=run_id)
            stage["meeting_id"] = meeting_id
            stage["metadata"]["transcript_line_count"] = len(
                [line for line in transcript.splitlines() if line.strip()]
            )

        if not transcript or not transcript.strip():
            raise ValueError("Transcription returned an empty transcript.")

        current_stage = "speaker_extraction"
        with stage_event(run_id, "speaker_extraction") as stage:
            speakers = extract_speaker_info(transcript)
            stage["meeting_id"] = meeting_id
            stage["metadata"]["detected_speaker_count"] = len(speakers)

        current_stage = "transcript_persistence"
        # Save transcript durably before intelligence generation.
        save_transcription(meeting_id, transcript, speakers, run_id=run_id)

    except Exception as exc:
        return fail(
            f"Audio processing failed: {type(exc).__name__}. "
            "Check the recording and transcription dependencies, then retry.",
            exc,
        )

    emit_event(
        run_id,
        "prepare_meeting",
        "success",
        duration_ms=(time.perf_counter() - total_start) * 1000,
        meeting_id=meeting_id,
        metadata={
            "transcript_line_count": len(
                [line for line in transcript.splitlines() if line.strip()]
            ),
            "detected_speaker_count": len(speakers),
            "transcript_saved": True,
        },
    )

    return {
        "ok": True,
        "meeting_id": meeting_id,
        "run_id": run_id,
        "transcript": transcript,
        "speakers": speakers,
        "error": None,
    }


def finalize_speakers(
    transcript: str,
    speakers: dict,
    speaker_confirmation: str | None,
    names: list[str | None],
) -> dict[str, Any]:
    """Apply optional human-provided names to the speaker-aware transcript."""
    if not transcript:
        return {
            "ok": False,
            "transcript": transcript or "",
            "error": "No meeting transcript is available.",
        }

    if speaker_confirmation == "No":
        return {"ok": True, "transcript": transcript, "error": None}

    speaker_list = list((speakers or {}).keys())
    final_transcript = transcript

    for index, speaker in enumerate(speaker_list):
        if index >= len(names):
            break
        name = names[index]
        if name and name.strip():
            # Replace only the complete speaker token, never a substring of another ID.
            token_pattern = re.compile(
                rf"(?<![A-Za-z0-9_]){re.escape(speaker)}(?![A-Za-z0-9_])"
            )
            final_transcript = token_pattern.sub(lambda _match: name.strip(), final_transcript)

    return {"ok": True, "transcript": final_transcript, "error": None}


# =========================================================
# MEETING INTELLIGENCE
# =========================================================


def generate_brief(
    transcript: str,
    speakers: dict,
    topic: str | None,
    *,
    run_id: str | None = None,
    meeting_id: int | None = None,
) -> dict[str, Any]:
    """Generate intelligence for an existing lifecycle-managed meeting."""
    run_id = run_id or new_run_id()
    total_start = time.perf_counter()
    warnings: list[str] = []
    current_stage = "input_validation"

    if not meeting_id or not run_id:
        return {"ok": False, "error": "Missing meeting or processing-run ID. Please retry."}
    if not transcript or not transcript.strip():
        return {"ok": False, "error": "No meeting transcript is available."}

    topic = (topic or "").strip() or "Meeting Discussion"

    try:
        current_stage = "transcript_persistence"
        # Preserve speaker-name edits made during speaker review.
        save_transcription(meeting_id, transcript, speakers, run_id=run_id)

        current_stage = "analytics"
        with stage_event(run_id, "analytics") as stage:
            analytics = analyze_transcript(transcript)
            stage["meeting_id"] = meeting_id
            stage["metadata"]["result_type"] = type(analytics).__name__
        if not isinstance(analytics, dict):
            raise ValueError("Transcript analytics returned an invalid response.")

        current_stage = "meeting_intelligence"
        with stage_event(run_id, "meeting_intelligence") as stage:
            intelligence = generate_meeting_intelligence(topic=topic, transcript=transcript)
            stage["meeting_id"] = meeting_id
            stage["metadata"]["model"] = INTELLIGENCE_MODEL

        if not isinstance(intelligence, dict):
            raise ValueError("The intelligence model returned an invalid response.")
        if not isinstance(intelligence.get("action_items", []), list):
            raise ValueError("The intelligence response contains invalid action items.")

        current_stage = "validating"
        update_meeting_lifecycle(
            meeting_id,
            "validating",
            current_stage=current_stage,
            run_id=run_id,
        )

        visual_insights = []
        current_stage = "visual_insights"
        try:
            visual_diagnostics: dict[str, Any] = {}
            with stage_event(run_id, "visual_insights") as stage:
                visual_insights = extract_visual_insights(
                    transcript, diagnostics=visual_diagnostics
                )
                stage["meeting_id"] = meeting_id
                stage["metadata"].update(visual_diagnostics)
            if not isinstance(visual_insights, list):
                raise ValueError("Visual insights returned an invalid response.")
            analytics["visual_insights"] = visual_insights
        except Exception as visual_exc:
            warning = (
                "Visual insights could not be generated "
                f"({type(visual_exc).__name__}). The core meeting results will still be saved."
            )
            warnings.append(warning)
            emit_event(
                run_id,
                "visual_insights",
                "failed",
                meeting_id=meeting_id,
                error_type=type(visual_exc).__name__,
                metadata={"optional": True},
            )

        current_stage = "persistence"
        result = finalize_processing_meeting(
            meeting_id,
            run_id=run_id,
            topic=topic,
            intelligence=intelligence,
            analytics=analytics,
            warnings=warnings,
        )

        duration_ms = (time.perf_counter() - total_start) * 1000
        emit_event(
            run_id,
            "generate_brief",
            "success",
            duration_ms=duration_ms,
            meeting_id=meeting_id,
            metadata={"status": result["status"], "warning_count": len(warnings)},
        )

        return {
            "ok": True,
            "meeting_id": meeting_id,
            "run_id": run_id,
            "status": result["status"],
            "topic": topic,
            "transcript": transcript,
            "speakers": speakers,
            "intelligence": intelligence,
            "analytics": analytics,
            "visual_insights": visual_insights,
            "warnings": warnings,
            "error": None,
        }

    except Exception as exc:
        # Preserve the transcript and record the stage that actually failed.
        try:
            update_meeting_lifecycle(
                meeting_id,
                "needs_retry",
                current_stage=current_stage,
                run_id=run_id,
                error_message=(
                    "Meeting analysis did not complete. The transcript remains saved; retry processing."
                ),
                error_type=type(exc).__name__,
            )
        except Exception:
            pass

        emit_event(
            run_id,
            "generate_brief",
            "failed",
            duration_ms=(time.perf_counter() - total_start) * 1000,
            meeting_id=meeting_id,
            error_type=type(exc).__name__,
            metadata={"failed_stage": current_stage},
        )
        return {
            "ok": False,
            "meeting_id": meeting_id,
            "run_id": run_id,
            "error": (
                f"Meeting analysis failed ({type(exc).__name__}) during {current_stage}. "
                "The transcript was saved if transcription completed. "
                "Retry after checking the model service and diagnostics."
            ),
        }


# =========================================================
# SAVED MEETINGS
# =========================================================


def load_saved_meeting(meeting_id: int | None) -> dict[str, Any]:
    """Load a saved meeting without rerunning the AI pipeline."""
    if meeting_id is None:
        return {"ok": False, "error": "Select a meeting from history first."}

    meeting = get_meeting(meeting_id)
    if meeting is None:
        return {"ok": False, "error": "Meeting could not be found."}

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


def remove_saved_meeting(meeting_id: int | None) -> dict[str, Any]:
    """Delete a saved meeting and its cascaded tasks."""
    if meeting_id is None:
        return {"ok": False, "error": "Select a meeting to delete."}

    deleted = delete_meeting(meeting_id)
    if not deleted:
        return {"ok": False, "error": "Meeting could not be found."}

    print(f"Meeting deleted: {meeting_id}")
    return {"ok": True, "meeting_id": meeting_id, "error": None}


def retry_meeting(meeting_id: int | None) -> dict[str, Any]:
    """Retry analysis from a saved transcript without retranscribing audio."""
    if meeting_id is None:
        return {"ok": False, "error": "Select a meeting to retry."}

    meeting = get_meeting(meeting_id)
    if meeting is None:
        return {"ok": False, "error": "Meeting could not be found."}

    transcript = (meeting.get("transcript") or "").strip()
    if not transcript:
        return {"ok": False, "error": "This meeting has no saved transcript to retry."}

    try:
        attempt = start_meeting_retry(meeting_id)
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}

    return generate_brief(
        transcript,
        meeting.get("speaker_data") or {},
        meeting.get("topic") or "Meeting Discussion",
        run_id=attempt["run_id"],
        meeting_id=meeting_id,
    )


# =========================================================
# TASKS
# =========================================================


def list_tasks(status_filter: str = "All") -> list[dict[str, Any]]:
    """Return workspace tasks, optionally filtered by status."""
    if status_filter == "All":
        return get_tasks()
    return get_tasks(status=status_filter)


def get_selected_task(task_id: int | None) -> dict[str, Any] | None:
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


def workspace_analytics_data() -> dict[str, Any]:
    """Calculate workspace-level meeting/task metrics defensively."""
    meetings = get_all_meetings()
    tasks = get_tasks()

    total_duration = sum((meeting.get("duration_seconds") or 0) for meeting in meetings)
    average_duration = total_duration / len(meetings) if meetings else 0

    pending = sum(1 for task in tasks if task.get("status") == "Pending")
    in_progress = sum(1 for task in tasks if task.get("status") == "In Progress")
    completed = sum(1 for task in tasks if task.get("status") == "Completed")

    total_tasks = len(tasks)
    completion_rate = completed / total_tasks * 100 if total_tasks else 0
    recent = sorted(
        meetings,
        key=lambda meeting: meeting.get("created_at") or "",
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
        retry_meeting=retry_meeting,
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
