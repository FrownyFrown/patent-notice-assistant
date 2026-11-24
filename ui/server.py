"""로컬 진행 화면. 명령은 실행하지 않는다."""
import argparse
from collections import deque
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time
import unicodedata
from urllib.parse import parse_qs, unquote, urlsplit
import uuid
import webbrowser
from datetime import datetime

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from scripts.lib.state import atomic, now

MB = 1024 * 1024
CASE_ID = re.compile(r'[0-9A-Za-z][0-9A-Za-z-]{0,63}')
CSP = "default-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox; frame-ancestors 'self'"
WEB = Path(__file__).parent / 'web'
STATIC = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}


class Failure(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def clean_name(value):
    name = unicodedata.normalize('NFC', value).replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(c for c in name if not unicodedata.category(c).startswith('C') and c not in '<>:"/\\|?*')
    name = name.strip(' .')
    stem, dot, suffix = name.rpartition('.')
    if not dot or not stem or suffix.lower() not in ('pdf', 'txt'):
        raise ValueError('PDF 또는 TXT 이름이 필요합니다')
    if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]', stem.split('.')[0].rstrip(), re.I):
        stem = '_' + stem
    while len((stem + '.' + suffix).encode('utf-8')) > 150:
        stem = stem[:-1]
    return stem + '.' + suffix


