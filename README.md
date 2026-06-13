# PDF Compressor

A local Python PDF compressor with a command-line interface and a browser-based UI. It uses Ghostscript for real PDF optimization, including an aggressive **maximum possible compression** profile.

## Install Ghostscript

The Python app is dependency-free, but PDF compression requires Ghostscript:

```bash
brew install ghostscript
```

Other platforms:

```bash
sudo apt install ghostscript
sudo dnf install ghostscript
winget install ArtifexSoftware.Ghostscript
```

## Run the web interface

```bash
python3 app.py
```

Then open:

```text
http://127.0.0.1:8765
```

## Compress from the command line

```bash
python3 app.py input.pdf --profile max
```

Choose an output path:

```bash
python3 app.py input.pdf --profile max --output compressed.pdf
```

## Profiles

```bash
python3 app.py --list-profiles
```

- `max`: smallest possible files; may flatten pages to low-resolution JPEG images.
- `screen`: very small files for screen viewing.
- `ebook`: balanced compression for readable documents.
- `printer`: moderate compression for print-friendly quality.
- `lossless`: stream cleanup without intentional image downsampling.

## Tests

```bash
python3 -m unittest discover -s tests
```
