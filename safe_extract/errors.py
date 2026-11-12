"""Exception hierarchy used by :mod:`safe_extract`.

All exceptions inherit from :class:`SafeExtractError` so callers can catch
them with a single ``except`` while still being able to distinguish the four
failure categories:

* :class:`UnsafeContentError`  -- dangerous member names or entry types
* :class:`ResourceLimitError`  -- configured member / size / depth limits
* :class:`ArchiveCorruptError` -- truncated, malformed or failing checksums
* :class:`TargetConflictError` -- destination exists / cannot be published
"""


class SafeExtractError(Exception):
    """Base class for every error raised by this package."""

    def __init__(self, message, *, member=None, path=None):
        super().__init__(message)
        self.message = message
        self.member = member
        self.path = path

    def __str__(self):
        details = []
        if self.member is not None:
            details.append("member={!r}".format(self.member))
        if self.path is not None:
            details.append("path={!r}".format(self.path))
        if details:
            return "{} ({})".format(self.message, ", ".join(details))
        return self.message


class UnsafeContentError(SafeExtractError):
    """An archive member escapes the destination or uses a forbidden type."""


class ResourceLimitError(SafeExtractError):
    """A configured limit (members, sizes, depth) was exceeded."""


class ArchiveCorruptError(SafeExtractError):
    """The archive is truncated, malformed, or fails an integrity check."""


class TargetConflictError(SafeExtractError):
    """The destination already exists or cannot be prepared/published."""


class LockError(TargetConflictError):
    """Another extraction holds the destination lock.

    It is a subclass of :class:`TargetConflictError` so callers that only
    care about the destination category keep working.
    """
