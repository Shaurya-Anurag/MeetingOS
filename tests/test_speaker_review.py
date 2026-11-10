import unittest

from app.main import finalize_speakers, validate_speaker_review
from app.speaker_review import transcript_to_review_rows, validate_speaker_review_rows


class SpeakerReviewTests(unittest.TestCase):
    def setUp(self):
        self.original = "\n".join([
            "[0.00s -> 1.20s] SPEAKER_00: We should launch on Friday.",
            "[1.30s -> 2.10s] SPEAKER_01: I will confirm the venue.",
        ])

    def test_allows_only_detected_speaker_reassignment(self):
        reviewed = self.original.replace(
            "SPEAKER_01: I will confirm",
            "SPEAKER_00: I will confirm",
        )
        result = validate_speaker_review(self.original, reviewed)
        self.assertEqual(result["changed_labels"], 1)
        self.assertIn("SPEAKER_00: I will confirm", result["transcript"])

    def test_rejects_unknown_speaker_id(self):
        reviewed = self.original.replace("SPEAKER_01:", "SPEAKER_99:")
        with self.assertRaisesRegex(ValueError, "not a detected speaker"):
            validate_speaker_review(self.original, reviewed)

    def test_rejects_timestamp_edit(self):
        reviewed = self.original.replace("0.00s", "0.50s")
        with self.assertRaisesRegex(ValueError, "only the speaker label"):
            validate_speaker_review(self.original, reviewed)

    def test_rejects_utterance_text_edit(self):
        reviewed = self.original.replace("Friday", "Monday")
        with self.assertRaisesRegex(ValueError, "only the speaker label"):
            validate_speaker_review(self.original, reviewed)

    def test_rejects_added_or_removed_lines(self):
        with self.assertRaisesRegex(ValueError, "number of utterance lines"):
            validate_speaker_review(self.original, self.original.splitlines()[0])


    def test_builds_editable_rows(self):
        rows = transcript_to_review_rows(self.original)
        self.assertEqual(rows[0], ["0.00s -> 1.20s", "SPEAKER_00", "We should launch on Friday."])

    def test_accepts_valid_row_speaker_change(self):
        rows = transcript_to_review_rows(self.original)
        rows[1][1] = "SPEAKER_00"
        result = validate_speaker_review_rows(self.original, rows)
        self.assertEqual(result["changed_labels"], 1)
        self.assertIn("SPEAKER_00: I will confirm", result["transcript"])

    def test_rejects_row_timestamp_or_text_edit(self):
        rows = transcript_to_review_rows(self.original)
        rows[0][2] = "Changed words"
        with self.assertRaisesRegex(ValueError, "only the speaker label"):
            validate_speaker_review_rows(self.original, rows)

    def test_rejects_unknown_row_speaker(self):
        rows = transcript_to_review_rows(self.original)
        rows[0][1] = "SPEAKER_99"
        with self.assertRaisesRegex(ValueError, "not a detected speaker"):
            validate_speaker_review_rows(self.original, rows)

    def test_rejects_missing_rows(self):
        rows = transcript_to_review_rows(self.original)[:-1]
        with self.assertRaisesRegex(ValueError, "number of utterance rows"):
            validate_speaker_review_rows(self.original, rows)

    def test_finalize_preserves_corrected_speaker_label(self):
        reviewed = self.original.replace("SPEAKER_01:", "SPEAKER_00:")
        result = finalize_speakers(
            reviewed,
            {"SPEAKER_00": [], "SPEAKER_01": []},
            "No",
            [],
            original_transcript=self.original,
        )
        self.assertTrue(result["ok"])
        self.assertIn("SPEAKER_00: I will confirm", result["transcript"])


if __name__ == "__main__":
    unittest.main()
