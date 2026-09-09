import json
import re
from typing import Any

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:3b"
TIMEOUT = 600

SYSTEM_PROMPT = """
You extract ONLY meaningful quantitative/business information from a meeting transcript for a deterministic chart renderer.
Return ONLY JSON in this exact shape:
{
  "insights": [
    {
      "title": "short title",
      "metric": "what is measured",
      "unit": "unit such as INR, USD, %, people, units, or empty string",
      "chart_type": "line | bar | donut | kpi",
      "data": [
        {"label": "2024", "value": 120.0}
      ],
      "trend": "brief trend statement or empty string",
      "evidence": [
        {"timestamp": "00:12:10", "text": "supporting transcript statement"}
      ]
    }
  ]
}

Rules:
- Extract ONLY numbers explicitly supported by the transcript. Never invent or estimate.
- A visual insight must represent a measurable quantity, comparison, rate, percentage, amount,
  count, performance measure, or time-series that has analytical meaning.
- Include revenue, profit, loss, costs, prices, percentages, counts, rates, growth, budgets,
  performance metrics, market size, customer counts, ratios, comparisons and time-series data.
- Convert obvious spoken quantities to numeric values (2 million -> 2000000; 5 lakh -> 500000).
- Time series -> line. Category comparisons -> bar. Percentage composition -> donut.
- A single meaningful numerical claim -> kpi.
- DO NOT extract calendar dates, deadlines, due dates, launch dates, meeting dates, timestamps,
  speaker numbers, segment numbers, duration/meeting length, or relative scheduling phrases such as
  "next week" as quantitative business metrics.
- DO NOT extract qualitative labels such as low/high/medium risk as numeric metrics unless the transcript
  explicitly gives a numerical probability/rate for that metric.
- A date written as a number is still a DATE, not a metric. For example, "September 22" is not a KPI.
- A deadline expressed as a number is still a DEADLINE, not a metric. For example, "finish by September 14"
  is not a KPI, and "due in 2 weeks" is not a KPI.
- Metrics involving elapsed/performance time are valid only when the transcript clearly measures something,
  e.g. "average response time fell from 18 minutes to 12 minutes". Do not treat ordinary meeting duration
  as a business metric.
- "Grew 18% over five years" is a valid KPI unless yearly values are explicitly available.
- Keep evidence directly tied to the quantitative claim and include evidence whenever possible.
- If there is no meaningful quantitative information, return {"insights": []}.
- Merge values for the same metric into one insight when practical.
- Keep the result focused; no more than 12 insights.
"""


_CALENDAR_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_CALENDAR_DATE_RE = re.compile(
    rf"\b(?:{_CALENDAR_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?\b|"
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_CALENDAR_MONTHS})\b",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_TIME_CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[ap]m)?\b", re.IGNORECASE)
_TEMPORAL_WORD_RE = re.compile(
    r"\b(?:deadline|due|by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"next\s+(?:week|month|day)|this\s+(?:week|month)|launch\s+date|target\s+date|"
    r"target\s+launch|meeting\s+(?:date|starts?|started)|scheduled|schedule|"
    r"on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.IGNORECASE,
)
_QUALITATIVE_RISK_RE = re.compile(r"\b(?:high|medium|low)\s+(?:risk|risk\s+level)\b|\brisk\b", re.IGNORECASE)
_DURATION_RE = re.compile(
    r"\b(?:meeting|call|session)\s+(?:lasted?|duration|length)|\b(?:lasted?|duration|length)\b",
    re.IGNORECASE,
)


def _parse_json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {"insights": []}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _contains_numeric_text(text: str) -> bool:
    return bool(re.search(r"\b\d+(?:\.\d+)?\b|\d+[.,]\d+", text or ""))


