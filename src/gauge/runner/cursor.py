"""The Cursor CLI channel (hard rules 1-4). Nothing here has been run against the real CLI yet.

Every flag used is documented at https://cursor.com/docs/cli (read 2026-10-02): `-p/--print`,
`--output-format`, `--mode`, `--model`, `--workspace`, `--list-models`, `-v/--version`. See
docs/RUNNER.md for what is verified and what is not, and for the limitations (the agent adds its own
hidden instructions; tools are limited by `--mode ask`, not removed; temperature is not
controllable).

Isolation (rule 1): the process is started with its working directory AND `--workspace` set to
`runs/sandbox/`, which must be empty before every run and is swept after it. The prompt is passed
directly, never as a file in a project. A fresh process per run gives a fresh session (rule 2).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from gauge.config import CursorParams
from gauge.runner.base import RunRequest, RunResult

# TODO(verify): the CLI's real wording on exhausted usage is unknown; this errs towards stopping.
USAGE_LIMIT_RE = re.compile(
    r"usage limit|rate limit|quota|too many requests|limit (?:has been )?reached"
    r"|out of (?:usage|credits)",
    re.IGNORECASE,
)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
SHIM_SUFFIXES = (".cmd", ".bat", ".ps1")


class CursorLaunchError(RuntimeError):
    """The CLI cannot be started safely (not installed, prompt too long, ...)."""


def resolve_executable(
    params: CursorParams, which: Callable[[str], str | None] = shutil.which
) -> list[str]:
    for name in params.executables:
        found = which(name)
        if found:
            return [found]
    raise CursorLaunchError(
        f"none of {params.executables} is on PATH: install the Cursor CLI and log in "
        "(README, hand-off notes); the manual mode needs no CLI"
    )


def argv_length(command: Sequence[str]) -> int:
    return len(subprocess.list2cmdline(list(command)))


def argv_limit(command: Sequence[str], params: CursorParams) -> int:
    """Characters allowed on the command line: `.cmd`/`.bat` shims go through cmd.exe, which caps a
    line near 8,191 characters; a real executable is limited by CreateProcess (32,767)."""
    return (
        params.shim_argv_limit_chars
        if str(command[0]).lower().endswith(SHIM_SUFFIXES)
        else params.argv_limit_chars
    )


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def model_is_listed(name: str, listing: str) -> bool:
    """Whether `name` appears in the CLI's model listing as a whole token (format-agnostic)."""
    pattern = rf"(?<![\w./:-]){re.escape(name)}(?![\w./:-])"
    return re.search(pattern, strip_ansi(listing)) is not None


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def sandbox_entries(sandbox: Path) -> list[str]:
    return sorted(p.name for p in sandbox.iterdir()) if sandbox.is_dir() else []


def sweep_sandbox(sandbox: Path) -> list[str]:
    """Remove whatever the CLI left behind (for example a `.cursor` folder); return the names."""
    removed = []
    for path in sorted(sandbox.iterdir()):
        removed.append(path.name)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    return removed


