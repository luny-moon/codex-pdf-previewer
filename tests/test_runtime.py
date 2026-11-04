import concurrent.futures
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from support import ROOT, PLUGIN, LAUNCHER, cli, get, sample_pdf

sys.dont_write_bytecode = True


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hd-pdf-test-')
        self.base = Path(self.temporary.name)
        self.state = self.base / 'session data'
        self.document = self.base / 'unicode 文档 with spaces.pdf'
        self.document.write_bytes(sample_pdf())

    def tearDown(self):
        cli(self.state, 'stop', '--all')
        self.temporary.cleanup()

    def reject(self, url, status, **kwargs):
        with self.assertRaises(HTTPError) as caught:
            get(url, **kwargs)
        self.assertEqual(caught.exception.code, status)

    def test_lifecycle_assets_refresh_and_guards(self):
        session = cli(self.state, 'open', self.document)
        again = cli(self.state, 'open', self.document)
        self.assertTrue(again['reused'])
        self.assertEqual(session['pid'], again['pid'])
        url = session['url']
        for route in ('', 'reader.js', 'entry.js', 'reader.css', 'meta.json',
                      'pdfjs/build/pdf.mjs', 'pdfjs/build/pdf.worker.mjs', 'pdfjs/web/pdf_viewer.css'):
            self.assertEqual(get(url + route)[0], 200)
        self.assertEqual(json.loads(get(url + 'meta.json')[1])['name'], self.document.name)
        self.assertEqual(get(url + 'document.pdf')[1], self.document.read_bytes())
        self.assertEqual(get(url + 'pdfjs/build/pdf.mjs')[2]['Content-Type'], 'text/javascript')
        self.assertEqual(get(url, method='HEAD')[1], b'')
        for route in ('../plugin.json', 'pdfjs/%2e%2e/%2e%2e/plugin.json', 'pdfjs/',
                      'scripts/preview.py', 'document.pdf/extra'):
            self.reject(url + route, 404)
        self.reject(url, 403, headers={'Host': 'invalid.example'})
        self.reject(url + '__shutdown', 403, method='POST', data=b'')
        updated = self.document.with_suffix('.new')
        updated.write_bytes(sample_pdf(2))
        updated.replace(self.document)
        self.assertEqual(get(url + 'document.pdf')[1], sample_pdf(2))
        self.assertTrue(cli(self.state, 'status')[0]['running'])
        self.assertTrue(cli(self.state, 'stop', self.document)[0]['stopped'])
        self.assertEqual(cli(self.state, 'status'), [])
        self.assertFalse(cli(self.state, 'open', self.document)['reused'])

    def test_parallel_open_and_same_basename(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            sessions = list(pool.map(lambda _: cli(self.state, 'open', self.document), range(2)))
        self.assertEqual(sessions[0]['url'], sessions[1]['url'])
        self.assertEqual(sorted(s['reused'] for s in sessions), [False, True])
        other = self.base / 'other' / self.document.name
        other.parent.mkdir()
        other.write_bytes(sample_pdf(2))
        second = cli(self.state, 'open', other)
        self.assertNotEqual(second['url'], sessions[0]['url'])
        cli(self.state, 'stop', self.document)
        self.assertEqual(get(second['url'])[0], 200)

    def test_invalid_document_and_explicit_reuse(self):
        invalid = self.base / 'invalid.pdf'
        invalid.write_text('not a PDF', encoding='utf-8')
        self.assertNotEqual(cli(self.state, 'open', invalid, check=False).returncode, 0)
        first = cli(self.state, 'open', self.document)
        reused = cli(self.state, 'open', self.document, '--reuse-url', first['url'])
        self.assertTrue(reused['reused'])
        self.assertFalse(reused['managed'])
        other = self.base / 'other.pdf'
        other.write_bytes(sample_pdf(2))
        mismatch = cli(self.state, 'open', other, '--reuse-url', first['url'])
        self.assertNotEqual(mismatch['url'], first['url'])
        self.assertTrue(mismatch['managed'])

    def test_native_system_launcher(self):
        env = os.environ.copy()
        state = self.state
        if sys.platform == 'win32':
            env['LOCALAPPDATA'] = str(self.base / 'app data')
            state = Path(env['LOCALAPPDATA']) / 'codex-pdf-previewer'
            command = [env.get('COMSPEC', 'cmd.exe'), '/d', '/c',
                       str(PLUGIN / 'open-pdf.cmd'), str(self.document)]
        else:
            name = 'open-pdf.command' if sys.platform == 'darwin' else 'open-pdf.sh'
            command = ['sh', str(PLUGIN / name), str(self.document), '--state-dir', str(state)]
        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True,
                                    encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            session = json.loads(result.stdout)
            self.assertEqual(get(session['url'] + 'document.pdf')[1], self.document.read_bytes())
        finally:
            cli(state, 'stop', '--all')

    def test_platform_data_locations(self):
        launcher = module_at('preview', LAUNCHER)
        with patch.object(launcher.sys, 'platform', 'darwin'):
            self.assertEqual(launcher.default_state_root(), Path.home() / 'Library/Application Support/codex-pdf-previewer')
        with patch.object(launcher.sys, 'platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': str(self.base)}):
            self.assertEqual(launcher.default_state_root(), self.base / 'codex-pdf-previewer')
        with patch.object(launcher.sys, 'platform', 'linux'), patch.dict(os.environ, {'XDG_STATE_HOME': ''}):
            self.assertEqual(launcher.default_state_root(), Path.home() / '.local/state/codex-pdf-previewer')

    def test_numeric_loopback_startup_needs_no_dns(self):
        launcher = module_at('preview', LAUNCHER)
        with patch.object(socket, 'getfqdn', side_effect=AssertionError('DNS must not be used')):
            server = launcher.LoopbackServer(('127.0.0.1', 0), launcher.BaseHTTPRequestHandler)
            try:
                self.assertGreater(server.server_port, 0)
            finally:
                server.server_close()


