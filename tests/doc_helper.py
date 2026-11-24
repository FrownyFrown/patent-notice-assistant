"""시험 공보와 받은 바이트 목록을 함께 쓴다."""
import hashlib
import json
from pathlib import Path


def write_doc(folder, doc):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, ensure_ascii=False).encode('utf-8')
    (folder / (doc['doc_id'] + '.json')).write_bytes(data)
    path = folder / '.index.json'
    index = json.loads(path.read_bytes()) if path.exists() else {}
    index[doc['doc_id']] = hashlib.sha256(data).hexdigest()
    path.write_text(json.dumps(index), encoding='utf-8')
