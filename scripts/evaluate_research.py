#!/usr/bin/env python3
"""Run the versioned research corpus, preserving raw outputs for human evaluation.

No model-generated score is treated as a human label. Use an empty dedicated
root; development and final holdout runs deliberately have separate roots.
"""
import argparse
import json
from pathlib import Path
import time
from pitr.application.service import Workstation
from pitr.adapters.tool_http import ToolServer
from pitr.research.queue import ResearchQueue
from pitr.domain.contracts import CreateCase,Scope,StartRun
from pitr.domain.common import uid


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--split',choices=['development','holdout'],default='development')
    parser.add_argument('--provider',choices=['codex','claude'],required=True)
    parser.add_argument('--case',action='append')
    parser.add_argument('--depth',choices=['interactive','standard','deep'],default='standard')
    args=parser.parse_args()
    corpus=json.loads(Path('benchmarks/research-cases.json').read_text())
    cases=[c for c in corpus['cases'] if c['holdout']==(args.split=='holdout') and (not args.case or c['id'] in args.case)]
    if not cases:raise ValueError('No matching cases')
    root=Path(args.root)
    if (root/'research.sqlite').exists():raise ValueError('Benchmark runs require a new data directory')
    station=Workstation(root)
    station.register_subject('A',identity='EXAMPLE-A',name='Example A Ltd',aliases=['Company A','甲公司'])
    station.register_subject('B',identity='EXAMPLE-B',name='Example B Ltd',aliases=['Company B','乙公司'])
    station.register_subject('PDD',identity='PDD',name='PDD Holdings',official_domains=['investor.pddholdings.com'])
    runs=[]
    for case in cases:
        refs=[];subjects=['EXAMPLE-A','EXAMPLE-B']
        for i,material in enumerate(case['materials']):
            raw=Path(material['file']).read_bytes() if material.get('file') else material['text'].encode()
            source=station.import_source(raw,material.get('media_type','text/plain'),title=material['title'],subjects=subjects,operation_id=case['id']+'-source-'+str(i))
            refs.append(source.ref)
        if case.get('originals'):
            subjects=['PDD']
            for original in case['originals']:
                source=station.fetch_source(original['url'],title=original['title'],subjects=subjects,operation_id=uid('official'))
                if source.digest!=original['sha256']:raise ValueError('Official fixture changed; verify the original before evaluation')
                refs.append(source.ref)
        # Historical cases provide explicitly synthetic timelines for reasoning
        # evaluation; actual scope enforcement is covered by the engineering suite.
        request=CreateCase(operation_id=case['id'],question=case['question'],scope=Scope(subjects=subjects,allow_public_search=False),
            sources=refs,agent_provider=args.provider,depth=args.depth,report_type='memo')
        result=station.create_case(request)
        run=station.start_run(result['id'],StartRun(operation_id=case['id']+'-run',expected_revision=1))
        runs.append({'benchmark_case':case['id'],'category':case['category'],'run':run['id']})
    server=ToolServer(station);queue=ResearchQueue(station)
    try:
        while any(station.get_run(r['run']).status in ('queued','running') for r in runs):
            status=[{**r,'status':station.get_run(r['run']).status} for r in runs]
            (root/'evaluation-progress.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
            time.sleep(5)
        for record in runs:
            run=station.get_run(record['run'])
            record.update(status=run.status,seconds=run.active_seconds,tool_calls=run.tool_calls,
                report=run.report.model_dump() if run.report else None,human_evaluation='not_performed')
            if run.report:
                view=station.reports.view(run.report)
                record.update(delivery=view.delivery,checks=[{'name':c.name,'status':c.status} for c in view.checks])
        result={'corpus_version':corpus['version'],'split':args.split,'provider':args.provider,'cases':runs,'human_evaluation':'not_performed'}
        (root/'evaluation-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps(result,ensure_ascii=False))
    finally:queue.close();server.close()


if __name__=='__main__':main()
