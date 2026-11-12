import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safe_extract import (  # noqa: E402
    ExtractionLimits,
    ResourceLimitError,
    safe_extract,
)
from tests._helpers import (  # noqa: E402
    file_info,
    make_tar,
    make_zip,
    write_raw_tar_member,
)


class LimitsTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="safe_extract_test_")

    def target(self, name):
        return os.path.join(self.workdir, name)

    def test_member_count_limit_zip_and_tar(self):
        zip_archive = self.target("many.zip")
        make_zip(zip_archive, [("f{}".format(i), b"x") for i in range(5)])
        with self.assertRaises(ResourceLimitError) as caught:
            safe_extract(
                zip_archive,
                self.target("zout"),
                limits=ExtractionLimits(max_members=3),
            )
        self.assertIn("member count", caught.exception.message)

        tar_archive = self.target("many.tar")
        make_tar(
            tar_archive,
            [(file_info("f{}".format(i), b"x"), b"x") for i in range(5)],
        )
        with self.assertRaises(ResourceLimitError):
            safe_extract(
                tar_archive,
                self.target("tout"),
                limits=ExtractionLimits(max_members=3),
            )

    def test_single_file_size_limit_counts_actual_bytes(self):
        archive = self.target("big.zip")
        make_zip(archive, [("f", b"x" * 100)])
        with self.assertRaises(ResourceLimitError) as caught:
            safe_extract(
                archive,
                self.target("out"),
                limits=ExtractionLimits(max_single_file_size=50),
            )
        self.assertEqual(caught.exception.member, "f")
        self.assertFalse(os.path.exists(self.target("out")))

    def test_total_size_limit_stops_mid_stream(self):
        archive = self.target("two.zip")
        make_zip(
            archive,
            [("a", b"x" * 60), ("b", b"y" * 60)],
        )
        with self.assertRaises(ResourceLimitError) as caught:
            safe_extract(
                archive,
                self.target("out"),
                limits=ExtractionLimits(
                    max_single_file_size=10_000, max_total_size=100
                ),
            )
        self.assertEqual(caught.exception.member, "b")
        # No staging directory or partial published result remains.
        leftovers = [
            name
            for name in os.listdir(self.workdir)
            if name.startswith(".__safe_extract_")
        ]
        self.assertEqual(leftovers, [])

    def test_declared_header_size_is_not_trusted(self):
        # A raw header claims 10 GiB while only a handful of real data
        # blocks follow: the total-size limit must trip based on actual
        # bytes read, without trusting or allocating the declared size.
        archive = self.target("forged.tar")
        write_raw_tar_member(
            archive, "huge", 10 * 1024 ** 3, data_blocks=200
        )
        with self.assertRaises(ResourceLimitError):
            safe_extract(
                archive,
                self.target("out"),
                limits=ExtractionLimits(max_total_size=1024),
            )
        self.assertFalse(os.path.exists(self.target("out")))

    def test_path_depth_limit(self):
        deep = "/".join("d{}".format(i) for i in range(6)) + "/f"
        archive = self.target("deep.zip")
        make_zip(archive, [(deep, b"x")])
        with self.assertRaises(ResourceLimitError) as caught:
            safe_extract(
                archive,
                self.target("out"),
                limits=ExtractionLimits(max_path_depth=3),
            )
        self.assertEqual(caught.exception.member, deep)

        tar_archive = self.target("deep.tar")
        make_tar(
            tar_archive,
            [(file_info(deep, b"x"), b"x")],
        )
        with self.assertRaises(ResourceLimitError):
            safe_extract(
                tar_archive,
                self.target("tar_out"),
                limits=ExtractionLimits(max_path_depth=3),
            )

    def test_invalid_limits_are_rejected_early(self):
        with self.assertRaises(ValueError):
            ExtractionLimits(max_members=-1)
        with self.assertRaises(ValueError):
            ExtractionLimits(max_total_size=1.5)


if __name__ == "__main__":
    unittest.main()
