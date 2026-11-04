"""Synthetic public-domain test data and isolated launcher helpers."""
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/hd-pdf-preview'
LAUNCHER = PLUGIN / 'scripts/preview.py'
HTTP = build_opener(ProxyHandler({}))


def sample_pdf(pages=5):
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for number in range(1, pages + 1):
        page_id = len(objects) + 1
        stream_id = page_id + 1
        kids.append(f'{page_id} 0 R')
        objects.append((f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
                        f'/Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>').encode('ascii'))
        content = (f'BT /F1 24 Tf 72 680 Td (HD PDF Preview - Sample page {number}) Tj '
                   '0 -48 Td /F1 14 Tf (Synthetic test document. No personal information.) Tj ET').encode('ascii')
        objects.append(f'<< /Length {len(content)} >>\nstream\n'.encode('ascii') + content + b'\nendstream')
    objects[1] = (f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {pages} >>').encode('ascii')
    result = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{number} 0 obj\n'.encode('ascii') + body + b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode('ascii'))
    for offset in offsets[1:]:
        result.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    result.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode('ascii'))
    return bytes(result)


def cli(state, *args, check=True):
    result = subprocess.run([sys.executable, str(LAUNCHER), *map(str, args), '--state-dir', str(state)],
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    if check:
        if result.returncode:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)
    return result


def get(url, **kwargs):
    with HTTP.open(Request(url, **kwargs), timeout=5) as response:
        return response.status, response.read(), dict(response.headers)
