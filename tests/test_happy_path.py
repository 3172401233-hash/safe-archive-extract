import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safe_extract import (  # noqa: E402
    FORMAT_TAR,
    FORMAT_TAR_GZ,
    FORMAT_ZIP,
    ExtractionLimits,
    detect_format,
    safe_extract,
)
from tests._helpers import (  # noqa: E402
    dir_info,
    file_info,
    make_tar,
    make_zip,
    read_tree,
)


class HappyPathTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="safe_extract_test_")

    def target(self, name):
        return os.path.join(self.workdir, name)

    def test_extracts_zip_with_nested_dirs(self):
        archive = self.target("a.zip")
        make_zip(
            archive,
            [
                ("root/", None),
                ("root/a.txt", b"alpha"),
                ("root/nested/b.txt", b"beta"),
            ],
        )
        result = safe_extract(archive, self.target("out"))
        self.assertEqual(result.files, 2)
        self.assertEqual(result.total_bytes, 9)
        self.assertEqual(
            read_tree(result.target),
            {
                os.path.join("root", "a.txt"): b"alpha",
                os.path.join("root", "nested", "b.txt"): b"beta",
            },
        )

    def test_extracts_tar_and_tar_gz(self):
        payload = b"x" * 2048
        for mode, suffix in (("w", ".tar"), ("w:gz", ".tar.gz")):
            archive = self.target("a" + suffix)
            make_tar(
                archive,
                [
                    (dir_info("d"), None),
                    (file_info("d/f.bin", payload), payload),
                ],
                mode=mode,
            )
            result = safe_extract(archive, self.target("out" + suffix))
            self.assertEqual(
                read_tree(result.target),
                {os.path.join("d", "f.bin"): payload},
            )
            self.assertEqual(result.total_bytes, 2048)

    def test_accepts_seekable_file_object(self):
        archive = self.target("a.zip")
        make_zip(archive, [("f", b"data")])
        with open(archive, "rb") as handle:
            result = safe_extract(handle, self.target("out"))
        self.assertEqual(read_tree(result.target), {"f": b"data"})

    def test_detect_format(self):
        zip_path = self.target("a.zip")
        tar_path = self.target("a.tar")
        targz_path = self.target("a.tar.gz")
        make_zip(zip_path, [("f", b"")])
        make_tar(tar_path, [(file_info("f", b""), b"")])
        make_tar(targz_path, [(file_info("f", b""), b"")], mode="w:gz")
        self.assertEqual(detect_format(path=zip_path), FORMAT_ZIP)
        self.assertEqual(detect_format(path=tar_path), FORMAT_TAR)
        self.assertEqual(detect_format(path=targz_path), FORMAT_TAR_GZ)

        with open(targz_path, "rb") as handle:
            self.assertEqual(detect_format(handle), FORMAT_TAR_GZ)
            self.assertEqual(handle.tell(), 0)

    def test_explicit_format_skips_detection(self):
        archive = self.target("weird.bin")
        make_tar(
            archive,
            [(file_info("f", b"ok"), b"ok")],
            mode="w",
        )
        result = safe_extract(
            archive, self.target("out"), archive_format=FORMAT_TAR
        )
        self.assertEqual(read_tree(result.target), {"f": b"ok"})

    def test_dot_and_root_entries_are_ignored(self):
        archive = self.target("a.tar")
        make_tar(
            archive,
            [
                (dir_info("."), None),
                (file_info("f", b"z"), b"z"),
            ],
        )
        result = safe_extract(archive, self.target("out"))
        self.assertEqual(result.members, 1)

    def test_custom_limits_are_honored(self):
        archive = self.target("a.zip")
        make_zip(archive, [("f", b"12345")])
        result = safe_extract(
            archive,
            self.target("out"),
            limits=ExtractionLimits(
                max_members=1,
                max_single_file_size=5,
                max_total_size=5,
                max_path_depth=1,
            ),
        )
        self.assertEqual(result.total_bytes, 5)

    def test_invalid_explicit_format_raises_value_error(self):
        archive = self.target("a.zip")
        make_zip(archive, [("f", b"x")])
        with self.assertRaises(ValueError):
            safe_extract(
                archive, self.target("out"), archive_format="rar"
            )


if __name__ == "__main__":
    unittest.main()
