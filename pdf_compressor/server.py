"""Small local web interface for the PDF compressor."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import uuid
from urllib.parse import parse_qs, urlparse

from .core import CompressionError, PROFILES, compress_pdf, format_bytes


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
RESULT_TTL_SECONDS = 30 * 60
ERROR_TTL_SECONDS = 10 * 60
CLEANUP_INTERVAL_SECONDS = 60


class CompressorRequestHandler(BaseHTTPRequestHandler):
    server_version = "PDFCompressor/0.1"
    jobs: dict[str, dict[str, object]] = {}
    job_lock = threading.Lock()
    workdir: Path | None = None

    def do_GET(self) -> None:
        self.cleanup_expired_jobs()
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(render_home())
            return
        if parsed.path == "/progress":
            self._handle_progress(parsed.query)
            return
        if parsed.path == "/status":
            self._handle_status(parsed.query)
            return
        if parsed.path == "/result":
            self._handle_result(parsed.query)
            return
        if parsed.path == "/download":
            self._handle_download(parsed.query)
            return
        if parsed.path == "/health":
            self._send_text("ok")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        self.cleanup_expired_jobs()
        parsed = urlparse(self.path)
        if parsed.path != "/compress":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            fields, upload = self._parse_upload()
            profile_name = fields.get("profile", "max")
            if profile_name not in PROFILES:
                raise CompressionError("Invalid compression profile.")
            target_size_bytes = _target_size_from_fields(fields)
            password = fields.get("password", "").strip() or None

            if self.workdir is None:
                raise CompressionError("Server storage is not available.")

            job_id = uuid.uuid4().hex
            input_path = self.workdir / f"{job_id}-upload.pdf"
            output_path = self.workdir / f"{job_id}-compressed.pdf"
            input_path.write_bytes(upload["data"])
            del upload

            with self.job_lock:
                self.jobs[job_id] = {
                    "id": job_id,
                    "status": "queued",
                    "progress": 3,
                    "message": "Upload received",
                    "input_path": input_path,
                    "output_path": output_path,
                    "profile_name": profile_name,
                    "target_size_bytes": target_size_bytes,
                    "created_at": time.time(),
                    "expires_at": time.time() + ERROR_TTL_SECONDS,
                }

            thread = threading.Thread(target=_compress_job, args=(job_id, password), daemon=True)
            thread.start()

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/progress?id={job_id}")
            self.end_headers()
        except CompressionError as exc:
            self._send_html(render_error(_public_error_message(str(exc))), HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        status = args[1] if len(args) > 1 else ""
        print(f"{self.address_string()} - {self.command} {urlparse(self.path).path} {status}")

    def _handle_progress(self, query: str) -> None:
        job = self._job_from_query(query)
        if not job:
            self._send_html(render_error("Compression job was not found."), HTTPStatus.NOT_FOUND)
            return
        self._send_html(render_progress(job))

    def _handle_status(self, query: str) -> None:
        job = self._job_from_query(query)
        if not job:
            self._send_json({"status": "missing", "message": "Compression job was not found."}, HTTPStatus.NOT_FOUND)
            return
        self._send_json(_job_status_payload(job))

    def _handle_result(self, query: str) -> None:
        job = self._job_from_query(query)
        if not job:
            self._send_html(render_error("Compression result was not found."), HTTPStatus.NOT_FOUND)
            return
        if job.get("status") in {"queued", "running"}:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/progress?id={escape(str(job['id']))}")
            self.end_headers()
            return
        if job.get("status") == "error":
            self._send_html(
                render_error(_public_error_message(str(job.get("message", "Compression failed.")))),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._send_html(render_result(job))

    def _handle_download(self, query: str) -> None:
        job = self._job_from_query(query)
        if not job:
            self.send_error(HTTPStatus.NOT_FOUND, "Download not found")
            return
        if job.get("status") != "complete":
            self.send_error(HTTPStatus.CONFLICT, "Compressed file is not ready")
            return

        output_path = Path(str(job["path"]))
        if not output_path.exists():
            self.delete_job(str(job["id"]), remove_output=True)
            self.send_error(HTTPStatus.GONE, "Compressed file expired")
            return

        data = output_path.read_bytes()
        filename = str(job["filename"])
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self._send_private_headers()
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(data)
        finally:
            self.delete_job(str(job["id"]), remove_output=True)

    def _job_from_query(self, query: str) -> dict[str, object] | None:
        job_id = parse_qs(query).get("id", [""])[0]
        with self.job_lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    @classmethod
    def get_job(cls, job_id: str) -> dict[str, object] | None:
        with cls.job_lock:
            job = cls.jobs.get(job_id)
            return dict(job) if job else None

    @classmethod
    def update_job(cls, job_id: str, **updates: object) -> None:
        with cls.job_lock:
            if job_id in cls.jobs:
                cls.jobs[job_id].update(updates)

    @classmethod
    def delete_job(cls, job_id: str, *, remove_output: bool = True) -> None:
        with cls.job_lock:
            job = cls.jobs.pop(job_id, None)
        if job:
            _delete_job_files(job, remove_output=remove_output)

    @classmethod
    def cleanup_expired_jobs(cls, now: float | None = None) -> None:
        current_time = time.time() if now is None else now
        expired_job_ids: list[str] = []
        with cls.job_lock:
            for job_id, job in cls.jobs.items():
                if str(job.get("status", "")) in {"queued", "running"}:
                    continue
                expires_at = float(job.get("expires_at", 0) or 0)
                if expires_at and expires_at <= current_time:
                    expired_job_ids.append(job_id)

        for job_id in expired_job_ids:
            cls.delete_job(job_id, remove_output=True)

    def _parse_upload(self) -> tuple[dict[str, str], dict[str, object]]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise CompressionError("Expected a PDF upload.")

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            raise CompressionError("Upload is empty.")
        if content_length > MAX_UPLOAD_BYTES:
            raise CompressionError(f"Upload is too large. Limit: {format_bytes(MAX_UPLOAD_BYTES)}.")

        body = self.rfile.read(content_length)
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )

        fields: dict[str, str] = {}
        upload: dict[str, object] | None = None

        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue

            if name == "pdf":
                filename = part.get_filename() or "uploaded.pdf"
                data = part.get_payload(decode=True) or b""
                if not data:
                    raise CompressionError("Uploaded PDF is empty.")
                if not filename.lower().endswith(".pdf"):
                    raise CompressionError("Uploaded file must have a .pdf extension.")
                upload = {"data": data}
            else:
                raw = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                fields[name] = raw.decode(charset, errors="replace")

        if upload is None:
            raise CompressionError("Choose a PDF file before compressing.")
        return fields, upload

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._send_private_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self._send_private_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_private_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_private_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    with tempfile.TemporaryDirectory(prefix="pdf-compressor-") as tmp:
        CompressorRequestHandler.workdir = Path(tmp)
        CompressorRequestHandler.jobs = {}
        server = ThreadingHTTPServer((host, port), CompressorRequestHandler)
        stop_cleanup = threading.Event()
        cleanup_thread = threading.Thread(target=_cleanup_loop, args=(stop_cleanup,), daemon=True)
        cleanup_thread.start()
        print(f"PDF Compressor is running at http://{host}:{port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            stop_cleanup.set()
            CompressorRequestHandler.cleanup_expired_jobs(now=time.time() + max(RESULT_TTL_SECONDS, ERROR_TTL_SECONDS) + 1)
            server.server_close()


def _cleanup_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(CLEANUP_INTERVAL_SECONDS):
        CompressorRequestHandler.cleanup_expired_jobs()


def _compress_job(job_id: str, password: str | None = None) -> None:
    job = CompressorRequestHandler.get_job(job_id)
    if not job:
        return

    input_path = Path(str(job["input_path"]))
    output_path = Path(str(job["output_path"]))
    profile_name = str(job["profile_name"])
    target_size_bytes = int(job["target_size_bytes"])

    def report(progress: int, message: str) -> None:
        CompressorRequestHandler.update_job(
            job_id,
            status="running",
            progress=progress,
            message=message,
            expires_at=time.time() + ERROR_TTL_SECONDS,
        )

    try:
        report(5, "Preparing compression")
        result = compress_pdf(
            input_path,
            output_path,
            profile_name=profile_name,
            target_size_bytes=target_size_bytes,
            progress_callback=report,
            password=password,
        )
        CompressorRequestHandler.update_job(
            job_id,
            status="complete",
            progress=100,
            message="Compression complete",
            path=result.output_path,
            filename="compressed.pdf",
            profile=result.profile.label,
            method=result.method,
            original_size=result.original_size,
            compressed_size=result.compressed_size,
            savings_percent=result.savings_percent,
            bytes_saved=result.bytes_saved,
            worker_count=result.worker_count,
            input_path="",
            output_path="",
            expires_at=time.time() + RESULT_TTL_SECONDS,
        )
    except CompressionError as exc:
        _delete_if_present(output_path)
        CompressorRequestHandler.update_job(
            job_id,
            status="error",
            progress=100,
            message=_public_error_message(str(exc)),
            input_path="",
            output_path="",
            expires_at=time.time() + ERROR_TTL_SECONDS,
        )
    finally:
        password = None
        _delete_if_present(input_path)


def _target_size_from_fields(fields: dict[str, str]) -> int:
    raw_size = fields.get("target_size_mb", "").strip()
    if not raw_size:
        raise CompressionError("Enter the required output size in MB.")

    try:
        size_mb = float(raw_size)
    except ValueError as exc:
        raise CompressionError("Required output size must be a number.") from exc

    if size_mb <= 0:
        raise CompressionError("Required output size must be greater than zero.")

    return max(1, round(size_mb * 1024 * 1024))


def _job_status_payload(job: dict[str, object]) -> dict[str, object]:
    progress = int(job.get("progress", 0))
    payload: dict[str, object] = {
        "id": str(job["id"]),
        "status": str(job.get("status", "queued")),
        "progress": max(0, min(progress, 100)),
        "message": str(job.get("message", "")),
        "targetSize": format_bytes(int(job["target_size_bytes"])),
    }
    if job.get("status") == "complete":
        payload["resultUrl"] = f"/result?id={job['id']}"
    return payload


def _target_placeholder(max_target_size_bytes: int | None) -> str:
    if max_target_size_bytes is None:
        return "5"
    target_mb = max_target_size_bytes / (1024 * 1024)
    return f"{target_mb:.2f}".rstrip("0").rstrip(".")


def _render_hosted_limit_note(max_file_size_bytes: int | None, max_target_size_bytes: int | None) -> str:
    if max_file_size_bytes is None and max_target_size_bytes is None:
        return ""

    parts: list[str] = []
    if max_file_size_bytes is not None:
        parts.append(f"uploads up to {format_bytes(max_file_size_bytes)}")
    if max_target_size_bytes is not None:
        parts.append(f"downloads up to {format_bytes(max_target_size_bytes)}")
    limit_text = " and ".join(parts)
    return (
        '<p class="privacy-note hosted-note">'
        f"This hosted version supports {escape(limit_text)}. "
        "For larger PDFs, use the local app or a storage-backed upload setup."
        "</p>"
    )


def _render_client_size_guard(max_file_size_bytes: int | None, max_target_size_bytes: int | None) -> str:
    if max_file_size_bytes is None and max_target_size_bytes is None:
        return ""

    file_limit = "null" if max_file_size_bytes is None else str(max_file_size_bytes)
    target_limit = "null" if max_target_size_bytes is None else str(max_target_size_bytes)
    file_label = format_bytes(max_file_size_bytes) if max_file_size_bytes is not None else ""
    target_label = format_bytes(max_target_size_bytes) if max_target_size_bytes is not None else ""
    return f"""
        <script>
          (() => {{
            const form = document.querySelector(".compress-form");
            const error = document.getElementById("clientError");
            if (!form || !error) {{
              return;
            }}

            const maxFileBytes = {file_limit};
            const maxTargetBytes = {target_limit};
            const maxFileLabel = "{escape(file_label)}";
            const maxTargetLabel = "{escape(target_label)}";

            form.addEventListener("submit", (event) => {{
              const fileInput = form.elements.namedItem("pdf");
              const targetInput = form.elements.namedItem("target_size_mb");
              const file = fileInput && fileInput.files ? fileInput.files[0] : null;
              const targetMb = Number(targetInput ? targetInput.value : 0);
              const targetBytes = targetMb * 1024 * 1024;
              let message = "";

              if (maxFileBytes && file && file.size > maxFileBytes) {{
                message = "This version supports PDFs up to " + maxFileLabel + ". Choose a smaller PDF, or use the local app for larger files.";
              }} else if (maxTargetBytes && targetBytes > maxTargetBytes) {{
                message = "This version can return compressed files up to " + maxTargetLabel + ". Choose a smaller target size, or use the local app for larger files.";
              }}

              if (message) {{
                event.preventDefault();
                error.textContent = message;
                error.classList.remove("hidden");
                error.setAttribute("tabindex", "-1");
                error.focus();
              }} else {{
                error.textContent = "";
                error.classList.add("hidden");
              }}
            }});
          }})();
        </script>
    """


def render_home(
    *,
    max_file_size_bytes: int | None = None,
    max_target_size_bytes: int | None = None,
    blob_upload_enabled: bool = False,
) -> str:
    options = "\n".join(
        f'<option value="{escape(profile.name)}">{escape(profile.label)}</option>'
        for profile in PROFILES.values()
    )
    target_placeholder = _target_placeholder(max_target_size_bytes)
    hosted_note = _render_hosted_limit_note(max_file_size_bytes, max_target_size_bytes)
    client_guard = _render_client_size_guard(max_file_size_bytes, max_target_size_bytes)
    upload_limit_label = format_bytes(max_file_size_bytes or MAX_UPLOAD_BYTES)
    blob_upload_attr = ' data-blob-upload="true"' if blob_upload_enabled else ""
    blob_upload_script = '<script type="module" src="/blob-upload-client.js"></script>' if blob_upload_enabled else ""
    return _page(
        "PDF Compressor",
        f"""
        <main class="shell">
          <section class="tool-panel">
            <div class="panel-heading">
              <div>
                <h1>Compress PDF</h1>
                <p class="lead">Choose a PDF and target size.</p>
              </div>
              <span class="status">Ready</span>
            </div>

            <form class="compress-form" action="/compress" method="post" enctype="multipart/form-data" data-max-upload-bytes="{max_file_size_bytes or MAX_UPLOAD_BYTES}"{blob_upload_attr}>
              <label class="file-drop">
                <span>PDF file (max {escape(upload_limit_label)})</span>
                <input type="file" name="pdf" accept="application/pdf,.pdf" required>
              </label>

              <div class="form-grid">
                <label>
                  <span>Compression style</span>
                  <select name="profile">{options}</select>
                </label>
                <label>
                  <span>Required size (MB)</span>
                  <input type="number" name="target_size_mb" min="0.01" step="0.01" placeholder="{target_placeholder}" required>
                </label>
              </div>

              <label>
                <span>PDF password, if needed</span>
                <input type="password" name="password" autocomplete="current-password" placeholder="Leave empty for unlocked PDFs">
              </label>

              <div class="client-error hidden" id="clientError"></div>
              <div class="upload-status hidden" id="uploadStatus">
                <div class="progress-shell" aria-label="PDF progress">
                  <div class="progress-meter" id="uploadProgressMeter"></div>
                </div>
                <div class="status-steps" aria-label="Compression status">
                  <div class="status-step" id="stepFile"><span class="step-mark"></span><span id="stepFileText">File uploading</span></div>
                  <div class="status-step" id="stepCompressing"><span class="step-mark"></span><span>Compression in progress</span></div>
                </div>
              </div>
              <button type="submit">Compress PDF</button>
            </form>

            <p class="privacy-note">Files are cleaned up after processing and download.</p>
            {hosted_note}
          </section>
        </main>
        {client_guard}
        {blob_upload_script}
        """,
    )


def render_progress(job: dict[str, object]) -> str:
    job_id = escape(str(job["id"]))
    progress = max(0, min(int(job.get("progress", 0)), 100))
    status = str(job.get("status", "queued"))
    message_text = "Compression failed" if status == "error" else str(job.get("message", "Compression queued"))
    message = escape(message_text)
    target_size = format_bytes(int(job["target_size_bytes"]))
    return _page(
        "Compressing PDF",
        f"""
        <main class="shell">
          <section class="tool-panel">
            <div class="panel-heading">
              <div>
                <h1>Compressing PDF</h1>
                <p class="lead">Target: {escape(target_size)}</p>
              </div>
              <span class="status" id="statusLabel">Working</span>
            </div>
            <div class="progress-shell" aria-label="Compression progress">
              <div class="progress-meter" id="progressMeter" style="width: {progress}%"></div>
            </div>
            <div class="progress-meta">
              <strong id="progressValue">{progress}%</strong>
              <span>Files are cleaned up automatically</span>
            </div>
            <p class="progress-message" id="progressMessage">{message}</p>
            <pre class="error hidden" id="progressError"></pre>
            <div class="actions hidden" id="progressActions">
              <a class="button" id="resultLink" href="/result?id={job_id}">View result</a>
              <a class="secondary" href="/">Compress another</a>
            </div>
          </section>
        </main>
        <script>
          const jobId = "{job_id}";
          const meter = document.getElementById("progressMeter");
          const value = document.getElementById("progressValue");
          const message = document.getElementById("progressMessage");
          const label = document.getElementById("statusLabel");
          const error = document.getElementById("progressError");
          const actions = document.getElementById("progressActions");
          const resultLink = document.getElementById("resultLink");

          async function refreshProgress() {{
            try {{
              const response = await fetch(`/status?id=${{encodeURIComponent(jobId)}}`, {{ cache: "no-store" }});
              const job = await response.json();
              const progress = Math.max(0, Math.min(Number(job.progress || 0), 100));
              meter.style.width = `${{progress}}%`;
              value.textContent = `${{progress}}%`;
              message.textContent = job.message || "";

              if (job.status === "complete") {{
                label.textContent = "Ready";
                resultLink.href = job.resultUrl || `/result?id=${{encodeURIComponent(jobId)}}`;
                actions.classList.remove("hidden");
                window.location.href = resultLink.href;
                return;
              }}

              if (job.status === "error" || job.status === "missing") {{
                label.textContent = "Check";
                label.classList.add("warning");
                message.textContent = "";
                error.textContent = job.message || "Compression failed.";
                error.classList.remove("hidden");
                actions.classList.remove("hidden");
                resultLink.classList.add("hidden");
                return;
              }}

              window.setTimeout(refreshProgress, 700);
            }} catch (err) {{
              message.textContent = "Waiting for compression status";
              window.setTimeout(refreshProgress, 1200);
            }}
          }}

          refreshProgress();
        </script>
        """,
    )


def render_result(job: dict[str, object]) -> str:
    saved = int(job["bytes_saved"])
    saved_class = "positive" if saved >= 0 else "negative"
    target_size = int(job["target_size_bytes"])
    impact_html = _render_impact(job)
    return _page(
        "Your PDF Is Ready",
        f"""
        <main class="shell">
          <section class="tool-panel">
            <div class="panel-heading">
              <div>
                <h1>Your PDF is ready</h1>
                <p class="lead">Download your compressed PDF.</p>
              </div>
              <span class="status">Ready</span>
            </div>
            <dl class="stats">
              <div><dt>Profile</dt><dd>{escape(str(job["profile"]))}</dd></div>
              <div><dt>Compression used</dt><dd>{escape(str(job["method"]))}</dd></div>
              <div><dt>Original</dt><dd>{format_bytes(int(job["original_size"]))}</dd></div>
              <div><dt>Output</dt><dd>{format_bytes(int(job["compressed_size"]))}</dd></div>
              <div><dt>Target</dt><dd>{format_bytes(target_size)}</dd></div>
              <div><dt>Savings</dt><dd class="{saved_class}">{format_bytes(saved)} ({float(job["savings_percent"]):.1f}%)</dd></div>
            </dl>
            {impact_html}
            <div class="actions">
              <a class="button" href="/download?id={escape(str(job["id"]))}">Download PDF</a>
              <a class="secondary" href="/">Compress another</a>
            </div>
            <p class="cleanup-note">The server copy is removed after download or after it expires.</p>
          </section>
        </main>
        """,
    )


def render_blob_result(job: dict[str, object], *, download_url: str, cleanup_url: str) -> str:
    saved = int(job["bytes_saved"])
    saved_class = "positive" if saved >= 0 else "negative"
    target_size = int(job["target_size_bytes"])
    impact_html = _render_impact(job)
    return _page(
        "Your PDF Is Ready",
        f"""
        <main class="shell">
          <section class="tool-panel">
            <div class="panel-heading">
              <div>
                <h1>Your PDF is ready</h1>
                <p class="lead">Download your compressed PDF.</p>
              </div>
              <span class="status">Ready</span>
            </div>
            <dl class="stats">
              <div><dt>Profile</dt><dd>{escape(str(job["profile"]))}</dd></div>
              <div><dt>Compression used</dt><dd>{escape(str(job["method"]))}</dd></div>
              <div><dt>Original</dt><dd>{format_bytes(int(job["original_size"]))}</dd></div>
              <div><dt>Output</dt><dd>{format_bytes(int(job["compressed_size"]))}</dd></div>
              <div><dt>Target</dt><dd>{format_bytes(target_size)}</dd></div>
              <div><dt>Savings</dt><dd class="{saved_class}">{format_bytes(saved)} ({float(job["savings_percent"]):.1f}%)</dd></div>
            </dl>
            {impact_html}
            <div class="actions">
              <a class="button" id="blobDownloadLink" href="{escape(download_url)}">Download PDF</a>
              <a class="secondary" href="/">Compress another</a>
            </div>
            <p class="cleanup-note">The uploaded PDF was removed after compression. The compressed file is removed shortly after download starts.</p>
          </section>
        </main>
        <script>
          const downloadLink = document.getElementById("blobDownloadLink");
          if (downloadLink) {{
            downloadLink.addEventListener("click", () => {{
              const payload = JSON.stringify({{ url: {json.dumps(cleanup_url)} }});
              window.setTimeout(() => {{
                if (!navigator.sendBeacon || !navigator.sendBeacon("/cleanup-blob", payload)) {{
                  fetch("/cleanup-blob", {{
                    method: "POST",
                    headers: {{ "content-type": "application/json" }},
                    body: payload,
                    keepalive: true,
                  }}).catch(() => {{}});
                }}
              }}, 30000);
            }}, {{ once: true }});
          }}
        </script>
        """,
    )


def _render_impact(job: dict[str, object]) -> str:
    items = "\n".join(
        f"""
              <div>
                <dt>{escape(title)}</dt>
                <dd>{escape(description)}</dd>
              </div>
        """
        for title, description in _impact_items(job)
    )
    return f"""
            <section class="impact">
              <h2>Impact of smaller size</h2>
              <dl class="impact-list">
                {items}
              </dl>
            </section>
    """


def _impact_items(job: dict[str, object]) -> list[tuple[str, str]]:
    original_size = int(job["original_size"])
    compressed_size = int(job["compressed_size"])
    target_size = int(job["target_size_bytes"])
    saved = original_size - compressed_size
    savings_percent = float(job["savings_percent"])
    method = str(job["method"])
    method_lower = method.lower()

    items = [
        (
            "Size benefit",
            f"Reduced by {format_bytes(saved)} ({savings_percent:.1f}% smaller), so uploads, downloads, sharing, and storage use less data.",
        )
    ]

    if compressed_size <= target_size:
        items.append(("Target fit", f"Finished {format_bytes(target_size - compressed_size)} under the requested limit."))

    if "page-by-page compression" in method_lower:
        items.extend(_raster_impact_items(method))
    elif "light cleanup" in method_lower or "without changing quality" in method_lower:
        items.extend(
            [
                ("Visual quality", "Usually unchanged; the file was cleaned up without intentionally lowering image quality."),
                (
                    "Text and search",
                    "Text, links, forms, and selection should usually remain available because pages are not flattened.",
                ),
            ]
        )
    elif "image compression" in method_lower or "keeps text selectable" in method_lower:
        items.extend(
            [
                (
                    "Visual quality",
                    "Images were compressed at their original dimensions, so page resolution is not lowered.",
                ),
                (
                    "Text and search",
                    "Text, links, forms, and selection should usually remain available because pages are not flattened.",
                ),
                (
                    "Image detail",
                    "Photos or scans may look slightly softer when zoomed, but layout and text are preserved.",
                ),
            ]
        )
    elif "lossless" in method_lower:
        items.extend(
            [
                ("Visual quality", "Usually unchanged; the file is cleaned up without intentionally lowering image quality."),
                ("Text and search", "Text, links, and selection should usually remain available."),
            ]
        )
    else:
        items.extend(
            [
                ("Visual quality", "Images may be made smaller, so photos or scans can look softer when zoomed or printed."),
                ("Text and search", "Text, links, and selection should usually remain available because pages are not flattened."),
            ]
        )

    return items


def _raster_impact_items(method: str) -> list[tuple[str, str]]:
    reduced_color = "reduced color" in method.lower()
    visual_detail = "Each page was compressed more strongly to meet the size limit"
    if reduced_color:
        visual_detail += ", and color was reduced to save more space"
    items = [
        ("Visual quality", f"{visual_detail}; fine text, signatures, stamps, and scanned images may look softer."),
        ("Text and search", "Pages are flattened into images, so selectable text, search, links, and form fields may be lost."),
        ("Print quality", "Best for screen viewing or strict file-size limits; printed output may be less sharp."),
    ]
    if reduced_color:
        items.append(("Color", "Color information is removed to save more space."))
    return items


def _public_error_message(message: str) -> str:
    lower = message.lower()
    if "ghostscript" in lower:
        return (
            "This PDF needs a stronger compression step that is not available on this server. "
            "Try a larger target size, or run the app where full compression support is installed."
        )
    if "poppler" in lower or "pdftoppm" in lower or "pdf2image" in lower:
        return (
            "This PDF needs page-by-page compression support that is not available on this server. "
            "Try a larger target size, or run the app where full compression support is installed."
        )
    if "pikepdf" in lower or "jpeg2000" in lower or "pillow" in lower:
        return (
            "This server could not run the image compression step for this PDF. "
            "Try a larger target size or another PDF."
        )
    return message


def render_error(message: str) -> str:
    return _page(
        "Compression Error",
        f"""
        <main class="shell">
          <section class="tool-panel">
            <div class="panel-heading">
              <h1>Compression stopped</h1>
              <span class="status warning">Check</span>
            </div>
            <pre class="error">{escape(message)}</pre>
            <div class="actions">
              <a class="secondary" href="/">Back</a>
            </div>
          </section>
        </main>
        """,
    )


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #18211d;
      --muted: #64716b;
      --paper: #f6f6f2;
      --panel: #ffffff;
      --line: #d9ded8;
      --accent: #2d806a;
      --accent-dark: #21614f;
      --warn: #9b4f11;
      --bad: #9f2f25;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--paper);
      color: var(--ink);
    }}
    .shell {{
      width: min(680px, calc(100vw - 32px));
      margin: 0 auto;
      padding: clamp(24px, 7vw, 64px) 0;
    }}
    .tool-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: clamp(20px, 4vw, 32px);
      box-shadow: 0 14px 34px rgba(24, 33, 29, 0.07);
    }}
    .panel-heading {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(2rem, 5vw, 2.8rem);
      line-height: 1.05;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 1.1rem;
      line-height: 1.3;
      letter-spacing: 0;
    }}
    .lead {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.5;
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 0 12px;
      border-radius: 999px;
      background: #e4f1ed;
      color: var(--accent-dark);
      font-weight: 800;
      font-size: 0.88rem;
      white-space: nowrap;
    }}
    .status.warning {{
      background: #f8e7d5;
      color: var(--warn);
    }}
    .compress-form {{
      display: grid;
      gap: 18px;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 180px;
      gap: 14px;
    }}
    label {{
      display: grid;
      gap: 8px;
      color: var(--muted);
      font-size: 0.94rem;
      font-weight: 750;
    }}
    input,
    select {{
      width: 100%;
      min-height: 48px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfbf8;
      color: var(--ink);
      font: inherit;
      font-weight: 650;
      padding: 10px 12px;
    }}
    input::placeholder {{
      color: #8b958f;
    }}
    .file-drop {{
      border: 1px dashed #acb8b2;
      border-radius: 8px;
      background: #fbfcfa;
      padding: 16px;
    }}
    .file-drop input {{
      min-height: 40px;
      border: 0;
      background: transparent;
      padding: 0;
    }}
    .file-drop input::file-selector-button {{
      min-height: 34px;
      margin-right: 10px;
      border: 0;
      border-radius: 8px;
      background: var(--ink);
      color: #fff;
      font: inherit;
      font-weight: 800;
      padding: 7px 12px;
      cursor: pointer;
    }}
    .client-error {{
      border: 1px solid #e2aaa0;
      border-radius: 8px;
      background: #fff7f5;
      color: var(--bad);
      padding: 12px 14px;
      font-size: 0.94rem;
      line-height: 1.45;
      font-weight: 750;
    }}
    .upload-status {{
      display: grid;
      gap: 10px;
      color: var(--muted);
      font-weight: 750;
    }}
    .upload-status p {{
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .status-steps {{
      display: grid;
      gap: 8px;
      margin-top: 2px;
    }}
    .status-step {{
      display: flex;
      align-items: center;
      gap: 9px;
      color: var(--muted);
      font-size: 0.94rem;
      line-height: 1.35;
    }}
    .step-mark {{
      width: 20px;
      height: 20px;
      flex: 0 0 20px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: #fff;
      font-size: 0.78rem;
      font-weight: 900;
    }}
    .status-step.active {{
      color: var(--ink);
    }}
    .status-step.active .step-mark {{
      border-color: var(--accent);
      background: #e4f1ed;
    }}
    .status-step.active .step-mark::before {{
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--accent);
    }}
    .status-step.done {{
      color: var(--accent-dark);
    }}
    .status-step.done .step-mark {{
      border-color: var(--accent);
      background: var(--accent);
    }}
    .status-step.done .step-mark::before {{
      content: "✓";
    }}
    input:focus,
    select:focus,
    button:focus,
    a:focus {{
      outline: 3px solid rgba(45, 128, 106, 0.24);
      outline-offset: 2px;
    }}
    button,
    .button {{
      min-height: 50px;
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: white;
      font: inherit;
      font-weight: 850;
      cursor: pointer;
      padding: 13px 18px;
      text-decoration: none;
      text-align: center;
    }}
    button:hover,
    .button:hover {{
      background: var(--accent-dark);
    }}
    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 24px;
    }}
    .secondary {{
      min-height: 50px;
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--ink);
      background: #fff;
      font-weight: 850;
      padding: 13px 18px;
      text-decoration: none;
    }}
    .privacy-note,
    .cleanup-note {{
      margin: 16px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 0;
    }}
    .stats div {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }}
    dt {{
      color: var(--muted);
      font-weight: 800;
      font-size: 0.78rem;
      margin-bottom: 7px;
      text-transform: uppercase;
    }}
    dd {{
      margin: 0;
      font-size: 1.08rem;
      font-weight: 850;
      overflow-wrap: anywhere;
    }}
    .positive {{ color: var(--accent-dark); }}
    .negative {{ color: var(--bad); }}
    .impact {{
      margin-top: 24px;
      padding-top: 20px;
      border-top: 1px solid var(--line);
    }}
    .impact-list {{
      display: grid;
      gap: 10px;
      margin: 0;
    }}
    .impact-list div {{
      display: grid;
      gap: 4px;
      padding-bottom: 10px;
      border-bottom: 1px solid #edf0ea;
    }}
    .impact-list div:last-child {{
      border-bottom: 0;
      padding-bottom: 0;
    }}
    .impact-list dd {{
      font-size: 0.98rem;
      font-weight: 650;
      line-height: 1.45;
      color: var(--ink);
    }}
    .progress-shell {{
      width: 100%;
      height: 16px;
      overflow: hidden;
      border: 1px solid #bfd0c7;
      border-radius: 999px;
      background: #edf1ec;
    }}
    .progress-meter {{
      min-width: 8px;
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
      transition: width 240ms ease;
    }}
    .progress-meta {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 0.92rem;
      font-weight: 750;
    }}
    .progress-message {{
      min-height: 1.5em;
      margin: 18px 0 0;
      color: var(--ink);
      font-size: 1.06rem;
      font-weight: 800;
      overflow-wrap: anywhere;
    }}
    .error {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      border: 1px solid #efc8c3;
      border-radius: 8px;
      background: #fff7f5;
      color: var(--bad);
      padding: 16px;
      font: 0.95rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    .hidden {{ display: none !important; }}
    @media (max-width: 560px) {{
      .shell {{ width: min(100vw - 20px, 680px); padding: 18px 0; }}
      .panel-heading {{ flex-direction: column; }}
      .form-grid {{ grid-template-columns: 1fr; }}
      .stats {{ grid-template-columns: 1fr; }}
      .actions > * {{ width: 100%; justify-content: center; }}
      .progress-meta {{ flex-direction: column; gap: 6px; }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _delete_job_files(job: dict[str, object], *, remove_output: bool = True) -> None:
    for key in ("input_path", "output_path"):
        raw_path = str(job.get(key, "") or "")
        if raw_path:
            _delete_if_present(Path(raw_path))

    if remove_output:
        raw_path = str(job.get("path", "") or "")
        if raw_path:
            _delete_if_present(Path(raw_path))


def _delete_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
