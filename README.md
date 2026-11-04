# codex-pdf-previewer

**Are you tired of blurry PDF previews in Codex, especially on a large monitor?**

`codex-pdf-previewer` is a local plugin that gives you control over PDF rendering
resolution. It uses PDF.js with independent 1x, 2x and 3x canvas sampling, so you
can render vector text, equations and fine lines at a higher resolution without
changing the size of the whole Codex interface.

The reader opens beside your chat, with continuous scrolling, selectable text,
page navigation, fit-width and a refresh button. It runs on your computer and
reads your local PDF directly.

## See the difference

These two original, single-page PDFs were made for the examples. They contain
no personal manuscript material. For a fair comparison, use the same document,
page, zoom, window size and display scaling in both previews.

### Example 1: type, equations and small print

[Download the demonstration PDF](docs/demos/typography-demo.pdf)

This specimen contains 7-12 pt text, superscripts, subscripts and a small table.
Compare letter edges, indices and the smallest labels on your own display.

<table>
<tr><th>Codex default preview</th><th>codex-pdf-previewer</th></tr>
<tr>
<td><a href="docs/comparisons/typography-before.png"><img src="docs/comparisons/typography-before.png" alt="Default Codex preview of the typography demo, captured on a large display" width="560"></a></td>
<td><a href="docs/comparisons/typography-after.png"><img src="docs/comparisons/typography-after.png" alt="The same typography demo in codex-pdf-previewer, captured on a large display" width="560"></a></td>
</tr>
</table>

Real screenshots supplied from a large display. The original image pixels
are preserved; click either image to inspect the full-resolution capture.

### Example 2: fine lines and chart detail

[Download the demonstration PDF](docs/demos/vector-detail-demo.pdf)

This specimen contains vector curves, a dense grid, small axis labels and a
0.20-1.00 pt line-width ladder. Compare thin strokes and grid intersections.

<!-- Insert the user's real large-display before/after screenshots here. -->

Actual appearance depends on the source PDF, zoom and display scaling. The
comparisons use real screen captures; no simulated blur is used as a Codex
baseline. Higher sampling improves vector rendering, but cannot restore detail
that is missing from an already blurry scanned PDF.

## Download for your system

All downloads require **Python 3.10 or newer**. These are portable plugin ZIPs,
not native `.dmg` or `.exe` installers. Each system package includes its matching
launcher; the universal ZIP includes all three launchers.

| System | Download | Python command |
| --- | --- | --- |
| macOS | [Download for macOS](https://github.com/luny-moon/codex-pdf-previewer/releases/download/v1.2.0/codex-pdf-previewer-1.2.0-macos.zip) | `python3` |
| Windows | [Download for Windows](https://github.com/luny-moon/codex-pdf-previewer/releases/download/v1.2.0/codex-pdf-previewer-1.2.0-windows.zip) | `py -3` or `python` |
| Linux | [Download for Linux](https://github.com/luny-moon/codex-pdf-previewer/releases/download/v1.2.0/codex-pdf-previewer-1.2.0-linux.zip) | `python3` |

[Universal ZIP](https://github.com/luny-moon/codex-pdf-previewer/releases/download/v1.2.0/codex-pdf-previewer-1.2.0.zip)
· [SHA-256 checksums](https://github.com/luny-moon/codex-pdf-previewer/releases/download/v1.2.0/SHA256SUMS)
· [Release notes](https://github.com/luny-moon/codex-pdf-previewer/releases/tag/v1.2.0)

This repository is currently **private**. Sign in with an account that has
repository access to view the examples or download the release assets.

## Use it in Codex

With a current Codex CLI installed, add the marketplace and install the plugin:

```text
codex plugin marketplace add luny-moon/codex-pdf-previewer
codex plugin add codex-pdf-previewer@codex-pdf-previewer-marketplace
```

Start a new Codex desktop chat and say:

> Use codex-pdf-previewer to open this local PDF: /path/to/document.pdf

You can also invoke `$open-codex-pdf`. The plugin starts a local reader and
opens its URL in Codex's built-in browser. If that reader is already open,
it can reuse the same tab. The browser's own address and annotation toolbar
remain part of Codex.

Default settings are **150% zoom** and **3x sampling**. Change them independently
in the reader. After recompiling or replacing your PDF, click **刷新** to reread
it. The plugin does not compile TeX or modify your document.

## Use it on its own

Extract a downloaded ZIP and run from its `codex-pdf-previewer` directory.

macOS / Linux:

```bash
python3 scripts/preview.py open "/path/to/document.pdf"
```

Windows PowerShell:

```powershell
py -3 scripts/preview.py open "C:\Documents\sample.pdf"
```

Open the JSON result's `url` in a modern browser. The launcher prints the URL;
it does not open a browser window by itself. The platform ZIPs also include
`open-pdf.command`, `open-pdf.cmd` or `open-pdf.sh` for the same operation.

Use the same Python command and script with `status`, `stop <pdf-path>` or
`stop --all` to manage plugin-owned sessions. Different documents receive
separate loopback ports. Reopening the same document reuses a live session.

## Local files stay local

The reader listens only on `127.0.0.1`. It serves the selected PDF and packaged
assets, without a general file browser or upload service. It does not execute
PDF JavaScript or send telemetry. Other processes on your computer can access
a running local reader, so stop a session when finished with a sensitive file.

Session records and logs are kept outside the plugin:

| System | Default session-data directory |
| --- | --- |
| macOS | `~/Library/Application Support/codex-pdf-previewer` |
| Windows | `%LOCALAPPDATA%\codex-pdf-previewer` |
| Linux | `$XDG_STATE_HOME/codex-pdf-previewer`, default `~/.local/state/codex-pdf-previewer` |

These records contain local paths and a shutdown token; keep them private.
`--state-dir` overrides the location. Plugin ZIPs contain no user PDFs, source
manuscripts, screenshots, session records or logs. The two example PDFs live
separately in this repository's `docs/demos/` directory.

## Development

The runtime uses the Python standard library and bundled PDF.js. CI checks
service startup, Unicode paths, concurrent opens, archive contents and actual
Chromium rendering on macOS, Windows and Linux; it also tests Python 3.13 on Linux.

```text
python -m unittest discover -s tests -v
python scripts/build_release.py --out-dir build --all-platforms
```

For the browser checks, install Playwright and Chromium, then run
`python tests/browser_smoke.py`. To regenerate the original example documents,
install ReportLab and run `python scripts/create_demo_pdfs.py`; output goes to
`build/demo-pdfs/`.

## License

Original code and demonstration documents are available under the [MIT License](LICENSE).
Bundled PDF.js is Apache-2.0; its font and decoder licenses are retained in
[third-party notices](plugins/codex-pdf-previewer/THIRD_PARTY.md).
