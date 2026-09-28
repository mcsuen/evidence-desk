"""Pydantic request and response schemas; no UI-specific required-field rewriting."""
import argparse
import json
import re
from pathlib import Path
from pitr.config import settings
from pitr.domain.common import Command, Contract
from pitr.domain import contracts, views
from pitr.adapters import api
from pitr.lab.news import contracts as news_contracts
from pitr.application import evaluation

EXPORTS = {}
for module, prefix in ((contracts,''),(views,''),(api,''),(news_contracts,'lab_'),(evaluation,'')):
    for name, model in vars(module).items():
        if isinstance(model,type) and issubclass(model,Contract) and model.__module__ == module.__name__:
            filename = prefix+re.sub(r'(?<!^)(?=[A-Z])','_',name).lower()+'.v1.json'
            EXPORTS[filename] = model

def build_schema(name):
    model=EXPORTS[name]
    mode='validation' if issubclass(model,Command) else 'serialization'
    return {**model.model_json_schema(mode=mode),'$schema':'https://json-schema.org/draft/2020-12/schema','$id':f'pitr/{name}'}

def export_schemas(out_dir=None,*,check=False):
    out_dir=Path(out_dir or settings.schemas_dir)
    expected={name:json.dumps(build_schema(name),ensure_ascii=False,indent=2)+'\n' for name in EXPORTS}
    if check:
        actual={p.name:p.read_text() for p in out_dir.glob('*.json')}
        if actual!=expected:raise ValueError('Schema 与当前 Python 契约不一致，请重新导出')
    else:
        out_dir.mkdir(parents=True,exist_ok=True)
        for path in out_dir.glob('*.json'):
            if path.name not in expected:path.unlink()
        for name,body in expected.items():(out_dir/name).write_text(body)
    return [out_dir/name for name in expected]

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for path in export_schemas(check=args.check):print(path)
