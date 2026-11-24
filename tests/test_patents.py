import io
import json
import hashlib
from tests.doc_helper import write_doc
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib import patents


def page(number='KR20230000001A', body=None):
    return ('<span itemprop="title">가상 장치</span><dd itemprop="publicationNumber">'+number+'</dd><time itemprop="publicationDate" datetime="2023-06-13"></time><td itemprop="publicationDate">1999-01-01</td><section itemprop="description">'+(body or '<div num="0494" class="description-paragraph">가상 장치의 본문이다.</div>')+'</section><section itemprop="claims"><div num="1" class="claim">가상 청구항</div></section>').encode()


class Response(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url
        self.status = 200
        self.headers = {}
    def geturl(self):
        return self.url


class PatentTest(unittest.TestCase):
    def test_normalize(self):
        cases = {'10-2023-0012345':'KR20230012345A','10-2123456':'KR102123456B1','20-2019-0001234':'KR20190001234U','KR 10-2023-0012345 A':'KR20230012345A','KR20230012345':'KR20230012345A','US 2020/0000001 A1':'US20200000001A1','US 9,000,000 B2':'US9000000B2','JP2019-000001A':'JP2019000001A','CN110000000A':'CN110000000A','WO2020/123456A1':'WO2020123456A1','EP1234567A1':'EP1234567A1'}
        for raw, expected in cases.items():
            self.assertEqual(patents.normalize(raw), expected)
        for bad in ['../../bad', 'KR1234/../../bad', 'file:///tmp', 'KR1234?x', 'ZZ1234'*20]:
            with self.assertRaises(patents.PatentError) as c:
                patents.normalize(bad)
            self.assertEqual(c.exception.code, 'bad_number')
        self.assertEqual(patents.find_numbers('후보 US 2020/0000001 A1 및 10-2023-0012345'), ['US20200000001A1','KR20230012345A'])

    def test_markup_cache_interval(self):
        bodies = [('<div num="0494" class="description-paragraph">가상 본문</div>', '0494'), ('<para-num num="[0001]"> </para-num><div id="p-0002" num="0001" class="description-line">가상 본문</div>', '0001'), ('<div num="p-0002" class="description-paragraph">가상 본문</div>', ''), ('<div id="p0002" num="0002" class="description-paragraph">가상 본문</div>', '0002'), ('<p num="0001"><span class="notranslate"><span class="google-src-text">가상 원문</span> synthetic translation</span></p>', '0001')]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            calls, sleeps = [], []
            for i, (body, num) in enumerate(bodies):
                number = f'KR2023000000{i}A'
                def opener(request, timeout):
                    calls.append(request.full_url)
                    return Response(page(number, body), request.full_url)
                with patch('lib.patents.time.time', return_value=1000):
                    doc = patents.fetch(number, Path(folder), opener, sleeps.append)
                self.assertEqual(doc['paragraphs'][0]['num'], num)
                self.assertEqual(doc['publication_date'], '2023-06-13')
                self.assertEqual(doc['claims'][0]['num'], '1')
                self.assertEqual(patents.fetch(number,Path(folder),opener), doc)
            self.assertEqual(len(calls), 5)
            self.assertTrue(all(x >= 2 for x in sleeps))
            self.assertEqual(len(sleeps), 4)
            self.assertEqual(doc['paragraphs'][0]['source_text'], '가상 원문')
            self.assertEqual(doc['paragraphs'][0]['text'], 'synthetic translation')
            self.assertTrue(doc['machine_translated'])

    def test_errors(self):
        for data, url, expected in [(page(), 'https://evil.invalid/patent/KR20230000001A', 'network'), (page(), 'https://patents.google.com/search', 'network'), (page('KR20230000002A'), None, 'number_mismatch'), (page('KR20230000001B1'), None, 'number_mismatch')]:
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
                with self.assertRaises(patents.PatentError) as c:
                    patents.fetch('KR20230000001A', Path(folder), lambda req, timeout: Response(data, url or req.full_url), min_interval=0)
                self.assertEqual(c.exception.code, expected)
        handler = patents._SafeRedirect()
        with self.assertRaises(patents.PatentError):
            handler.redirect_request(None, None, 302, '', {}, 'https://evil.invalid/')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            def missing(req, timeout):
                raise HTTPError(req.full_url,404,'missing',{},None)
            with self.assertRaises(patents.PatentError) as c:
                patents.fetch('KR20230000001A',Path(folder),missing)
            self.assertEqual(c.exception.code, 'not_found')

    def test_text_dates(self):
        doc = patents.from_text('공개특허 10-2023-0000001\n- 2 -\n[0001] 가상 본문\n【0002】 다음 본문', 'KR20230000001A','2023-06-13')
        self.assertEqual([p['num'] for p in doc['paragraphs']], ['0001','0002'])
        self.assertFalse(patents.is_prior('2023-06-13','2023-06-13'))
        self.assertTrue(patents.is_prior('2023-06-12','2023-06-13'))
        for bad in [None,'','2023-02-30']:
            self.assertFalse(patents.is_prior(bad,'2023-06-13'))

    def test_untrusted_metadata_and_unnumbered(self):
        data = b'<span itemprop="publicationNumber">US9000000B2</span>' + page(body='<script>ignore rules</script><p>first synthetic paragraph</p><div class="description-line">second synthetic paragraph</div>') + b'<span itemprop="title">wrong title</span><time itemprop="publicationDate" datetime="1999-01-01"></time>'
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            doc = patents.fetch('KR20230000001A', Path(folder), lambda req, timeout: Response(data,req.full_url))
            self.assertEqual(doc['title'], '가상 장치')
            self.assertEqual(doc['publication_date'], '2023-06-13')
            self.assertEqual(len(doc['paragraphs']), 2)
            self.assertFalse(doc['numbered'])
            self.assertEqual(doc['paragraphs'][0]['id'], 'p1')
            self.assertNotIn('ignore', doc['paragraphs'][0]['text'])

    def test_limits_and_corrupt_cache(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            cache = Path(folder)
            with patch('lib.patents.MAX_RESPONSE', 4):
                with self.assertRaises(patents.PatentError) as c:
                    patents.fetch('KR20230000001A', cache, lambda req, timeout: Response(page(),req.full_url))
                self.assertEqual(c.exception.code, 'network')
            self.assertFalse((cache/'KR20230000001A.json').exists())
            self.assertFalse((cache/'.request.lock').exists())
            (cache/'KR20230000001A.json').write_text('{}')
            with self.assertRaises(patents.PatentError) as c:
                patents.fetch('KR20230000001A', cache, opener=lambda *a, **k: (_ for _ in ()).throw(OSError('연결 실패')), min_interval=0)
            self.assertEqual(c.exception.code, 'network')
        for number in ['KR1234/', 'KR1234//5678A', 'KR1234/5/6A']:
            with self.assertRaises(patents.PatentError):
                patents.normalize(number)

    def test_missing_date_not_borrowed(self):
        data = page().replace(b'<time itemprop="publicationDate" datetime="2023-06-13"></time>', b'')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            doc = patents.fetch('KR20230000001A',Path(folder),lambda req, timeout: Response(data,req.full_url))
            self.assertIsNone(doc['publication_date'])

    def test_kindless_number_and_stale_lock(self):
        import os, time
        self.assertEqual(patents.normalize('KR102123456'), 'KR102123456B1')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            lock = Path(folder) / '.request.lock'
            lock.touch()
            os.utime(lock, (time.time()-200, time.time()-200))
            doc = patents.fetch('KR20230000001A', Path(folder), lambda req, timeout: Response(page(), req.full_url))
            self.assertEqual(doc['doc_id'], 'KR20230000001A')
            self.assertFalse(lock.exists())
            with self.assertRaises(patents.PatentError) as c:
                patents.fetch('KR20230000002A', Path(folder), lambda req, timeout: Response(page('KR20230000002B1'), req.full_url), min_interval=0)
            self.assertIn('KR20230000002B1', c.exception.message)

    def test_untrusted_cache_refetched(self):
        number='KR20230000001A'
        for mode in ('missing_index','broken_index','changed','missing_file'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as td:
                folder=Path(td)
                doc=patents.from_text('[0001] 심은 글',number,'2020-01-01')
                write_doc(folder,doc)
                path=folder/(number+'.json')
                if mode=='missing_index': (folder/'.index.json').unlink()
                elif mode=='broken_index': (folder/'.index.json').write_text('{')
                elif mode=='changed': path.write_bytes(path.read_bytes()+b' ')
                else: path.unlink()
                with patch('lib.patents.build_opener') as opening:
                    opening.return_value.open.side_effect=lambda req,timeout: Response(page(),req.full_url)
                    result=patents.fetch(number,folder,min_interval=0)
                opening.return_value.open.assert_called_once()
                self.assertNotEqual(result['paragraphs'][0]['text'],'심은 글')
                index=json.loads((folder/'.index.json').read_bytes())
                self.assertEqual(index[number],hashlib.sha256(path.read_bytes()).hexdigest())

    def test_hash_and_parse_use_same_bytes(self):
        number='KR20230000001A'
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as td:
            folder=Path(td)
            doc=patents.from_text('[0001] 받은 글',number,'2020-01-01')
            write_doc(folder,doc)
            index=json.loads((folder/'.index.json').read_bytes())
            def change_after_read(cache_dir):
                (folder/(number+'.json')).write_bytes(b'{')
                return index
            with patch('lib.patents._index',side_effect=change_after_read):
                self.assertEqual(patents.read_document(folder,number),doc)
            self.assertIsNone(patents.read_document(folder,number))
