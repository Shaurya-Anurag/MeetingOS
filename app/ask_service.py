from __future__ import annotations

import json
import re
from typing import Any

from app.database import get_all_meetings, get_meeting
from app.llm_service import call_llm


STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were",
    "what", "why", "when", "where", "who", "how",
    "did", "does", "do", "we", "they", "it", "this",
    "that", "to", "of", "for", "in", "on", "and", "or",
    "our", "their", "about", "from", "with", "by",
    "be", "been", "being", "tell", "me",
}

TRANSCRIPT_LINE_PATTERN = re.compile(
    r"\[(\d+(?:\.\d+)?)s\s*->\s*(\d+(?:\.\d+)?)s\]\s+"
    r"(.+?):\s*(.*)"
)


# =========================================================
# BASIC TEXT HELPERS
# =========================================================

def _tokenize(text: str) -> set[str]:
    words = re.findall(
        r"[a-zA-Z0-9']+",
        (text or "").lower(),
    )

    return {
        word
        for word in words
        if len(word) > 1 and word not in STOPWORDS
    }


def _numbers(text: str) -> set[str]:
    return set(
        re.findall(
            r"\b\d+(?:\.\d+)?\b",
            text or "",
        )
    )


def _normalized(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        (text or "").strip().lower(),
    )


def _score_text(query: str, text: str) -> float:
    """
    Lexical relevance score.

    Exact phrase + token overlap + numeric/date matching.
    Numbers are weighted heavily because:
        September 14 != September 22
    """

    query_normalized = _normalized(query)
    text_normalized = _normalized(text)

    query_tokens = _tokenize(query)
    text_tokens = _tokenize(text)

    if not query_tokens:
        return 0.0

    overlap = query_tokens & text_tokens

    score = len(overlap) * 2.0

    if query_normalized and query_normalized in text_normalized:
        score += 8.0

    query_numbers = _numbers(query)
    text_numbers = _numbers(text)

    if query_numbers:
        score += len(query_numbers & text_numbers) * 6.0

    return score


def _question_intents(query: str) -> set[str]:
    text = _normalized(query)

    intents = set()

    if re.search(
        r"\b(decision|decided|choose|chosen|approved|"
        r"approve|target|launch|final|commitment)\b",
        text,
    ):
        intents.add("decision")

    if re.search(
        r"\b(task|action|assigned|owner|responsible|"
        r"deadline|finish|complete|deliver)\b",
        text,
    ):
        intents.add("action")

    if re.search(
        r"\b(revenue|sales|count|number|"
        r"percent|percentage|growth|"
        r"trend|average|metric|metrics|"
        r"rate|increase|decrease|"
        r"comparison|compare)\b",
        text,
    ):
        intents.add("analytics")

    return intents


# =========================================================
# TRANSCRIPT / PROVENANCE
# =========================================================

def build_transcript_index(
    transcript: str,
) -> list[dict[str, Any]]:
    """
    Parse the final speaker-aware transcript.

    Example:
    [27.23s -> 29.10s] Harshal: I will finish the campaign.
    """

    segments = []

    for line in (transcript or "").splitlines():

        match = TRANSCRIPT_LINE_PATTERN.match(
            line.strip()
        )

        if not match:
            continue

        start = float(match.group(1))
        end = float(match.group(2))
        speaker = match.group(3).strip()
        text = match.group(4).strip()

        segments.append({
            "start": start,
            "end": end,
            "speaker": speaker,
            "text": text,
        })

    return segments


def _timestamp_number(timestamp: Any) -> float | None:
    if timestamp is None:
        return None

    match = re.search(
        r"\d+(?:\.\d+)?",
        str(timestamp),
    )

    if not match:
        return None

    try:
        return float(match.group())
    except ValueError:
        return None


def _match_transcript_segment(
    segments: list[dict[str, Any]],
    timestamp: Any = None,
    text_hint: str = "",
) -> dict[str, Any] | None:

    timestamp_value = _timestamp_number(timestamp)

    best = None
    best_score = float("-inf")

    for segment in segments:

        score = 0.0

        # Strongest signal: timestamp.
        if timestamp_value is not None:

            if (
                segment["start"]
                <= timestamp_value
                <= segment["end"]
            ):
                score += 100.0

            else:
                score -= abs(
                    segment["start"] - timestamp_value
                )

        # Secondary signal: text similarity.
        if text_hint:
            score += (
                len(
                    _tokenize(text_hint)
                    & _tokenize(segment["text"])
                )
                * 3.0
            )

        if score > best_score:
            best_score = score
            best = segment

    return best


