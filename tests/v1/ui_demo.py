"""Explicit offline UI fixtures. Only used by the isolated browser server."""
from pitr.application.trace import span
from pitr.domain.common import uid
from pitr.domain.contracts import CreateCase, StartRun, Scope, Ref, Decide
from pitr.application.tools import ToolService
from pitr.research.queue import ResearchQueue
from conftest import report_fixture


def seed_ui_demo(station):
    raw=b'Offline UI fixture. PDD and BABA operate marketplaces. This is not an investment conclusion. PDD Holdings 2025Q2 GAAP RMB millions. Revenue 100.000'
    source=station.import_source(raw,'text/plain',subjects=['PDD','BABA'],title='离线演示原件：平台业务与关系')
    case=station.create_case(CreateCase(operation_id='demo-case',question='离线演示：平台业务关系与经营变化',scope=Scope(subjects=['PDD','BABA']),sources=[source.ref]))
    station.start_run(case['id'],StartRun(operation_id='demo-start',expected_revision=1),binding={'provider':'local'})
    queue=ResearchQueue(station,start=False);run=queue.claim('local');tools=ToolService(station)
    with span(station.store,run,'研究与报告','agent',fixture='明确标注的离线界面演示') as (identity,_):
        token=tools.issue(run.id,run.generation,parent_span=identity)
        def call(name,**args):return tools.call(token,{'operation_id':uid('demo'),'name':name,'arguments':args})
        try:call('source.read',ref=source.ref.model_dump(),block_id='offline-missing-block')
        except KeyError:pass
        view,value,evidence,claim=report_fixture((station,source,run,queue,tools,token,call))
        relation=call('assertion.propose',title='离线演示：电商平台同业关系',statement='原件描述两家主体的平台业务，此处仅用于界面验收。',kind='relationship',subjects=['PDD','BABA'],support=[{'id':evidence['id'],'revision':1}],alternative='同业关系本身不证明直接交易、订单或业务增长。',next_check='取得各主体准确披露后继续核查。',relation={'from':'PDD','to':'BABA','type':'同业','maturity':'in_operation','semantic_basis':'原件同时描述两家主体的平台业务；不推断供货关系。'})
        model=call('model.propose',title='离线演示：经营观察模型',subjects=['PDD'],assumptions=[{'id':value['id'],'revision':1}],outputs=[{'id':value['id'],'revision':1}],rationale='固定已取得的输入值，演示模型依赖与版本展示；不构成预测。')
        document=view.document.model_dump(mode='json')
        report=call('report.save',title='离线演示：平台研究报告',summary=document['summary'],sections=document['sections'],assertions=[{'id':claim['id'],'revision':1},{'id':relation['id'],'revision':1}],models=[{'id':model['id'],'revision':1}],change_reason='加入关系与模型，供界面对照验收')
    ref=Ref.model_validate(report['report'])
    # Independent fixture runtime reads the real frozen report and returns labelled fixture data.
    queue.review(station.get_run(run.id),ref,lambda:queue.fence(run))
    queue.finish(run,'completed')
    for group in station.reports.groups():
        if group['report']==report['report'] and group['status']=='pending':
            station.reports.decide(group['id'],Decide(operation_id=uid('demo-adopt'),expected_revision=group['revision'],action='adopt',reason='离线界面验收专用：模拟人工决定，不是实际研究采纳'))
    return case['id']
