"""Run only Debug tasks and expose a bounded diagnostic on the public CI page."""
from collections import deque
from pathlib import Path
import subprocess
import sys

TASKS = {"build": ["assembleDebug", "assembleDebugAndroidTest"], "device": ["connectedDebugAndroidTest"]}
if __name__ == "__main__":
    tasks = TASKS[sys.argv[1]]
    root = Path(__file__).resolve().parents[1] / "frontend/android"
    tail = deque(maxlen=70)
    with subprocess.Popen([str(root / "gradlew"), "--no-daemon", "--console=plain", *tasks], cwd=root,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            tail.append(line)
        result = process.wait()
    if result:
        message = "".join(tail)[-6000:].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error title=Android Gradle failure::" + message, flush=True)
    else:
        print("::notice title=Android Gradle::BUILD SUCCESSFUL " + " ".join(tasks), flush=True)
    raise SystemExit(result)
