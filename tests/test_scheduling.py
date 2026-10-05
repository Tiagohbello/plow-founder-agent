from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "meeting", ROOT / "skills/founder-scheduling/scripts/meeting.py"
)
meeting = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(meeting)
PROFILE_SPEC = importlib.util.spec_from_file_location(
    "founder_profile", ROOT / "skills/founder-context/scripts/profile.py"
)
profile = importlib.util.module_from_spec(PROFILE_SPEC)
PROFILE_SPEC.loader.exec_module(profile)
MONITOR_SPEC = importlib.util.spec_from_file_location(
    "pipeline_monitor", ROOT / "skills/pipeline-monitor/scripts/monitor.py"
)
monitor = importlib.util.module_from_spec(MONITOR_SPEC)
MONITOR_SPEC.loader.exec_module(monitor)


class MeetingInferenceTests(unittest.TestCase):
    def test_profile_and_monitor_reuse_the_shared_meeting_schema(self):
        preferences = {
            "duration_minutes": 45,
            "format": "in_person",
            "location": " Office ",
            "participants": [" founder@example.com "],
            "timezone": " America/Recife ",
        }
        normalized_preferences = {
            "duration_minutes": 45,
            "format": "in_person",
            "location": "Office",
            "participants": ["founder@example.com"],
            "timezone": "America/Recife",
        }
        self.assertEqual(normalized_preferences, meeting.normalize_meeting_preferences(preferences))
        self.assertEqual(normalized_preferences, profile.meeting_preferences(preferences))

        details = {**preferences, "evidence_refs": [" thread:1 ", "thread:1"]}
        normalized_details = {
            **normalized_preferences,
            "evidence_refs": ["thread:1"],
        }
        self.assertEqual(normalized_details, meeting.normalize_meeting_details(details))
        self.assertEqual(normalized_details, monitor.normalize_meeting_details(details))

        invalid_format = {**preferences, "format": "conference"}
        with self.assertRaisesRegex(ValueError, "format must be"):
            profile.meeting_preferences(invalid_format)
        with self.assertRaisesRegex(ValueError, "format must be"):
            monitor.normalize_meeting_details({**details, "format": "conference"})

    def test_resolves_details_in_approved_precedence_order(self):
        result = meeting.resolve_meeting_details(
            request={"duration_minutes": 45},
            profile={"format": "video", "timezone": "America/Recife"},
            history=[{"identity_verified": True, "details": {
                "participants": ["alex@example.com"], "location": "Remote"},
              "evidence_refs": ["calendar:prior-meeting:1"]}],
            inference={"city": {"value": "Recife", "evidence_refs": ["wiki:person:1"]}},
            context_refs=["gmail:request:1", "profile:meeting"],
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["details"]["duration_minutes"], 45)
        self.assertEqual(result["details"]["format"], "video")
        self.assertEqual(result["details"]["participants"], ["alex@example.com"])
        self.assertEqual(result["details"]["city"], "Recife")
        self.assertEqual(set(result["evidence_refs"]), {
            "gmail:request:1", "profile:meeting", "calendar:prior-meeting:1", "wiki:person:1"
        })

    def test_current_request_overrides_profile_and_history(self):
        result = meeting.resolve_meeting_details(
            request={"duration_minutes": 60, "format": "phone"},
            profile={"duration_minutes": 30, "format": "video", "timezone": "America/Recife"},
            history=[{"identity_verified": True, "details": {
                "duration_minutes": 30, "format": "video", "participants": ["alex@example.com"]},
                "evidence_refs": ["calendar:prior-meeting:1"]}],
        )
        self.assertEqual(result["details"]["duration_minutes"], 60)
        self.assertEqual(result["details"]["format"], "phone")

    def test_history_only_counts_for_verified_identity_and_consistent_records(self):
        base = {"duration_minutes": 30, "format": "video", "participants": ["alex@example.com"],
                "timezone": "America/Recife"}
        ignored = meeting.resolve_meeting_details(
            history=[{"identity_verified": False, "details": base}]
        )
        self.assertFalse(ignored["ready"])
        self.assertIn("participants", ignored["unresolved"])
        consistent = meeting.resolve_meeting_details(history=[
            {"identity_verified": True, "details": base,
             "evidence_refs": ["calendar:prior-meeting:1"]},
            {"identity_verified": True, "details": {**base, "participants": ["ALEX@example.com"]},
             "evidence_refs": ["calendar:prior-meeting:2"]},
        ])
        self.assertTrue(consistent["ready"])

    def test_conflicting_verified_history_blocks_lower_precedence_inference(self):
        history = [
            {"identity_verified": True, "details": {"duration_minutes": 30},
             "evidence_refs": ["calendar:prior-meeting:1"]},
            {"identity_verified": True, "details": {"duration_minutes": 45},
             "evidence_refs": ["calendar:prior-meeting:2"]},
        ]
        result = meeting.resolve_meeting_details(
            history=history,
            inference={"duration_minutes": {"value": 30, "evidence_refs": ["thread:1"]}},
        )
        self.assertIn("duration_minutes", result["ambiguous"])
        self.assertIn("duration_minutes", result["unresolved"])
        self.assertNotIn("duration_minutes", result["details"])

    def test_inference_requires_source_evidence_and_never_fills_absent_facts(self):
        with self.assertRaisesRegex(ValueError, "evidence_refs"):
            meeting.resolve_meeting_details(inference={"duration_minutes": {"value": 30}})
        result = meeting.resolve_meeting_details()
        self.assertFalse(result["ready"])
        self.assertEqual(result["details"], {})

    def test_unreferenced_history_fact_cannot_be_made_ready_by_unrelated_context_ref(self):
        result = meeting.resolve_meeting_details(
            request={"duration_minutes": 30, "format": "video", "timezone": "America/Recife"},
            history=[{"identity_verified": True,
                      "details": {"participants": ["alex@example.com"]},
                      "evidence_refs": []}],
            context_refs=["gmail:unrelated-context"],
        )
        self.assertFalse(result["ready"])
        self.assertIn("participants", result["unresolved"])
        self.assertNotIn("participants", result["details"])

    def test_in_person_location_and_real_participants_are_required(self):
        result = meeting.resolve_meeting_details(
            request={"duration_minutes": 30, "format": "in_person",
                     "participants": ["alex@example.com"], "timezone": "America/Recife"}
        )
        self.assertFalse(result["ready"])
        self.assertIn("location", result["unresolved"])
        with self.assertRaisesRegex(ValueError, "participants"):
            meeting.resolve_meeting_details(request={"participants": []})

    def test_empty_evidence_refs_marks_readiness_unresolved(self):
        result = meeting.resolve_meeting_details(
            request={"duration_minutes": 30, "format": "video",
                     "participants": ["alex@example.com"], "timezone": "America/Recife"},
        )
        self.assertFalse(result["ready"])
        self.assertIn("evidence_refs", result["unresolved"])
        self.assertEqual([], result["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