def read_limited(path, limit):
    with path.open('rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise Failure(404, '파일이 없습니다')
        if os.fstat(stream.fileno()).st_size > limit:
            raise Failure(413, '파일이 너무 큽니다')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise Failure(413, '파일이 너무 큽니다')
    return data


def json_file(path, limit):
    return json.loads(read_limited(path, limit).decode('utf-8-sig'))


class LocalServer(ThreadingHTTPServer):
    # Windows 에서는 같은 포트에 두 번 묶일 수 있어 끈다. 그 밖에서는 바로 다시 열 수 있게 켠다.
    allow_reuse_address = os.name != 'nt'
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(root, port, token, chat_dir=None, allowed_host=''):
    server = LocalServer(('127.0.0.1', port), Handler, bind_and_activate=False)
    server.root = Path(root).resolve()
    server.port = port
    server.token = token
    server.chat_dir = Path(chat_dir).absolute() if chat_dir else None
    server.allowed_host = allowed_host
    server.lock = threading.Lock()
    server.chat_times = deque()
    return server


class Handler(BaseHTTPRequestHandler):
    timeout = 30

    def log_message(self, *args):
        pass

    def __getattr__(self, name):
        if name.startswith('do_'):
            return self.dispatch
        raise AttributeError(name)

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {'error': '요청을 처리할 수 없습니다'})

    def respond(self, status, body=b'', content_type='application/json; charset=utf-8', headers=None, preview=False):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Security-Policy', PREVIEW_CSP if preview else CSP)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Connection', 'close')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.close_connection = True
        if self.command != 'HEAD':
            self.wfile.write(body)

    def dispatch(self):
        try:
            self.guard()
            if self.command not in ('GET', 'POST'):
                raise Failure(405, '지원하지 않는 요청입니다')
            target = urlsplit(self.path)
            path = unquote(target.path, errors='strict')
            query = parse_qs(target.query)
            # 같은 호스트의 다른 프로그램 쿠키가 섞여도 읽히게 직접 나눈다.
            parts = [p.strip().partition('=') for p in self.headers.get('Cookie', '').split(';')]
            authenticated = any(k == self.cookie_name() and self.same(v) for k, _, v in parts)
            entry = self.command == 'GET' and path == '/' and len(query.get('token', [])) == 1 and self.same(query['token'][0])
            if not authenticated and not entry:
                if self.command == 'GET' and path in ('/', '/index.html'):
                    return self.respond(401, '화면을 닫고 실행 파일로 다시 열어 주세요'.encode('utf-8'), 'text/plain; charset=utf-8')
                raise Failure(401, '화면을 다시 열어 주세요')
            if target.scheme or target.netloc or '%' in path or '\\' in path or any(p in ('.', '..') for p in path.split('/')):
                raise Failure(404, '경로가 없습니다')
            if self.command == 'GET':
                self.get(path, entry)
            else:
                self.post(path, query)
        except Failure as exc:
            self.respond(exc.status, {'error': exc.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, UnicodeError, TypeError, RecursionError):
            self.respond(400, {'error': '내용을 확인해 주세요'})
        except (OSError, KeyError):
            self.respond(500, {'error': '파일을 읽거나 저장할 수 없습니다'})

    do_GET = dispatch
    do_POST = dispatch

    def cookie_name(self):
        return f'patent_ui_{self.server.port}'

    def same(self, value):
        return hmac.compare_digest(value.encode('utf-8', 'surrogateescape'), self.server.token.encode('utf-8'))

    def guard(self):
        hosts = self.headers.get_all('Host', [])
        allowed = {f'127.0.0.1:{self.server.port}', f'localhost:{self.server.port}'}
        if self.server.allowed_host:
            allowed.add(self.server.allowed_host)
        if len(hosts) != 1 or hosts[0] not in allowed:
            raise Failure(403, '허용되지 않은 주소입니다')
        origins = self.headers.get_all('Origin', [])
        permitted = {f'http://127.0.0.1:{self.server.port}', f'http://localhost:{self.server.port}'}
        if self.server.allowed_host:
            permitted.update(('http://' + self.server.allowed_host, 'https://' + self.server.allowed_host))
        if len(origins) > 1 or (self.command == 'POST' and not origins):
            raise Failure(403, '요청 출처를 확인할 수 없습니다')
        if origins and (origins[0] not in permitted or urlsplit(origins[0]).netloc != hosts[0]):
            raise Failure(403, '허용되지 않은 출처입니다')
        if self.headers.get_all('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) > 1:
            raise Failure(400, '요청 크기가 올바르지 않습니다')
        length = self.headers.get('Content-Length')
        if length is not None and (len(length) > 12 or not re.fullmatch(r'[0-9]+', length)):
            raise Failure(400, '요청 크기가 올바르지 않습니다')

    def case_dir(self, case_id):
        if not CASE_ID.fullmatch(case_id):
            raise Failure(404, '사건이 없습니다')
        base = self.server.root / 'cases'
        case = base / case_id
        if not base.resolve().is_relative_to(self.server.root) or not case.resolve().is_relative_to(base.resolve()) or not case.is_dir():
            raise Failure(404, '사건이 없습니다')
        return case.resolve()

    def case_file(self, case_id, relative, missing=False):
        case = self.case_dir(case_id)
        path = case / relative
        resolved = path.resolve()
        if not resolved.is_relative_to(case) or (path.exists() and not path.is_file()):
            raise Failure(404, '파일이 없습니다')
        if not missing and not path.is_file():
            raise Failure(404, '파일이 없습니다')
        return resolved

    def state(self, case_id):
        path = self.case_file(case_id, 'state.json')
        try:
            data = json_file(path, 20 * MB)
            if not isinstance(data, dict) or type(data.get('revision')) is not int:
                raise ValueError()
            return data
        except (ValueError, UnicodeError, RecursionError):
            raise Failure(422, '사건 상태를 읽을 수 없습니다')

    def review(self, case_id):
        path = self.case_file(case_id, 'review.json', missing=True)
        try:
            result = json_file(path, 20 * MB)
            if isinstance(result, dict) and isinstance(result.get('items'), dict):
                return result
        except (FileNotFoundError, ValueError, UnicodeError, RecursionError):
            pass
        return {}

    def get(self, path, entry):
        if path in STATIC:
            name, mime = STATIC[path]
            headers = {'Set-Cookie': f'{self.cookie_name()}={self.server.token}; HttpOnly; SameSite=Strict; Path=/'} if entry else {}
            return self.respond(200, (WEB / name).read_bytes(), mime, headers)
        if path == '/api/cases':
            rows = []
            base = self.server.root / 'cases'
            if not base.resolve().is_relative_to(self.server.root):
                raise Failure(404, '사건이 없습니다')
            if base.is_dir():
                for case in base.iterdir():
                    if not CASE_ID.fullmatch(case.name) or not case.is_dir():
                        continue
                    row = dict(case_id=case.name, title='', application_number='', updated_at='', revision=None, next_title='')
                    try:
                        s = self.state(case.name)
                        row.update({key: s.get(key) for key in ('title', 'application_number', 'updated_at', 'revision')})
                        row['next_title'] = s.get('next', {}).get('title', '') if isinstance(s.get('next'), dict) else ''
                    except (Failure, OSError):
                        row['error'] = '사건 상태를 읽을 수 없습니다'
                    rows.append(row)
            rows.sort(key=lambda r: str(r.get('updated_at') or ''), reverse=True)
            return self.respond(200, rows)
        if path == '/api/chat':
            return self.respond(200, self.chat_read())
        match = re.fullmatch(r'/api/cases/([^/]+)(?:/(notice\.html|notice\.docx))?', path)
        if not match:
            raise Failure(404, '경로가 없습니다')
        case_id, artifact = match.groups()
        if artifact:
            file = self.case_file(case_id, 'out/' + artifact)
            html = artifact.endswith('.html')
            data = read_limited(file, (10 if html else 50) * MB)
            return self.respond(200, data, 'text/html; charset=utf-8' if html else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                                {} if html else {'Content-Disposition': 'attachment; filename="notice.docx"'}, preview=html)
        data = json.dumps(dict(state=self.state(case_id), review=self.review(case_id)), ensure_ascii=False).encode('utf-8')
        etag = '"' + hashlib.sha256(data).hexdigest() + '"'
        self.respond(304 if self.headers.get('If-None-Match') == etag else 200,
                     b'' if self.headers.get('If-None-Match') == etag else data, headers={'ETag': etag})

    def length(self, limit):
        values = self.headers.get_all('Content-Length', [])
        if len(values) != 1 or not re.fullmatch(r'[0-9]+', values[0]) or len(values[0]) > 12:
            raise Failure(400, '요청 크기가 필요합니다')
        size = int(values[0])
        if size > limit:
            raise Failure(413, '파일 또는 글이 너무 큽니다')
        return size

    def read_body(self, size):
        try:
            data = self.rfile.read(size)
        except (TimeoutError, OSError):
            raise Failure(400, '전송이 끝나지 않았습니다')
        if len(data) != size:
            raise Failure(400, '전송이 끝나지 않았습니다')
        return data

    def post(self, path, query):
        if path == '/api/upload':
            return self.upload(query)
        size = self.length(32 * 1024)
        if self.headers.get_content_type() != 'application/json':
            raise Failure(400, 'JSON 글이 필요합니다')
        data = json.loads(self.read_body(size))
        if not isinstance(data, dict):
            raise Failure(400, '내용을 확인해 주세요')
        if path == '/api/chat':
            return self.chat_post(data)
        match = re.fullmatch(r'/api/cases/([^/]+)/review', path)
        if not match:
            raise Failure(404, '경로가 없습니다')
        case_id = match[1]
        with self.server.lock:
            s = self.state(case_id)
            key, checked, revision = data.get('key'), data.get('checked'), data.get('revision')
            items = s.get('review_items')
            keys = [r.get('key') for r in items if isinstance(r, dict)] if isinstance(items, list) else []
            if not isinstance(key, str) or key not in keys or type(checked) is not bool or type(revision) is not int:
                raise Failure(400, '확인 항목이 올바르지 않습니다')
            if revision != s['revision']:
                raise Failure(409, '내용이 바뀌었습니다. 다시 확인해 주세요')
            review = self.review(case_id) or {'schema_version': 1, 'items': {}}
            review['items'][key] = dict(checked=checked, at=now(), revision=revision)
            review['schema_version'] = 1
            atomic(self.case_file(case_id, 'review.json', missing=True), json.dumps(review, ensure_ascii=False))
        self.respond(200, review)

    def upload(self, query):
        size = self.length(50 * MB)
        if not size or self.headers.get_content_type() != 'application/octet-stream' or len(query.get('name', [])) != 1:
            raise Failure(400, '파일과 이름이 필요합니다')
        name = clean_name(query['name'][0])
        folder = self.server.root / 'input'
        if not folder.resolve().is_relative_to(self.server.root):
            raise Failure(404, '저장 폴더가 없습니다')
        folder.mkdir(exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix='.upload-', suffix='.part', dir=folder)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                remaining, first = size, True
                while remaining:
                    chunk = self.read_body(min(remaining, 64 * 1024))
                    if name.lower().endswith('.pdf') and first and not chunk.startswith(b'%PDF-'):
                        raise Failure(400, 'PDF 파일을 확인해 주세요')
                    if name.lower().endswith('.txt') and b'\x00' in chunk:
                        raise Failure(400, 'TXT 파일을 확인해 주세요')
                    stream.write(chunk)
                    remaining -= len(chunk)
                    first = False
                stream.flush()
                os.fsync(stream.fileno())
            with self.server.lock:
                normalized = unicodedata.normalize('NFC', name).casefold()
                if any(unicodedata.normalize('NFC', p.name).casefold() == normalized for p in folder.iterdir()):
                    raise Failure(409, '같은 이름의 파일이 있습니다')
                target = folder / name
                try:
                    os.link(temp, target)
                except FileExistsError:
                    raise Failure(409, '같은 이름의 파일이 있습니다')
                except OSError:
                    try:
                        output = target.open('xb')
                    except FileExistsError:
                        raise Failure(409, '같은 이름의 파일이 있습니다')
                    try:
                        with output, temp.open('rb') as source:
                            shutil.copyfileobj(source, output)
                            output.flush()
                            os.fsync(output.fileno())
                    except BaseException:
                        target.unlink()
                        raise
            self.respond(201, {'name': name, 'message': 'Codex 채팅에서 검토를 시작하세요'})
        finally:
            temp.unlink(missing_ok=True)

    def chat_path(self, name):
        folder = self.server.chat_dir
        if folder is None:
            raise Failure(404, '채팅이 꺼져 있습니다')
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise Failure(403, '채팅 파일을 사용할 수 없습니다')
        return path

    def chat_read(self):
        if self.server.chat_dir is None:
            return {'enabled': False}
        messages = []
        with self.server.lock:
            for name, role, field in [('inbox.jsonl', 'user', 'case'), ('outbox.jsonl', 'assistant', 'reply_to')]:
                path = self.chat_path(name)
                if not path.exists():
                    continue
                with path.open('rb') as stream:
                    stream.seek(0, 2)
                    size = stream.tell()
                    start = max(0, size - MB)
                    stream.seek(start)
                    data = stream.read(MB)
                lines = data.split(b'\n')
                if start:
                    lines = lines[1:]
                if lines and not lines[-1]:
                    lines.pop()
                for line in lines[-200:]:
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ('id', 'ts', 'text', field)):
                            continue
                        if not row['id'] or len(row['id']) > 128 or not row['text'].strip() or '\x00' in row['text'] or len(row[field]) > 128:
                            continue
                        at = datetime.fromisoformat(row['ts'])
                        if at.tzinfo is None:
                            continue
                        messages.append(dict(id=row['id'], ts=row['ts'], text=row['text'][:4000], role=role,
                                             **{field: row[field]}, order=at.timestamp()))
                    except (ValueError, UnicodeError, OverflowError, RecursionError):
                        continue
        messages.sort(key=lambda r: (r['order'], r['id']))
        for row in messages:
            row.pop('order')
        return {'enabled': True, 'messages': messages[-200:]}

    def chat_post(self, data):
        if self.server.chat_dir is None:
            raise Failure(404, '채팅이 꺼져 있습니다')
        text, case = data.get('text'), data.get('case')
        if not isinstance(text, str) or not isinstance(case, str):
            raise Failure(400, '글과 사건을 확인해 주세요')
        text = text.strip()
        if not 1 <= len(text) <= 4000 or '\x00' in text:
            raise Failure(400, '글은 1자부터 4000자까지입니다')
        if case:
            try:
                self.state(case)
            except Failure:
                raise Failure(400, '사건을 확인해 주세요')
        with self.server.lock:
            moment = time.monotonic()
            times = self.server.chat_times
            while times and moment - times[0] >= 60:
                times.popleft()
            if len(times) >= 20:
                raise Failure(429, '잠시 뒤 다시 보내 주세요')
            path = self.chat_path('inbox.jsonl')
            self.chat_path('outbox.jsonl')
            row = dict(id=uuid.uuid4().hex, ts=now(), text=text, case=case)
            with path.open('ab') as stream:
                stream.write((json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8'))
                stream.flush()
            times.append(moment)
        self.respond(201, row)


def main():
    parser = argparse.ArgumentParser(description='로컬 진행 화면')
    parser.add_argument('--no-open', action='store_true', help='브라우저를 열지 않음')
    args = parser.parse_args()
    try:
        port = int(os.environ.get('PATENT_UI_PORT', '8943'))
        if not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        print('포트는 1부터 65535까지입니다')
        return 1
    token = secrets.token_urlsafe(32)
    server = make_server(os.environ.get('PATENT_WORK_ROOT', REPO), port, token,
                         os.environ.get('PATENT_UI_CHAT_DIR'), os.environ.get('PATENT_UI_ALLOWED_HOST', ''))
    try:
        try:
            server.server_bind()
            server.server_activate()
        except OSError:
            print('포트를 열 수 없습니다. 열린 화면 서버를 확인하세요')
            return 1
        address = f'http://127.0.0.1:{port}/?token={token}'
        print(address, flush=True)
        if not args.no_open:
            webbrowser.open(address)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
