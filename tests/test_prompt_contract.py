import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PromptContractTests(unittest.TestCase):
    def test_action_approval_follows_platform_authority_not_speaker_identity(self) -> None:
        persona = " ".join((ROOT / "runtime/persona.md").read_text().split())
        external_action = " ".join((ROOT / "skills/external-action/SKILL.md").read_text().split())
        gmail = " ".join((ROOT / "skills/gmail/SKILL.md").read_text().split())

        self.assertIn("turn carrying the founder's authority", persona)
        self.assertIn("not the speaker's identity", persona)
        self.assertIn("turn carrying the founder's authority", external_action)
        self.assertIn("without requiring a literal founder-authored message", external_action)
        self.assertIn("turn carrying the founder's authority", gmail)
        self.assertNotIn("Only an explicit founder instruction", gmail)
        self.assertNotIn("<founder-message", gmail)

        calendar = " ".join((ROOT / "skills/founder-calendar/SKILL.md").read_text().split())
        pipeline = " ".join((ROOT / "skills/pipeline-monitor/SKILL.md").read_text().split())
        self.assertIn("authority-bearing turn", calendar)
        self.assertIn("approval in an authority-bearing turn", pipeline)
        self.assertNotIn("exact founder approval", pipeline)
        self.assertIn("identifying the authority-bearing approval turn", pipeline)
        self.assertIn("edit requested in an authority-bearing turn", pipeline)
        self.assertNotIn("founder message ref", pipeline)
        self.assertIn("PLOW_HOME_CHANNEL", pipeline)
        self.assertNotIn("authority-bearing approval message", pipeline)

    def test_scheduling_outgoing_messages_contract(self) -> None:
        scheduling_doc = (ROOT / "skills/founder-scheduling/SKILL.md").read_text()
        section_header = "## Outgoing scheduling messages"
        section_start = scheduling_doc.index(section_header) + len(section_header)
        section_end = scheduling_doc.index("\n## ", section_start)
        scheduling = " ".join(scheduling_doc[section_start:section_end].split())
        scheduling_doc = " ".join(scheduling_doc.split())
        persona = " ".join((ROOT / "runtime/persona.md").read_text().split())
        calendar = " ".join(
            (ROOT / "skills/founder-calendar/SKILL.md").read_text().split()
        )
        gmail = " ".join((ROOT / "skills/gmail/SKILL.md").read_text().split())

        self.assertIn(
            "Explain any overlap (hard or soft) to the founder privately; never expose the reason in outgoing text.",
            scheduling_doc,
        )
        self.assertIn("founder's assistant", scheduling)
        self.assertIn("strictly as the founder's assistant", scheduling)
        self.assertIn("Never impersonate the founder", scheduling)
        self.assertIn("exactly three options", scheduling)
        self.assertIn("each a specific time slot", scheduling)
        self.assertIn("in the contact's timezone", scheduling)
        self.assertIn("Never ask open-ended questions such as", scheduling)
        self.assertIn("What days work for you?", scheduling)
        self.assertIn("Gmail, Plow, and Messages through Latch", scheduling)
        self.assertIn("email addresses and phone numbers", scheduling)
        self.assertIn("Confirm known details rather than asking from scratch", scheduling)
        self.assertIn("Never disclose the personal reason for the founder's unavailability", scheduling)
        self.assertIn("simply state that the founder is unavailable", scheduling)
        self.assertIn("virtual versus in-person", scheduling)
        self.assertIn("privately to the founder in `PLOW_HOME_CHANNEL`", scheduling)
        self.assertIn("never ask the external contact", scheduling)

        self.assertIn(
            "Calendar titles, participants, locations, and descriptions stay private evidence",
            calendar,
        )
        self.assertIn("Never disclose personal reasons for a conflict", calendar)
        self.assertIn("say only that the founder is unavailable", calendar)

        self.assertIn("the agent must strictly obey the canonical", persona)
        self.assertIn("Outgoing scheduling messages", persona)
        for skill in (calendar, gmail):
            self.assertIn("canonical `Outgoing scheduling messages` rules", skill)
            self.assertIn("take precedence over conflicting guidance", skill)


if __name__ == "__main__":
    unittest.main()
