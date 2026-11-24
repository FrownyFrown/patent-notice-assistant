import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.verify import squash, contains, check_quote


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.doc = {'numbered': True, 'machine_translated': True, 'paragraphs': [
            {'num':'0001', 'text':'container opens', 'source_text':'가상 용기가 열린다'},
            {'num':'0002', 'text':'sensor measures weight', 'source_text':'감지부가 무게를 잰다'},
            {'num':'0003', 'text':'alarm sounds', 'source_text':''}]}

    def test_checks(self):
        self.assertEqual(squash('Ａ \n\x00B'), 'AB')
        self.assertTrue(contains('용기가 열린다', '가상 용기가\n열린다'))
        for quote, nums, result in [('container opens',['0001'],'pass'), ('가상 용기가 열린다',['0001'],'pass'), ('container opens',['9999'],'moved'), ('container opens',['0001','9999'],'moved'), ('container opens',[],'moved'), ('조작한 인용문입니다',['0001'],'fail'), ('container...opens',['0001'],'fail'), ('short',['0001'],'fail'), ('',[],'none'), ('opens sensor measures',['0001','0002'],'pass'), ('opens alarm sounds',[],'fail')]:
            with self.subTest(quote=quote, nums=nums):
                self.assertEqual(check_quote(self.doc, quote, nums)['result'], result)
        self.assertFalse(check_quote(self.doc, '가상 용기가 열린다', ['0001'])['passages'][0]['translated'])
        self.assertTrue(check_quote(self.doc, 'container opens', ['0001'])['passages'][0]['translated'])
        self.doc['paragraphs'][0]['num'] = ''
        self.assertEqual(check_quote(self.doc, 'container opens', [])['paragraphs'], [])
