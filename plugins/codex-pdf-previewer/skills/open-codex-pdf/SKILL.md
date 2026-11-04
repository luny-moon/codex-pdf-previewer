---
name: open-codex-pdf
description: Open attached or local PDFs in Codex's built-in high-resolution reader. Use when users ask to open or preview a PDF, including “打开这个 PDF” and “预览 PDF”, unless they choose another viewer. Do not invoke just to extract text, edit a PDF, or compile TeX.
---

Open the PDF inside Codex. The user does not need a command, a localhost URL,
or an external application.

1. Resolve the PDF from the current attachment or explicit path first. If the
   user refers to the current project's PDF, use its existing output (normally
   `build/main.pdf`). Ask only when the document is genuinely ambiguous. Do not
   compile or edit a manuscript merely to open it.
2. Resolve `../../scripts/preview.py` relative to this installed SKILL.md.
   Find Python 3.10+ (`python3`, or `py -3` / `python` on Windows). Run
   `<python> <plugin-root>/scripts/preview.py open <absolute-pdf-path>` with
   correctly quoted arguments. Read the JSON result's `url`.
3. Discover and call the available `open_in_codex` tool with
   `target: {type: "browser", url: <returned-url>}`, normally `placement: "right"`.
   Open the actual reader URL, not the PDF file through the default file preview.
   Do not stop after printing a link. Never launch a system browser through
   `webbrowser`, OS commands (`open`, `start`, `xdg-open`), or file associations. If the
   host has no Codex browser capability, explain that this host cannot display
   the preview rather than launching another application.

Reuse an existing reader tab for the same document. The launcher reuses live
sessions automatically; `--reuse-url <current-reader-url>` can also adopt an
existing reader after checking its PDF bytes. Do not assume a fixed port.
Before reusing a tab, check its displayed filename and
`document.body.dataset.sourceKind` if browser inspection is available. A tab
with source kind `file` may display a browser-picked PDF different from its
server document. Preserve that view unless the user requested replacing it.
Avoid duplicate tabs, reloading a reader merely to focus it, and changes to
Codex's global UI scale.

Inside the reader, **打开 PDF** and drag/drop switch files in the same Codex
tab. Browser-picked files stay local; **重新选择** rereads a changed disk file.
For server-selected files, **刷新** rereads the original path. Full-tab reload
returns to that original path. Keep existing zoom and sampling preferences.

`preview.py status` lists this plugin's sessions. Use `stop <absolute-pdf-path>`
or `stop --all` only when requested. Do not stop unrelated services to free a
port. Session records and logs stay in the user's state directory, outside
the document's project. PDF.js is bundled; no PDF upload or API key is needed.
