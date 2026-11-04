# HD PDF Preview / 高清 PDF 预览

A local PDF reader for Codex desktop: continuous scrolling, selectable text,
page navigation, fit-width, 100–300% zoom and independent 1x/2x/3x sampling.
Defaults: 150% zoom and 3x sampling. Python 3.10+ and a modern browser are
required; PDF.js is bundled.

Use the installed `open-hd-pdf` skill, or run from this package directory:

```bash
python3 scripts/preview.py open "/path/to/document.pdf"
python3 scripts/preview.py status
python3 scripts/preview.py stop "/path/to/document.pdf"
```

On Windows replace `python3` with `py -3` or `python` (3.10+). Quote paths
with spaces. The launcher prints a loopback URL and does not open a window.
Click **刷新** after replacing a PDF. No document is uploaded or modified.

Session data is stored outside the plugin in the operating system's user-data
directory. It contains local paths, process metadata, logs and a stop token;
do not distribute it. `--state-dir` overrides its location.

Full installation and platform instructions:
https://github.com/luny-moon/hd-pdf-preview

Original code: MIT. Third-party notices: `THIRD_PARTY.md` and `vendor/pdfjs/`.
