import unittest

from app.evidence_model import build_canonical_evidence
from app.intelligence_validation import validate_intelligence_payload, verify_claim_evidence


class EvidenceGraphTests(unittest.TestCase):
    def test_evidence_id_is_stable(self):
        transcript = "[10.00s -> 12.00s] Shaurya: I will finish the landing page by September 12th."
        intelligence = {"action_items": [{"task": "Finish landing page", "evidence": [
            {"timestamp": "10.5s", "text": "I will finish the landing page by September 12th."}
        ]}]}
        first = build_canonical_evidence(1, transcript, intelligence)
        second = build_canonical_evidence(1, transcript, intelligence)
        self.assertEqual(first[0]["evidence_id"], second[0]["evidence_id"])
        self.assertEqual(first[0]["speaker"], "Shaurya")
        self.assertEqual(first[0]["verification_status"], "verified")

    def test_unverified_evidence_has_no_speaker(self):
        transcript = "[10.00s -> 12.00s] Shaurya: I will finish the landing page."
        intelligence = {"action_items": [{"task": "Finish landing page", "evidence": [
            {"timestamp": "10.5s", "text": "I will finish the campaign."}
        ]}]}
        row = build_canonical_evidence(1, transcript, intelligence)[0]
        self.assertEqual(row["verification_status"], "unverified")
        self.assertIsNone(row["speaker"])

    def test_structural_validation_and_support_status(self):
        payload, warnings = validate_intelligence_payload({
            "action_items": [{"task": "Do work", "evidence": []}],
            "decisions": "bad-shape",
        })
        self.assertTrue(warnings)
        checked = verify_claim_evidence(payload)
        self.assertEqual(checked["action_items"][0]["support_status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
