"""Cross-platform task runner. `make` is not installed on this Windows machine, so every Makefile
target has an equivalent here:  python tasks.py <test|lint|format|all-dry|ddl|check>
"""

from __future__ import annotations

import subprocess
import sys

PY = sys.executable

TARGETS: dict[str, list[list[str]]] = {
    "test": [[PY, "-m", "pytest"]],
    "lint": [[PY, "-m", "ruff", "check", "src", "tests", "scripts", "tasks.py", "dashboard"]],
    "format": [[PY, "-m", "ruff", "format", "src", "tests", "scripts", "tasks.py", "dashboard"]],
    "all-dry": [[PY, "-m", "gauge.cli", "all-dry"]],
    "ddl": [[PY, "-m", "gauge.cli", "init-db", "--ddl-only"]],
}
TARGETS["check"] = TARGETS["lint"] + TARGETS["test"] + TARGETS["all-dry"]


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in TARGETS:
        print(f"usage: python tasks.py <{'|'.join(TARGETS)}>", file=sys.stderr)
        return 2
    for cmd in TARGETS[argv[1]]:
        print("$", " ".join(cmd), flush=True)
        code = subprocess.call(cmd)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
