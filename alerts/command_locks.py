from contextlib import contextmanager
import os
from pathlib import Path
import time

from django.conf import settings


class CommandAlreadyRunning(RuntimeError):
    pass


@contextmanager
def command_lock(name: str, *, timeout: int | None = None):
    lock_timeout = timeout or settings.ARGUS_COMMAND_LOCK_TIMEOUT_SECONDS
    lock_dir = Path(settings.BASE_DIR) / "tmp" / "command_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{name}.lock"

    _remove_stale_lock(lock_path, lock_timeout)

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise CommandAlreadyRunning(f"{name} is already running.") from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(f"pid={os.getpid()}\ncreated_at={int(time.time())}\n")
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _remove_stale_lock(lock_path: Path, timeout: int) -> None:
    try:
        stat = lock_path.stat()
    except FileNotFoundError:
        return

    if time.time() - stat.st_mtime > timeout:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
