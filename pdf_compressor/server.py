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
import uuid
from urllib.parse import parse_qs, urlparse

from .core import CompressionError, PROFILES, compress_pdf, format_bytes


MAX_UPLOAD_BYTES = 300 * 1024 * 1024


class CompressorRequestHandler(BaseHTTPRequestHandler):
    server_version = "PDFCompressor/0.1"
    jobs: dict[str, dict[str, object]] = {}
    job_lock = threading.Lock()
    workdir: Path | None = None

    def do_GET(self) -> None:
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

            if self.workdir is None:
                raise CompressionError("Server storage is not available.")

            job_id = uuid.uuid4().hex
            safe_name = _safe_filename(upload["filename"])
            input_path = self.workdir / f"{job_id}-{safe_name}"
            output_path = self.workdir / f"{job_id}-compressed.pdf"
            input_path.write_bytes(upload["data"])

            with self.job_lock:
                self.jobs[job_id] = {
                    "id": job_id,
                    "status": "queued",
                    "progress": 3,
                    "message": "Upload received",
                    "input_path": input_path,
                    "output_path": output_path,
                    "safe_name": safe_name,
                    "profile_name": profile_name,
                    "target_size_bytes": target_size_bytes,
                }

            thread = threading.Thread(target=_compress_job, args=(job_id,), daemon=True)
            thread.start()

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/progress?id={job_id}")
            self.end_headers()
        except CompressionError as exc:
            self._send_html(render_error(str(exc)), HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

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
            self._send_html(render_error(str(job.get("message", "Compression failed."))), HTTPStatus.BAD_REQUEST)
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
            self.send_error(HTTPStatus.GONE, "Compressed file expired")
            return

        data = output_path.read_bytes()
        filename = str(job["filename"])
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

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
                upload = {"filename": filename, "data": data}
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
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    with tempfile.TemporaryDirectory(prefix="pdf-compressor-") as tmp:
        CompressorRequestHandler.workdir = Path(tmp)
        server = ThreadingHTTPServer((host, port), CompressorRequestHandler)
        print(f"PDF Compressor is running at http://{host}:{port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            server.server_close()


def _compress_job(job_id: str) -> None:
    job = CompressorRequestHandler.get_job(job_id)
    if not job:
        return

    input_path = Path(str(job["input_path"]))
    output_path = Path(str(job["output_path"]))
    safe_name = str(job["safe_name"])
    profile_name = str(job["profile_name"])
    target_size_bytes = int(job["target_size_bytes"])

    def report(progress: int, message: str) -> None:
        CompressorRequestHandler.update_job(
            job_id,
            status="running",
            progress=progress,
            message=message,
        )

    try:
        report(5, "Preparing compression")
        result = compress_pdf(
            input_path,
            output_path,
            profile_name=profile_name,
            target_size_bytes=target_size_bytes,
            progress_callback=report,
        )
        download_name = f"{Path(safe_name).stem}.{profile_name}.compressed.pdf"
        CompressorRequestHandler.update_job(
            job_id,
            status="complete",
            progress=100,
            message="Compression complete",
            path=result.output_path,
            filename=download_name,
            profile=result.profile.label,
            method=result.method,
            original_size=result.original_size,
            compressed_size=result.compressed_size,
            savings_percent=result.savings_percent,
            bytes_saved=result.bytes_saved,
        )
    except CompressionError as exc:
        CompressorRequestHandler.update_job(
            job_id,
            status="error",
            progress=100,
            message=str(exc),
        )
    finally:
        try:
            input_path.unlink()
        except FileNotFoundError:
            pass


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


def render_home() -> str:
    options = "\n".join(
        f'<option value="{escape(profile.name)}">{escape(profile.label)}</option>'
        for profile in PROFILES.values()
    )
    return _page(
        "PDF Compressor",
        f"""
        <main class="shell">
          <section class="tool-panel">
            <div class="title-row">
              <h1>PDF Compressor</h1>
              <span class="status">Local</span>
            </div>
            <form action="/compress" method="post" enctype="multipart/form-data">
              <label>
                <span>Input PDF</span>
                <input type="file" name="pdf" accept="application/pdf,.pdf" required>
              </label>
              <label>
                <span>Compression profile</span>
                <select name="profile">{options}</select>
              </label>
              <label>
                <span>Required output size (MB)</span>
                <input type="number" name="target_size_mb" min="0.01" step="0.01" placeholder="5" required>
              </label>
              <button type="submit">Compress PDF</button>
            </form>
          </section>
        </main>
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
            <div class="title-row">
              <h1>Compressing PDF</h1>
              <span class="status" id="statusLabel">Working</span>
            </div>
            <div class="progress-shell" aria-label="Compression progress">
              <div class="progress-meter" id="progressMeter" style="width: {progress}%"></div>
            </div>
            <div class="progress-meta">
              <strong id="progressValue">{progress}%</strong>
              <span>Target: {escape(target_size)}</span>
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
    return _page(
        "Compression Complete",
        f"""
        <main class="shell">
          <section class="tool-panel">
            <div class="title-row">
              <h1>Compression Complete</h1>
              <span class="status">Ready</span>
            </div>
            <dl class="stats">
              <div><dt>Profile</dt><dd>{escape(str(job["profile"]))}</dd></div>
              <div><dt>Method</dt><dd>{escape(str(job["method"]))}</dd></div>
              <div><dt>Original</dt><dd>{format_bytes(int(job["original_size"]))}</dd></div>
              <div><dt>Output</dt><dd>{format_bytes(int(job["compressed_size"]))}</dd></div>
              <div><dt>Target</dt><dd>{format_bytes(target_size)}</dd></div>
              <div><dt>Savings</dt><dd class="{saved_class}">{format_bytes(saved)} ({float(job["savings_percent"]):.1f}%)</dd></div>
            </dl>
            <div class="actions">
              <a class="button" href="/download?id={escape(str(job["id"]))}">Download PDF</a>
              <a class="secondary" href="/">Compress another</a>
            </div>
          </section>
        </main>
        """,
    )


def render_error(message: str) -> str:
    return _page(
        "Compression Error",
        f"""
        <main class="shell">
          <section class="tool-panel">
            <div class="title-row">
              <h1>Compression Error</h1>
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
      --ink: #17201c;
      --muted: #596861;
      --paper: #f6f5ef;
      --panel: #ffffff;
      --line: #d8ddd5;
      --accent: #267466;
      --accent-dark: #1c5b50;
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
      width: min(760px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 48px 0;
    }}
    .tool-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: clamp(20px, 4vw, 34px);
      box-shadow: 0 18px 45px rgba(23, 32, 28, 0.08);
    }}
    .title-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 28px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.8rem, 4vw, 3rem);
      line-height: 1;
      letter-spacing: 0;
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 0 12px;
      border-radius: 999px;
      background: #e5f1ed;
      color: var(--accent-dark);
      font-weight: 700;
      font-size: 0.9rem;
      white-space: nowrap;
    }}
    .status.warning {{
      background: #f8e7d5;
      color: var(--warn);
    }}
    form {{
      display: grid;
      gap: 20px;
    }}
    label {{
      display: grid;
      gap: 8px;
      color: var(--muted);
      font-size: 0.95rem;
      font-weight: 700;
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
      font-weight: 600;
      padding: 10px 12px;
    }}
    input:focus,
    select:focus,
    button:focus,
    a:focus {{
      outline: 3px solid rgba(38, 116, 102, 0.28);
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
      font-weight: 800;
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
      font-weight: 800;
      padding: 13px 18px;
      text-decoration: none;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin: 0;
    }}
    .stats div {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }}
    dt {{
      color: var(--muted);
      font-weight: 800;
      font-size: 0.82rem;
      margin-bottom: 8px;
      text-transform: uppercase;
    }}
    dd {{
      margin: 0;
      font-size: 1.25rem;
      font-weight: 850;
      overflow-wrap: anywhere;
    }}
    .positive {{ color: var(--accent-dark); }}
    .negative {{ color: var(--bad); }}
    .progress-shell {{
      width: 100%;
      height: 18px;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #edf0ea;
    }}
    .progress-meter {{
      min-width: 8px;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), #4b9a6d);
      transition: width 240ms ease;
    }}
    .progress-meta {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 0.95rem;
      font-weight: 800;
    }}
    .progress-message {{
      min-height: 1.5em;
      margin: 18px 0 0;
      color: var(--ink);
      font-weight: 750;
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
      .shell {{ width: min(100vw - 20px, 760px); padding: 18px 0; }}
      .title-row {{ align-items: flex-start; flex-direction: column; }}
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


def _safe_filename(filename: object) -> str:
    safe = Path(str(filename)).name.strip() or "uploaded.pdf"
    return safe if safe.lower().endswith(".pdf") else f"{safe}.pdf"
