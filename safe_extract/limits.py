"""Configurable extraction limits."""

from dataclasses import dataclass


@dataclass
class ExtractionLimits:
    """Upper bounds enforced while an archive is being read.

    Size limits are compared against the bytes actually read from the data
    streams, never against the sizes declared by archive headers.
    """

    #: Maximum number of accepted members (files and directories).
    max_members: int = 100_000
    #: Maximum uncompressed size of a single file, in bytes.
    max_single_file_size: int = 100 * 1024 * 1024
    #: Maximum total uncompressed size of all files combined, in bytes.
    max_total_size: int = 1024 * 1024 * 1024
    #: Maximum number of path components allowed for a member path.
    max_path_depth: int = 100

    def __post_init__(self):
        for name in (
            "max_members",
            "max_single_file_size",
            "max_total_size",
            "max_path_depth",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(
                    "{} must be a non-negative int, got {!r}".format(name, value)
                )
