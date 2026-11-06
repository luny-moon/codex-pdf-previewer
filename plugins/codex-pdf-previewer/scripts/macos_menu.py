"""Install an optional, managed macOS PDF application without changing defaults."""
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

BUNDLE_ID = 'org.codex-pdf-previewer.open-pdf'
APP_NAME = 'Codex PDF Previewer.app'
MANIFEST = 'codex-pdf-previewer-managed.json'
MANAGED_KEY = 'CodexPDFPreviewerManaged'
DISCOVERY_TIMEOUT = 3.0
DISCOVERY_POLL_INTERVAL = 0.15


class MenuSetupError(Exception):
    pass


# Run in a separate Python process so native framework loading never changes the
# installer's process. All operations here use public Launch Services APIs.
LS_HELPER = r'''
import ctypes as c
import json
import plistlib
import sys
from pathlib import Path
cf = c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
ls = c.CDLL('/System/Library/Frameworks/CoreServices.framework/CoreServices')
ptr = c.c_void_p
cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ptr, c.c_char_p, c.c_long, c.c_bool]
cf.CFURLCreateFromFileSystemRepresentation.restype = ptr
cf.CFStringCreateWithCString.argtypes = [ptr, c.c_char_p, c.c_uint32]
cf.CFStringCreateWithCString.restype = ptr
cf.CFStringGetLength.argtypes = [ptr]
cf.CFStringGetLength.restype = c.c_long
cf.CFStringGetMaximumSizeForEncoding.argtypes = [c.c_long, c.c_uint32]
cf.CFStringGetMaximumSizeForEncoding.restype = c.c_long
cf.CFStringGetCString.argtypes = [ptr, c.c_char_p, c.c_long, c.c_uint32]
cf.CFStringGetCString.restype = c.c_bool
cf.CFRelease.argtypes = [ptr]
cf.CFURLCopyFileSystemPath.argtypes = [ptr, c.c_int]
cf.CFURLCopyFileSystemPath.restype = ptr
cf.CFArrayGetCount.argtypes = [ptr]
cf.CFArrayGetCount.restype = c.c_long
cf.CFArrayGetValueAtIndex.argtypes = [ptr, c.c_long]
cf.CFArrayGetValueAtIndex.restype = ptr
ls.LSRegisterURL.argtypes = [ptr, c.c_bool]
ls.LSRegisterURL.restype = c.c_int32
ls.LSCopyDefaultRoleHandlerForContentType.argtypes = [ptr, c.c_uint32]
ls.LSCopyDefaultRoleHandlerForContentType.restype = ptr
ls.LSCopyApplicationURLsForURL.argtypes = [ptr, c.c_uint32]
ls.LSCopyApplicationURLsForURL.restype = ptr
UTF8 = 0x08000100
ALL_ROLES = 0xffffffff

def text(value):
    if not value:
        return None
    size = cf.CFStringGetMaximumSizeForEncoding(cf.CFStringGetLength(value), UTF8) + 1
    buffer = c.create_string_buffer(size)
    if not cf.CFStringGetCString(value, buffer, size, UTF8):
        raise RuntimeError('Could not read a native string')
    return buffer.value.decode('utf-8')

def url(path, directory=False):
    data = str(path).encode('utf-8')
    result = cf.CFURLCreateFromFileSystemRepresentation(None, data, len(data), directory)
    if not result:
        raise RuntimeError('Could not make a file URL')
    return result

operation, path = sys.argv[1:3]
if operation == 'register':
    value = url(path, True)
    try:
        if ls.LSRegisterURL(value, True):
            raise RuntimeError('Launch Services could not register the application')
    finally:
        cf.CFRelease(value)
    print(json.dumps({'registered': True}))
elif operation == 'query':
    uti = cf.CFStringCreateWithCString(None, b'com.adobe.pdf', UTF8)
    default = ls.LSCopyDefaultRoleHandlerForContentType(uti, ALL_ROLES)
    try:
        default_id = text(default)
    finally:
        if default:
            cf.CFRelease(default)
        cf.CFRelease(uti)
    value = url(path)
    applications = ls.LSCopyApplicationURLsForURL(value, ALL_ROLES)
    result = []
    try:
        if applications:
            for index in range(cf.CFArrayGetCount(applications)):
                app = cf.CFArrayGetValueAtIndex(applications, index)
                app_path = cf.CFURLCopyFileSystemPath(app, 0)
                try:
                    location = text(app_path)
                finally:
                    if app_path:
                        cf.CFRelease(app_path)
                if not location:
                    continue
                try:
                    with (Path(location) / 'Contents/Info.plist').open('rb') as stream:
                        info = plistlib.load(stream)
                except (OSError, ValueError, plistlib.InvalidFileException):
                    continue
                result.append({'appPath': location,
                               'bundleId': info.get('CFBundleIdentifier', ''),
                               'displayName': info.get('CFBundleDisplayName') or info.get('CFBundleName') or Path(location).stem})
    finally:
        if applications:
            cf.CFRelease(applications)
        cf.CFRelease(value)
    print(json.dumps({'default_handler': default_id, 'applications': result}, ensure_ascii=False))
else:
    raise RuntimeError('Unsupported native operation')
'''


