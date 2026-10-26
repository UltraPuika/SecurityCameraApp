"""Dev helper: run lint, type check and tests; write a UTF-8 summary to .check-output.txt."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
STEPS = [
    ("ruff", [str(Path(PY).with_name("ruff")), "check", "."]),
    ("mypy", [str(Path(PY).with_name("mypy")), "app", "tests"]),
    ("pytest", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *sys.argv[1:]]),
]

out = []
for name, cmd in STEPS:
    r = subprocess.run(  # noqa: S603  (fixed local tool commands)
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )
    text = (r.stdout + r.stderr).strip()
    out.append(f"=== {name} (exit {r.returncode}) ===\n{text[-6000:]}\n")
(ROOT / ".check-output.txt").write_text("\n".join(out), encoding="utf-8")
