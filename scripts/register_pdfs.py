"""File downloaded BRSR PDFs under data/raw/pdf/<SYMBOL>_<FY>.pdf and list them in a manifest.

    python scripts/register_pdfs.py <folder-or-files...> [--apply]

Without --apply it only reports what it would do. A PDF whose company or year is ambiguous is left
where it is. The manifest (data/reference/pdf_manifest.csv) is tracked; the PDFs are not (data/raw).
"""

from __future__ import annotations

import csv
import hashlib
import logging
import shutil
import sys
from pathlib import Path

from pypdf import PdfReader

from gauge.ingest.pool import load_pool
from gauge.ingest.rawfiles import identify_pdf

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings on some annual reports
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "reference" / "pdf_manifest.csv"
COLUMNS = ["stored_name", "original_name", "nse_symbol", "isin", "fy", "pages", "bytes", "sha256",
           "match_evidence"]  # fmt: skip


def first_pages_text(path: Path, n: int = 6) -> tuple[str, int]:
    reader = PdfReader(path)
    return "\n".join((p.extract_text() or "") for p in reader.pages[:n]), len(reader.pages)


def main(args: list[str]) -> None:
    apply = "--apply" in args
    sources = [Path(a) for a in args if not a.startswith("--")]
    files = [f for s in sources for f in (sorted(s.glob("*.pdf")) if s.is_dir() else [s])]
    pool = load_pool(ROOT)
    out_dir = ROOT / "data" / "raw" / "pdf"
    rows, seen = [], set()
    for f in files:
        data = f.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen:
            print(f"duplicate (same bytes), skipped: {f.name}")
            continue
        seen.add(sha)
        text, pages = first_pages_text(f)
        match = identify_pdf(text, pool)
        if match.entry is None or match.fy is None:
            why = match.evidence if match.entry is None else "fiscal year not determined"
            print(f"LEFT   {f.name}: {why}")
            continue
        stored = f"{match.entry.nse_symbol}_{match.fy}.pdf"
        print(f"FILE   {f.name} -> {stored}  ({match.evidence}, {pages} pages)")
        rows.append(
            {
                "stored_name": stored,
                "original_name": f.name,
                "nse_symbol": match.entry.nse_symbol,
                "isin": match.entry.isin,
                "fy": match.fy,
                "pages": pages,
                "bytes": len(data),
                "sha256": sha,
                "match_evidence": match.evidence,
            }
        )
        if apply:
            out_dir.mkdir(parents=True, exist_ok=True)
            target = out_dir / stored
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                target = out_dir / f"{match.entry.nse_symbol}_{match.fy}_{sha[:8]}.pdf"
            if not target.exists():
                shutil.copy2(f, target)
    if apply and rows:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        with MANIFEST.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda r: r["stored_name"]))
        print(f"\nwrote {MANIFEST.relative_to(ROOT)} ({len(rows)} PDFs)")
    elif not apply:
        print("\n(dry run: nothing copied; add --apply)")


if __name__ == "__main__":
    main(sys.argv[1:])
