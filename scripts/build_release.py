#!/usr/bin/env python3
"""Build and audit a document-free plugin ZIP using a fixed path allowlist."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/codex-pdf-previewer'
FILES = {
    'plugin.json', '.codex-plugin/plugin.json', 'README.md', 'INSTALL.md', 'install.py',
    'LICENSE', 'THIRD_PARTY.md', 'scripts/preview.py', 'skills/open-codex-pdf/SKILL.md',
    'scripts/menu_open.py', 'scripts/linux_menu.py',
    'skills/open-codex-pdf/agents/openai.yaml',
    'assets/reader/index.html', 'assets/reader/entry.js',
    'assets/reader/reader.js', 'assets/reader/reader.css',
    'vendor/pdfjs/LICENSE', 'vendor/pdfjs/package.json',
    'vendor/pdfjs/build/pdf.mjs', 'vendor/pdfjs/build/pdf.worker.mjs',
    'vendor/pdfjs/web/pdf_viewer.css',
}
VENDOR_TREES = ('vendor/pdfjs/cmaps/', 'vendor/pdfjs/standard_fonts/',
                'vendor/pdfjs/wasm/', 'vendor/pdfjs/web/images/')
FORBIDDEN_SUFFIXES = {'.pdf', '.tex', '.log', '.db', '.sqlite', '.pyc', '.map'}
SECRET = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')
HOME = re.compile(rb'(?:/home/(?!web_user(?:/|\b))[^\s\x00\"\x27<>]+|/Users/[^\s\x00\"\x27<>]+|[A-Za-z]:[\\/]+Users[\\/]+[^\s\x00\"\x27<>]+)')


def audit_payload(name, data):
    path = Path(name)
    if path.is_absolute() or '\\' in name or '..' in path.parts:
        raise ValueError(f'Unsafe archive path: {name}')
    if name not in FILES and not name.startswith(VENDOR_TREES):
        raise ValueError(f'Unexpected package file: {name}')
    if path.suffix.lower() in FORBIDDEN_SUFFIXES or '__pycache__' in path.parts:
        raise ValueError(f'Generated or document file: {name}')
    if SECRET.search(data) or HOME.search(data):
        raise ValueError(f'Possible secret or private home path in {name}')


def build(out_dir):
    version = json.loads((PLUGIN / 'plugin.json').read_text(encoding='utf-8'))['version']
    selected = []
    for path in sorted(PLUGIN.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks are not allowed in release source')
        if not path.is_file():
            continue
        relative = path.relative_to(PLUGIN).as_posix()
        data = path.read_bytes()
        audit_payload(relative, data)
        selected.append((relative, data))
    missing = FILES - {name for name, _ in selected}
    if missing:
        raise ValueError(f'Missing package files: {sorted(missing)}')
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f'codex-pdf-previewer-{version}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
        for name, data in selected:
            info = zipfile.ZipInfo('codex-pdf-previewer/' + name)
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            stream.writestr(info, data, compresslevel=9)
    with zipfile.ZipFile(archive) as stream:
        if stream.testzip() is not None:
            raise ValueError('Corrupt ZIP')
        for name in stream.namelist():
            audit_payload(name.removeprefix('codex-pdf-previewer/'), stream.read(name))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out_dir / 'SHA256SUMS').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    return {'archive': str(archive), 'platform': 'universal', 'file_count': len(selected), 'sha256': digest,
            'documents_included': False, 'private_paths_or_tokens_detected': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'build')
    # Older CI calls this flag. All systems now share the same package.
    parser.add_argument('--all-platforms', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(json.dumps(build(args.out_dir), indent=2))
