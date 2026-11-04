import unittest
from scripts.check_ci_policy import ROOT, validate


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github/workflows/ci.yml").read_text()

    def test_real_workflow_validates(self):
        self.assertEqual(set(validate(self.text)["jobs"]), {"python", "frontend"})

    def test_elevated_permissions_fail(self):
        with self.assertRaises(ValueError): validate(self.text.replace("contents: read", "contents: write"))

    def test_privileged_pr_trigger_fails(self):
        with self.assertRaises(ValueError): validate(self.text.replace("pull_request:", "pull_request_target:"))

    def test_floating_action_fails(self):
        with self.assertRaises(ValueError): validate(self.text.replace("d23441a48e516b6c34aea4fa41551a30e30af803", "v6"))

    def test_ignored_failure_fails_policy(self):
        with self.assertRaises(ValueError): validate(self.text + "\n# continue-on-error: true\n")

    def test_live_diagnostic_cannot_replace_smoke(self):
        with self.assertRaises(ValueError): validate(self.text.replace("scripts/verify_e_module.py", "scripts/verify_e2e.py"))
