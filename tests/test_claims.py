import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.claims import parse


class ClaimsTest(unittest.TestCase):
    def test_preserve(self):
        text = '청구범위\n청구항 1 \n  가상 감지\n부;  \n공개특허 10-2026-0000000\n- 3 -\n제어부. \n청구항 2\n제1항에 있어서,\n추가부.\n발명의 설명\n청구항 3\n무시'
        result = parse(text)
        a, b = result['claims']
        self.assertEqual(a['text'], '가상 감지\n부;  \n제어부.')
        self.assertTrue(a['warnings'])
        self.assertEqual(text[a['start']:a['start']+2], '가상')
        self.assertEqual(b['preamble'], '제1항에 있어서,')
        self.assertEqual(b['body'], '추가부.')

    def test_references(self):
        forms = [('제1항에 있어서,', [1]), ('제1항 내지 제3항 중 어느 한 항에 있어서,', [1,2,3]), ('제1항 또는 제2항', [1,2]), ('제 1 항에 따른', [1]), ('제1항, 제3항 및 제5항 중', [1,3,5]), ('청구항 1에 있어서,', [1])]
        for form, expected in forms:
            with self.subTest(form=form):
                c = parse('【청구범위】\n【청구항 6】\n'+form+'\n가상 장치.')['claims'][0]
                self.assertEqual(c['depends_on'], expected)
        c = parse('[청구범위]\n[청구항 2]\n제1항의 장치를 제어하는 방법')['claims'][0]
        self.assertEqual(c['preamble'], '')
        self.assertIn('형식만 종속일 수 있음', c['warnings'])

    def test_dates_and_warnings(self):
        r = parse('(22) 출원일자 2025년04월02일\n(43) 공개일자 2026.10.12\n(30) 우선권주장\n1020240000000 2024-03-05 KR\n1020230000000 2023년03월05일 KR\n(54) 발명의 명칭 가상 장치\n(57) 요 약\n청구범위\n(전체 청구항 수 : 총 15 항)\n청구항 1\n제3항에 있어서, 가상부\n청구항 3\n제1항에 있어서, 추가부\n청구항 3\n삭제\n요 약 서')
        self.assertEqual(len(r['date_candidates']), 4)
        self.assertEqual(r['title'], '가상 장치')
        for word in ['누락', '중복', '순환', '불일치', '뒤 항']:
            self.assertIn(word, ' '.join(r['warnings']))
        self.assertTrue(r['claims'][-1]['deleted'])
        self.assertFalse(parse('발명의 설명\n청구항 1에 있어서 내용')['claims'])

    def test_offsets_and_no_false_headers(self):
        text = '【청구범위】\n[청구항 1]\n첫 문장;  \n청구항 1에 있어서 기재된 내용을 기록한다.\n청구항 1의 발명은 가상 내용이다.\n[청구항 2]\n삭제\n기 술 분 야\n[청구항 3]\n무시'
        claims = parse(text)['claims']
        self.assertEqual(len(claims), 2)
        for c in claims:
            self.assertEqual(text[c['start']:c['end']], c['text'])
        text = '청구범위\n청구항 1\n가상 장치;\n공개특허 10-2026-0000000  \n  들여쓴 가상 문장.\n발명의 설명'
        self.assertIn('\n  들여쓴', parse(text)['claims'][0]['text'])

    def test_adjacent_bracket_headings(self):
        text = '【청구범위】【청구항 1】가상 본문;\n추가부.\n【청구항 2】제1항에 따른 가상 장치\n【발명의 설명】\n무시'
        result = parse(text)['claims']
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['text'], '가상 본문;\n추가부.')
        self.assertEqual(result[1]['depends_on'], [1])

    def test_real_layout(self):
        text = ('(21) 출원번호 10-2025-0000000\n(22) 출원일자 2025년04월02일\n     심사청구일자 2025년04월03일\n청구범위\n청구항 1\n가상 장치로서,\n'
                '도면에 나타낸 부와\n요약 정보를 내는 부를 포함하는 장치.\n청구항 2\n제1항의 가상 장치에 있어서,\n추가부.\n'
                '청구항 3\n제1항 또는 제2항 중 어느 한 항에 기재된 가상 장치에 있어서,\n추가부 2.\n발명의 설명\n기 술 분 야\n[0001] 글')
        r = parse(text)
        self.assertEqual([d['date'] for d in r['date_candidates']], ['2025-04-02'])
        self.assertEqual([c['number'] for c in r['claims']], [1, 2, 3])
        self.assertIn('요약 정보', r['claims'][0]['text'])
        self.assertEqual([c['body'] for c in r['claims'][1:]], ['추가부.', '추가부 2.'])
        self.assertEqual(r['claims'][2]['depends_on'], [1, 2])
