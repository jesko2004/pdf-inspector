"""Cleanup only service-owned leftovers while the executor is exclusively held."""

import os
import re
import shutil
import signal
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from threading import Thread
from time import sleep

from .execution_lock import SingleExecutorLock

UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def cleanup_owned_files(data_dir: Path):
    data_dir = data_dir.resolve()
    cleaned = 0
    work = data_dir / "work"
    if work.is_dir() and not work.is_symlink():
        for path in work.iterdir():
            if path.name.startswith("worker-") and path.is_dir() and not path.is_symlink() and path.resolve().parent == work:
                shutil.rmtree(path)
                cleaned += 1
    known_tasks = set()
    database = data_dir / "tasks.sqlite3"
    if database.is_file():
        with closing(sqlite3.connect(database)) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone():
                known_tasks = {r[0] for r in connection.execute("SELECT id FROM tasks")}
    for folder, suffixes in (("uploads", (".upload", ".pdf")), ("results", (".tmp",))):
        directory = data_dir / folder
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in directory.iterdir():
            identity = path.name.removesuffix(".json.tmp") if path.name.endswith(".json.tmp") else path.stem
            if (path.is_file() and not path.is_symlink() and path.resolve().parent == directory
                    and path.suffix in suffixes and UUID.fullmatch(identity)
                    and (path.suffix != ".pdf" or path.stem not in known_tasks)):
                path.unlink()
                cleaned += 1
    # A lease absent from metadata has no reader to preserve. Keep referenced
    # leases for the normal transactionally guarded lifecycle reaper.
    leases = data_dir / "index-leases"
    knowledge = data_dir / "knowledge.sqlite3"
    known_leases = set()
    if knowledge.is_file():
        with closing(sqlite3.connect(knowledge)) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='retrieval_leases'").fetchone():
                known_leases = {r[0] for r in connection.execute("SELECT id FROM retrieval_leases")}
    if leases.is_dir() and not leases.is_symlink():
        for path in leases.iterdir():
            if path.suffix == ".lock" and UUID.fullmatch(path.stem) and path.stem not in known_leases and not path.is_symlink():
                try:
                    lock = SingleExecutorLock(path)
                except (OSError, RuntimeError):
                    continue
                lock.close()
                path.unlink()
                cleaned += 1
    return cleaned


def guard_parent_exit():
    """Linux native worker kills its whole process group if its parent exits."""
    if os.name == "nt":
        return  # KILL_ON_JOB_CLOSE already provides this ownership rule.
    if os.getpgrp() != os.getpid():
        raise RuntimeError("native worker requires its own process group")
    parent = os.getppid()
    if sys.platform.startswith("linux"):
        import ctypes
        def kill_group(_signum, _frame):
            os.killpg(os.getpgrp(), signal.SIGKILL)
        signal.signal(signal.SIGTERM, kill_group)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            raise RuntimeError("cannot install native parent-death guard")
        if os.getppid() != parent or parent == 1:
            kill_group(None, None)
    else:
        def watch():
            while os.getppid() == parent:
                sleep(0.1)
            os.killpg(os.getpgrp(), signal.SIGKILL)
        Thread(target=watch, daemon=True).start()