def _source_from_segment(
    meeting: dict,
    segment: dict[str, Any],
    source_type: str = "Transcript",
) -> dict[str, Any]:

    return {
        "meeting_id": meeting["id"],
        "meeting_topic": meeting.get(
            "topic",
            "Meeting",
        ),
        "speaker": segment.get(
            "speaker",
            "Unknown speaker",
        ),
        "timestamp": (
            f'{segment["start"]:.2f}s'
        ),
        "evidence": segment.get(
            "text",
            "",
        ),
        "source_type": source_type,
    }


# =========================================================
# INTELLIGENCE RETRIEVAL
# =========================================================

def _flatten_intelligence(
    meeting: dict,
    query: str,
) -> list[dict[str, Any]]:

    intelligence = meeting.get(
        "intelligence"
    ) or {}

    segments = build_transcript_index(
        meeting.get("transcript", "")
    )

    intents = _question_intents(query)

    candidates = []

    categories = [
        "topics",
        "decisions",
        "action_items",
        "risks_and_concerns",
        "unresolved_questions",
        "contradictions",
    ]

    for category in categories:

        items = intelligence.get(
            category,
            [],
        )

        if not isinstance(items, list):
            continue

        for item in items:

            if not isinstance(item, dict):
                continue

            # Searchable representation of the structured item.
            searchable_parts = []

            for key, value in item.items():

                if key == "evidence":
                    continue

                if isinstance(value, str):
                    searchable_parts.append(value)

                elif isinstance(value, list):
                    searchable_parts.extend(
                        str(v)
                        for v in value
                        if isinstance(v, str)
                    )

            searchable_text = " ".join(
                searchable_parts
            )

            base_score = _score_text(
                query,
                searchable_text,
            )

            # A date/number mentioned in the user's question
            # should retrieve relevant actions, decisions, deadlines,
            # etc. regardless of category.
            query_numbers = _numbers(query)
            item_numbers = _numbers(searchable_text)

            if query_numbers:
                matched_numbers = query_numbers & item_numbers

                if matched_numbers:
                    base_score += 10.0

            # Category-aware ranking.
            if (
                "decision" in intents
                and category == "decisions"
            ):
                base_score += 5.0

            if (
                "action" in intents
                and category == "action_items"
            ):
                base_score += 5.0

            if base_score <= 0:
                continue

            evidence_items = item.get(
                "evidence",
                [],
            )

            if not isinstance(
                evidence_items,
                list,
            ):
                evidence_items = []

            # Prefer individual evidence spans.
            if evidence_items:

                for evidence in evidence_items:

                    if not isinstance(
                        evidence,
                        dict,
                    ):
                        continue

                    evidence_text = str(
                        evidence.get(
                            "text",
                            "",
                        )
                    ).strip()

                    query_numbers = _numbers(query)
                    evidence_numbers = _numbers(evidence_text)

                    evidence_score = (
                        base_score
                        + _score_text(
                            query,
                            evidence_text,
                        )
                    )

                    if query_numbers & evidence_numbers:
                        evidence_score += 15.0

                    timestamp = evidence.get(
                        "timestamp"
                    )

                    evidence_score = (
                        base_score
                        + _score_text(
                            query,
                            evidence_text,
                        )
                    )

                    matched_segment = (
                        _match_transcript_segment(
                            segments,
                            timestamp,
                            evidence_text,
                        )
                    )

                    candidates.append({
                        "score": evidence_score,
                        "kind": "intelligence",
                        "category": category,
                        "meeting": meeting,
                        "item": item,
                        "evidence": evidence,
                        "segment": matched_segment,
                    })

            else:
                candidates.append({
                    "score": base_score,
                    "kind": "intelligence",
                    "category": category,
                    "meeting": meeting,
                    "item": item,
                    "evidence": None,
                    "segment": None,
                })

    return candidates


# =========================================================
# ANALYTICS RETRIEVAL
# =========================================================

