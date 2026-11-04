---
name: open-codex-pdf
description: Open or manage a local high-resolution PDF reader in Codex desktop, with continuous scrolling, selectable text and independent 1–3x sampling. Use for requests to open a PDF in 高清预览 or reuse this reader; not for editing PDF contents or compiling TeX.
---

Use the bundled reader and Python launcher. Resolve the launcher as `../../scripts/preview.py` relative to this SKILL.md, using its actual installed path rather than a remembered home directory.

Find Python 3.10 or newer: normally `python3` on macOS/Linux; on Windows use `py -3` or `python` after checking its version. Use that interpreter for the commands below, quoting paths with spaces. Do not assume a POSIX shell or a particular home-directory layout.

1. Resolve the requested PDF. For the current LaTeX project, prefer its existing `build/main.pdf` when the user did not specify another document. Do not compile or edit the manuscript merely to open a preview.
2. Run `<python> <plugin-root>/scripts/preview.py open <absolute-pdf-path>`. The command prints JSON with `url`, `reused`, and `managed`. No browser is opened by this command. A previous managed session for that document is reused; different documents get separate loopback ports. If the current chat already has a local reader URL, pass `--reuse-url <that-url>`; this reuses it only after comparing its PDF bytes with the requested file. Obtain that URL from the current chat or browser; do not assume a fixed port.
3. Show the returned URL in Codex's built-in browser using the available `open_in_codex` browser capability when the user requests opening the document. If that same reader is already open, preserve its tab; report the existing URL or use its Refresh button after recompilation. Avoid duplicate tabs, closing/reopening the reader, and changes to the app's global UI scale. If no browser-opening tool exists, provide a clickable loopback link.

The visual defaults are 150% zoom and 3x sampling, with 1x/2x/3x and fit-width controls. Existing browser preferences take precedence. Click **刷新** to reread a recompiled PDF.

`<python> <plugin-root>/scripts/preview.py status` lists only this plugin's managed sessions. `stop <absolute-pdf-path>` stops the matching plugin-managed session, and `stop --all` stops all plugin-managed sessions only when requested. External readers reused through `--reuse-url` are not managed or stopped by this plugin. Do not stop an unrelated service to free a port; the launcher chooses a free port.

Python 3.10+ and a modern desktop browser are required. PDF.js is bundled; no npm install, remote service, API key, application patch, or upload is needed. Read only the selected PDF and packaged assets. Session metadata/logs live under the user's state directory (or `--state-dir` when explicitly supplied), never alongside the manuscript. A session ends when explicitly stopped or when its process exits; `open` restarts a dead session safely.