def _skip(reason, **extra):
    return {'status': 'skipped', 'reason': reason, **extra}


def _safe_path(value):
    return isinstance(value, (str, os.PathLike)) and not any(c in str(value) for c in '\0\r\n')


def _valid_gui(value):
    if not value or not _safe_path(value):
        return None
    app = Path(value).expanduser()
    if not app.is_absolute() or app.suffix != '.app':
        return None
    try:
        app = app.resolve(strict=True)
        if app.suffix != '.app':
            return None
        with (app / 'Contents/Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
        identifier = info.get('CFBundleIdentifier', '')
        if identifier not in ('com.openai.codex', 'com.openai.chat') and not identifier.startswith('com.openai.codex.'):
            return None
        # The shared launcher submits codex://browser. A similarly named old
        # ChatGPT bundle without that URL claim is not a compatible GUI.
        types = info.get('CFBundleURLTypes', [])
        if not isinstance(types, list):
            return None
        schemes = {scheme.lower() for item in types if isinstance(item, dict)
                   if isinstance(item.get('CFBundleURLSchemes'), list)
                   for scheme in item['CFBundleURLSchemes'] if isinstance(scheme, str)}
        if 'codex' not in schemes:
            return None
        executable = info.get('CFBundleExecutable')
        if not isinstance(executable, str) or not executable or Path(executable).name != executable:
            return None
        binary = app / 'Contents/MacOS' / executable
        return app if binary.is_file() and os.access(binary, os.X_OK) else None
    except (OSError, ValueError, plistlib.InvalidFileException, AttributeError):
        return None


def _discover_gui(launcher=None):
    requested = launcher or os.environ.get('CODEX_PDF_PREVIEWER_GUI')
    if requested:
        return _valid_gui(requested)
    # Never use the executable named codex: that is usually the CLI.
    for candidate in (Path('/Applications/Codex.app'), Path('/Applications/ChatGPT.app'),
                      Path.home() / 'Applications/Codex.app', Path.home() / 'Applications/ChatGPT.app'):
        app = _valid_gui(candidate)
        if app is not None:
            return app
    return None


def _run(argv, message):
    try:
        return subprocess.run([str(arg) for arg in argv], check=True, capture_output=True,
                              text=True, encoding='utf-8', timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        raise MenuSetupError(message) from error


def _services(operation, path):
    response = _run([sys.executable, '-c', LS_HELPER, operation, path],
                    'macOS could not inspect or register the PDF application.')
    try:
        result = json.loads(response.stdout)
        if (not isinstance(result, dict)
                or operation == 'register' and result.get('registered') is not True):
            raise ValueError('Invalid result')
        return result
    except (ValueError, TypeError) as error:
        raise MenuSetupError('macOS returned an invalid application registration result.') from error


def _source(package_root, gui, state):
    # JSON string literals plus NSTask's argument array keep paths out of shell
    # syntax. openDocuments is the JXA application Open Documents event handler.
    fixed = json.dumps([str(package_root / 'scripts/menu_open.py'), '--launcher', str(gui),
                        '--state-dir', str(state)], ensure_ascii=True)
    python = json.dumps(str(Path(sys.executable).resolve()), ensure_ascii=True)
    return ('ObjC.import("Foundation");\n'
            'function openDocuments(documents) {\n'
            '  for (var index = 0; index < documents.length; index++) {\n'
            '    var task = $.NSTask.alloc.init;\n'
            '    task.executableURL = $.NSURL.fileURLWithPath(' + python + ');\n'
            '    task.arguments = $(' + fixed + '.concat([String(documents[index])]));\n'
            '    var error = Ref();\n'
            '    if (!task.launchAndReturnError(error)) throw new Error("Could not start PDF previewer");\n'
            '    task.waitUntilExit;\n'
            '    if (task.terminationStatus !== 0) throw new Error("Could not open the PDF in Codex");\n'
            '  }\n'
            '}\n')


def _plist():
    return {'CFBundleIdentifier': BUNDLE_ID, 'CFBundleName': 'Codex PDF Previewer',
            'CFBundleDisplayName': '用高清 PDF 插件打开', 'CFBundlePackageType': 'APPL',
            'LSUIElement': True, MANAGED_KEY: True,
            'CFBundleDocumentTypes': [{'CFBundleTypeName': 'PDF document',
                                      'CFBundleTypeRole': 'Viewer', 'LSHandlerRank': 'Alternate',
                                      'LSItemContentTypes': ['com.adobe.pdf']}]}


def _manifest(app):
    if app.is_symlink() or not app.is_dir():
        return None
    try:
        location = app / 'Contents/Resources' / MANIFEST
        if location.is_symlink():
            return None
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        record = json.loads(location.read_text(encoding='utf-8'))
        if (info.get('CFBundleIdentifier') != BUNDLE_ID or info.get(MANAGED_KEY) is not True
                or record.get('managed') is not True or record.get('bundle_id') != BUNDLE_ID
                or record.get('format') != 1):
            return None
        return record
    except (OSError, ValueError, plistlib.InvalidFileException, AttributeError):
        return None


def _digest(app):
    digest = hashlib.sha256()
    for item in sorted(app.rglob('*')):
        relative = item.relative_to(app).as_posix().encode('utf-8')
        digest.update(relative + b'\0')
        if item.is_symlink():
            digest.update(b'link\0' + os.readlink(item).encode('utf-8'))
        elif item.is_file():
            digest.update(item.read_bytes())
    return digest.hexdigest()



def _read_record(path):
    if path.is_symlink():
        raise MenuSetupError('The macOS menu installation record is a symbolic link; left it unchanged.')
    return path.read_bytes() if path.exists() else None


def _write_record(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.installation-', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _query(probe):
    result = _services('query', probe)
    if not isinstance(result.get('applications'), list):
        raise MenuSetupError('macOS could not enumerate PDF applications.')
    default = result.get('default_handler')
    if default is not None and not isinstance(default, str):
        raise MenuSetupError('macOS returned an invalid default PDF application.')
    return result


def _discovered(result, app):
    try:
        expected = app.resolve(strict=True)
    except OSError:
        return False
    for item in result['applications']:
        if not isinstance(item, dict) or item.get('bundleId') != BUNDLE_ID:
            continue
        value = item.get('appPath')
        if not isinstance(value, str) or not _safe_path(value):
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            continue
        try:
            if candidate.resolve(strict=True) == expected or candidate.samefile(expected):
                return True
        except OSError:
            continue
    return False


def _wait_for_discovery(probe, app, default_handler):
    # LSRegisterURL can finish before other Launch Services readers observe its
    # document claim. Keep both the real viewer-discovery and default guards.
    deadline = time.monotonic() + DISCOVERY_TIMEOUT
    while True:
        result = _query(probe)
        if result['default_handler'] != default_handler:
            raise MenuSetupError('The default PDF application changed during registration.')
        if _discovered(result, app):
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MenuSetupError('macOS did not discover the generated PDF application.')
        time.sleep(min(DISCOVERY_POLL_INTERVAL, remaining))


def _installed(app, gui, state, changed):
    return {'status': 'installed', 'app_bundle': str(app), 'bundle_id': BUNDLE_ID,
            'launcher': str(gui), 'state_dir': str(state), 'changed': changed,
            'pdf_default_unchanged': True, 'os_registered': True,
            'viewer_discovered': True, 'ui_verified': False,
            'visibility_note': 'Codex displays at most five PDF applications; the native menu order can limit visibility.'}


def _install_locked(package, setup, gui):
    app = setup / APP_NAME
    state = setup / 'state'
    previous = _manifest(app) if app.exists() or app.is_symlink() else None
    if (app.exists() or app.is_symlink()) and previous is None:
        return _skip('An unmanaged application already owns the macOS PDF menu location; left it unchanged.')
    sidecar = setup / 'installation.json'
    old_sidecar = _read_record(sidecar)
    if old_sidecar is not None:
        try:
            installed = json.loads(old_sidecar)
        except ValueError:
            installed = None
        if (not isinstance(installed, dict) or installed.get('managed') is not True
                or installed.get('bundle_id') != BUNDLE_ID or installed.get('format') != 1):
            return _skip('An unmanaged record owns the macOS menu setup location; left it unchanged.')
    else:
        installed = None
    if previous is not None and (installed is None
            or installed.get('fingerprint') != previous.get('fingerprint')
            or installed.get('content_sha256') != _digest(app)):
        return _skip('The managed macOS PDF application changed outside this installer; left it unchanged.')
    if previous is None and installed is not None:
        return _skip('An earlier macOS menu record has no matching application; left it unchanged for recovery.')
    source = _source(package, gui, state)
    fingerprint = hashlib.sha256((source + json.dumps(_plist(), sort_keys=True)).encode('utf-8')).hexdigest()
    with tempfile.TemporaryDirectory(prefix='.pdf-menu-', dir=setup) as temporary:
        staging = Path(temporary)
        probe = staging / 'registration-probe.pdf'
        probe.write_bytes(b'%PDF-1.4\n% Synthetic registration probe.\n%%EOF\n')
        before = _query(probe)
        if not before['default_handler']:
            return _skip('No existing default PDF application was found; menu setup was skipped to preserve that choice.')
        if previous is not None and previous.get('fingerprint') == fingerprint:
            if not _discovered(before, app):
                _services('register', app)
            _wait_for_discovery(probe, app, before['default_handler'])
            return _installed(app, gui, state, False)
        source_file = staging / 'wrapper.js'
        source_file.write_text(source, encoding='utf-8')
        compiled = staging / APP_NAME
        _run(['/usr/bin/osacompile', '-l', 'JavaScript', '-o', compiled, source_file],
             'macOS could not compile the PDF application wrapper.')
        info_path = compiled / 'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info.update(_plist())
        info_path.write_bytes(plistlib.dumps(info))
        resources = compiled / 'Contents/Resources'
        resources.mkdir(parents=True, exist_ok=True)
        record = {'format': 1, 'managed': True, 'bundle_id': BUNDLE_ID,
                  'fingerprint': fingerprint}
        manifest_path = resources / MANIFEST
        manifest_path.write_text(json.dumps(record, sort_keys=True) + '\n', encoding='utf-8')
        _run(['/usr/bin/codesign', '--force', '--sign', '-', compiled],
             'macOS could not sign the generated PDF application wrapper.')
        _run(['/usr/bin/codesign', '--verify', '--strict', compiled],
             'macOS could not verify the generated PDF application wrapper.')
        # Keep the digest outside the signed resources. The manifest is included
        # in the signature and is not changed after signing.
        content_digest = _digest(compiled)
        desired_sidecar = (json.dumps({**record, 'content_sha256': content_digest},
                                      sort_keys=True) + '\n').encode('utf-8')
        backup = None
        published = False
        try:
            if _read_record(sidecar) != old_sidecar:
                raise MenuSetupError('The macOS menu installation record changed during setup; left it unchanged.')
            if previous is None and (app.exists() or app.is_symlink()):
                raise MenuSetupError('Another application appeared at the macOS menu location; left it unchanged.')
            if previous is not None and (_manifest(app) != previous
                    or _digest(app) != installed['content_sha256']):
                raise MenuSetupError('The macOS PDF application changed during setup; left it unchanged.')
            if previous is not None:
                backup = setup / 'backups' / ('install-' + uuid.uuid4().hex)
                backup.mkdir(parents=True, mode=0o700)
                (backup / 'manifest.json').write_text(json.dumps({'default_handler': before['default_handler'],
                                                                'app_bundle': str(app)}), encoding='utf-8')
                os.replace(app, backup / APP_NAME)
            os.replace(compiled, app)
            published = True
            # An external sidecar avoids modifying resources after codesigning.
            _write_record(sidecar, desired_sidecar)
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            _services('register', app)
            _wait_for_discovery(probe, app, before['default_handler'])
            return _installed(app, gui, state, True)
        except (OSError, ValueError, MenuSetupError, plistlib.InvalidFileException) as error:
            rollback_error = False
            try:
                if published:
                    current = _manifest(app)
                    if current is None or _digest(app) != content_digest:
                        raise MenuSetupError('The generated wrapper changed outside this installer.')
                    shutil.rmtree(app)
                if backup is not None:
                    shutil.copytree(backup / APP_NAME, app, symlinks=True)
                    _services('register', app)
                current_sidecar = _read_record(sidecar)
                if current_sidecar != old_sidecar:
                    if current_sidecar != desired_sidecar:
                        raise MenuSetupError('The macOS menu installation record changed outside this installer.')
                    if old_sidecar is None:
                        sidecar.unlink(missing_ok=True)
                    else:
                        _write_record(sidecar, old_sidecar)
            except (OSError, MenuSetupError):
                rollback_error = True
            return _skip(str(error), rollback_failed=rollback_error,
                         backup_dir=str(backup) if backup else None)


def install_menu(package_root, codex_home, launcher=None):
    if sys.platform != 'darwin':
        return _skip('The macOS PDF application is available only on macOS.')
    try:
        if not _safe_path(package_root) or not _safe_path(codex_home):
            return _skip('A macOS PDF menu path contains an unsupported control character.')
        package = Path(package_root).expanduser().resolve(strict=True)
        if not (package / 'scripts/menu_open.py').is_file():
            return _skip('The durable PDF menu launcher is unavailable.')
        gui = _discover_gui(launcher)
        if gui is None:
            return _skip('A verified Codex or ChatGPT application bundle was not found; core plugin installation is unaffected.')
        for tool in ('/usr/bin/osacompile', '/usr/bin/codesign'):
            if not Path(tool).is_file() or not os.access(tool, os.X_OK):
                return _skip('A required macOS application tool is unavailable; core plugin installation is unaffected.')
        setup = Path(codex_home).expanduser().resolve() / 'pdf-previewer-menu/macos'
        if setup.is_symlink() or setup.parent.is_symlink():
            return _skip('The macOS PDF menu setup location is a symbolic link; left it unchanged.')
        setup.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = setup / '.install-lock'
        try:
            lock.mkdir(mode=0o700)
        except FileExistsError:
            return _skip('Another macOS PDF menu installation is in progress; retry later.')
        try:
            return _install_locked(package, setup, gui)
        finally:
            lock.rmdir()
    except (OSError, ValueError, MenuSetupError, plistlib.InvalidFileException):
        return _skip('macOS PDF menu setup could not complete; core plugin installation is unaffected.')
