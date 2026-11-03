"""Deterministic offline entry point; zero tests, skips or failures are not green."""
import argparse
import json
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["all", "security", "business", "isolation"], default="all")
    parser.add_argument("--order", choices=["normal", "reverse", "shuffle"], default="normal")
    parser.add_argument("--harness", action="store_true")
    parser.add_argument("--self-test-failure", action="store_true")
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("Optimized Python disables assertions; refusing test run")
    if args.harness:
        from tests.support import OfflineEnvironment
        from scripts.run_harness import main as harness
        with OfflineEnvironment():
            return harness()
    loader = unittest.TestLoader()
    patterns = {"all": ["test_*.py"], "security": ["test_security.py", "test_pr1_review.py"],
                "business": ["test_business.py"], "isolation": ["test_isolation.py", "test_api_smoke.py", "test_ci_policy.py"]}
    tests = [test for pattern in patterns[args.suite] for test in flatten(loader.discover(str(ROOT / "tests"), pattern=pattern))]
    if args.self_test_failure:
        class IntentionalFailure(unittest.TestCase):
            def runTest(self): self.fail("Synthetic negative control: runner must exit 1")
        tests = [IntentionalFailure()]
    if args.order == "reverse": tests.reverse()
    elif args.order == "shuffle": random.Random(20261103).shuffle(tests)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(tests))
    report = {"tests": result.testsRun,
              "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped) - len(result.expectedFailures) - len(result.unexpectedSuccesses),
              "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
              "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses)}
    print(json.dumps(report))
    return 0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped and not result.expectedFailures else 1


if __name__ == "__main__":
    raise SystemExit(main())
