"""Locks between title-runs processes on one computer: the window and the command line, or two command lines, share
one state folder and one config file.

held(path): a file lock (<file>.lock beside it) for a read, change and write of a shared file: the status file, the
local tests list, the config, the sign-in.

Runner: state/client/runner.lock, held by the one process running a test on this computer, so two never run at once.
The holder writes its process ID into the file, so another process can say who is testing. While it holds the lock it
also watches the status file for a stop request: Stop in the window or `title-runs stop` may come from another
process, which can't end this one's build or game itself.
"""

import contextlib
import os
import threading
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: msvcrt's byte-range locks (written, not yet run there)
    fcntl = None
    import msvcrt


def _lock(handle, blocking=True):
    if fcntl:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    else:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)


def _unlock(handle):
    if fcntl:
        fcntl.flock(handle, fcntl.LOCK_UN)
    else:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


_threads = {}  # lock file -> threading.RLock: a process's own threads queue up before the file lock
_guard = threading.Lock()


@contextlib.contextmanager
def held(path):
    """An exclusive lock for the shared file path, for the with block; waits for another holder, in this process or another."""
    lock_path = Path(str(path) + ".lock")
    with _guard:
        thread_lock = _threads.setdefault(str(lock_path), threading.RLock())
    with thread_lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+") as handle:
            _lock(handle)
            try:
                yield
            finally:
                _unlock(handle)


class Busy(RuntimeError):
    """Another process on this computer is running a test."""


class Runner:
    """The runner lock. with Runner(state_dir).hold(status, stop): run one test; raises Busy when another process holds
    it. stop() is called once if the status file asks for a stop while the test runs."""

    def __init__(self, state_dir):
        self.path = Path(state_dir) / "client" / "runner.lock"

    def holder(self):
        """The process ID of another process running a test here, or None."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+") as handle:
            try:
                _lock(handle, blocking=False)
            except OSError:
                handle.seek(0)
                text = handle.read().strip()
                return int(text) if text.isdigit() else -1
            _unlock(handle)
            return None

    @contextlib.contextmanager
    def hold(self, status=None, stop=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")
        try:
            try:
                _lock(handle, blocking=False)
            except OSError:
                handle.seek(0)
                text = handle.read().strip()
                raise Busy(f"another title-runs process (pid {text or '?'}) is running a test on this computer") from None
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
            done = threading.Event()
            if status is not None:
                status.update(stop_requested=False)  # a stop asked for before this test was for the one before it
            if status is not None and stop is not None:
                threading.Thread(target=self._watch, args=(status, stop, done), name="stop-watch", daemon=True).start()
            try:
                yield
            finally:
                done.set()
                handle.seek(0)
                handle.truncate()
                handle.flush()
                _unlock(handle)
        finally:
            handle.close()

    @staticmethod
    def _watch(status, stop, done):
        while not done.wait(1):
            if status.read().get("stop_requested"):
                stop()
                return
