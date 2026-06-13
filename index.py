"""Vercel ASGI entrypoint for the PDF compressor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

from pdf_compressor.core import CompressionError, PROFILES, compress_pdf, format_bytes
from pdf_compressor.server import (
    MAX_UPLOAD_BYTES,
    _delete_if_present,
    _public_error_message,
    _target_size_from_fields,
    render_blob_result,
    render_error,
    render_home,
)


app = FastAPI()
SERVERLESS_WORKDIR = Path(tempfile.gettempdir()) / "pdf-compressor"
SERVERLESS_WORKDIR.mkdir(parents=True, exist_ok=True)
VERCEL_DIRECT_PAYLOAD_BYTES = 4 * 1024 * 1024
BLOB_API_VERSION = "12"
BLOB_API_URL = os.environ.get("VERCEL_BLOB_API_URL", "https://vercel.com/api/blob").rstrip("/")


class BlobCompressionRequest(BaseModel):
    blob_url: str
    blob_pathname: str = ""
    filename: str = "uploaded.pdf"
    profile: str = "max"
    target_size_mb: str
    password: str = ""


@app.get("/")
def home() -> HTMLResponse:
    blob_upload_enabled = _blob_upload_enabled()
    upload_limit = MAX_UPLOAD_BYTES if blob_upload_enabled else VERCEL_DIRECT_PAYLOAD_BYTES
    target_limit = MAX_UPLOAD_BYTES if blob_upload_enabled else VERCEL_DIRECT_PAYLOAD_BYTES
    return HTMLResponse(
        render_home(
            max_file_size_bytes=upload_limit,
            max_target_size_bytes=target_limit,
            blob_upload_enabled=blob_upload_enabled,
        ),
        headers=_private_headers(),
    )


@app.get("/health")
def health() -> PlainTextResponse:
    return PlainTextResponse("ok", headers=_private_headers())


@app.post("/compress")
async def compress(
    pdf: UploadFile = File(...),
    profile: str = Form("max"),
    target_size_mb: str = Form(...),
    password: str = Form(""),
) -> Response:
    input_path: Path | None = None
    output_path: Path | None = None
    pdf_password = password.strip() or None
    try:
        if profile not in PROFILES:
            raise CompressionError("Invalid compression profile.")
        if not (pdf.filename or "").lower().endswith(".pdf"):
            raise CompressionError("Uploaded file must have a .pdf extension.")

        target_size_bytes = _target_size_from_fields({"target_size_mb": target_size_mb})
        if target_size_bytes > VERCEL_DIRECT_PAYLOAD_BYTES:
            raise CompressionError(
                "This hosted version can return compressed files up to "
                f"{format_bytes(VERCEL_DIRECT_PAYLOAD_BYTES)}. "
                "Choose a smaller target size, or use the local app for larger files."
            )

        data = await pdf.read()
        if not data:
            raise CompressionError("Uploaded PDF is empty.")
        if len(data) > VERCEL_DIRECT_PAYLOAD_BYTES:
            raise CompressionError(
                "This hosted version can receive PDFs up to "
                f"{format_bytes(VERCEL_DIRECT_PAYLOAD_BYTES)}. "
                "Use the local app or a storage-backed upload setup for larger files."
            )
        if len(data) > MAX_UPLOAD_BYTES:
            raise CompressionError(f"Upload is too large. Limit: {format_bytes(MAX_UPLOAD_BYTES)}.")

        job_id = uuid.uuid4().hex
        input_path = SERVERLESS_WORKDIR / f"{job_id}-upload.pdf"
        output_path = SERVERLESS_WORKDIR / f"{job_id}-compressed.pdf"
        input_path.write_bytes(data)
        del data

        result = compress_pdf(
            input_path,
            output_path,
            profile_name=profile,
            target_size_bytes=target_size_bytes,
            password=pdf_password,
        )
        body = result.output_path.read_bytes()
        headers = {
            **_private_headers(),
            "Content-Disposition": 'attachment; filename="compressed.pdf"',
        }
        return Response(content=body, media_type="application/pdf", headers=headers)
    except CompressionError as exc:
        return HTMLResponse(render_error(_public_error_message(str(exc))), status_code=400, headers=_private_headers())
    finally:
        pdf_password = None
        if input_path is not None:
            _delete_if_present(input_path)
        if output_path is not None:
            _delete_if_present(output_path)


@app.post("/compress-blob")
async def compress_blob(payload: BlobCompressionRequest) -> HTMLResponse:
    input_path: Path | None = None
    output_path: Path | None = None
    uploaded_blob_url = payload.blob_url.strip()
    result_blob_url = ""
    pdf_password = payload.password.strip() or None
    try:
        if not _blob_upload_enabled():
            raise CompressionError("Storage is not configured for this deployment.")
        if payload.profile not in PROFILES:
            raise CompressionError("Invalid compression profile.")
        if not payload.filename.lower().endswith(".pdf"):
            raise CompressionError("Uploaded file must have a .pdf extension.")

        _validate_blob_url(uploaded_blob_url)
        target_size_bytes = _target_size_from_fields({"target_size_mb": payload.target_size_mb})
        if target_size_bytes > MAX_UPLOAD_BYTES:
            raise CompressionError(f"Required output size is too large. Limit: {format_bytes(MAX_UPLOAD_BYTES)}.")

        job_id = uuid.uuid4().hex
        input_path = SERVERLESS_WORKDIR / f"{job_id}-upload.pdf"
        output_path = SERVERLESS_WORKDIR / f"{job_id}-compressed.pdf"
        _download_blob_to_file(uploaded_blob_url, input_path, MAX_UPLOAD_BYTES)

        result = compress_pdf(
            input_path,
            output_path,
            profile_name=payload.profile,
            target_size_bytes=target_size_bytes,
            password=pdf_password,
        )

        uploaded_result = _upload_blob_file(
            result.output_path,
            f"results/{job_id}-compressed.pdf",
            content_type="application/pdf",
        )
        result_blob_url = str(uploaded_result["url"])
        download_url = str(uploaded_result.get("downloadUrl") or _download_url(result_blob_url))
        job = {
            "id": job_id,
            "profile": result.profile.label,
            "method": result.method,
            "original_size": result.original_size,
            "compressed_size": result.compressed_size,
            "target_size_bytes": target_size_bytes,
            "bytes_saved": result.bytes_saved,
            "savings_percent": result.savings_percent,
        }
        return HTMLResponse(
            render_blob_result(job, download_url=download_url, cleanup_url=result_blob_url),
            headers=_private_headers(),
        )
    except CompressionError as exc:
        if result_blob_url:
            _delete_blob_quietly(result_blob_url)
        return HTMLResponse(render_error(_public_error_message(str(exc))), status_code=400, headers=_private_headers())
    finally:
        pdf_password = None
        if uploaded_blob_url:
            _delete_blob_quietly(uploaded_blob_url)
        if input_path is not None:
            _delete_if_present(input_path)
        if output_path is not None:
            _delete_if_present(output_path)


@app.post("/cleanup-blob")
async def cleanup_blob(request: Request) -> PlainTextResponse:
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body.decode("utf-8") if raw_body else "{}")
        url = str(payload.get("url", "")).strip()
        if url:
            _delete_blob(url)
    except (CompressionError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return PlainTextResponse("ok", headers=_private_headers())


def _private_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def _blob_upload_enabled() -> bool:
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip())


def _blob_token() -> str:
    token = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
    if not token:
        raise CompressionError("Storage token is missing.")
    return token


def _blob_store_id(token: str) -> str:
    parts = token.split("_")
    if len(parts) < 4 or not parts[3]:
        raise CompressionError("Storage token is invalid.")
    return parts[3]


def _blob_api_headers(*, content_type: str | None = None) -> dict[str, str]:
    token = _blob_token()
    store_id = _blob_store_id(token)
    headers = {
        "authorization": f"Bearer {token}",
        "x-vercel-blob-store-id": store_id,
        "x-api-blob-request-id": f"{store_id}:{uuid.uuid4().hex}",
        "x-api-blob-request-attempt": "0",
        "x-api-version": BLOB_API_VERSION,
    }
    if content_type:
        headers["content-type"] = content_type
    return headers


def _validate_blob_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".blob.vercel-storage.com"):
        raise CompressionError("Uploaded file is not from secure storage.")
    if not parsed.path.lower().endswith(".pdf"):
        raise CompressionError("Uploaded file must be a PDF.")


def _download_blob_to_file(url: str, destination: Path, max_bytes: int) -> None:
    _validate_blob_url(url)
    headers = {"authorization": f"Bearer {_blob_token()}"}
    request = UrlRequest(url, headers=headers)
    try:
        with urlopen(request, timeout=120) as response, destination.open("wb") as output:
            content_length = int(response.headers.get("content-length", "0") or "0")
            if content_length > max_bytes:
                raise CompressionError(f"Upload is too large. Limit: {format_bytes(max_bytes)}.")

            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise CompressionError(f"Upload is too large. Limit: {format_bytes(max_bytes)}.")
                output.write(chunk)
    except HTTPError as exc:
        raise CompressionError("Could not read the uploaded PDF from storage.") from exc
    except URLError as exc:
        raise CompressionError("Could not reach storage for the uploaded PDF.") from exc


def _upload_blob_file(path: Path, pathname: str, *, content_type: str) -> dict[str, object]:
    data = path.read_bytes()
    params = urlencode({"pathname": pathname})
    headers = _blob_api_headers(content_type=content_type)
    headers.update(
        {
            "x-vercel-blob-access": "public",
            "x-content-type": content_type,
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "0",
            "x-cache-control-max-age": "60",
            "x-content-length": str(len(data)),
        }
    )
    request = UrlRequest(f"{BLOB_API_URL}/?{params}", data=data, method="PUT", headers=headers)
    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise CompressionError("Could not save the compressed PDF to storage.") from exc
    except URLError as exc:
        raise CompressionError("Could not reach storage for the compressed PDF.") from exc


def _delete_blob(url: str) -> None:
    _validate_blob_url(url)
    body = json.dumps({"urls": [url]}).encode("utf-8")
    request = UrlRequest(
        f"{BLOB_API_URL}/delete",
        data=body,
        method="POST",
        headers=_blob_api_headers(content_type="application/json"),
    )
    try:
        with urlopen(request, timeout=30):
            return
    except HTTPError as exc:
        raise CompressionError("Could not remove the file from storage.") from exc
    except URLError as exc:
        raise CompressionError("Could not reach storage to remove the file.") from exc


def _delete_blob_quietly(url: str) -> None:
    try:
        _delete_blob(url)
    except CompressionError:
        pass


def _download_url(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}download=1"
