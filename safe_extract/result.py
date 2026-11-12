"""Result object returned after a successful extraction."""

from dataclasses import dataclass


@dataclass
class ExtractionResult:
    #: Absolute path of the published destination directory.
    target: str
    #: Number of directories created (including implicit parent dirs).
    directories: int
    #: Number of regular files written.
    files: int
    #: Number of accepted archive members (files and directories).
    members: int
    #: Total file bytes actually read and written.
    total_bytes: int
