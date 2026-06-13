import unittest
from pathlib import Path
import tempfile

from pdf_compressor.server import CompressorRequestHandler, _impact_items, _job_status_payload


class ServerImpactTests(unittest.TestCase):
    def test_raster_impact_reports_text_and_color_tradeoffs(self):
        items = dict(
            _impact_items(
                {
                    "original_size": 10 * 1024 * 1024,
                    "compressed_size": 4 * 1024 * 1024,
                    "target_size_bytes": 5 * 1024 * 1024,
                    "savings_percent": 60.0,
                    "method": "Page-by-page compression with reduced color",
                }
            )
        )

        self.assertIn("under the requested limit", items["Target fit"])
        self.assertIn("compressed more strongly", items["Visual quality"])
        self.assertIn("selectable text", items["Text and search"])
        self.assertIn("Color information is removed", items["Color"])

    def test_ghostscript_impact_reports_text_should_remain(self):
        items = dict(
            _impact_items(
                {
                    "original_size": 10 * 1024 * 1024,
                    "compressed_size": 6 * 1024 * 1024,
                    "target_size_bytes": 7 * 1024 * 1024,
                    "savings_percent": 40.0,
                    "method": "Making the PDF smaller for sharing",
                }
            )
        )

        self.assertIn("not flattened", items["Text and search"])

    def test_pikepdf_jpeg2000_impact_reports_resolution_is_preserved(self):
        items = dict(
            _impact_items(
                {
                    "original_size": 10 * 1024 * 1024,
                    "compressed_size": 4 * 1024 * 1024,
                    "target_size_bytes": 5 * 1024 * 1024,
                    "savings_percent": 60.0,
                    "method": "Image compression that keeps text selectable",
                }
            )
        )

        self.assertIn("original dimensions", items["Visual quality"])
        self.assertIn("not flattened", items["Text and search"])
        self.assertIn("slightly softer", items["Image detail"])


class ServerPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.original_jobs = CompressorRequestHandler.jobs
        CompressorRequestHandler.jobs = {}

    def tearDown(self):
        CompressorRequestHandler.jobs = self.original_jobs

    def test_expired_complete_job_removes_files_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "compressed.pdf"
            output_path.write_bytes(b"%PDF-1.4\ncompressed")
            CompressorRequestHandler.jobs["job-1"] = {
                "id": "job-1",
                "status": "complete",
                "path": output_path,
                "expires_at": 10,
            }

            CompressorRequestHandler.cleanup_expired_jobs(now=11)

            self.assertNotIn("job-1", CompressorRequestHandler.jobs)
            self.assertFalse(output_path.exists())

    def test_running_job_is_not_cleaned_before_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "upload.pdf"
            input_path.write_bytes(b"%PDF-1.4\ninput")
            CompressorRequestHandler.jobs["job-2"] = {
                "id": "job-2",
                "status": "running",
                "input_path": input_path,
                "expires_at": 10,
            }

            CompressorRequestHandler.cleanup_expired_jobs(now=11)

            self.assertIn("job-2", CompressorRequestHandler.jobs)
            self.assertTrue(input_path.exists())

    def test_status_payload_does_not_expose_file_paths(self):
        payload = _job_status_payload(
            {
                "id": "job-3",
                "status": "complete",
                "progress": 100,
                "message": "Compression complete",
                "target_size_bytes": 1024,
                "path": "/private/tmp/secret.pdf",
                "input_path": "/private/tmp/upload.pdf",
            }
        )

        self.assertNotIn("path", payload)
        self.assertNotIn("input_path", payload)
        self.assertIn("resultUrl", payload)


if __name__ == "__main__":
    unittest.main()
