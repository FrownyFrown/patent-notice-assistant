"""BM25 단락 순위. 순위는 판단 결과가 아니다."""
import math
import re
import unicodedata
from collections import Counter


def _tokens(text):
    words = re.findall(r'[a-z0-9]+|[가-힣]+|[\u3040-\u30ff\u3400-\u9fff]+', unicodedata.normalize('NFKC', text).lower())
    result = []
    for word in words:
        if word.isascii() or len(word) == 1:
            result.append(word)
        else:
            result.extend(word[i:i+2] for i in range(len(word)-1))
    return result


def top(components, doc, n=8, context=''):
    if not isinstance(n, int) or n < 0:
        raise ValueError('단락 수는 0 이상의 정수여야 합니다.')
    paragraphs = doc.get('paragraphs', [])
    counts = [Counter(_tokens(p.get('text', '')+' '+p.get('source_text', ''))) for p in paragraphs]
    sizes = [sum(c.values()) for c in counts]
    avg = sum(sizes) / len(sizes) if sum(sizes) else 1
    df = Counter(t for c in counts for t in c)
    result = {}
    for component in components:
        synonyms = component.get('synonyms', {})
        terms = set(_tokens(' '.join([component.get('text', ''), context] + [s for lang in ('ko','en','zh') for s in synonyms.get(lang, [])])))
        scores = []
        for i, count in enumerate(counts):
            score = 0.0
            for term in terms:
                frequency = count[term]
                if frequency:
                    idf = math.log(1+(len(counts)-df[term]+0.5)/(df[term]+0.5))
                    score += idf * frequency * 2.2 / (frequency+1.2*(0.25+0.75*sizes[i]/avg))
            if score > 0:
                scores.append((i, score))
        scores.sort(key=lambda item: (-item[1], item[0]))
        result[component['id']] = [paragraphs[i]['id'] for i, _ in scores[:n]]
    return result
