#!/usr/bin/env python3
"""Exercise the default research path with both installed, authenticated hosts."""
import argparse
import json
from pathlib import Path
import time

from pitr.application.service import Workstation
from pitr.adapters.tool_http import ToolServer
from pitr.research.queue import ResearchQueue
from pitr.artifacts.queue import ExportQueue
from pitr.domain.contracts import CreateCase, StartRun, Scope, ExportRequest, ContinueRun


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--provider',action='append',choices=['codex','claude'])
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();root=Path(args.root)
    station=Workstation(root);station.agents.refresh()
    station.register_subject('pdd',identity='PDD',name='PDD Holdings',aliases=['拼多多'],official_domains=['investor.pddholdings.com'])
    sources=[]
    for item in json.loads(Path('docs/demo/sources.json').read_text()):
        source=station.fetch_source(item['url'],subjects=['PDD'],title=item['title'],operation_id='pdd-'+item['period'])
        if source.digest!=item['sha256']:raise ValueError('Official disclosure bytes changed; inspect originals before running')
        sources.append(source.ref)
    question=Path('docs/demo/question.txt').read_text()
    ids=[]
    for provider in args.provider or ['codex','claude']:
        case=station.create_case(CreateCase(operation_id='case-'+provider,question=question,
            scope=Scope(subjects=['PDD'],period='2025Q2 / 2024Q2',allow_public_search=False),sources=sources,
            report_type='earnings',agent_provider=provider,depth='standard'))
        run=station.start_run(case['id'],StartRun(operation_id='start-'+provider,expected_revision=1))
        if args.resume:
            current=station.get_run(run['id'])
            if current.status in ('waiting_user','failed','cancelled','budget_exhausted') or (current.status=='completed' and station.reports.view(current.report).delivery!='ready'):
                station.continue_run(current.id,ContinueRun(operation_id='resume-'+current.id+'-'+str(current.generation),expected_generation=current.generation,additional_calls=180,additional_seconds=900,
                    instruction='补齐尚未登记的核心判断对象，并修正独立复核指出的措辞、引用定位和范围说明。保留原件确实不支持的研究缺口；不要把工具与执行状态写入研究正文。'))
        ids.append(run['id'])
    server=ToolServer(station);queue=ResearchQueue(station);exports=ExportQueue(station)
    print('Runs: '+json.dumps(ids),flush=True)
    previous=None;started=time.monotonic()
    try:
        while time.monotonic()-started<3800:
            runs=[station.get_run(rid) for rid in ids]
            status=[{'provider':r.lane,'id':r.id,'status':r.status,'stage':r.stage,'tools':r.tool_calls,'seconds':round(r.active_seconds),'report':r.report.model_dump() if r.report else None,'error':r.error} for r in runs]
            if status!=previous:
                (root/'acceptance-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
                print(json.dumps(status,ensure_ascii=False),flush=True);previous=status
            if all(r.status not in ('queued','running') for r in runs):break
            time.sleep(15)
        for run in runs:
            if run.report:
                for paper in ('Letter','A4'):
                    station.reports.export(ExportRequest(operation_id='export-v2-'+run.id+'-'+paper+'-'+str(run.report.revision),report=run.report,paper=paper))
        deadline=time.monotonic()+400
        while time.monotonic()<deadline:
            with station.store.connect() as db:jobs=[json.loads(r[0]) for r in db.execute('SELECT body FROM exports')]
            if not any(j['status'] in ('queued','running') for j in jobs):break
            time.sleep(2)
        result={'runs':status,'exports':jobs,'human_evaluation':'not_performed'}
        (root/'acceptance-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        queue.close();exports.close();server.close()


if __name__=='__main__':main()
