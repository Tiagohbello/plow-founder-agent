from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "skills/founder-context/scripts/profile.py"


class VideoPreferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db = Path(self.temporary.name) / "profile.db"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def profile(self, *args: str, ok: bool = True) -> dict | subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(PROFILE), "--db", str(self.db), *args],
            text=True, capture_output=True, check=False,
        )
        if ok:
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(2, result.returncode)
        return result

    def test_unknown_then_google_meet_is_typed_and_clears_zoom(self) -> None:
        self.assertNotIn("video_provider", self.profile("show")["preferences"])
        self.profile("set-video-preference", "--provider", "zoom",
                     "--zoom-link-mode", "personal_room",
                     "--zoom-personal-room-url", "https://us02web.zoom.us/j/123456789")
        preferences = self.profile("set-video-preference", "--provider", "google_meet")["preferences"]
        self.assertEqual("google_meet", preferences["video_provider"])
        self.assertNotIn("zoom_link_mode", preferences)
        self.assertNotIn("zoom_personal_room_url", preferences)
        self.assertEqual(preferences, self.profile("show")["preferences"])

    def test_personal_room_to_per_meeting_removes_url(self) -> None:
        room = "https://zoom.us/my/founder"
        preferences = self.profile("set-video-preference", "--provider", "zoom",
                                   "--zoom-link-mode", "personal_room",
                                   "--zoom-personal-room-url", room)["preferences"]
        self.assertEqual({"video_provider": "zoom", "zoom_link_mode": "personal_room",
                          "zoom_personal_room_url": room}, preferences)
        preferences = self.profile("set-video-preference", "--provider", "zoom",
                                   "--zoom-link-mode", "per_meeting")["preferences"]
        self.assertEqual({"video_provider": "zoom", "zoom_link_mode": "per_meeting"}, preferences)
        self.assertEqual(preferences, self.profile("show")["preferences"])

    def test_invalid_settings_preserve_prior_configuration(self) -> None:
        self.profile("set-video-preference", "--provider", "zoom",
                     "--zoom-link-mode", "personal_room",
                     "--zoom-personal-room-url", "https://zoom.us/my/founder")
        original = self.profile("show")["preferences"]
        invalid = [
            ("--provider", "zoom"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "http://zoom.us/my/founder"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us.evil.test/my/founder"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://user:pass@zoom.us/my/founder"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/not-a-room"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/my/founder?pwd=secret"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/my/founder?token=secret"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/my/founder?utm_source=mail"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/my/founder?"),
            ("--provider", "zoom", "--zoom-link-mode", "per_meeting",
             "--zoom-personal-room-url", "https://zoom.us/my/founder"),
            ("--provider", "google_meet", "--zoom-link-mode", "per_meeting"),
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.profile("set-video-preference", *arguments, ok=False)
                self.assertEqual(original, self.profile("show")["preferences"])


if __name__ == "__main__":
    unittest.main()
