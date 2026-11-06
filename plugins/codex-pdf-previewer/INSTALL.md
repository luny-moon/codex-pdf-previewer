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
   Downloads. On supported Linux desktops it registers a GIO PDF application;
   on macOS it creates and locally signs a helper in `~/Applications`. Both
   use the verified Codex GUI and keep the existing default PDF reader.
   `--codex-home` selects a non-default profile when needed.
4. Check `installed` and `pdf_menu` in the result. Menu setup can be skipped
   without preventing plugin installation. Ask the user to refresh or restart
   Codex if the plugin is not visible in a new chat. Do not open a sample
   document during installation.

On supported macOS and Linux clients, the user can open a PDF in Codex and choose
**Open in → 用高清 PDF 插件打开**. This adds an HD reader tab and preserves the
original PDF preview. A newly opened PDF avoids an old cached menu. Multiple
Codex windows use the most recently active main window.

If the GUI launcher is not detected, rerun installation with
`--gui-launcher <absolute-GUI-launcher-path>`; this is separate from the Codex CLI.
`--no-menu` installs only the reader. Windows uses the chat opening flow; the
current Windows Codex PDF menu filters out custom file handlers. A Windows
Explorer association does not add an item to this menu.

Opening PDFs is a separate user action. The installed `open-codex-pdf` skill
handles attached files, local paths and requests such as “打开这个 PDF”. It
must display the reader through Codex's `open_in_codex` browser capability.
The macOS and Linux menus use Codex's existing browser deep link. They do not
modify the client or make the plugin the default PDF reader. Never launch a
system browser.

On macOS, check `os_registered`, `viewer_discovered`, and
`pdf_default_unchanged` in `pdf_menu`. These confirm system registration;
`ui_verified: false` means the installer has not inspected Codex's interface.
Codex currently lists at most five native PDF applications, so system ordering
can affect whether the helper is visible. If the helper location is owned by
another profile or has user changes, setup leaves it intact and reports why.

The macOS helper has native operating-system tests. Its Codex menu behavior
is inferred from the inspected client route; acceptance in a real macOS Codex
window is still pending. Report that distinction when validating installation.
