"""Compatibility alias: the former legacy runner is now isolated by default."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verify_e_module import main

if __name__ == "__main__":
    raise SystemExit(main())
