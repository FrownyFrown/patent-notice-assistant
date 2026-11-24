"""PDF와 텍스트 파일의 글자 추출."""
import logging
import sys
from pathlib import Path

MAX_BYTES = 200 * 1024 * 1024
MAX_PAGES = 600


def extract(path: Path):
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('파일 크기는 200MB 이하여야 합니다.')
        kind = path.suffix.lower().lstrip('.')
        if kind == 'txt':
            data = path.read_bytes()
            for encoding in ('utf-8-sig', 'cp949'):
                try:
                    text = data.decode(encoding)
                    return dict(text=text, kind=kind, pages=None, warnings=[])
                except UnicodeDecodeError:
                    pass
            raise ValueError('TXT 인코딩을 UTF-8 또는 CP949로 바꿔 주세요.')
        if kind != 'pdf':
            raise ValueError('PDF 또는 TXT 파일을 넣어 주세요.')
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'vendor'))
        logger = logging.getLogger('pypdf')
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('암호 PDF입니다. 암호를 해제한 사본을 넣어 주세요.')
        if len(reader.pages) > MAX_PAGES:
            raise ValueError('PDF는 600쪽 이하여야 합니다.')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        if sum(c.isalnum() for c in text) < 10:
            raise ValueError('글자가 거의 없는 스캔 PDF입니다. OCR 처리한 파일을 넣어 주세요.')
        return dict(text=text, kind=kind, pages=len(reader.pages), warnings=[])
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('파일을 읽지 못했습니다. 파일 형식과 읽기 권한을 확인해 주세요.') from exc
