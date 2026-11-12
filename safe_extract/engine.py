"""Orchestration: staging directory, validation, atomic publish."""

import contextlib
import os
import shutil
import tempfile

from .constants import FORMAT_TAR, FORMAT_TAR_GZ, FORMAT_ZIP
from .errors import (
    ArchiveCorruptError,
    TargetConflictError,
    UnsafeContentError,
)
from .limits import ExtractionLimits
from .lock import DestinationLock
from .paths import is_within
from .result import ExtractionResult
from .tar_archive import consume_tar
from .tracker import Tracker
from .zip_archive import consume_zip

_GZIP_MAGIC = b"\x1f\x8b"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def detect_format(fileobj=None, *, path=None):
    """Detect the archive format from magic bytes.

    Either a seekable binary file object or a filesystem ``path`` must be
    given. The stream position is restored before returning.
    """
    if fileobj is not None:
        current = fileobj.tell()
        header = fileobj.read(262)
        fileobj.seek(current)
    elif path is not None:
        with open(path, "rb") as handle:
            header = handle.read(262)
    else:
        raise TypeError("detect_format requires a fileobj or path argument")

    if header.startswith(_GZIP_MAGIC):
        return FORMAT_TAR_GZ
    if header[:4] in _ZIP_MAGICS:
        return FORMAT_ZIP
    # tar USTAR magic lives at offset 257; old-style tar has no magic but
    # tarfile still accepts it, so treat remaining files as plain tar and let
    # tarfile raise ArchiveCorruptError if it disagrees.
    return FORMAT_TAR


@contextlib.contextmanager
def _open_source(archive):
    if hasattr(archive, "read"):
        if not hasattr(archive, "seek"):
            raise TypeError("archive file objects must be seekable")
        yield archive
        return
    if not isinstance(archive, (str, bytes, os.PathLike)):
        raise TypeError(
            "archive must be a path or a seekable binary file object"
        )
    with open(archive, "rb") as handle:
        yield handle


def safe_extract(
    archive,
    destination,
    *,
    limits=None,
    archive_format=None,
    lock_timeout=0.0,
):
    """Extract ``archive`` into ``destination`` only after full validation.

    The archive is never unpacked directly into ``destination``. A private
    staging directory is created next to it, every member is validated and
    streamed into that staging directory, and only after the whole archive
    has been processed successfully is the staging directory renamed to
    ``destination`` in one atomic step.

    ``archive`` is a filesystem path or a seekable binary file object.
    ``destination`` must not exist yet. ``lock_timeout`` (seconds) controls
    how long to wait when another extraction owns the destination lock;
    ``0.0`` fails immediately.

    Returns an :class:`~safe_extract.result.ExtractionResult`.
    """
    if limits is None:
        limits = ExtractionLimits()
    elif not isinstance(limits, ExtractionLimits):
        raise TypeError("limits must be an ExtractionLimits instance")
    if archive_format is not None and archive_format not in (
        FORMAT_ZIP,
        FORMAT_TAR,
        FORMAT_TAR_GZ,
    ):
        raise ValueError(
            "unsupported archive format: {!r}".format(archive_format)
        )

    target = os.path.abspath(os.fspath(destination))
    parent = os.path.dirname(target)
    name = os.path.basename(target)
    if not name:
        raise TargetConflictError(
            "destination has no directory name", path=target
        )
    if not os.path.isdir(parent):
        raise TargetConflictError(
            "destination parent directory does not exist", path=parent
        )
    if os.path.lexists(target):
        raise TargetConflictError(
            "destination already exists", path=target
        )

    lock = DestinationLock(target, timeout=lock_timeout)
    lock.acquire()
    staging_dir = None
    try:
        # Re-check after acquiring the lock: another process may have
        # published a result between our first check and lock acquisition.
        if os.path.lexists(target):
            raise TargetConflictError(
                "destination already exists", path=target
            )

        parent_real = os.path.realpath(parent)
        staging_dir = tempfile.mkdtemp(
            prefix=".__safe_extract_{}_".format(name),
            dir=parent_real,
        )
        staging_real = os.path.realpath(staging_dir)
        if os.path.dirname(staging_real) != parent_real:
            raise TargetConflictError(
                "staging directory was redirected outside the destination "
                "parent",
                path=staging_dir,
            )

        tracker = Tracker(staging_real, limits)
        with _open_source(archive) as fileobj:
            detected = archive_format or detect_format(fileobj)
            if detected == FORMAT_ZIP:
                try:
                    consume_zip(fileobj, tracker, limits)
                except (OSError, EOFError) as exc:
                    raise ArchiveCorruptError(
                        "archive could not be processed: {}".format(exc),
                        path=target,
                    )
            elif detected in (FORMAT_TAR, FORMAT_TAR_GZ):
                try:
                    consume_tar(
                        fileobj,
                        tracker,
                        limits,
                        gzip_required=detected == FORMAT_TAR_GZ,
                    )
                except (OSError, EOFError) as exc:
                    raise ArchiveCorruptError(
                        "archive could not be processed: {}".format(exc),
                        path=target,
                    )
            else:
                raise ArchiveCorruptError(
                    "archive contents do not match a supported format",
                    path=target,
                )

        published = staging_real
        try:
            os.rename(staging_real, target)
        except OSError as exc:
            raise TargetConflictError(
                "could not publish destination: {}".format(exc),
                path=target,
            )
        if not is_within(parent_real, os.path.realpath(target)):
            # Extremely unlikely (rename is inside one directory) but keep
            # the invariant explicit and roll back if it ever happens.
            os.rename(target, published)
            raise UnsafeContentError(
                "published destination escapes its parent directory",
                path=target,
            )

        return ExtractionResult(
            target=os.path.abspath(target),
            members=tracker.members,
            files=tracker.files,
            directories=tracker.directories,
            total_bytes=tracker.total_bytes,
        )
    finally:
        if staging_dir is not None and os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        lock.release()
