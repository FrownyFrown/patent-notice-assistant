"""외부 자원 없는 HTML과 OOXML 초안."""
import html as html_lib
import io
import re
import zipfile


def clean(value):
    return ''.join(c for c in str(value) if c in '\n\t\r' or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)


def esc(value):
    return html_lib.escape(clean(value), quote=True)


def particle(text, consonant, vowel):
    text = re.sub(r'\(단락[^)]*\)', '', text)
    tail = re.sub(r'[^가-힣A-Za-z0-9]', '', text)[-1:]
    has = bool(tail) and (('가' <= tail <= '힣' and (ord(tail) - 0xAC00) % 28 != 0) or tail in '013678')
    if consonant == '으로' and tail and '가' <= tail <= '힣' and (ord(tail) - 0xAC00) % 28 == 8:
        return vowel
    return consonant if has else vowel


def paragraphs(nums):
    return '(단락 ' + ', '.join('[' + n + ']' for n in nums) + ')' if nums else '(단락번호 없음)'


def reference_text(text, refs):
    numbers = {r['doc_id']: '인용발명 ' + str(r['no']) for r in refs}
    if not numbers:
        return text
    pattern = '|'.join(re.escape(k) for k in sorted(numbers, key=len, reverse=True))
    return re.sub(pattern, lambda m: numbers[m.group()], text)


def inline(text):
    return re.sub(r'\s*\r?\n\s*', ' ', text).strip()


def sentences(r, refs, dependent=False):
    if r['verdict'] != 'refuse_draft':
        return []
    no = next(x['no'] for x in refs if x['doc_id'] == r['primary_doc_id'])
    claim = inline(r['common_claim_text'])
    cited = inline(reference_text(r['common_cited_text'], refs))
    result = []
    if claim and cited:
        result.append(f"제{r['claim']}항 발명에 기재된 {claim}{particle(claim, '은', '는')} 인용발명 {no}에 개시된 {cited}{paragraphs(r['common_paragraphs'])}{particle(cited, '과', '와')} 실질적으로 동일합니다.")
    for i, d in enumerate(r['differences']):
        loc = paragraphs(d['paragraphs']) if d['doc_id'] else ''
        reason = inline(reference_text(d['reason'], refs))
        text = inline(reference_text(d['text'], refs))
        if d['basis'] == 'other_reference':
            ref = next((x['no'] for x in refs if x['doc_id'] == d['doc_id']), None)
            if ref is not None and not re.match(r'인용발명 ' + str(ref) + r'(?!\d)', reason):
                reason = f'인용발명 {ref}에 기재된 ' + reason
        lead = '다만,' if i == 0 else '또한,'
        result.append(f"{lead} 제{r['claim']}항 발명은 {text}에서 인용발명 {no}{particle(str(no), '과', '와')} 차이가 있으나, 위 차이나는 부분은 {reason}{loc}{particle(reason, '으로', '로')} 쉽게 도출해낼 수 있는 것입니다.")
    if r['motivation'].strip() and not (dependent and not (claim and cited)):
        result.append(inline(reference_text(r['motivation'], refs)).rstrip('.') + '.')
    return result


LABELS = {'29-1-2': '제29조제1항제2호', '29-2': '제29조제2항',
          'yes': '있음', 'partial': '일부', 'no': '없음', 'unverified': '미확인',
          'pass': '일치', 'moved': '단락 수정', 'fail': '실패', 'none': '인용문 없음',
          'code': '프로그램', 'codex': '코덱스', 'user': '사용자',
          'ok': '확인', 'warn': '주의', 'todo': '확인 전'}


def label(value):
    return LABELS.get(value, value)


