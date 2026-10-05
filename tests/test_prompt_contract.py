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

    def test_video_provider_scheduling_contract(self) -> None:
        context = " ".join((ROOT / "skills/founder-context/SKILL.md").read_text().split())
        scheduling = " ".join((ROOT / "skills/founder-scheduling/SKILL.md").read_text().split())
        calendar = " ".join((ROOT / "skills/founder-calendar/SKILL.md").read_text().split())
        action = " ".join((ROOT / "skills/external-action/SKILL.md").read_text().split())
        pick = scheduling.split("## Pick", 1)[1].split("## Sweep", 1)[0]

        for token in ("preferences.video", "provider", "link_mode", "personal_room_url",
                      "set-video-preference", "never infer Google Meet"):
            self.assertIn(token, context)
        self.assertIn("meeting-specific choice takes immediate precedence", pick)
        self.assertIn("do not use the default provider for this invitation", pick)
        self.assertIn("a Zoom link supplied by the guest", pick)
        self.assertIn("do not silently assume Google Meet", pick)
        self.assertIn("`--with-meet`", pick)
        self.assertIn("Read back the event by returned ID", pick)
        self.assertIn("verify its generated Meet URL", pick)
        self.assertIn("`video.personal_room_url`, the persisted HTTPS Zoom room", pick)
        self.assertIn("**without** `--with-meet`", pick)
        self.assertIn("calendar plan starts with the real invitation (`effect: invitation`)", pick)
        self.assertIn("not an effect in the monitor calendar plan", pick)
        self.assertIn("`--suggestion-id`, because monitor-linked product writes are forbidden", pick)
        self.assertIn("`join_url` in the `effect: invitation` intent", pick)
        self.assertIn("without sending Zoom's own invitations", pick)
        self.assertIn("Latch/browser/API", pick)
        self.assertIn("`join_url`", pick)
        self.assertIn("read back the Zoom meeting by provider ID", pick)
        self.assertIn("Only after the invitation has been fetched and verified may a hold be changed or deleted", pick)
        self.assertIn("Use `--with-meet` only for Google Meet", calendar)
        self.assertIn("two independently claimed and verified ledger operations", action)
        self.assertIn("it never contains `effect: zoom_meeting`", action)

    def test_scheduling_inference_and_travel_contract(self) -> None:
        scheduling = " ".join((ROOT / "skills/founder-scheduling/SKILL.md").read_text().split())
        calendar = " ".join((ROOT / "skills/founder-calendar/SKILL.md").read_text().split())
        pipeline = " ".join((ROOT / "skills/pipeline-monitor/SKILL.md").read_text().split())
        action = " ".join((ROOT / "skills/external-action/SKILL.md").read_text().split())
        for fragment in (
            "explicit current request → persisted profile preference → consistent history for the verified identity → evidence-backed inference",
            "identity-verified prior meeting history",
            "entities/people",
            "ask the founder privately in `PLOW_HOME_CHANNEL`",
            "Never invent participants, locations, or times",
            "travel_before", "travel_after", "selected_option_id", "convert_travel",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, scheduling)
        for fragment in (
            "meeting_details", "nonempty `evidence_refs`", "participant identity must be verified",
            "mutually non-overlapping", "both travel segments", "completed persisted offer",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, pipeline)
        self.assertIn("attendee-free", calendar)
        self.assertIn("convert_travel", action)

    def test_scheduling_outgoing_messages_contract(self) -> None:
        documents = {
            "scheduling": " ".join((ROOT / "skills/founder-scheduling/SKILL.md").read_text().split()),
            "calendar": " ".join((ROOT / "skills/founder-calendar/SKILL.md").read_text().split()),
            "persona": " ".join((ROOT / "runtime/persona.md").read_text().split()),
            "gmail": " ".join((ROOT / "skills/gmail/SKILL.md").read_text().split()),
        }
        requirements = {
            "scheduling": """
                ## Outgoing scheduling messages
                Explain hard or soft overlaps privately; never expose the reason in outgoing text.
                Write external messages strictly as the founder's assistant (for example, “Hi, I'm <Founder>'s assistant”). Never impersonate the founder
                Offer exactly three options, each a specific time slot in the contact's timezone. Never ask open-ended questions such as “What days work for you?”
                always search existing conversations in Gmail, Plow, and Messages through Latch for email addresses and phone numbers. Confirm known details rather than asking from scratch.
                Never disclose the personal reason for the founder's unavailability (medical, family, or otherwise); simply state that the founder is unavailable.
                Route internal ambiguity that cannot be inferred from context (for example, virtual versus in-person) privately to the founder in `PLOW_HOME_CHANNEL`; never ask the external contact.
            """,
            "calendar": """
                Calendar titles, participants, locations, and descriptions stay private evidence, including in a trusted group. Share any of these details only when the founder specifically asks to disclose them. Never disclose personal reasons for a conflict; say only that the founder is unavailable.
                A useful answer is "Available 2–4pm; would 2:30, 3, or 3:30 work?"
                canonical `Outgoing scheduling messages` rules
                They take precedence over conflicting guidance
            """,
            "persona": """
                Never disclose personal reasons for being unavailable, even when asked; simply state that the founder is unavailable.
                agent must strictly obey the canonical `Outgoing scheduling messages` rules
            """,
            "gmail": """
                follow and prioritize the canonical `Outgoing scheduling messages` rules in `skills/founder-scheduling/SKILL.md`. They take precedence over conflicting guidance
            """,
        }
        for source, fragments in requirements.items():
            for fragment in fragments.splitlines():
                with self.subTest(source=source, fragment=fragment.strip()):
                    self.assertIn(fragment.strip(), documents[source])


if __name__ == "__main__":
    unittest.main()