class CursorRunner:
    mode = "cli"

    def __init__(
        self,
        params: CursorParams,
        sandbox: Path,
        *,
        executable: Sequence[str] | None = None,
        run_process: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.params = params
        self.sandbox = Path(sandbox)
        self.sandbox.mkdir(parents=True, exist_ok=True)
        self.executable = list(executable) if executable is not None else resolve_executable(params)
        self._run = run_process
        self._version: str | None = None

    # -- commands --------------------------------------------------------------------------------
    def base_command(self, model: str) -> list[str]:
        p = self.params
        return [
            *self.executable,
            "-p",
            "--output-format",
            p.output_format,
            "--mode",
            p.mode,
            "--model",
            model,
            "--workspace",
            str(self.sandbox),
            *p.extra_args,
        ]

    def build_command(self, model: str, prompt: str) -> list[str]:
        command = self.base_command(model)
        if self.params.prompt_transport == "argv":
            command.append(prompt)
        return command

    def check_fits(self, model: str, prompt: str) -> None:
        """Raise before any call if the prompt cannot be passed as documented."""
        if self.params.prompt_transport != "argv":
            return
        command = self.build_command(model, prompt)
        limit = argv_limit(command, self.params)
        if (length := argv_length(command)) > limit:
            raise CursorLaunchError(
                f"the command line would be {length:,} characters, over the {limit:,} limit for "
                f"{self.executable[0]}. Use `--mode manual`, or set cursor.prompt_transport: stdin "
                "once `gauge smoke --channel cli` has shown that the CLI reads stdin"
            )

    def logged_command(self, command: list[str], prompt: str) -> list[str]:
        """The command as logged: the prompt (already stored in full in `run.prompt_text`) is
        replaced by its length and SHA-256 so the log is not duplicated 30,000 characters long."""
        if self.params.prompt_transport != "argv":
            return [*command, f"<stdin: prompt of {len(prompt)} chars>"]
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return [*command[:-1], f"<prompt: {len(prompt)} chars, sha256 {digest}>"]

    # -- information -----------------------------------------------------------------------------
    def _capture(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run an information command (`--version`, `--list-models`) in the sandbox and leave the
        sandbox as it was found: anything the CLI wrote there is removed."""
        try:
            return self._run(
                args,
                cwd=self.sandbox,
                capture_output=True,
                timeout=60,
            )
        finally:
            sweep_sandbox(self.sandbox)

    def version(self) -> str:
        if self._version is None:
            try:
                done = self._capture([*self.executable, "--version"])
                text = strip_ansi((_text(done.stdout) or _text(done.stderr)).strip())
                self._version = text.splitlines()[0] if done.returncode == 0 and text else "unknown"
            except (OSError, subprocess.SubprocessError):
                self._version = "unknown"
        return self._version

    def list_models(self) -> str | None:
        """The CLI's own model listing (raw text), or None if it cannot be obtained."""
        try:
            done = self._capture([*self.executable, "--list-models"])
        except (OSError, subprocess.SubprocessError):
            return None
        out = _text(done.stdout)
        return out if done.returncode == 0 and out.strip() else None

    # -- run -------------------------------------------------------------------------------------
    def run(self, request: RunRequest) -> RunResult:
        if request.system_prompt:
            raise CursorLaunchError(
                "the Cursor channel takes one combined prompt, no system prompt"
            )
        leftovers = sandbox_entries(self.sandbox)
        if leftovers:
            raise CursorLaunchError(
                f"the sandbox {self.sandbox} is not empty ({leftovers}); it must be empty (rule 1)"
            )
        self.check_fits(request.model, request.prompt)
        version = self.version()  # before the call: an info command may touch the sandbox
        command = self.build_command(request.model, request.prompt)
        started = datetime.now(UTC)
        t0 = time.monotonic()
        notes: list[str] = []
        try:
            done = self._run(
                command,
                cwd=self.sandbox,
                # Bytes in and out: text mode would turn every \n of the prompt into \r\n on
                # Windows, so the model would receive something other than the logged prompt.
                input=(
                    request.prompt.encode("utf-8")
                    if self.params.prompt_transport == "stdin"
                    else None
                ),
                capture_output=True,
                timeout=self.params.timeout_seconds,
            )
            stdout, stderr, code = _text(done.stdout), _text(done.stderr), done.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = _text(exc.stdout), _text(exc.stderr)
            code = 124
            notes.append(f"[gauge] timed out after {self.params.timeout_seconds:.0f} s")
        except OSError as exc:
            raise CursorLaunchError(f"could not start {self.executable[0]}: {exc}") from exc

        removed = sweep_sandbox(self.sandbox)
        if removed:
            notes.append(
                f"[gauge] removed {len(removed)} item(s) the CLI left in the sandbox: {removed}"
            )
        extra: dict = {}
        unusable = code != 0 or not stdout.strip()
        if unusable and USAGE_LIMIT_RE.search(strip_ansi(stdout + "\n" + stderr)):
            extra["usage_limit"] = True
        return RunResult(
            stdout=stdout,
            stderr="\n".join(filter(None, [stderr.rstrip("\n"), *notes])),
            exit_code=code,
            duration_s=round(time.monotonic() - t0, 3),
            command=self.logged_command(command, request.prompt),
            cli_version=version,
            started_utc=started,
            finished_utc=datetime.now(UTC),
            extra=extra,
        )
