import unittest
from scripts.verify_e_module import run_checks


class ApiSmokeTests(unittest.TestCase):
    def test_authorized_anonymous_demo_missing_and_real_pipeline(self):
        report = run_checks()
        self.assertEqual(report["checks"], 26)
        self.assertEqual((report["failed"], report["skipped"]), (0, 0))
        self.assertEqual(report["llm"], "blocked_missing_credentials")
