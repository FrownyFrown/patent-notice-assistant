"""포트를 열지 않는 화면 서버 시험."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

from ui import server

ROOT = Path(__file__).resolve().parents[1]


class UITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.case = self.root / 'cases' / 'sample'
        self.case.mkdir(parents=True)
        self.state = json.loads((ROOT / 'tests/fixtures/state-sample.json').read_text())
        self.state['case_id'] = 'sample'
        self.save_state()
        self.chat = self.root / 'chat'
        self.chat.mkdir()
        self.srv = server.make_server(self.root, 8943, 'secret', self.chat)
        self.addCleanup(self.srv.server_close)

    def save_state(self):
        (self.case / 'state.json').write_text(json.dumps(self.state), encoding='utf-8')

    def request(self, path='/', method='GET', body=b'', auth=True, host='127.0.0.1:8943',
                origin='http://127.0.0.1:8943', extra=(), length=None, content_length=True):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        a.settimeout(5)
        headers = [('Host', host)]
        if auth:
            headers.append(('Cookie', f'other="a b; patent_ui_{self.srv.port}=secret'))
        if origin is not None:
            headers.append(('Origin', origin))
        if method == 'POST':
            headers += [('Content-Length', str(len(body) if length is None else length)),
                        ('Content-Type', 'application/octet-stream' if path.startswith('/api/upload') else 'application/json')]
        if not content_length:
            headers = [(k, v) for k, v in headers if k != 'Content-Length']
        headers += list(extra)
        raw = f'{method} {path} HTTP/1.1\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in headers) + '\r\n'
        errors = []
        def handle():
            try:
                self.srv.finish_request(b, ('127.0.0.1', 1))
            except Exception as exc:
                errors.append(exc)
            finally:
                b.close()
        thread = threading.Thread(target=handle)
        thread.start()
        a.sendall(raw.encode() + body)
        a.shutdown(socket.SHUT_WR)
        response = http.client.HTTPResponse(a, method=method)
        response.begin()
        result = (response.status, dict(response.getheaders()), response.read())
        response.close()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        return result

    def post(self, path, data, origin='http://127.0.0.1:8943'):
        return self.request(path, 'POST', json.dumps(data).encode(), origin=origin)

    def test_auth_and_headers(self):
        for path in ['/', '/app.js', '/api/cases', '/?token=wrong']:
            status, headers, body = self.request(path, auth=False)
            self.assertEqual(status, 401)
            self.assertIn('다시 열어', body.decode())
            for name in ['Content-Security-Policy', 'X-Content-Type-Options', 'Referrer-Policy',
                         'Cache-Control', 'Cross-Origin-Resource-Policy']:
                self.assertIn(name, headers)
        status, headers, _ = self.request('/?token=secret', auth=False, origin=None)
        self.assertEqual(status, 200)
        for attr in ['HttpOnly', 'SameSite=Strict', 'Path=/']:
            self.assertIn(attr, headers['Set-Cookie'])
        self.assertNotIn('Location', headers)

    def test_host_origin_methods(self):
        self.assertEqual(self.request(host='bad:8943')[0], 403)
        self.assertEqual(self.request(extra=[('Host', '127.0.0.1:8943')])[0], 403)
        self.assertEqual(self.request(origin='http://bad')[0], 403)
        self.assertEqual(self.request(host='localhost:8943')[0], 403)
        self.assertEqual(self.post('/api/chat', {}, origin=None)[0], 403)
        self.assertEqual(self.request(method='DELETE')[0], 405)
        self.srv.allowed_host = 'local.example'
        self.assertEqual(self.request(host='local.example', origin='https://local.example')[0], 200)
        self.assertEqual(self.request(host='other.example', origin=None)[0], 403)

    def test_paths(self):
        for path in ['/api/cases/%2e%2e', '/api/cases/sample%2f..', '/api/cases/sample%5cout',
                     '/api/cases/' + 'a' * 65, '/other', '/api/cases/sample/source.txt']:
            self.assertEqual(self.request(path)[0], 404)
        outside = self.root / 'outside'
        outside.write_text('{}')
        (self.case / 'state.json').unlink()
        try:
            (self.case / 'state.json').symlink_to(outside)
        except OSError:
            self.skipTest('심볼릭 링크를 만들 수 없습니다')
        self.assertEqual(self.request('/api/cases/sample')[0], 404)

    def test_upload_names(self):
        cases = [('a/b.txt', 'b.txt'), ('C:\\x\\a.pdf', 'a.pdf'), ('.. a?.TXT .', 'a.TXT'),
                 ('CON.txt', '_CON.txt'), ('com1.PDF', '_com1.PDF'), ('a\u202eb.txt', 'ab.txt'),
                 ('e\u0301.txt', '\u00e9.txt')]
        for raw, clean in cases:
            self.assertEqual(server.clean_name(raw), clean)
        self.assertLessEqual(len(server.clean_name('가' * 100 + '.txt').encode()), 150)
        for raw in ['a.exe', '', '.txt']:
            with self.assertRaises(ValueError):
                server.clean_name(raw)

    def test_upload(self):
        self.assertEqual(self.request('/api/upload?name=a.txt', 'POST', b'hello')[0], 201)
        self.assertEqual(self.request('/api/upload?name=A.TXT', 'POST', b'new')[0], 409)
        self.assertEqual((self.root / 'input/a.txt').read_bytes(), b'hello')
        for name, body in [('x.pdf', b'no'), ('x.txt', b'a\x00b'), ('x.txt', b'')]:
            self.assertEqual(self.request('/api/upload?name=' + name, 'POST', body)[0], 400)
        self.assertEqual(self.request('/api/upload?name=x.pdf', 'POST', b'%PDF-test')[0], 201)
        self.assertEqual(self.request('/api/upload?name=short.txt', 'POST', b'abc', length=20)[0], 400)
        self.assertFalse((self.root / 'input/short.txt').exists())
        self.assertEqual(sorted(p.name for p in (self.root / 'input').iterdir()), ['a.txt', 'x.pdf'])
        self.assertEqual(self.request('/api/upload?name=huge.txt', 'POST', length=50 * 1024 * 1024 + 1)[0], 413)
        self.assertEqual(self.request('/api/upload?name=x.txt', 'POST', b'abc',
                                      extra=[('Content-Length', '3')])[0], 400)
        self.assertEqual(self.request('/api/upload?name=x.txt', 'POST', extra=[('Transfer-Encoding', 'chunked')])[0], 400)
        self.assertEqual(self.request('/api/upload?name=x.txt', 'POST', length='-1')[0], 400)

    def test_review_etag(self):
        original = (self.case / 'state.json').read_bytes()
        path = '/api/cases/sample'
        status, headers, _ = self.request(path)
        self.assertEqual(status, 200)
        self.assertEqual(self.request(path, extra=[('If-None-Match', headers['ETag'])])[0], 304)
        data = dict(key='claims', checked=True, revision=self.state['revision'])
        self.assertEqual(self.post(path + '/review', data)[0], 200)
        saved = json.loads((self.case / 'review.json').read_text())
        self.assertEqual(saved['schema_version'], 1)
        self.assertEqual(saved['items']['claims']['revision'], self.state['revision'])
        self.assertTrue(saved['items']['claims']['checked'])
        self.assertEqual((self.case / 'state.json').read_bytes(), original)
        self.assertNotEqual(self.request(path)[1]['ETag'], headers['ETag'])
        data['revision'] -= 1
        self.assertEqual(self.post(path + '/review', data)[0], 409)
        data['revision'] = True
        self.assertEqual(self.post(path + '/review', data)[0], 400)
        data.update(revision=self.state['revision'], key='unknown')
        self.assertEqual(self.post(path + '/review', data)[0], 400)
        (self.case / 'review.json').write_text('broken')
        self.assertEqual(json.loads(self.request(path)[2])['review'], {})

    def test_artifacts_and_broken_state(self):
        out = self.case / 'out'
        out.mkdir()
        (out / 'notice.html').write_text('<p>초안</p>')
        (out / 'notice.docx').write_bytes(b'docx')
        status, headers, _ = self.request('/api/cases/sample/notice.html')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Security-Policy'], "default-src 'none'; style-src 'unsafe-inline'; sandbox; frame-ancestors 'self'")
        self.assertIn('attachment', self.request('/api/cases/sample/notice.docx')[1]['Content-Disposition'])
        (self.case / 'state.json').write_text('{')
        rows = json.loads(self.request('/api/cases')[2])
        self.assertEqual(rows[0]['case_id'], 'sample')
        self.assertIn('error', rows[0])
        self.assertEqual(self.request('/api/cases/sample')[0], 422)

    def test_chat(self):
        text = '<script>\n글</script>'
        self.assertEqual(self.post('/api/chat', dict(text=text, case='sample'))[0], 201)
        lines = (self.chat / 'inbox.jsonl').read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])['text'], text)
        self.assertEqual(self.post('/api/chat', dict(text='가' * 4000, case=''))[0], 201)
        for value in ['가' * 4001, ' ', '\x00']:
            self.assertEqual(self.post('/api/chat', dict(text=value, case=''))[0], 400)
        self.assertEqual(self.post('/api/chat', dict(text='글', case='../bad'))[0], 400)
        (self.chat / 'outbox.jsonl').write_text('bad\n[]\n' + json.dumps(dict(id='reply', ts='2026-01-01T00:00:00+09:00', text='x' * 5000, reply_to='')) + '\n')
        rows = json.loads(self.request('/api/chat')[2])['messages']
        self.assertEqual(len(rows), 3)
        self.assertTrue(any(row['text'] == text for row in rows))
        self.assertTrue(any(len(row['text']) == 4000 for row in rows))
        for _ in range(18):
            self.assertEqual(self.post('/api/chat', dict(text='글', case=''))[0], 201)
        self.assertEqual(self.post('/api/chat', dict(text='글', case=''))[0], 429)
        self.srv.chat_dir = None
        self.assertEqual(json.loads(self.request('/api/chat')[2]), {'enabled': False})
        self.assertIn(self.post('/api/chat', dict(text='글', case=''))[0], [403, 404])

    def test_more_request_boundaries(self):
        self.assertEqual(self.request('/api/cases', auth=False, extra=[('Cookie', f'patent_ui_{self.srv.port}=wrong')])[0], 401)
        self.assertEqual(self.request('/%2e%2e', auth=False)[0], 401)
        self.assertEqual(self.request(extra=[('Content-Length', '-1')])[0], 400)
        self.assertEqual(self.request('/api/chat', 'POST', b'{}', length=32769)[0], 413)
        self.assertEqual(self.request('/api/chat', 'POST', b'{')[0], 400)
        self.assertEqual(self.request('/api/chat', 'POST', b'{}', content_length=False)[0], 400)
        self.assertEqual(self.request(extra=[('Origin', 'http://127.0.0.1:8943')])[0], 403)
        self.assertEqual(self.request('/api/cases/sample', method='HEAD')[0], 405)
        self.assertEqual(self.request(auth=False, extra=[('Cookie', 'bad@key=x')])[0], 401)
        self.assertEqual(self.srv.allow_reuse_address, os.name != 'nt')
        self.assertEqual(server.Handler.timeout, 30)

    def test_response_limits(self):
        out = self.case / 'out'
        out.mkdir()
        for path, limit, url in [(self.case / 'state.json', 20, '/api/cases/sample'),
                                 (out / 'notice.html', 10, '/api/cases/sample/notice.html'),
                                 (out / 'notice.docx', 50, '/api/cases/sample/notice.docx')]:
            with path.open('wb') as stream:
                stream.truncate(limit * 1024 * 1024 + 1)
            self.assertEqual(self.request(url)[0], 413)

    def test_chat_tail_links_and_rate_reset(self):
        row = dict(id='reply', ts='2026-01-01T00:00:00+09:00', text='글', reply_to='')
        out = self.chat / 'outbox.jsonl'
        out.write_text('x' * (1024 * 1024 + 1) + '\n' + (json.dumps(row) + '\n') * 205)
        self.assertEqual(len(json.loads(self.request('/api/chat')[2])['messages']), 200)
        with patch.object(server.time, 'monotonic', return_value=100):
            for _ in range(20):
                self.assertEqual(self.post('/api/chat', dict(text='글', case=''))[0], 201)
        with patch.object(server.time, 'monotonic', return_value=161):
            self.assertEqual(self.post('/api/chat', dict(text='글', case=''))[0], 201)
        out.unlink()
        try:
            out.symlink_to(self.case / 'state.json')
        except OSError:
            self.skipTest('심볼릭 링크를 만들 수 없습니다')
        self.assertEqual(self.request('/api/chat')[0], 403)
        self.assertEqual(self.post('/api/chat', dict(text='글', case=''))[0], 403)

    def test_upload_fallback_and_normalized_collision(self):
        with patch.object(server.os, 'link', side_effect=OSError):
            self.assertEqual(self.request('/api/upload?name=fallback.txt', 'POST', b'hello')[0], 201)
        self.assertEqual((self.root / 'input/fallback.txt').read_bytes(), b'hello')
        with patch.object(server.os, 'link', side_effect=OSError), patch.object(server.shutil, 'copyfileobj', side_effect=OSError):
            self.assertEqual(self.request('/api/upload?name=failed.txt', 'POST', b'hello')[0], 500)
        self.assertFalse((self.root / 'input/failed.txt').exists())
        name = quote('e\u0301.txt')
        self.assertEqual(self.request('/api/upload?name=' + name, 'POST', b'hello')[0], 201)
        self.assertEqual(self.request('/api/upload?name=' + quote('\u00e9.txt'), 'POST', b'hello')[0], 409)
        self.assertFalse(list((self.root / 'input').glob('*.part')))

    def test_concurrent_upload_and_review(self):
        def upload(_):
            return self.request('/api/upload?name=same.txt', 'POST', b'hello')[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(upload, range(4)))
        self.assertEqual(sorted(results), [201, 409, 409, 409])
        self.assertEqual((self.root / 'input/same.txt').read_bytes(), b'hello')
        def review(key):
            return self.post('/api/cases/sample/review', dict(key=key, checked=True, revision=self.state['revision']))[0]
        keys = [r['key'] for r in self.state['review_items']]
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(list(pool.map(review, keys)), [200] * len(keys))
        saved = json.loads((self.case / 'review.json').read_text())
        self.assertEqual(set(saved['items']), set(keys))

    def test_case_and_artifact_links(self):
        outside = self.root / 'elsewhere'
        outside.mkdir()
        (outside / 'state.json').write_text(json.dumps(self.state))
        out = self.case / 'out'
        out.mkdir()
        try:
            (self.root / 'cases' / 'linked').symlink_to(outside, target_is_directory=True)
            (out / 'notice.html').symlink_to(outside / 'state.json')
        except OSError:
            self.skipTest('심볼릭 링크를 만들 수 없습니다')
        self.assertEqual(self.request('/api/cases/linked')[0], 404)
        self.assertEqual(self.request('/api/cases/sample/notice.html')[0], 404)
        (self.case / 'review.json').symlink_to(outside / 'state.json')
        self.assertEqual(self.post('/api/cases/sample/review', dict(key='claims', checked=True, revision=self.state['revision']))[0], 404)

    def test_static_policy(self):
        code = (ROOT / 'ui/server.py').read_text()
        for bad in ['subprocess', 'os.system']:
            self.assertNotIn(bad, code)
        js = (ROOT / 'ui/web/app.js').read_text()
        for bad in ['innerHTML', 'insertAdjacentHTML', 'document.write', 'eval(']:
            self.assertNotIn(bad, js)
        html = (ROOT / 'ui/web/index.html').read_text()
        self.assertNotRegex(html, r'(?:src|href)=[\"\x27]https?://')
        self.assertNotRegex((ROOT / 'ui/web/style.css').read_text(), r'@import|url\(')
        self.assertIn('history.replaceState', js)
        for name in ['app.js', 'style.css', 'index.html']:
            self.assertEqual(self.request('/' + name)[0], 200)


if __name__ == '__main__':
    unittest.main()
