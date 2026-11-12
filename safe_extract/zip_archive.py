"""Streaming ZIP reader built on :mod:`zipfile`."""

import stat
import zipfile
import zlib

from .errors import ArchiveCorruptError, UnsafeContentError
from .paths import validate_member_name


def consume_zip(fileobj, tracker, limits):
    """Validate and extract every member of an open ZIP file."""
    try:
        archive = zipfile.ZipFile(fileobj)
        infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, EOFError, zlib.error) as exc:
        raise ArchiveCorruptError("malformed ZIP archive: {}".format(exc))

    try:
        for info in infos:
            name = info.filename
            components = validate_member_name(name, limits.max_path_depth)
            if not components:
                # Archive root entry such as "." or "/".
                continue
            tracker.register_member(components)

            if info.flag_bits & 0x1:
                raise UnsafeContentError(
                    "encrypted ZIP entries are not supported", member=name
                )

            unix_mode = info.external_attr >> 16
            if unix_mode:
                mode = stat.S_IFMT(unix_mode)
                if mode == 0:
                    # Permission bits without any file-type bits: assume a
                    # regular file (typical of archives written by zipfile
                    # or produced on non-Unix systems).
                    pass
                elif mode not in (stat.S_IFREG, stat.S_IFDIR):
                    raise UnsafeContentError(
                        "ZIP member is neither a regular file nor a "
                        "directory (unix mode {:#o})".format(unix_mode),
                        member=name,
                    )

            is_dir = info.is_dir()
            try:
                if is_dir:
                    tracker.make_directory(components, name)
                    continue

                with archive.open(info, "r") as stream:
                    tracker.write_file(components, name, stream)
            except (zipfile.BadZipFile, EOFError, zlib.error) as exc:
                raise ArchiveCorruptError(
                    "corrupt ZIP member data: {}".format(exc), member=name
                )
    finally:
        archive.close()
