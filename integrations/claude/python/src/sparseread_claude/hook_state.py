"""Bounded, process-safe one-time redirect state for Claude hook invocations."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_TTL = 24 * 60 * 60
_MAX = 512


@contextmanager
def _locked_state(directory: Path) -> Iterator[Path]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = directory / "state.lock"
    if lock_path.is_symlink():
        raise ValueError("invalid state lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(lock_path, flags, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError("invalid state lock")
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            def unlock() -> None:
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            def unlock() -> None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        try:
            yield directory / "state.json"
        finally:
            unlock()


def claim_redirect(workspace: str | None, session_id: str, path: Path) -> bool:
    """Return true only for a new source identity; state failures fail open."""
    if not workspace or not session_id:
        return False
    try:
        root = Path(workspace).resolve(strict=True)
        path = path.resolve(strict=True)
        source_stat = path.stat()
        identity = (source_stat.st_dev, source_stat.st_ino, source_stat.st_size, source_stat.st_mtime_ns, source_stat.st_ctime_ns)
        key = hashlib.sha256(f"{root}\0{session_id}\0{path}\0{identity}".encode()).hexdigest()
        directory = root / ".sparseread" / "claude-hook"
        if directory.is_symlink() or directory.parent.is_symlink():
            return False
        now = time.time()
        with _locked_state(directory) as state_path:
            if state_path.is_symlink():
                return False
            if state_path.exists():
                fd = os.open(state_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
                with os.fdopen(fd, "rb") as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                        return False
                    data = json.loads(source.read(65537))
                if not isinstance(data, dict) or not isinstance(data.get("redirects"), dict):
                    return False
                redirects = data["redirects"]
            else:
                redirects = {}
            redirects = {k: v for k, v in redirects.items() if isinstance(k, str) and isinstance(v, (int, float)) and 0 <= now - v < _TTL}
            if key in redirects:
                return False
            redirects[key] = now
            redirects = dict(sorted(redirects.items(), key=lambda item: item[1])[-_MAX:])
            fd, name = tempfile.mkstemp(prefix=".state-", dir=directory)
            temporary = Path(name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    json.dump({"redirects": redirects}, out, separators=(",", ":"))
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, state_path)
            finally:
                temporary.unlink(missing_ok=True)
        return True
    except (OSError, ValueError, TypeError):
        return False
