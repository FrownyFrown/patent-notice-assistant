import ast
import json
import os
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]


class PackagingTest(unittest.TestCase):
    def test_required_files(self):
        for name in ['AGENTS.md','.agents/skills/patent-notice/SKILL.md','setup.bat','setup.command','.gitignore','.gitattributes','input/.gitkeep']:
            self.assertTrue((ROOT/name).is_file(),name)
        self.assertLessEqual(len((ROOT/'AGENTS.md').read_text().splitlines()),60)

    def test_text_policy(self):
        paths=list((ROOT/'scripts').rglob('*.py'))+list((ROOT/'tests').glob('test_*.py'))+list((ROOT/'schemas').glob('*.json'))+list((ROOT/'references').glob('*.md'))+list((ROOT/'tests/example').glob('*.*'))+[ROOT/'AGENTS.md',ROOT/'setup.bat',ROOT/'setup.command']
        skill=ROOT/'.agents/skills/patent-notice/SKILL.md'
        if skill.exists(): paths.append(skill)
        banned=[chr(0x00B7),chr(0x2013),chr(0x2014),'\uac00\uc871','\uc544\ubc84\uc9c0','\uc2ec\uc0ac\uad00','\x2fUsers\x2f','message'+'_id']
        for p in paths:
            if not p.is_file(): continue
            text=p.read_text(encoding='utf-8')
            for token in banned: self.assertNotIn(token,text,str(p.relative_to(ROOT)))
            self.assertFalse(re.search(r'\*\*[^*]+\*\*',text),str(p))
            self.assertFalse(any(0x1F000<=ord(c)<=0x1FAFF or 0x2600<=ord(c)<=0x27BF for c in text),str(p))

    def test_start_files(self):
        bat=(ROOT/'setup.bat').read_bytes()
        self.assertIn(b'\r\n',bat)
        self.assertNotIn(b'\n',bat.replace(b'\r\n',b''))
        self.assertNotIn(b'\r',(ROOT/'setup.command').read_bytes())
        self.assertTrue(os.access(ROOT/'setup.command',os.X_OK))

    def test_schema_rules(self):
        def walk(node):
            if isinstance(node,dict):
                if node.get('type')=='object':
                    self.assertIs(node.get('additionalProperties'),False)
                    self.assertEqual(set(node['properties']),set(node['required']))
                for value in node.values(): walk(value)
            elif isinstance(node,list):
                for value in node: walk(value)
        for p in (ROOT/'schemas').glob('*.json'): walk(json.loads(p.read_text()))

    def test_no_child_codex(self):
        for p in (ROOT/'scripts').rglob('*.py'):
            tree=ast.parse(p.read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.Call):
                    self.assertFalse(any(k.arg=='shell' and isinstance(k.value,ast.Constant) and k.value.value is True for k in node.keywords),str(p))
            self.assertNotRegex(p.read_text(),r'subprocess\.[a-z_]+\([^\n]*[\x22\x27]codex')

    def test_no_kana_in_code(self):
        paths = list((ROOT/'scripts').rglob('*.py')) + list((ROOT/'tests').glob('test_*.py'))
        for p in paths:
            if p.name == 'test_rank.py':
                continue
            self.assertNotRegex(p.read_text(), r'[\u3040-\u30ff]', str(p))

    def test_only_canonical_skill(self):
        self.assertNotIn('references/' + 'patent-notice-skill.md', (ROOT/'AGENTS.md').read_text())
