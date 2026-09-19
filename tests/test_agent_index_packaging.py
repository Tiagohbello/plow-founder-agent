from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AgentIndexPackagingTests(unittest.TestCase):
    def test_cloud_identity_defaults_are_baked_into_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text()

        self.assertIn("ENV AGENT_ID=founder-agent", dockerfile)
        self.assertIn('AGENT_NAME="Founder Agent"', dockerfile)
        self.assertIn("HERMES_HOME=/var/lib/hermes", dockerfile)

    def test_reporter_imports_and_forwards_cloud_environment(self):
        reporter = (ROOT / "image/s6-overlay/s6-rc.d/agent-index/run").read_text()

        self.assertTrue(reporter.startswith("#!/command/with-contenv sh\n"))
        self.assertIn('PLOW_API_BASE="$PLOW_API_BASE"', reporter)
        self.assertIn('HERMES_HOME="$HERMES_HOME"', reporter)
        self.assertIn('env "PLOW_AGENT_TOKEN=$PLOW_AGENT_TOKEN"', reporter)
        self.assertIn('--agent "$AGENT_ID"', reporter)


if __name__ == "__main__":
    unittest.main()
