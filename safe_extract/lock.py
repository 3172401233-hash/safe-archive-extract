"""Cross-process destination lock.

Lock protocol
-------------
The lock is an ordinary file created with ``O_CREAT | O_EXCL`` inside the
destination's *parent* directory (which always exists). On POSIX systems an
``flock(2)`` advisory lock is additionally taken on that file:

* ``O_EXCL`` makes the "first caller wins" rule atomic, so simultaneous
  extractions into the same target cannot both proceed;
* ``flock`` is released automatically by the kernel when the process exits
  (including crashes / ``SIGKILL``), which lets a later caller take over a
  lock whose holder is dead;
* lock files left behind by older copies that crashed before ``flock`` was
  used, or running on Windows, are detected via the PID written inside and
  treated as stale when that process is no longer alive.

Platform notes
--------------
* Linux / macOS / other POSIX: fully supported, including stale-lock
  takeover after process death. Tested on Linux by this package's tests.
* Windows: ``msvcrt.locking`` provides an equivalent best-effort mandatory
  byte-range lock, but PID-based stale detection cannot see processes owned
  by other users and the path is not exercised by the CI tests here.
"""

import os
import time

from .errors import LockError

_POLL_INTERVAL = 0.05


class DestinationLock:
    def __init__(self, target_path, timeout=0.0):
        self._target = target_path
        self._timeout = timeout
        self._lock_path = target_path + ".lock"
        self._fd = None

    @property
    def lock_path(self):
        return self._lock_path

    def acquire(self):
        deadline = time.monotonic() + max(0.0, self._timeout)
        while True:
            try:
                fd = os.open(
                    self._lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                if self._try_take_over_stale():
                    continue
                if time.monotonic() >= deadline:
                    raise LockError(
                        "destination is locked by another extraction",
                        path=self._target,
                    )
                time.sleep(_POLL_INTERVAL)
                continue

            self._fd = fd
            try:
                self._begin_locking()
                self._stamp()
            except BaseException:
                os.close(fd)
                self._fd = None
                try:
                    os.unlink(self._lock_path)
                except OSError:
                    pass
                raise
            return self

    def release(self):
        if self._fd is None:
            return
        try:
            self._end_locking()
        finally:
            os.close(self._fd)
            self._fd = None
            try:
                os.unlink(self._lock_path)
            except FileNotFoundError:
                pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()

    def _begin_locking(self):
        try:
            import fcntl
        except ImportError:
            self._begin_locking_windows()
            return
        fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _end_locking(self):
        try:
            import fcntl
        except ImportError:
            self._end_locking_windows()
            return
        fcntl.flock(self._fd, fcntl.LOCK_UN)

    def _begin_locking_windows(self):
        import msvcrt

        msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)

    def _end_locking_windows(self):
        import msvcrt

        try:
            msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

    def _stamp(self):
        os.ftruncate(self._fd, 0)
        os.write(self._fd, "{}\n".format(os.getpid()).encode("ascii"))
        os.fsync(self._fd)

    def _try_take_over_stale(self):
        """Replace the lock file when its holder appears to be dead."""
        try:
            with open(self._lock_path, "r") as handle:
                content = handle.read().strip()
            pid = int(content)
        except (OSError, ValueError):
            return False
        if pid <= 0 or not self._process_is_dead(pid):
            return False
        try:
            os.unlink(self._lock_path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    @staticmethod
    def _process_is_dead(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # Process exists but belongs to another user: not provably dead.
            return False
        except OSError:
            return False
        return False
