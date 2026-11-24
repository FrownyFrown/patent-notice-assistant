import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import state


class StateTest(unittest.TestCase):
    def test_shape(self):
        sample = json.loads((ROOT / 'tests/fixtures/state-sample.json').read_text())
        s = state.new_case('case-test')
        self.assertEqual(set(s), set(sample))
        for key in ('input', 'settings', 'next', 'usage', 'verification'):
            self.assertEqual(set(s[key]), set(sample[key]))
        for key in ('steps', 'review_items'):
            self.assertEqual(set(s[key][0]), set(sample[key][0]))

    def test_atomic_revision_and_invalidation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tests/example') as td:
            p = Path(td) / 'state.json'
            s = state.new_case('case-test')
            state.save(p, s)
            state.save(p, s)
            self.assertEqual(state.load(p)['revision'], 2)
            s['artifacts'] = [dict(kind='html', path='out/notice.html', created_at='', stale=False)]
            state.invalidate(s, 4)
            self.assertEqual(s['steps'][4]['status'], 'stale')
            self.assertTrue(s['artifacts'][0]['stale'])
            self.assertEqual(list(Path(td).glob('.write-*')), [])

    def test_path_rejected(self):
        with self.assertRaises(ValueError):
            state.new_case('../outside')
