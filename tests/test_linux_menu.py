import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'linux_menu_test_subject', ROOT / 'plugins/codex-pdf-previewer/scripts/linux_menu.py')
menu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(menu)


class LinuxMenuTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-menu-test-')
        self.base = Path(self.temporary.name)
        self.profile = self.base / 'profile 文档'
        self.package = self.base / 'durable source' / 'plugin'
        (self.package / 'scripts').mkdir(parents=True)
        (self.package / 'scripts/menu_open.py').write_text('# fixture\n')
        self.gui = self.base / 'Codex GUI launcher'
        self.gui.write_text('#!/bin/sh\nexit 0\n')
        self.gui.chmod(0o700)
        self.data = self.base / 'data'
        self.config = self.base / 'config'
        self.desktop = self.data / 'applications' / menu.DESKTOP_ID
        self.mimeapps = self.config / 'mimeapps.list'
        self.mimeapps.parent.mkdir(parents=True)
        self.original = (b'# retain this comment\n[Default Applications]\n'
                         b'application/pdf=viewer.desktop;\ntext/plain=editor.desktop;\n\n'
                         b'[Added Associations]\napplication/pdf=other.desktop;viewer.desktop;\n'
                         b'image/png=image.desktop;\n\n[Unrelated Section]\nx=keep\n')
        self.mimeapps.write_bytes(self.original)
        self.env = patch.dict(os.environ, {
            'XDG_DATA_HOME': str(self.data), 'XDG_CONFIG_HOME': str(self.config),
            'CODEX_PDF_PREVIEWER_GUI': ''})
        self.env.start()
        self.platform = patch.object(menu.sys, 'platform', 'linux')
        self.platform.start()

    def tearDown(self):
        self.platform.stop()
        self.env.stop()
        self.temporary.cleanup()

    def install(self, queries=None):
        answers = queries or [('viewer.desktop', menu.DESKTOP_ID)] * 2
        with patch.object(menu.shutil, 'which', return_value='/usr/bin/gio'), \
                patch.object(menu, '_query_gio', side_effect=answers):
            return menu.install_menu(self.package, self.profile, self.gui)

    def test_transaction_preserves_defaults_other_settings_and_backups(self):
        self.mimeapps.chmod(0o640)
        result = self.install()
        self.assertEqual(result['status'], 'installed')
        self.assertTrue(result['pdf_default_unchanged'])
        expected = self.original.replace(b'application/pdf=other.desktop;viewer.desktop;',
                                         b'application/pdf=codex-pdf-previewer.desktop;other.desktop;viewer.desktop;')
        self.assertEqual(self.mimeapps.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(self.mimeapps.stat().st_mode), 0o640)
        backup = Path(result['backup_dir'])
        manifest = json.loads((backup / 'manifest.json').read_text())
        mime = next(x for x in manifest['files'] if x['path'] == str(self.mimeapps))
        self.assertEqual((backup / mime['backup']).read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
        self.assertIn('--state-dir', self.desktop.read_text())
        self.assertIn(str(self.profile / 'pdf-previewer-menu/state'), self.desktop.read_text())
        self.assertEqual(stat.S_IMODE(Path(result['state_dir']).stat().st_mode), 0o700)
        before = self.desktop.read_bytes(), self.mimeapps.read_bytes()
        again = self.install()
        self.assertFalse(again['changed'])
        self.assertEqual((self.desktop.read_bytes(), self.mimeapps.read_bytes()), before)
        self.assertEqual(len(list(backup.parent.iterdir())), 1)

    def test_default_change_rolls_back_new_desktop_and_exact_config(self):
        result = self.install([('viewer.desktop', ''), (menu.DESKTOP_ID, menu.DESKTOP_ID)])
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('rolled back', result['reason'])
        self.assertEqual(result['rollback_failed'], [])
        self.assertFalse(self.desktop.exists())
        self.assertEqual(self.mimeapps.read_bytes(), self.original)

    def test_unknown_desktop_never_overwritten(self):
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text('[Desktop Entry]\nType=Application\nExec=unrelated-app %f\n')
        before = self.desktop.read_bytes()
        result = self.install([('viewer.desktop', '')])
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(self.desktop.read_bytes(), before)
        self.assertEqual(self.mimeapps.read_bytes(), self.original)

    def test_known_manual_entry_can_be_updated_and_restored_on_failure(self):
        self.desktop.parent.mkdir(parents=True)
        old = ('[Desktop Entry]\nType=Application\nName=用高清 PDF 插件打开\n'
               'Comment=Open a high-resolution PDF preview inside Codex\n'
               'Exec=/usr/bin/python3 "/some user/data/codex-pdf-previewer-client/menu-handler.py" %f\n').encode()
        self.desktop.write_bytes(old)
        result = self.install([('viewer.desktop', ''), ('changed.desktop', menu.DESKTOP_ID)])
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(self.desktop.read_bytes(), old)
        self.assertEqual(self.mimeapps.read_bytes(), self.original)
        result = self.install()
        self.assertEqual(result['status'], 'installed')
        self.assertIn(menu.MANAGED_KEY, self.desktop.read_text())
        self.assertNotIn('menu-handler.py', self.desktop.read_text())

    def test_partial_write_failure_restores_all_original_bytes(self):
        real_write = menu._atomic_write
        failed = False

        def write(path, data, mode):
            nonlocal failed
            if path == self.mimeapps and not failed:
                failed = True
                raise OSError('fixture write failed')
            return real_write(path, data, mode)

        with patch.object(menu, '_atomic_write', side_effect=write):
            result = self.install([('viewer.desktop', '')])
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['rollback_failed'], [])
        self.assertFalse(self.desktop.exists())
        self.assertEqual(self.mimeapps.read_bytes(), self.original)

    def test_external_concurrent_change_is_preserved_during_rollback(self):
        answers = 0

        def query(gio):
            nonlocal answers
            answers += 1
            if answers == 2:
                self.desktop.write_bytes(b'another process wrote this')
                return 'different.desktop', ''
            return 'viewer.desktop', ''

        with patch.object(menu.shutil, 'which', return_value='/usr/bin/gio'), \
                patch.object(menu, '_query_gio', side_effect=query):
            result = menu.install_menu(self.package, self.profile, self.gui)
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['rollback_failed'], [str(self.desktop)])
        self.assertEqual(self.desktop.read_bytes(), b'another process wrote this')
        self.assertEqual(self.mimeapps.read_bytes(), self.original)

    def test_missing_default_does_not_register_the_plugin(self):
        result = self.install([(None, 'No default applications')])
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('No existing default', result['reason'])
        self.assertFalse(self.desktop.exists())
        self.assertEqual(self.mimeapps.read_bytes(), self.original)

    def test_real_python_path_with_percent_skips_without_partial_changes(self):
        with patch.object(menu.sys, 'executable', str(self.base / 'python%executable')):
            result = self.install([('viewer.desktop', '')])
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('Python executable path contains %', result['reason'])
        self.assertFalse(self.desktop.exists())
        self.assertEqual(self.mimeapps.read_bytes(), self.original)

    def test_similar_desktop_name_is_not_treated_as_discovery(self):
        result = self.install([('viewer.desktop', ''),
                               ('viewer.desktop', 'not-' + menu.DESKTOP_ID)])
        self.assertEqual(result['status'], 'skipped')
        self.assertFalse(self.desktop.exists())
        self.assertEqual(self.mimeapps.read_bytes(), self.original)

    def test_optional_prerequisites_and_non_linux_skip(self):
        with patch.object(menu.sys, 'platform', 'darwin'):
            self.assertEqual(menu.install_menu(self.package, self.profile)['status'], 'skipped')
        with patch.object(menu.shutil, 'which', return_value=None):
            self.assertEqual(menu.install_menu(self.package, self.profile)['status'], 'skipped')
        with patch.object(menu.shutil, 'which', return_value='/usr/bin/gio'), \
                patch.object(menu, '_discover_launcher', return_value=None):
            self.assertEqual(menu.install_menu(self.package, self.profile)['status'], 'skipped')
        self.assertFalse(self.desktop.exists())

    def test_automatic_discovery_does_not_use_codex_cli(self):
        cli = self.base / 'codex'
        cli.write_text('#!/bin/sh\nexit 0\n')
        cli.chmod(0o700)
        real_valid = menu._valid_executable
        with patch.object(menu.shutil, 'which', return_value=str(cli)), \
                patch.object(menu, '_valid_executable', side_effect=lambda p: real_valid(p) if p == str(cli) else None):
            self.assertIsNone(menu._discover_launcher())
        with patch.dict(os.environ, {'CODEX_PDF_PREVIEWER_GUI': str(self.gui)}):
            self.assertEqual(menu._discover_launcher(), self.gui.resolve())

    def test_invalid_duplicate_config_and_symlinks_are_not_replaced(self):
        ambiguous = b'[Added Associations]\napplication/pdf=a.desktop;\n[Added Associations]\nx=y\n'
        self.mimeapps.write_bytes(ambiguous)
        result = self.install([('viewer.desktop', '')])
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(self.mimeapps.read_bytes(), ambiguous)
        self.assertFalse(self.desktop.exists())
        self.mimeapps.unlink()
        target = self.base / 'managed dotfile'
        target.write_bytes(self.original)
        self.mimeapps.symlink_to(target)
        result = self.install([('viewer.desktop', '')])
        self.assertEqual(result['status'], 'skipped')
        self.assertTrue(self.mimeapps.is_symlink())
        self.assertEqual(target.read_bytes(), self.original)


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('gio'), 'requires Linux GIO')
class IsolatedGioTests(unittest.TestCase):
    def test_exec_special_paths_and_real_gio_discovery_without_default_change(self):
        # This launches only a temporary argv recorder, never Codex or a PDF GUI.
        # Every association and desktop entry stays inside independent XDG dirs.
        with tempfile.TemporaryDirectory(prefix='pdf-gio-isolated-') as temporary:
            base = Path(temporary)
            special = base / 'space 文档 $dollar `tick` "quote" percent% slash\\'
            package = special / 'plugin'
            scripts = package / 'scripts'
            scripts.mkdir(parents=True)
            output = base / 'recorded argv.json'
            (scripts / 'menu_open.py').write_text('import json,sys\nfrom pathlib import Path\n'
                                                + 'Path(' + repr(str(output)) + ').write_text(json.dumps(sys.argv[1:]))\n')
            gui = special / 'GUI $ ` " % launcher'
            gui.write_text('#!/bin/sh\nexit 0\n')
            gui.chmod(0o700)
            python = special / 'python $ ` " % executable'
            python.symlink_to(sys.executable)
            profile = special / 'profile'
            data = base / 'data'
            config = base / 'config'
            apps = data / 'applications'
            apps.mkdir(parents=True)
            config.mkdir()
            (apps / 'viewer.desktop').write_text('[Desktop Entry]\nType=Application\nName=Fixture viewer\n'
                                                 'Exec=/usr/bin/true %f\nMimeType=application/pdf;\n')
            (config / 'mimeapps.list').write_text('[Default Applications]\napplication/pdf=viewer.desktop;\n'
                                                  '[Added Associations]\napplication/pdf=viewer.desktop;\n')
            env = {'XDG_DATA_HOME': str(data), 'XDG_CONFIG_HOME': str(config),
                   'XDG_DATA_DIRS': str(base / 'empty-system'), 'XDG_CURRENT_DESKTOP': '',
                   'CODEX_PDF_PREVIEWER_GUI': '', 'LC_ALL': 'C'}
            with patch.dict(os.environ, env), patch.object(menu.sys, 'executable', str(python)):
                result = menu.install_menu(package, profile, gui)
                self.assertEqual(result['status'], 'installed', result)
                self.assertEqual(menu._query_gio(shutil.which('gio'))[0], 'viewer.desktop')
                pdf = special / 'selected $ ` " % document.pdf'
                pdf.write_bytes(b'fixture; opener only records its path')
                launch = subprocess.run(['gio', 'launch', result['desktop_file'], str(pdf)],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(launch.returncode, 0, launch.stderr)
                for _ in range(100):
                    if output.exists():
                        break
                    time.sleep(0.01)
                self.assertTrue(output.exists(), launch.stderr)
                self.assertEqual(json.loads(output.read_text()),
                                 ['--launcher', str(gui.resolve()), '--state-dir',
                                  str(profile.resolve() / 'pdf-previewer-menu/state'), str(pdf)])


if __name__ == '__main__':
    unittest.main()
