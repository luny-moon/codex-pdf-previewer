#!/usr/bin/env python3
"""Open PDFs in the local reader using the system browser."""
import argparse
import json
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', nargs='+', type=Path)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--print-url', action='store_true', help='Prepare the reader without opening a browser')
    args = parser.parse_args()
    launcher = Path(__file__).resolve().with_name('preview.py')
    for document in args.pdf:
        command = [sys.executable, str(launcher), 'open', str(document)]
        if args.state_dir:
            command.extend(['--state-dir', str(args.state_dir)])
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            print(result.stderr.strip(), file=sys.stderr)
            return result.returncode
        url = json.loads(result.stdout)['url']
        parts = urlsplit(url)
        if parts.scheme != 'http' or parts.hostname != '127.0.0.1':
            raise RuntimeError('Expected a local reader URL')
        print(url, flush=True)
        if not args.print_url and not webbrowser.open(url, new=2):
            print('Open the printed URL in your browser.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
