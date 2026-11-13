import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.provenance_graph import get_meeting_graph, persist_meeting_graph


class ProvenancePersistenceTests(unittest.TestCase):
    def test_graph_and_canonical_evidence_persist_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'meetingos-test.db'
            with patch.object(database, 'DB_PATH', db_path):
                database.initialize_database()
                with database.get_connection() as connection:
                    cursor = connection.execute(
                        "INSERT INTO meetings(topic, created_at, status, transcript) VALUES (?, ?, ?, ?)",
                        ('Test', database.utc_now(), 'ready', '[10.00s -> 12.00s] Shaurya: I will finish the landing page by September 12th.'),
                    )
                    meeting_id = cursor.lastrowid
                transcript = '[10.00s -> 12.00s] Shaurya: I will finish the landing page by September 12th.'
                intelligence = {'action_items': [{'task': 'Finish landing page', 'owner': 'Shaurya', 'deadline': 'September 12th', 'evidence': [{'timestamp': '10.5s', 'text': 'I will finish the landing page by September 12th.'}]}]}
                first = persist_meeting_graph(meeting_id, transcript, intelligence, {})
                second = persist_meeting_graph(meeting_id, transcript, intelligence, {})
                graph = get_meeting_graph(meeting_id)
                self.assertEqual(first, second)
                self.assertGreater(first['nodes'], 1)
                self.assertGreater(first['edges'], 0)
                self.assertTrue(any(node['type'] == 'evidence' for node in graph['nodes']))
                with database.get_connection() as connection:
                    count = connection.execute('SELECT COUNT(*) FROM canonical_evidence WHERE meeting_id = ?', (meeting_id,)).fetchone()[0]
                self.assertEqual(count, 1)
                audit_id = database.record_audit_event(meeting_id, 'test_event', {'ok': True})
                self.assertGreater(audit_id, 0)
                database.create_research_run('run-test', 'Evidence graph test', hypothesis='Stable evidence IDs', config={'seed': 7})
                database.finish_research_run('run-test', {'passed': 1}, status='completed')
                with database.get_connection() as connection:
                    run = connection.execute('SELECT status, metrics_json FROM research_runs WHERE id = ?', ('run-test',)).fetchone()
                self.assertEqual(run['status'], 'completed')


if __name__ == '__main__':
    unittest.main()