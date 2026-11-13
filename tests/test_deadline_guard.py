import unittest
from unittest.mock import patch

from app.ask_service import _deadline_disambiguation


class DeadlineDisambiguationTests(unittest.TestCase):
    QUERY = (
        "Does September 22nd represent a deadline for "
        "Shaurya's landing page, or is it a separate target date?"
    )

    def setUp(self):
        self.meeting = {
            "id": 54,
            "topic": "Project launch planning",
            "transcript": "",
            "intelligence": {
                "action_items": [
                    {
                        "task": "Finish landing page",
                        "owner": "Shaurya",
                        "deadline": "September 12th",
                        "evidence": [{"timestamp": "120.70s", "text": "I will finish the landing page by September 12th."}],
                    }
                ],
                "decisions": [
                    {
                        "decision": "September 22nd is the target date for Research Test 1.",
                        "evidence": [{"timestamp": "130.00s", "text": "September 22nd is the target date."}],
                    }
                ],
            },
        }

    @patch("app.ask_service.get_meeting")
    @patch("app.ask_service.get_all_meetings")
    def test_separate_target_date_does_not_override_explicit_task_deadline(self, all_meetings, get_meeting):
        all_meetings.return_value = [{"id": 54}]
        get_meeting.return_value = self.meeting
        result = _deadline_disambiguation(self.QUERY)
        self.assertIsNotNone(result)
        self.assertIn("September 12th", result["answer"])
        self.assertIn("target date", result["answer"])
        self.assertNotIn("September 22nd is a deadline", result["answer"])

    @patch("app.ask_service.get_meeting")
    @patch("app.ask_service.get_all_meetings")
    def test_does_not_override_when_action_deadline_is_missing(self, all_meetings, get_meeting):
        self.meeting["intelligence"]["action_items"][0]["deadline"] = None
        all_meetings.return_value = [{"id": 54}]
        get_meeting.return_value = self.meeting
        self.assertIsNone(_deadline_disambiguation(self.QUERY))

    @patch("app.ask_service.get_meeting")
    @patch("app.ask_service.get_all_meetings")
    def test_does_not_guess_when_saved_action_items_conflict(self, all_meetings, get_meeting):
        conflicting = {
            **self.meeting,
            "id": 55,
            "intelligence": {
                "action_items": [{
                    "task": "Finish landing page",
                    "owner": "Shaurya",
                    "deadline": "September 15th",
                    "evidence": [],
                }]
            },
        }
        all_meetings.return_value = [{"id": 54}, {"id": 55}]
        get_meeting.side_effect = [self.meeting, conflicting]
        self.assertIsNone(_deadline_disambiguation(self.QUERY))


if __name__ == "__main__":
    unittest.main()