def sections(state, docs):
    conclusions = state['conclusions']
    dependent = {c['number'] for c in state['claims'] if c['kind'] == 'dependent'}
    refuses = [c for c in conclusions if c['verdict'] == 'refuse_draft']
    intro = '초안, 담당자 확인 필요. 비공식 보조 도구의 출력이며 법적 판단이 아닙니다.'
    if not refuses:
        intro = '거절이유를 찾지 못함. ' + intro
    supplied = {c['doc_id'] for c in state['candidates'] if c.get('origin') == 'user_pdf'}
    result = [('의견제출통지서 검토 초안', [f"{state['title']} ({state['application_number'] or state['case_id']}), 판단 기준일 {state['input']['basis_date']}", intro]),
              ('심사대상 청구항', [', '.join(str(c['number']) for c in state['claims'] if not c['deleted'])]),
              ('적용 조문', [', '.join(dict.fromkeys(label(c['statute']) for c in refuses)) or '없음']),
              ('거절이유 있는 청구항', [['청구항', '조문', '인용발명 조합']] +
               [[str(c['claim']), label(c['statute']), ', '.join(map(str, c['reference_nos']))] for c in refuses]),
              ('특허 가능한 청구항', ['거절이유를 찾지 못한 항: ' + (', '.join(str(c['claim']) for c in conclusions if c['verdict'] == 'no_reason_found') or '없음')]),
              ('보류 항', [', '.join(str(c['claim']) for c in conclusions if c['verdict'] == 'hold') or '없음']),
              ('구체적 거절이유', [t for c in refuses for t in [f"제{c['claim']}항", *sentences(c, state['references'], dependent=c['claim'] in dependent)]] or ['없음']),
              ('인용발명 목록', [['번호', '문헌번호', '제목', '공개일', '비고']] +
               [[str(r['no']), r['doc_id'], r['title'], r['publication_date'] or '', ', '.join(x for x in ('기계번역 포함' if r['machine_translated'] else '', '직접 넣은 PDF, 원본 확인 필요' if r['doc_id'] in supplied else '') if x)] for r in state['references']])]

    annex = [f"제{c['claim']}항 보류 사유: " + '; '.join(c['hold_reasons']) for c in conclusions if c['verdict'] == 'hold']
    annex += [f"빠진 문헌 {c['doc_id']}: {c['excluded_reason']}" for c in state['candidates'] if c['status'] != 'accepted']
    annex += [f"조사 범위: 검색 {state['usage']['search_calls']}회 / 한도 {state['usage']['search_limit']}회"]
    annex += ['빈칸 ' + g['component_id'] + ': ' + g['text'] for g in state['gaps']]
    for c in conclusions:
        annex += [f"제{c['claim']}항 효과 검토: {reference_text(c['effect_review'], state['references'])}", f"제{c['claim']}항 논리가 깨질 지점: {reference_text(c['weak_point'], state['references'])}"]
        for d in c['differences']:
            if d['basis'] == 'well_known':
                annex.append('주지관용 증거: ' + ('있음' if d['evidence'].get('has_evidence') else '없음') + ' ' + d['evidence'].get('detail', ''))
    annex += [('기재불비 메모: ' if n['kind'] == 'description' else '참고: ') + n['text'] + (': ' + n['quote'] + ' [' + label(n['check']) + ']' if n['kind'] == 'description' else '') for n in state['notes']]
    annex += ['점검표 ' + c['id'] + ' [' + label(c['by']) + '] ' + c['label'] + ': ' + label(c['result']) + ' ' + c['note'] for c in state['checklist']]
    annex += ['보정을 시사하는 글에는 법률적 효과가 없으며, 보정은 출원인이 정합니다.']
    result.append(('참고사항 별첨', annex))
    cs = {c['id']: c['claim'] for c in state['components']}
    result.append(('전항 검증표', [['청구항', '구성', '문헌', '판정', '단락', '인용문', '대조 결과']] +
                   [[str(cs.get(m['component_id'], '')), m['component_id'], m['doc_id'], label(m['verdict']),
                     ', '.join(m['paragraphs']) or '단락번호 없음', m['quote'],
                     '[원문 대조 실패, 담당자 확인 필요]' if m['check'] == 'fail' else label(m['check'])]
                    for m in state['matrix']]))
    return result