def _is_non_metric_insight(
    title: str,
    metric: str,
    unit: str,
    evidence_text: str,
) -> bool:
    """Reject common LLM mistakes where ordinary meeting facts become 'metrics'."""
    combined = " ".join((title, metric, unit, evidence_text)).strip()
    normalized = combined.lower()
    unit_normalized = unit.lower().strip()

    # Calendar dates and scheduling facts are not visual metrics.
    if _CALENDAR_DATE_RE.search(evidence_text) or _NUMERIC_DATE_RE.search(evidence_text):
        return True
    if unit_normalized in {"date", "dates", "calendar date"}:
        return True
    if _TEMPORAL_WORD_RE.search(normalized):
        # Allow genuine operational time metrics such as response time / turnaround time.
        performance_time = re.search(
            r"\b(?:response|resolution|turnaround|processing|cycle|delivery|wait|lead)\s+time\b",
            normalized,
        )
        if not performance_time:
            return True

    # Plain clock/timestamp information is not a business metric.
    if _TIME_CLOCK_RE.search(evidence_text) and not re.search(
        r"\b(?:response|resolution|turnaround|processing|cycle|delivery|wait|lead)\s+time\b",
        normalized,
    ):
        return True

    # Qualitative risk statements are not quantitative insights.
    if _QUALITATIVE_RISK_RE.search(normalized):
        explicit_probability = re.search(
            r"\b(?:risk|probability|likelihood|chance)\b.{0,40}\d+(?:\.\d+)?\s*%",
            normalized,
        )
        if not explicit_probability:
            return True

    # Meeting duration is an application statistic, not a business metric.
    if _DURATION_RE.search(normalized):
        return True

    # If the unit/title says a calendar concept, reject it even when the evidence is terse.
    if re.search(r"\b(?:deadline|due date|launch date|target date|schedule|scheduled date)\b", normalized):
        return True

    return False


def validate_visual_insights(payload: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"line", "bar", "donut", "kpi"}
    validated = []

    for insight in payload.get("insights", []):
        if not isinstance(insight, dict):
            continue

        title = str(insight.get("title") or insight.get("metric") or "Quantitative Insight").strip()
        metric = str(insight.get("metric") or "Metric").strip()
        unit = str(insight.get("unit") or "").strip()

        points = []
        for point in insight.get("data", []):
            if not isinstance(point, dict):
                continue
            label = str(point.get("label") or "").strip()
            value = _number(point.get("value"))
            if label and value is not None:
                points.append({"label": label, "value": value})

        if not points:
            continue

        evidence = []
        for item in insight.get("evidence", []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if text:
                evidence.append({
                    "timestamp": str(item.get("timestamp") or "").strip(),
                    "text": text,
                })

        # Use the evidence as the strongest semantic signal. If the model supplied it,
        # verify that the evidence actually contains a quantitative claim.
        evidence_text = " ".join(item["text"] for item in evidence)
        if evidence_text and not _contains_numeric_text(evidence_text):
            continue

        if _is_non_metric_insight(title, metric, unit, evidence_text):
            continue

        chart_type = str(insight.get("chart_type") or "kpi").strip().lower()
        if chart_type not in allowed:
            chart_type = "kpi"

        # A lone incidental count is usually meeting content, not a useful visual insight.
        # Keep single-point KPIs for amounts, percentages, rates, and explicitly framed
        # aggregate/performance measures; require at least two points for ordinary counts.
        if len(points) == 1:
            chart_type = "kpi"
            count_like = re.search(
                r"\b(count|counts|cases|incidents|tickets|registrations|signups|sign-ups|issues|items|people|users|customers|employees|orders|tasks|calls)\b",
                f"{title} {metric} {unit}".lower(),
            )
            aggregate_framing = re.search(
                r"\b(total|average|avg|current|overall|monthly|weekly|daily|yearly|annual|per[- ](?:day|week|month|year))\b",
                evidence_text.lower(),
            )
            strong_unit = unit.lower() in {"%", "percent", "percentage", "inr", "usd", "eur", "gbp", "lakh", "crore", "million", "billion"}
            if count_like and not aggregate_framing and not strong_unit:
                continue

        validated.append({
            "title": title,
            "metric": metric,
            "unit": unit,
            "chart_type": chart_type,
            "data": points,
            "trend": str(insight.get("trend") or "").strip(),
            "evidence": evidence,
        })

    return validated[:12]


def extract_visual_insights(transcript: str) -> list[dict[str, Any]]:
    if not transcript or not transcript.strip():
        return []

    payload = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "temperature": 0.0,
        "num_predict": 1400,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        body = response.json()
        raw = body.get("message", {}).get("content", "")
        return validate_visual_insights(_parse_json(raw))
    except (requests.RequestException, ValueError, TypeError):
        return []
