import json
import re

from app.llm_service import call_llm
from app.prompts import (
    get_intelligence_system_prompt,
    build_intelligence_user_prompt,
)


# Supports transcript lines such as:
# [38.00s -> 40.00s] Bob: I'll retest the issue tomorrow.
TRANSCRIPT_LINE_PATTERN = re.compile(
    r"^\s*\[(\d+(?:\.\d+)?)s\s*->\s*(\d+(?:\.\d+)?)s\]\s*(.*?):\s*(.*)$"
)
TIMESTAMP_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def build_speaker_index(transcript: str) -> list[dict]:
    """Build a timestamp-indexed lookup from a speaker-aware transcript."""
    entries = []

    for line in (transcript or "").splitlines():
        match = TRANSCRIPT_LINE_PATTERN.match(line)

        if not match:
            continue

        start = float(match.group(1))
        end = float(match.group(2))
        speaker = match.group(3).strip()
        text = match.group(4).strip()

        entries.append({
            "start": start,
            "end": end,
            "speaker": speaker,
            "text": text,
        })

    # Ensure binary-search matching below can rely on sorted segment starts.
    entries.sort(key=lambda entry: entry["start"])
    return entries


def _normalize_evidence_text(text: str) -> str:
    """Normalize text for conservative transcript evidence comparison."""
    return " ".join(re.findall(r"\b\w+\b", (text or "").casefold()))



def validate_evidence(
    intelligence: dict,
    transcript: str,
) -> dict:
    """Verify evidence wording against transcript segments near its timestamp."""
    segments = build_speaker_index(transcript)

    categories = (
        "topics",
        "decisions",
        "action_items",
        "risks_and_concerns",
        "unresolved_questions",
        "contradictions",
    )

    for category in categories:
        items = intelligence.get(category, [])
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            evidence = item.get("evidence", [])
            if not isinstance(evidence, list):
                continue

            for evidence_item in evidence:
                if not isinstance(evidence_item, dict):
                    continue

                text = _normalize_evidence_text(
                    str(evidence_item.get("text", ""))
                )
                timestamp_text = str(evidence_item.get("timestamp", ""))
                timestamp_match = TIMESTAMP_NUMBER_PATTERN.search(timestamp_text)

                if not text or not timestamp_match:
                    evidence_item["verification_status"] = "unverified"
                    continue

                timestamp = float(timestamp_match.group())
                nearby = [
                    segment for segment in segments
                    if segment["start"] - 2.0 <= timestamp <= segment["end"] + 2.0
                ]

                matched = False
                for index, segment in enumerate(nearby):
                    windows = [segment["text"]]

                    if index + 1 < len(nearby):
                        following = nearby[index + 1]
                        if following["start"] - segment["end"] <= 2.0:
                            windows.append(segment["text"] + " " + following["text"])

                    for window in windows:
                        normalized = _normalize_evidence_text(window)
                        if normalized and (
                            text in normalized or normalized in text
                        ):
                            matched = True
                            break

                    if matched:
                        break

                evidence_item["verification_status"] = (
                    "verified" if matched else "unverified"
                )

    return intelligence


def attach_speakers_to_evidence(
    intelligence: dict,
    transcript: str,
) -> dict:
    """Attach speakers deterministically using evidence timestamps."""
    speaker_index = build_speaker_index(transcript)

    if not speaker_index or not isinstance(intelligence, dict):
        return intelligence

    evidence_categories = (
        "topics",
        "decisions",
        "action_items",
        "risks_and_concerns",
        "unresolved_questions",
        "contradictions",
    )

    # Cache repeated timestamp conversions within this response.
    timestamp_cache = {}

    for category in evidence_categories:
        items = intelligence.get(category, [])

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            evidence = item.get("evidence", [])

            if not isinstance(evidence, list):
                continue

            for evidence_item in evidence:
                if not isinstance(evidence_item, dict):
                    continue

                timestamp = evidence_item.get("timestamp")
                if timestamp is None or timestamp == "":
                    continue

                cache_key = str(timestamp).strip()
                if cache_key not in timestamp_cache:
                    match = TIMESTAMP_NUMBER_PATTERN.search(cache_key)
                    timestamp_cache[cache_key] = (
                        float(match.group()) if match else None
                    )

                timestamp_value = timestamp_cache[cache_key]
                if timestamp_value is None:
                    continue

                # Usually evidence timestamps fall inside a segment. If not,
                # find the nearest segment by start/end distance.
                best_match = None
                best_distance = float("inf")

                for segment in speaker_index:
                    if segment["start"] <= timestamp_value <= segment["end"]:
                        best_match = segment
                        best_distance = 0.0
                        break

                    if timestamp_value < segment["start"]:
                        distance = segment["start"] - timestamp_value
                    else:
                        distance = timestamp_value - segment["end"]

                    if distance < best_distance:
                        best_distance = distance
                        best_match = segment

                    # Sorted segments: later starts cannot improve the match
                    # once their start is farther away than the current best.
                    if (
                        segment["start"] > timestamp_value
                        and best_match is not None
                        and segment["start"] - timestamp_value > best_distance
                    ):
                        break

                if best_match and best_distance <= 2.0:
                    evidence_item["speaker"] = best_match["speaker"]
                else:
                    evidence_item.pop("speaker", None)

    return intelligence


def generate_meeting_intelligence(topic: str, transcript: str) -> dict:
    system_prompt = get_intelligence_system_prompt()
    user_prompt = build_intelligence_user_prompt(topic, transcript)

    raw_response = call_llm(system_prompt, user_prompt)

    # Avoid printing the entire potentially large response on every run.
    print(f"[INTELLIGENCE] LLM response received ({len(raw_response)} chars)", flush=True)

    try:
        intelligence = json.loads(raw_response)
    except json.JSONDecodeError:
        return {
            "executive_summary": "Unable to parse meeting intelligence.",
            "topics": [],
            "decisions": [],
            "action_items": [],
            "risks_and_concerns": [],
            "unresolved_questions": [],
            "contradictions": [],
        }

    if not isinstance(intelligence, dict):
        return {
            "executive_summary": "Unable to parse meeting intelligence.",
            "topics": [],
            "decisions": [],
            "action_items": [],
            "risks_and_concerns": [],
            "unresolved_questions": [],
            "contradictions": [],
        }

    intelligence = validate_evidence(intelligence, transcript)
    return attach_speakers_to_evidence(intelligence, transcript)