# HD PDF Preview / 高清 PDF 预览

A Codex desktop plugin for local PDFs with continuous scrolling, selectable
text, and high-resolution canvas sampling independent of application UI zoom.

- 150% zoom and 3x sampling by default; fit-width and 1x/2x/3x controls.
- Page navigation, text copying, refresh and original-PDF download.
- Nearby-page rendering with canvas memory limits.
- One reusable session per document; separate loopback ports for different files.
- Python standard library only; PDF.js 5.6.205 is bundled.

## Install in Codex

With a current Codex CLI installed:

```text
codex plugin marketplace add luny-moon/hd-pdf-preview
codex plugin add hd-pdf-preview@hd-pdf-preview-plugins
```

Start a new Codex desktop chat and ask:

> Use HD PDF Preview to open my local PDF at this path: …

Or invoke `$open-hd-pdf`. The skill resolves its installed package, starts
the reader, and displays the returned URL in the built-in browser. A matching
open reader can be reused. Plugin availability depends on your Codex version;
the launcher also works standalone. See the [official packaging guide](https://developers.openai.com/plugins/build/plugins).

## Platforms and standalone use

Requires **Python 3.10+** and a modern desktop browser. CI runs the launcher
lifecycle tests and actual Chromium rendering on **macOS, Windows and Linux**,
including filenames with spaces and non-ASCII characters. Python 3.13 is also
tested on Linux. These checks cover the Python server and browser reader;
they do not automate the Codex desktop app itself.

Clone the repository and run from its root:

macOS / Linux:

```bash
python3 plugins/hd-pdf-preview/scripts/preview.py open "/path/to/document.pdf"
```

Windows PowerShell:

```powershell
py -3 plugins/hd-pdf-preview/scripts/preview.py open "C:\Documents\sample.pdf"
```

`python` is also suitable on Windows if it points to Python 3.10 or newer.
Open the JSON result's `url` in a browser. The command itself does not open a
browser window. Use the same interpreter and script with `status` or
`stop <pdf-path>` to manage sessions. `stop --all` ends all plugin-managed
sessions. After replacing a PDF, click **刷新** in the reader.

| System | Default session-data directory |
| --- | --- |
| macOS | `~/Library/Application Support/codex-hd-pdf-preview` |
| Windows | `%LOCALAPPDATA%\codex-hd-pdf-preview` |
| Linux | `$XDG_STATE_HOME/codex-hd-pdf-preview`, default `~/.local/state/codex-hd-pdf-preview` |

`--state-dir <directory>` overrides the location. Records contain local file
paths, process metadata and a shutdown token; logs also stay in this directory.
Keep this data private. POSIX permissions apply on macOS/Linux; Windows uses
the directory's inherited user ACLs. No systemd service or native binary is required.

## Privacy

The package contains code, instructions and runtime resources. **No user PDF,
TeX source, document screenshot, session record or log is included.** Tests
generate a small synthetic PDF in a temporary directory.

The server binds only to `127.0.0.1` and provides the selected PDF plus an
allowlist of packaged assets. It does not expose directory browsing or a
general file API. PDF bytes are not uploaded, PDF JavaScript is not executed,
and the reader has no telemetry. Other processes on the same computer can
access a running loopback reader; stop it when finished with a sensitive
document. Shutdown requires the per-session token stored in local state.

Release packaging uses a fixed file allowlist and audits the ZIP. Generated
documents, screenshots, session data and developer test artifacts are excluded.

## Development

```text
python -m unittest discover -s tests -v
python scripts/build_release.py --out-dir build
```

Optional browser verification:

```text
python -m pip install playwright
python -m playwright install chromium
python tests/browser_smoke.py
```

The release ZIP contains the installable `hd-pdf-preview/` folder. The source
repository additionally contains the marketplace catalog and CI tests.

## 中文说明

在 Codex 桌面版中安装后，可以说：“用高清 PDF 预览打开这个本地 PDF”，
并附上文件路径。默认 150% 缩放与 3 倍采样，支持连续滚动、页码跳转、
文字复制和刷新。支持 macOS、Windows、Linux 的 Python 3.10+ 环境。
Windows 使用 `py -3` 或 `python`，macOS/Linux 通常使用 `python3`。
文件仅在本机读取，发布包不包含用户论文、截图、个人路径或运行记录。

## License

Original code: [MIT](LICENSE). Bundled PDF.js is Apache-2.0; font and decoder
notices are preserved. See [third-party notices](plugins/hd-pdf-preview/THIRD_PARTY.md).