def html(state, docs):
    body = []
    for heading, rows in sections(state, docs):
        body.append('<section><h2>' + esc(heading) + '</h2>')
        table = bool(rows and isinstance(rows[0], list))
        if table:
            body.append('<div class="table"><table>')
        for i, row in enumerate(rows):
            if table:
                tag = 'th' if i == 0 else 'td'
                body.append('<tr>' + ''.join(f'<{tag}>' + esc(v) + f'</{tag}>' for v in row) + '</tr>')
            else:
                tag = 'h3' if re.fullmatch(r'제\d+항', row) else 'p'
                body.append('<' + tag + '>' + esc(row) + '</' + tag + '>')
        body.append('</table></div></section>' if table else '</section>')
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>검토 초안</title><style>body{font-family:"Malgun Gothic",sans-serif;margin:2rem;line-height:1.6}td,th{border:1px solid #777;padding:6px;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}.table{overflow:auto}p{white-space:pre-wrap}h2{font-size:1.2rem}</style><body>' + ''.join(body) + '</body></html>'


def docx(state, docs):
    w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    def p(text, heading=False):
        style = '<w:b/><w:sz w:val="28"/>' if heading else ''
        content = '</w:t><w:br/><w:t xml:space="preserve">'.join(esc(line) for line in str(text).splitlines())
        return '<w:p><w:r><w:rPr><w:rFonts w:ascii="Malgun Gothic" w:eastAsia="맑은 고딕"/>' + style + '</w:rPr><w:t xml:space="preserve">' + content + '</w:t></w:r></w:p>'
    body = []
    for heading, rows in sections(state, docs):
        body.append(p(heading, True))
        if rows and isinstance(rows[0], list):
            borders = ''.join(f'<w:{side} w:val="single" w:sz="4" w:color="777777"/>' for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
            grid = ''.join('<w:gridCol w:w="' + str(9638 // len(rows[0])) + '"/>' for _ in rows[0])
            body.append('<w:tbl><w:tblPr><w:tblW w:type="pct" w:w="5000"/><w:tblBorders>' + borders + '</w:tblBorders></w:tblPr><w:tblGrid>' + grid + '</w:tblGrid>')
            for i, row in enumerate(rows):
                shade = '<w:tcPr><w:shd w:fill="E8EDF2"/></w:tcPr>' if i == 0 else ''
                body.append('<w:tr>' + ''.join('<w:tc>' + shade + p(cell) + '</w:tc>' for cell in row) + '</w:tr>')
            body.append('</w:tbl>')
        else:
            body.extend(p(row, bool(re.fullmatch(r'제\d+항', row))) for row in rows)
    body.append('<w:sectPr><w:headerReference w:type="default" r:id="rId1"/><w:footerReference w:type="default" r:id="rId2"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1134" w:bottom="1440" w:left="1134" w:header="708" w:footer="708"/></w:sectPr>')
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>' + ''.join(f'<Override PartName="/word/{name}.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>' for name, kind in [('document', 'document.main'), ('header1', 'header'), ('footer1', 'footer')]) + '</Types>',
        '_rels/.rels': f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml': f'<w:document xmlns:w="{w}" xmlns:r="{rel}"><w:body>' + ''.join(body) + '</w:body></w:document>',
        'word/_rels/document.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="{rel}/{kind}" Target="{kind}1.xml"/>' for i, kind in [(1, 'header'), (2, 'footer')]) + '</Relationships>',
        'word/header1.xml': f'<w:hdr xmlns:w="{w}">' + p('초안, 담당자 확인 필요') + '</w:hdr>',
        'word/footer1.xml': f'<w:ftr xmlns:w="{w}"><w:p><w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p></w:ftr>'}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, value in files.items():
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + value)
    return output.getvalue()
