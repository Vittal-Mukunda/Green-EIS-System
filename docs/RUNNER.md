# RUNNER

Status: **written and tested against fakes; never run against the real Cursor CLI or the real API.**
Tests use a fake `agent` script, canned runners and a mocked HTTP transport. Nothing here proves how
the real CLI behaves, and the first real call is the smoke test (`gauge smoke`), which only you run.

## The three channels

| Channel | Command | Models | Mode logged |
|---|---|---|---|
| Cursor CLI | `gauge run --mode cli` | the 4 primary models (and S1 if enabled) | `cli` |
| Manual paste | `gauge run --mode manual`, then `gauge import-manual` | the same models | `manual` |
| Free API | `gauge run --mode api` | the baseline B1 | `api` |

All three go through the same `execute_run`, so every run logs: run ID, UTC times, CLI version, model
name, condition, repetition, seed, the exact command, the full prompt and its SHA-256, raw stdout and
stderr, exit code and duration; the raw reply is saved to `runs/raw/{run_id}.txt` **before** it is
parsed. A run with a successful raw file is skipped unless `--force` (resumable, idempotent).

## Cursor CLI: what is verified and what is not

Read in Cursor's documentation on 2026-10-02 (cursor.com/docs/cli: overview, parameters, headless).
The CLI is **not installed** on the build machine, so `agent --help` could not be read (hard rule 3):
please run `agent --help`, `agent --version` and `agent --list-models` once and compare.

The command the runner builds, started with the working directory set to `runs/sandbox/`:

```
agent -p --output-format text --mode ask --model <name> --workspace runs/sandbox "<prompt>"
```

| Part | Source | Status |
|---|---|---|
| `agent` (the spec says `cursor-agent`; the runner tries `agent`, then `cursor-agent`) | docs use `agent` | documented; V-03 |
| `-p`, `--print`: non-interactive, prints the response | parameters table | documented |
| `--output-format text` (also `json`, `stream-json`; only `text` is used) | parameters table | documented |
| `--mode ask`: documented as read-only ("explore ... without making changes") | parameters table | documented; limits tools, does not remove them (V-33) |
| `--model <name>`: the exact name, never `auto` | parameters table | documented |
| `--workspace <path>` | parameters table | documented |
| `--list-models` and `--version` | parameters table | documented; output format unknown (V-32) |
| the prompt as the last, positional argument | the docs' examples | documented |
| the prompt on **stdin** | not mentioned anywhere | **unverified** (V-30) |
| exit codes and the wording when a usage limit is reached | not documented | **unknown** (V-31) |
| authentication in scripts: `CURSOR_API_KEY` | headless page | documented; the runner never reads or logs it |

Each run is a new process with no `--resume` or `--continue`, which the docs describe as the way to
continue a chat, so each run is a fresh session (hard rule 2).

### The command-line length problem (V-30)

A real C1 prompt is about 23,000 characters (measured on the provisional sample) and a real C2 about
37,000 (estimated). Windows allows about 32,767 characters per command, and only about 8,191 if `agent`
is installed as a `.cmd` shim, which goes through `cmd.exe`. The runner measures the command before
every call and **refuses** (before spending anything) if it is over the limit
(`cursor.argv_limit_chars` 30,000, or `cursor.shim_argv_limit_chars` 7,500 for `.cmd`/`.bat`). Then:

1. `gauge smoke --channel cli --model P1 --transport stdin` tests whether the CLI reads the prompt
   from stdin. If it works, set `cursor.prompt_transport: stdin` in `config/models.yaml`.
2. Otherwise use manual mode, which has no such limit.

### Isolation (hard rule 1)

The process runs with its working directory **and** `--workspace` set to `runs/sandbox/`, which must be
empty before every run (a pre-flight check and a per-run check refuse otherwise). Afterwards the
runner removes whatever the CLI left there (for example a state folder) and records the names in the
run's stderr as a `[gauge]` line, so the next run starts empty and nothing leaks between runs. The
prompt is passed directly, never as a file in a project. Bytes go in and out unchanged (text mode would
turn each `\n` into `\r\n` on Windows, so the model would not receive the logged prompt).

### Limitations to state in the paper

* Cursor's agent adds its own hidden system instructions; they are not visible or controllable.
* The temperature and other sampling parameters cannot be set for the Cursor runs.
* `--mode ask` restricts tools but is not documented to remove all of them.
* The agent may apply your user-level Cursor rules; clear them before the study (V-33).
* The model behind a name can change without notice; only the name and dates are logged.
* The CLI version is logged with every run (`agent --version`, first line).

## Pre-flight (what `gauge run` checks before the first call)

1. The frozen files and **every rendered prompt** still match `registry/frozen_manifest.json` (rule 7).
2. No model name is a placeholder, empty or `auto` (rule 4).
3. Cursor: the executable exists, `--version` works, **every configured name is in `agent
   --list-models`** (whole-token match), `runs/sandbox/` is empty, and the longest prompt fits.
4. API: the key is in `.env` (`OPENROUTER_API_KEY`; never printed or logged), the id ends in `:free`
   and **is in OpenRouter's current model list** (a public endpoint).