def _analytics_search_text(
    insight: dict[str, Any],
) -> str:

    parts = [
        str(insight.get("title", "")),
        str(insight.get("metric", "")),
        str(insight.get("unit", "")),
        str(insight.get("trend", "")),
    ]

    for point in insight.get(
        "data",
        [],
    ):

        if not isinstance(point, dict):
            continue

        parts.append(
            str(point.get("label", ""))
        )

        parts.append(
            str(point.get("value", ""))
        )

    for evidence in insight.get(
        "evidence",
        [],
    ):

        if not isinstance(evidence, dict):
            continue

        parts.append(
            str(evidence.get("text", ""))
        )

    return " ".join(parts)


def _analytics_candidates(
    meeting: dict,
    query: str,
) -> list[dict[str, Any]]:

    analytics = meeting.get(
        "analytics"
    ) or {}

    visual_insights = analytics.get(
        "visual_insights",
        [],
    )

    if not isinstance(
        visual_insights,
        list,
    ):
        return []

    intents = _question_intents(query)

    if "analytics" not in intents:
        # Still allow analytics when the query
        # directly matches the metric.
        pass

    segments = build_transcript_index(
        meeting.get("transcript", "")
    )

    candidates = []

    for insight in visual_insights:

        if not isinstance(
            insight,
            dict,
        ):
            continue

        searchable_text = (
            _analytics_search_text(
                insight
            )
        )

        score = _score_text(
            query,
            searchable_text,
        )


        if score <= 0:
            continue

        evidence_items = insight.get(
            "evidence",
            [],
        )

        if not isinstance(
            evidence_items,
            list,
        ):
            evidence_items = []

        # Add deterministic first/last change information.
        points = [
            point
            for point in insight.get(
                "data",
                [],
            )
            if isinstance(point, dict)
        ]

        derived = {}

        if len(points) >= 2:

            first = points[0].get("value")
            last = points[-1].get("value")

            try:
                first_value = float(first)
                last_value = float(last)

                delta = (
                    last_value
                    - first_value
                )

                derived["start_value"] = (
                    first_value
                )

                derived["end_value"] = (
                    last_value
                )

                derived["absolute_change"] = (
                    delta
                )

                if first_value != 0:
                    derived["percent_change"] = (
                        delta
                        / abs(first_value)
                        * 100
                    )

            except (
                TypeError,
                ValueError,
            ):
                pass

        if evidence_items:

            for evidence in evidence_items:

                if not isinstance(
                    evidence,
                    dict,
                ):
                    continue

                evidence_text = str(
                    evidence.get(
                        "text",
                        "",
                    )
                ).strip()

                timestamp = evidence.get(
                    "timestamp"
                )

                evidence_score = (
                    score
                    + _score_text(
                        query,
                        evidence_text,
                    )
                )

                matched_segment = (
                    _match_transcript_segment(
                        segments,
                        timestamp,
                        evidence_text,
                    )
                )

                candidates.append({
                    "score": evidence_score,
                    "kind": "analytics",
                    "category": "visual_insights",
                    "meeting": meeting,
                    "item": insight,
                    "evidence": evidence,
                    "segment": matched_segment,
                    "derived": derived,
                })

        else:

            candidates.append({
                "score": score,
                "kind": "analytics",
                "category": "visual_insights",
                "meeting": meeting,
                "item": insight,
                "evidence": None,
                "segment": None,
                "derived": derived,
            })

    return candidates


# =========================================================
# CROSS-MEETING RETRIEVAL
# =========================================================

