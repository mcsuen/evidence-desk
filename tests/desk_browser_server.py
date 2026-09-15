import tempfile
import os
from pathlib import Path
from pitr.desk.service import Desk
from pitr.desk.storage import canonical
from pitr.desk.contracts import Metric,Citation
from pitr.desk.api import create_app
import uvicorn
root=Path(tempfile.mkdtemp(prefix='pitr-desk-browser-'))
desk=Desk(root)
raw=b'PDD HOLDINGS\n\nAugust 1, 2025\n\nThis is an offline UI test fixture, not a company report.\n\nInvestment may remain elevated. Revenue 100. Operating profit 20.'
d=desk.ingest(raw,'text/plain','https://investor.pddholdings.com/offline-test','PDD','2025Q2 Offline test fixture')
ref=Citation(source_id=d.id,block_id=d.blocks[-1].id,quote=d.blocks[-1].text)
with desk.store.connect(write=True) as db:
 for period,rev,op in [('2024Q1',70,15),('2024Q2',80,24),('2024Q3',85,17),('2024Q4',88,18),('2025Q1',90,19),('2025Q2',100,20)]:
  for name,value in [('revenue',rev),('online_marketing',rev*.5),('transaction_services',rev*.5),('operating_profit',op),('cost_of_revenue',rev*.4),('sales_marketing',rev*.6-10-op),('general_admin',5),('research_development',5),('net_income',18),('eps_ads',4),('operating_cash_flow',22)]:
   m=Metric(id=name+period,name=name,label=name,period=period,value=value,unit='RMB_per_ADS' if name=='eps_ads' else 'RMB_mn',citation=ref)
   db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,'PDD',d.id,canonical(m)))
with desk.store.connect(write=True) as db:
 db.execute("UPDATE wiki_outbox SET status='delivered' WHERE kind='compile'")
# Deterministic layout fixture; no model is called and it is labelled as such.
from research_fixtures import Research
from pitr.desk.research.contracts import ResearchRequest
from pitr.desk.research.tools import ToolPlane
from pitr.desk.research.verify import validate
from pitr.desk.tasks import Queue
from pitr.desk.contracts import utcnow
queue=Queue(desk);snap=desk.snapshot('PDD',utcnow())[0]
request=Research(desk,queue).create(ResearchRequest(operation_id='browser-report-fixture',company='PDD',period='2025Q2',question='离线界面验收：利润率变化核对',intent='earnings',snapshot=snap))
task=queue.claim();plane=ToolPlane(desk,task,queue.owner,lambda u:queue.checkpoint(task,u));plane.prepare()
e=plane.read_source(d.id)['blocks'][-1]
calc=plane.financial_comparison('operating_profit')['references']['yoy']
claims=[{'id':k,'section':k,'text':'2025Q2 经营利润变化为 {{'+calc['id']+'}}。','verdict':'interpretation','evidence':[e['id']],'alternative':'可能反映投入的发生时点。','next_check':'核对后续同口径成本与收入。'} for k in ['changes','baseline','cash_margin','persistence','model_impact','questions']]
report=validate({'title':'离线界面验收 · 财报核对','claims':claims,'gaps':['此数据为浏览器验收样例，不是公司研究结论。']},plane)
with desk.store.connect(write=True) as db:
 db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(task['id'],1,canonical({'raw':{'claims':claims},'validated':report})))
 task.update(status='completed',result=report);db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',('completed',canonical(task),task['id']))
fixture_mode=True
app=create_app(root,Path(__file__).resolve().parents[1]/'web'/'dist',worker=True,
               agent_runtime=(lambda _:None) if fixture_mode else None)
if fixture_mode:
 from pitr.desk.research.intake import IntakeWorker
 from pitr.desk.research.contracts import ResearchInterpretation,ResearchSubject
 def fixture_interpret(desk,request,messages,key,fence):
  # Explicit offline UX fixture. Production never uses this resolver.
  question=request['input']['question'];bare=not question.strip() and not messages
  names=['PDD','BABA'] if '比较' in question else ['BABA'] if '阿里' in question else ['PDD']
  return ResearchInterpretation(title='利润持续性研究',scope_type='comparison' if len(names)>1 else 'company',subjects=[ResearchSubject(company_id=c,name={'PDD':'拼多多','BABA':'阿里巴巴'}[c],mention={'PDD':'拼多多','BABA':'阿里巴巴'}[c],verified=True) for c in names],questions=['利润增长是否可持续？'],plan=['读取原始披露','核对现金流','寻找替代解释'],clarification='希望我如何处理这些材料？' if bare else '',options=['复核核心观点及依据','总结关键内容','收录至 Wiki'] if bare else []).model_dump()
 from pitr.desk.research import native
 native.run=lambda *a:{'status':'waiting_user','note':'Offline UI fixture; no model execution.'}
 # Queue creates its intake worker during startup; inject the fixture at construction.
 import pitr.desk.research.intake as intake_module
 original_worker=intake_module.IntakeWorker
 intake_module.IntakeWorker=lambda desk,queue=None:original_worker(desk,queue,resolver=fixture_interpret)
uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('PITR_BROWSER_PORT','8879')))
