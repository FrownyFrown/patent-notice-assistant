import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.rank import top


class RankTest(unittest.TestCase):
    def test_rank(self):
        doc = {'paragraphs':[{'id':'p1','text':'weight sensor'}, {'id':'p2','text':'weight sensor'}, {'id':'p3','text':'unrelated'}]}
        c = [{'id':'1-A','text':'무게 감지부','synonyms':{'en':['weight sensor']}}]
        self.assertEqual(top(c, doc), {'1-A':['p1','p2']})
        self.assertEqual(top(c, doc, n=1), {'1-A':['p1']})
        self.assertEqual(top(c, {'paragraphs':[]}), {'1-A':[]})
        doc = {'paragraphs':[{'id':'p1','text':'감지부는 작동한다'}, {'id':'p2','text':'容器開閉'}]}
        self.assertEqual(top([{'id':'a','text':'감지부'}],doc)['a'], ['p1'])
        self.assertEqual(top([{'id':'a','text':'容器'}],doc)['a'], ['p2'])
