# MeetingOS Parts 4–10 Implementation Batch

Branch: `experiment/pipeline-observability`

## Implemented foundations

### Part 4 — Transcript and speaker attribution
- Speaker labels are derived from transcript segments only when the evidence quote matches transcript text.
- Canonical evidence rejects timestamps more than two seconds from the nearest transcript segment.
- Action items are flagged for review when a verified evidence speaker conflicts with the extracted owner; the owner is not silently rewritten.
- Existing transcript correction validation and original-transcript preservation remain in place.

### Part 5 — Canonical evidence model
- Stable SHA-256-derived evidence IDs.
- Normalized timestamps, transcript span, speaker, quote, category, item index and verification status.
- Evidence IDs and verification metadata are attached to persisted intelligence and visual insight evidence.

### Part 6 — Intelligence validation
- Required intelligence categories are normalized to lists.
- Malformed records and evidence spans are filtered with warnings.
- Claims with missing or unverified evidence are marked `needs_review`.
- The existing evidence-grounding and structured-output path remains the source of generated claims.

### Part 7 — Visual insights
- Visual insight evidence is canonicalized alongside transcript intelligence.
- Visual evidence receives stable evidence IDs and verification metadata.
- Existing numeric/date/risk filtering remains active.

### Part 8 — Meeting Decision Provenance Graph
- Persistent meeting, claim, evidence and speaker nodes.
- `contains_claim`, `contains_evidence`, `supported_by` and verified `associated_with` edges.
- Per-meeting graph rebuild is idempotent and removes stale nodes/edges.

### Part 9 — Ask MeetingOS integration
- Ask retrieval supplements its existing context with persisted graph matches.
- Canonical evidence matches are exposed as additional source records.
- The graph is supplemental; it does not replace transcript/intelligence retrieval.

### Part 10 — Database safety and research data
- SQLite tables and indexes for canonical evidence, graph nodes/edges, audit events and research runs.
- Foreign keys cascade on meeting deletion.
- Audit-event and research-run create/finish APIs.
- Existing context-managed SQLite transactions remain in use.

## Verification required locally

These changes were committed remotely; the GitHub connector cannot execute the local Python environment or model stack. Run:

```bash
git pull --ff-only
python -m py_compile app/main.py app/database.py app/ask_service.py app/evidence_model.py app/intelligence_validation.py app/provenance_graph.py app/intelligence_service.py
python -m unittest discover -s tests -v
python -m app.main
```

Then process one recording and confirm that `canonical_evidence`, `provenance_nodes`, `provenance_edges`, and `meeting_audit_events` receive rows. Reopen the meeting and ask a question that should retrieve one of its claims.

## Known limitations / not claimed complete

- This is an initial graph model, not yet a full cross-meeting entity-resolution or contradiction-resolution engine.
- Research-run storage exists, but a benchmark runner, dataset snapshotting and experiment comparison UI are not yet implemented.
- Visual insights are evidence-linked, but their numerical values are not independently recomputed from raw transcript statements.
- Owner/speaker mismatches are flagged for review, not automatically resolved.
- Runtime, migration-on-existing-database and full UI regression verification remain outstanding.