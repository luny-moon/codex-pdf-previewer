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
        self.app = self.setup / self.menu.APP_NAME
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
    @unittest.skipUnless(os.environ.get('GITHUB_ACTIONS') == 'true',
                         'Temporary native registration matrix runs only on GitHub Actions')
    def test_native_registration_diagnostic_matrix(self):
        """Keep production behavior unchanged while measuring native claims."""
        if not all(Path(tool).is_file() for tool in ('/usr/bin/osacompile', '/usr/bin/codesign')):
            self.skipTest('Standard macOS applet tools are unavailable')
        menu = load_module()
        token = uuid.uuid4().hex
        user_apps = Path.home() / 'Applications'
        made_user_apps = not user_apps.exists()
        created_apps = []
        results = []
        before = None
        try:
            user_apps.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='mac-pdf-matrix-') as temporary:
                base = Path(temporary).resolve()
                gui = fake_gui(base)
                package = base / 'synthetic package'
                (package / 'scripts').mkdir(parents=True)
                # The matrix never opens an app. Its fixed target is harmless
                # even if an OS background mechanism unexpectedly starts it.
                (package / 'scripts/menu_open.py').write_text('raise SystemExit(0)\n', encoding='utf-8')
                valid_probe = base / 'valid-probe.pdf'
                valid_probe.write_bytes(sample_pdf())
                minimal_probe = base / 'minimal-probe.pdf'
                minimal_probe.write_bytes(b'%PDF-1.4\n% Synthetic registration probe.\n%%EOF\n')
                before = menu._query(valid_probe)
                self.assertTrue(before['default_handler'], before)
                cases = [(location, agent, extensions, rank)
                         for location in ('temporary', 'user-applications')
                         for agent in (True, False) for extensions in (False, True)
                         for rank in ('Alternate', 'Default')]
                for index, (location, agent, extensions, rank) in enumerate(cases):
                    identifier = 'org.codex-pdf-previewer.matrix.' + token + '.case' + str(index)
                    name = 'Codex PDF Native CI ' + token + '-' + str(index) + '.app'
                    destination = (base if location == 'temporary' else user_apps) / name
                    self.assertFalse(destination.exists())
                    staging = base / ('stage-' + str(index))
                    staging.mkdir()
                    source = staging / 'wrapper.js'
                    source.write_text(menu._source(package, gui, base / 'unused-state'), encoding='utf-8')
                    compiled = staging / name
                    menu._run(['/usr/bin/osacompile', '-l', 'JavaScript', '-o', compiled, source],
                              'Could not compile a synthetic diagnostic applet')
                    with patch.object(menu, 'BUNDLE_ID', identifier):
                        info_file = compiled / 'Contents/Info.plist'
                        info = plistlib.loads(info_file.read_bytes())
                        info.update(menu._plist())
                        info['CFBundleName'] = name[:-4]
                        info['CFBundleDisplayName'] = name[:-4]
                        if not agent:
                            info.pop('LSUIElement', None)
                        claim = info['CFBundleDocumentTypes'][0]
                        claim['LSHandlerRank'] = rank
                        if extensions:
                            claim['CFBundleTypeExtensions'] = ['pdf']
                            claim['CFBundleTypeMIMETypes'] = ['application/pdf']
                        info_file.write_bytes(plistlib.dumps(info))
                        menu._run(['/usr/bin/codesign', '--force', '--sign', '-', compiled],
                                  'Could not sign a synthetic diagnostic applet')
                        menu._run(['/usr/bin/codesign', '--verify', '--strict', compiled],
                                  'Could not verify a synthetic diagnostic applet')
                        os.replace(compiled, destination)
                        created_apps.append(destination)
                        registration = menu._services('register', destination)
                        discovered = False
                        wait_error = None
                        try:
                            menu._wait_for_discovery(valid_probe, destination, before['default_handler'])
                            discovered = True
                        except menu.MenuSetupError as error:
                            wait_error = str(error)
                        valid_query = menu._query(valid_probe)
                        minimal_query = menu._query(minimal_probe)
                        details = self._native_registration_details(menu, identifier, valid_probe)
                        result = {'case': index, 'location': location, 'ui_element': agent,
                                  'explicit_pdf_extension_and_mime': extensions,
                                  'handler_rank': rank,
                                  'synthetic_bundle_id': identifier, 'synthetic_app': str(destination),
                                  'registration': registration, 'discovered_with_valid_pdf': discovered,
                                  'discovered_with_minimal_probe': menu._discovered(minimal_query, destination),
                                  'wait_error': wait_error, 'native_registration': details,
                                  'valid_probe_query': valid_query,
                                  'minimal_probe_query': minimal_query}
                        results.append(result)
                        # Keep only one synthetic candidate on disk at a time.
                        # This also immediately backs out a rank experiment if
                        # macOS unexpectedly changes its chosen PDF default.
                        shutil.rmtree(destination)
                        after_cleanup = menu._query(valid_probe)
                        result['default_after_own_app_removal'] = after_cleanup['default_handler']
                        self.assertEqual(valid_query['default_handler'], before['default_handler'], result)
                        self.assertEqual(minimal_query['default_handler'], before['default_handler'], result)
                        self.assertEqual(after_cleanup['default_handler'], before['default_handler'], result)
        finally:
            # This is controlled runner diagnostics, never a product document or
            # a claim that registration alone verifies the Codex menu.
            print('MACOS_PDF_NATIVE_DIAGNOSTIC_MATRIX=' + json.dumps(
                {'baseline_default': None if before is None else before['default_handler'],
                 'cases': results}, ensure_ascii=False, sort_keys=True), flush=True)
            for app in reversed(created_apps):
                if app.is_dir() and app.name.startswith('Codex PDF Native CI ' + token + '-'):
                    shutil.rmtree(app)
            if made_user_apps:
                try:
                    user_apps.rmdir()
                except OSError:
                    pass

    def _native_registration_details(self, menu, identifier, probe):
        # Reuse only the ctypes definitions, then inspect this synthetic id's
        # registration and the UTI of this generated probe through public APIs.
        definitions = menu.LS_HELPER.split('operation, path = sys.argv[1:3]', 1)[0]
        script = definitions + r"""
identifier, probe = sys.argv[1:3]
ls.LSCopyApplicationURLsForBundleIdentifier.argtypes = [ptr, c.POINTER(c.c_int32)]
ls.LSCopyApplicationURLsForBundleIdentifier.restype = ptr
ls.LSCopyAllRoleHandlersForContentType.argtypes = [ptr, c.c_uint32]
ls.LSCopyAllRoleHandlersForContentType.restype = ptr
bundle = cf.CFStringCreateWithCString(None, identifier.encode('utf-8'), UTF8)
error = c.c_int32(0)
applications = ls.LSCopyApplicationURLsForBundleIdentifier(bundle, c.byref(error))
paths = []
if applications:
    try:
        for index in range(cf.CFArrayGetCount(applications)):
            item = cf.CFURLCopyFileSystemPath(cf.CFArrayGetValueAtIndex(applications, index), 0)
            try:
                paths.append(text(item))
            finally:
                if item:
                    cf.CFRelease(item)
    finally:
        cf.CFRelease(applications)
cf.CFRelease(bundle)
uti = cf.CFStringCreateWithCString(None, b'com.adobe.pdf', UTF8)
handlers = ls.LSCopyAllRoleHandlersForContentType(uti, ALL_ROLES)
handler_ids = []
if handlers:
    try:
        handler_ids = [text(cf.CFArrayGetValueAtIndex(handlers, i))
                       for i in range(cf.CFArrayGetCount(handlers))]
    finally:
        cf.CFRelease(handlers)
cf.CFRelease(uti)
probe_uti = None
uti_error = None
try:
    cf.CFURLCopyResourcePropertyForKey.argtypes = [ptr, ptr, c.POINTER(ptr), c.POINTER(ptr)]
    cf.CFURLCopyResourcePropertyForKey.restype = c.c_bool
    key = c.c_void_p.in_dll(cf, 'kCFURLTypeIdentifierKey').value
    probe_url = url(probe)
    value, native_error = ptr(), ptr()
    try:
        if cf.CFURLCopyResourcePropertyForKey(probe_url, key, c.byref(value), c.byref(native_error)):
            probe_uti = text(value)
    finally:
        if value:
            cf.CFRelease(value)
        if native_error:
            cf.CFRelease(native_error)
        cf.CFRelease(probe_url)
except (AttributeError, OSError, ValueError) as exception:
    uti_error = type(exception).__name__
print(json.dumps({'registered_bundle_paths': paths, 'bundle_lookup_status': error.value,
                  'declares_pdf_handler': identifier in handler_ids,
                  'pdf_handler_count': len(handler_ids), 'probe_uti': probe_uti,
                  'probe_uti_error': uti_error}, ensure_ascii=False))
"""
        response = subprocess.run([sys.executable, '-c', script, identifier, str(probe)],
                                  check=True, capture_output=True, text=True,
                                  encoding='utf-8', timeout=15)
        return json.loads(response.stdout)

    def test_real_compile_registration_and_open_documents_argv(self):
        if not all(Path(tool).is_file() for tool in ('/usr/bin/osacompile', '/usr/bin/codesign', '/usr/bin/open')):
            self.skipTest('Standard macOS applet tools are unavailable')
        menu = load_module()
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
            # This test registers only a unique synthetic bundle, never the
            # production bundle id or the real codex:// default application.
            identifier = 'org.codex-pdf-previewer.integration.' + uuid.uuid4().hex
            diagnostics = []
            real_query = menu._query

            def captured_query(probe):
                response = real_query(probe)
                diagnostics.append({'synthetic_probe': str(probe), 'result': response})
                return response

            expected_app = (base / 'profile/pdf-previewer-menu/macos' / menu.APP_NAME).resolve()
            with patch.object(menu, 'BUNDLE_ID', identifier), \
                    patch.object(menu, '_query', side_effect=captured_query):
                result = menu.install_menu(package, base / 'profile', launcher=gui)
                if result['status'] != 'installed':
                    self.fail(json.dumps({'installation': result,
                                          'expected_synthetic_bundle_id': identifier,
                                          'expected_synthetic_app': str(expected_app),
                                          'native_queries': diagnostics}, ensure_ascii=False, indent=2))
                self.assertTrue(result['viewer_discovered'])
                self.assertFalse(result['ui_verified'])
                app = Path(result['app_bundle'])
                subprocess.run(['/usr/bin/open', '-a', str(app), str(document)], check=True,
                               capture_output=True, text=True, timeout=20)
                self._wait_for_records(record, 1)
                subprocess.run(['/usr/bin/open', '-a', str(app), str(second), str(document)],
                               check=True, capture_output=True, text=True, timeout=20)
                rows = self._wait_for_records(record, 3)
                expected_prefix = ['--launcher', str(gui.resolve()), '--state-dir', result['state_dir']]
                self.assertEqual(rows[0], expected_prefix + [str(document)])
                self.assertCountEqual(rows[1:], [expected_prefix + [str(second)],
                                                expected_prefix + [str(document)]])
                probe = base / 'probe.pdf'
                probe.write_bytes(sample_pdf())
                after = menu._query(probe)
                self.assertTrue(menu._discovered(after, app))

    def _wait_for_records(self, record, count):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if record.exists():
                rows = [json.loads(line) for line in record.read_text(encoding='utf-8').splitlines()]
                if len(rows) >= count:
                    return rows
            time.sleep(0.1)
        self.fail('The synthetic applet did not receive the expected Open Documents events')


if __name__ == '__main__':
    unittest.main()
