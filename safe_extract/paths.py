"""Member-name validation and path containment helpers.

The validation is deliberately platform independent: archives produced on
Windows must be rejected on Linux as well, so Windows-specific spellings
(drive letters, UNC paths, backslashes) are always refused.
"""

import os
import re

from .errors import UnsafeContentError, ResourceLimitError

# Matches "C:" at the start of a name, including drive-relative ("C:foo")
# and drive-absolute ("C:/foo") spellings.
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def validate_member_name(name, max_path_depth):
    """Validate an archive member name and return its normalized components.

    Returns a tuple of path components with ``""`` and ``"."`` entries
    removed. An empty tuple means the entry represents the archive root
    (e.g. ``"."`` or ``"/"``) and can be skipped by the caller.

    Raises :class:`UnsafeContentError` for unsafe names and
    :class:`ResourceLimitError` when the depth limit is exceeded.
    """
    if not isinstance(name, str):
        raise UnsafeContentError(
            "member name is not a string: {!r}".format(name), member=name
        )
    if name == "":
        raise UnsafeContentError("empty member name", member=name)
    if "\x00" in name:
        raise UnsafeContentError("member name contains a NUL byte", member=name)
    if "\\" in name:
        raise UnsafeContentError(
            "backslashes are not allowed in member names", member=name
        )
    if _WINDOWS_DRIVE_RE.match(name):
        raise UnsafeContentError(
            "Windows drive-letter paths are not allowed", member=name
        )
    if name.startswith("/"):
        # Also covers UNC-style "//server/share" spellings.
        raise UnsafeContentError(
            "absolute paths are not allowed in member names", member=name
        )

    components = []
    for part in name.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise UnsafeContentError(
                "parent-directory ('..') references are not allowed", member=name
            )
        components.append(part)

    if len(components) > max_path_depth:
        raise ResourceLimitError(
            "member path depth {} exceeds limit {}".format(
                len(components), max_path_depth
            ),
            member=name,
        )
    return tuple(components)


def is_within(root_real, candidate_real):
    """Return True when ``candidate_real`` is inside ``root_real``.

    Both arguments must already be fully resolved (``os.path.realpath``).
    """
    try:
        return os.path.commonpath([root_real, candidate_real]) == root_real
    except ValueError:
        # Different drives on Windows, etc.
        return False
