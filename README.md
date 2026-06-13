# PDF Compressor

A Python PDF compressor with a browser UI, command-line interface, and Vercel serverless entrypoint. The local app shows live progress while it works toward the required target size, then removes uploaded and generated files after the result is handled.

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

- `api/index.py`: Vercel Python Function entrypoint.
- `vercel.json`: routes all web traffic to the Python handler and sets a 300 second function limit.
- `requirements.txt`: Python dependencies for Vercel installs.
- `.vercelignore`: excludes local caches, tests, and generated PDFs from the deployment bundle.

Deploy:

```bash
npx vercel
```

Production deploy:

```bash
npx vercel --prod
```

The Vercel handler compresses during the upload request and returns the PDF directly. That keeps uploads, passwords, and generated files out of cross-request storage. The local server keeps the richer progress-page flow because it can safely hold short-lived in-memory job state.

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
