"""Vercel serverless entrypoint for the PDF compressor."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
import sys
import tempfile
import uuid
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdf_compressor.core import CompressionError, PROFILES, compress_pdf
from pdf_compressor.server import (
    CompressorRequestHandler,
    _delete_if_present,
    _public_error_message,
    _target_size_from_fields,
    render_error,
)


SERVERLESS_WORKDIR = Path(tempfile.gettempdir()) / "pdf-compressor"
SERVERLESS_WORKDIR.mkdir(parents=True, exist_ok=True)


class handler(CompressorRequestHandler):
    """Single-request compression handler for stateless deployments."""

    workdir = SERVERLESS_WORKDIR
    jobs: dict[str, dict[str, object]] = {}

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/compress":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        input_path: Path | None = None
        output_path: Path | None = None
        password: str | None = None
        try:
            fields, upload = self._parse_upload()
            profile_name = fields.get("profile", "max")
            if profile_name not in PROFILES:
                raise CompressionError("Invalid compression profile.")

            target_size_bytes = _target_size_from_fields(fields)
            password = fields.get("password", "").strip() or None
            job_id = uuid.uuid4().hex
            input_path = self.workdir / f"{job_id}-upload.pdf"
            output_path = self.workdir / f"{job_id}-compressed.pdf"
            input_path.write_bytes(bytes(upload["data"]))
            del upload

            result = compress_pdf(
                input_path,
                output_path,
                profile_name=profile_name,
                target_size_bytes=target_size_bytes,
                password=password,
            )
            data = result.output_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self._send_private_headers()
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", 'attachment; filename="compressed.pdf"')
            self.end_headers()
            self.wfile.write(data)
        except CompressionError as exc:
            self._send_html(render_error(_public_error_message(str(exc))), HTTPStatus.BAD_REQUEST)
        finally:
            password = None
            if input_path is not None:
                _delete_if_present(input_path)
            if output_path is not None:
                _delete_if_present(output_path)
