from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pdf_compressor.core import (
    CompressionCandidate,
    CompressionNotUsefulError,
    CompressionTargetError,
    GhostscriptMissingError,
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
                result = compress_pdf(
                    source,
                    output,
                    profile_name="screen",
                    ghostscript_path="/usr/bin/gs",
                    target_size_bytes=50,
                )

            self.assertLessEqual(result.compressed_size, 50)
            self.assertTrue(output.exists())

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
                with self.assertRaises(CompressionTargetError):
                    compress_pdf(
                        source,
                        output,
                        profile_name="screen",
                        ghostscript_path="/usr/bin/gs",
                        target_size_bytes=50,
                    )

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
