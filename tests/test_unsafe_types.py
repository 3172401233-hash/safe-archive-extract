import os
import stat
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safe_extract import UnsafeContentError, safe_extract  # noqa: E402
from tests._helpers import (  # noqa: E402
    file_info,
    make_tar,
    make_zip,
    special_info,
    zip_info_with_mode,
)


class UnsafeTypesTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="safe_extract_test_")

    def target(self, name):
        return os.path.join(self.workdir, name)

    def test_tar_rejects_symlink_hardlink_device_and_fifo(self):
        cases = [
            (special_info("lnk", tarfile.SYMTYPE, linkname="f"), "symlink"),
            (special_info("hlk", tarfile.LNKTYPE, linkname="f"), "hardlink"),
            (
                special_info("chr", tarfile.CHRTYPE, mode=0o600 | stat.S_IFCHR),
                "char device",
            ),
            (
                special_info("blk", tarfile.BLKTYPE, mode=0o600 | stat.S_IFBLK),
                "block device",
            ),
            (
                special_info("fifo", tarfile.FIFOTYPE, mode=0o600 | stat.S_IFIFO),
                "fifo",
            ),
        ]
        for index, (info, label) in enumerate(cases):
            archive = self.target("bad{}.tar".format(index))
            make_tar(
                archive,
                [
                    (file_info("f", b"ok"), b"ok"),
                    (info, None),
                ],
            )
            with self.assertRaises(UnsafeContentError) as caught:
                safe_extract(archive, self.target("out{}".format(index)))
            self.assertIn(label.replace(" ", ""), str(caught.exception).replace(" ", ""))
            self.assertFalse(
                os.path.exists(self.target("out{}".format(index)))
            )

    def test_zip_rejects_symlink_and_fifo_entries(self):
        cases = [
            (zip_info_with_mode("lnk", stat.S_IFLNK | 0o777), "symlink"),
            (zip_info_with_mode("fifo", stat.S_IFIFO | 0o644), "fifo"),
        ]
        for index, (info, _label) in enumerate(cases):
            archive = self.target("bad{}.zip".format(index))
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr(info, b"target")
            with self.assertRaises(UnsafeContentError):
                safe_extract(archive, self.target("out{}".format(index)))

    def test_duplicate_member_name_is_rejected(self):
        for fmt in ("zip", "tar"):
            archive = self.target("dup." + fmt)
            if fmt == "zip":
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    make_zip(archive, [("f", b"a"), ("f", b"b")])
            else:
                make_tar(
                    archive,
                    [
                        (file_info("f", b"a"), b"a"),
                        (file_info("f", b"b"), b"b"),
                    ],
                )
            with self.assertRaises(UnsafeContentError) as caught:
                safe_extract(archive, self.target("out_" + fmt))
            self.assertEqual(caught.exception.member, "f")

    def test_file_directory_type_conflict_is_rejected(self):
        for fmt in ("zip", "tar"):
            archive = self.target("conflict." + fmt)
            if fmt == "zip":
                make_zip(
                    archive,
                    [
                        ("name", b"a"),
                        ("name/child", b"b"),
                    ],
                )
            else:
                make_tar(
                    archive,
                    [
                        (file_info("name", b"a"), b"a"),
                        (file_info("name/child", b"b"), b"b"),
                    ],
                )
            with self.assertRaises(UnsafeContentError):
                safe_extract(archive, self.target("out_" + fmt))

    def test_directory_then_file_same_path_is_rejected(self):
        archive = self.target("swap.zip")
        make_zip(archive, [("name/", b""), ("name", b"x")])
        with self.assertRaises(UnsafeContentError):
            safe_extract(archive, self.target("out"))

    def test_file_used_as_parent_directory_is_rejected(self):
        for fmt in ("zip", "tar"):
            archive = self.target("parent." + fmt)
            if fmt == "zip":
                make_zip(
                    archive,
                    [("name", b"a"), ("name/child", b"b")],
                )
            else:
                make_tar(
                    archive,
                    [
                        (file_info("name", b"a"), b"a"),
                        (file_info("name/child", b"b"), b"b"),
                    ],
                )
            with self.assertRaises(UnsafeContentError) as caught:
                safe_extract(archive, self.target("pout_" + fmt))
            self.assertIsNotNone(caught.exception.path)


if __name__ == "__main__":
    unittest.main()
