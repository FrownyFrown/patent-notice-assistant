"""공개 공보를 제한된 주소에서 읽고 원문 단락으로 저장한다."""
import json
import hashlib
import os
import re
import tempfile
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE = 20 * 1024 * 1024


class PatentError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def normalize(number):
    if not isinstance(number, str) or len(number) > 100:
        raise PatentError('bad_number', '문헌번호 형식을 확인해 주세요.')
    value = re.sub(r'\s+', '', number).upper()
    korean = re.fullmatch(r'(?:KR)?(10|20)-(\d{4})-(\d{7})([A-Z][0-9]?)?', value)
    grant = re.fullmatch(r'(?:KR)?(10|20)-(\d{7})([A-Z][0-9]?)?', value)
    if korean:
        prefix, year, serial, kind = korean.groups()
        value = 'KR'+year+serial+(kind or ('A' if prefix == '10' else 'U'))
    elif grant:
        prefix, serial, kind = grant.groups()
        value = 'KR'+prefix+serial+(kind or ('B1' if prefix == '10' else 'Y1'))
    elif re.fullmatch(r'(?:[A-Z]{2}\d{4}[-/]\d{1,7}|US\d{1,3}(?:,\d{3})+)[A-Z]?[0-9]?', value):
        value = re.sub(r'[,/-]', '', value)
    if re.fullmatch(r'KR10\d{7}', value):
        value += 'B1'
    elif re.fullmatch(r'KR\d{11}', value):
        value += 'A'
    if not re.fullmatch(r'[A-Z]{2}[0-9]{4,14}[A-Z]?[0-9]?', value):
        raise PatentError('bad_number', '문헌번호 형식을 확인해 주세요.')
    return value


def find_numbers(text):
    pattern = r'(?<![A-Za-z0-9])(?:[A-Z]{2}\s*(?:10-|20-)?\d[\d,/-]*(?:\s*[A-Z]\d?)?|(?:10|20)-\d{4}-\d{7}|(?:10|20)-\d{7})(?![A-Za-z0-9])'
    result = []
    for match in re.finditer(pattern, text, re.I):
        try:
            number = normalize(match.group())
            if number not in result:
                result.append(number)
        except PatentError:
            pass
    return result


def _date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else None
    except ValueError:
        return None


def is_prior(publication_date, basis_date):
    publication, basis = _date(publication_date), _date(basis_date)
    return bool(publication and basis and publication < basis)


def _url(doc_id):
    return 'https://patents.google.com/patent/'+doc_id+('/ko' if doc_id.startswith('KR') else '/en')


def _safe_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'patents.google.com' or not re.fullmatch(r'/patent/[A-Za-z0-9]+(?:/(?:ko|en))?/?', parsed.path) or parsed.query or parsed.fragment:
        raise PatentError('network', '허용되지 않은 공보 주소 이동을 거부했습니다.')


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title, self.number, self.publication = '', '', None
        self.seen_date = False
        self.paragraphs, self.claims = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        prop = attrs.get('itemprop', '')
        classes = attrs.get('class', '').split()
        section = prop if tag == 'section' and prop in ('description','claims') else ''
        parent_section = next((f['section'] for f in reversed(self.stack) if f['section']), '')
        capture = ''
        if tag == 'span' and prop == 'title' and not self.title:
            capture = 'title'
        elif tag == 'dd' and prop == 'publicationNumber' and not self.number:
            capture = 'number'
        elif parent_section == 'description' and (tag == 'p' or tag == 'div' and any(c in classes for c in ('description-paragraph','description-line'))):
            if not any(f['capture'] == 'paragraph' for f in self.stack):
                capture = 'paragraph'
        elif parent_section == 'claims' and tag == 'div' and 'claim' in classes:
            if not any(f['capture'] == 'claim' for f in self.stack):
                capture = 'claim'
        if tag == 'time' and prop == 'publicationDate' and not self.seen_date:
            self.seen_date = True
            value = attrs.get('datetime', '')
            self.publication = value if _date(value) else None
        frame = dict(tag=tag, section=section, capture=capture, num=attrs.get('num',''), source='google-src-text' in classes, hidden=tag in ('script','style'), text=[], original=[])
        if tag == 'br':
            self.handle_data('\n')
        if tag not in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):
            self.stack.append(frame)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if any(f['hidden'] for f in self.stack):
            return
        source = any(f['source'] for f in self.stack)
        for frame in self.stack:
            if frame['capture']:
                frame['original' if source else 'text'].append(data)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i]['tag'] == tag), None)
        if index is None:
            return
        frames = self.stack[index:]
        del self.stack[index:]
        for f in reversed(frames):
            value = ''.join(f['text']).strip()
            source = ''.join(f['original']).strip()
            kind = f['capture']
            if kind == 'title' and not self.title:
                self.title = value
            elif kind == 'number' and not self.number:
                self.number = value
            elif kind == 'paragraph' and (value or source):
                num = f['num'] if re.fullmatch(r'\d+', f['num']) else ''
                self.paragraphs.append(dict(id='p'+str(len(self.paragraphs)+1), num=num, text=value or source, source_text=source if value else ''))
            elif kind == 'claim' and value:
                self.claims.append(dict(num=f['num'], text=value))


