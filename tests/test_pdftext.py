import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.pdftext import extract


def minimal_pdf(content=b'BT /F1 12 Tf 10 100 Td (Synthetic patent text for extraction.) Tj ET'):
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>', b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream']
    data = b'%PDF-1.4\n'
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    pos = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{x:010d} 00000 n \n'.encode() for x in offsets[1:])
    return data+b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(pos).encode()+b'\n%%EOF'


class PdfTest(unittest.TestCase):
    def test_extract(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            p = Path(folder)/'sample.txt'
            for encoding in ['utf-8','utf-8-sig','cp949']:
                p.write_bytes('가상 청구항\n가상 장치'.encode(encoding))
                self.assertEqual(extract(p)['text'], '가상 청구항\n가상 장치')
            p = Path(folder)/'sample.pdf'
            p.write_bytes(minimal_pdf())
            self.assertEqual(extract(p)['pages'], 1)
            self.assertIn('Synthetic', extract(p)['text'])
            p.write_bytes(minimal_pdf(b''))
            with self.assertRaisesRegex(ValueError, '스캔'):
                extract(p)
            with patch('lib.pdftext.MAX_BYTES', 1):
                with self.assertRaises(ValueError):
                    extract(p)
            p.write_bytes(minimal_pdf())
            with patch('lib.pdftext.MAX_PAGES', 0):
                with self.assertRaises(ValueError):
                    extract(p)
            from pypdf import PdfReader, PdfWriter
            writer = PdfWriter()
            writer.append(PdfReader(p))
            writer.encrypt('synthetic-password')
            with p.open('wb') as f:
                writer.write(f)
            with self.assertRaisesRegex(ValueError, '암호'):
                extract(p)
