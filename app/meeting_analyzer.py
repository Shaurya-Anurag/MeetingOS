import re


def analyze_transcript(transcript: str) -> dict:
    if not transcript or not transcript.strip():
        return {
            "word_count": 0,
            "duration_seconds": 0,
            "duration_minutes": 0,
            "segment_count": 0,
        }

    segments = transcript.strip().splitlines()

    word_count = len(
        re.findall(r"\b[\w'-]+\b", transcript)
    )

    timestamps = re.findall(
        r"\[(\d+(?:\.\d+)?)s\s*->\s*(\d+(?:\.\d+)?)s\]",
        transcript
    )

    duration_seconds = 0

    if timestamps:
        duration_seconds = max(
            float(end)
            for _, end in timestamps
        )

    return {
        "word_count": word_count,
        "duration_seconds": round(duration_seconds, 2),
        "duration_minutes": round(duration_seconds / 60, 2),
        "segment_count": len(segments),
    }