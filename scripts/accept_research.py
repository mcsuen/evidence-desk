"""Opt-in real model acceptance on clearly labelled isolated synthetic documents."""
from pathlib import Path
import time,json
from pitr.agent_runtime.runtime import AgentRuntime
from pitr.desk.service import Desk
from pitr.desk.tasks import Queue
from pitr.desk.research.service import Research
from pitr.desk.research.contracts import ResearchRequest
from pitr.desk.research.intake import IntakeWorker
root=Path('tmp/research-live-'+time.strftime('%Y%m%d-%H%M%S')).resolve()
d=Desk(root);d.agents=AgentRuntime(d);q=Queue(d);service=Research(d,q)
ids=[]
for company,rev,profit,cash in [('PDD',100,20,25),('BABA',200,30,32)]:
 text=f'''OFFLINE SOFTWARE ACCEPTANCE FIXTURE — NOT ACTUAL COMPANY DATA.
Company identity for test routing: {company}.
Calendar quarter: 2025Q2, April 1 to June 30, 2025. Currency and unit: RMB million. Accounting basis: US GAAP. This is a synthetic consolidated entity with no other segments.
Revenue: {rev}. Operating profit: {profit}. Operating cash flow: {cash}.
These values are invented solely for validating software arithmetic and evidence links. They must never be described as actual corporate disclosures, an investment conclusion, or a business outlook. No actual company profitability can be inferred from this fixture.
'''
 ids.append(service.upload(text.encode(),'text/plain',company+'-offline-acceptance.txt')['source_id'])
r=service.create(ResearchRequest(operation_id='real-model-acceptance',question='这是软件验收。仅比较附件中拼多多和阿里的离线模拟数据：两者营业利润率及经营现金流与营业利润的比率有什么差异？只回答这两个问题，保留模拟资料限制，不推导实际公司情况。无需搜索外部材料。',source_ids=ids,budget_seconds=600,tool_budget=100))
print('ROOT',root,flush=True);print('REQUEST',r['id'],flush=True)
IntakeWorker(d,q).run_one();r=service.get(r['id']);print('INTERPRETED',r['interpretation_status'],json.dumps(r.get('interpretation'),ensure_ascii=False),flush=True)
(root/'request.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
if r['task']['status']=='queued':
 q.run_one();r=service.get(r['id']);print('FINISHED',r['task']['status'],r['task'].get('error',''),flush=True)
 (root/'final.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
 try:
  report=service.artifact(r['id']);(root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('REPORT',report['status'],report.get('delivery'),flush=True)
 except Exception as e:print('NO_REPORT',str(e),flush=True)
