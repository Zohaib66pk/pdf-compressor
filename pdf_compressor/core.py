"""Core PDF compression logic.

The heavy lifting is delegated to Ghostscript's ``pdfwrite`` device. That is
the practical route for strong PDF compression because the largest savings
usually come from image downsampling and stream re-encoding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable, Iterable


class CompressionError(RuntimeError):
    """Raised when compression fails."""


class GhostscriptMissingError(CompressionError):
    """Raised when no Ghostscript executable can be found."""


class CompressionNotUsefulError(CompressionError):
    """Raised when every compression attempt is larger than the input."""


class CompressionTargetError(CompressionError):
    """Raised when no compression attempt meets the requested output size."""


@dataclass(frozen=True)
class CompressionProfile:
    name: str
    label: str
    description: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class CompressionCandidate:
    path: Path
    label: str


@dataclass(frozen=True)
class CompressionResult:
    input_path: Path
    output_path: Path
    profile: CompressionProfile
    original_size: int
    compressed_size: int
    method: str

    @property
    def bytes_saved(self) -> int:
        return self.original_size - self.compressed_size

    @property
    def savings_percent(self) -> float:
        if self.original_size == 0:
            return 0.0
        return (self.bytes_saved / self.original_size) * 100


ProgressCallback = Callable[[int, str], None]


BASE_ARGS: tuple[str, ...] = (
    "-dNOPAUSE",
    "-dBATCH",
    "-dSAFER",
    "-sDEVICE=pdfwrite",
    "-dCompatibilityLevel=1.5",
    "-dCompressFonts=true",
    "-dSubsetFonts=true",
    "-dCompressPages=true",
    "-dUseFlateCompression=true",
    "-dDetectDuplicateImages=true",
)


PROFILES: dict[str, CompressionProfile] = {
    "max": CompressionProfile(
        name="max",
        label="Maximum possible compression",
        description="Smallest files. May flatten pages to low-resolution JPEG images.",
        args=(
            "-dPDFSETTINGS=/screen",
            "-dDownsampleColorImages=true",
            "-dColorImageResolution=72",
            "-dColorImageDownsampleType=/Bicubic",
            "-dAutoFilterColorImages=false",
            "-dColorImageFilter=/DCTEncode",
            "-dDownsampleGrayImages=true",
            "-dGrayImageResolution=72",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dAutoFilterGrayImages=false",
            "-dGrayImageFilter=/DCTEncode",
            "-dDownsampleMonoImages=true",
            "-dMonoImageResolution=150",
            "-dMonoImageDownsampleType=/Subsample",
            "-dJPEGQ=35",
            "-dConvertCMYKImagesToRGB=true",
            "-sColorConversionStrategy=RGB",
            "-dProcessColorModel=/DeviceRGB",
        ),
    ),
    "screen": CompressionProfile(
        name="screen",
        label="Screen",
        description="Very small files for viewing on screens.",
        args=(
            "-dPDFSETTINGS=/screen",
            "-dDownsampleColorImages=true",
            "-dColorImageResolution=96",
            "-dDownsampleGrayImages=true",
            "-dGrayImageResolution=96",
            "-dDownsampleMonoImages=true",
            "-dMonoImageResolution=200",
            "-dJPEGQ=55",
        ),
    ),
    "ebook": CompressionProfile(
        name="ebook",
        label="Ebook",
        description="Balanced compression for readable documents.",
        args=(
            "-dPDFSETTINGS=/ebook",
            "-dDownsampleColorImages=true",
            "-dColorImageResolution=150",
            "-dDownsampleGrayImages=true",
            "-dGrayImageResolution=150",
            "-dDownsampleMonoImages=true",
            "-dMonoImageResolution=300",
            "-dJPEGQ=72",
        ),
    ),
    "printer": CompressionProfile(
        name="printer",
        label="Printer",
        description="Moderate compression with print-friendly image quality.",
        args=(
            "-dPDFSETTINGS=/printer",
            "-dDownsampleColorImages=true",
            "-dColorImageResolution=300",
            "-dDownsampleGrayImages=true",
            "-dGrayImageResolution=300",
            "-dDownsampleMonoImages=true",
            "-dMonoImageResolution=600",
            "-dJPEGQ=85",
        ),
    ),
    "lossless": CompressionProfile(
        name="lossless",
        label="Lossless cleanup",
        description="Rewrites and compresses streams without intentional image quality loss.",
        args=(
            "-dPDFSETTINGS=/prepress",
            "-dAutoFilterColorImages=true",
            "-dAutoFilterGrayImages=true",
            "-dDownsampleColorImages=false",
            "-dDownsampleGrayImages=false",
            "-dDownsampleMonoImages=false",
            "-dJPEGQ=95",
        ),
    ),
}


def find_ghostscript() -> str | None:
    """Return the first available Ghostscript executable."""

    return shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")


def get_profile(profile_name: str) -> CompressionProfile:
    key = profile_name.lower().strip()
    try:
        return PROFILES[key]
    except KeyError as exc:
        valid = ", ".join(PROFILES)
        raise CompressionError(f"Unknown profile '{profile_name}'. Choose one of: {valid}.") from exc


def default_output_path(input_path: Path, profile_name: str) -> Path:
    return input_path.with_name(f"{input_path.stem}.{profile_name}.compressed.pdf")


def build_ghostscript_command(
    input_path: Path | str,
    output_path: Path | str,
    profile_name: str = "max",
    ghostscript_path: str | None = None,
) -> list[str]:
    """Build the Ghostscript command without executing it."""

    profile = get_profile(profile_name)
    executable = ghostscript_path or find_ghostscript()
    if executable is None:
        raise GhostscriptMissingError(_missing_ghostscript_message())

    return [
        executable,
        *BASE_ARGS,
        *profile.args,
        f"-sOutputFile={Path(output_path)}",
        str(Path(input_path)),
    ]


def compress_pdf(
    input_path: Path | str,
    output_path: Path | str | None = None,
    profile_name: str = "max",
    ghostscript_path: str | None = None,
    allow_larger: bool = False,
    target_size_bytes: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> CompressionResult:
    """Compress a PDF and return compression statistics."""

    source = Path(input_path).expanduser().resolve()
    if not source.exists():
        raise CompressionError(f"Input file does not exist: {source}")
    if not source.is_file():
        raise CompressionError(f"Input path is not a file: {source}")
    if source.suffix.lower() != ".pdf":
        raise CompressionError("Input file must be a PDF.")

    profile = get_profile(profile_name)
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else default_output_path(source, profile.name).resolve()
    )

    if destination == source:
        raise CompressionError("Output path must be different from the input PDF.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    original_size = source.stat().st_size

    if target_size_bytes is not None and target_size_bytes <= 0:
        raise CompressionError("Target output size must be greater than zero.")

    _notify_progress(progress_callback, 8, "Preparing PDF")
    with tempfile.TemporaryDirectory(prefix="pdf-compressor-candidates-", dir=destination.parent) as tmp:
        candidate_dir = Path(tmp)
        candidates = _create_candidates(
            source,
            candidate_dir,
            profile,
            ghostscript_path=ghostscript_path,
            progress_callback=progress_callback,
        )

        if not candidates:
            raise CompressionError("No compression candidate was created.")

        best = min(candidates, key=lambda candidate: candidate.path.stat().st_size)
        best_size = best.path.stat().st_size
        if target_size_bytes is not None and best_size > target_size_bytes:
            attempted = ", ".join(
                f"{candidate.label}: {format_bytes(candidate.path.stat().st_size)}" for candidate in candidates
            )
            raise CompressionTargetError(
                "Could not compress the PDF to the requested target size. "
                f"Target: {format_bytes(target_size_bytes)}. Smallest attempt: {format_bytes(best_size)}. "
                f"Attempts: {attempted}."
            )

        if best_size >= original_size and not allow_larger:
            attempted = ", ".join(
                f"{candidate.label}: {format_bytes(candidate.path.stat().st_size)}" for candidate in candidates
            )
            raise CompressionNotUsefulError(
                "No smaller PDF could be produced for this file. "
                f"Original: {format_bytes(original_size)}. Best attempt: {format_bytes(best_size)}. "
                f"Attempts: {attempted}."
            )

        _notify_progress(progress_callback, 92, "Saving compressed PDF")
        best.path.replace(destination)

    _notify_progress(progress_callback, 98, "Compression complete")
    return CompressionResult(
        input_path=source,
        output_path=destination,
        profile=profile,
        original_size=original_size,
        compressed_size=destination.stat().st_size,
        method=best.label,
    )


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    sign = "-" if size < 0 else ""
    value = abs(float(size))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{sign}{int(value)} {unit}"
            return f"{sign}{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def _create_candidates(
    source: Path,
    candidate_dir: Path,
    profile: CompressionProfile,
    ghostscript_path: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[CompressionCandidate]:
    candidates: list[CompressionCandidate] = []

    if profile.name == "max":
        profile_names = ("max", "screen", "ebook")
        raster_settings = (
            (110, 48),
            (90, 40),
            (72, 34),
        )
    else:
        profile_names = (profile.name,)
        raster_settings = ()

    total_attempts = len(profile_names) + len(raster_settings)
    completed_attempts = 0

    for profile_name in profile_names:
        label = f"Ghostscript {get_profile(profile_name).label}"
        _notify_progress(progress_callback, _attempt_progress(completed_attempts, total_attempts), f"Running {label}")
        output = candidate_dir / f"{profile_name}.pdf"
        _run_ghostscript_pdfwrite(source, output, profile_name, ghostscript_path=ghostscript_path)
        if output.exists() and output.stat().st_size > 0:
            candidates.append(CompressionCandidate(output, label))
        completed_attempts += 1
        _notify_progress(progress_callback, _attempt_progress(completed_attempts, total_attempts), f"Finished {label}")

    for index, (dpi, quality) in enumerate(raster_settings, start=1):
        label = f"Raster JPEG {dpi} DPI, quality {quality}"
        _notify_progress(progress_callback, _attempt_progress(completed_attempts, total_attempts), f"Running {label}")
        output = candidate_dir / f"raster-{index}-{dpi}dpi-q{quality}.pdf"
        _run_raster_pdf(source, output, dpi=dpi, quality=quality, ghostscript_path=ghostscript_path)
        if output.exists() and output.stat().st_size > 0:
            candidates.append(CompressionCandidate(output, label))
        completed_attempts += 1
        _notify_progress(progress_callback, _attempt_progress(completed_attempts, total_attempts), f"Finished {label}")

    return candidates


def _attempt_progress(completed_attempts: int, total_attempts: int) -> int:
    if total_attempts <= 0:
        return 15
    return 15 + round((completed_attempts / total_attempts) * 70)


def _notify_progress(callback: ProgressCallback | None, progress: int, message: str) -> None:
    if callback is None:
        return
    callback(max(0, min(progress, 99)), message)


def _run_ghostscript_pdfwrite(
    source: Path,
    output: Path,
    profile_name: str,
    ghostscript_path: str | None = None,
) -> None:
    command = build_ghostscript_command(source, output, profile_name, ghostscript_path=ghostscript_path)
    _run_command(command, output)


def _run_raster_pdf(
    source: Path,
    output: Path,
    dpi: int,
    quality: int,
    ghostscript_path: str | None = None,
) -> None:
    executable = ghostscript_path or find_ghostscript()
    if executable is None:
        raise GhostscriptMissingError(_missing_ghostscript_message())

    with tempfile.TemporaryDirectory(prefix="pdf-compressor-pages-", dir=output.parent) as tmp:
        page_dir = Path(tmp)
        page_pattern = page_dir / "page-%05d.jpg"
        command = [
            executable,
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            "-sDEVICE=jpeg",
            f"-r{dpi}",
            f"-dJPEGQ={quality}",
            "-dTextAlphaBits=4",
            "-dGraphicsAlphaBits=4",
            f"-sOutputFile={page_pattern}",
            str(source),
        ]
        _run_command(command, None)

        images = sorted(page_dir.glob("page-*.jpg"))
        if not images:
            raise CompressionError("Ghostscript did not render any pages for raster compression.")
        _write_jpeg_pdf(images, output, dpi=dpi)


def _run_command(command: list[str], output: Path | None) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        if output is not None:
            _delete_if_present(output)
        details = _clean_process_output((completed.stderr, completed.stdout))
        raise CompressionError(f"Ghostscript failed with exit code {completed.returncode}.{details}")

    if output is not None and (not output.exists() or output.stat().st_size == 0):
        _delete_if_present(output)
        raise CompressionError("Ghostscript finished but did not create a valid output PDF.")


def _write_jpeg_pdf(images: list[Path], output: Path, dpi: int) -> None:
    objects: list[bytes] = []

    def add_object(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    catalog_id = add_object(b"")
    pages_id = add_object(b"")
    page_ids: list[int] = []

    for index, image_path in enumerate(images, start=1):
        image_data = image_path.read_bytes()
        width, height = _jpeg_dimensions(image_data)
        page_width = width * 72 / dpi
        page_height = height * 72 / dpi
        image_id = add_object(
            b"<< /Type /XObject /Subtype /Image "
            + f"/Width {width} /Height {height} ".encode("ascii")
            + b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            + f"/Length {len(image_data)} >>\nstream\n".encode("ascii")
            + image_data
            + b"\nendstream"
        )
        content = f"q\n{page_width:.4f} 0 0 {page_height:.4f} 0 0 cm\n/Im{index} Do\nQ\n".encode("ascii")
        content_id = add_object(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"endstream"
        )
        page_id = add_object(
            b"<< /Type /Page "
            + f"/Parent {pages_id} 0 R ".encode("ascii")
            + f"/MediaBox [0 0 {page_width:.4f} {page_height:.4f}] ".encode("ascii")
            + f"/Resources << /XObject << /Im{index} {image_id} 0 R >> >> ".encode("ascii")
            + f"/Contents {content_id} 0 R >>".encode("ascii")
        )
        page_ids.append(page_id)

    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    with output.open("wb") as pdf:
        pdf.write(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for object_id, payload in enumerate(objects, start=1):
            offsets.append(pdf.tell())
            pdf.write(f"{object_id} 0 obj\n".encode("ascii"))
            pdf.write(payload)
            pdf.write(b"\nendobj\n")

        xref_start = pdf.tell()
        pdf.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        pdf.write(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            pdf.write(f"{offset:010d} 00000 n \n".encode("ascii"))
        pdf.write(
            b"trailer\n"
            + f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n".encode("ascii")
            + b"startxref\n"
            + f"{xref_start}\n".encode("ascii")
            + b"%%EOF\n"
        )


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        raise CompressionError("Rendered page is not a JPEG image.")

    offset = 2
    start_of_frame_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    standalone_markers = {0x01, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9}

    while offset < len(data):
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break

        marker = data[offset]
        offset += 1
        if marker in standalone_markers:
            continue
        if offset + 2 > len(data):
            break

        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            break
        if marker in start_of_frame_markers:
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height
        offset += segment_length

    raise CompressionError("Could not read rendered JPEG dimensions.")


def _clean_process_output(chunks: Iterable[str]) -> str:
    text = "\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())
    if not text:
        return ""
    return f"\n{text[-4000:]}"


def _delete_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _missing_ghostscript_message() -> str:
    return (
        "Ghostscript is required for PDF compression but was not found.\n"
        "Install it, then run this app again:\n"
        "  macOS:   brew install ghostscript\n"
        "  Ubuntu:  sudo apt install ghostscript\n"
        "  Fedora:  sudo dnf install ghostscript\n"
        "  Windows: winget install ArtifexSoftware.Ghostscript"
    )
