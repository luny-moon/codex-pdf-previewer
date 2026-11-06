#!/usr/bin/env python3
"""Install this package into Codex using a durable local marketplace."""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = 'codex-pdf-previewer'
MARKETPLACE = 'codex-pdf-previewer-local'


def configure_menu(package_root, codex_home, launcher=None):
    if sys.platform != 'linux':
        return {'status': 'skipped', 'reason': 'PDF menu integration currently supports Linux'}
    spec = importlib.util.spec_from_file_location('codex_pdf_linux_menu',
                                                 package_root / 'scripts/linux_menu.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.install_menu(package_root, codex_home, launcher)


def install(codex_home=None, codex=None, menu=True, gui_launcher=None):
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required')
    executable = codex or shutil.which('codex')
    if not executable:
        raise RuntimeError('Locate the Codex desktop CLI and pass its path with --codex')
    manifest = json.loads((ROOT / 'plugin.json').read_text(encoding='utf-8'))
    if manifest.get('name') != NAME:
        raise ValueError('Unexpected plugin manifest')
    home = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()
    parent = home / 'plugin-sources' / NAME
    packages = parent / 'packages'
    if packages.is_relative_to(ROOT):
        raise ValueError('The Codex profile must be outside the plugin package')
    packages.mkdir(parents=True, exist_ok=True)
    # A durable source outside Downloads and the install cache survives moving
    # the ZIP and cannot overwrite an active reader's source during an upgrade.
    source = Path(tempfile.mkdtemp(prefix='source-', dir=packages))
    shutil.copytree(ROOT, source / 'plugin', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    catalog = parent / '.agents' / 'plugins' / 'marketplace.json'
    catalog.parent.mkdir(parents=True, exist_ok=True)
    temporary_catalog = catalog.with_suffix('.tmp')
    temporary_catalog.write_text(json.dumps({
        'name': MARKETPLACE,
        'interface': {'displayName': 'Codex PDF Previewer'},
        'plugins': [{
            'name': NAME,
            'source': {'source': 'local', 'path': './' + (source / 'plugin').relative_to(parent).as_posix()},
            'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_USE'},
            'category': 'Productivity',
        }],
    }, indent=2) + '\n', encoding='utf-8')
    temporary_catalog.replace(catalog)
    env = os.environ.copy()
    env['CODEX_HOME'] = str(home)
    for arguments in [
        ['plugin', 'marketplace', 'add', str(parent), '--json'],
        ['plugin', 'add', f'{NAME}@{MARKETPLACE}', '--json'],
    ]:
        result = subprocess.run([str(executable), *arguments], env=env, capture_output=True,
                                text=True, encoding='utf-8', timeout=90)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Codex could not install the plugin')
    menu_result = {'status': 'skipped', 'reason': 'Disabled with --no-menu'}
    if menu:
        try:
            menu_result = configure_menu(source / 'plugin', home, gui_launcher)
        except Exception:
            # The reader is installed even on systems without a supported GUI
            # launcher or desktop integration. Never fall back to a browser.
            menu_result = {'status': 'skipped', 'reason': 'PDF menu setup could not be completed'}
    # Do not print raw CLI installation records or make this the default reader.
    return {'installed': True, 'plugin': NAME, 'version': manifest['version'],
            'refresh_or_restart_codex': True, 'pdf_menu': menu_result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', help='Path to the Codex CLI if it is not on PATH')
    parser.add_argument('--codex-home', type=Path, help='Use a specific Codex profile')
    parser.add_argument('--gui-launcher', type=Path, help='Absolute Codex GUI launcher path for the Linux PDF menu')
    parser.add_argument('--no-menu', action='store_true', help='Install the reader without the Linux PDF menu')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.codex_home, args.codex, not args.no_menu, args.gui_launcher),
                         ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
