from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_config(path: Path) -> dict[str, Any]:
    """Load JSON-compatible YAML without introducing a runtime YAML dependency."""
    raw = path.read_bytes()
    config = json.loads(raw)
    if config.get("schema_version") != "1.0":
        raise ValueError("unsupported source configuration schema_version")
    source_ids = [source["source_id"] for source in config["sources"]]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("duplicate source_id in configuration")
    return config


def config_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