def retrieve_meeting_context(
    query: str,
    max_sources: int = 10,
    max_per_meeting: int = 4,
) -> list[dict[str, Any]]:

    query = (query or "").strip()

    if not query:
        return []

    meetings = get_all_meetings()

    all_candidates = []

    for meeting_summary in meetings:

        meeting_id = meeting_summary["id"]

        meeting = get_meeting(
            meeting_id
        )

        if not meeting:
            continue

        # Topic relevance.
        topic_score = (
            _score_text(
                query,
                meeting.get(
                    "topic",
                    "",
                ),
            )
            * 1.5
        )

        intelligence = (
            _flatten_intelligence(
                meeting,
                query,
            )
        )

        analytics = (
            _analytics_candidates(
                meeting,
                query,
            )
        )

        # Transcript-level retrieval.
        transcript_candidates = []

        segments = build_transcript_index(
            meeting.get(
                "transcript",
                "",
            )
        )

        for segment in segments:

            score = _score_text(
                query,
                segment["text"],
            )

            if score <= 0:
                continue

            score += topic_score

            transcript_candidates.append({
                "score": score,
                "kind": "transcript",
                "category": "transcript",
                "meeting": meeting,
                "item": None,
                "evidence": None,
                "segment": segment,
            })

        all_candidates.extend(
            intelligence
        )

        all_candidates.extend(
            analytics
        )

        all_candidates.extend(
            transcript_candidates
        )

    # Highest relevance first.
    all_candidates.sort(
        key=lambda candidate: candidate["score"],
        reverse=True,
    )

    # Remove duplicate transcript lines.
    seen = set()

    selected = []
    per_meeting = {}

    for candidate in all_candidates:

        meeting_id = candidate[
            "meeting"
        ]["id"]

        if (
            per_meeting.get(
                meeting_id,
                0,
            )
            >= max_per_meeting
        ):
            continue

        segment = candidate.get(
            "segment"
        )

        if segment:

            dedupe_key = (
                meeting_id,
                round(
                    segment["start"],
                    2,
                ),
                segment["text"],
            )

            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)

        selected.append(
            candidate
        )

        per_meeting[meeting_id] = (
            per_meeting.get(
                meeting_id,
                0,
            )
            + 1
        )

        if len(selected) >= max_sources:
            break

    return selected


# =========================================================
# CONTEXT FOR OLLAMA
# =========================================================

