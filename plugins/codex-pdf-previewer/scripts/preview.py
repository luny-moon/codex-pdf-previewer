#!/usr/bin/env python3
"""Local PDF reader launcher. Python 3.10+, standard library only."""
import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.error import URLError
from urllib.parse import unquote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'assets' / 'reader'
PDFJS = ROOT / 'vendor' / 'pdfjs'
OPENER = build_opener(ProxyHandler({}))


class LoopbackServer(ThreadingHTTPServer):
    def server_bind(self):
        # A numeric loopback listener needs no reverse-DNS lookup. HTTPServer's
        # default getfqdn() can block startup on systems with slow host lookup.
        TCPServer.server_bind(self)
        self.server_name = '127.0.0.1'
        self.server_port = self.server_address[1]


def default_state_root():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    return base / 'codex-pdf-previewer'


def state_root(value=None):
    if value:
        result = Path(value).expanduser().resolve()
    else:
        result = default_state_root()
    result.mkdir(parents=True, exist_ok=True, mode=0o700)
    return result


def document_path(value):
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != '.pdf':
        raise ValueError('Expected an existing PDF file')
    with path.open('rb') as stream:
        if b'%PDF-' not in stream.read(1024):
            raise ValueError('The selected file does not have a PDF header')
    return path


def record_path(state, document):
    return state / (hashlib.sha256(os.path.normcase(str(document)).encode('utf-8')).hexdigest()[:24] + '.json')


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    temporary.replace(path)


def local_url(value):
    parts = urlsplit(value)
    if (parts.scheme != 'http' or parts.hostname != '127.0.0.1' or
            parts.username or parts.password or parts.path not in ('', '/') or
            parts.query or parts.fragment or not parts.port):
        raise ValueError('Expected http://127.0.0.1:<port>/')
    return f'http://127.0.0.1:{parts.port}/'


def request_json(url, **kwargs):
    with OPENER.open(Request(url, **kwargs), timeout=1) as response:
        return json.load(response)


def alive(record):
    try:
        url = local_url(record['url'])
        health = request_json(url + 'health.json')
        return health.get('instance') == record['instance'] and health.get('plugin') == 'codex-pdf-previewer'
    except (OSError, URLError, ValueError, KeyError, TypeError):
        return False


