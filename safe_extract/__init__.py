"""Safe extraction of untrusted ZIP / TAR / TAR.GZ archives.

Public entry point: :func:`safe_extract`.
"""

from .constants import FORMAT_ZIP, FORMAT_TAR, FORMAT_TAR_GZ
from .engine import safe_extract as safe_extract, detect_format
from .errors import (
    SafeExtractError,
    UnsafeContentError,
    ResourceLimitError,
    ArchiveCorruptError,
    TargetConflictError,
    LockError,
)
from .limits import ExtractionLimits
from .result import ExtractionResult

__all__ = [
    "safe_extract",
    "detect_format",
    "ExtractionLimits",
    "ExtractionResult",
    "SafeExtractError",
    "UnsafeContentError",
    "ResourceLimitError",
    "ArchiveCorruptError",
    "TargetConflictError",
    "LockError",
    "FORMAT_ZIP",
    "FORMAT_TAR",
    "FORMAT_TAR_GZ",
]

__version__ = "1.0.0"
