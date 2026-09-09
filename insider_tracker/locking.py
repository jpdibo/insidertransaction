from __future__ import annotations

import os
import time
import uuid
from pathlib import Path


class LockBusy(RuntimeError):
    pass


class ProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None
        self.token = uuid.uuid4().hex

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            try:
                content = self.path.read_text(encoding="ascii")
                owner_pid = int(content.partition("pid=")[2].splitlines()[0])
                os.kill(owner_pid, 0)
            except (ValueError, IndexError):
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError as stat_exc:
                    raise LockBusy(f"writer lock held or unreadable: {self.path}") from stat_exc
                if age < 5:
                    raise LockBusy(f"writer lock is fresh but incomplete: {self.path}") from exc
                self._reclaim()
            except PermissionError as permission_exc:
                raise LockBusy(f"writer lock owner cannot be inspected: {self.path}") from permission_exc
            except OSError:
                self._reclaim()
            else:
                raise LockBusy(f"writer lock held by pid {owner_pid}: {self.path}") from exc
        os.write(self.fd, f"pid={os.getpid()}\ntoken={self.token}\n".encode("ascii"))
        os.fsync(self.fd)
        return self

    def _reclaim(self) -> None:
        try:
            self.path.unlink()
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, OSError) as retry_exc:
            raise LockBusy(f"writer lock held or cannot be reclaimed: {self.path}") from retry_exc

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            content = self.path.read_text(encoding="ascii")
        except OSError:
            return
        if f"token={self.token}\n" in content:
            try:
                self.path.unlink()
            except OSError:
                pass
