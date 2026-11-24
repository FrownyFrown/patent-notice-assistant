"""사건 상태와 원자적 저장."""
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULTS = dict(max_references=4, search_limit=6, top_paragraphs=8)
KEYS = ['input', 'claims', 'components', 'search', 'compare', 'gap', 'judge', 'notice']
NAMES = ['입력', '청구항', '구성 분해', '검색', '대조', '빈칸 검색', '판단 초안', '통지서']


def now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode('utf-8'))
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(21):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if attempt == 20:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        return json.load(f)


def save(path, state):
    updated = dict(state, revision=state['revision'] + 1, updated_at=now())
    atomic(path, json.dumps(updated, ensure_ascii=False, indent=2) + '\n')
    state.update(updated)


def new_case(case_id, parsed=None, extracted=None, file_name='', sha256='', settings=None,
             public_confirmed=False, application_date=None, priority_date=None,
             publication_number=''):
    if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z-]{0,63}', case_id):
        raise ValueError('사건 이름이 올바르지 않습니다.')
    parsed, extracted = parsed or {}, extracted or {}
    date_warnings = []
    dates = parsed.get('date_candidates', [])
    if application_date is None:
        candidates = sorted({d['date'] for d in dates if d['kind'] == 'application'})
        if len(candidates) == 1:
            application_date = candidates[0]
        elif len(candidates) > 1:
            date_warnings.append('출원일 후보가 여러 날입니다. 맞는지 확인하세요.')
    if priority_date is None:
        candidates = sorted({d['date'] for d in dates if d['kind'] == 'priority'})
        priority_date = candidates[0] if candidates else None
    at = now()
    cfg = dict(DEFAULTS, **(settings or {}))
    s = dict(schema_version=1, case_id=case_id, title=parsed.get('title', ''),
             application_number=parsed.get('application_number', ''),
             publication_number=publication_number or parsed.get('publication_number', ''),
             created_at=at, updated_at=at, revision=0, draft_notice='초안, 담당자 확인 필요', settings=cfg)
    s['input'] = dict(file_name=file_name, kind=extracted.get('kind', 'txt'), sha256=sha256,
                      pages=extracted.get('pages'), chars=len(extracted.get('text', '')),
                      public_confirmed=public_confirmed, public_confirmed_at=at if public_confirmed else None,
                      application_date=application_date, priority_date=priority_date,
                      basis_date=priority_date or application_date,
                      basis_source='priority' if priority_date else 'application' if application_date else '',
                      date_candidates=parsed.get('date_candidates', []),
                      warnings=extracted.get('warnings', []) + parsed.get('warnings', []) + date_warnings)
    s['steps'] = [dict(id=i, key=k, name=NAMES[i], by='code' if i in (0, 1, 7) else 'codex',
                       status='todo', message='', started_at=None, finished_at=None, attempts=0)
                  for i, k in enumerate(KEYS)]
    s['next'] = dict(step=0, actor='user', title='', command='', worksheet='', output='', worksheet_chars=0, say='')
    s['claims'] = parsed.get('claims', [])
    for key in ['components', 'candidates', 'matrix', 'gaps', 'references', 'conclusions',
                'checklist', 'notes', 'artifacts', 'events']:
        s[key] = []
    s['verification'] = dict(checked_at=None, summary=dict.fromkeys(['pass', 'moved', 'fail', 'none'], 0), items=[])
    labels = ['청구항이 원본과 같음', '출원일과 우선일이 맞음', '후보 문헌과 제외 사유를 봄',
              '인용문과 단락을 원문에서 봄', '청구항별 결론을 판단함', '통지서 문장을 읽고 고침']
    s['review_items'] = [dict(key=k, label=v, required=True) for k, v in zip(
        ['claims', 'dates', 'candidates', 'quotes', 'conclusions', 'notice'], labels)]
    s['usage'] = dict(search_calls=0, search_limit=cfg['search_limit'], worksheet_chars=[], note='토큰 수는 Codex 화면에서 확인')
    for i in (0, 1):
        transition(s, i, 'done')
    claim_warnings = list(parsed.get('warnings', []))
    claim_warnings += [w for c in s['claims'] for w in c.get('warnings', [])]
    if claim_warnings:
        transition(s, 1, 'warning', '; '.join(dict.fromkeys(claim_warnings)))
    return s


def transition(s, step, status, message=''):
    row = s['steps'][step]
    if row['status'] == status and row['message'] == message:
        return
    row.update(status=status, message=message)
    if status in ('working', 'done', 'warning', 'skipped'):
        row['started_at'] = row['started_at'] or now()
    if status == 'working':
        row['attempts'] += 1
    row['finished_at'] = now() if status in ('done', 'warning', 'skipped') else None


def invalidate(s, step):
    fields = {2: ['components'], 3: ['candidates'], 4: ['matrix', 'gaps'],
              5: [], 6: ['conclusions', 'references', 'checklist']}
    for i in range(step, 8):
        transition(s, i, 'stale')
        for key in fields.get(i, []):
            s[key] = []
    if step <= 4:
        s['verification'] = dict(checked_at=None, summary=dict.fromkeys(['pass', 'moved', 'fail', 'none'], 0), items=[])
    for a in s['artifacts']:
        a['stale'] = True


def event(s, step, message, level='info'):
    s['events'] = (s['events'] + [dict(at=now(), step=step, level=level, message=message)])[-50:]
