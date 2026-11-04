"""Parse real YAML and reject CI permission/trigger/pinning regressions."""
from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "actions/checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/setup-node": "249970729cb0ef3589644e2896645e5dc5ba9c38",
}


def validate(text):
    data = yaml.safe_load(text)
    # PyYAML's YAML 1.1 schema interprets the GitHub 'on' key as boolean True.
    triggers = data.get("on", data.get(True))
    if not isinstance(triggers, dict) or "pull_request" not in triggers or "pull_request_target" in triggers:
        raise ValueError("Unsafe or missing PR trigger")
    if data.get("permissions") != {"contents": "read"}:
        raise ValueError("Workflow permissions must be contents: read")
    if "secrets." in text or "continue-on-error" in text or "|| true" in text:
        raise ValueError("Secrets or failure masking are not allowed")
    if set(data["jobs"]) != {"python", "frontend"}:
        raise ValueError("Unexpected CI jobs")
    for job in data["jobs"].values():
        if job.get("permissions", {"contents": "read"}) != {"contents": "read"} or job.get("runs-on") != "ubuntu-24.04" or not 1 <= job.get("timeout-minutes", 0) <= 20:
            raise ValueError("Unsafe job policy")
        for step in job["steps"]:
            command = step.get("run", "")
            if re.search(r"probe_|full_pipeline|verify_e2e|verify_data_pipeline|verify_knowledge|--allow-network", command):
                raise ValueError("Live diagnostics must not enter routine CI")
            if "uses" not in step: continue
            name, sha = step["uses"].split("@")
            if PINS.get(name) != sha or not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("Action must use the verified full commit")
            options = step.get("with", {})
            if name == "actions/checkout" and options.get("persist-credentials") is not False:
                raise ValueError("Checkout credentials must not persist")
            if name == "actions/setup-node" and (options.get("node-version") != "24.19.0" or options.get("package-manager-cache") is not False):
                raise ValueError("Node version/cache policy changed")
            if name == "actions/setup-python" and options.get("python-version") != "3.12.14":
                raise ValueError("Python version changed")
    return data


if __name__ == "__main__":
    result = validate((ROOT / ".github/workflows/ci.yml").read_text())
    print("workflow_yaml_valid jobs=" + ",".join(result["jobs"]))