5. It then asks for confirmation (use `--yes` to skip), because the calls use your quota.

Any failure lists every problem and starts nothing.

## The loop (`gauge run --mode cli|api`)

Plan order (seeded random across models and conditions), one fresh call per run, a `pause_seconds`
pause between calls (default 20 s, rule 11). Options: `--only P1,P2`, `--limit N`, `--force`, `--yes`.
It **stops cleanly** (exit code 3, run the same command later to resume) when:

* a usage limit is reached: the CLI reports one (wording unverified, V-31), or the API keeps answering
  429 (or names a per-day limit); the limited run is retried on resume;
* repetition 2 may not start yet: it must start at least `rep2_min_gap_minutes` (60) after repetition
  1 ended on the same channel; the message says when;
* two runs in a row fail (so a broken setup does not burn quota);
* you press Ctrl-C (finished runs are already committed).

## Manual mode

`gauge run --mode manual [--only P1]` writes every prompt to `runs/prompts/{run_id}.md` (with
`index.csv` listing hashes) and prints, for each run still to do:

1. Open a new Cursor chat in an empty folder.
2. Select the model named for the run.
3. Paste the whole of `runs/prompts/{run_id}.md`.
4. Save the reply, exactly as given, to `runs/manual_inbox/{run_id}.txt`.

`gauge import-manual` then logs the replies like any other run. It refuses if a frozen file changed;
it reports (never guesses at) files that are not `<run_id>.txt`, are not planned runs, or are empty. A
manual run is logged as mode `manual`, command `manual-import`, with the reply file's modification time
as its timestamp. The model name logged is the one in `config/models.yaml`, so it must be the model you
selected.

## API mode (the baseline)

An OpenAI-compatible `chat/completions` call to OpenRouter (`https://openrouter.ai/api/v1`), with the
same instructions as the Cursor models in the **system** message and the evidence in the user message.

* `temperature` is 0 and logged. `max_tokens` (16,000), `seed` (42) and `top_p` (not sent) are sent only
  if configured and are logged as sent; the provider-returned model string, the full request body (never
  the key, which travels only in the header) and the full response JSON and the rate-limit headers are
  stored.
* HTTP 429 and 5xx are retried with exponential backoff (1, 2, 4, ... up to 60 s; `Retry-After` is
  honoured), up to `api.max_retries`. A 429 that persists, or names a daily limit, is a usage limit.
* **The baseline model.** OpenRouter's list on 2026-10-02 has no free `gpt-oss-120b`; the default is
  now `nvidia/nemotron-3-super-120b-a12b:free` (V-04). Free models change; the ID is re-checked before
  every start.
* An empty reply (for example a reasoning model that used all its tokens) is stored with its
  `finish_reason` and the run is marked failed.
* Not implemented: splitting a batch by sector (`api.split_batch_by_sector`), because the 262k-token
  context holds the whole prompt; the setting refuses to start if turned on.
* The Groq fallback exists in the client but its model ID is unverified (V-07).

## Parsing and the single repair

`gauge parse` reads each successful run's **raw file** and validates it company by company against the
output schema: a rating of `"3"` or `3.0`, a value out of range, an extra key, a justification over 40
words or a driver name not in the printed list is invalid (only the case and spacing of a driver name
are normalised, V-34). A fenced block or prose around the array is tolerated, a truncated or
trailing-comma reply is not. Every company the prompt listed gets one judgment, `ok` or
`parse_failure` with the reason, so one bad object never discards the others.

`gauge parse --repair --mode cli|api|manual` repeats a run **once**, as a new fresh session, with the
original prompt unchanged followed by a correction notice naming the problems. The repeat is logged as
`<run_id>__repair`. Only the companies that were invalid take their values from it; companies that were
valid keep their first answers, so the repair never resamples. A company still invalid is
`parse_failure` and there is no second attempt (a repair *call* that fails technically, with no reply,
may be tried again). The report gives, per model, the first-reply and the final parse-failure rates and
the number of failed calls.

## What you do, in order

1. Install the Cursor CLI and log in (or set `CURSOR_API_KEY`); run `agent --version`,
   `agent --list-models` and `agent --help`; clear user-level Cursor rules.
2. Fill the four model names in `config/models.yaml` exactly as `--list-models` prints them.
3. Create a free OpenRouter key, put it in `.env` as `OPENROUTER_API_KEY`, and decide on the baseline
   model (V-04).
4. Review `docs/sample_prompts.md`, then freeze (`gauge freeze`), after the sample is final.
5. Smoke tests (one real call each, they ask first):
   `gauge smoke --channel cli --model P1`, and with `--transport stdin` if argv is refused;
   `gauge smoke --channel api --model B1`.
6. Launch: `gauge run --mode cli` (or manual mode), `gauge run --mode api`, then `gauge parse
   --repair --mode ...`.

## Exit codes of `gauge run`

0 finished (or `--limit` reached), 1 refused to start or runs failed, 3 stopped early (usage limit,
repetition gap, repeated failures, Ctrl-C): run the same command again.
