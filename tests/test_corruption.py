import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safe_extract import ArchiveCorruptError, safe_extract  # noqa: E402
from tests._helpers import (  # noqa: E402
    corrupt_first_data_byte,
    file_info,
    make_tar,
    make_zip,
    truncate_file,
)


class CorruptionTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="safe_extract_test_")

    def target(self, name):
        return os.path.join(self.workdir, name)

    def test_zip_crc_mismatch_is_corruption(self):
        archive = self.target("crc.zip")
        make_zip(archive, [("f", b"some real content here")])
        corrupt_first_data_byte(archive)
        with self.assertRaises(ArchiveCorruptError):
            safe_extract(archive, self.target("out"))
        self.assertFalse(os.path.exists(self.target("out")))

    def test_truncated_zip_is_corruption(self):
        archive = self.target("trunc.zip")
        make_zip(archive, [("f", b"x" * 5000)])
        size = os.path.getsize(archive)
        truncate_file(archive, size // 2)
        with self.assertRaises(ArchiveCorruptError):
            safe_extract(archive, self.target("out"))

    def test_random_bytes_are_corruption(self):
        archive = self.target("random.bin")
        with open(archive, "wb") as handle:
            handle.write(b"definitely not an archive" * 20)
        with self.assertRaises(ArchiveCorruptError):
            safe_extract(archive, self.target("out"))

    def test_explicit_format_mismatch_is_corruption(self):
        zip_archive = self.target("a.zip")
        make_zip(zip_archive, [("f", b"x")])
        for wrong_format in ("tar", "tar.gz"):
            with self.assertRaises(ArchiveCorruptError):
                safe_extract(
                    zip_archive,
                    self.target("zout_" + wrong_format.replace(".", "_")),
                    archive_format=wrong_format,
                )

        plain_tar = self.target("a.tar")
        make_tar(plain_tar, [(file_info("f", b"x"), b"x")])
        with self.assertRaises(ArchiveCorruptError):
            safe_extract(
                plain_tar,
                self.target("tout"),
                archive_format="tar.gz",
            )

    def test_truncated_tar_gz_is_corruption(self):
        archive = self.target("trunc.tar.gz")
        make_tar(
            archive,
            [(file_info("f", b"x" * 300), b"x" * 300)],
            mode="w:gz",
        )
        size = os.path.getsize(archive)
        truncate_file(archive, size // 2)
        with self.assertRaises(ArchiveCorruptError):
            safe_extract(archive, self.target("out"))

    def test_truncated_tar_stream_is_corruption(self):
        archive = self.target("trunc.tar")
        make_tar(
            archive,
            [(file_info("f", b"x" * 4096), b"x" * 4096)],
        )
        size = os.path.getsize(archive)
        # Cut inside the member data blocks: tarfile raises ReadError
        # ("unexpected end of data") instead of silently NUL-padding.
        truncate_file(archive, size // 4)
        with self.assertRaises(ArchiveCorruptError):
            safe_extract(archive, self.target("out"))
        self.assertFalse(os.path.exists(self.target("out")))

    def test_error_identifies_member(self):
        archive = self.target("crc.zip")
        make_zip(archive, [("named_member", b"payload payload payload")])
        corrupt_first_data_byte(archive)
        with self.assertRaises(ArchiveCorruptError) as caught:
            safe_extract(archive, self.target("out"))
        self.assertTrue(
            caught.exception.member == "named_member"
            or "named_member" in str(caught.exception)
        )


if __name__ == "__main__":
    unittest.main()
