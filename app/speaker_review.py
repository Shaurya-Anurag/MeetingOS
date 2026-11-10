from __future__ import annotations

import re
from typing import Any

SPEAKER_LINE_PATTERN = re.compile(
    r"^\s*\[\s*(\d+(?:\.\d+)?)s\s*->\s*"
    r"(\d+(?:\.\d+)?)s\s*\]\s*"
    r"(SPEAKER_\d+|UNKNOWN)\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)


def transcript_to_review_rows(transcript: str) -> list[list[str]]:
    """Convert timestamped transcript lines into editable review-table rows."""
    rows: list[list[str]] = []
    for line_number, line in enumerate((transcript or "").splitlines(), 1):
        if not line.strip():
            continue
        match = SPEAKER_LINE_PATTERN.match(line.strip())
        if not match:
            raise ValueError(
                f"Line {line_number} is not a timestamped speaker segment and cannot be reviewed in the table."
            )
        timestamp = f"{match.group(1)}s -> {match.group(2)}s"
        rows.append([timestamp, match.group(3).upper(), match.group(4)])
    return rows


def validate_speaker_review_rows(
    original_transcript: str,
    reviewed_rows: Any,
) -> dict[str, Any]:
    """Validate editable review rows and rebuild the canonical transcript."""
    original_rows = transcript_to_review_rows(original_transcript)
    if not isinstance(reviewed_rows, (list, tuple)):
        raise ValueError("Speaker review data is missing or malformed.")
    rows = [list(row) for row in reviewed_rows]
    if len(rows) != len(original_rows):
        raise ValueError("Transcript review changed the number of utterance rows.")

    allowed = {row[1] for row in original_rows}
    allowed.add("UNKNOWN")
    corrected_lines = []
    changed = 0

    for index, (original, reviewed) in enumerate(zip(original_rows, rows), 1):
        if len(reviewed) != 3:
            raise ValueError(f"Row {index}: expected timestamp, speaker, and utterance columns.")
        timestamp, speaker, utterance = (str(value or "").strip() for value in reviewed)
        if timestamp != original[0] or utterance != original[2]:
            raise ValueError(f"Row {index}: only the speaker label may be changed.")
        speaker = speaker.upper()
        if speaker not in allowed:
            raise ValueError(f"Row {index}: '{speaker}' is not a detected speaker or UNKNOWN.")
        changed += speaker != original[1]
        start, end = original[0].split(" -> ")
        corrected_lines.append(f"[{start} -> {end}] {speaker}: {original[2]}")
    return {"transcript": "\n".join(corrected_lines), "changed_labels": int(changed)}
