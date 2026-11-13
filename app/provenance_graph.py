"""Meeting Decision Provenance Graph (MDPG) persistence and query helpers."""
from __future__ import annotations

import json
from typing import Any

from app.database import get_connection
from app.evidence_model import build_canonical_evidence


def persist_meeting_graph(
    meeting_id: int,
    transcript: str,
    intelligence: dict[str, Any],
    analytics: dict[str, Any] | None = None,
) -> dict[str, int]:
    evidence = build_canonical_evidence(meeting_id, transcript, intelligence, analytics)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str, str, dict[str, Any]]] = []

    meeting_node = f"meeting:{meeting_id}"
    nodes[meeting_node] = {"type": "meeting", "label": f"Meeting {meeting_id}", "data": {"meeting_id": meeting_id}}

    for row in evidence:
        eid = row["evidence_id"]
        nodes[eid] = {"type": "evidence", "label": row["text"][:180], "data": row}
        edges.append((meeting_node, eid, "contains_evidence", {}))
        item = row.get("item") or {}
        category = row["category"]
        claim_text = str(
            item.get("task") or item.get("decision") or item.get("issue")
            or item.get("risk") or item.get("question") or item.get("name")
            or item.get("title") or category
        )
        claim_id = f"claim:{meeting_id}:{category}:{row['item_index']}"
        nodes[claim_id] = {"type": "claim", "label": claim_text[:180], "data": {"category": category, "item": item}}
        edges.append((claim_id, eid, "supported_by", {"verification_status": row["verification_status"]}))
        edges.append((meeting_node, claim_id, "contains_claim", {}))
        if row.get("speaker"):
            speaker_id = f"speaker:{meeting_id}:{row['speaker'].casefold()}"
            nodes[speaker_id] = {"type": "speaker", "label": row["speaker"], "data": {"speaker": row["speaker"]}}
            edges.append((speaker_id, claim_id, "associated_with", {"basis": "timestamp_and_text_verified"}))

    with get_connection() as connection:
        for node_id, node in nodes.items():
            connection.execute(
                """INSERT INTO provenance_nodes(node_id, meeting_id, node_type, label, data_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(node_id) DO UPDATE SET node_type=excluded.node_type,
                   label=excluded.label, data_json=excluded.data_json, updated_at=CURRENT_TIMESTAMP""",
                (node_id, meeting_id, node["type"], node["label"], json.dumps(node["data"], ensure_ascii=False)),
            )
        connection.execute("DELETE FROM provenance_edges WHERE meeting_id = ?", (meeting_id,))
        for source, target, relation, metadata in edges:
            connection.execute(
                """INSERT OR IGNORE INTO provenance_edges(meeting_id, source_node_id, target_node_id, relation, metadata_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (meeting_id, source, target, relation, json.dumps(metadata, ensure_ascii=False)),
            )
        connection.execute("DELETE FROM canonical_evidence WHERE meeting_id = ?", (meeting_id,))
        for row in evidence:
            connection.execute(
                """INSERT INTO canonical_evidence(
                    evidence_id, meeting_id, category, item_index, timestamp, start_seconds,
                    end_seconds, speaker, text, transcript_text, verification_status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["evidence_id"], meeting_id, row["category"], row["item_index"],
                    row["timestamp"], row["start_seconds"], row["end_seconds"], row["speaker"],
                    row["text"], row["transcript_text"], row["verification_status"],
                    json.dumps(row, ensure_ascii=False),
                ),
            )
    return {"nodes": len(nodes), "edges": len(edges), "evidence": len(evidence)}


def search_provenance_graph(query: str, limit: int = 12) -> list[dict[str, Any]]:
    terms = [term.casefold() for term in (query or "").split() if len(term) > 2]
    if not terms:
        return []
    where = " OR ".join(["LOWER(label) LIKE ?" for _ in terms])
    params = [f"%{term}%" for term in terms]
    params.append(max(1, min(int(limit), 50)))
    with get_connection() as connection:
        rows = connection.execute(
            f"""SELECT node_id, meeting_id, node_type, label, data_json
                FROM provenance_nodes WHERE {where}
                ORDER BY updated_at DESC LIMIT ?""",
            params,
        ).fetchall()
    return [
        {"node_id": row["node_id"], "meeting_id": row["meeting_id"],
         "node_type": row["node_type"], "label": row["label"],
         "data": json.loads(row["data_json"] or "{}")}
        for row in rows
    ]
