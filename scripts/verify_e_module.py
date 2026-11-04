"""Offline API smoke: synthetic Host/token/data, no real configuration loading."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_checks() -> dict:
    from tests.support import OfflineEnvironment
    checks = []
    def check(name, valid):
        if not valid:
            raise AssertionError("API smoke failed: " + name)
        checks.append(name)
    with OfflineEnvironment(seed=True) as env:
        client = env.client()
        def get(path):
            response = client.get(path)
            check("HTTP GET " + path, response.status_code == 200)
            return response.json()
        check("health minimal", get("/api/health") == {"status": "ok"})
        check("dashboard demo provenance", get("/api/dashboard")["data_source_status"] == "demo")
        settings = get("/api/settings/status")
        check("no real env or key", not settings["env_file_exists"] and not settings["fields"]["LLM_D_API_KEY"]["configured"])
        system = get("/api/system/check")
        check("LLM explicitly blocked", any(c["name"] == "llm_api_key" and c["level"] == "BLOCKED" for c in system["checks"]))
        tasks = get("/api/tasks")
        check("synthetic demo task content", len(tasks["items"]) == 1 and tasks["items"][0]["raw_id"] == "demo_synthetic_homework")
        materials = get("/api/materials")
        check("demo status is not real parsing success", materials["status"] == "demo" and materials["items"] == [])
        check("knowledge demo provenance", get("/api/knowledge/status")["status"] == "demo")
        response = client.post("/api/retrieval/search", json={"query": "demo", "top_k": 3, "mode": "keyword"})
        check("retrieval missing index", response.status_code == 200 and response.json()["status"] == "missing" and not response.json()["items"])
        for path, body in [("/api/qa", {"question": "Demo question"}), ("/api/summaries", {"topic": "Demo topic"}), ("/api/homework-assistant", {"question": "Demo homework"})]:
            response = client.post(path, json=body)
            check(path + " missing-key blocked", response.status_code == 200 and response.json()["status"] == "blocked" and response.json()["error_code"] == "missing_api_key")
        anonymous = env.client(authorized=False)
        check("anonymous health allowed", anonymous.get("/api/health").json() == {"status": "ok"})
        check("anonymous data rejected", anonymous.get("/api/tasks").status_code == 401)
        check("anonymous write rejected without side effects", anonymous.post("/api/settings/local", json={"learn_username": "synthetic"}).status_code == 401 and not (env.root / ".env").exists())
        check("unknown Origin denied", client.post("/api/sync/run", headers={"Origin": "https://attacker.invalid"}, json={}).status_code == 403)
        check("no remote/real source", get("/api/debug/data-source")["tasks"]["source"] == "demo")
    # A new environment and adapters must not reuse the demo/missing index cache.
    with OfflineEnvironment(seed=True) as env:
        records = [json.loads(line) for line in env.config.demo_collector_jsonl.read_text().splitlines()]
        records[0]["raw_id"] = "synthetic_homework"
        env.write_records(env.config.collector_jsonl, records)
        chunks = [json.loads(line) for line in env.config.demo_material_chunks_jsonl.read_text().splitlines()]
        chunks[0].update(file_hash="synthetic-hash", chunk_id="synthetic-chunk")
        env.write_records(env.config.material_chunks_jsonl, chunks)
        client = env.client()
        payload = client.get("/api/debug/data-source").json()
        check("real pipeline classification uses synthetic records", payload["tasks"]["source"] == "real" and payload["materials"]["source"] == "real")
        payload = client.post("/api/retrieval/search", json={"query": "合成", "mode": "keyword"}).json()
        check("keyword retrieval exercises real index", payload["status"] == "ready" and len(payload["items"]) == 1)
    return {"checks": len(checks), "passed": len(checks), "failed": 0, "skipped": 0,
            "llm": "blocked_missing_credentials", "data": "synthetic_demo_and_real_pipeline"}


def main() -> int:
    if not __debug__:
        raise RuntimeError("Do not disable test assertions")
    print(json.dumps(run_checks(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
