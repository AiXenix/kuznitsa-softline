"""Координация локальных CLI-сборок и открытия снимка движком."""
from contextlib import contextmanager
import fcntl


@contextmanager
def snapshot_lock(data,write=False):
    with (data/".catalog.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        yield
