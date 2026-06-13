from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pdf_compressor.core import (
    CompressionCandidate,
    ImageRecompressionStats,
    Jpeg2000Setting,
    CompressionNotUsefulError,
    CompressionTargetError,
    DEFAULT_WORKER_COUNT,
    GhostscriptMissingError,
    RasterSetting,
    _create_candidates,
    _jpeg2000_ratio_for_target,
    _run_pikepdf_jpeg2000_recompress,
    _run_raster_pdf,
    _validate_pdf,
    _write_jpeg_pdf,
    _resolve_worker_count,
    build_ghostscript_command,
    compress_pdf,
    default_output_path,
    format_bytes,
    get_profile,
)


class CoreTests(unittest.TestCase):
    def test_max_profile_contains_aggressive_image_settings(self):
        command = build_ghostscript_command(
            "input.pdf",
            "output.pdf",
            profile_name="max",
            ghostscript_path="/usr/bin/gs",
        )

        self.assertIn("-dPDFSETTINGS=/screen", command)
        self.assertIn("-dColorImageResolution=72", command)
        self.assertIn("-dGrayImageResolution=72", command)
        self.assertIn("-dJPEGQ=35", command)
        self.assertEqual(command[-2], "-sOutputFile=output.pdf")
        self.assertEqual(command[-1], "input.pdf")

    def test_ghostscript_command_accepts_pdf_password(self):
        command = build_ghostscript_command(
            "input.pdf",
            "output.pdf",
            profile_name="screen",
            ghostscript_path="/usr/bin/gs",
            password="secret",
        )

        self.assertIn("-sPDFPassword=secret", command)

    def test_unknown_profile_fails_clearly(self):
        with self.assertRaisesRegex(Exception, "Unknown profile"):
            get_profile("tiny")

    def test_default_output_path_uses_profile_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "report.pdf"
            self.assertEqual(
                default_output_path(source, "max"),
                Path(tmp) / "report.max.compressed.pdf",
            )

    def test_missing_ghostscript_is_reported(self):
        with patch("pdf_compressor.core.find_ghostscript", return_value=None):
            with self.assertRaises(GhostscriptMissingError):
                build_ghostscript_command("in.pdf", "out.pdf", ghostscript_path=None)

    def test_format_bytes_handles_negative_values(self):
        self.assertEqual(format_bytes(-2048), "-2.00 KB")

    def test_compress_pdf_rejects_larger_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            output = Path(tmp) / "output.pdf"
            larger = Path(tmp) / "larger.pdf"
            source.write_bytes(b"%PDF-1.4\nsmall")
            larger.write_bytes(b"%PDF-1.4\nthis candidate is larger than the source")

            with patch(
                "pdf_compressor.core._create_candidates",
                return_value=[CompressionCandidate(larger, "larger test candidate")],
            ):
                with patch("pdf_compressor.core._validate_pdf", return_value=1):
                    with self.assertRaises(CompressionNotUsefulError):
                        compress_pdf(source, output, profile_name="screen", ghostscript_path="/usr/bin/gs")

            self.assertFalse(output.exists())

    def test_compress_pdf_accepts_candidate_under_target_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            output = Path(tmp) / "output.pdf"
            candidate = Path(tmp) / "candidate.pdf"
            source.write_bytes(b"%PDF-1.4\n" + (b"x" * 100))
            candidate.write_bytes(b"%PDF-1.4\nsmall")

            with patch(
                "pdf_compressor.core._create_candidates",
                return_value=[CompressionCandidate(candidate, "small test candidate")],
            ):
                with patch("pdf_compressor.core._validate_pdf", return_value=1):
                    result = compress_pdf(
                        source,
                        output,
                        profile_name="screen",
                        ghostscript_path="/usr/bin/gs",
                        target_size_bytes=50,
                    )

            self.assertLessEqual(result.compressed_size, 50)
            self.assertTrue(output.exists())

    def test_compress_pdf_prefers_smaller_candidate_when_larger_candidate_is_under_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            output = Path(tmp) / "output.pdf"
            larger = Path(tmp) / "larger.pdf"
            smaller = Path(tmp) / "smaller.pdf"
            source.write_bytes(b"%PDF-1.4\n" + (b"x" * 100))
            larger.write_bytes(b"x" * 130)
            smaller.write_bytes(b"x" * 80)

            with patch(
                "pdf_compressor.core._create_candidates",
                return_value=[
                    CompressionCandidate(larger, "larger under target"),
                    CompressionCandidate(smaller, "smaller under target"),
                ],
            ):
                with patch("pdf_compressor.core._validate_pdf", return_value=1):
                    result = compress_pdf(
                        source,
                        output,
                        profile_name="screen",
                        ghostscript_path="/usr/bin/gs",
                        target_size_bytes=200,
                    )

            self.assertEqual(result.compressed_size, 80)
            self.assertEqual(result.method, "smaller under target")

    def test_compress_pdf_rejects_candidates_over_target_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            output = Path(tmp) / "output.pdf"
            candidate = Path(tmp) / "candidate.pdf"
            source.write_bytes(b"%PDF-1.4\n" + (b"x" * 100))
            candidate.write_bytes(b"%PDF-1.4\n" + (b"x" * 60))

            with patch(
                "pdf_compressor.core._create_candidates",
                return_value=[CompressionCandidate(candidate, "oversized test candidate")],
            ):
                with patch("pdf_compressor.core._validate_pdf", return_value=1):
                    with self.assertRaises(CompressionTargetError):
                        compress_pdf(
                            source,
                            output,
                            profile_name="screen",
                            ghostscript_path="/usr/bin/gs",
                            target_size_bytes=50,
                        )

            self.assertFalse(output.exists())

    def test_target_size_uses_more_aggressive_raster_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            output = Path(tmp) / "output.pdf"
            source.write_bytes(b"%PDF-1.4\n" + (b"x" * 12_000))
            raster_attempts = []

            def fake_pdfwrite(_source, pdf_output, _profile_name, ghostscript_path=None, password=None):
                pdf_output.write_bytes(b"x" * 7_000)

            def fake_raster(
                _source,
                pdf_output,
                *,
                setting,
                ghostscript_path=None,
                page_count=0,
                password=None,
                worker_count=1,
                page_progress_callback=None,
            ):
                dpi = setting.dpi
                quality = setting.quality
                grayscale = setting.grayscale
                raster_attempts.append((dpi, quality, grayscale))
                size = 4_500 if (dpi, quality, grayscale) == (64, 30, False) else 6_000
                pdf_output.write_bytes(b"x" * size)

            with patch("pdf_compressor.core._run_ghostscript_pdfwrite", side_effect=fake_pdfwrite):
                with patch("pdf_compressor.core._run_raster_pdf", side_effect=fake_raster):
                    with patch("pdf_compressor.core._validate_pdf", return_value=1):
                        result = compress_pdf(
                            source,
                            output,
                            profile_name="max",
                            ghostscript_path="/usr/bin/gs",
                            target_size_bytes=5_000,
                            worker_count=3,
                        )

            self.assertEqual(result.compressed_size, 4_500)
            self.assertEqual(result.worker_count, 1)
            self.assertEqual(result.method, "Page-by-page compression")
            self.assertIn((64, 30, False), raster_attempts)

    def test_jpeg2000_candidate_can_satisfy_target_before_raster(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            source.write_bytes(b"%PDF-1.4\n" + (b"x" * 1_000))
            candidate_dir = Path(tmp) / "candidates"
            candidate_dir.mkdir()

            def fake_jpeg2000(_source, pdf_output, **_kwargs):
                pdf_output.write_bytes(b"x" * 800)
                return ImageRecompressionStats(images_seen=2, images_recompressed=2)

            with patch("pdf_compressor.core._run_pikepdf_jpeg2000_recompress", side_effect=fake_jpeg2000):
                with patch("pdf_compressor.core._run_ghostscript_pdfwrite") as ghostscript:
                    with patch("pdf_compressor.core._run_raster_pdf") as raster:
                        candidates = _create_candidates(
                            source,
                            candidate_dir,
                            get_profile("max"),
                            target_size_bytes=900,
                            original_size=source.stat().st_size,
                            page_count=2,
                        )

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].label, "Image compression that keeps text selectable")
            ghostscript.assert_not_called()
            raster.assert_not_called()

    def test_target_jpeg2000_runs_one_image_pass_before_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            source.write_bytes(b"%PDF-1.4\n" + (b"x" * 10_000))
            candidate_dir = Path(tmp) / "candidates"
            candidate_dir.mkdir()
            progress_messages = []

            def fake_jpeg2000(_source, pdf_output, *, image_progress_callback=None, **_kwargs):
                if image_progress_callback:
                    image_progress_callback(0, 40)
                    image_progress_callback(1, 40)
                    image_progress_callback(40, 40)
                pdf_output.write_bytes(b"x" * 9_000)
                return ImageRecompressionStats(images_seen=40, images_recompressed=40)

            def fake_pdfwrite(_source, pdf_output, _profile_name, ghostscript_path=None, password=None):
                pdf_output.write_bytes(b"x" * 8_000)

            def fake_raster(_source, pdf_output, *, setting, **_kwargs):
                pdf_output.write_bytes(b"x" * 4_000)

            with patch("pdf_compressor.core._run_pikepdf_jpeg2000_recompress", side_effect=fake_jpeg2000) as jpeg2000:
                with patch("pdf_compressor.core._run_ghostscript_pdfwrite", side_effect=fake_pdfwrite):
                    with patch("pdf_compressor.core._run_raster_pdf", side_effect=fake_raster):
                        _create_candidates(
                            source,
                            candidate_dir,
                            get_profile("max"),
                            progress_callback=lambda _progress, message: progress_messages.append(message),
                            target_size_bytes=5_000,
                            original_size=source.stat().st_size,
                            page_count=2,
                        )

            self.assertEqual(jpeg2000.call_count, 1)
            image_zero_messages = [
                message for message in progress_messages if message == "Compressing images: 0 of 40"
            ]
            self.assertEqual(image_zero_messages, ["Compressing images: 0 of 40"])

    def test_jpeg2000_ratio_for_target_uses_single_target_quality(self):
        self.assertEqual(_jpeg2000_ratio_for_target(5_000, 10_000), 10)
        self.assertEqual(_jpeg2000_ratio_for_target(5_000, 30_000), 18)
        self.assertEqual(_jpeg2000_ratio_for_target(5_000, 130_000), 60)

    def test_pikepdf_jpeg2000_recompresses_embedded_image_without_rasterizing_page(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            page_image = Path(tmp) / "page.jpg"
            source = Path(tmp) / "source.pdf"
            output = Path(tmp) / "output.pdf"
            image = Image.new("RGB", (220, 160))
            for y in range(image.height):
                for x in range(image.width):
                    image.putpixel((x, y), ((x * 5) % 256, (y * 7) % 256, ((x + y) * 3) % 256))
            image.save(page_image, "JPEG", quality=96)
            image.close()
            _write_jpeg_pdf([page_image], source, dpi=72)

            stats = _run_pikepdf_jpeg2000_recompress(
                source,
                output,
                setting=Jpeg2000Setting(24),
            )

            self.assertEqual(stats.images_seen, 1)
            self.assertEqual(stats.images_recompressed, 1)
            self.assertLess(output.stat().st_size, source.stat().st_size)
            self.assertEqual(_validate_pdf(output), 1)

    def test_resolve_worker_count_caps_auto_and_custom_values(self):
        self.assertEqual(_resolve_worker_count(None, 1), 1)
        self.assertEqual(_resolve_worker_count(None, 20), DEFAULT_WORKER_COUNT)
        self.assertEqual(_resolve_worker_count(8, 3), 3)
        with self.assertRaisesRegex(Exception, "Worker count"):
            _resolve_worker_count(0, 3)

    def test_target_size_keeps_searching_if_early_candidate_is_larger_than_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            source.write_bytes(b"%PDF-1.4\n" + (b"x" * 100))
            candidate_dir = Path(tmp) / "candidates"
            candidate_dir.mkdir()
            raster_calls = []

            def fake_pdfwrite(_source, pdf_output, _profile_name, ghostscript_path=None, password=None):
                pdf_output.write_bytes(b"x" * 120)

            def fake_raster(_source, pdf_output, *, setting, **_kwargs):
                raster_calls.append(setting)
                pdf_output.write_bytes(b"x" * 80)

            with patch("pdf_compressor.core._run_ghostscript_pdfwrite", side_effect=fake_pdfwrite):
                with patch("pdf_compressor.core._run_raster_pdf", side_effect=fake_raster):
                    candidates = _create_candidates(
                        source,
                        candidate_dir,
                        get_profile("max"),
                        target_size_bytes=200,
                        original_size=source.stat().st_size,
                        page_count=2,
                    )

            self.assertTrue(raster_calls)
            self.assertEqual(min(candidate.path.stat().st_size for candidate in candidates), 80)

    def test_raster_pdf_renders_pages_with_workers(self):
        class FakeImage:
            mode = "RGB"

            def save(self, path, _format, *, quality, optimize):
                Path(path).write_bytes(b"jpeg")

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            output = Path(tmp) / "output.pdf"
            source.write_bytes(b"%PDF-1.4\nfake")
            rendered_pages = []

            def fake_convert(_source, *, first_page, last_page, userpw, **_kwargs):
                rendered_pages.append((first_page, last_page, userpw))
                return [FakeImage()]

            with patch("pdf_compressor.core._load_pdf_raster_tools", return_value=(fake_convert, object())):
                with patch("pdf_compressor.core._write_jpeg_pdf") as write_pdf:
                    progress_counts = []
                    _run_raster_pdf(
                        source,
                        output,
                        setting=RasterSetting(72, 40),
                        page_count=3,
                        password="pw",
                        worker_count=2,
                        page_progress_callback=lambda completed, total: progress_counts.append((completed, total)),
                    )

            self.assertEqual(sorted(rendered_pages), [(1, 1, "pw"), (2, 2, "pw"), (3, 3, "pw")])
            self.assertEqual(progress_counts, [(0, 3), (1, 3), (2, 3), (3, 3)])
            write_pdf.assert_called_once()
            image_paths = write_pdf.call_args.args[0]
            self.assertEqual([path.name for path in image_paths], ["page-00001.jpg", "page-00002.jpg", "page-00003.jpg"])


if __name__ == "__main__":
    unittest.main()
