"""Core PDF compression logic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable, Iterable


class CompressionError(RuntimeError):
    """Raised when compression fails."""


class GhostscriptMissingError(CompressionError):
    """Raised when no Ghostscript executable can be found."""


class PdfRasterDependencyError(CompressionError):
    """Raised when Poppler, pdf2image, or Pillow are not available."""


class PdfImageRecompressionError(CompressionError):
    """Raised when embedded image recompression cannot run."""


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
class RasterSetting:
    dpi: int
    quality: int
    grayscale: bool = False

    @property
    def label(self) -> str:
        if self.grayscale:
            return "Page-by-page compression with reduced color"
        return "Page-by-page compression"

    @property
    def filename_suffix(self) -> str:
        color_mode = "gray" if self.grayscale else "color"
        return f"{color_mode}-{self.dpi}dpi-q{self.quality}"


@dataclass(frozen=True)
class Jpeg2000Setting:
    compression_ratio: int

    @property
    def label(self) -> str:
        return "Image compression that keeps text selectable"

    @property
    def filename_suffix(self) -> str:
        return f"jpx-r{self.compression_ratio}"


@dataclass(frozen=True)
class ImageRecompressionStats:
    images_seen: int
    images_recompressed: int


@dataclass(frozen=True)
class CompressionResult:
    input_path: Path
    output_path: Path
    profile: CompressionProfile
    original_size: int
    compressed_size: int
    method: str
    worker_count: int = 1

    @property
    def bytes_saved(self) -> int:
        return self.original_size - self.compressed_size

    @property
    def savings_percent(self) -> float:
        if self.original_size == 0:
            return 0.0
        return (self.bytes_saved / self.original_size) * 100


ProgressCallback = Callable[[int, str], None]
CountProgressCallback = Callable[[int, int], None]
DEFAULT_WORKER_COUNT = 3


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


STANDARD_MAX_RASTER_SETTINGS: tuple[RasterSetting, ...] = (
    RasterSetting(110, 48),
    RasterSetting(90, 40),
    RasterSetting(72, 34),
)


STANDARD_JPEG2000_SETTINGS: dict[str, tuple[Jpeg2000Setting, ...]] = {
    "max": (Jpeg2000Setting(18),),
    "screen": (Jpeg2000Setting(16),),
    "ebook": (Jpeg2000Setting(12),),
    "printer": (Jpeg2000Setting(8),),
}


TARGET_JPEG2000_RATIOS: tuple[int, ...] = (10, 14, 18, 24, 32, 45, 60)


TARGET_RASTER_SETTINGS: tuple[RasterSetting, ...] = (
    RasterSetting(110, 48),
    RasterSetting(96, 44),
    RasterSetting(90, 40),
    RasterSetting(84, 38),
    RasterSetting(78, 36),
    RasterSetting(72, 34),
    RasterSetting(68, 32),
    RasterSetting(64, 30),
    RasterSetting(60, 28),
    RasterSetting(56, 26),
    RasterSetting(52, 24),
    RasterSetting(48, 22),
    RasterSetting(44, 20),
    RasterSetting(40, 18),
    RasterSetting(36, 16),
    RasterSetting(32, 14),
    RasterSetting(28, 12),
    RasterSetting(24, 10),
    RasterSetting(72, 32, grayscale=True),
    RasterSetting(60, 26, grayscale=True),
    RasterSetting(48, 20, grayscale=True),
    RasterSetting(40, 16, grayscale=True),
    RasterSetting(32, 12, grayscale=True),
    RasterSetting(24, 9, grayscale=True),
    RasterSetting(18, 7, grayscale=True),
)


def find_ghostscript() -> str | None:
    """Return the first available Ghostscript executable."""

    return shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")


def find_pdftoppm() -> str | None:
    """Return the Poppler pdftoppm executable if it is available."""

    return shutil.which("pdftoppm")


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
    password: str | None = None,
) -> list[str]:
    """Build the Ghostscript command without executing it."""

    profile = get_profile(profile_name)
    executable = ghostscript_path or find_ghostscript()
    if executable is None:
        raise GhostscriptMissingError(_missing_ghostscript_message())

    command = [
        executable,
        *BASE_ARGS,
        *profile.args,
    ]
    if password:
        command.append(f"-sPDFPassword={password}")
    command.extend([f"-sOutputFile={Path(output_path)}", str(Path(input_path))])
    return command


def compress_pdf(
    input_path: Path | str,
    output_path: Path | str | None = None,
    profile_name: str = "max",
    ghostscript_path: str | None = None,
    allow_larger: bool = False,
    target_size_bytes: int | None = None,
    progress_callback: ProgressCallback | None = None,
    password: str | None = None,
    worker_count: int | None = None,
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

    _notify_progress(progress_callback, 6, "Checking your PDF")
    page_count = _validate_pdf(source, password=password, context="Input PDF")
    resolved_worker_count = _resolve_worker_count(worker_count, page_count)
    _notify_progress(progress_callback, 8, f"Preparing {page_count} pages")
    with tempfile.TemporaryDirectory(prefix="pdf-compressor-candidates-", dir=destination.parent) as tmp:
        candidate_dir = Path(tmp)
        candidates = _create_candidates(
            source,
            candidate_dir,
            profile,
            ghostscript_path=ghostscript_path,
            progress_callback=progress_callback,
            target_size_bytes=target_size_bytes,
            original_size=original_size,
            page_count=page_count,
            password=password,
            worker_count=resolved_worker_count,
        )

        if not candidates:
            raise CompressionError("No compression candidate was created.")

        best = _select_best_candidate(candidates, target_size_bytes, original_size=original_size)
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

        _notify_progress(progress_callback, 92, "Saving your compressed PDF")
        best.path.replace(destination)

    _notify_progress(progress_callback, 96, "Checking the compressed file")
    _validate_pdf(destination, context="Compressed output")
    _notify_progress(progress_callback, 98, "Compression complete")
    return CompressionResult(
        input_path=source,
        output_path=destination,
        profile=profile,
        original_size=original_size,
        compressed_size=destination.stat().st_size,
        method=best.label,
        worker_count=resolved_worker_count,
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
    target_size_bytes: int | None = None,
    original_size: int | None = None,
    page_count: int = 0,
    password: str | None = None,
    worker_count: int = 1,
) -> list[CompressionCandidate]:
    candidates: list[CompressionCandidate] = []
    jpeg2000_settings = _jpeg2000_settings_for_profile(profile.name, target_size_bytes, original_size)

    if profile.name == "max":
        profile_names = ("max", "screen", "ebook")
        raster_settings = _raster_settings_for_target(target_size_bytes, STANDARD_MAX_RASTER_SETTINGS)
    else:
        profile_names = (profile.name,)
        raster_settings = _raster_settings_for_target(target_size_bytes, ())

    total_attempts = len(jpeg2000_settings) + len(profile_names) + len(raster_settings)
    completed_attempts = 0
    stop_jpeg2000_attempts = False

    for index, setting in enumerate(jpeg2000_settings, start=1):
        label = setting.label
        output = candidate_dir / f"pikepdf-{index}-{setting.filename_suffix}.pdf"

        def image_progress(completed: int, total: int) -> None:
            page_progress = _attempt_item_progress(completed_attempts, total_attempts, completed, total)
            _notify_progress(progress_callback, page_progress, f"Compressing images: {completed} of {total}")

        try:
            stats = _run_pikepdf_jpeg2000_recompress(
                source,
                output,
                setting=setting,
                password=password,
                image_progress_callback=image_progress,
            )
        except PdfImageRecompressionError as exc:
            _delete_if_present(output)
            _notify_progress(
                progress_callback,
                _attempt_progress(completed_attempts + 1, total_attempts),
                "Moving to the next compression step",
            )
            stats = ImageRecompressionStats(images_seen=0, images_recompressed=0)

        if output.exists() and output.stat().st_size > 0:
            candidate_label = label
            if stats.images_recompressed == 0:
                candidate_label = "Light cleanup without changing quality"
                stop_jpeg2000_attempts = True
            candidates.append(CompressionCandidate(output, candidate_label))
            if _has_useful_candidate_under_target([candidates[-1]], target_size_bytes, original_size):
                _notify_progress(
                    progress_callback,
                    _attempt_progress(completed_attempts + 1, total_attempts),
                    "Target size reached after compressing images",
                )
                return candidates

        completed_attempts += 1
        if stop_jpeg2000_attempts:
            break

    for profile_name in profile_names:
        label = _optimization_candidate_label(profile_name)
        _notify_progress(
            progress_callback,
            _attempt_progress(completed_attempts, total_attempts),
            f"{label}",
        )
        output = candidate_dir / f"{profile_name}.pdf"
        try:
            _run_ghostscript_pdfwrite(source, output, profile_name, ghostscript_path=ghostscript_path, password=password)
        except GhostscriptMissingError:
            _delete_if_present(output)
            completed_attempts += 1
            _notify_progress(
                progress_callback,
                _attempt_progress(completed_attempts, total_attempts),
                "Moving to page-by-page compression",
            )
            break
        except CompressionError:
            _delete_if_present(output)
            completed_attempts += 1
            _notify_progress(
                progress_callback,
                _attempt_progress(completed_attempts, total_attempts),
                "Trying another compression step",
            )
            continue
        if output.exists() and output.stat().st_size > 0:
            candidates.append(CompressionCandidate(output, label))
        completed_attempts += 1
        _notify_progress(progress_callback, _attempt_progress(completed_attempts, total_attempts), "Checking file size")

    if _has_useful_candidate_under_target(candidates, target_size_bytes, original_size):
        return candidates

    for index, setting in enumerate(raster_settings, start=1):
        label = setting.label
        output = candidate_dir / f"raster-{index}-{setting.filename_suffix}.pdf"

        def page_progress(completed: int, total: int) -> None:
            raster_progress = _attempt_item_progress(completed_attempts, total_attempts, completed, total)
            _notify_progress(progress_callback, raster_progress, f"Compressing pages: {completed} of {total}")

        _run_raster_pdf(
            source,
            output,
            setting=setting,
            ghostscript_path=ghostscript_path,
            page_count=page_count,
            password=password,
            worker_count=worker_count,
            page_progress_callback=page_progress,
        )
        if output.exists() and output.stat().st_size > 0:
            candidate = CompressionCandidate(output, label)
            candidates.append(candidate)
            if _has_useful_candidate_under_target([candidate], target_size_bytes, original_size):
                _notify_progress(
                    progress_callback,
                    _attempt_progress(completed_attempts + 1, total_attempts),
                    f"Target size reached after compressing {page_count} pages",
                )
                return candidates
        completed_attempts += 1

    return candidates


def _raster_settings_for_target(
    target_size_bytes: int | None,
    default_settings: tuple[RasterSetting, ...],
) -> tuple[RasterSetting, ...]:
    if target_size_bytes is None:
        return default_settings

    settings = list(TARGET_RASTER_SETTINGS)
    for candidate in default_settings:
        if candidate not in settings:
            settings.append(candidate)
    return tuple(settings)


def _optimization_candidate_label(profile_name: str) -> str:
    labels = {
        "max": "Reducing file size as much as possible",
        "screen": "Making the PDF smaller for sharing",
        "ebook": "Balancing size and readability",
        "printer": "Keeping print quality while reducing size",
        "lossless": "Cleaning up the PDF without changing quality",
    }
    return labels.get(profile_name, "Reducing PDF size")


def _jpeg2000_settings_for_profile(
    profile_name: str,
    target_size_bytes: int | None,
    original_size: int | None = None,
) -> tuple[Jpeg2000Setting, ...]:
    if target_size_bytes is not None:
        return (Jpeg2000Setting(_jpeg2000_ratio_for_target(target_size_bytes, original_size)),)
    return STANDARD_JPEG2000_SETTINGS.get(profile_name, ())


def _jpeg2000_ratio_for_target(target_size_bytes: int, original_size: int | None) -> int:
    if not original_size or target_size_bytes <= 0:
        return TARGET_JPEG2000_RATIOS[0]

    requested_ratio = original_size / target_size_bytes
    if requested_ratio <= 2:
        desired_ratio = 10
    elif requested_ratio <= 4:
        desired_ratio = 14
    elif requested_ratio <= 6:
        desired_ratio = 18
    elif requested_ratio <= 10:
        desired_ratio = 24
    elif requested_ratio <= 16:
        desired_ratio = 32
    elif requested_ratio <= 25:
        desired_ratio = 45
    else:
        desired_ratio = 60

    for ratio in TARGET_JPEG2000_RATIOS:
        if ratio >= desired_ratio:
            return ratio
    return TARGET_JPEG2000_RATIOS[-1]


def _select_best_candidate(
    candidates: list[CompressionCandidate],
    target_size_bytes: int | None,
    original_size: int | None = None,
) -> CompressionCandidate:
    if target_size_bytes is None:
        return min(candidates, key=lambda candidate: candidate.path.stat().st_size)

    under_target = [candidate for candidate in candidates if candidate.path.stat().st_size <= target_size_bytes]
    useful_under_target = [
        candidate for candidate in under_target if original_size is None or candidate.path.stat().st_size < original_size
    ]
    if useful_under_target:
        return max(useful_under_target, key=lambda candidate: candidate.path.stat().st_size)
    if under_target:
        return max(under_target, key=lambda candidate: candidate.path.stat().st_size)
    return min(candidates, key=lambda candidate: candidate.path.stat().st_size)


def _has_useful_candidate_under_target(
    candidates: list[CompressionCandidate],
    target_size_bytes: int | None,
    original_size: int | None,
) -> bool:
    if target_size_bytes is None:
        return False
    return any(
        candidate.path.stat().st_size <= target_size_bytes
        and (original_size is None or candidate.path.stat().st_size < original_size)
        for candidate in candidates
    )


def _resolve_worker_count(worker_count: int | None, page_count: int) -> int:
    if page_count <= 1:
        return 1
    if worker_count is not None:
        if worker_count <= 0:
            raise CompressionError("Worker count must be greater than zero.")
        return min(worker_count, page_count)

    cpu_count = os.cpu_count() or 1
    return min(DEFAULT_WORKER_COUNT, cpu_count, page_count)


def _attempt_progress(completed_attempts: int, total_attempts: int) -> int:
    if total_attempts <= 0:
        return 15
    return 15 + round((completed_attempts / total_attempts) * 70)


def _attempt_item_progress(
    completed_attempts: int,
    total_attempts: int,
    completed_items: int,
    total_items: int,
) -> int:
    if total_attempts <= 0:
        return 15
    item_fraction = 0.0 if total_items <= 0 else completed_items / total_items
    return 15 + round(((completed_attempts + item_fraction) / total_attempts) * 70)


def _notify_progress(callback: ProgressCallback | None, progress: int, message: str) -> None:
    if callback is None:
        return
    callback(max(0, min(progress, 99)), message)


def _run_ghostscript_pdfwrite(
    source: Path,
    output: Path,
    profile_name: str,
    ghostscript_path: str | None = None,
    password: str | None = None,
) -> None:
    command = build_ghostscript_command(source, output, profile_name, ghostscript_path=ghostscript_path, password=password)
    _run_command(command, output)


def _run_pikepdf_jpeg2000_recompress(
    source: Path,
    output: Path,
    setting: Jpeg2000Setting,
    password: str | None = None,
    image_progress_callback: CountProgressCallback | None = None,
) -> ImageRecompressionStats:
    pikepdf, PdfImage, Image, _features = _load_pikepdf_image_tools()
    images_seen = 0
    images_recompressed = 0

    try:
        pdf = pikepdf.open(source, password=password or "")
    except Exception as exc:
        raise PdfImageRecompressionError(f"pikepdf could not open the PDF.{_dependency_detail(exc)}") from exc

    with pdf:
        images = _unique_pdf_images(pdf)
        total_images = len(images)
        if image_progress_callback is not None:
            image_progress_callback(0, total_images)

        for image_object in images:
            images_seen += 1
            if _recompress_pdf_image_to_jpeg2000(
                image_object,
                pikepdf=pikepdf,
                PdfImage=PdfImage,
                Image=Image,
                setting=setting,
            ):
                images_recompressed += 1

            if image_progress_callback is not None:
                image_progress_callback(images_seen, total_images)

        try:
            pdf.save(
                output,
                min_version="1.5",
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                recompress_flate=True,
            )
        except Exception as exc:
            _delete_if_present(output)
            raise PdfImageRecompressionError(f"pikepdf could not save the recompressed PDF.{_dependency_detail(exc)}") from exc

    return ImageRecompressionStats(images_seen=images_seen, images_recompressed=images_recompressed)


def _unique_pdf_images(pdf: object) -> list[object]:
    images: list[object] = []
    seen: set[object] = set()

    for page in pdf.pages:
        for image_object in page.images.values():
            key: object
            try:
                key = tuple(image_object.objgen) if image_object.is_indirect else id(image_object)
            except Exception:
                key = id(image_object)
            if key in seen:
                continue
            seen.add(key)
            images.append(image_object)

    return images


def _recompress_pdf_image_to_jpeg2000(
    image_object: object,
    *,
    pikepdf: object,
    PdfImage: object,
    Image: object,
    setting: Jpeg2000Setting,
) -> bool:
    try:
        pdf_image = PdfImage(image_object)
        if pdf_image.image_mask:
            return False
        raw_size = len(image_object.read_raw_bytes())
        original_image = pdf_image.as_pil_image()
    except Exception:
        return False

    image = original_image
    try:
        if image.mode in {"RGBA", "LA"} or ("transparency" in image.info):
            return False
        if image.mode not in {"RGB", "L", "CMYK"}:
            image = image.convert("RGB")

        buffer = io.BytesIO()
        image.save(
            buffer,
            format="JPEG2000",
            quality_mode="rates",
            quality_layers=[setting.compression_ratio],
            irreversible=True,
        )
        encoded = buffer.getvalue()
        if not encoded or len(encoded) >= raw_size:
            return False

        image_object.write(encoded, filter=pikepdf.Name("/JPXDecode"), decode_parms=None)
        _set_jpeg2000_image_metadata(image_object, pikepdf=pikepdf, image=image)
        return True
    except Exception:
        return False
    finally:
        if image is not original_image:
            image.close()
        original_image.close()


def _set_jpeg2000_image_metadata(image_object: object, *, pikepdf: object, image: object) -> None:
    color_space = {
        "L": "/DeviceGray",
        "CMYK": "/DeviceCMYK",
    }.get(image.mode, "/DeviceRGB")
    image_object[pikepdf.Name("/ColorSpace")] = pikepdf.Name(color_space)
    image_object[pikepdf.Name("/BitsPerComponent")] = 8
    image_object[pikepdf.Name("/Width")] = image.width
    image_object[pikepdf.Name("/Height")] = image.height
    for key in ("/Decode", "/DecodeParms"):
        try:
            del image_object[pikepdf.Name(key)]
        except (KeyError, ValueError):
            pass


def _run_raster_pdf(
    source: Path,
    output: Path,
    setting: RasterSetting,
    ghostscript_path: str | None = None,
    page_count: int = 0,
    password: str | None = None,
    worker_count: int = 1,
    page_progress_callback: CountProgressCallback | None = None,
) -> None:
    del ghostscript_path
    pdfium = _load_pdfium_renderer()

    with tempfile.TemporaryDirectory(prefix="pdf-compressor-pages-", dir=output.parent) as tmp:
        page_dir = Path(tmp)
        page_total = page_count or _validate_pdf(source, password=password, context="Input PDF")
        workers = _resolve_worker_count(worker_count, page_total)
        if page_progress_callback is not None:
            page_progress_callback(0, page_total)
        if pdfium is not None:
            images = _render_pdfium_pages(
                pdfium,
                source,
                page_dir,
                page_total=page_total,
                setting=setting,
                password=password,
                worker_count=workers,
                page_progress_callback=page_progress_callback,
            )
        else:
            convert_from_path, _pdfinfo_from_path = _load_pdf_raster_tools()
            images = _render_raster_pages(
                convert_from_path,
                source,
                page_dir,
                page_total=page_total,
                setting=setting,
                password=password,
                worker_count=workers,
                page_progress_callback=page_progress_callback,
            )
        if not images:
            raise CompressionError("Page-by-page compression did not render any pages.")
        _write_jpeg_pdf(images, output, dpi=setting.dpi)


def _render_pdfium_pages(
    pdfium: object,
    source: Path,
    page_dir: Path,
    *,
    page_total: int,
    setting: RasterSetting,
    password: str | None,
    worker_count: int,
    page_progress_callback: CountProgressCallback | None = None,
) -> list[Path]:
    if worker_count <= 1 or page_total <= 1:
        images = []
        for page_number in range(1, page_total + 1):
            images.append(_render_pdfium_page(pdfium, source, page_dir, page_number, setting, password))
            if page_progress_callback is not None:
                page_progress_callback(page_number, page_total)
        return images

    images_by_page: dict[int, Path] = {}
    completed_pages = 0
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_render_pdfium_page, pdfium, source, page_dir, page_number, setting, password): page_number
            for page_number in range(1, page_total + 1)
        }
        for future in as_completed(futures):
            page_number = futures[future]
            images_by_page[page_number] = future.result()
            completed_pages += 1
            if page_progress_callback is not None:
                page_progress_callback(completed_pages, page_total)

    return [images_by_page[page_number] for page_number in sorted(images_by_page)]


def _render_pdfium_page(
    pdfium: object,
    source: Path,
    page_dir: Path,
    page_number: int,
    setting: RasterSetting,
    password: str | None,
) -> Path:
    document = None
    page = None
    bitmap = None
    original_image = None
    image = None
    try:
        document = pdfium.PdfDocument(str(source), password=password or None)
        page = document[page_number - 1]
        bitmap = page.render(scale=setting.dpi / 72)
        original_image = bitmap.to_pil()
        image = original_image
        mode = "L" if setting.grayscale else "RGB"
        if image.mode != mode:
            image = image.convert(mode)
        image_path = page_dir / f"page-{page_number:05d}.jpg"
        image.save(image_path, "JPEG", quality=setting.quality, optimize=True)
        return image_path
    except Exception as exc:
        raise CompressionError(f"Could not render page {page_number} for compression.{_dependency_detail(exc)}") from exc
    finally:
        if image is not None and image is not original_image:
            image.close()
        if original_image is not None:
            original_image.close()
        for item in (bitmap, page, document):
            close = getattr(item, "close", None)
            if close is not None:
                close()


def _render_raster_pages(
    convert_from_path: Callable[..., list[object]],
    source: Path,
    page_dir: Path,
    *,
    page_total: int,
    setting: RasterSetting,
    password: str | None,
    worker_count: int,
    page_progress_callback: CountProgressCallback | None = None,
) -> list[Path]:
    if worker_count <= 1 or page_total <= 1:
        images = []
        for page_number in range(1, page_total + 1):
            images.append(_render_raster_page(convert_from_path, source, page_dir, page_number, setting, password))
            if page_progress_callback is not None:
                page_progress_callback(page_number, page_total)
        return images

    images_by_page: dict[int, Path] = {}
    completed_pages = 0
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _render_raster_page,
                convert_from_path,
                source,
                page_dir,
                page_number,
                setting,
                password,
            ): page_number
            for page_number in range(1, page_total + 1)
        }
        for future in as_completed(futures):
            page_number = futures[future]
            images_by_page[page_number] = future.result()
            completed_pages += 1
            if page_progress_callback is not None:
                page_progress_callback(completed_pages, page_total)

    return [images_by_page[page_number] for page_number in sorted(images_by_page)]


def _render_raster_page(
    convert_from_path: Callable[..., list[object]],
    source: Path,
    page_dir: Path,
    page_number: int,
    setting: RasterSetting,
    password: str | None,
) -> Path:
    rendered = convert_from_path(
        str(source),
        dpi=setting.dpi,
        first_page=page_number,
        last_page=page_number,
        thread_count=1,
        grayscale=setting.grayscale,
        userpw=password,
    )
    if len(rendered) != 1:
        raise CompressionError(f"Poppler did not render page {page_number}.")

    original_image = rendered[0]
    image = original_image
    try:
        mode = "L" if setting.grayscale else "RGB"
        if image.mode != mode:
            image = image.convert(mode)
        image_path = page_dir / f"page-{page_number:05d}.jpg"
        image.save(image_path, "JPEG", quality=setting.quality, optimize=True)
        return image_path
    finally:
        if image is not original_image:
            image.close()
        original_image.close()


def _validate_pdf(path: Path, password: str | None = None, context: str = "PDF") -> int:
    try:
        return _validate_pdf_with_pikepdf(path, password=password, context=context)
    except ImportError:
        return _validate_pdf_with_poppler(path, password=password, context=context)


def _validate_pdf_with_pikepdf(path: Path, password: str | None = None, context: str = "PDF") -> int:
    import pikepdf

    try:
        with pikepdf.open(path, password=password or "") as pdf:
            pages = len(pdf.pages)
    except Exception as exc:
        raise CompressionError(
            f"{context} could not be opened. It may be corrupted or password-protected. "
            "If it has a password, enter the correct password and try again."
            f"{_dependency_detail(exc)}"
        ) from exc

    if pages <= 0:
        raise CompressionError(f"{context} has no readable pages.")
    return pages


def _validate_pdf_with_poppler(path: Path, password: str | None = None, context: str = "PDF") -> int:
    _convert_from_path, pdfinfo_from_path = _load_pdf_raster_tools()
    try:
        info = pdfinfo_from_path(str(path), userpw=password)
    except Exception as exc:
        raise CompressionError(
            f"{context} could not be opened. It may be corrupted or password-protected. "
            "If it has a password, enter the correct password and try again."
            f"{_dependency_detail(exc)}"
        ) from exc

    try:
        pages = int(info.get("Pages", 0))
    except (TypeError, ValueError) as exc:
        raise CompressionError(f"{context} page count could not be read.") from exc
    if pages <= 0:
        raise CompressionError(f"{context} has no readable pages.")
    return pages


def _load_pdf_raster_tools() -> tuple[Callable[..., object], Callable[..., dict[str, object]]]:
    if find_pdftoppm() is None:
        raise PdfRasterDependencyError(
            "PDFium or Poppler is required for page-by-page compression, but neither is available.\n"
            "Install pypdfium2 or Poppler, then run this app again:\n"
            "  Python:  .venv/bin/python -m pip install pypdfium2\n"
            "  macOS:   brew install poppler\n"
            "  Ubuntu:  sudo apt install poppler-utils\n"
            "  Windows: choco install poppler"
        )

    try:
        from pdf2image import convert_from_path, pdfinfo_from_path
        from PIL import Image as _Image
    except ImportError as exc:
        raise PdfRasterDependencyError(
            "pdf2image and Pillow are required for raster compression.\n"
            "Install them in this project environment:\n"
            "  python3 -m venv .venv\n"
            "  .venv/bin/python -m pip install pdf2image pillow"
        ) from exc

    return convert_from_path, pdfinfo_from_path


def _load_pdfium_renderer() -> object | None:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    return pdfium


def _load_pikepdf_image_tools() -> tuple[object, object, object, object]:
    try:
        import pikepdf
        from pikepdf import PdfImage
        from PIL import Image, features
    except ImportError as exc:
        raise PdfImageRecompressionError(
            "pikepdf and Pillow are required for embedded JPEG2000 image recompression.\n"
            "Install them in this project environment:\n"
            "  .venv/bin/python -m pip install pikepdf pillow"
        ) from exc

    if not features.check("jpg_2000"):
        raise PdfImageRecompressionError(
            "Pillow is installed without JPEG2000 support, so pikepdf JPEG2000 recompression cannot run."
        )

    return pikepdf, PdfImage, Image, features


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
        width, height, components = _jpeg_info(image_data)
        page_width = width * 72 / dpi
        page_height = height * 72 / dpi
        color_space = "/DeviceGray" if components == 1 else "/DeviceRGB"
        image_id = add_object(
            b"<< /Type /XObject /Subtype /Image "
            + f"/Width {width} /Height {height} ".encode("ascii")
            + f"/ColorSpace {color_space} /BitsPerComponent 8 /Filter /DCTDecode ".encode("ascii")
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
    width, height, _components = _jpeg_info(data)
    return width, height


def _jpeg_info(data: bytes) -> tuple[int, int, int]:
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
            components = data[offset + 7]
            return width, height, components
        offset += segment_length

    raise CompressionError("Could not read rendered JPEG dimensions.")


def _clean_process_output(chunks: Iterable[str]) -> str:
    text = "\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())
    if not text:
        return ""
    return f"\n{text[-4000:]}"


def _dependency_detail(exc: Exception) -> str:
    detail = str(exc).strip()
    return f"\n{detail[-1000:]}" if detail else ""


def _short_error(exc: Exception) -> str:
    detail = str(exc).splitlines()[0].strip()
    return detail[:160] if detail else exc.__class__.__name__


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
