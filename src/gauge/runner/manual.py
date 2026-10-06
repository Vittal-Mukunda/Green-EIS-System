"""Manual mode (spec 4.8): the owner pastes each prompt into a Cursor chat and saves the reply.

1. Open a new Cursor chat in an empty folder.
2. Select the model named for the run.
3. Paste `runs/prompts/{run_id}.md`.
4. Save the reply to `runs/manual_inbox/{run_id}.txt`.

`gauge import-manual` then ingests the inbox files through the same `execute_run` logging as every
other channel: prompt text and hash, raw reply saved before parsing, one row per run. A manual
run is logged as mode `manual`; its timestamps are the reply file's modification time (the only time
that is known) and the command is `manual-import`, so nothing about it is mistaken for an
automated call.
The model name logged is the one in config/models.yaml: the owner must have selected exactly that
model in Cursor's picker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from gauge.runner.base import RunRequest, RunResult

REPAIR_SUFFIX = "__repair"


class InboxRunner:
    """Replays a reply file from the inbox as if it were a call (no process, no network)."""

    mode = "manual"

    def __init__(self, inbox: Path) -> None:
        self.inbox = Path(inbox)

    def path_for(self, run_id: str) -> Path:
        return self.inbox / f"{run_id}.txt"

    def run(self, request: RunRequest) -> RunResult:
        path = self.path_for(request.run_id)
        with path.open(encoding="utf-8", newline="") as fh:
            text = fh.read()
        when = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        return RunResult(
            stdout=text,
            stderr="",
            exit_code=0,
            duration_s=0.0,
            command=["manual-import", path.name],
            cli_version="manual",
            started_utc=when,
            finished_utc=when,
        )


@dataclass
class InboxListing:
    originals: list[str] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)  # original run_ids that have a repair reply
    ignored: list[str] = field(default_factory=list)


def scan_inbox(inbox: Path) -> InboxListing:
    """Reply files by kind. Anything that is not `<run_id>.txt` is reported, never guessed at."""
    listing = InboxListing()
    if not inbox.is_dir():
        return listing
    for path in sorted(inbox.iterdir()):
        if path.name.lower() == "readme.txt":
            continue
        if path.suffix.lower() != ".txt":
            listing.ignored.append(path.name)
            continue
        if path.stem.endswith(REPAIR_SUFFIX):
            listing.repairs.append(path.stem[: -len(REPAIR_SUFFIX)])
        else:
            listing.originals.append(path.stem)
    return listing


INSTRUCTIONS = """\
Run {run_id}  (model {model_key}: {model_name}; condition {condition}; repetition {repetition})
  1. Open a NEW Cursor chat in an empty folder (no project files, no rules).
  2. Select the model: {model_name}
  3. Paste the whole of {prompt_path}
  4. Save the reply, exactly as given, to {inbox_path}"""
