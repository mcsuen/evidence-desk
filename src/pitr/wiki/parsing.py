"""Bound PDF parsing in a disposable process; originals already live in CAS."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_original(raw, media, url, company, title, timeout):
    from pitr.desk.sources import parse_document
    if not (raw.startswith(b'%PDF') or 'pdf' in media):
        return parse_document(raw, media, url, company, title)
    from pitr.desk.contracts import Document
    from pitr.security import child_env
    with tempfile.TemporaryDirectory(prefix='pitr-wiki-parse-') as directory:
        path=Path(directory)/'original.pdf'
        path.write_bytes(raw)
        result=subprocess.run([sys.executable, '-m', 'pitr.wiki.parsing'],
            input=json.dumps({'path':str(path),'media':media,'url':url,'company':company,'title':title}),
            text=True,capture_output=True,timeout=max(1,timeout),env=child_env())
        if result.returncode:
            raise ValueError('PDF 转换失败：'+result.stderr[-400:])
        return Document.model_validate_json(result.stdout)


if __name__=='__main__':
    from pitr.desk.sources import parse_document
    body=json.load(sys.stdin)
    print(parse_document(Path(body['path']).read_bytes(),body['media'],body['url'],body['company'],body['title']).model_dump_json())
