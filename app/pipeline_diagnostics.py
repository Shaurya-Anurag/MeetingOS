from __future__ import annotations

import json
import logging
import time
import uuid

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

LOGGER = logging.getLogger("meetingos.pipeline")

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "pipeline.jsonl"


def new_run_id() -> str:
    """Create a unique identifier for one processing attempt."""
    return str(uuid.uuid4())


def emit_event(
    run_id: str,
    stage: str,
    status: str,
    *,
    duration_ms: float | None = None,
    meeting_id: int | None = None,
    metadata: dict | None = None,
    error_type: str | None = None,
) -> None:
    """Append one structured event without logging meeting content."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        "meeting_id": meeting_id,
        "metadata": metadata or {},
        "error_type": error_type,
    }

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        # Diagnostics must never cause meeting processing to fail.
        LOGGER.exception("Could not write pipeline diagnostics.")


@contextmanager
def stage_event(
    run_id: str,
    stage: str,
    *,
    metadata: dict | None = None,
) -> Iterator[dict]:
    """Record the outcome and duration of a pipeline stage."""
    started = time.perf_counter()
    result = {"metadata": dict(metadata or {})}

    emit_event(
        run_id,
        stage,
        "started",
        metadata=result["metadata"],
    )

    try:
        yield result
    except Exception as exc:
        emit_event(
            run_id,
            stage,
            "failed",
            duration_ms=(time.perf_counter() - started) * 1000,
            metadata=result["metadata"],
            error_type=type(exc).__name__,
        )
        raise
    else:
        emit_event(
            run_id,
            stage,
            result.get("status", "success"),
            duration_ms=(time.perf_counter() - started) * 1000,
            meeting_id=result.get("meeting_id"),
            metadata=result["metadata"],
        )
