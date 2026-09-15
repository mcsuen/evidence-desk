"""Run real semantic intake in an isolated control directory; never starts deep research."""
import argparse,json,time,sys
from pathlib import Path
from pitr.agent_runtime.runtime import AgentRuntime
from pitr.desk.service import Desk
from pitr.desk.research.service import Research
from pitr.desk.research.contracts import ResearchRequest
from pitr.desk.research.semantics import interpret
p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=4);p.add_argument('--ids',default='');args=p.parse_args()
root=Path('tmp/research-intake-eval-'+time.strftime('%Y%m%d-%H%M%S')).resolve();d=Desk(root);d.agents=AgentRuntime(d);service=Research(d)
cases=json.loads(Path('tests/fixtures/research_intents.json').read_text());results=[]
if args.ids:cases=[c for c in cases if c['id'] in args.ids.split(',')]
else:cases=cases[:args.limit]
for c in cases:
 started=time.monotonic();row={'id':c['id'],'expected':c}
 try:
  req=ResearchRequest(operation_id='eval-'+c['id'],workflow_version=3,question=c['question'],company=c.get('company',''),context_source=c.get('context_source','none'))
  r=service.create(req);value=interpret(d,r,[],c['id']);row['actual']=value
  checks={'clarification':bool(value['clarification'])==c['clarify']}
  if 'verified_name' in c:checks['verified_identity']=any(s['verified'] and c['verified_name'].casefold() in s['name'].casefold() for s in value['subjects'])
  if 'targets' in c:checks['targets']=sorted(s['company_id'] for s in value['subjects'] if s['role']=='target')==sorted(c['targets'])
  if 'scope' in c:checks['scope']=value['scope_type']==c['scope']
  if 'period' in c:checks['period']=value['period']==c['period']
  if 'intent' in c:checks['intent']=value['intent']==c['intent']
  row.update(checks=checks,passed=all(checks.values()))
 except Exception as e:row.update(passed=False,error=str(e))
 row['seconds']=round(time.monotonic()-started,2);results.append(row)
 print(c['id'],row['passed'],row['seconds'],row.get('error',''),flush=True)
 (root/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print('Results:',root/'results.json',flush=True)
sys.exit(0 if all(r['passed'] for r in results) else 1)
