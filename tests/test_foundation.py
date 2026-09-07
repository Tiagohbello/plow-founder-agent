import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FoundationContractTests(unittest.TestCase):
    def test_soul_defines_product_identity_and_permissions(self):
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        for phrase in ("technical chief of staff", "Onboard the project", "Founder Shift",
                       "draft PR", "Sending communication always requires", "Never merge"):
            self.assertIn(phrase, soul)
        self.assertIn("A narrow\ninstruction", soul)

    def test_dockerfile_uses_immutable_official_base(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertRegex(
            dockerfile,
            re.compile(
                r"^FROM public\.ecr\.aws/e1h7x4a2/plow-cloud-agents:base-[0-9a-f]{40}"
                r"@sha256:[0-9a-f]{64}$",
                re.MULTILINE,
            ),
        )
        self.assertIn(
            "runtime/SOUL.md /opt/founder-agent/payload/SOUL.md",
            dockerfile,
        )
        self.assertIn("variant/manifest.json /opt/founder-agent/manifest.json", dockerfile)

    def test_credentials_are_excluded_from_context_and_git(self):
        self.assertIn("plow-credentials", (ROOT / ".dockerignore").read_text())
        self.assertIn("plow-credentials", (ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