class PackageTests(unittest.TestCase):
    def test_release_contains_no_documents_or_state(self):
        builder = module_at('builder', ROOT / 'scripts/build_release.py')
        with tempfile.TemporaryDirectory(prefix='hd-pdf-package-') as temporary:
            report = builder.build(Path(temporary))
            with zipfile.ZipFile(report['archive']) as archive:
                for name in archive.namelist():
                    self.assertFalse(name.endswith(('.pdf', '.tex', '.log', '.lock', '.pyc')))
                    self.assertNotIn('__pycache__', name)
            self.assertFalse(report['documents_included'])
        with self.assertRaises(ValueError):
            builder.audit_payload('assets/reader/private.pdf', b'%PDF-1.4')
        with self.assertRaises(ValueError):
            builder.audit_payload('README.md', b'/Users/example/private-file')

    def test_system_downloads_have_correct_launchers(self):
        builder = module_at('builder', ROOT / 'scripts/build_release.py')
        with tempfile.TemporaryDirectory(prefix='pdf-platform-packages-') as temporary:
            reports = builder.build_all(Path(temporary))
            self.assertEqual(len(reports), 4)
            self.assertEqual(len((Path(temporary) / 'SHA256SUMS').read_text().splitlines()), 4)
            for report in reports:
                with zipfile.ZipFile(report['archive']) as archive:
                    names = set(archive.namelist())
                    for platform, launcher in builder.LAUNCHERS.items():
                        expected = report['platform'] in ('universal', platform)
                        self.assertEqual('codex-pdf-previewer/' + launcher in names, expected)
                        if expected and launcher.endswith(('.sh', '.command')):
                            self.assertTrue(archive.getinfo('codex-pdf-previewer/' + launcher).external_attr >> 16 & 0o111)


if __name__ == '__main__':
    unittest.main()
