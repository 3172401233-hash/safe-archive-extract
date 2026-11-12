import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safe_extract import UnsafeContentError, safe_extract  # noqa: E402
from tests._helpers import (  # noqa: E402
    file_info,
    make_tar,
    make_zip,
)


UNSAFE_NAMES = [
    "../escape",
    "foo/../../escape",
    "foo/../bar/../../escape",
    "/etc/passwd",
    "//etc/passwd",
    "//server/share/doc",
    "C:/Windows/system32",
    "C:relative",
    "D:\\evil",
    "foo\\bar",
]

# NUL bytes are stripped by tarfile/zipfile while archives are *written*,
# so they are covered separately at the validator level.
NUL_NAMES = ["foo\x00bar", "foo/\x00"]


class UnsafePathsTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="safe_extract_test_")
        self.sentinel = os.path.join(self.workdir, "sentinel")
        with open(self.sentinel, "wb") as handle:
            handle.write(b"untouched")

    def target(self, name):
        return os.path.join(self.workdir, name)

    def _assert_failure_cleanup(self, archive, dest):
        with self.assertRaises(UnsafeContentError) as caught:
            safe_extract(archive, dest)
        self.assertIsNotNone(caught.exception.member)
        self.assertFalse(os.path.exists(dest))
        self.assertEqual(
            os.listdir(self.workdir).count("sentinel"), 1
        )
        with open(self.sentinel, "rb") as handle:
            self.assertEqual(handle.read(), b"untouched")
        leftovers = [
            name
            for name in os.listdir(self.workdir)
            if name.startswith(".__safe_extract_") or name.endswith(".lock")
        ]
        self.assertEqual(leftovers, [])

    def test_unsafe_zip_member_names(self):
        for index, name in enumerate(UNSAFE_NAMES):
            archive = self.target("bad{}.zip".format(index))
            make_zip(archive, [(name, b"x")])
            self._assert_failure_cleanup(
                archive, self.target("dest{}".format(index))
            )

    def test_unsafe_tar_member_names(self):
        for index, name in enumerate(UNSAFE_NAMES):
            archive = self.target("bad{}.tar".format(index))
            make_tar(archive, [(file_info(name, b"x"), b"x")])
            self._assert_failure_cleanup(
                archive, self.target("dest{}".format(index))
            )

    def test_nul_byte_member_names_are_rejected(self):
        from safe_extract.paths import validate_member_name

        for name in NUL_NAMES:
            with self.assertRaises(UnsafeContentError):
                validate_member_name(name, 100)

    def test_pre_existing_parent_symlink_cannot_redirect_writes(self):
        # A symlink pre-created inside the staging directory cannot redirect
        # writes: the containment check follows real paths and refuses.
        outside = tempfile.mkdtemp(prefix="safe_extract_outside_")
        outside_sentinel = os.path.join(outside, "marker")
        with open(outside_sentinel, "wb") as handle:
            handle.write(b"safe")
        try:
            archive = self.target("evil.zip")
            make_zip(archive, [("linkdir/escaped.txt", b"pwned")])
            dest = self.target("dest")

            from safe_extract.tracker import Tracker
            import safe_extract.engine as engine

            class InjectingTracker(Tracker):
                def __init__(self, staging_dir, limits):
                    super().__init__(staging_dir, limits)
                    os.symlink(outside, os.path.join(staging_dir, "linkdir"))

            original = engine.Tracker
            engine.Tracker = InjectingTracker
            with self.assertRaises(UnsafeContentError):
                try:
                    safe_extract(archive, dest)
                finally:
                    engine.Tracker = original
            self.assertFalse(os.path.exists(dest))
            self.assertFalse(os.path.exists(os.path.join(outside, "escaped.txt")))
            with open(outside_sentinel, "rb") as handle:
                self.assertEqual(handle.read(), b"safe")
        finally:
            import shutil

            shutil.rmtree(outside, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
