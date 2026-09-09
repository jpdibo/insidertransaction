from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def store_raw(data: bytes, raw_root: Path, suffix: str = ".bin") -> tuple[str, str, int]:
    digest = hashlib.sha256(data).hexdigest()
    relative = Path(digest[:2]) / f"{digest}{suffix}"
    destination = raw_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"hash collision or corrupt raw object: {destination}")
        return digest, relative.as_posix(), len(data)
    fd, temp_name = tempfile.mkstemp(prefix="raw-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if hashlib.sha256(Path(temp_name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("raw object hash verification failed")
        os.replace(temp_name, destination)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return digest, relative.as_posix(), len(data)
