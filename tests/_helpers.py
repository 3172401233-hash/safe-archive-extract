"""Helpers that build benign and malicious archives inside temp dirs.

Everything is generated on the fly; tests never touch real user files.
"""

import io
import os
import stat
import tarfile
import zipfile


def make_zip(path, entries):
    """Write a ZIP. ``entries`` maps member name -> bytes or zipfile info."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            if isinstance(payload, zipfile.ZipInfo):
                archive.writestr(payload, b"")
            elif payload is None:
                archive.writestr(name, b"")
            else:
                archive.writestr(name, payload)
    return path


def make_tar(path, entries, mode="w"):
    """Write a TAR (or TAR.GZ when ``mode='w:gz'``).

    Each entry is a ``(TarInfo, data-bytes-or-None)`` tuple.
    """
    with tarfile.open(path, mode) as archive:
        for info, data in entries:
            if data is None:
                archive.addfile(info)
            else:
                archive.addfile(info, io.BytesIO(data))
    return path


def file_info(name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o600
    return info


def dir_info(name):
    if not name.endswith("/"):
        name = name + "/"
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o700
    return info


def special_info(name, entry_type, linkname=None, mode=0o600):
    info = tarfile.TarInfo(name)
    info.type = entry_type
    info.mode = mode
    if linkname is not None:
        info.linkname = linkname
    return info


def zip_info_with_mode(name, unix_mode):
    info = zipfile.ZipInfo(name)
    info.external_attr = (unix_mode & 0xFFFF) << 16
    return info


def corrupt_first_data_byte(path):
    """Flip one byte inside the first local file data of a ZIP."""
    with open(path, "r+b") as handle:
        with zipfile.ZipFile(path) as archive:
            info = archive.infolist()[0]
        # Local file header: 30 fixed bytes + filename + extra field.
        offset = 30 + len(info.filename.encode()) + len(info.extra)
        handle.seek(offset)
        byte = handle.read(1)
        handle.seek(offset)
        handle.write(bytes([byte[0] ^ 0xFF]))


def truncate_file(path, keep_bytes):
    with open(path, "r+b") as handle:
        handle.truncate(keep_bytes)


def read_tree(root):
    """Return ``{relative path: content-bytes}`` for files under root."""
    result = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root)
            with open(full, "rb") as handle:
                result[rel] = handle.read()
    return result


def write_raw_tar_member(
    path, name, size, typeflag=b"0", mode=0o644, data_blocks=0
):
    """Append a single raw 512-byte TAR header with forged metadata.

    Only the header is written (no data blocks), which lets tests craft a
    member whose *declared* size is huge without allocating that memory.
    """
    header = bytearray(512)

    def put(offset, text):
        raw = text.encode("ascii")
        header[offset:offset + len(raw)] = raw

    put(0, name[:100])
    put(100, "{:07o}\x00".format(mode))
    put(108, "0000000\x00")
    put(116, "0000000\x00")
    put(124, "{:011o}\x00".format(size))
    put(136, "0000000\x00")
    put(148, "0000000\x00")
    header[156:157] = typeflag
    put(257, "ustar\x0000")

    # The checksum field itself counts as eight spaces while summing.
    checksum = sum(header) - sum(header[148:156]) + 8 * ord(" ")
    header[148:156] = "{:06o}\x00 ".format(checksum).encode("ascii")
    with open(path, "ab") as handle:
        handle.write(bytes(header))
        for _ in range(data_blocks):
            handle.write(b"\0" * 512)


# Re-exported for test readability.
S_IFLNK = stat.S_IFLNK
