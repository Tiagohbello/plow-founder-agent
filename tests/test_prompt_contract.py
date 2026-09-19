import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PromptContractTests(unittest.TestCase):
    def test_action_approval_follows_platform_authority_not_speaker_identity(self) -> None:
        persona = " ".join((ROOT / "runtime/persona.md").read_text().split())
        external_action = " ".join((ROOT / "skills/external-action/SKILL.md").read_text().split())
        gmail = " ".join((ROOT / "skills/gmail/SKILL.md").read_text().split())

        self.assertIn("turn carrying the founder's authority", persona)
        self.assertIn("turn carrying the founder's authority", external_action)
        self.assertIn("turn carrying the founder's authority", gmail)
        self.assertNotIn("Only an explicit founder instruction", gmail)
        self.assertNotIn("<founder-message", gmail)

        calendar = " ".join((ROOT / "skills/founder-calendar/SKILL.md").read_text().split())
        pipeline = " ".join((ROOT / "skills/pipeline-monitor/SKILL.md").read_text().split())
        self.assertIn("authority-bearing turn", calendar)
        self.assertIn("owner's approval message", pipeline)
        self.assertNotIn("authority-bearing approval message", pipeline)


if __name__ == "__main__":
    unittest.main()
