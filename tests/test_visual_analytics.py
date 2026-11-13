import unittest
from unittest.mock import patch

from app.visual_analytics_service import extract_visual_insights


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "total_duration": 100,
            "load_duration": 10,
            "prompt_eval_duration": 20,
            "eval_duration": 70,
            "prompt_eval_count": 100,
            "eval_count": 20,
            "message": {
                "content": (
                    '{"insights":[{"title":"Revenue","metric":"Revenue",'
                    '"unit":"USD","chart_type":"kpi",'
                    '"data":[{"label":"Current","value":120}],'
                    '"evidence":[{"timestamp":"00:10","text":'
                    '"Revenue reached 120 USD."}]}]}'
                )
            },
        }


class VisualAnalyticsTests(unittest.TestCase):
    @patch("app.visual_analytics_service.requests.post", return_value=_FakeResponse())
    def test_extract_visual_insights_accepts_pipeline_diagnostics(self, post):
        diagnostics = {}
        result = extract_visual_insights(
            "Revenue increased from 100 to 120.",
            diagnostics=diagnostics,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Revenue")
        self.assertEqual(diagnostics["status"], "success")
        self.assertEqual(diagnostics["valid_insight_count"], 1)
        self.assertEqual(post.call_count, 1)

    def test_empty_transcript_reports_skipped_diagnostics(self):
        diagnostics = {}
        result = extract_visual_insights("", diagnostics=diagnostics)

        self.assertEqual(result, [])
        self.assertEqual(diagnostics["status"], "skipped")
        self.assertEqual(diagnostics["reason"], "empty_transcript")


if __name__ == "__main__":
    unittest.main()
