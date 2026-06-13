"""PDF compression tools powered by Ghostscript."""

from .core import (
    CompressionError,
    CompressionNotUsefulError,
    CompressionProfile,
    CompressionResult,
    GhostscriptMissingError,
    PROFILES,
    build_ghostscript_command,
    compress_pdf,
    find_ghostscript,
)

__all__ = [
    "CompressionError",
    "CompressionNotUsefulError",
    "CompressionProfile",
    "CompressionResult",
    "GhostscriptMissingError",
    "PROFILES",
    "build_ghostscript_command",
    "compress_pdf",
    "find_ghostscript",
]
