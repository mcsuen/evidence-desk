"""Review handoff is bound to a server-stored artifact, never a client numeric bypass."""
import json
from ..storage import Conflict,digest
from pitr.wiki.contracts import ProposalInput, RevisionDraft, Reference

def delivery_gate(report):
    if (report.get('delivery',{}).get('status') not in ('ready','partial') or report.get('verification',{}).get('independent_review') not in ('passed','passed_with_gaps')):
        raise Conflict('研究尚未通过独立复核并完成交付，草稿不能进入正式业务审核')


def resolve(db,ref):
    row=db.execute('SELECT * FROM research_requests WHERE id=?',(ref.get('request_id'),)).fetchone()
    if not row:raise Conflict('研究交接身份不存在')
    task=db.execute('SELECT status FROM tasks WHERE id=?',(row['task_id'],)).fetchone()
    if not task or task['status']!='completed':raise Conflict('研究运行尚未完整交付，不能直接提交其草稿')
    if json.loads(row['body']).get('invalidated'):raise Conflict('原研究消息已变更，交接需要重新复核')
    artifact=db.execute('SELECT version,body FROM research_artifacts WHERE task_id=? ORDER BY version DESC LIMIT 1',(row['task_id'],)).fetchone()
    if not artifact or artifact['version']!=ref.get('artifact_version'):raise Conflict('研究产物已有新版本，旧提案需要重新复核')
    report=json.loads(artifact['body'])['validated']
    delivery_gate(report)
    if report['snapshot']!=ref.get('snapshot'):raise Conflict('研究交接快照身份不一致')
    claim=next((c for c in report['claims'] if c['id']==ref.get('claim_id')),None)
    if not claim or claim['validation']!='integrity_checked' or digest(claim)!=ref.get('claim_digest'):raise Conflict('研究结论不匹配或仍有核验问题')
    return report,claim


def propose(service,rid,body):
    report=service.artifact(rid);request=service.get(rid)
    if request['task']['status']!='completed':raise Conflict('只有已交付研究可以生成审核包')
    delivery_gate(report)
    if body.get('kind','wiki')!='wiki':raise ValueError('研究只交接 Wiki 提案')
    with service.desk.store.connect() as db:
        version=db.execute('SELECT MAX(version) FROM research_artifacts WHERE task_id=?',(request['task_id'],)).fetchone()[0]
    if body.get('artifact_version') and body['artifact_version']!=version:raise Conflict('报告已有新版本，请切换到最新报告后生成待审提案')
    claim=next((c for c in report['claims'] if c['id']==body.get('claim_id')),None)
    if not claim or claim['validation']!='integrity_checked' or not claim['alternative'] or not claim['next_check']:raise ValueError('结论需通过完整性核验并具备替代解释与检验条件')
    ref={'request_id':request['id'],'artifact_version':version,'claim_id':claim['id'],'claim_digest':digest(claim),'snapshot':report['snapshot']}
    object_id='wiki:research:'+request['id']+':'+claim['id']
    # Include transitive evidence, so downstream source withdrawal invalidates the proposal.
    allclaims={c['id']:c for c in report['claims']};ids={claim['id']}
    for _ in allclaims:
        for cid in list(ids):ids.update(allclaims[cid]['depends_on'])
    refs={x for cid in ids for x in allclaims[cid]['evidence']+allclaims[cid]['counterevidence']}
    # Calculation operand evidence is already materialized in the report.
    refs.update(e['id'] for e in report['evidence'])
    citations=[{'source_id':e['source_id'],'block_id':e['block_id'],'quote':e['quote']} for e in report['evidence'] if e['id'] in refs]
    with service.desk.store.connect(write=True) as db:
        service.desk._sources_valid(db,service.desk._snapshot(db,report['snapshot']))
        reason='来自核验后的研究产物；保留快照、计算依赖，仍须人工审核。替代解释：'+claim['alternative']+'；后续检验：'+claim['next_check']
        draft=RevisionDraft(id=object_id,kind='page',expected_version=0,
            title=body.get('title') or report['title'],content=claim['text'],page_type='analysis',nature='interpretation',
            citations=citations,numeric_assertions=[{'kind':'research_artifact','field':'content','research_ref':ref}],reason=reason)
        return service.desk.wiki.propose(ProposalInput(operation_id=body['operation_id'],company=request['input']['company'],
            policy=Reference(**service.desk.wiki._policy(db)),changes=[draft],reason=reason,origin='research'),db=db)
