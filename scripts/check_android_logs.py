"""No values printed: fail if the synthetic credential reaches device logs."""
from pathlib import Path
import sys
if __name__ == "__main__":
    data = Path(sys.argv[1]).read_bytes()
    if b"synthetic-agnes-" in data or b"Bearer sk-" in data:
        raise SystemExit("Synthetic credential reached Android logs; values withheld")
    print("::notice title=Credential log scan::No synthetic API credential in device logs")