def _doc(doc_id, title, publication_date, paragraphs, claims=None, origin='manual'):
    return dict(doc_id=doc_id, title=title, publication_date=publication_date, url=_url(doc_id), numbered=any(p['num'] for p in paragraphs), machine_translated=any(p['source_text'] for p in paragraphs), origin=origin, paragraphs=paragraphs, claims=claims or [])


def from_text(text, doc_id, publication_date, title=''):
    from .claims import HEADER
    doc_id = normalize(doc_id)
    text = HEADER.sub('', text)
    matches = list(re.finditer(r'(?:\[(\d{4})\]|【(\d{4})】)', text))
    paragraphs = []
    if matches:
        pieces = [(m[1] or m[2], text[m.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()) for i, m in enumerate(matches)]
        prefix = text[:matches[0].start()].strip()
        if prefix:
            pieces.insert(0, ('', prefix))
    else:
        pieces = [('', p.strip()) for p in re.split(r'\n\s*\n' if re.search(r'\n\s*\n', text) else r'\n', text)]
    for num, value in pieces:
        if value:
            paragraphs.append(dict(id='p'+str(len(paragraphs)+1), num=num, text=value, source_text=''))
    if not paragraphs:
        raise PatentError('no_text', '공보 본문이 없습니다. 글자가 있는 파일을 넣어 주세요.')
    return _doc(doc_id, title, publication_date if _date(publication_date) else None, paragraphs)


def _atomic(path, value):
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.'+path.name, delete=False) as f:
            temp = Path(f.name)
            json.dump(value, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def _index(cache_dir):
    try:
        value = json.loads((Path(cache_dir) / '.index.json').read_bytes())
        if not isinstance(value, dict) or any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in value.values()):
            return {}
        return value
    except (OSError, ValueError):
        return {}


def read_document(cache_dir, doc_id):
    doc_id = normalize(doc_id)
    try:
        path = Path(cache_dir) / (doc_id + '.json')
        with path.open('rb') as f:
            data = f.read(20_000_001)
        if len(data) > 20_000_000 or _index(cache_dir).get(doc_id) != hashlib.sha256(data).hexdigest():
            return None
        def unique(pairs):
            value = {}
            for k, v in pairs:
                if k in value:
                    raise ValueError('중복 항목입니다.')
                value[k] = v
            return value
        value = json.loads(data, object_pairs_hook=unique)
        if value['doc_id'] != doc_id or not isinstance(value['paragraphs'], list) or not all(k in value for k in ('title','publication_date','url','numbered','machine_translated','origin','claims')):
            return None
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def store_document(cache_dir, doc):
    from .state import atomic
    cache_dir = Path(cache_dir)
    doc_id = normalize(doc['doc_id'])
    data = (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    atomic(cache_dir / (doc_id + '.json'), data)
    index = _index(cache_dir)
    # 모델이 목록까지 고치면 변조를 막을 수 없다.
    index[doc_id] = hashlib.sha256(data).hexdigest()
    atomic(cache_dir / '.index.json', json.dumps(index))


def fetch(doc_id, cache_dir: Path, opener=None, sleep=time.sleep, min_interval=2.0):
    doc_id = normalize(doc_id)
    if not isinstance(min_interval, (int, float)) or min_interval < 0 or not min_interval < float('inf'):
        raise PatentError('network', '요청 간격을 확인해 주세요.')
    cache_dir = Path(cache_dir)
    lock = cache_dir / '.request.lock'
    locked = False
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        value = read_document(cache_dir, doc_id)
        if value is not None:
            return value
        deadline = time.monotonic()+30
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                locked = True
                break
            except FileExistsError:
                try:  # 중간에 꺼진 실행이 남긴 잠금은 90초 뒤 치운다
                    if time.time()-lock.stat().st_mtime > 90:
                        lock.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise PatentError('network', '다른 공보 요청이 끝나지 않았습니다. 잠금 파일을 확인해 주세요.')
                sleep(0.1)
        value = read_document(cache_dir, doc_id)
        if value is not None:
            return value
        stamp = cache_dir / '.request-time.json'
        if stamp.exists():
            try:
                last = float(json.loads(stamp.read_text(encoding='utf-8')))
                delay = max(0.0, last+min_interval-time.time())
                if delay > 60:
                    raise ValueError()
                if delay:
                    sleep(delay)
            except (ValueError, TypeError) as exc:
                raise PatentError('network', '요청 시각 파일 또는 시스템 시각을 확인해 주세요.') from exc
        _atomic(stamp, time.time())
        request = Request(_url(doc_id), headers={'User-Agent':'Patent document reader/1.0', 'Accept':'text/html'})
        opening = opener or build_opener(_SafeRedirect()).open
        if not callable(opening):
            opening = opening.open
        with opening(request, timeout=30) as response:
            _safe_url(response.geturl())
            status = getattr(response, 'status', 200)
            if status == 404:
                raise PatentError('not_found', '공보를 찾지 못했습니다. PDF 또는 TXT를 넣어 주세요.')
            if status != 200:
                raise PatentError('network', '공보 서버 응답을 확인하지 못했습니다.')
            if int(response.headers.get('Content-Length', '0')) > MAX_RESPONSE:
                raise PatentError('network', '공보 응답이 20MB를 넘습니다.')
            data = response.read(MAX_RESPONSE+1)
        if len(data) > MAX_RESPONSE:
            raise PatentError('network', '공보 응답이 20MB를 넘습니다.')
        parser = _Page()
        parser.feed(data.decode('utf-8', errors='replace'))
        parser.close()
        try:
            actual = normalize(parser.number)
        except PatentError:
            actual = ''
        if actual != doc_id:
            raise PatentError('number_mismatch', f'요청한 번호와 페이지 번호가 다릅니다. 맞는 문헌이면 {actual or "종류코드를 포함한 번호"} 로 다시 받아 주세요.')
        if not parser.paragraphs:
            raise PatentError('no_text', '공보 본문을 찾지 못했습니다. PDF 또는 TXT를 넣어 주세요.')
        doc = _doc(doc_id, parser.title, parser.publication, parser.paragraphs, parser.claims, 'web_search')
        store_document(cache_dir, doc)
        return doc
    except PatentError:
        raise
    except HTTPError as exc:
        exc.close()
        code = 'not_found' if exc.code == 404 else 'network'
        raise PatentError(code, '공보를 받지 못했습니다. 번호와 연결을 확인하거나 PDF를 넣어 주세요.') from exc
    except (OSError, ValueError, TypeError) as exc:
        hint = ' 파이썬 인증서 설치가 필요할 수 있습니다.' if 'CERTIFICATE' in str(exc) else ''
        raise PatentError('network', '공보를 받거나 저장하지 못했습니다. 네트워크 승인, 연결, 캐시 폴더를 확인해 주세요.'+hint) from exc
    finally:
        if locked:
            lock.unlink(missing_ok=True)
