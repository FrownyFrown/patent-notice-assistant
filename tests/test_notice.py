import io
import sys
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from lib import notice
from lib.judge import enforce
from tests.test_judge import fixture


class NoticeTest(unittest.TestCase):
    def sample(self):
        s,docs,raw=fixture()
        s['conclusions'],s['references'],_=enforce(s,docs,raw)
        s['verification']['summary']['fail']=1
        s['matrix'][0].update(quote='<tag>&\x00',note='',check_message='',passages=[])
        return s,docs

    def test_docx_zip_xml(self):
        s,docs=self.sample()
        with zipfile.ZipFile(io.BytesIO(notice.docx(s,docs))) as z:
            for name in z.namelist(): ET.fromstring(z.read(name))
            text=z.read('word/document.xml').decode()
            for heading in ('심사대상 청구항','거절이유 있는 청구항','특허 가능한 청구항','구체적 거절이유','참고사항'):
                self.assertIn(heading,text)
            self.assertIn('&lt;tag&gt;&amp;',text)
            self.assertIn('11906',text)
            self.assertIn('PAGE',z.read('word/footer1.xml').decode())

    def test_html_escape_and_no_refusal(self):
        s,docs=self.sample()
        s['conclusions'][0]['verdict']='no_reason_found'
        text=notice.html(s,docs)
        self.assertIn('거절이유를 찾지 못함',text)
        self.assertNotIn('<tag>',text)
        self.assertNotIn('\x00',text)
        self.assertNotIn('src=',text)

    def test_particles(self):
        self.assertEqual(notice.particle('장치','은','는'),'는')
        self.assertEqual(notice.particle('통.','과','와'),'과')
        s,docs=self.sample()
        text=notice.sentences(s['conclusions'][0],s['references'])[0]
        self.assertIn('장치는',text)
        self.assertIn('표시부(단락 [0012])와',text)
