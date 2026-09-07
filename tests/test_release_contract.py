import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_all_remaining_specs_have_discoverable_skills(self):
        expected = {
            "founder-profile",
            "founder-observe",
            "founder-queue",
            "founder-focus",
            "engineering-assist",
            "gmail",
            "founder-calendar",
            "product-access",
            "external-operations",
            "founder-shift",
            "founder-onboarding",
        }
        actual = {path.parent.name for path in ROOT.glob("*/SKILL.md")}
        self.assertTrue(expected.issubset(actual))

    def test_docker_bundles_versioned_variant_and_agent_index_service(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        for name in (
            "founder-profile",
            "founder-memory",
            "founder-brief",
            "founder-observe",
            "founder-queue",
            "founder-focus",
            "engineering-assist",
            "gmail",
            "founder-calendar",
            "product-access",
            "external-operations",
            "founder-shift",
            "founder-onboarding",
            "communication",
        ):
            self.assertIn(f"{name}/ /opt/founder-agent/payload/skills/{name}/", dockerfile)
        self.assertIn("variant/manifest.json /opt/founder-agent/manifest.json", dockerfile)
        self.assertIn("runtime/variant_init.py /opt/founder-agent/variant_init.py", dockerfile)
        self.assertIn("COPY vendor/client.pin /opt/plow/agent-index-client.pin", dockerfile)
        self.assertIn("sha256sum /opt/plow/agent-index-client.py", dockerfile)
        self.assertIn("COPY image/s6-overlay/ /etc/s6-overlay/", dockerfile)

    def test_agent_index_pin_is_immutable_and_compose_requires_id(self):
        pin = (ROOT / "vendor" / "client.pin").read_text()
        self.assertRegex(pin, re.compile(r"^sha=[0-9a-f]{40}$", re.MULTILINE))
        self.assertRegex(pin, re.compile(r"^sha256=[0-9a-f]{64}$", re.MULTILINE))
        self.assertIn("AGENT_ID: ${AGENT_ID:?set the Agent Index id", (ROOT / "compose.yml").read_text())

    def test_release_docs_cover_first_value_and_known_limits(self):
        readme = (ROOT / "README.md").read_text()
        for phrase in (
            "Plow",
            "Latch",
            "What's going on?",
            "Founder Shift",
            "--self-check",
            "--dry-run",
            "Known limitations",
        ):
            self.assertIn(phrase, readme)

    def test_reporter_stands_down_without_agent_id_and_depends_on_plow_init(self):
        run = (ROOT / "image" / "s6-overlay" / "s6-rc.d" / "agent-index" / "run").read_text()
        self.assertIn("no AGENT_ID", run)
        self.assertIn("--register --agent", run)
        self.assertTrue((ROOT / "image" / "s6-overlay" / "s6-rc.d" / "agent-index" / "dependencies.d" / "plow-init").exists())
        for service in ("hermes-gateway", "main-hermes", "agent-index"):
            self.assertTrue((ROOT / "image" / "s6-overlay" / "s6-rc.d" / service / "dependencies.d" / "variant-init").exists())

    def test_docs_preserve_volume_on_update(self):
        readme = (ROOT / "README.md").read_text()
        self.assertNotIn("docker compose down -v", readme)
        self.assertIn("/opt/founder-agent/doctor.py", readme)

    def test_manifest_covers_and_hashes_every_payload_file(self):
        manifest = json.loads((ROOT / "variant" / "manifest.json").read_text())
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        sources = {"SOUL.md": ROOT / "runtime" / "SOUL.md"}
        for directory in (
            "founder-profile", "founder-memory", "founder-brief", "founder-observe",
            "founder-queue", "founder-focus", "engineering-assist", "gmail",
            "founder-calendar", "product-access", "external-operations",
            "founder-shift", "founder-onboarding", "communication",
        ):
            for path in (ROOT / directory).glob("**/*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                    sources[f"skills/{path.relative_to(ROOT)}"] = path
        self.assertEqual(set(manifest["files"]), set(sources))
        for relative, path in sources.items():
            self.assertEqual(manifest["files"][relative], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(manifest["retired_files"], {
            "skills/whatsapp/SKILL.md": "8496b4a0d9d19d9ee0996f05b1742e7fe434bae8cdde95d55b20a156ccf3ae4a"
        })

    def test_failure_modes_are_explicit_and_partial(self):
        observe = (ROOT / "founder-observe" / "SKILL.md").read_text()
        for phrase in ("blocked", "unconfigured", "available", "One blocked source"):
            self.assertIn(phrase, observe)


if __name__ == "__main__":
    unittest.main()
