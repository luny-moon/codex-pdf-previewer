#!/usr/bin/env python3
"""Open a native PDF menu selection in the existing Codex desktop client."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def checked_document(value):
    document = Path(value).expanduser()
    if not document.is_absolute():
        raise ValueError('Select an absolute local PDF path')
    document = document.resolve(strict=True)
    if not document.is_file() or document.suffix.lower() != '.pdf':
        raise ValueError('Select an existing PDF file')
    return document


def checked_url(value):
    if not isinstance(value, str):
        raise ValueError('The reader did not return a URL')
    url = urlsplit(value)
    if (url.scheme != 'http' or url.hostname != '127.0.0.1'
            or not url.port or url.path != '/' or url.username is not None
            or url.password is not None or url.query or url.fragment):
        raise ValueError('The reader returned an unexpected URL')
    return value


def open_document(pdf, launcher, state_dir=None, prepare_only=False):
    document = checked_document(pdf)
    gui = Path(launcher).expanduser()
    if not gui.is_absolute():
        raise ValueError('The Codex GUI launcher must be an absolute path')
    gui = gui.resolve(strict=True)
    if not gui.is_file() or not os.access(gui, os.X_OK):
        raise ValueError('The Codex GUI launcher is not executable')
    command = [sys.executable, str(ROOT / 'scripts/preview.py'), 'open', str(document)]
    if state_dir is not None:
        command.extend(['--state-dir', str(Path(state_dir).expanduser().resolve())])
    prepared = subprocess.run(command, check=True, capture_output=True, text=True,
                              encoding='utf-8', timeout=20)
    reader = json.loads(prepared.stdout)
    if not isinstance(reader, dict):
        raise ValueError('The reader returned an invalid result')
    if not isinstance(reader.get('pdf'), str) or Path(reader['pdf']).resolve() != document:
        raise ValueError('The reader opened a different document')
    url = checked_url(reader.get('url'))
    deep_link = 'codex://browser?' + urlencode({'url': url})
    if not prepare_only:
        # Pass the existing client's public browser link directly to its GUI
        # launcher. No system browser, shell, private IPC or client patch.
        process = subprocess.Popen([str(gui), deep_link], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   close_fds=True, start_new_session=True)
        try:
            code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            code = 0  # A newly started GUI may continue running; leave it alive.
        if code:
            raise RuntimeError('Codex could not accept the PDF preview link')
    return {'url': url, 'pdf': str(document), 'submitted_to_codex': not prepare_only}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf')
    parser.add_argument('--launcher', required=True, help='Absolute Codex GUI launcher path')
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--prepare-only', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        result = open_document(args.pdf, args.launcher, args.state_dir, args.prepare_only)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(json.dumps({'error': 'Could not open the selected PDF inside Codex.'}),
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
