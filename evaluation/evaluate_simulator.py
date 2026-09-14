"""Run and save the official three baselines without modifying the harness."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "harness" / "simulate.py"
OUT = ROOT / "evaluation" / "baseline_results.txt"


def main():
    sections = []
    for label, flags in (("STANDARD", []), ("SHOCK", ["--shock"])):
        run = subprocess.run([sys.executable, str(HARNESS), *flags], cwd=HARNESS.parent,
                             check=True, capture_output=True, text=True)
        sections.append(f"[{label}]\n{run.stdout.strip()}\n")
    output = "\n".join(sections)
    OUT.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

