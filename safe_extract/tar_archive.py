"""Streaming TAR / TAR.GZ reader built on :mod:`tarfile`."""

import tarfile

from .errors import (
    ArchiveCorruptError,
    SafeExtractError,
    UnsafeContentError,
)
from .paths import validate_member_name

_ACCEPTED_TYPES = {
    tarfile.REGTYPE: "regular file",
    tarfile.AREGTYPE: "regular file",
    tarfile.DIRTYPE: "directory",
}

_TYPE_LABELS = {
    tarfile.SYMTYPE: "symlink",
    tarfile.LNKTYPE: "hardlink",
    tarfile.CHRTYPE: "char device",
    tarfile.BLKTYPE: "block device",
    tarfile.FIFOTYPE: "fifo",
    tarfile.CONTTYPE: "contiguous file",
}


def consume_tar(fileobj, tracker, limits, gzip_required=False):
    """Validate and extract every member of an open TAR (possibly gzip)."""
    mode = "r|gz" if gzip_required else "r|*"
    try:
        archive = tarfile.open(fileobj=fileobj, mode=mode)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ArchiveCorruptError("malformed TAR archive: {}".format(exc))

    try:
        for member in archive:
            name = member.name
            components = validate_member_name(name, limits.max_path_depth)
            if not components:
                continue
            tracker.register_member(components)

            entry_type = member.type
            if entry_type not in _ACCEPTED_TYPES:
                type_label = _TYPE_LABELS.get(
                    entry_type, "code {}".format(entry_type)
                )
                detail = "unsupported TAR entry type {!r}".format(type_label)
                if member.linkname:
                    detail += " linking to {!r}".format(member.linkname)
                raise UnsafeContentError(detail, member=name)

            try:
                if entry_type == tarfile.DIRTYPE:
                    tracker.make_directory(components, name)
                else:
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ArchiveCorruptError(
                            "TAR member has no readable data stream",
                            member=name,
                        )
                    try:
                        # ExFileObject is a BufferedReader that pulls 8 KiB
                        # from the underlying stream up front; reading the
                        # raw _FileInFile instead gives us exact-length reads
                        # without over-reading past truncated data.
                        tracker.write_file(
                            components, name, getattr(stream, "raw", stream)
                        )
                    finally:
                        stream.close()
            except SafeExtractError:
                # UnsafeContentError / ResourceLimitError / corruption
                # already carry the right category and member context.
                raise
            except (tarfile.TarError, OSError, EOFError) as exc:
                raise ArchiveCorruptError(
                    "corrupt TAR member data: {}".format(exc), member=name
                )
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ArchiveCorruptError("malformed TAR archive: {}".format(exc))
    finally:
        try:
            archive.close()
        except (tarfile.TarError, OSError, EOFError):
            pass
