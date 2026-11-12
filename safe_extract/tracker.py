"""State tracker and streaming writer for an in-progress extraction.

The tracker enforces:

* member count limits;
* duplicate names and file/directory type conflicts;
* that every created path stays inside the staging directory even when a
  pre-existing parent component is a symbolic link;
* per-file and total size limits based on the bytes actually read.
"""

import os

from .errors import (
    ResourceLimitError,
    UnsafeContentError,
)
from .paths import is_within

# Small read unit so limit checks fire early. Note that tarfile's
# ExFileObject is a BufferedReader asking the underlying stream for 8 KiB
# at a time; the _Stream layer splits that into 512-byte TAR blocks, so a
# 1 KiB request is served by two block reads without over-reading.
_CHUNK_SIZE = 1024


class Tracker:
    def __init__(self, staging_dir, limits):
        self._staging_real = os.path.realpath(staging_dir)
        self._limits = limits
        # Every explicit member path, normalized as a component tuple.
        self._paths = set()
        # Parent directories created implicitly while writing files.
        self._implicit_dirs = set()
        self.members = 0
        self.files = 0
        self.directories = 0
        self.total_bytes = 0

    @property
    def staging_real(self):
        return self._staging_real

    def register_member(self, components):
        """Check the member count and reject duplicate/conflicting names."""
        if self.members >= self._limits.max_members:
            raise ResourceLimitError(
                "member count exceeds limit {}".format(self._limits.max_members),
                member="/".join(components),
            )
        if components in self._paths:
            raise UnsafeContentError(
                "duplicate member path in archive",
                member="/".join(components),
            )
        self._paths.add(components)
        self.members += 1

    def make_directory(self, components, member_name):
        self._ensure_parents(components, member_name)
        path = self._build_path(components)
        if components in self._implicit_dirs:
            self._implicit_dirs.discard(components)
            self.directories += 1
            return path
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            # Defensive: an unexpected object already occupies this name.
            raise UnsafeContentError(
                "path already exists and cannot be used as a directory",
                member=member_name,
                path=path,
            )
        self._check_containment(path, member_name)
        self.directories += 1
        return path

    def write_file(self, components, member_name, stream):
        """Stream ``stream`` to disk, enforcing size limits while reading."""
        self._ensure_parents(components, member_name)
        path = self._build_path(components)
        try:
            if os.path.lexists(path):
                raise UnsafeContentError(
                    "path already exists and cannot be used as a file",
                    member=member_name,
                    path=path,
                )
        except UnsafeContentError:
            raise
        except OSError as exc:
            raise UnsafeContentError(
                "path conflicts with another member type: {}".format(exc),
                member=member_name,
                path=path,
            )
        written = 0
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            raise UnsafeContentError(
                "path conflicts with another member type: {}".format(exc),
                member=member_name,
                path=path,
            )
        try:
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > self._limits.max_single_file_size:
                    raise ResourceLimitError(
                        "single file size {} exceeds limit {}".format(
                            written, self._limits.max_single_file_size
                        ),
                        member=member_name,
                        path=path,
                    )
                if self.total_bytes + len(chunk) > self._limits.max_total_size:
                    raise ResourceLimitError(
                        "total extraction size exceeds limit {}".format(
                            self._limits.max_total_size
                        ),
                        member=member_name,
                        path=path,
                    )
                os.write(fd, chunk)
                self.total_bytes += len(chunk)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        else:
            os.close(fd)
        self._check_containment(path, member_name)
        self.files += 1
        return path, written

    def _ensure_parents(self, components, member_name):
        current = ()
        for part in components[:-1]:
            current = current + (part,)
            path = self._build_path(current)
            if current in self._implicit_dirs:
                continue
            if current in self._paths:
                # Explicit member with this name already exists; it must be a
                # directory for the child path to be valid.
                if not os.path.isdir(path):
                    raise UnsafeContentError(
                        "member path is used both as a file and as a "
                        "directory",
                        member=member_name,
                        path=path,
                    )
                continue
            try:
                os.makedirs(path, mode=0o700, exist_ok=True)
            except OSError as exc:
                raise UnsafeContentError(
                    "path conflicts with another member type: {}".format(exc),
                    member=member_name,
                    path=path,
                )
            # makedirs() may have been redirected by a pre-existing symlink;
            # verify the real location is still inside the staging dir.
            self._check_containment(path, member_name)
            self._implicit_dirs.add(current)
            self.directories += 1

    def _build_path(self, components):
        return os.path.join(self._staging_real, *components)

    def _check_containment(self, path, member_name):
        real = os.path.realpath(path)
        if not is_within(self._staging_real, real):
            raise UnsafeContentError(
                "resolved path escapes the extraction directory",
                member=member_name,
                path=path,
            )
