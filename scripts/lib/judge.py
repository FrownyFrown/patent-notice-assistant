"""판단 초안에 적용하는 보수적인 순수 함수."""
import re
from copy import deepcopy
from .verify import contains


def enforce(state, docs, raw):
    rows = raw['conclusions'] if isinstance(raw, dict) else raw
    active = [c for c in state['claims'] if not c['deleted']]
    if sorted(r['claim'] for r in rows) != sorted(c['number'] for c in active):
        raise ValueError('삭제되지 않은 모든 청구항의 판단을 한 번씩 제출하세요.')
    accepted = {c['doc_id'] for c in state['candidates'] if c['status'] == 'accepted'}
    valid_docs = accepted & set(docs)
    results, references, holds, seen = [], [], [], set()
    by_claim, ref_by_id = {}, {}
    components = state['components']
    matrix = state['matrix']
    used = set()
    for claim in sorted(active, key=lambda c: c['number']):
        num = claim['number']
        r = deepcopy(next(r for r in rows if r['claim'] == num))
        r.update(reference_nos=[], hold_reasons=[], sentences=[], statute='')
        reasons = r['hold_reasons']
        if r['verdict'] == 'refuse_draft':
            # 공통점 청구항 글은 차이점이 아닌 구성의 원문으로 프로그램이 조립한다. 구성이 빠지거나 바뀌지 않는다.
            different = {i for d in r['differences'] for i in d['component_ids']}
            r['common_claim_text'] = ', '.join(c['text'].strip(' ;,.\r\n\t') for c in sorted(components, key=lambda c: c['order'])
                                               if c['claim'] == num and c['id'] not in different)
            r['common_claim_text'] = re.sub(r', (?=(?:을|를|은|는|과|와)\s)', '', r['common_claim_text'])
            if not r['common_claim_text']:
                r.update(common_cited_text='', common_paragraphs=[])
        elif r['common_claim_text'] and not contains(r['common_claim_text'], claim['body'] if claim['kind'] == 'dependent' else claim['text']):
            raise ValueError(f'제{num}항 common_claim_text가 청구항 원문에 없습니다.')
        if r['verdict'] == 'refuse_draft' and (not r['effect_review'].strip() or not r['weak_point'].strip()):
            raise ValueError(f'제{num}항 effect_review와 weak_point를 채우세요.')
        parents = [by_claim.get(p) for p in claim['depends_on']]
        inherited = []
        if parents:
            if len(parents) == 1 and parents[0] and parents[0]['verdict'] == 'no_reason_found':
                r['verdict'] = 'no_reason_found'
            elif any(not p or p['verdict'] != 'refuse_draft' for p in parents):
                r['verdict'] = 'hold'
                reasons.append('상위항이 모두 거절 초안으로 확인되지 않았습니다.')
            inherited = [d for p in parents if p for d in p['doc_ids']]
            r['doc_ids'] = list(dict.fromkeys(inherited + r['doc_ids']))
            primary = [p['primary_doc_id'] for p in parents if p and p['primary_doc_id']]
            if primary:
                r['primary_doc_id'] = primary[0]
            if len(set(primary)) > 1:
                reasons.append('상위항의 주인용 문헌이 서로 다릅니다.')
        r['doc_ids'] = list(dict.fromkeys(r['doc_ids']))
        if any(d not in valid_docs for d in r['doc_ids']):
            reasons.append('받지 않았거나 제외된 문헌은 인용할 수 없습니다.')
        relevant = [c for c in components if c['claim'] == num]
        ids = {c['id'] for c in relevant}
        checked = [m for m in matrix if m['doc_id'] in valid_docs and m['check'] in ('pass', 'moved')]

        if len(r['doc_ids']) > 1:
            used_here = {m['doc_id'] for m in checked if m['component_id'] in ids and m['verdict'] in ('yes', 'partial')}
            r['doc_ids'] = [d for d in r['doc_ids'] if d in used_here or d in inherited]

        def numbers_ok(doc_id, nums, component_ids=None):
            actual = {p['num'] for p in docs.get(doc_id, {}).get('paragraphs', []) if p['num']}
            evidence = [m for m in checked if m['doc_id'] == doc_id and
                        m['component_id'] in (component_ids if component_ids is not None else ids)]
            verified = {p for m in evidence for p in m['paragraphs']}
            return bool(evidence) and set(nums) <= actual & verified and (bool(nums) or not docs[doc_id]['numbered'])

        if r['verdict'] == 'refuse_draft':
            primary = r['primary_doc_id']
            if primary not in r['doc_ids'] or primary not in valid_docs:
                reasons.append('주인용 문헌을 확인할 수 없습니다.')
            if r['common_claim_text'] or r['common_cited_text'] or r['common_paragraphs']:
                if not numbers_ok(primary, r['common_paragraphs']):
                    reasons.append('공통점 단락은 해당 항의 원문 대조를 통과해야 합니다.')
            covered_diff = set()
            for diff in r['differences']:
                ds = set(diff['component_ids'])
                if not ds or not ds <= ids:
                    reasons.append('차이점의 구성 번호가 올바르지 않습니다.')
                covered_diff |= ds
                if not diff['text'].strip() or not diff['reason'].strip():
                    reasons.append('차이점과 도출 이유가 필요합니다.')
                d = diff['doc_id']
                if d and (d not in valid_docs or d not in r['doc_ids']):
                    reasons.append('차이점의 문헌이 인용 목록에 없습니다.')
                if diff['paragraphs'] and not numbers_ok(d, diff['paragraphs'], ds):
                    reasons.append('차이점 단락의 원문 대조가 확인되지 않았습니다.')
                ev = diff['evidence']
                expected = {'other_reference': set(), 'well_known': {'has_evidence', 'detail'}, 'design_choice': {'condition_1', 'condition_2'}}[diff['basis']]
                if set(ev) != expected:
                    reasons.append('차이점 근거 유형과 evidence 형식이 다릅니다.')
                if diff['basis'] == 'other_reference':
                    if not numbers_ok(d, diff['paragraphs'], ds):
                        reasons.append('다른 인용발명의 검증 근거가 없습니다.')
                elif diff['basis'] == 'well_known':
                    if type(ev.get('has_evidence')) is not bool or not ev.get('detail', '').strip():
                        reasons.append('주지관용 증거 유무와 설명을 적으세요.')
                    if d and d == primary:
                        reasons.append('주지관용 증거 문헌은 주인용으로 쓸 수 없습니다.')
                elif diff['basis'] == 'design_choice':
                    if not all(isinstance(ev.get(k), str) and ev[k].strip() for k in ('condition_1', 'condition_2')):
                        reasons.append('설계변경의 두 조건에 근거가 필요합니다.')
            for c in relevant:
                matches = [m for m in checked if m['component_id'] == c['id'] and m['doc_id'] in r['doc_ids']]
                yes = any(m['verdict'] == 'yes' and (m['doc_id'] == primary or any(
                    d['basis'] == 'other_reference' and d['doc_id'] == m['doc_id'] and c['id'] in d['component_ids']
                    for d in r['differences'])) for m in matches)
                if c['id'] not in covered_diff and not yes:
                    reasons.append(f"구성 {c['id']}에 확인된 공통점 또는 차이점 근거가 없습니다.")
                if any(m['verdict'] == 'partial' and m['doc_id'] == primary for m in matches) and c['id'] not in covered_diff:
                    reasons.append(f"일부만 대응하는 구성 {c['id']}을 차이점으로 적으세요.")
            if any(c['id'] not in covered_diff for c in relevant) and not (r['common_claim_text'].strip() and r['common_cited_text'].strip()):
                reasons.append('공통점의 청구항 글과 인용 글이 필요합니다.')
            if not relevant:
                reasons.append('확인된 구성이 없습니다.')
            combo = frozenset(r['doc_ids'])
            if len(combo) > 1 and combo not in seen and not r['motivation'].strip():
                reasons.append('처음 사용하는 문헌 조합에는 결합 동기가 필요합니다.')
            if len(used | combo) > state['settings']['max_references']:
                reasons.append('최대 인용 문헌 수를 넘습니다.')
            if reasons:
                r['verdict'] = 'hold'
            else:
                r['statute'] = '29-1-2' if not r['differences'] and len(combo) == 1 and not any(p and p['statute'] == '29-2' for p in parents) else '29-2'
                seen.add(combo)
                used |= combo
        if r['verdict'] != 'refuse_draft':
            r.update(doc_ids=[], primary_doc_id='', statute='')
        else:
            ordered = [r['primary_doc_id']] + [d for d in r['doc_ids'] if d != r['primary_doc_id']]
            r['doc_ids'] = ordered
            for d in ordered:
                if d not in ref_by_id:
                    doc = docs[d]
                    ref = dict(no=len(references) + 1, doc_id=d, title=doc['title'],
                               publication_date=doc['publication_date'], primary_for=[], used_in=[],
                               machine_translated=doc['machine_translated'], url=doc['url'])
                    ref_by_id[d] = ref
                    references.append(ref)
                ref = ref_by_id[d]
                ref['used_in'].append(num)
                if d == r['primary_doc_id']:
                    ref['primary_for'].append(num)
                r['reference_nos'].append(ref['no'])
        r['hold_reasons'] = list(dict.fromkeys(reasons))
        holds.extend(f'제{num}항: {reason}' for reason in reasons)
        results.append(r)
        by_claim[num] = r
    return results, references, holds


def hindsight(state, conclusions):
    notes = []
    for r in conclusions:
        if r['verdict'] != 'refuse_draft':
            continue
        warnings = []
        if len(r['doc_ids']) >= 3:
            warnings.append('문헌 3건 이상 결합: 사후적 고찰을 확인하세요.')
        groups = {}
        for c in state['components']:
            if c['claim'] == r['claim'] and c['group']:
                groups.setdefault(c['group'], set()).add(c['id'])
        for d in r['differences']:
            if d['basis'] == 'other_reference':
                for group in groups.values():
                    if group & set(d['component_ids']) and not group <= set(d['component_ids']):
                        warnings.append('유기적 묶음 일부를 다른 문헌에서 가져왔습니다.')
        notes += [dict(kind='hindsight', claim=r['claim'], text=t, quote='', check='none') for t in dict.fromkeys(warnings)]
    return notes
