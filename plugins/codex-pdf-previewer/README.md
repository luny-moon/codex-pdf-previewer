# codex-pdf-previewer

Are you tired of blurry PDF previews in Codex, especially on a large monitor?
This local plugin renders PDF text, equations and lines with independent
1x/2x/3x canvas sampling. It supports continuous scrolling, text selection,
page navigation, fit-width and manual refresh.

In a new Codex desktop chat, use `$open-codex-pdf` and give a local PDF path.
The default is 150% zoom with 3x sampling. Files are read on your computer;
no PDF is uploaded or modified. Python 3.10+ is required, and PDF.js is bundled.

## Standalone commands

macOS / Linux:

```bash
python3 scripts/preview.py open "/path/to/document.pdf"
```

Windows:

```powershell
py -3 scripts/preview.py open "C:\Documents\sample.pdf"
```

On Windows, `python` also works when it is Python 3.10+. The system ZIPs
include a matching `open-pdf.command`, `open-pdf.cmd` or `open-pdf.sh` helper.
The command prints a local URL; open it in your browser. It does not open a
browser window automatically. Click **刷新** after updating your PDF.

Use `status`, `stop <pdf-path>` or `stop --all` with the same script to manage
sessions. Session records stay in the operating system's user-data directory
under `codex-pdf-previewer`. They contain local paths, logs and a shutdown token;
do not distribute them. `--state-dir` overrides that location.

Examples, downloads and installation:
https://github.com/luny-moon/codex-pdf-previewer

## License

Original code: MIT. See `LICENSE`. PDF.js and bundled fonts/decoders retain
licenses listed in `THIRD_PARTY.md` and `vendor/pdfjs/`.
