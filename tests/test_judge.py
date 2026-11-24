import copy
import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib.judge import enforce, hindsight
from lib.state import new_case


def fixture(count=1):
    s = new_case('case-test')
    s['claims'] = [dict(number=i, text='빛을 내는 장치', body='빛을 내는 장치', kind='independent' if i==1 else 'dependent', depends_on=[] if i==1 else [1], deleted=False, preamble='', start=0, end=8, warnings=[]) for i in range(1,count+1)]
    s['components'] = [dict(id=f'{i}-A', claim=i, text='빛을 내는 장치', group='', order=1, verified=True, synonyms=dict(ko=[],en=[],zh=[]), cpc=[]) for i in range(1,count+1)]
    doc = json.loads((ROOT / 'tests/example/publication.json').read_text())
    d = doc['doc_id']
    s['candidates'] = [dict(doc_id=d,status='accepted')]
    s['matrix'] = [dict(component_id=f'{i}-A',doc_id=d,verdict='yes',check='pass',paragraphs=['0012']) for i in range(1,count+1)]
    raw = dict(description_notes=[],conclusions=[dict(claim=i,verdict='refuse_draft',doc_ids=[d],primary_doc_id=d,common_claim_text='빛을 내는 장치',common_cited_text='빛을 내는 표시부',common_paragraphs=['0012'],differences=[],motivation='',effect_review='효과 검토',weak_point='용어 대응 확인') for i in range(1,count+1)])
    return s, {d:doc}, raw


class JudgeTest(unittest.TestCase):
    def test_common_text_is_built_from_components(self):
        s, docs, raw = fixture()
        s['components'] = [dict(s['components'][0], id='1-A', order=1, text='빛을 내는 표시부;'),
                           dict(s['components'][0], id='1-B', order=2, text='소리를 내는 스피커;'),
                           dict(s['components'][0], id='1-C', order=3, text='전원부를 포함하는 장치.')]
        s['matrix'] = [dict(s['matrix'][0], component_id=i) for i in ('1-A', '1-C')]
        raw['conclusions'][0].update(common_claim_text='모델이 줄여 쓴 글', differences=[dict(component_ids=['1-B'], text='스피커', basis='design_choice', doc_id='', paragraphs=[], reason='변경', evidence=dict(condition_1='가', condition_2='나'))])
        c = enforce(s, docs, raw)[0][0]
        self.assertEqual(c['common_claim_text'], '빛을 내는 표시부, 전원부를 포함하는 장치')
        self.assertEqual((c['verdict'], c['statute']), ('refuse_draft', '29-2'))

    def test_pure_single(self):
        s, docs, raw = fixture()
        before = copy.deepcopy((s,docs,raw))
        cs, refs, holds = enforce(s,docs,raw)
        self.assertEqual(cs[0]['statute'],'29-1-2')
        self.assertEqual(refs[0]['no'],1)
        self.assertFalse(holds)
        self.assertEqual((s,docs,raw),before)

    def test_unreceived_excluded_and_bad_paragraph(self):
        for mode in ('missing','excluded','number','check'):
            with self.subTest(mode=mode):
                s,docs,raw=fixture()
                if mode=='missing': docs={}
                if mode=='excluded': s['candidates'][0]['status']='excluded'
                if mode=='number': raw['conclusions'][0]['common_paragraphs']=['9999']
                if mode=='check': s['matrix'][0]['check']='fail'
                self.assertEqual(enforce(s,docs,raw)[0][0]['verdict'],'hold')

    def test_missing_and_partial(self):
        for verdict in ('no','partial','unverified'):
            s,docs,raw=fixture()
            s['matrix'][0]['verdict']=verdict
            self.assertEqual(enforce(s,docs,raw)[0][0]['verdict'],'hold')

    def test_parent(self):
        for verdict in ('no_reason_found','hold'):
            s,docs,raw=fixture(2)
            raw['conclusions'][0]['verdict']=verdict
            self.assertEqual(enforce(s,docs,raw)[0][1]['verdict'],verdict)

    def test_multiple_parents(self):
        s,docs,raw=fixture(3)
        s['claims'][2]['depends_on']=[1,2]
        raw['conclusions'][1]['verdict']='no_reason_found'
        self.assertEqual(enforce(s,docs,raw)[0][2]['verdict'],'hold')

    def test_bad_common_and_empty_reviews(self):
        for field in ('effect_review','weak_point'):
            s,docs,raw=fixture()
            raw['conclusions'][0][field]=''
            with self.assertRaises(ValueError): enforce(s,docs,raw)

    def difference(self, basis, evidence, doc_id=''):
        return dict(component_ids=['1-A'],text='빛의 차이',basis=basis,doc_id=doc_id,paragraphs=[],reason='근거가 있는 변경',evidence=evidence)

    def test_design_conditions(self):
        for valid in (False,True):
            s,docs,raw=fixture()
            s['matrix'][0]['verdict']='partial'
            raw['conclusions'][0]['differences']=[self.difference('design_choice',dict(condition_1='같은 기술사상',condition_2='더 나은 효과 없음' if valid else ''))]
            c=enforce(s,docs,raw)[0][0]
            self.assertEqual(c['verdict'],'refuse_draft' if valid else 'hold')
            if valid: self.assertEqual(c['statute'],'29-2')

    def test_well_known(self):
        for evidence, primary, expected in [(dict(has_evidence=False,detail='추가 증거 필요'),False,'refuse_draft'),({},False,'hold'),(dict(has_evidence=True,detail='자료'),True,'hold')]:
            s,docs,raw=fixture()
            d=next(iter(docs))
            raw['conclusions'][0]['differences']=[self.difference('well_known',evidence,d if primary else '')]
            self.assertEqual(enforce(s,docs,raw)[0][0]['verdict'],expected)

    def test_combination_motivation_limit_and_inherit(self):
        for mode in ('valid','motivation','limit'):
            s,docs,raw=fixture(2)
            d2='KR20180000002A'
            docs[d2]=dict(copy.deepcopy(next(iter(docs.values()))),doc_id=d2)
            s['candidates'].append(dict(doc_id=d2,status='accepted'))
            s['matrix'].append(dict(component_id='1-A',doc_id=d2,verdict='yes',check='pass',paragraphs=['0012']))
            r=raw['conclusions'][0]
            r['doc_ids'].append(d2)
            r['motivation']='공통 과제' if mode!='motivation' else ''
            diff=self.difference('other_reference',{},d2); diff['paragraphs']=['0012']
            r['differences']=[diff]
            if mode=='limit': s['settings']['max_references']=1
            cs,refs,_=enforce(s,docs,raw)
            self.assertEqual(cs[0]['verdict'],'refuse_draft' if mode=='valid' else 'hold')
            if mode=='valid':
                self.assertEqual(set(cs[1]['doc_ids']),set(cs[0]['doc_ids']))
                self.assertEqual(cs[1]['primary_doc_id'],cs[0]['primary_doc_id'])
                self.assertEqual([r['no'] for r in refs],[1,2])

    def test_hindsight(self):
        s,docs,raw=fixture()
        s['components'][0]['group']='1-G1'
        s['components'].append(dict(s['components'][0],id='1-B'))
        r=raw['conclusions'][0]
        r['doc_ids']=['A','B','C']
        r['differences']=[self.difference('other_reference',{},'B')]
        notes=hindsight(s,[r])
        self.assertEqual(len(notes),2)
