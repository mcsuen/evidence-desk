import time
import pytest
from pitr.application.service import Workstation
from pitr.application.tools import ToolService
from pitr.domain.contracts import CreateCase, StartRun, Scope
from pitr.research.queue import ResearchQueue


@pytest.fixture
def station(tmp_path):
    result=Workstation(tmp_path/'research',runtime=False)
    result.register_subject('subject-pdd',identity='PDD',name='拼多多',aliases=['PDD Holdings'],official_domains=['investor.pddholdings.com'])
    return result


@pytest.fixture
def running(station):
    raw='PDD Holdings 2025Q2 GAAP RMB millions\nRevenue 100.000\nOperating income (20.000)\n\nPDD Holdings 2024Q2 GAAP RMB millions\nRevenue 80.000'
    source=station.import_source(raw.encode(),'text/plain',subjects=['PDD'])
    case=station.create_case(CreateCase(operation_id='case',question='收入与盈利变化',scope=Scope(subjects=['PDD']),sources=[source.ref]))
    result=station.start_run(case['id'],StartRun(operation_id='start',expected_revision=1),binding={'provider':'local'})
    queue=ResearchQueue(station,start=False)
    run=queue.claim('local')
    tools=ToolService(station);token=tools.issue(run.id,run.generation)
    counter=0
    def call(tool_name,**arguments):
        nonlocal counter
        counter+=1
        return tools.call(token,{'operation_id':f'test-{counter}','name':tool_name,'arguments':arguments})
    return station,source,run,queue,tools,token,call


def ref(value):
    return {'id':value['id'],'revision':value['revision']}


def report_fixture(running,*,risk='fact'):
    station,source,run,queue,tools,token,call=running
    evidence=call('evidence.quote',source=source.ref.model_dump(),block_id=source.blocks[0].id,quote=source.blocks[0].text)
    e=ref(evidence)
    value=call('value.bind',evidence=e,literal='100.000',metric='revenue',subject='PDD',period='2025Q2',
        original_unit='RMB_mn',unit='RMB_mn',unit_evidence=e,period_evidence=e,basis_evidence=e,
        basis='GAAP',frequency='quarter',currency='CNY')
    claim=call('assertion.propose',title='收入规模',statement='收入为披露的季度收入',kind=risk,subjects=['PDD'],support=[e],values=[ref(value)])
    report=call('report.save',title='拼多多季度研究',summary=[{'id':'summary','inlines':[{'type':'text','text':'本季收入为'},
        {'type':'value','ref':ref(value)},{'type':'citation','ref':e}],'assertions':[ref(claim)]}],
        sections=[{'id':'financials','title':'经营变化','blocks':[{'type':'table','id':'data','title':'关键指标','columns':['指标','本季'],
            'rows':[[[{'type':'text','text':'收入'}],[{'type':'value','ref':ref(value)}]]]},
            {'type':'chart','id':'chart','title':'收入变化','kind':'column','categories':['本季','未披露'],
             'series':[{'name':'收入','values':[ref(value),None]}],'unit':'RMB_mn'}]}],assertions=[ref(claim)])
    return station.reports.view(report['report']),value,evidence,claim
