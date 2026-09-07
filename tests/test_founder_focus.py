import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "founder-focus" / "focus.py"


def load_module():
    spec = importlib.util.spec_from_file_location("founder_focus", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FounderFocusTests(unittest.TestCase):
    def test_short_and_long_windows_choose_different_fitting_work(self):
        focus = load_module()
        items = [
            {"id": 1, "title": "Ship small fix", "context": "20 minutes", "priority": "medium", "status": "ready"},
            {"id": 2, "title": "Plan migration", "context": "3 hours", "priority": "high", "status": "needs_founder"},
        ]
        short = focus.recommend_focus(items, [], 30)
        long = focus.recommend_focus(items, [], 180)
        self.assertEqual(short["recommendation"]["id"], 1)
        self.assertEqual(long["recommendation"]["id"], 2)

    def test_deferred_memory_never_becomes_focus(self):
        focus = load_module()
        result = focus.recommend_focus(
            [{"id": 1, "title": "SSO", "context": "customer request", "priority": "urgent", "status": "ready"}],
            [{"subject": "SSO", "status": "deferred"}],
            60,
        )
        self.assertIsNone(result["recommendation"])

    def test_deferred_feature_still_allows_customer_communication(self):
        focus = load_module()
        result = focus.recommend_focus(
            [{"id": 2, "title": "Reply about SSO", "context": "20 minutes", "priority": "high",
              "status": "ready", "action_kind": "communicate", "evidence": "gmail:m-22"}],
            [{"subject": "SSO", "status": "deferred"}], 45,
        )
        self.assertEqual(result["recommendation"]["id"], 2)


if __name__ == "__main__":
    unittest.main()
