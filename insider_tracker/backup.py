from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .db import connect


def create_backup(database: Path, raw_root: Path, destination_root: Path, version: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_root.mkdir(parents=True, exist_ok=True)
    final = destination_root / stamp
    temp = Path(tempfile.mkdtemp(prefix="backup-", dir=destination_root))
    try:
        source = connect(database, readonly=True)
        target = sqlite3.connect(temp / "insiders.sqlite3")
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        check = sqlite3.connect(temp / "insiders.sqlite3")
        check.row_factory = sqlite3.Row
        rows = check.execute("SELECT sha256, relative_path, size_bytes FROM raw_objects ORDER BY sha256").fetchall()
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        check.close()
        if integrity != "ok":
            raise RuntimeError(f"backup integrity check failed: {integrity}")
        manifest_objects = []
        for row in rows:
            source_path = raw_root / row["relative_path"]
            if not source_path.is_file():
                raise FileNotFoundError(f"referenced raw object missing: {source_path}")
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != row["sha256"]:
                raise RuntimeError(f"raw hash mismatch: {source_path}")
            destination = temp / "raw" / row["relative_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination)
            manifest_objects.append(dict(row))
        manifest = {"created_at": stamp, "code_version": version, "database": "insiders.sqlite3", "raw_objects": manifest_objects}
        (temp / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, final)
        return final
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def restore_backup(bundle: Path, destination: Path) -> None:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError("restore destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundle / manifest["database"], destination / "insiders.sqlite3")
    for item in manifest["raw_objects"]:
        source = bundle / "raw" / item["relative_path"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError(f"backup raw hash mismatch: {source}")
        target = destination / "raw" / item["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    connection = connect(destination / "insiders.sqlite3")
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("restored database integrity check failed")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"restored database foreign-key violations: {len(violations)}")
    finally:
        connection.close()
