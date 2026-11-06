"""Install an optional user-level Linux PDF Open in menu entry."""
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

DESKTOP_ID = 'codex-pdf-previewer.desktop'
MIME_TYPE = 'application/pdf'
MANAGED_KEY = 'X-Codex-PDF-Previewer-Managed'


class MenuSetupError(Exception):
    pass


def _skip(reason, **extra):
    return {'status': 'skipped', 'reason': reason, **extra}


def _xdg_path(variable, fallback):
    value = os.environ.get(variable)
    return Path(value) if value and Path(value).is_absolute() else fallback


def _valid_executable(value):
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() or any(c in str(path) for c in '\0\r\n'):
        return None
    try:
        path = path.resolve(strict=True)
        return path if path.is_file() and os.access(path, os.X_OK) else None
    except OSError:
        return None


def _discover_launcher(launcher=None):
    requested = launcher or os.environ.get('CODEX_PDF_PREVIEWER_GUI')
    if requested:
        return _valid_executable(requested)
    # The command named codex is normally the CLI, not the desktop launcher.
    candidates = [shutil.which('chatgpt'), shutil.which('codex-launcher'),
                  '/usr/lib/chatgpt/codex-launcher', '/opt/ChatGPT/codex-launcher',
                  '/opt/Codex/codex-launcher']
    for candidate in candidates:
        path = _valid_executable(candidate)
        if path is not None and path.name.lower() != 'codex':
            return path
    return None


def desktop_quote(argument):
    """Quote one literal Exec argument, including desktop-entry key escaping."""
    value = str(argument)
    if any(c in value for c in '\0\r\n'):
        raise MenuSetupError('A menu command path contains an unsupported control character.')
    # Percent field codes are expanded even inside quotes. Only the final %f
    # appended by _desktop_file is a field code; all path percents are literal.
    value = value.replace('%', '%%')
    value = ''.join('\\' + c if c in '\\"`$' else c for c in value)
    value = value.replace('\\', '\\\\').replace('\t', '\\t')
    return '"' + value + '"'


def _desktop_file(package_root, launcher, state_dir):
    python = Path(sys.executable).resolve()
    # GIO checks the first executable before expanding %% field escapes. Resolve
    # common venv/symlink paths, and skip the exceptional unrepresentable case.
    if '%' in str(python):
        raise MenuSetupError('The Python executable path contains %; Linux menu setup was skipped because GIO cannot load that executable path.')
    argv = [python, package_root / 'scripts' / 'menu_open.py',
            '--launcher', launcher, '--state-dir', state_dir]
    command = ' '.join(desktop_quote(value) for value in argv) + ' %f'
    return ('[Desktop Entry]\nType=Application\nName=用高清 PDF 插件打开\n'
            'Comment=Open a high-resolution PDF preview inside Codex\n'
            'NoDisplay=true\nTerminal=false\nStartupNotify=false\n'
            'Icon=application-pdf\nMimeType=application/pdf;\n'
            'Categories=Office;Viewer;\n' + MANAGED_KEY + '=true\n'
            'Exec=' + command + '\n').encode('utf-8')


def _desktop_values(data):
    values, in_entry = {}, False
    for line in data.decode('utf-8').splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            in_entry = line == '[Desktop Entry]'
        elif in_entry and '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            values[key] = value
    return values


def _owned_desktop(data):
    try:
        values = _desktop_values(data)
        if values.get(MANAGED_KEY) == 'true':
            return True
        # Recognize the earlier local manual setup by its command and UI
        # semantics, without embedding anyone's home directory in the package.
        if (values.get('Name') != '用高清 PDF 插件打开' or
                values.get('Comment') != 'Open a high-resolution PDF preview inside Codex'):
            return False
        command = shlex.split(values.get('Exec', ''))
        return (len(command) == 3 and Path(command[0]).name.startswith('python')
                and Path(command[1]).is_absolute()
                and Path(command[1]).parts[-2:] == ('codex-pdf-previewer-client', 'menu-handler.py')
                and command[2] == '%f')
    except (UnicodeError, ValueError):
        return False


