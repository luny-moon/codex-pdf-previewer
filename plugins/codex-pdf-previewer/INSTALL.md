# Installation for Codex

Use these instructions when the user asks you to install this plugin from its
GitHub page or a downloaded ZIP. Inspect the manifest and `install.py` first.

1. For a ZIP, extract its single plugin folder. For a repository URL, obtain the
   repository using the user's existing access and locate
   `plugins/codex-pdf-previewer/`. The package root contains `install.py` and
   `plugin.json`. A private repository requires an account with access.
2. Find Python 3.10+ and the Codex CLI. Use the desktop app's bundled CLI if it
   is not on PATH; pass its absolute path with `--codex`. Report a missing
   prerequisite instead of claiming installation succeeded.
3. Run `<python> <package-root>/install.py`. The installer copies the package
   to the user's Codex profile, registers a local marketplace, and installs the
   plugin using the CLI. It does not depend on the extracted ZIP remaining in
   Downloads. On Linux it also adds a PDF menu option when a GIO desktop and
   the Codex GUI launcher are available, keeping the current default PDF reader.
   `--codex-home` selects a non-default profile when needed.
4. Check `installed` and `pdf_menu` in the result. Menu setup can be skipped
   without preventing plugin installation. Ask the user to refresh or restart
   Codex if the plugin is not visible in a new chat. Do not open a sample
   document during installation.

On Linux, the user can open a PDF in Codex and choose
**Open in → 用高清 PDF 插件打开**. This adds an HD reader tab and preserves the
original PDF preview. A newly opened PDF avoids an old cached menu. Multiple
Codex windows use the most recently active main window.

If the GUI launcher is not detected, rerun installation with
`--gui-launcher <absolute-GUI-launcher-path>`; this is separate from the Codex CLI.
`--no-menu` installs only the reader. macOS and Windows use the chat opening flow.

Opening PDFs is a separate user action. The installed `open-codex-pdf` skill
handles attached files, local paths and requests such as “打开这个 PDF”. It
must display the reader through Codex's `open_in_codex` browser capability.
The Linux menu uses Codex's existing browser deep link; it does not modify the
client or make the plugin the default PDF reader. Never launch a system browser.
