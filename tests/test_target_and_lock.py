import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safe_extract import (  # noqa: E402
    TargetConflictError,
    safe_extract,
)
from tests._helpers import make_zip  # noqa: E402


class TargetConflictTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="safe_extract_test_")

    def target(self, name):
        return os.path.join(self.workdir, name)

    def make_archive(self, name="a.zip", payload=b"hello"):
        archive = self.target(name)
        make_zip(archive, [("f", payload)])
        return archive

    def test_existing_destination_is_rejected_and_untouched(self):
        archive = self.make_archive()
        dest = self.target("existing")
        os.mkdir(dest)
        marker = os.path.join(dest, "marker")
        with open(marker, "wb") as handle:
            handle.write(b"original")
        with self.assertRaises(TargetConflictError):
            safe_extract(archive, dest)
        with open(marker, "rb") as handle:
            self.assertEqual(handle.read(), b"original")

    def test_existing_symlink_destination_is_rejected(self):
        archive = self.make_archive()
        elsewhere = self.target("elsewhere")
        os.mkdir(elsewhere)
        link = self.target("link_dest")
        os.symlink(elsewhere, link)
        with self.assertRaises(TargetConflictError):
            safe_extract(archive, link)
        self.assertTrue(os.path.islink(link))

    def test_missing_parent_directory_is_rejected(self):
        archive = self.make_archive()
        with self.assertRaises(TargetConflictError):
            safe_extract(archive, self.target("no/such/parent/out"))

    def test_publish_race_is_conflict_not_corruption(self):
        import safe_extract.engine as engine

        archive = self.make_archive()
        original_rename = os.rename

        def racing_rename(src, dst):
            raise FileExistsError(17, "simulated publish race")

        os.rename = racing_rename
        try:
            with self.assertRaises(TargetConflictError):
                safe_extract(archive, self.target("raced"))
        finally:
            os.rename = original_rename
        self.assertFalse(os.path.exists(self.target("raced")))
        leftovers = [
            name
            for name in os.listdir(self.workdir)
            if name.startswith(".__safe_extract_")
        ]
        self.assertEqual(leftovers, [])

    def test_lock_is_removed_after_success_and_failure(self):
        archive = self.make_archive()
        dest = self.target("ok")
        safe_extract(archive, dest)
        self.assertFalse(os.path.exists(dest + ".lock"))

        bad = self.target("bad.zip")
        make_zip(bad, [("../escape", b"x")])
        with self.assertRaises(Exception):
            safe_extract(bad, self.target("bad_out"))
        self.assertFalse(os.path.exists(self.target("bad_out.lock")))
        leftovers = [
            name
            for name in os.listdir(self.workdir)
            if name.startswith(".__safe_extract_")
        ]
        self.assertEqual(leftovers, [])


class ConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="safe_extract_test_")
        self.archive = os.path.join(self.workdir, "a.zip")
        make_zip(self.archive, [("f", b"concurrent")])
        self.dest = os.path.join(self.workdir, "out")

    def test_threads_only_one_succeeds(self):
        errors = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            try:
                safe_extract(self.archive, self.dest)
            except TargetConflictError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(errors), 7)
        self.assertTrue(os.path.isdir(self.dest))
        with open(os.path.join(self.dest, "f"), "rb") as handle:
            self.assertEqual(handle.read(), b"concurrent")
        self.assertFalse(os.path.exists(self.dest + ".lock"))

    def test_lock_timeout_waits_then_succeeds_after_release(self):
        from safe_extract.lock import DestinationLock

        held = DestinationLock(self.dest)
        held.acquire()
        result = {}

        def waiter():
            try:
                safe_extract(self.archive, self.dest, lock_timeout=3.0)
                result["ok"] = True
            except Exception as exc:  # pragma: no cover - failure path
                result["error"] = exc

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.3)
        held.release()
        thread.join(timeout=5)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.isdir(self.dest))

    def test_stale_lock_from_dead_process_is_taken_over(self):
        lock_path = self.dest + ".lock"
        # A PID that cannot exist on the system is treated as dead.
        fake_pid = 2_000_000
        with open(lock_path, "w") as handle:
            handle.write("{}\n".format(fake_pid))
        result = safe_extract(self.archive, self.dest, lock_timeout=0.2)
        self.assertEqual(result.target, os.path.abspath(self.dest))
        self.assertFalse(os.path.exists(lock_path))

    def test_subprocesses_only_one_succeeds(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = "\n".join(
            [
                "import sys",
                "sys.path.insert(0, {!r})".format(root),
                "from safe_extract import safe_extract, TargetConflictError",
                "try:",
                "    safe_extract({!r}, {!r})".format(self.archive, self.dest),
                "    print('WON')",
                "except TargetConflictError:",
                "    print('LOST')",
            ]
        )
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(4)
        ]
        outcomes = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(
                process.returncode,
                0,
                stderr.decode(errors="replace"),
            )
            outcomes.append(stdout.decode().strip())
        self.assertEqual(sorted(outcomes).count("LOST"), 3)
        self.assertEqual(sorted(outcomes).count("WON"), 1)
        self.assertTrue(os.path.isdir(self.dest))
        self.assertFalse(os.path.exists(self.dest + ".lock"))


if __name__ == "__main__":
    unittest.main()
