"""Canonical, deterministic evidence records for MeetingOS."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.ask_service import build_transcript_index


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").casefold()))


def build_canonical_evidence(
    meeting_id: int,
    transcript: str,
    intelligence: dict[str, Any] | None = None,
    analytics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build stable evidence rows and derive speaker only from transcript time."""
    segments = build_transcript_index(transcript)
    records: dict[str, dict[str, Any]] = {}

    def add(category: str, item_index: int, evidence: dict[str, Any], item: dict[str, Any]):
        text = str(evidence.get("text") or "").strip()
        if not text:
            return
        raw_ts = evidence.get("timestamp")
        match = re.search(r"\d+(?:\.\d+)?", str(raw_ts or ""))
        timestamp = float(match.group()) if match else None
        segment = None
        if timestamp is not None and segments:
            segment = min(
                segments,
                key=lambda row: 0 if row["start"] <= timestamp <= row["end"]
                else min(abs(row["start"] - timestamp), abs(row["end"] - timestamp)),
            )
        source_text = segment["text"] if segment else ""
        normalized_evidence = _normalize(text)
        normalized_source = _normalize(source_text)
        verified = bool(
            normalized_evidence and normalized_source
            and (normalized_evidence in normalized_source or normalized_source in normalized_evidence)
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