def same_pdf(url, document):
    """Explicitly adopt an already-open legacy reader without changing it."""
    url = local_url(url)
    try:
        # Require the existing reader's metadata route before fetching any bytes.
        request_json(url + 'meta.json')
        expected = hashlib.sha256()
        with document.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                expected.update(chunk)
        actual = hashlib.sha256()
        remaining = document.stat().st_size
        with OPENER.open(url + 'document.pdf', timeout=3) as stream:
            while chunk := stream.read(min(1024 * 1024, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    return False
                actual.update(chunk)
        return remaining == 0 and actual.digest() == expected.digest()
    except (OSError, URLError, ValueError):
        return False


@contextmanager
def session_lock(path):
    # Kernel locks are released even when a launcher exits unexpectedly.
    # Leave the lock file in place: unlinking it could let callers lock
    # different inodes for the same PDF.
    lock = path.with_suffix('.lock')
    with lock.open('a+b') as stream:
        os.chmod(lock, 0o600)
        if os.name == 'nt':
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'\0')
                stream.flush()
            def acquire():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(stream, fcntl.LOCK_UN)
        deadline = time.monotonic() + 15
        while True:
            try:
                acquire()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('Another launch is still pending; retry shortly')
                time.sleep(0.1)
        try:
            yield
        finally:
            release()


def start(args):
    document = document_path(args.pdf)
    if args.reuse_url and same_pdf(args.reuse_url, document):
        return {'url': local_url(args.reuse_url), 'pdf': str(document), 'reused': True, 'managed': False}
    state = state_root(args.state_dir)
    path = record_path(state, document)
    with session_lock(path):
        record = read_json(path)
        if os.path.normcase(record.get('pdf', '')) == os.path.normcase(str(document)) and alive(record):
            return public_record(record, reused=True)
        instance = secrets.token_hex(16)
        command = [sys.executable, str(Path(__file__).resolve()), 'serve', str(document),
                   '--state-dir', str(state), '--instance', instance, '--port', str(args.port)]
        log_path = path.with_suffix('.log')
        process_options = ({'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                           if os.name == 'nt' else {'start_new_session': True})
        with log_path.open('ab') as log:
            os.chmod(log_path, 0o600)
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     close_fds=True, **process_options)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(f'Preview exited; inspect {log_path}')
            record = read_json(path)
            if record.get('instance') == instance and alive(record):
                return public_record(record, reused=False)
            time.sleep(0.1)
        # Only terminate the child just created by this invocation.
        child.terminate()
        child.wait(timeout=5)
        raise RuntimeError(f'Preview did not start; inspect {log_path}')


def public_record(record, **extra):
    return {key: record[key] for key in ('url', 'pdf', 'pid')} | {'managed': True} | extra


def serve(args):
    document = document_path(args.pdf)
    if not (PDFJS / 'build/pdf.mjs').is_file():
        raise RuntimeError('Bundled PDF.js is missing; reinstall the complete plugin folder')
    state = state_root(args.state_dir)
    path = record_path(state, document)
    instance = args.instance or secrets.token_hex(16)
    shutdown_token = secrets.token_hex(32)

    class Handler(BaseHTTPRequestHandler):
        def authorized_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def headers_for(self, status, mime, size):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(size))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self' blob:; font-src 'self' blob: data:; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'self'")
            self.end_headers()

        def send_json(self, value, head=False):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.headers_for(200, 'application/json; charset=utf-8', len(data))
            if not head:
                self.wfile.write(data)

        def do_HEAD(self):
            self.send_content(head=True)

        def do_GET(self):
            self.send_content()

        def send_content(self, head=False):
            if not self.authorized_host():
                self.send_error(403, 'Loopback host required')
                return
            route = unquote(urlsplit(self.path).path)
            if route == '/health.json':
                self.send_json({'plugin': 'codex-pdf-previewer', 'instance': instance}, head)
                return
            if route == '/meta.json':
                self.send_json({'name': document.name}, head)
                return
            target = None
            if route == '/document.pdf':
                target = document
            elif route in ('/', '/index.html', '/entry.js', '/reader.js', '/reader.css'):
                target = WEB / ('index.html' if route == '/' else route[1:])
            elif route.startswith('/pdfjs/'):
                candidate = (PDFJS / route[len('/pdfjs/'):]).resolve()
                if candidate.is_relative_to(PDFJS.resolve()):
                    target = candidate
            if target is None or not target.is_file():
                self.send_error(404)
                return
            mime = {'.mjs': 'text/javascript', '.js': 'text/javascript', '.wasm': 'application/wasm'}.get(target.suffix)
            mime = mime or mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            try:
                # Reopen the path per request so an atomic PDF replacement is visible.
                with target.open('rb') as stream:
                    self.headers_for(200, mime, os.fstat(stream.fileno()).st_size)
                    if not head:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except OSError:
                self.send_error(404)

        def do_POST(self):
            if (not self.authorized_host() or urlsplit(self.path).path != '/__shutdown' or
                    not hmac.compare_digest(self.headers.get('X-Preview-Token', ''), shutdown_token)):
                self.send_error(403)
                return
            self.send_json({'stopping': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = LoopbackServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    record = {'url': f'http://127.0.0.1:{server.server_port}/', 'pdf': str(document),
              'pid': os.getpid(), 'instance': instance, 'shutdown_token': shutdown_token}
    write_json(path, record)
    print(json.dumps(public_record(record), ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if read_json(path).get('instance') == instance:
            path.unlink(missing_ok=True)


def stop_record(path, record):
    if not alive(record):
        return {'pdf': record.get('pdf'), 'stopped': False, 'reason': 'already stopped'}
    request_json(local_url(record['url']) + '__shutdown', method='POST', data=b'',
                 headers={'X-Preview-Token': record['shutdown_token']})
    deadline = time.monotonic() + 3
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    if alive(record):
        raise RuntimeError('Preview has not stopped yet; retry status')
    return {'pdf': record['pdf'], 'stopped': True}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('open', 'serve'):
        command = commands.add_parser(name)
        command.add_argument('pdf')
        command.add_argument('--port', type=int, default=0, help='0 chooses a free loopback port')
        command.add_argument('--state-dir')
        if name == 'open':
            command.add_argument('--reuse-url', help='Reuse an existing loopback reader only if PDF bytes match')
        else:
            command.add_argument('--instance', help=argparse.SUPPRESS)
    status = commands.add_parser('status')
    status.add_argument('--state-dir')
    stop = commands.add_parser('stop')
    stop.add_argument('pdf', nargs='?')
    stop.add_argument('--all', action='store_true')
    stop.add_argument('--state-dir')
    args = parser.parse_args()
    try:
        if args.command == 'serve':
            serve(args)
            return
        if args.command == 'open':
            result = start(args)
        else:
            state = state_root(args.state_dir)
            if args.command == 'status':
                result = []
                for path in sorted(state.glob('*.json')):
                    record = read_json(path)
                    if all(key in record for key in ('url', 'pdf', 'pid')):
                        result.append(public_record(record) | {'running': alive(record)})
            else:
                if bool(args.pdf) == args.all:
                    parser.error('stop needs one PDF path or --all')
                paths = sorted(state.glob('*.json')) if args.all else [record_path(state, Path(args.pdf).expanduser().resolve())]
                result = [stop_record(path, read_json(path)) for path in paths if path.is_file()]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
