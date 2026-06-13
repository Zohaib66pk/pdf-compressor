"""Command-line interface for PDF Compressor."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .core import CompressionError, PROFILES, compress_pdf, format_bytes
from .server import run_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdf-compressor",
        description="Compress PDF files with a local Python interface powered by Ghostscript.",
    )
    parser.add_argument("input", nargs="?", help="PDF file to compress. Omit to open the local web UI.")
    parser.add_argument("-o", "--output", help="Output PDF path.")
    parser.add_argument(
        "-p",
        "--profile",
        default="max",
        choices=tuple(PROFILES),
        help="Compression profile. Default: max.",
    )
    parser.add_argument("--ghostscript", help="Path to a Ghostscript executable.")
    parser.add_argument("--server", action="store_true", help="Start the local web interface.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the web interface.")
    parser.add_argument("--port", type=int, default=8765, help="Port for the web interface.")
    parser.add_argument("--list-profiles", action="store_true", help="Show compression profiles and exit.")

    args = parser.parse_args(argv)

    if args.list_profiles:
        _print_profiles()
        return 0

    if args.server or not args.input:
        try:
            run_server(host=args.host, port=args.port)
            return 0
        except OSError as exc:
            print(f"Error: could not start server at {args.host}:{args.port}: {exc}", file=sys.stderr)
            return 1

    try:
        result = compress_pdf(
            Path(args.input),
            Path(args.output) if args.output else None,
            profile_name=args.profile,
            ghostscript_path=args.ghostscript,
        )
    except CompressionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Compressed: {result.output_path}")
    print(f"Profile:    {result.profile.label}")
    print(f"Method:     {result.method}")
    print(f"Original:   {format_bytes(result.original_size)}")
    print(f"Output:     {format_bytes(result.compressed_size)}")
    print(f"Savings:    {format_bytes(result.bytes_saved)} ({result.savings_percent:.1f}%)")
    return 0


def _print_profiles() -> None:
    for profile in PROFILES.values():
        print(f"{profile.name:8} {profile.label}")
        print(f"         {profile.description}")


if __name__ == "__main__":
    raise SystemExit(main())
