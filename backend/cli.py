"""Command-line entry point for the Utilities Management Agent (run from backend/).

  uv run python cli.py --create-database          create the PostgreSQL database in DATABASE_URL (`utilities` on Neon)
  uv run python cli.py --seed-mock                replace the mock roster and incident history (proof of concept)
  uv run python cli.py --init-db                  create the tables (drops the old demo-plant tables if present)
  uv run python cli.py --load FILE.csv [FILE...]  load the CSV files (dataset detected from the header)
  uv run python cli.py --load FILE.csv --replace  ...replacing the rows already stored for that dataset
  uv run python cli.py --status                   what data is loaded
  uv run python cli.py --health                   utility health board (no LLM)
  uv run python cli.py --scan                     monitoring scan -> raise de-duplicated alerts (no LLM)
  uv run python cli.py                            interactive chat with the agent (Domo AI)
  uv run python cli.py "question"                 ask one question   (-v shows the tool trace)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.core.config import settings
from app.db.session import SessionLocal, ensure_database, init_db
from app.services import analytics as an
from app.services import ingest, monitor


def _status():
    with SessionLocal() as s:
        for d in ingest.dataset_status(s):
            rng = f"{d['first_ts']:%Y-%m-%d %H:%M} -> {d['last_ts']:%Y-%m-%d %H:%M}" if d["rows"] else "-"
            print(f"  {d['label']:<18} {d['rows']:>7} rows   {rng}   ({d['file_name']})")


def _load(paths: list[str], replace: bool):
    for p in paths:
        path = Path(p)
        with SessionLocal() as s:
            res = ingest.ingest_csv(s, path.read_bytes(), path.name, mode="replace" if replace else "append")
        print(f"  {res['label']}: {res['inserted']} inserted, {res['duplicates_skipped']} duplicates skipped, "
              f"{res['invalid_skipped']} invalid (file had {res['rows_in_file']}); table now {res['total_rows']} rows")
        for e in res["errors"]:
            print(f"      ! {e}")


def _health():
    with SessionLocal() as s:
        hb = an.health_board(s)
    if hb.get("empty"):
        print(hb["message"])
        return
    print(f"Utility health board, data as of {hb['as_of']:%Y-%m-%d %H:%M}: {hb['overall_status']}")
    for x in hb["utilities"]:
        print(f"\n  {x['utility_type']:<15} {x['status']:<7} flow 24h {x['avg_flow_24h']} "
              f"({x['flow_change_pct']}% vs prev 7d)  alarms 7d: {x['alarms_7d']}")
        for r in x["reasons"]:
            print(f"      - {r}")
    print(f"\n  {hb['anomaly_conclusion']}")
    if hb["downtime_link"]:
        print(f"  {hb['downtime_link']['conclusion']}")


def _scan():
    with SessionLocal() as s:
        res = monitor.run_scan(s)
    print(f"Scan at {res['as_of']:%Y-%m-%d %H:%M}: {res['created_count']} new alert(s), "
          f"{res['already_open_count']} already open.")
    for a in res["created"]:
        print(f"  #{a['id']} [{a['severity']}] {a['utility_type']}: {a['title']} -> {a['assigned_to']}")


def _ask(question, history, verbose):
    from app.agent.agent import run_agent          # lazy: non-LLM commands work without a token
    from app.agent.domo_llm import DomoAPIError
    try:
        result = run_agent(question, history)
    except DomoAPIError as e:
        print(f"Domo AI error: {e}")
        return None
    if verbose:
        for i, st in enumerate(result.steps, 1):
            print(f"  [{i}] {st['tool']}({json.dumps(st['input'])}) -> {st['output'][:160]}...")
        print(f"  ({result.usage.get('llm_calls')} Domo calls, {result.usage.get('input_tokens')} in / "
              f"{result.usage.get('output_tokens')} out tokens, {result.duration_ms / 1000:.1f}s)")
    print(f"\n{result.answer}\n")
    return result.answer


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Utilities Management Agent")
    p.add_argument("question", nargs="*", help="question for the agent (omit for interactive chat)")
    p.add_argument("-v", "--verbose", action="store_true", help="show tool calls")
    p.add_argument("--load", nargs="+", metavar="CSV", help="load one or more CSV files")
    p.add_argument("--replace", action="store_true", help="with --load: replace the stored rows of that dataset")
    for flag in ("--health", "--scan", "--status", "--init-db", "--create-database", "--seed-mock", "--clear-mock"):
        p.add_argument(flag, action="store_true")
    p.add_argument("--json", action="store_true", help="with --health: print raw JSON")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    if args.create_database:
        print(ensure_database())
        return

    print(f"Database: {'PostgreSQL' if settings.is_postgres else 'SQLite (set DATABASE_URL for Neon)'}",
          file=sys.stderr)
    dropped = init_db()
    if dropped:
        print(f"Dropped old demo-plant tables: {', '.join(dropped)}")
    if args.seed_mock:
        from app.twin import mock
        print(mock.seed())
        return
    if args.clear_mock:
        from app.twin import mock
        with SessionLocal() as s:
            print(mock.clear_mock(s))
            s.commit()
        return
    if args.load:
        _load(args.load, args.replace)
        return
    if args.init_db:
        print("Tables are ready. Load data with --load or from the Data page of the app.")
        return
    if args.status:
        _status()
        return
    if args.health:
        if args.json:
            from app.agent.tools import to_json
            with SessionLocal() as s:
                print(to_json(an.health_board(s)))
        else:
            _health()
        return
    if args.scan:
        _scan()
        return
    if args.question:
        _ask(" ".join(args.question), [], args.verbose)
        return

    print("Utilities Management Agent - ask about compressed air, chilled water, HVAC, process water or nitrogen.\n"
          "Type 'exit' to quit.\n")
    history: list[dict] = []
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in ("exit", "quit"):
            break
        if not q:
            continue
        answer = _ask(q, history, args.verbose)
        if answer:
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]


if __name__ == "__main__":
    main()
