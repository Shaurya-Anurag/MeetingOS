"""Canonical, deterministic evidence records for MeetingOS."""
from __future__ import annotations

import hashlib
import re
from typing import Any

TRANSCRIPT_LINE_PATTERN = re.compile(r"^\s*\[(\d+(?:\.\d+)?)s\s*->\s*(\d+(?:\.\d+)?)s\]\s*(.*?):\s*(.*)$")


def _transcript_index(transcript: str) -> list[dict[str, Any]]:
    segments = []
    for line in (transcript or "").splitlines():
        match = TRANSCRIPT_LINE_PATTERN.match(line.strip())
        if match:
            segments.append({"start": float(match.group(1)), "end": float(match.group(2)), "speaker": match.group(3).strip(), "text": match.group(4).strip()})
    return segments


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _parse_seconds(value: Any) -> float | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    if ':' in raw:
        try:
            parts = [float(part) for part in raw.split(':')]
            if len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            if len(parts) == 2:
                return parts[0] * 60 + parts[1]
        except ValueError:
            return None
    match = re.search(r'\d+(?:\.\d+)?', raw)
    return float(match.group()) if match else None

def _normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").casefold()))


def build_canonical_evidence(
    meeting_id: int,
    transcript: str,
    intelligence: dict[str, Any] | None = None,
    analytics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build stable evidence rows and derive speaker only from transcript time."""
    segments = _transcript_index(transcript)
    records: dict[str, dict[str, Any]] = {}

    def add(category: str, item_index: int, evidence: dict[str, Any], item: dict[str, Any]):
        text = str(evidence.get("text") or "").strip()
        if not text:
            return
        raw_ts = evidence.get("timestamp")
        timestamp = _parse_seconds(raw_ts)
        segment = None
        if timestamp is not None and segments:
            nearest = min(
                segments,
                key=lambda row: 0 if row["start"] <= timestamp <= row["end"]
                else min(abs(row["start"] - timestamp), abs(row["end"] - timestamp)),
            )
            distance = 0.0 if nearest["start"] <= timestamp <= nearest["end"] else min(
                abs(nearest["start"] - timestamp), abs(nearest["end"] - timestamp)
            )
            if distance <= 2.0:
                segment = nearest
        source_text = segment["text"] if segment else ""
        normalized_evidence = _normalize(text)
        normalized_source = _normalize(source_text)
        verified = bool(
            normalized_evidence and normalized_source
            and normalized_evidence in normalized_source
        )
        # If the evidence is not text-verified, do not attach a guessed speaker.
        speaker = segment["speaker"] if verified and segment else None
        start = segment["start"] if segment else timestamp
        end = segment["end"] if segment else None
        evidence_id = _stable_id(meeting_id, category, item_index, raw_ts, text)
        records[evidence_id] = {
            "evidence_id": evidence_id,
            "meeting_id": int(meeting_id),
            "category": category,
            "item_index": int(item_index),
            "timestamp": timestamp,
            "start_seconds": start,
            "end_seconds": end,
            "speaker": speaker,
            "text": text,
            "transcript_text": source_text or None,
            "verification_status": "verified" if verified else "unverified",
            "item": item,
        }

    for category, items in (intelligence or {}).items():
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            evidence_items = item.get("evidence", [])
            if isinstance(evidence_items, list):
                for evidence in evidence_items:
                    if isinstance(evidence, dict):
                        add(category, index, evidence, item)

    visual = (analytics or {}).get("visual_insights", [])
    if isinstance(visual, list):
        for index, item in enumerate(visual):
            if not isinstance(item, dict):
                continue
            evidence_items = item.get("evidence", [])
            if isinstance(evidence_items, list):
                for evidence in evidence_items:
                    if isinstance(evidence, dict):
                        add("visual_insights", index, evidence, item)

    return list(records.values())


def apply_canonical_evidence(intelligence: dict[str, Any], analytics: dict[str, Any], meeting_id: int, transcript: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Attach stable IDs, verified speakers and explicit ownership-review flags."""
    rows = build_canonical_evidence(meeting_id, transcript, intelligence, analytics)
    intelligence_copy = dict(intelligence or {})
    analytics_copy = dict(analytics or {})
    for row in rows:
        category = row['category']
        collection = analytics_copy.get('visual_insights', []) if category == 'visual_insights' else intelligence_copy.get(category, [])
        index = row['item_index']
        if index >= len(collection) or not isinstance(collection[index], dict):
            continue
        item = collection[index]
        for span in item.get('evidence', []):
            if not isinstance(span, dict):
                continue
            span_timestamp = _parse_seconds(span.get('timestamp'))
            if span_timestamp != row.get('timestamp'):
                continue
            if _normalize(str(span.get('text') or '')) != _normalize(row['text']):
                continue
            span['evidence_id'] = row['evidence_id']
            span['verification_status'] = row['verification_status']
            if row.get('speaker'):
                span['speaker'] = row['speaker']
            else:
                span.pop('speaker', None)
        if category == 'action_items' and row.get('speaker'):
            owner = str(item.get('owner') or '').strip()
            if owner and owner.casefold() != row['speaker'].casefold():
                item['ownership_review'] = {
                    'status': 'mismatch', 'recorded_owner': owner,
                    'evidence_speaker': row['speaker'],
                    'reason': 'Verified transcript speaker differs from the extracted action owner.'
                }
                item['support_status'] = 'needs_review'
    return intelligence_copy, analytics_copy, rows
