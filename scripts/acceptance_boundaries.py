"""Real installed-host cancellation, service restart and partial-delivery acceptance."""
import argparse
import json
from pathlib import Path
import time
import httpx

from pitr.application.service import Workstation
from pitr.adapters.tool_http import ToolServer
from pitr.research.queue import ResearchQueue
from pitr.domain.contracts import CreateCase,Scope,StartRun,ContinueRun
from pitr.domain.common import uid


def wait_until(predicate,seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.5)
    raise TimeoutError('Acceptance condition was not observed within its limit')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
    station=Workstation(args.root);station.register_subject('subject',identity='TEST',name='Example A Ltd')
    source=station.import_source(b'Example A Ltd operates retail shops. The company has not disclosed customer concentration.','text/plain',subjects=['TEST'])
    ids=[]
    for provider in ('codex','claude'):
        case=station.create_case(CreateCase(operation_id='case-'+provider,question='只根据上传原件，给出一份很短的公司经营事实备忘。先读取context，再保存checkpoint说明进度，然后引用原句并保存报告。不要补充新来源或编造数值。',
            scope=Scope(subjects=['TEST'],allow_public_search=False),sources=[source.ref],agent_provider=provider,depth='interactive'))
        run=station.start_run(case['id'],StartRun(operation_id='start-'+provider,expected_revision=1));ids.append(run['id'])
    server=ToolServer(station);queue=ResearchQueue(station)
    result=[]
    try:
        # Cancel immediately after actual controlled tool traffic from each native host.
        for rid in ids:
            wait_until(lambda:station.get_run(rid).tool_calls>0,150)
            station.cancel(rid,'cancel-'+rid)
        wait_until(lambda:not station.agents.processes,30)
        with station.store.connect() as db:
            assert db.execute('SELECT count(*) FROM grants WHERE active=1').fetchone()[0]==0
        old_url=server.url;server.close()
        try:httpx.post(old_url+'/call',json={'name':'context'},timeout=2,trust_env=False)
        except httpx.TransportError:pass
        else:raise AssertionError('Stopped tool service still reachable')
        server=ToolServer(station)
        for rid in ids:
            run=station.get_run(rid);assert run.status=='cancelled'
            with station.store.connect(write=True) as db:
                # Intentionally tiny remaining tool allowance exercises the real wrap-up path.
                run.budget.tool_calls=run.tool_calls;station.save_run(db,run)
            station.continue_run(rid,ContinueRun(operation_id='partial-'+rid,expected_generation=run.generation,additional_calls=1,additional_seconds=120))
        wait_until(lambda:all(station.get_run(r).status not in ('queued','running') for r in ids),240)
        for rid in ids:
            run=station.get_run(rid)
            if run.status!='budget_exhausted':raise AssertionError((rid,run.status,run.error))
            assert run.report and station.reports.view(run.report).delivery=='partial'
            result.append({'provider':run.lane,'run':run.id,'cancelled_after_native_tools':True,'service_restarted':True,
                           'partial_report':run.report.model_dump(),'partial_generation':run.generation})
            station.continue_run(rid,ContinueRun(operation_id='complete-'+rid,expected_generation=run.generation,additional_calls=40,additional_seconds=300))
        wait_until(lambda:all(station.get_run(r).status not in ('queued','running') for r in ids),420)
        for item in result:
            run=station.get_run(item['run']);view=station.reports.view(run.report)
            item.update(final_status=run.status,report=run.report.model_dump(),checks=[{'name':c.name,'status':c.status} for c in view.checks],generation=run.generation)
            assert run.status=='completed' and all(c.status in ('passed','not_applicable') for c in view.checks),item
        Path(args.root,'acceptance-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:queue.close();server.close()


if __name__=='__main__':main()
