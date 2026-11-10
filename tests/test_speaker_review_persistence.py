import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database


class SpeakerReviewPersistenceTests(unittest.TestCase):
    def test_corrected_transcript_persists_without_overwriting_original(self):
        original = "[0.00s -> 1.00s] SPEAKER_00: We should launch Friday."
        corrected = "[0.00s -> 1.00s] SPEAKER_01: We should launch Friday."

        with tempfile.TemporaryDirectory() as directory:
            test_db = Path(directory) / "meetingos-test.db"
            with patch.object(database, "DB_PATH", test_db):
                database.initialize_database()
                run_id = "speaker-review-test-run"
                meeting_id = database.create_processing_meeting(
                    "Speaker review persistence test",
                    run_id=run_id,
                )

                database.save_transcription(
                    meeting_id,
                    original,
                    {"SPEAKER_00": ["We should launch Friday."]},
                    run_id=run_id,
                )
                database.save_transcription(
                    meeting_id,
                    corrected,
                    {"SPEAKER_00": [], "SPEAKER_01": ["We should launch Friday."]},
                    run_id=run_id,
                )

                meeting = database.get_meeting(meeting_id)
                self.assertEqual(meeting["original_transcript"], original)
                self.assertEqual(meeting["transcript"], corrected)
                self.assertEqual(
                    meeting["speaker_data"],
                    {"SPEAKER_00": [], "SPEAKER_01": ["We should launch Friday."]},
                )


if __name__ == "__main__":
    unittest.main()
