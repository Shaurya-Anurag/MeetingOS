import json
import re
from typing import Any

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:3b"
TIMEOUT = 600

SYSTEM_PROMPT = """
You extract quantitative information from a meeting transcript for a deterministic chart renderer.
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
- Include revenue, profit, loss, costs, prices, percentages, counts, rates, growth, budgets,
  performance metrics, market size, customer counts, ratios, comparisons and time-series data.
- Convert obvious spoken quantities to numeric values (2 million -> 2000000; 5 lakh -> 500000).
- Time series -> line. Category comparisons -> bar. Percentage composition -> donut.
- A single meaningful numerical claim -> kpi.
- Do not treat dates, timestamps, speaker numbers or segment timings as business metrics.
- "Grew 18% over five years" is a valid KPI unless yearly values are explicitly available.
- Keep evidence directly tied to the quantitative claim.
- If there is no meaningful quantitative information, return {"insights": []}.
- Merge values for the same metric into one insight when practical.
- Keep the result focused; no more than 12 insights.
"""


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


def validate_visual_insights(payload: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"line", "bar", "donut", "kpi"}
    validated = []

    for insight in payload.get("insights", []):
        if not isinstance(insight, dict):
            continue

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

        chart_type = str(insight.get("chart_type") or "kpi").strip().lower()
        if chart_type not in allowed:
            chart_type = "kpi"
        if len(points) == 1:
            chart_type = "kpi"

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

        validated.append({
            "title": str(insight.get("title") or insight.get("metric") or "Quantitative Insight").strip(),
            "metric": str(insight.get("metric") or "Metric").strip(),
            "unit": str(insight.get("unit") or "").strip(),
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