def _add_association(data):
    text = data.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines(keepends=True)
    sections = [i for i, line in enumerate(lines) if line.strip() == '[Added Associations]']
    if len(sections) > 1:
        raise MenuSetupError('The Linux MIME association file has duplicate sections; left it unchanged.')
    if not sections:
        suffix = '' if not text or text.endswith(('\n', '\r')) else newline
        if text and not text.endswith(newline + newline):
            suffix += newline
        return (text + suffix + '[Added Associations]' + newline +
                MIME_TYPE + '=' + DESKTOP_ID + ';' + newline).encode('utf-8')
    start = sections[0] + 1
    end = next((i for i in range(start, len(lines)) if lines[i].strip().startswith('[')), len(lines))
    keys = [i for i in range(start, end)
            if re.match(r'^\s*application/pdf\s*=', lines[i])]
    if len(keys) > 1:
        raise MenuSetupError('The Linux MIME association file has duplicate PDF entries; left it unchanged.')
    if keys:
        index = keys[0]
        entries = [entry.strip() for entry in lines[index].split('=', 1)[1].strip().split(';')
                   if entry.strip() and entry.strip() != DESKTOP_ID]
        prefix = lines[index].split('=', 1)[0] + '='
        replacement = prefix + ';'.join([DESKTOP_ID, *entries]) + ';' + newline
        if replacement.rstrip('\r\n') == lines[index].rstrip('\r\n'):
            return data
        lines[index] = replacement
    else:
        if start and not lines[start - 1].endswith(('\n', '\r')):
            lines[start - 1] += newline
        lines.insert(start, MIME_TYPE + '=' + DESKTOP_ID + ';' + newline)
    return ''.join(lines).encode('utf-8')


def _query_gio(gio):
    env = dict(os.environ, LC_ALL='C', LANG='C')
    result = subprocess.run([str(gio), 'mime', MIME_TYPE], env=env, capture_output=True,
                            text=True, encoding='utf-8', timeout=15)
    if result.returncode:
        raise MenuSetupError('Linux could not inspect the current PDF application; menu setup was skipped.')
    match = re.search(r'^Default application for .*?:\s*([A-Za-z0-9_.+-]+\.desktop)\s*$',
                      result.stdout, re.MULTILINE)
    return (match.group(1) if match else None), result.stdout


def _discovered(output):
    return re.search(r'^\s*' + re.escape(DESKTOP_ID) + r'\s*$', output, re.MULTILINE) is not None


def _snapshot(path):
    if path.is_symlink():
        raise MenuSetupError('A Linux menu configuration file is a symbolic link; left it unchanged.')
    if not path.exists():
        return {'data': None, 'mode': 0o600}
    if not path.is_file():
        raise MenuSetupError('A Linux menu configuration path is not a regular file; left it unchanged.')
    return {'data': path.read_bytes(), 'mode': stat.S_IMODE(path.stat().st_mode)}


def _atomic_write(path, data, mode):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.pdf-menu-', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _rollback(changes, originals):
    failed = []
    for path, desired in reversed(list(changes.items())):
        try:
            current = _snapshot(path)['data']
            old = originals[path]
            if current == old['data']:
                continue
            if current != desired:
                raise MenuSetupError('Configuration changed outside this installer.')
            if old['data'] is None:
                path.unlink()
            else:
                _atomic_write(path, old['data'], old['mode'])
        except (OSError, MenuSetupError):
            failed.append(str(path))
    return failed


