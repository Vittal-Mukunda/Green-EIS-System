"""Write a deployable snapshot of the evidence database for the public demo.

    python scripts/make_demo_snapshot.py [--source data/processed/gauge.db] [--out data/demo/gauge_demo.db]

The snapshot is a consistent copy (SQLite backup API; the source is only read) with everything that is
not evidence removed: human annotations and all model-run tables. The deployed demo shows only the
evidence views, and a visitor's changes then land in the copy, never in the working database.

It refuses to write an empty snapshot and warns if any text column holds a local path.
Standard library only, so it runs without the project installed.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Tables that hold model runs or human labels on them, children before parents.
RUN_TABLES = (
    "annotation",
    "disagreement_flag",
    "evaluation_result",
    "transition_result",
    "claim",
    "judgment",
    "run_company_position",
    "run",
)
# What the evidence views need; a snapshot without these would show empty pages.
REQUIRED = ("company", "report", "indicator_value", "kpi_value")
BACKSLASH = chr(92)


def tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return [r[0] for r in rows if not r[0].startswith("sqlite_")]


def count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def local_path_hits(con: sqlite3.Connection) -> list[str]:
    """Columns that contain something that looks like a path on the owner's machine."""
    hits = []
    for table in tables(con):
        for _, name, kind, *_ in con.execute(f'PRAGMA table_info("{table}")').fetchall():
            if "CHAR" not in kind.upper() and "TEXT" not in kind.upper():
                continue
            pattern = f"%:{BACKSLASH}%"
            n = con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{name}" LIKE ? OR "{name}" LIKE ?',
                (pattern, "%/Users/%"),
            ).fetchone()[0]
            if n:
                hits.append(f"{table}.{name} ({n} rows)")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", default="data/processed/gauge.db")
    parser.add_argument("--out", default="data/demo/gauge_demo.db")
    args = parser.parse_args()
    source = Path(args.source)
    out = Path(args.out)
    source = source if source.is_absolute() else ROOT / source
    out = out if out.is_absolute() else ROOT / out
    if not source.is_file():
        print(f"source database not found: {source}", file=sys.stderr)
        return 1
    if source.resolve() == out.resolve():
        print("source and output are the same file", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        src.close()

    try:
        present = set(tables(dst))
        removed = {}
        dst.execute("PRAGMA foreign_keys = OFF")
        for table in RUN_TABLES:
            if table in present:
                removed[table] = count(dst, table)
                dst.execute(f'DELETE FROM "{table}"')
        dst.commit()

        missing = [t for t in REQUIRED if t not in present or count(dst, t) == 0]
        if missing:
            dst.close()
            out.unlink(missing_ok=True)
            print(
                f"refusing to write an empty snapshot; no rows in: {', '.join(missing)}",
                file=sys.stderr,
            )
            return 1

        dst.execute("PRAGMA journal_mode = DELETE")
        dst.execute("VACUUM")
        print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
        for table in REQUIRED + ("quality_flag", "sector_benchmark"):
            if table in present:
                print(f"  {table}: {count(dst, table)} rows")
        dropped = {t: n for t, n in removed.items() if n}
        print(
            "  removed run/annotation rows: "
            + (", ".join(f"{t} {n}" for t, n in dropped.items()) or "none")
        )
        hits = local_path_hits(dst)
        if hits:
            print(
                "WARNING: text that looks like a local path in " + "; ".join(hits), file=sys.stderr
            )
            return 2
    finally:
        dst.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
