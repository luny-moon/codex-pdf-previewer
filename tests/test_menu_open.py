"""Isolated tests for the explicit PDF menu action; never start GUI or a reader."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from support import PLUGIN, sample_pdf

sys.dont_write_bytecode = True
MENU_SCRIPT = PLUGIN / 'scripts/menu_open.py'
PREVIEW_SCRIPT = PLUGIN / 'scripts/preview.py'


def load_menu():
    spec = importlib.util.spec_from_file_location('menu_open_under_test', MENU_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MenuOpenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.menu = load_menu()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-menu-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        filename = ('中文 proof ; $(not-a-command) quoted.PDF' if sys.platform == 'win32'
                    else '中文 proof ; $(not-a-command) "quoted".PDF')
        self.document = self.base / filename
        self.document.write_bytes(sample_pdf(2))
        self.state = self.base / 'reader state 文档'
        self.launcher = self.base / 'Codex GUI launcher with spaces'
        self.launcher.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        self.launcher.chmod(0o755)
        self.url = 'http://127.0.0.1:34791/'

    def backend_result(self, *, url=None, pdf=None, returncode=0, stderr=''):
        return subprocess.CompletedProcess(
            [], returncode,
            stdout=json.dumps({'url': self.url if url is None else url,
                               'pdf': str(self.document) if pdf is None else str(pdf)}),
            stderr=stderr,
        )

    def gui_process(self, returncode=0):
        process = MagicMock()
        process.wait.return_value = returncode
        process.poll.return_value = returncode
        process.returncode = returncode
        return process

    def test_unicode_and_shell_characters_remain_argv_and_use_same_reader_url(self):
        process = self.gui_process()
        with patch.object(self.menu.subprocess, 'run', return_value=self.backend_result()) as run, \
                patch.object(self.menu.subprocess, 'Popen', return_value=process) as popen:
            result = self.menu.open_document(self.document, self.launcher, state_dir=self.state)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], [
            sys.executable, str(PREVIEW_SCRIPT), 'open', str(self.document.resolve()),
            '--state-dir', str(self.state.resolve()),
        ])
        self.assertFalse(run.call_args.kwargs.get('shell', False))
        self.assertEqual(popen.call_count, 1)
        argv = popen.call_args.args[0]
        self.assertEqual(len(argv), 2)
        self.assertEqual(argv[0], str(self.launcher.resolve()))
        self.assertFalse(popen.call_args.kwargs.get('shell', False))
        deep_link = urlsplit(argv[1])
        self.assertEqual((deep_link.scheme, deep_link.netloc, deep_link.path),
                         ('codex', 'browser', ''))
        self.assertEqual(parse_qs(deep_link.query), {'url': [self.url]})
        self.assertNotIn(str(self.document), argv[1])
        self.assertEqual(result['url'], self.url)
        self.assertEqual(result['pdf'], str(self.document.resolve()))
        self.assertTrue(result['submitted_to_codex'])
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_prepare_only_starts_no_gui_and_preserves_backend_url(self):
        with patch.object(self.menu.subprocess, 'run', return_value=self.backend_result()) as run, \
                patch.object(self.menu.subprocess, 'Popen') as popen:
            result = self.menu.open_document(self.document, self.launcher,
                                             state_dir=self.state, prepare_only=True)
        self.assertEqual(run.call_count, 1)
        popen.assert_not_called()
        self.assertEqual(result['url'], self.url)
        self.assertEqual(result['pdf'], str(self.document.resolve()))
        self.assertFalse(result['submitted_to_codex'])

    def test_untrusted_reader_urls_are_rejected_before_gui_submission(self):
        invalid_urls = (
            'https://127.0.0.1:34791/',
            'http://example.invalid:34791/',
            'http://localhost:34791/',
            'http://user:password@127.0.0.1:34791/',
            'http://127.0.0.1/',
            'http://127.0.0.1:34791/other',
            'http://127.0.0.1:34791/?redirect=https://example.invalid/',
            'http://127.0.0.1:34791/#fragment',
        )
        for url in invalid_urls:
            with self.subTest(url=url), \
                    patch.object(self.menu.subprocess, 'run', return_value=self.backend_result(url=url)), \
                    patch.object(self.menu.subprocess, 'Popen') as popen:
                with self.assertRaises((ValueError, RuntimeError)):
                    self.menu.open_document(self.document, self.launcher)
                popen.assert_not_called()

    def test_pdf_mismatch_and_bad_backend_output_never_open_gui(self):
        other = self.base / 'different.pdf'
        other.write_bytes(sample_pdf(1))
        bad_results = (
            self.backend_result(pdf=other),
            subprocess.CompletedProcess([], 0, stdout='not JSON', stderr=''),
            subprocess.CompletedProcess([], 0, stdout='{}', stderr=''),
            subprocess.CompletedProcess([], 0, stdout='[]', stderr=''),
            subprocess.CompletedProcess([], 0, stdout='null', stderr=''),
        )
        for response in bad_results:
            with self.subTest(output=response.stdout), \
                    patch.object(self.menu.subprocess, 'run', return_value=response), \
                    patch.object(self.menu.subprocess, 'Popen') as popen:
                with self.assertRaises((ValueError, RuntimeError, KeyError)):
                    self.menu.open_document(self.document, self.launcher)
                popen.assert_not_called()
        failure = subprocess.CalledProcessError(1, ['synthetic preview'],
                                                stderr='reader preparation failed')
        with patch.object(self.menu.subprocess, 'run', side_effect=failure), \
                patch.object(self.menu.subprocess, 'Popen') as popen:
            with self.assertRaises(subprocess.SubprocessError):
                self.menu.open_document(self.document, self.launcher)
            popen.assert_not_called()

    def test_gui_launch_failure_and_nonzero_exit_are_reported(self):
        with patch.object(self.menu.subprocess, 'run', return_value=self.backend_result()), \
                patch.object(self.menu.subprocess, 'Popen', side_effect=OSError('cannot start GUI')):
            with self.assertRaises((OSError, RuntimeError)):
                self.menu.open_document(self.document, self.launcher)
        process = self.gui_process(returncode=7)
        with patch.object(self.menu.subprocess, 'run', return_value=self.backend_result()), \
                patch.object(self.menu.subprocess, 'Popen', return_value=process):
            with self.assertRaises((OSError, RuntimeError)):
                self.menu.open_document(self.document, self.launcher)
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_gui_wait_timeout_does_not_kill_application(self):
        process = self.gui_process(returncode=None)
        process.wait.side_effect = subprocess.TimeoutExpired('synthetic GUI launcher', 1)
        with patch.object(self.menu.subprocess, 'run', return_value=self.backend_result()), \
                patch.object(self.menu.subprocess, 'Popen', return_value=process):
            result = self.menu.open_document(self.document, self.launcher)
        self.assertTrue(result['submitted_to_codex'])
        process.wait.assert_called_once()
        process.kill.assert_not_called()
        process.terminate.assert_not_called()


    def test_cli_requires_launcher_and_passes_explicit_prepare_arguments(self):
        output = {'url': self.url, 'pdf': str(self.document), 'submitted_to_codex': False}
        argv = [str(MENU_SCRIPT), str(self.document), '--launcher', str(self.launcher),
                '--state-dir', str(self.state), '--prepare-only']
        printed = io.StringIO()
        with patch.object(self.menu.sys, 'argv', argv), \
                patch.object(self.menu, 'open_document', return_value=output) as open_document, \
                contextlib.redirect_stdout(printed):
            self.assertEqual(self.menu.main(), 0)
        open_document.assert_called_once_with(str(self.document), str(self.launcher),
                                              self.state, True)
        self.assertEqual(json.loads(printed.getvalue()), output)
        with patch.object(self.menu.sys, 'argv', [str(MENU_SCRIPT), str(self.document)]), \
                patch.object(self.menu, 'open_document') as open_document, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                self.menu.main()
        self.assertEqual(caught.exception.code, 2)
        open_document.assert_not_called()

    def test_invalid_gui_launcher_is_rejected_without_starting_reader_or_gui(self):
        missing = self.base / 'missing launcher'
        with patch.object(self.menu.subprocess, 'run') as run, \
                patch.object(self.menu.subprocess, 'Popen') as popen:
            with self.assertRaises((ValueError, RuntimeError, OSError)):
                self.menu.open_document(self.document, missing)
            run.assert_not_called()
            popen.assert_not_called()
        # Windows does not implement POSIX executable mode bits; exercise this
        # validation independently of filesystem/chmod semantics on every OS.
        with patch.object(self.menu.os, 'access', return_value=False) as access, \
                patch.object(self.menu.subprocess, 'run') as run, \
                patch.object(self.menu.subprocess, 'Popen') as popen:
            with self.assertRaises((ValueError, RuntimeError, OSError)):
                self.menu.open_document(self.document, self.launcher)
            access.assert_called_once_with(self.launcher.resolve(), self.menu.os.X_OK)
            run.assert_not_called()
            popen.assert_not_called()



if __name__ == '__main__':
    unittest.main()