def _build_context(
    retrieved: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:

    blocks = []
    sources = []

    source_counter = 1

    for candidate in retrieved:

        meeting = candidate["meeting"]

        source_id = (
            f"S{source_counter}"
        )

        source_counter += 1

        segment = candidate.get(
            "segment"
        )

        # ---------------------------------------------
        # Deterministic provenance
        # ---------------------------------------------

        if segment:

            source = _source_from_segment(
                meeting,
                segment,
                (
                    "Analytics evidence"
                    if candidate["kind"]
                    == "analytics"
                    else "Transcript"
                ),
            )

            source["source_id"] = (
                source_id
            )

            sources.append(
                source
            )

        else:

            source = {
                "source_id": source_id,
                "meeting_id": meeting["id"],
                "meeting_topic": meeting.get(
                    "topic",
                    "Meeting",
                ),
                "speaker": "",
                "timestamp": "",
                "evidence": "",
                "source_type": (
                    "Structured meeting data"
                ),
            }

            sources.append(
                source
            )

        # ---------------------------------------------
        # Context
        # ---------------------------------------------

        block = [
            f"SOURCE ID: {source_id}",
            f"MEETING ID: {meeting['id']}",
            f"MEETING TOPIC: {meeting.get('topic', '')}",
        ]

        if candidate["kind"] == "transcript":

            block.append(
                "TRANSCRIPT EVIDENCE:"
            )

            if segment:
                block.append(
                    f'[{segment["start"]:.2f}s -> '
                    f'{segment["end"]:.2f}s] '
                    f'{segment["speaker"]}: '
                    f'{segment["text"]}'
                )

        elif candidate["kind"] == "intelligence":

            category = candidate[
                "category"
            ]

            item = candidate[
                "item"
            ]

            block.append(
                f"STRUCTURED INTELLIGENCE "
                f"({category}):"
            )

            block.append(
                json.dumps(
                    item,
                    ensure_ascii=False,
                )
            )

            if segment:
                block.append(
                    "SOURCE TRANSCRIPT:"
                )

                block.append(
                    f'[{segment["start"]:.2f}s -> '
                    f'{segment["end"]:.2f}s] '
                    f'{segment["speaker"]}: '
                    f'{segment["text"]}'
                )

        elif candidate["kind"] == "analytics":

            insight = candidate[
                "item"
            ]

            block.append(
                "QUANTITATIVE ANALYTICS:"
            )

            block.append(
                json.dumps(
                    insight,
                    ensure_ascii=False,
                )
            )

            derived = candidate.get(
                "derived",
                {},
            )

            if derived:
                block.append(
                    "DETERMINISTIC CALCULATION:"
                )

                block.append(
                    json.dumps(
                        derived,
                        ensure_ascii=False,
                    )
                )

            if segment:
                block.append(
                    "SOURCE TRANSCRIPT:"
                )

                block.append(
                    f'[{segment["start"]:.2f}s -> '
                    f'{segment["end"]:.2f}s] '
                    f'{segment["speaker"]}: '
                    f'{segment["text"]}'
                )

        blocks.append(
            "\n".join(block)
        )

    return (
        "\n\n".join(blocks),
        sources,
    )



# =========================================================
# DETERMINISTIC DEADLINE DISAMBIGUATION
# =========================================================

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH_DATE_PATTERN = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def _date_keys(text: str) -> set[tuple[int, int]]:
    return {
        (_MONTHS[match.group(1).lower()], int(match.group(2)))
        for match in _MONTH_DATE_PATTERN.finditer(text or "")
    }


def _collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [part for child in value.values() for part in _collect_strings(child)]
    if isinstance(value, list):
        return [part for child in value for part in _collect_strings(child)]
    return []


def _deadline_disambiguation(query: str) -> dict[str, str] | None:
    """
    Resolve explicit 'is date a deadline for task?' questions from saved
    action-item records. The LLM must not override a directly recorded
    action-item deadline with a different target date.
    """
    normalized_query = _normalized(query)
    if not re.search(r"\b(deadline|due date)\b", normalized_query):
        return None

    task_match = re.search(
        r"\b(?:deadline|due date)\s+for\s+(.+?)(?:\?|,|\bor\s+is\b|$)",
        query,
        re.IGNORECASE,
    )
    requested_dates = _date_keys(query)
    if not task_match or len(requested_dates) != 1:
        return None

    task_tokens = _tokenize(task_match.group(1))
    if not task_tokens:
        return None

    requested_date = next(iter(requested_dates))
    matching_actions = []
    target_date_evidence = []

    for summary in get_all_meetings():
        meeting = get_meeting(summary["id"])
        if not meeting:
            continue

        intelligence = meeting.get("intelligence") or {}
        action_items = intelligence.get("action_items", [])
        if isinstance(action_items, list):
            for item in action_items:
                if not isinstance(item, dict):
                    continue
                task = str(item.get("task", ""))
                tokens = _tokenize(task)
                coverage = len(tokens & task_tokens) / max(1, len(task_tokens))
                if coverage < 0.6:
                    continue
                deadline = str(item.get("deadline") or "").strip()
                deadline_dates = _date_keys(deadline)
                if deadline and deadline_dates:
                    matching_actions.append({
                        "meeting": meeting,
                        "item": item,
                        "task": task,
                        "deadline": deadline,
                        "deadline_dates": deadline_dates,
                    })

        # Only call a date a target date when the saved structured record
        # explicitly places "target" close to that date.
        for text_value in _collect_strings(intelligence):
            for match in _MONTH_DATE_PATTERN.finditer(text_value):
                date_key = (_MONTHS[match.group(1).lower()], int(match.group(2)))
                if date_key != requested_date:
                    continue
                window = text_value[max(0, match.start() - 45):match.end() + 45].lower()
                if "target" in window:
                    target_date_evidence.append((meeting, text_value))

    if not matching_actions:
        return None

    # Prefer a unique, directly matching task deadline. If records disagree,
    # leave the decision to the evidence-aware answer rather than guessing.
    distinct_deadlines = {
        tuple(sorted(action["deadline_dates"]))
        for action in matching_actions
    }
    if len(distinct_deadlines) != 1:
        return None

    recorded_dates = next(iter(distinct_deadlines))
    if requested_date in recorded_dates:
        return None

    action = matching_actions[0]
    deadline_display = action["deadline"]
    task_display = action["task"]
    owner = str(action["item"].get("owner") or "").strip()
    target_label = (
        "The records separately describe the queried date as a target date, "
        "but do not establish it as a replacement deadline."
        if target_date_evidence
        else "The saved evidence does not establish the queried date as a replacement deadline."
    )
    ownership = (
        f"The recorded action item assigns {task_display} to {owner} "
        if owner else f"The recorded action item is {task_display} "
    )
    return {
        "answer": (
            f"No. {ownership}with an explicit deadline of {deadline_display}. "
            f"{target_label}"
        ),
        "reasoning": (
            "This conclusion uses the structured action-item deadline as the "
            "direct commitment. A date mentioned as an affected or target date "
            "is not treated as the task deadline unless the action item explicitly "
            "records that date."
        ),
    }


# =========================================================
# LLM
# =========================================================

def _build_system_prompt() -> str:

    return """
You are MeetingOS, an evidence-grounded meeting intelligence assistant.

Answer the user's question using ONLY the supplied meeting context.

IMPORTANT:

1. Do not invent facts.
2. Do not invent meetings.
3. Do not invent speakers.
4. Do not invent timestamps.
5. Do not invent evidence.
6. Do not use information from previous questions.
7. Distinguish decisions, actions, risks, questions and discussion.
8. When the question is analytical, use the supplied quantitative data.
9. You may perform simple arithmetic using supplied numbers.
10. Do not claim causation merely because two events appear near each other.
11. If the evidence is insufficient, explicitly say so.
12. For cross-meeting questions, reason across the supplied meetings.
13. Distinguish an explicit action-item deadline from a separate target date, milestone, or date that is merely affected by an action.
14. Never relabel a target date as a task deadline unless the evidence explicitly assigns that date to that task.
15. If two dates appear, state what each date is explicitly attached to; do not infer replacement, extension, or dependency without direct evidence.
16. Use SOURCE IDs such as [S1] or [S2] when making important factual claims.
17. Do not create or return your own source metadata. MeetingOS attaches provenance separately.

Return ONLY valid JSON:

{
  "answer": "Direct answer to the user.",
  "reasoning": "Short explanation of how the supplied evidence supports the answer."
}
""".strip()


def ask_meetingos(
    query: str,
) -> dict[str, Any]:

    query = (query or "").strip()

    if not query:
        return {
            "answer": (
                "Ask me something about "
                "your meetings."
            ),
            "reasoning": "",
            "sources": [],
        }

    retrieved = retrieve_meeting_context(
        query
    )

    if not retrieved:
        return {
            "answer": (
                "I couldn't find enough "
                "relevant evidence across "
                "the saved meetings to answer that."
            ),
            "reasoning": "",
            "sources": [],
        }

    context, sources = (
        _build_context(
            retrieved
        )
    )

    # The provenance graph is a second, persisted retrieval surface. Its
    # matches supplement (never replace) transcript/intelligence retrieval.
    try:
        from app.provenance_graph import search_provenance_graph
        graph_matches = search_provenance_graph(query, limit=12)
    except Exception:
        graph_matches = []
    graph_context = json.dumps(graph_matches, ensure_ascii=False, default=str)
    known_source_keys = {(source.get("meeting_id"), source.get("timestamp"), source.get("evidence")) for source in sources}
    for node in graph_matches:
        if node.get("node_type") != "evidence":
            continue
        data = node.get("data") or {}
        evidence_text = str(data.get("text") or node.get("label") or "")
        timestamp = data.get("timestamp")
        key = (node.get("meeting_id"), f"{timestamp:.2f}s" if isinstance(timestamp, (int, float)) else str(timestamp or ""), evidence_text)
        if key in known_source_keys or not evidence_text:
            continue
        sources.append({
            "source_id": f"G{len(sources) + 1}",
            "evidence_id": node.get("node_id"),
            "meeting_id": node.get("meeting_id"),
            "meeting_topic": f"Meeting {node.get('meeting_id')}",
            "speaker": data.get("speaker") or "",
            "timestamp": key[1],
            "evidence": evidence_text,
            "source_type": "Canonical evidence",
            "verification_status": data.get("verification_status", "unverified"),
        })
        known_source_keys.add(key)

    user_prompt = f"""
USER QUESTION:
{query}

MEETING CONTEXT:
{context}

PERSISTED PROVENANCE GRAPH MATCHES (supplemental; verify against evidence above):
{graph_context}
""".strip()

    raw_response = call_llm(
        _build_system_prompt(),
        user_prompt,
    )

    try:

        result = json.loads(
            raw_response
        )

        if not isinstance(
            result,
            dict,
        ):
            raise ValueError(
                "Invalid response structure"
            )

        guarded_deadline = _deadline_disambiguation(query)
        if guarded_deadline:
            result["answer"] = guarded_deadline["answer"]
            result["reasoning"] = guarded_deadline["reasoning"]

        return {
            "answer": str(
                result.get(
                    "answer",
                    "No answer available.",
                )
            ),
            "reasoning": str(
                result.get(
                    "reasoning",
                    "",
                )
            ),
            # Source metadata is generated by MeetingOS, not the LLM.
            "sources": sources,
        }

    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ):

        return {
            "answer": (
                "I found relevant meeting "
                "evidence, but I couldn't "
                "safely format the answer."
            ),
            "reasoning": "",
            "sources": sources,
        }
