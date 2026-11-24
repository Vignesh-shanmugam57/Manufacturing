"""Load the plant CSV files from a folder into the database (Neon), with the same checks as the upload page.

Usage, from the backend folder:
    uv run python scripts/load_docs.py ../docs

Only files whose header matches a dataset the app knows are loaded; other files are reported and skipped.
Repeating the run is safe: rows that are already stored are skipped. The app reads the database at runtime, never
these files.
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import ingest  # noqa: E402


def main(folder: Path) -> int:
    if not folder.is_dir():
        print(f"not a folder: {folder}")
        return 2
    Base.metadata.create_all(engine)            # make sure every table exists in the database first
    loaded = skipped = 0
    with SessionLocal() as s:
        for path in sorted(folder.glob("*.csv")):
            data = path.read_bytes()
            header = next(csv.reader(io.StringIO(data.decode("utf-8-sig"))), [])
            if ingest.detect_dataset([h.strip() for h in header]) is None:
                print(f"skip   {path.name}: not a dataset the app uses")
                skipped += 1
                continue
            try:
                r = ingest.ingest_csv(s, data, path.name, "auto", "append")
            except ValueError as e:
                print(f"error  {path.name}: {e}")
                skipped += 1
                continue
            print(f"ok     {path.name}: {r['label']}: {r['inserted']:,} rows added, "
                  f"{r['duplicates_skipped']:,} already stored, {r['invalid_skipped']:,} invalid; "
                  f"table now {r['total_rows']:,} rows")
            loaded += 1
    print(f"done: {loaded} file(s) loaded, {skipped} skipped")
    return 0


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND.parent / "docs"
    sys.exit(main(folder.resolve()))
