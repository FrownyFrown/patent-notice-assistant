"""청구범위 내부의 청구항과 서지 날짜를 추출한다."""
import re
from datetime import date

HEADER = re.compile(r'(?m)^[ \t]*(?:(?:공개특허|등록특허)[ \t]+[A-Z0-9-]+[ \t]*|-[ \t]*\d+[ \t]*-[ \t]*)(?:\r?\n|$)')
DATE = re.compile(r'(\d{4})\s*[년.\-]\s*(\d{1,2})\s*[월.\-]\s*(\d{1,2})\s*일?')
REF = r'(?:제\s*(\d+)\s*항|청구항\s*(\d+))'


def parse(text):
    if not isinstance(text, str):
        raise ValueError('청구항 입력은 글이어야 합니다.')
    warnings, claims, dates = [], [], []
    meta = text.split('청구범위', 1)[0]
    kind = None
    for line in meta.splitlines():
        if re.search(r'출\s*원\s*일', line):
            kind = 'application'
        elif re.search(r'공\s*개\s*일', line):
            kind = 'publication'
        elif re.search(r'우\s*선(?:권|일)', line):
            kind = 'priority'
        elif re.match(r'\s*\(\d{2}\)', line) or re.search(r'일\s*자', line):
            kind = None
        if kind:
            for match in DATE.finditer(line):
                try:
                    value = date(*(int(x) for x in match.groups())).isoformat()
                    dates.append(dict(kind=kind, date=value, snippet=line.strip()))
                except ValueError:
                    warnings.append('날짜 형식을 확인해 주세요.')
    title_match = re.search(r'발\s*명\s*의\s*명\s*칭[ \t]*([^\n]*)', meta)
    app_match = re.search(r'출\s*원\s*번\s*호\s*([0-9-]+)', meta)
    pub_match = re.search(r'공\s*개\s*번\s*호\s*([A-Za-z0-9 -]+)', meta)
    publication = ''
    if pub_match:
        from .patents import normalize, PatentError
        try:
            publication = normalize(pub_match[1].strip())
        except PatentError:
            warnings.append('공개번호를 확인해 주세요.')
    section = re.search(r'(?m)^[ \t]*(?:【\s*청\s*구\s*범\s*위\s*】|\[\s*청\s*구\s*범\s*위\s*\]|청\s*구\s*범\s*위[ \t]*\r?$)', text)
    if section:
        tail = text[section.end():]
        ending = re.search(r'(?m)^'+r'[ \t]*[【\[]?[ \t]*(?:'+ '|'.join(r'\s*'.join(w) for w in ('발명의설명','발명의상세한설명','기술분야','배경기술','요약','요약서','도면의간단한설명','도면'))+r')[ \t]*[】\]]?[ \t]*\r?$', tail)
        end = section.end() + (ending.start() if ending else len(tail))
        heads = list(re.finditer(r'(?m)(?:^[ \t]*|(?<=[】\]]))(?:【[ \t]*청\s*구\s*항\s*(\d+)[ \t]*】|\[[ \t]*청\s*구\s*항\s*(\d+)[ \t]*\]|청\s*구\s*항\s*(\d+)[ \t]*\r?$)', text[section.end():end]))
        for index, head in enumerate(heads):
            number = int(next(x for x in head.groups() if x))
            start = section.end()+head.end()
            stop = section.end()+(heads[index+1].start() if index+1 < len(heads) else end-section.end())
            raw = text[start:stop]
            start += len(raw)-len(raw.lstrip())
            stop -= len(raw)-len(raw.rstrip())
            raw = text[start:stop]
            clean = HEADER.sub('', raw).strip()
            notes = ['쪽 머리글을 제거했습니다.'] if clean != raw else []
            refs = []
            # 인용 전제는 청구항 첫머리에서만 찾는다.
            prefix = re.match(r'\s*'+REF+r'(?:(?:\s*(?:내지|부터|또는|및|,|와|과)\s*)'+REF+r')*', clean)
            if prefix:
                expression = prefix.group()
                refs = [int(a or b) for a, b in re.findall(REF, expression)]
                for match in re.finditer(REF+r'\s*(?:내지|부터)\s*'+REF, expression):
                    a, b, c, d = match.groups()
                    lo, hi = int(a or b), int(c or d)
                    if hi >= lo and hi-lo <= 10000:
                        refs.extend(range(lo, hi+1))
                    else:
                        notes.append('인용 범위를 확인해 주세요.')
            refs = sorted(set(refs))
            preamble = ''
            if prefix:
                rest = clean[prefix.end():]
                premise = re.match(r'\s*(?:(?:중\s*(?:어느\s*한\s*항)?\s*)?에\s*있어서|에\s*따른|중(?:\s*어느\s*한\s*항)?)[ \t]*,?', rest)
                named = re.match(r'(?:\s*중\s*어느\s*한\s*항)?(?:\s*에\s*기재된|\s*의)\s*[^,;\n]{1,60}?에\s*있어서[ \t]*,?', rest)
                if named or premise:
                    preamble = clean[:prefix.end()+(named or premise).end()].rstrip()
                elif re.match(r'\s*의\s*', rest):
                    notes.append('형식만 종속일 수 있음')
                else:
                    preamble = prefix.group().strip()
            claims.append(dict(number=number, text=clean, kind='dependent' if refs else 'independent', depends_on=refs, preamble=preamble, body=clean[len(preamble):].strip() if preamble else clean, deleted=bool(re.fullmatch(r'[\s(\[]*삭제[\s)\].]*', clean)), start=start, end=stop, warnings=notes))
    else:
        warnings.append('청구범위 절을 찾지 못했습니다.')
    numbers = [c['number'] for c in claims]
    available = set(numbers)
    if numbers and (min(numbers) != 1 or len(available) != max(numbers)):
        warnings.append('청구항 번호 누락이 있습니다.')
    if len(numbers) != len(available):
        warnings.append('청구항 번호 중복이 있습니다.')
    graph = {c['number']:c['depends_on'] for c in claims}
    for c in claims:
        if any(n not in available for n in c['depends_on']):
            c['warnings'].append('없는 항 인용이 있습니다.')
        if any(n >= c['number'] for n in c['depends_on']):
            c['warnings'].append('뒤 항 인용 또는 자기 인용이 있습니다.')
        pending, visited = list(c['depends_on']), set()
        while pending:
            node = pending.pop()
            if node == c['number']:
                c['warnings'].append('청구항 인용 순환이 있습니다.')
                break
            if node not in visited:
                visited.add(node)
                pending.extend(graph.get(node, []))
        warnings.extend(f"청구항 {c['number']}: {w}" for w in c['warnings'])
    total = re.search(r'전체\s*청구항\s*수\s*:\s*총\s*(\d+)\s*항', text)
    if total and int(total[1]) != len(claims):
        warnings.append('전체 청구항 수와 추출 개수가 불일치합니다.')
    return dict(title=title_match[1].strip() if title_match else '', application_number=app_match[1] if app_match else '', publication_number=publication, claims=claims, date_candidates=dates, warnings=warnings)
