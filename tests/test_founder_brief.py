import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "founder-brief" / "SKILL.md"


class FounderBriefContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL.read_text()

    def test_skill_is_discoverable_and_uses_company_memory(self):
        self.assertIn("name: founder-brief", self.skill)
        self.assertIn("founder-profile", self.skill)
        self.assertIn("founder-queue", self.skill)
        self.assertIn("founder-observe", self.skill)
        self.assertIn(
            'python3 "$HERMES_HOME/skills/founder-memory/memory.py" list',
            self.skill,
        )

    def test_repo_inspection_is_read_only_and_uses_latch(self):
        self.assertIn("plow_list_skills", self.skill)
        self.assertIn("plow_run_command", self.skill)
        self.assertIn('"git status --short --branch; "', self.skill)
        self.assertIn('"git log -5 --oneline --decorate; "', self.skill)
        self.assertIn('read_paths=["<repository path>"]', self.skill)
        self.assertIn('goal="Read-only repository inspection for Founder Brief"', self.skill)
        self.assertIn("omit `write_paths` and `network`", self.skill)
        self.assertNotIn("plow_write_file", self.skill)

    def test_brief_has_prioritized_short_output_contract(self):
        for heading in ("NEEDS YOU", "I CAN HANDLE", "WATCHING"):
            self.assertIn(heading, self.skill)
        self.assertIn("Return at most three numbered items total", self.skill)
        self.assertIn("Why is this first?", self.skill)
        self.assertIn("status=deferred", self.skill)
        self.assertIn("Keep deferred implementation deferred", self.skill)
        self.assertIn("coverage is partial", self.skill)

    def test_status_can_reconcile_but_does_not_authorize_effects(self):
        self.assertIn("may reconcile memory and queue", self.skill)
        self.assertIn("does not authorize code changes", self.skill)
        self.assertIn("cannot treat the question\nas authorization", self.skill)

    def test_dockerfile_bundles_skill_in_variant_payload(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn(
            "founder-brief/ /opt/founder-agent/payload/skills/founder-brief/",
            dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
