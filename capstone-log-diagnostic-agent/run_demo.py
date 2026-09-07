from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from log_diagnostic_agent.demo import run_demo

if __name__ == "__main__":
    run_demo(ROOT / "data")
