import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class ProductContractTests(unittest.TestCase):
    def test_onboarding_does_not_promote_runner_to_product(self):
        skill=(ROOT/"founder-onboarding"/"SKILL.md").read_text()
        self.assertIn("vamos fazer o onboarding do projeto",skill)
        self.assertIn("tools/plow-agents",skill)
        self.assertIn("infrastructure unless",skill)
        self.assertIn("Ask one concise question",skill)

    def test_engineering_opens_draft_pr_and_leaves_review_to_founder(self):
        skill=(ROOT/"engineering-assist"/"SKILL.md").read_text()
        for phrase in ("Sentry", "GitHub CI", "isolated worktree", "draft PR", "needs_founder", "Never run deploy, merge"):
            self.assertIn(phrase,skill)

    def test_shift_uses_native_finite_silent_schedule(self):
        skill=(ROOT/"founder-shift"/"SKILL.md").read_text()
        for phrase in ("cronjob", "every `10m`", "one-shot finalizer", "[SILENT]", "claim-effect", "For cancellation"):
            self.assertIn(phrase,skill)

    def test_calendar_and_product_access_use_latch_and_operation_ledger(self):
        calendar=(ROOT/"founder-calendar"/"SKILL.md").read_text()
        product=(ROOT/"product-access"/"SKILL.md").read_text()
        onboarding=(ROOT/"founder-onboarding"/"SKILL.md").read_text()
        for phrase in ("plow-gog", "external-operations", "recurring", "conflicts"):
            self.assertIn(phrase,calendar)
        for phrase in ("credential_item_ref", "fill_secret", "source_kind=repo", "defaults to `approval`"):
            self.assertIn(phrase,product)
        self.assertIn("admin, application, or both",onboarding)
        self.assertIn("Ask one concise question",onboarding)

    def test_whatsapp_is_retired_from_active_capabilities(self):
        docker=(ROOT/"Dockerfile").read_text()
        self.assertNotIn("COPY --chown=0:0 whatsapp/",docker)
        self.assertFalse((ROOT/"whatsapp"/"SKILL.md").exists())
        drafts=(ROOT/"communication"/"drafts.py").read_text()
        self.assertIn('ACTIVE_CHANNELS = ("gmail",)',drafts)

    def test_communication_send_requires_specific_approval(self):
        skill=(ROOT/"gmail"/"SKILL.md").read_text()
        self.assertIn("Only an explicit founder instruction",skill)
        self.assertIn("thread, recipient,\nsubject, and draft",skill)
        self.assertIn("invalidates that\napproval",skill)

if __name__=="__main__": unittest.main()
