"""Shared test helpers (imported by tests as `from helpers import ...`)."""

from __future__ import annotations

import csv
from pathlib import Path

from gauge.ingest.manual import EXPECTED_COLUMNS


def write_manual_csv(path: Path, rows: list[dict]) -> Path:
    """Write a manual-entry CSV; missing keys default to blank."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in EXPECTED_COLUMNS})
    return path


def manual_row(**overrides) -> dict:
    base = dict(
        company="Alpha Ltd",
        nse_symbol="ALPHA",
        sector="Synthetic Alpha",
        fy="FY2024-25",
        indicator="revenue_from_operations",
        value="2000",
        unit="INR crore",
        boundary="consolidated",
        assured="yes",
        source_url="https://example.org/alpha.pdf",
        page_ref="p. 12",
    )
    return {**base, **overrides}


# ---- model replies ------------------------------------------------------------------------
DEFAULT_DRIVERS = ["Water intensity", "Energy intensity", "Waste recovery rate"]


def good_item(code: str, labels: list[str] | None = None) -> dict:
    """A reply object that passes the strict schema."""
    return {
        "company_code": code,
        "t2_class": "Average",
        "t3_rating": 3,
        "t3_confidence": 3,
        "top_drivers": list(labels[:3]) if labels else list(DEFAULT_DRIVERS),
        "justification": "Water intensity is close to the sector median.",
        "insufficient_evidence": False,
    }


def good_reply(codes: list[str], labels: list[str] | None = None) -> list[dict]:
    return [good_item(c, labels) for c in codes]


class CannedRunner:
    """A runner that returns prepared text per run_id (a list is JSON-encoded). It never touches a
    process or the network, so it is safe to use anywhere."""

    mode = "mock"

    def __init__(self, replies=None, default=None, usage_limit_on=()):
        self.replies = dict(replies or {})
        self.default = default
        self.usage_limit_on = set(usage_limit_on)
        self.calls = []

    def run(self, request):
        import json
        from datetime import UTC, datetime

        from gauge.runner.base import RunResult

        self.calls.append(request)
        now = datetime.now(UTC)
        extra = {}
        text = self.replies.get(request.run_id, self.default)
        text = "" if text is None else (text if isinstance(text, str) else json.dumps(text))
        code = 0
        if request.run_id in self.usage_limit_on:
            text, code, extra = "", 1, {"usage_limit": True}
        return RunResult(
            stdout=text,
            stderr="",
            exit_code=code,
            duration_s=0.0,
            command=["canned", request.run_id],
            cli_version="canned-0",
            started_utc=now,
            finished_utc=now,
            extra=extra,
        )


# A fake `agent` executable (a Python script) for the Cursor-channel tests.
FAKE_AGENT = """\
import json, os, sys, time

argv = sys.argv[1:]
if "--version" in argv:
    print("9.9.9-fake")
    sys.exit(0)
if "--list-models" in argv:
    if os.environ.get("FAKE_NO_LIST"):
        sys.exit(3)
    print("\\x1b[1mAvailable models\\x1b[0m")
    print("gpt-fake-1 - Fake GPT")
    print("gpt-fake-1-mini - Fake GPT mini")
    print("gem-fake.2 - Fake Gemini")
    sys.exit(0)

stdin = sys.stdin.buffer.read().decode("utf-8") if not sys.stdin.isatty() else ""
log = {
    "argv": argv,
    "cwd": os.getcwd(),
    "stdin": stdin,
    "sandbox_at_start": sorted(os.listdir(".")),
}
with open(os.environ["FAKE_LOG"], "w", encoding="utf-8") as fh:
    json.dump(log, fh)
leave = os.environ.get("FAKE_LEAVE")
if leave:
    os.makedirs(leave, exist_ok=True)
    open(os.path.join(leave, "state.txt"), "w").write("x")
    open("stray.txt", "w").write("x")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
sys.stderr.write(os.environ.get("FAKE_STDERR", ""))
if os.environ.get("FAKE_AUTO") and "FAKE_REPLY" not in os.environ:
    import re
    text = stdin or argv[-1]
    codes = list(dict.fromkeys(re.findall(r"^## ([A-Z]{3}-\\d{2})$", text, re.M)))
    drivers = ["Water intensity", "Energy intensity", "Waste recovery rate"]
    reply = json.dumps([
        {"company_code": c, "t2_class": "Average", "t3_rating": 3, "t3_confidence": 3,
         "top_drivers": drivers, "justification": "Water intensity is typical.",
         "insufficient_evidence": False} for c in codes])
    sys.stdout.buffer.write(reply.encode("utf-8"))
else:
    sys.stdout.buffer.write(os.environ.get("FAKE_REPLY", '[{"company_code": "X"}]').encode("utf-8"))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""
