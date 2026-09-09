from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .backup import create_backup, restore_backup
from .audit import create_audit_sample
from .config import config_hash, load_config
from .db import connect, migrate
from .locking import LockBusy, ProcessLock
from .pipeline import reconcile_cross_source_duplicates, recover_abandoned_runs, reparse_saved, run_daily, seed_registry
from .web import serve

ROOT = Path(__file__).resolve().parents[1]


def _paths(args):
    return Path(args.database), Path(args.config), Path(args.raw_root)


def _prepare(args):
    database, config_path, _ = _paths(args)
    config = load_config(config_path)
    connection = connect(database)
    migrate(connection, ROOT / "migrations")
    recover_abandoned_runs(connection)
    seed_registry(connection, config, config_hash(config_path))
    return connection, config


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m insider_tracker")
    result.add_argument("--database", default=str(ROOT / "data" / "insiders.sqlite3"))
    result.add_argument("--config", default=str(ROOT / "config" / "sources.yaml"))
    result.add_argument("--raw-root", default=str(ROOT / "data" / "raw"))
    sub = result.add_subparsers(dest="command", required=True)
    def common(command):
        command.add_argument("--database", default=argparse.SUPPRESS)
        command.add_argument("--config", default=argparse.SUPPRESS)
        command.add_argument("--raw-root", default=argparse.SUPPRESS)
        return command
    common(sub.add_parser("init-db"))
    daily = common(sub.add_parser("daily")); daily.add_argument("--cutoff"); daily.add_argument("--source", action="append")
    probe = common(sub.add_parser("probe")); probe.add_argument("--source", action="append")
    backfill = common(sub.add_parser("backfill")); backfill.add_argument("--cutoff", required=True); backfill.add_argument("--source", action="append")
    for name in ("reparse", "reconcile", "rebuild-metrics", "retry-quarantine"):
        command = common(sub.add_parser(name)); command.add_argument("--source", action="append"); command.add_argument("--dry-run", action="store_true")
    common(sub.add_parser("show-coverage"))
    backup = common(sub.add_parser("backup")); backup.add_argument("--destination", default=str(ROOT / "data" / "backups"))
    audit_sample = common(sub.add_parser("audit-sample")); audit_sample.add_argument("--source", required=True); audit_sample.add_argument("--size", type=int, default=50); audit_sample.add_argument("--output")
    restore = sub.add_parser("restore"); restore.add_argument("bundle"); restore.add_argument("destination")
    web = common(sub.add_parser("web")); web.add_argument("--host", default="127.0.0.1"); web.add_argument("--port", type=int, default=8080)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    database, config_path, raw_root = _paths(args)
    if args.command == "restore":
        restore_backup(Path(args.bundle), Path(args.destination)); print("restore verified"); return 0
    if args.command == "web":
        serve(database, args.host, args.port); return 0
    lock_path = database.parent / "lock"
    try:
        with ProcessLock(lock_path):
            connection, config = _prepare(args)
            try:
                if args.command == "init-db":
                    print(f"initialized {database}"); return 0
                if args.command in {"daily", "backfill"}:
                    cutoff = args.cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                    outcome = run_daily(connection, config, config_path, raw_root, ROOT / "data" / "reports", cutoff, set(args.source or []), mode=args.command)
                    backup_path = None
                    try:
                        backup_path = create_backup(database, raw_root, ROOT / "data" / "backups", __version__)
                    except Exception as exc:
                        outcome.status = "partial_failure"
                        connection.execute("UPDATE ingestion_runs SET status='partial_failure' WHERE id=?", (outcome.run_id,)); connection.commit()
                        print(f"backup failed: {exc}", file=sys.stderr)
                    print(json.dumps({"run_id": outcome.run_id, "status": outcome.status, "backup": str(backup_path) if backup_path else None, "sources": [item.__dict__ for item in outcome.sources]}, indent=2))
                    return 0 if outcome.status == "success" else 2
                if args.command == "probe":
                    selected = set(args.source or [])
                    rows = [source for source in config["sources"] if not selected or source["source_id"] in selected]
                    print(json.dumps([{"source_id": source["source_id"], "adapter": source["adapter"], "configured_status": source["status"], "probe": "fixture_available" if source["adapter"] == "fixture_json" and Path(source["fixture_path"]).is_dir() else "registry_only_not_tested"} for source in rows], indent=2)); return 0
                if args.command == "show-coverage":
                    rows = connection.execute("SELECT jurisdiction_code,source_id,status,last_verified_at,rights_status FROM sources ORDER BY jurisdiction_code").fetchall()
                    print(json.dumps([dict(row) for row in rows], indent=2)); return 0
                if args.command == "backup":
                    destination = create_backup(database, raw_root, Path(args.destination), __version__)
                    print(destination); return 0
                if args.command == "audit-sample":
                    output = Path(args.output) if args.output else ROOT / "data" / "reports" / f"audit_{args.source}.csv"
                    count = create_audit_sample(connection, args.source, args.size, output)
                    print(json.dumps({"source_id": args.source, "requested": args.size, "generated": count, "output": str(output)}))
                    return 0
                if args.command in {"reparse", "reconcile", "rebuild-metrics", "retry-quarantine"}:
                    if args.command == "reconcile":
                        candidates = reconcile_cross_source_duplicates(connection, dry_run=args.dry_run)
                        print(json.dumps({"command": "reconcile", "dry_run": args.dry_run, "candidates": candidates}))
                        return 0
                    if args.command in {"reparse", "retry-quarantine"}:
                        outcome = reparse_saved(connection, config, config_path, raw_root, set(args.source or []), args.dry_run)
                        print(json.dumps({"command": args.command, "dry_run": args.dry_run, **outcome}, indent=2))
                        return 0 if not outcome["quarantined"] else 2
                    print(json.dumps({"command": args.command, "dry_run": args.dry_run, "status": "no_pending_work"})); return 0
            finally:
                connection.close()
    except LockBusy as exc:
        print(str(exc), file=sys.stderr)
        return 3
    return 1
