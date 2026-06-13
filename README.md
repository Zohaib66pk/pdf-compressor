# PDF Compressor

A Python PDF compressor with a browser UI, command-line interface, and Vercel serverless entrypoint. The app accepts PDFs up to 100 MB. The local app shows live progress while it works toward the required target size, then removes uploaded and generated files after the result is handled.

## Install system tools

PDF compression requires Ghostscript and Poppler:

```bash
brew install ghostscript
brew install poppler
```

Other platforms:

```bash
sudo apt install ghostscript poppler-utils
sudo dnf install ghostscript poppler-utils
winget install ArtifexSoftware.Ghostscript
choco install poppler
```

Verify Poppler is on PATH:

```bash
pdftoppm -v
```

## Install Python packages

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## Run the web interface

```bash
.venv/bin/python app.py
```

Then open:

```text
http://127.0.0.1:8765
```

## Compress from the command line

```bash
.venv/bin/python app.py input.pdf --profile max
```

Choose an output path:

```bash
.venv/bin/python app.py input.pdf --profile max --output compressed.pdf
```

For password-protected PDFs:

```bash
.venv/bin/python app.py input.pdf --profile max --password "your-password"
```

The compressor tries one target-aware embedded JPEG2000 image recompression pass first because it keeps page text, links, and dimensions intact. If the requested target still cannot be met, it falls back to Ghostscript and then raster page compression.

Raster compression uses 3 parallel workers by default and reports compressed page counts while it runs. Advanced CLI override:

```bash
.venv/bin/python app.py input.pdf --profile max --workers 4
```

## Deploy to Vercel

This repo includes:

- `index.py`: Vercel ASGI entrypoint.
- `api/blob-upload.js`: short-lived Vercel Blob upload-token endpoint for browser uploads.
- `public/blob-upload-client.js`: bundled browser upload helper built from `assets/blob-upload-client.js`.
- `vercel.json`: Vercel project configuration.
- `requirements.txt`: Python dependencies for Vercel installs.
- `package.json`: Vercel Blob client upload dependency and build script.
- `.vercelignore`: excludes local caches, tests, and generated PDFs from the deployment bundle.

Deploy:

```bash
npx vercel
```

Production deploy:

```bash
npx vercel --prod
```

The Vercel handler uses Vercel Blob when `BLOB_READ_WRITE_TOKEN` is configured. The browser uploads the PDF directly to Blob, the Python function downloads it from Blob for compression, then the original Blob file is deleted. The compressed PDF is uploaded back to Blob for download and is deleted shortly after download starts.

The app's upload limit is 100 MB. Standard Vercel Functions have a much smaller request and response payload limit, so direct uploads fall back to a guarded small-file path if Blob storage is not configured.

For best compression on strict targets, run the local server or deploy to an environment where Ghostscript and Poppler are installed. Standard Vercel Python Functions do not include those system binaries by default.

## Profiles

```bash
.venv/bin/python app.py --list-profiles
```

- `max`: smallest possible files; may flatten pages to low-resolution JPEG images.
- `screen`: very small files for screen viewing.
- `ebook`: balanced compression for readable documents.
- `printer`: moderate compression for print-friendly quality.
- `lossless`: stream cleanup without intentional image downsampling.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
```
