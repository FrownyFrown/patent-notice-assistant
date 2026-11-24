"""자료의 지시문을 실행하지 않고 인용 글자만 대조한다."""
import unicodedata


def squash(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if not c.isspace() and not unicodedata.category(c).startswith('C'))


def contains(fragment, original):
    return bool(squash(fragment)) and squash(fragment) in squash(original)


def check_quote(doc, quote, nums):
    def answer(result, paragraphs=None, passages=None, message=''):
        return dict(result=result, paragraphs=paragraphs or [], message=message, passages=passages or [])
    needle = squash(quote)
    if not needle:
        return answer('none', message='인용문이 없습니다.')
    if len(needle) < 6 or '...' in needle or '\u2026' in quote:
        return answer('fail', message='인용문은 말줄임 없이 6자 이상이어야 합니다.')
    paragraphs = doc.get('paragraphs', [])
    known = {p.get('num', '') for p in paragraphs if p.get('num')}
    requested = set(nums)
    matches = []
    for width in (1, 2):
        for i in range(len(paragraphs)-width+1):
            group = paragraphs[i:i+width]
            for field in ('text', 'source_text'):
                values = [p.get(field, '') for p in group]
                if not all(values):
                    continue
                joined = ''.join(squash(value) for value in values)
                pos = joined.find(needle)
                if pos < 0:
                    continue
                if width == 2 and not (pos < len(squash(values[0])) < pos+len(needle)):
                    continue
                actual = list(dict.fromkeys(p['num'] for p in group if p.get('num')))
                good = (not actual or set(actual) <= requested) and requested <= known
                passages = [dict(num=p.get('num', ''), text=p.get(field, ''), translated=field == 'text' and bool(p.get('source_text'))) for p in group]
                matches.append((good, actual, passages))
    if not matches:
        return answer('fail', message='인용문이 원문에 없습니다.')
    good, actual, passages = next((m for m in matches if m[0]), matches[0])
    return answer('pass' if good else 'moved', actual, passages, '원문에서 확인했습니다.' if good else '원문에서 확인한 단락번호로 고쳤습니다.')
