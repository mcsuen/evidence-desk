"""Current Pydantic contracts are the sole source for schemas and frontend types."""
import argparse
import json
import re
from pathlib import Path
from pitr.config import settings
from pitr.desk.contracts import DeskView
from pitr.desk.company_model import ModelView
from pitr.desk.research.contracts import ResearchRequest, ResearchOutcome, ResearchInterpretation, ResearchSubject, ResearchMessage
from pitr.desk.research.trace.contracts import TraceView
from pitr.wiki import contracts as wiki_contracts

EXPORTS={
    'desk_view.v1.json':DeskView,
    'operating_model.v1.json':ModelView,
    'trace_view.v1.json':TraceView,
    'research_request.v3.json':ResearchRequest,
    'research_outcome.v3.json':ResearchOutcome,
    'research_interpretation.v3.json':ResearchInterpretation,
    'research_subject.v3.json':ResearchSubject,
    'research_message.v3.json':ResearchMessage,
}
for name in ('CaptureEnvelope','KnowledgeRevision','WikiPageRevision','PolicyRevision','KnowledgeEvent',
             'DecisionRecord','KnowledgeIssue','InspectionRun','ProposalInput','QueryInput','AnswerInput',
             'WikiJobRequest','WikiJobResult','WikiUpdateSchedule','CompanyRegistration'):
    EXPORTS['wiki_'+re.sub(r'(?<!^)(?=[A-Z])','_',name).lower()+'.v1.json']=getattr(wiki_contracts,name)

def build_schema(name):
    return {**EXPORTS[name].model_json_schema(),'$schema':'https://json-schema.org/draft/2020-12/schema','$id':f'pitr/{name}'}

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
