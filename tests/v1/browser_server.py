"""Isolated browser fixture. Only the Agent result is deterministic; commands are real."""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace

import uvicorn
from pitr.adapters.api import create_app
from pitr.application.service import Workstation
from pitr.application.tools import ToolService
from pitr.domain.common import uid
from pitr.domain.contracts import Scope,CreateCase,StartRun
from pitr.research.queue import ResearchQueue
from conftest import report_fixture

root=Path(tempfile.mkdtemp(prefix='pitr-v1-browser-'))
station=Workstation(root,runtime=False)
station.register_subject('pdd',identity='PDD',name='拼多多',aliases=['PDD Holdings','Temu'])
station.register_subject('baba',identity='BABA',name='阿里巴巴')
source=station.import_source(b'PDD Holdings 2025Q2 GAAP RMB millions\nRevenue 100.000\nOperating income (20.000)','text/plain',subjects=['PDD'],title='离线界面测试原件')
case=station.create_case(CreateCase(operation_id='case',question='离线界面验收：季度研究',scope=Scope(subjects=['PDD']),sources=[source.ref]))
station.start_run(case['id'],StartRun(operation_id='start',expected_revision=1),binding={'provider':'local'})
queue=ResearchQueue(station,start=False);run=queue.claim('local');tools=ToolService(station);token=tools.issue(run.id,run.generation)
def call(name,**arguments):return tools.call(token,{'operation_id':uid('fixture'),'name':name,'arguments':arguments})
report_fixture((station,source,run,queue,tools,token,call))
queue.finish(run,'completed')


class FixtureRuntime:
    def status(self):return {'agents':[{'id':'codex','name':'离线界面夹具','status':'logged_in','version':'fixture'}]}
    def refresh(self,background=False):return self.status()
    def selection(self,*args,**kwargs):return {'provider':'local','model':'offline-fixture'}
    def shutdown(self):pass
    def cancel(self,*args):pass
    def execute(self,task,prompt,schema,**kw):
        kw['fence']()
        if kw['role']=='independent-review':
            context=json.loads(prompt)
            return SimpleNamespace(data={'verdict':'pass','findings':[],'checked_assertions':context['required_assertions'],'evidence':[],'summary':'仅用于离线界面验收的固定结果'})
        for _ in range(15):time.sleep(.1);kw['fence']()
        grant=json.loads(Path(kw['authority']).read_text())
        current=station.get_run(task['id'])
        question=station.get_case(current.case_id).input.question
        if question=='来源更正后继续研究':
            def invoke(name,**arguments):
                return tools.call(grant['token'],{'operation_id':uid('browser-correction'),'name':name,'arguments':arguments})
            snapshot=station.store.get(current.snapshot,'snapshot')
            original=station.store.get(snapshot.sources[0],'source')
            anchor=invoke('evidence.quote',source=original.ref.model_dump(),block_id=original.blocks[0].id,quote=original.blocks[0].text)
            ref=lambda obj:{'id':obj['id'],'revision':obj['revision']}
            value=invoke('value.bind',evidence=ref(anchor),literal='120.000',metric='revenue',subject='PDD',period='2025Q2',original_unit='RMB_mn',unit='RMB_mn',unit_evidence=ref(anchor),period_evidence=ref(anchor),basis_evidence=ref(anchor),basis='GAAP',frequency='quarter',currency='CNY')
            old=next(a for a in station.store.list('assertion') if a.title=='收入规模')
            claim=invoke('assertion.propose',id=old.id,expected_revision=old.revision,title='收入规模',statement='更正后原件对应的季度收入',kind='fact',subjects=['PDD'],support=[ref(anchor)],values=[ref(value)])
            result=invoke('report.save',title='来源更正后的报告',summary=[{'id':'summary','inlines':[{'type':'text','text':'更正后的收入为'}, {'type':'value','ref':ref(value)},{'type':'citation','ref':ref(anchor)}],'assertions':[ref(claim)]}],sections=[{'id':'body','title':'本次变化','blocks':[{'type':'paragraph','id':'result','inlines':[{'type':'text','text':'保留旧报告，使用新原件修订判断。'}]}]}],assertions=[ref(claim)])
            return SimpleNamespace(data={'report':result['report'],'questions':[],'findings':'offline source correction fixture'})
        result=tools.call(grant['token'],{'operation_id':uid('fixture'),'name':'report.save','arguments':{
            'title':'离线界面测试报告','summary':[{'id':'summary','inlines':[{'type':'text','text':'这是一份明确标注的离线界面夹具。'}]}],
            'sections':[{'id':'body','title':'研究内容','blocks':[{'type':'paragraph','id':'result','inlines':[{'type':'text','text':'用于检查研究、修订与导出的产品路径。'}]}]}]}})
        return SimpleNamespace(data={'report':result['report'],'questions':[],'findings':'offline fixture'})


station.agents=FixtureRuntime()
if os.environ.get('PITR_UI_DEMO')=='1':
    from ui_demo import seed_ui_demo
    seed_ui_demo(station)
import pitr.artifacts.queue as export_module
class FixtureExports(export_module.ExportQueue):
    def perform(self,job):
        original=self.renderer
        if self.store.get(job.report,'report').title=='修订后的离线报告' and job.attempts==1:
            def fail(*args):raise RuntimeError('浏览器验收：模拟首次渲染中断')
            self.renderer=fail
        try:super().perform(job)
        finally:self.renderer=original
export_module.ExportQueue=FixtureExports
# A concurrent developer build must not remove the assets a browser test is reading.
web_dist=root/'web-dist'
shutil.copytree(Path(__file__).resolve().parents[2]/'web/dist',web_dist)
app=create_app(root,station=station,workers=True,web_dir=web_dist)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from news_fixtures import seed_news
seed_news(app.state.news)
uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('PITR_BROWSER_PORT','18879')),log_level='warning')
