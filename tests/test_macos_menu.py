"""Managed macOS PDF applet tests; the native case uses only synthetic files."""
import contextlib
import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from support import PLUGIN, sample_pdf

sys.dont_write_bytecode = True


def load_module():
    spec = importlib.util.spec_from_file_location('macos_menu_under_test',
                                                PLUGIN / 'scripts/macos_menu.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_gui(base):
    app = base / 'Codex.app'
    binary = app / 'Contents/MacOS/Codex'
    binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    binary.chmod(0o755)
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundlePackageType': 'APPL', 'CFBundleIdentifier': 'com.openai.codex',
        'CFBundleExecutable': 'Codex', 'CFBundleURLTypes': [{'CFBundleURLSchemes': ['codex']}],
    }))
    return app


class MacMenuTests(unittest.TestCase):
    def setUp(self):
        self.menu = load_module()
        self.temporary = tempfile.TemporaryDirectory(prefix='mac-pdf-menu-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.package = self.base / 'durable plugin 文档 with spaces'
        (self.package / 'scripts').mkdir(parents=True)
        (self.package / 'scripts/menu_open.py').write_text('# synthetic menu launcher\n', encoding='utf-8')
        self.home = self.base / 'profile'
        self.setup = self.home / 'pdf-previewer-menu/macos'
        self.applications = self.base / 'isolated Applications'
        self.app = self.applications / self.menu.APP_NAME
        self.gui = fake_gui(self.base)
        self.commands = []
        self.native = []
        self.default = 'com.apple.Preview'
        self.fail_next_registration = False
        self.hide_wrapper = False
        self.delayed_queries_remaining = 0

    @contextlib.contextmanager
    def mocked_host(self):
        original_is_file = Path.is_file
        original_access = os.access
        tools = {'/usr/bin/osacompile', '/usr/bin/codesign'}

        def is_file(path):
            return True if path.as_posix() in tools else original_is_file(path)

        def access(path, mode):
            if Path(path).as_posix() in tools or path == self.gui / 'Contents/MacOS/Codex':
                return True
            return original_access(path, mode)

        with patch.object(self.menu.sys, 'platform', 'darwin'), \
                patch.object(Path, 'is_file', is_file), \
                patch.object(self.menu.os, 'access', side_effect=access), \
                patch.object(self.menu, '_run', side_effect=self.fake_run), \
                patch.object(self.menu, '_services', side_effect=self.fake_services), \
                patch.object(self.menu, '_user_applications_dir', return_value=self.applications), \
                patch.object(self.menu, 'DISCOVERY_TIMEOUT', 0):
            yield

    def fake_run(self, argv, message):
        self.commands.append([str(arg) for arg in argv])
        if str(argv[0]) == '/usr/bin/osacompile':
            output = Path(argv[argv.index('-o') + 1])
            source = Path(argv[-1]).read_bytes()
            (output / 'Contents/MacOS').mkdir(parents=True)
            (output / 'Contents/Resources').mkdir()
            (output / 'Contents/MacOS/applet').write_bytes(b'synthetic executable')
            (output / 'Contents/Resources/main.scpt').write_bytes(source)
            (output / 'Contents/Info.plist').write_bytes(plistlib.dumps({
                'CFBundleExecutable': 'applet', 'CFBundlePackageType': 'APPL'}))
        elif str(argv[0]) == '/usr/bin/codesign' and '--sign' in argv:
            app = Path(argv[-1])
            signature = app / 'Contents/_CodeSignature/CodeResources'
            signature.parent.mkdir()
            signature.write_bytes(b'synthetic signature')
        return subprocess.CompletedProcess(argv, 0, stdout='{}', stderr='')

    def fake_services(self, operation, path):
        self.native.append((operation, str(path)))
        if operation == 'register':
            if self.fail_next_registration:
                self.fail_next_registration = False
                raise self.menu.MenuSetupError('synthetic registration failure')
            return {'registered': True}
        applications = [{'appPath': '/System/Applications/Preview.app',
                         'bundleId': self.default, 'displayName': 'Preview'}]
        if self.app.exists() and not self.hide_wrapper:
            if self.delayed_queries_remaining:
                self.delayed_queries_remaining -= 1
            else:
                applications.append({'appPath': str(self.app), 'bundleId': self.menu.BUNDLE_ID,
                                     'displayName': '用高清 PDF 插件打开'})
        return {'default_handler': self.default, 'applications': applications}

    def install(self):
        return self.menu.install_menu(self.package, self.home, launcher=self.gui)

    def test_local_applet_metadata_no_shell_and_idempotence(self):
        with self.mocked_host():
            result = self.install()
            self.assertEqual(result['status'], 'installed', result)
            self.assertTrue(result['os_registered'])
            self.assertTrue(result['viewer_discovered'])
            self.assertFalse(result['ui_verified'])
            self.assertTrue(result['pdf_default_unchanged'])
            self.assertIn('five', result['visibility_note'])
            info = plistlib.loads((self.app / 'Contents/Info.plist').read_bytes())
            self.assertEqual(info['CFBundleIdentifier'], self.menu.BUNDLE_ID)
            self.assertEqual(info['CFBundleDisplayName'], '用高清 PDF 插件打开')
            document_type = info['CFBundleDocumentTypes'][0]
            self.assertEqual(document_type['CFBundleTypeRole'], 'Viewer')
            self.assertEqual(document_type['LSHandlerRank'], 'Alternate')
            self.assertEqual(document_type['LSItemContentTypes'], ['com.adobe.pdf'])
            source = (self.app / 'Contents/Resources/main.scpt').read_text(encoding='utf-8')
            self.assertIn('function openDocuments(documents)', source)
            self.assertIn('$.NSTask', source)
            self.assertIn('task.arguments = $(', source)
            self.assertNotIn('do shell script', source)
            self.assertNotIn('/bin/sh', source)
            self.assertNotIn('LSSetDefault', self.menu.LS_HELPER)
            command_count = len(self.commands)
            again = self.install()
            self.assertEqual(again['status'], 'installed', again)
            self.assertFalse(again['changed'])
            self.assertEqual(len(self.commands), command_count)
            self.assertFalse((self.setup / '.install-lock').exists())
        self.assertEqual(self.commands[0][:3], ['/usr/bin/osacompile', '-l', 'JavaScript'])
        self.assertTrue(any('--verify' in command for command in self.commands))

    def test_cli_and_legacy_chatgpt_are_not_gui_bundles(self):
        self.assertIsNone(self.menu._valid_gui(self.base / 'codex'))
        self.assertIsNone(self.menu._valid_gui('codex'))
        info_path = self.gui / 'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info['CFBundleIdentifier'] = 'com.openai.chat'
        info.pop('CFBundleURLTypes')
        info_path.write_bytes(plistlib.dumps(info))
        with self.mocked_host():
            result = self.install()
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(self.commands, [])
        self.assertFalse(self.app.exists())

    def test_unknown_bundle_and_changed_managed_bundle_are_preserved(self):
        self.app.mkdir(parents=True)
        marker = self.app / 'user-file'
        marker.write_text('leave me alone', encoding='utf-8')
        with self.mocked_host():
            result = self.install()
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(marker.read_text(), 'leave me alone')
        self.assertEqual(self.commands, [])
        shutil.rmtree(self.app)
        with self.mocked_host():
            self.assertEqual(self.install()['status'], 'installed')
            compiled = self.app / 'Contents/Resources/main.scpt'
            compiled.write_text('independent user change', encoding='utf-8')
            count = len(self.commands)
            result = self.install()
            self.assertEqual(result['status'], 'skipped')
            self.assertEqual(compiled.read_text(), 'independent user change')
            self.assertEqual(len(self.commands), count)

    def test_other_profile_cannot_replace_an_existing_managed_application(self):
        with self.mocked_host():
            first = self.install()
            self.assertEqual(first['status'], 'installed', first)
            digest = self.menu._digest(self.app)
            commands = len(self.commands)
            result = self.menu.install_menu(self.package, self.base / 'other-profile', launcher=self.gui)
            self.assertEqual(result['status'], 'skipped')
            self.assertEqual(self.menu._digest(self.app), digest)
            self.assertEqual(len(self.commands), commands)
        self.assertFalse((self.base / 'other-profile/pdf-previewer-menu/macos/installation.json').exists())

    def test_failed_update_restores_previous_owned_bundle_and_sidecar(self):
        with self.mocked_host():
            self.assertEqual(self.install()['status'], 'installed')
            old_digest = self.menu._digest(self.app)
            sidecar = (self.setup / 'installation.json').read_bytes()
            other = self.base / 'new durable plugin'
            (other / 'scripts').mkdir(parents=True)
            (other / 'scripts/menu_open.py').write_text('# another synthetic launcher\n')
            self.fail_next_registration = True
            result = self.menu.install_menu(other, self.home, launcher=self.gui)
            self.assertEqual(result['status'], 'skipped', result)
            self.assertFalse(result['rollback_failed'])
            self.assertEqual(self.menu._digest(self.app), old_digest)
            self.assertEqual((self.setup / 'installation.json').read_bytes(), sidecar)
            backup = Path(result['backup_dir'])
            self.assertTrue((backup / self.menu.APP_NAME).is_dir())
            self.assertTrue((backup / 'manifest.json').is_file())

    def test_discovery_waits_briefly_but_requires_the_actual_registered_viewer(self):
        self.delayed_queries_remaining = 1
        with self.mocked_host(), patch.object(self.menu, 'DISCOVERY_TIMEOUT', 1), \
                patch.object(self.menu.time, 'monotonic', side_effect=[0, 0.1]), \
                patch.object(self.menu.time, 'sleep') as sleep:
            result = self.install()
        self.assertEqual(result['status'], 'installed', result)
        self.assertTrue(result['viewer_discovered'])
        sleep.assert_called_once_with(self.menu.DISCOVERY_POLL_INTERVAL)
        self.assertEqual(sum(operation == 'query' for operation, _ in self.native), 3)

    def test_discovery_requires_bundle_id_and_the_same_physical_path(self):
        self.app.mkdir(parents=True)
        alias = self.base / 'path-alias.app'
        other = self.base / 'different.app'
        other.mkdir()
        original_resolve = Path.resolve
        expected = original_resolve(self.app, strict=True)

        def resolve(path, *args, **kwargs):
            return expected if path == alias else original_resolve(path, *args, **kwargs)

        result = {'applications': [{'appPath': str(alias), 'bundleId': self.menu.BUNDLE_ID}]}
        with patch.object(Path, 'resolve', resolve):
            self.assertTrue(self.menu._discovered(result, self.app))
        result['applications'][0]['appPath'] = str(other)
        self.assertFalse(self.menu._discovered(result, self.app))
        result['applications'][0] = {'appPath': str(self.app), 'bundleId': 'unrelated.app'}
        self.assertFalse(self.menu._discovered(result, self.app))

    def test_default_change_stops_discovery_without_waiting(self):
        with patch.object(self.menu, '_query', return_value={
                'default_handler': 'another.default', 'applications': []}), \
                patch.object(self.menu.time, 'sleep') as sleep:
            with self.assertRaisesRegex(self.menu.MenuSetupError, 'default PDF application changed'):
                self.menu._wait_for_discovery(self.base / 'probe.pdf', self.app, 'com.apple.Preview')
        sleep.assert_not_called()

    def test_registration_discovery_failure_removes_only_new_owned_wrapper(self):
        self.hide_wrapper = True
        with self.mocked_host(), patch.object(self.menu.time, 'sleep') as sleep:
            result = self.install()
        self.assertEqual(result['status'], 'skipped')
        sleep.assert_not_called()
        self.assertEqual(sum(operation == 'query' for operation, _ in self.native), 2)
        self.assertFalse(result['rollback_failed'])
        self.assertFalse(self.app.exists())
        self.assertFalse((self.setup / 'installation.json').exists())
        self.assertFalse((self.setup / '.install-lock').exists())

    def test_no_default_and_other_platform_skip_without_registration(self):
        self.default = None
        with self.mocked_host():
            result = self.install()
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(self.commands, [])
        self.assertFalse(any(operation == 'register' for operation, _ in self.native))
        with patch.object(self.menu.sys, 'platform', 'linux'), \
                patch.object(self.menu, '_services') as native:
            result = self.install()
        self.assertEqual(result['status'], 'skipped')
        native.assert_not_called()

    def test_native_api_boundary_uses_fixed_python_and_argv(self):
        response = subprocess.CompletedProcess([], 0, stdout='{"registered": true}', stderr='')
        value = self.base / '中文 with spaces ; $().app'
        with patch.object(self.menu.subprocess, 'run', return_value=response) as run:
            self.assertTrue(self.menu._services('register', value)['registered'])
        self.assertEqual(run.call_args.args[0],
                         [sys.executable, '-c', self.menu.LS_HELPER, 'register', str(value)])
        self.assertFalse(run.call_args.kwargs.get('shell', False))
        self.assertTrue(run.call_args.kwargs['check'])


@unittest.skipUnless(sys.platform == 'darwin', 'Real applet event delivery requires macOS')
class NativeMacAppletTests(unittest.TestCase):
    def test_real_compile_registration_and_open_documents_argv(self):
        self._exercise_native_events(stay_open=False)

    @unittest.skipUnless(os.environ.get('GITHUB_ACTIONS') == 'true',
                         'Temporary stay-open comparison runs only on GitHub Actions')
    def test_stay_open_lifetime_comparison(self):
        self._exercise_native_events(stay_open=True)

    def _exercise_native_events(self, stay_open):
        if not all(Path(tool).is_file() for tool in ('/usr/bin/osacompile', '/usr/bin/codesign', '/usr/bin/open')):
            self.skipTest('Standard macOS applet tools are unavailable')
        menu = load_module()
        identifier = 'org.codex-pdf-previewer.integration.' + uuid.uuid4().hex
        app_name = 'Codex PDF Previewer CI ' + uuid.uuid4().hex + '.app'
        applications = menu._user_applications_dir()
        made_applications = not applications.exists()
        expected_app = (applications / app_name).resolve()
        self.assertFalse(expected_app.exists())
        try:
            with tempfile.TemporaryDirectory(prefix='mac-pdf-event-') as temporary:
                base = Path(temporary).resolve()
                gui = fake_gui(base)
                package = base / 'synthetic plugin 文档 with spaces'
                (package / 'scripts').mkdir(parents=True)
                record = base / 'received.jsonl'
                recorder = ('import json,sys\nfrom pathlib import Path\n'
                            'with Path(' + repr(str(record)) + ').open("a",encoding="utf-8") as stream:\n'
                            '    stream.write(json.dumps(sys.argv[1:],ensure_ascii=False)+"\\n")\n')
                (package / 'scripts/menu_open.py').write_text(recorder, encoding='utf-8')
                document = base / '中文 space ; $(not-a-command) "quote".pdf'
                document.write_bytes(sample_pdf())
                second = base / 'second.pdf'
                second.write_bytes(sample_pdf(2))
                third = base / 'third fresh.pdf'
                third.write_bytes(sample_pdf(3))
                # Standard user Applications location, but unique synthetic id
                # and name. The real Codex app and its URL default are untouched.
                diagnostics = []
                real_query = menu._query

                def captured_query(probe):
                    response = real_query(probe)
                    diagnostics.append({'synthetic_probe': str(probe), 'result': response})
                    return response

                original_run = menu._run

                def comparison_run(argv, message):
                    if stay_open and str(argv[0]) == '/usr/bin/osacompile':
                        argv = [argv[0], '-s', *argv[1:]]
                    return original_run(argv, message)

                with patch.object(menu, 'BUNDLE_ID', identifier), \
                        patch.object(menu, 'APP_NAME', app_name), \
                        patch.object(menu, '_query', side_effect=captured_query), \
                        patch.object(menu, '_run', side_effect=comparison_run):
                    result = menu.install_menu(package, base / 'profile', launcher=gui)
                    if result['status'] != 'installed':
                        self.fail(json.dumps({'installation': result,
                                              'expected_synthetic_bundle_id': identifier,
                                              'expected_synthetic_app': str(expected_app),
                                              'native_queries': diagnostics}, ensure_ascii=False, indent=2))
                    self.assertTrue(result['viewer_discovered'])
                    self.assertFalse(result['ui_verified'])
                    self.assertEqual(Path(result['app_bundle']).resolve(), expected_app)
                    app = Path(result['app_bundle'])
                    expected_prefix = ['--launcher', str(gui.resolve()), '--state-dir', result['state_dir']]
                    subprocess.run(['/usr/bin/open', '-a', str(app), str(document)], check=True,
                                   capture_output=True, text=True, timeout=20)
                    first = self._wait_for_records(record, 1, 'initial single document')
                    self.assertEqual(first, [expected_prefix + [str(document)]])
                    # Distinguish genuine batch delivery from the OS possibly
                    # treating an already-open document specially.
                    subprocess.run(['/usr/bin/open', '-a', str(app), str(second), str(third)],
                                   check=True, capture_output=True, text=True, timeout=20)
                    rows = self._wait_for_records(record, 3, 'two fresh documents in one event')
                    self.assertEqual(rows[0], expected_prefix + [str(document)])
                    self.assertCountEqual(rows[1:], [expected_prefix + [str(second)],
                                                    expected_prefix + [str(third)]])
                    subprocess.run(['/usr/bin/open', '-a', str(app), str(document)], check=True,
                                   capture_output=True, text=True, timeout=20)
                    repeated = self._wait_for_records(record, 4, 'repeat the original document')
                    self.assertEqual(repeated[3:], [expected_prefix + [str(document)]])
                    probe = base / 'probe.pdf'
                    probe.write_bytes(sample_pdf())
                    after = menu._query(probe)
                    self.assertTrue(menu._discovered(after, app))
        finally:
            # A stay-open comparison must not leave an applet process behind.
            # The public query/terminate helper requires BOTH our random bundle
            # id and exact canonical app path before touching any process.
            self._stop_owned_applet(identifier, expected_app)
            if expected_app.is_dir() and not expected_app.is_symlink():
                info_path = expected_app / 'Contents/Info.plist'
                info = plistlib.loads(info_path.read_bytes())
                if info.get('CFBundleIdentifier') == identifier:
                    shutil.rmtree(expected_app)
            if made_applications:
                try:
                    applications.rmdir()
                except OSError:
                    pass

    def _owned_applet_processes(self, identifier, app, action):
        script = r"""
ObjC.import('AppKit');
function run(argv) {
    var identifier = argv[0], expected = argv[1], action = argv[2];
    var applications = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(identifier);
    var result = [];
    for (var i = 0; i < applications.count; i++) {
        var application = applications.objectAtIndex(i);
        var location = application.bundleURL;
        if (!location) continue;
        var actual = ObjC.unwrap(location.URLByResolvingSymlinksInPath.path);
        if (actual !== expected || ObjC.unwrap(application.bundleIdentifier) !== identifier) continue;
        var pid = Number(application.processIdentifier);
        if (action === 'terminate') application.terminate;
        if (action === 'force') application.forceTerminate;
        result.push(pid);
    }
    return JSON.stringify(result);
}
"""
        response = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', script,
                                   identifier, str(app.resolve()), action],
                                  check=True, capture_output=True, text=True,
                                  encoding='utf-8', timeout=10)
        return json.loads(response.stdout)

    def _stop_owned_applet(self, identifier, app):
        if not self._owned_applet_processes(identifier, app, 'inspect'):
            return
        self._owned_applet_processes(identifier, app, 'terminate')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not self._owned_applet_processes(identifier, app, 'inspect'):
                return
            time.sleep(0.1)
        self._owned_applet_processes(identifier, app, 'force')
        self.assertFalse(self._owned_applet_processes(identifier, app, 'inspect'),
                         'The exact synthetic applet did not stop during cleanup')

    def _wait_for_records(self, record, count, stage):
        deadline = time.monotonic() + 20
        rows = []
        last_parse_error = None
        while time.monotonic() < deadline:
            if record.exists():
                try:
                    rows = [json.loads(line) for line in record.read_text(encoding='utf-8').splitlines()]
                    last_parse_error = None
                except json.JSONDecodeError as error:
                    # An event recorder may still be flushing its last line.
                    last_parse_error = str(error)
                else:
                    if len(rows) >= count:
                        return rows
            time.sleep(0.1)
        self.fail('Synthetic Open Documents event did not finish: ' + json.dumps(
            {'stage': stage, 'expected_record_count': count, 'received_rows': rows,
             'synthetic_record': str(record), 'last_parse_error': last_parse_error},
            ensure_ascii=False))



if __name__ == '__main__':
    unittest.main()
