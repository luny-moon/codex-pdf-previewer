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
   Downloads. `--codex-home` selects a non-default profile when needed.
4. Check the result. Ask the user to refresh or restart Codex if the plugin is
   not visible in a new chat. Do not open a sample document during installation.

Opening PDFs is a separate user action. The installed `open-codex-pdf` skill
handles attached files, local paths and requests such as “打开这个 PDF”. It
must display the reader through Codex's `open_in_codex` browser capability.
Do not register a system PDF handler or launch a system browser.
