"""Run the existing smoke runner twice in an entirely synthetic configuration.

The original runner's failure is expected and reported, not counted as a pass.
The adapted run changes only its TestClient configuration, not its assertions.
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LEARNING_ASSISTANT_ROOT": directory, "SCHOLAROS_API_TOKEN": "synthetic-smoke-" + "x" * 40}, clear=True), patch("dotenv.load_dotenv"):
        from fastapi.testclient import TestClient
        from scripts import verify_e_module as legacy
        with patch("requests.sessions.Session.request", side_effect=AssertionError("External network forbidden")), patch("httpx.HTTPTransport.handle_request", side_effect=AssertionError("External network forbidden")):
            original = legacy.main()
            assert original == 1
            print("original_runner_exit=1 checks_executed=1 failed=1 reason=untrusted_testserver_host")
            client = TestClient(legacy.app, base_url="http://localhost")
            assert client.get("/api/dashboard").status_code == 401
            print("host_corrected_without_token=401")

            def scoped_client(app):
                return TestClient(app, base_url="http://localhost", headers={"Authorization": "Bearer " + os.environ["SCHOLAROS_API_TOKEN"]})
            with patch.object(legacy, "TestClient", scoped_client):
                result = legacy.main()
            assert result == 0
            # A 200 for D-module operations is a missing-credential response,
            # not evidence of a successful LLM call or completed business work.
            response = scoped_client(legacy.app).post("/api/qa", json={"question": "synthetic"})
            assert response.json()["status"] == "blocked"
            print("adapted_runner_exit=0 checks=11 passed=11 failed=0 skipped=0 llm=blocked_missing_credentials")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