def _install_locked(package_root, home, launcher, gio, setup_root):
    data_home = _xdg_path('XDG_DATA_HOME', Path.home() / '.local' / 'share')
    config_home = _xdg_path('XDG_CONFIG_HOME', Path.home() / '.config')
    desktop = data_home / 'applications' / DESKTOP_ID
    mimeapps = config_home / 'mimeapps.list'
    before_default, _ = _query_gio(gio)
    if before_default is None:
        return _skip('No existing default PDF application was found; menu setup was skipped to preserve that choice.')
    originals = {path: _snapshot(path) for path in (desktop, mimeapps)}
    if originals[desktop]['data'] is not None and not _owned_desktop(originals[desktop]['data']):
        return _skip('A different application already owns the PDF previewer menu file; left it unchanged.')
    state_dir = setup_root / 'state'
    changes = {desktop: _desktop_file(package_root, launcher, state_dir),
               mimeapps: _add_association(originals[mimeapps]['data'] or b'')}
    result = {'status': 'installed', 'desktop_id': DESKTOP_ID, 'desktop_file': str(desktop),
              'launcher': str(launcher), 'state_dir': str(state_dir), 'pdf_default_unchanged': True}
    if all(originals[path]['data'] == desired for path, desired in changes.items()):
        after_default, available = _query_gio(gio)
        if after_default != before_default:
            return _skip('The default PDF application changed during inspection; menu files were left unchanged.')
        if not _discovered(available):
            return _skip('Linux has not discovered the existing PDF menu entry; core plugin installation is unaffected.')
        return {**result, 'changed': False}
    backup = setup_root / 'backups' / ('install-' + uuid.uuid4().hex)
    backup.mkdir(parents=True, mode=0o700)
    files = []
    for index, (path, old) in enumerate(originals.items()):
        name = f'{index}.original'
        if old['data'] is not None:
            _atomic_write(backup / name, old['data'], 0o600)
        files.append({'path': str(path), 'existed': old['data'] is not None, 'mode': old['mode'],
                      'backup': name if old['data'] is not None else None,
                      'sha256': hashlib.sha256(old['data']).hexdigest() if old['data'] is not None else None})
    _atomic_write(backup / 'manifest.json', (json.dumps({'files': files, 'pdf_default': before_default},
                                                      indent=2) + '\n').encode(), 0o600)
    try:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        state_dir.chmod(0o700)
        for path, desired in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if _snapshot(path)['data'] != originals[path]['data']:
                raise MenuSetupError('Linux menu settings changed during setup; retry installation.')
            if desired != originals[path]['data']:
                _atomic_write(path, desired, originals[path]['mode'])
        after_default, available = _query_gio(gio)
        if after_default != before_default:
            raise MenuSetupError('Linux changed the default PDF application; menu setup was rolled back.')
        if not _discovered(available):
            raise MenuSetupError('Linux did not discover the PDF menu entry; menu setup was rolled back.')
        return {**result, 'changed': True, 'backup_dir': str(backup)}
    except (OSError, ValueError, UnicodeError, MenuSetupError, subprocess.SubprocessError) as error:
        failed = _rollback(changes, originals)
        reason = str(error) if isinstance(error, MenuSetupError) else 'Linux menu setup failed; original settings were restored.'
        if failed:
            reason = 'Linux menu setup failed and some files could not be restored; keep the saved backup.'
        return _skip(reason, backup_dir=str(backup), rollback_failed=failed)


def install_menu(package_root, codex_home, launcher=None):
    """Install the optional menu without ever changing the default PDF app.

    Missing Linux integration returns status=skipped; the core plugin can still
    install. Backups retain exact previous bytes and file modes for rollback.
    """
    if sys.platform != 'linux':
        return _skip('The PDF Open in menu shortcut is currently available on Linux only.')
    gio = shutil.which('gio')
    if gio is None:
        return _skip('The Linux gio desktop integration tool is unavailable; the core plugin still works.')
    gui = _discover_launcher(launcher)
    if gui is None:
        return _skip('The Codex desktop launcher was not found; use --gui-launcher with its absolute path.')
    try:
        package_root = Path(package_root).expanduser().resolve()
        home = Path(codex_home).expanduser().resolve()
        if not (package_root / 'scripts' / 'menu_open.py').is_file():
            return _skip('The durable plugin source is missing its PDF menu opener.')
        setup_root = home / 'pdf-previewer-menu'
        setup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        setup_root.chmod(0o700)
        import fcntl
        with (setup_root / 'install.lock').open('a', encoding='utf-8') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            return _install_locked(package_root, home, gui, gio, setup_root)
    except (OSError, ValueError, UnicodeError, MenuSetupError, subprocess.SubprocessError) as error:
        return _skip(str(error) if isinstance(error, MenuSetupError)
                     else 'Linux menu setup could not be completed; the core plugin still works.')
