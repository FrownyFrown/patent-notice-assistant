import copy
import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import work
from lib import state, notice, sheets
from lib.judge import enforce
from tests.test_judge import fixture


class MaintenanceTest(unittest.TestCase):
    def test_03_dates_and_warning(self):
        parsed = dict(date_candidates=[dict(kind=k, date=d) for k, d in [
            ('application', '2024-02-01'), ('priority', '2023-01-01'),
            ('priority', '2022-01-01')]], warnings=['전체 청구항 수와 추출 개수가 불일치합니다.'])
        s = state.new_case('test', parsed)
        self.assertEqual(s['input']['application_date'], '2024-02-01')
        self.assertEqual(s['input']['basis_date'], '2022-01-01')
        self.assertEqual(s['input']['basis_source'], 'priority')
        self.assertEqual(s['steps'][1]['status'], 'warning')
        self.assertIn('불일치', s['steps'][1]['message'])
        parsed['date_candidates'].append(dict(kind='application', date='2024-03-01'))
        s = state.new_case('test', parsed)
        self.assertIsNone(s['input']['application_date'])
        self.assertTrue(any('출원일' in w for w in s['input']['warnings']))
        s = state.new_case('test', parsed, application_date='2020-01-01')
        self.assertEqual(s['input']['application_date'], '2020-01-01')

    def sheet_state(self, stage):
        s, docs, raw = fixture()
        for c in s['candidates']:
            c.update({k: docs[c['doc_id']][k] for k in ('title', 'publication_date', 'machine_translated')})
        s['input'].update(public_confirmed=True, basis_date='2025-01-01')
        for i in range(stage): state.transition(s, i, 'done')
        state.transition(s, stage, 'ready')
        if stage == 4: s['matrix'] = []
        if stage == 6:
            s['matrix'][0].update(quote='글', passages=[{'text': '불필요한 원문'}])
        return s, docs

    def test_04_05_12_sheets(self):
        with tempfile.TemporaryDirectory() as td, patch.object(work, 'ROOT', Path(td).resolve()):
            folder = Path(td).resolve() / 'cases/test'
            for stage in (2, 3, 4, 6):
                with self.subTest(stage=stage):
                    s, docs = self.sheet_state(stage)
                    with patch.object(work, 'docs_for', return_value=docs):
                        body, _ = work.make_sheet(folder, s)
                        before = copy.deepcopy(s)
                        again, _ = work.make_sheet(folder, s)
                    self.assertEqual(body, again)
                    self.assertEqual(s['usage'], before['usage'])
                    self.assertEqual(s['steps'], before['steps'])
                    self.assertIn('scripts/work.py submit ' + state.KEYS[stage], body)
                    self.assertIn('cases/test/work/result-', body)
                    self.assertIn('결과 JSON 예', body)
                    marker = next(x for x in body.splitlines() if x.startswith('DATA-'))
                    data = json.loads(body.split(marker)[1])
                    if stage == 2:
                        self.assertEqual(set(data), {'title', 'claims'})
                        self.assertEqual(set(data['claims'][0]), {'number','kind','depends_on','text'})
                    if stage == 3:
                        self.assertEqual(set(data['components'][0]), {'id','text','synonyms','cpc'})
                    if stage == 4:
                        self.assertEqual(set(data['components'][0]), {'id','text'})
                    if stage == 6:
                        self.assertNotIn('passages', data['matrix'][0])
                        self.assertEqual(set(data['components'][0]), {'id','claim','text','group'})
                        self.assertIn('references/judgement.md', body)
                        self.assertIn('sentence-forms.md', body)

    def test_04_round_robin_budget(self):
        s, docs = self.sheet_state(4)
        s['components'].append(dict(s['components'][0], id='1-B'))
        d = next(iter(docs.values()))
        d['paragraphs'] = [dict(id=str(i), num=str(i), text=str(i)*6000) for i in range(4)]
        with tempfile.TemporaryDirectory() as td, patch.object(work, 'ROOT', Path(td).resolve()), \
                patch.object(work, 'docs_for', return_value=docs), \
                patch('lib.rank.top', return_value={'1-A':['0','1'], '1-B':['2','3']}):
            body, _ = work.make_sheet(Path(td).resolve()/'cases/test', s)
        marker = next(x for x in body.splitlines() if x.startswith('DATA-'))
        data = json.loads(body.split(marker)[1])
        ps = data['documents'][0]['paragraphs']
        self.assertEqual([p['id'] for p in ps], ['0','2'])
        self.assertLessEqual(sum(len(p['text']) for p in ps),16000)
        self.assertEqual(set(data['truncated_component_ids']), {'1-A','1-B'})
        self.assertIn('rank', body)

    def test_05_examples_match_schemas(self):
        for stage in (2,3,4,5,6):
            example = sheets.EXAMPLES[stage]
            name = 'search' if stage == 5 else state.KEYS[stage]
            self.assertEqual(work.schema_check(example, work.read_json(ROOT/'schemas'/(name+'.json'))), [])

    def test_06_sentences(self):
        s, docs, raw = fixture()
        r = raw['conclusions'][0]
        d = r['primary_doc_id']
        refs = [dict(doc_id=d,no=1),dict(doc_id='KR20180000002A',no=2)]
        r['common_claim_text'] = '빛을\n내는 장치'
        r['common_cited_text'] = d + '의 표시부'
        r['differences'] = [dict(text=d+'의 차이',reason='연결',doc_id=refs[1]['doc_id'],paragraphs=['0012'],basis='other_reference'),dict(text='차이',reason='변경',doc_id='',paragraphs=[],basis='design_choice')]
        r['motivation'] = d + '의 공통 과제'
        text = '\n'.join(notice.sentences(r, refs))
        self.assertNotIn(d,text)
        self.assertIn('빛을 내는 장치는',text)
        self.assertIn('인용발명 2에 기재된 연결(단락 [0012])로',text)
        self.assertIn('변경으로',text)
        self.assertIn('또한,',text)
        self.assertNotIn('결합 이유:',text)
        self.assertEqual(r['common_claim_text'],'빛을\n내는 장치')
        self.assertEqual(notice.particle('연결(단락 [0012])','으로','로'),'로')

    def test_07_judge(self):
        s, docs, raw = fixture(2)
        raw['conclusions'][0]['differences'] = [dict(component_ids=['1-A'],text='차이',basis='design_choice',doc_id='',paragraphs=[],reason='변경',evidence=dict(condition_1='동일',condition_2='효과 없음'))]
        cs, _, _ = enforce(s,docs,raw)
        self.assertEqual(cs[1]['statute'],'29-2')
        raw['conclusions'][0].update(differences=[], common_cited_text='')
        self.assertEqual(enforce(s,docs,raw)[0][0]['verdict'],'hold')
        for r in raw['conclusions']:
            r.update(verdict='hold',effect_review='',weak_point='')
        enforce(s,docs,raw)

    def test_07_unused_document(self):
        s, docs, raw = fixture()
        extra='KR20180000002A'
        docs[extra]=dict(next(iter(docs.values())),doc_id=extra)
        s['candidates'].append(dict(doc_id=extra,status='accepted'))
        raw['conclusions'][0]['doc_ids'].append(extra)
        cs, _, _=enforce(s,docs,raw)
        self.assertNotIn(extra,cs[0]['doc_ids'])

    def test_08_output(self):
        s, docs, raw = fixture()
        s['conclusions'],s['references'],_=enforce(s,docs,raw)
        s['matrix'][0].update(quote='첫 줄\n둘째 줄')
        s['checklist']=[dict(id='1',by='code',label='확인',result='ok',note='')]
        text=notice.html(s,docs)
        self.assertNotIn('29-1-2',text)
        self.assertNotIn('[code]',text)
        self.assertIn('제29조제1항제2호',text)
        self.assertIn('<th>문헌번호</th>',text)
        with zipfile.ZipFile(io.BytesIO(notice.docx(s,docs))) as z:
            xml=z.read('word/document.xml').decode()
        for token in ('<w:b/>','<w:sz','<w:tblGrid>','w:type="pct"','w:w="5000"','<w:shd','<w:br/>','제1항'):
            self.assertIn(token,xml)

    def test_09_description_notes(self):
        s, docs, raw = fixture()
        s['input']['basis_date']='2025-01-01'
        for c in s['candidates']: c['publication_date']=docs[c['doc_id']]['publication_date']
        raw['description_notes']=[dict(claim=1,text='기재 확인',quote='있는 글'),dict(claim=1,text='없는 인용',quote='다른 글')]
        self.assertEqual(work.schema_check(raw,work.read_json(ROOT/'schemas/judge.json')),[])
        with tempfile.TemporaryDirectory() as td, patch.object(work,'docs_for',return_value=docs):
            folder=Path(td); (folder/'source.txt').write_text('있는 글',encoding='utf-8')
            work.judgement(folder,s,raw)
            self.assertEqual([n['check'] for n in s['notes'] if n['kind']=='description'],['pass','fail'])
            raw['description_notes']=[]
            work.judgement(folder,s,raw)
            self.assertFalse(any(n['kind']=='description' for n in s['notes']))

    def test_10_atomic_retry(self):
        with tempfile.TemporaryDirectory() as td:
            with patch('lib.state.os.replace',side_effect=[PermissionError(),PermissionError(),None]) as replace, patch('lib.state.time.sleep') as sleep:
                state.atomic(Path(td)/'x','ok')
                self.assertEqual(replace.call_count,3)
                self.assertEqual(sleep.call_count,2)
            with patch('lib.state.os.replace',side_effect=PermissionError()), patch('lib.state.time.sleep') as sleep:
                with self.assertRaises(PermissionError): state.atomic(Path(td)/'x','ok')
                self.assertEqual(sleep.call_count,20)
            self.assertEqual(list(Path(td).glob('.write-*')),[])

    def test_11_bad_number_and_reason(self):
        s=state.new_case('test',application_date='2025-01-01')
        d='KR20190000001A'
        s['candidates']=[work.candidate(d,'앞 사유')]
        raw=dict(search_calls=1,candidates=[dict(doc_id='잘못된 번호',reason='',origin='manual',title=''),dict(doc_id=d,reason='뒤 사유',origin='search_report',title='')])
        self.assertEqual(work.schema_check(raw,work.read_json(ROOT/'schemas/search.json')),[])
        with redirect_stdout(io.StringIO()) as out, patch.object(work,'receive') as receive:
            work.search_submit(Path('.'),s,raw,3)
        self.assertIn('bad_number',out.getvalue())
        self.assertEqual(len(s['candidates']),1)
        self.assertIn('뒤 사유',s['candidates'][0]['reason'])
        receive.assert_not_called()

    def test_13_verification_items(self):
        s, docs, _=fixture()
        s['matrix'][0].update(verdict='no',quote='',check='none',check_message='',passages=[],paragraphs=[])
        with patch.object(work,'docs_for',return_value=docs),patch.object(work,'classify'):
            work.verify_all(Path('.'),s)
        self.assertEqual(s['verification']['items'],[])
        self.assertEqual(s['verification']['summary']['none'],1)
        sample=work.read_json(ROOT/'tests/fixtures/state-sample.json')
        self.assertTrue(all(i['quote'] and i['result']!='none' for i in sample['verification']['items']))

    def test_14_doctor(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ('내 드라이브','Google Drive','GoogleDrive-test','OneDrive - test','iCloud'):
                with self.subTest(name=name),patch.object(work,'ROOT',Path(td)/name),redirect_stdout(io.StringIO()) as out:
                    work.doctor(True)
                self.assertIn('동기화 폴더',out.getvalue())
                self.assertIn('input/',out.getvalue())

    def test_12_docx_deterministic(self):
        s, docs, raw = fixture()
        s['conclusions'], s['references'], _ = enforce(s, docs, raw)
        s['matrix'][0]['quote'] = '인용'
        with patch('zipfile.time.localtime', return_value=(2020,1,1,0,0,0,0,1,0)):
            first = notice.docx(s, docs)
        with patch('zipfile.time.localtime', return_value=(2021,1,1,0,0,0,0,1,0)):
            second = notice.docx(s, docs)
        self.assertEqual(first, second)

    def test_later_sheets_keep_dependent_claim_text(self):
        for stage in (3,6):
            s, docs=self.sheet_state(stage)
            s['claims'][0].update(kind='dependent',depends_on=[2],text='제2항에 있어서, 추가 구성',body='추가 구성')
            with tempfile.TemporaryDirectory() as td, patch.object(work,'ROOT',Path(td).resolve()),patch.object(work,'docs_for',return_value=docs):
                body,_=work.make_sheet(Path(td).resolve()/'cases/test',s)
            marker=next(x for x in body.splitlines() if x.startswith('DATA-'))
            data=json.loads(body.split(marker)[1])
            self.assertEqual(data['claims'][0]['text'],s['claims'][0]['text'])

    def test_verification_ignores_blank_quote(self):
        s, docs, _=fixture()
        s['matrix'][0].update(verdict='no',quote=' \n',check='none',check_message='',passages=[],paragraphs=[])
        with patch.object(work,'docs_for',return_value=docs),patch.object(work,'classify'):
            work.verify_all(Path('.'),s)
        self.assertEqual(s['verification']['items'],[])
        self.assertEqual(s['verification']['summary']['none'],1)

    def test_dependent_without_common_only_difference(self):
        _, _, raw=fixture()
        r=raw['conclusions'][0]
        r.update(common_claim_text='',common_cited_text='',common_paragraphs=[],motivation='결합 이유 문장')
        r['differences']=[dict(text='추가 구성',reason='변경',doc_id='',paragraphs=[],basis='design_choice')]
        refs=[dict(doc_id=r['primary_doc_id'],no=1)]
        result=notice.sentences(r,refs,dependent=True)
        self.assertEqual(len(result),1)
        self.assertIn('차이가 있으나',result[0])

    def test_unused_note_and_hold_merge(self):
        s, docs, raw=self.sheet_state(6)[0], fixture()[1], fixture()[2]
        extra='KR20180000002A'
        docs[extra]=dict(next(iter(docs.values())),doc_id=extra)
        s['candidates'].append(dict(s['candidates'][0],doc_id=extra))
        raw['conclusions'][0]['doc_ids'].append(extra)
        with patch.object(work,'docs_for',return_value=docs):
            work.judgement(Path('.'),s,raw)
            self.assertTrue(any(extra in n['text'] for n in s['notes']))
            s['conclusions'][0].update(verdict='hold',hold_reasons=['이전 사유'])
            raw['conclusions'][0]['common_paragraphs']=['9999']
            work.judgement(Path('.'),s,raw,rebuild=True)
            reasons=s['conclusions'][0]['hold_reasons']
            self.assertIn('이전 사유',reasons)
            self.assertGreater(len(reasons),1)
            self.assertEqual(len(reasons),len(set(reasons)))

    def test_changed_receive_recovery_and_failure(self):
        from lib import patents
        from tests.doc_helper import write_doc
        from tests.test_patents import Response, page
        doc = json.loads((ROOT/'tests/example/publication.json').read_bytes())
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as td:
            folder=Path(td)
            s=state.new_case('test',public_confirmed=True,application_date='2025-01-01')
            c=work.candidate(doc['doc_id'])
            s['candidates']=[c]
            write_doc(folder/'docs',doc)
            work.receive(folder,s,c)
            self.assertEqual(c['status'],'accepted')
            path=folder/'docs'/(doc['doc_id']+'.json')
            path.write_bytes(b'{')
            self.assertEqual(work.docs_for(folder,s),{})
            self.assertEqual(c['excluded_code'],'changed')
            with patch('lib.patents.build_opener') as opening:
                opening.return_value.open.side_effect=OSError('연결 실패')
                work.receive(folder,s,c)
                opening.return_value.open.assert_called_once()
            self.assertEqual((c['status'],c['excluded_code']),('pending','network'))
            with patch('lib.patents.build_opener') as opening, patch('lib.patents.time.sleep'):
                opening.return_value.open.side_effect=lambda req,timeout: Response(page(doc['doc_id']),req.full_url)
                work.receive(folder,s,c)
                opening.return_value.open.assert_called_once()
            self.assertEqual(c['status'],'accepted')
            self.assertEqual(work.docs_for(folder,s)[doc['doc_id']],patents.read_document(folder/'docs',doc['doc_id']))
