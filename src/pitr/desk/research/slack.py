"""Research routing only; durable acknowledgement, delivery and authorization stay generic."""
import re
from .service import Research
from .contracts import ResearchRequest,ResearchMessage
from pitr.integrations.slack import WorkflowUpdate,WorkflowModal


def controls(context,request,event_id=None):
    token=context.action('research_clarify',{'request_id':request['id'],'expected_input_version':request['input_version']},event_id=event_id)
    return [{'type':'section','text':{'type':'plain_text','text':'\n'.join(request['task']['research']['questions'])[:2600]}},
      {'type':'actions','elements':[{'type':'button','text':{'type':'plain_text','text':'回答 / 选择分析或收录'},'action_id':'pitr_action','value':token}]}]


def handle(adapter,event,context):
    service=Research(adapter.desk,adapter.queue)
    if event.kind=='submission' and event.action_id=='research_answer':
        values=event.values
        answer=ResearchMessage(operation_id=event.id,expected_input_version=event.metadata['expected_input_version'],text=values['question']['value'].get('value') or '分析附件',
          company=values['company']['value'].get('value') or '',intent=values['intent']['value']['selected_option']['value'])
        r=service.message(event.metadata['request_id'],answer)
        context.bind(r['task_id']);context.publish(event.id+':answer',WorkflowUpdate(text='已保存选择：'+r['id'],status='queued' if r['task']['status']=='queued' else 'completed'))
        return True
    if event.kind in ('changed','deleted'):
        matched=False
        message_ts=event.metadata.get('message_ts') or event.target.thread_ts
        for r in service.list():
            link=r['input']['context'].get('slack',{})
            if link.get('channel')==event.target.channel_id and link.get('message_ts')==message_ts:
                matched=True
                from ..contracts import utcnow
                from ..storage import canonical
                saved={k:v for k,v in r.items() if k!='task'};saved['invalidated']={'reason':'原研究消息已编辑或删除','at':utcnow()}
                with adapter.desk.store.connect(write=True) as db:db.execute('UPDATE research_requests SET body=? WHERE id=?',(canonical(saved),r['id']))
                for sid in r['input']['source_ids']:adapter.desk.withdraw(sid)
                if r['task']['status'] in ('queued','running','waiting_user'):adapter.queue.cancel(r['task_id'])
        if matched:
            context.publish(event.id+':invalidated',WorkflowUpdate(text='原研究消息已变更或删除；相关来源与待审结论已标记复核。历史报告保留。'))
        return False # Apply Wiki source invalidation for edits and deletions too.
    if event.kind not in ('message','mention','command'):return False
    text=event.text.strip()
    if re.match(r'^(收录|保存到\s*wiki|wiki\s+收录)',text,re.I):return False
    verb=text.split()[0].lower() if text else ''
    if verb in set(adapter.commands)-{'研究','research'}:return False
    if not text and not event.attachments:return False
    prior=next((r for r in service.list() if r['input']['context'].get('slack',{}).get('channel')==event.target.channel_id and r['input']['context'].get('slack',{}).get('message_ts')==event.target.thread_ts and r['input']['operation_id']!=event.id),None)
    def prepare():
        if len(event.attachments)>10:raise ValueError('每次最多十个附件')
        ids=[]
        for a in event.attachments:
            if a.status!='ready':raise ValueError('附件尚未成功下载，不能冒称已读：'+a.name)
            try:result=service.upload(context.attachment_bytes(a.id),a.media_type,a.name,'UNASSIGNED')
            except ValueError as error:
                from pitr.integrations.slack.contracts import WorkflowRejected
                raise WorkflowRejected(str(error)) from None
            ids.append(result['source_id'])
        return ResearchRequest(operation_id=event.id,question=text,company='',source_ids=ids,channel='slack',
           context={'followup':{'request_id':prior['id'],'input_version':prior['input_version']} if prior else None,'slack':{'event_id':event.id,'channel':event.target.channel_id,'message_ts':event.metadata.get('message_ts') or event.target.thread_ts}}).model_dump()
    prepared=ResearchRequest.model_validate(context.prepare(prepare))
    followup=prepared.context.get('followup')
    if followup:
        request=service.message(followup['request_id'],ResearchMessage(operation_id=event.id,text=prepared.question,source_ids=prepared.source_ids,expected_input_version=followup['input_version']))
    else:request=service.create(prepared)
    context.bind(request['task_id'])
    waiting=request['task']['status']=='waiting_user' and bool(request['task']['research']['questions'])
    context.publish(event.id+':research',WorkflowUpdate(text=('研究需要补充信息：' if waiting else '已保存，正在理解问题：')+request['id'],
       status='waiting_action' if waiting else 'queued',blocks=controls(context,request) if waiting else None))
    return True


def modal(adapter,event):
    r=Research(adapter.desk).get(event.metadata['request_id'])
    if r['task']['status']!='waiting_user':raise ValueError('这项选择已经处理')
    selected='report_review' if r['input']['source_ids'] else r['input']['intent']
    if selected=='auto':selected='investigation'
    options=[{'text':{'type':'plain_text','text':label},'value':v} for v,label in [('earnings','分析财报'),('report_review','复核研报观点'),('investigation','调查现有问题'),('collect','收录至 Wiki')]]
    return WorkflowModal(title='补充研究信息',action_id='research_answer',metadata=event.metadata,blocks=[
      {'type':'section','text':{'type':'plain_text','text':'\n'.join(r['task']['research']['questions'])[:2500]}},
      {'type':'input','block_id':'intent','label':{'type':'plain_text','text':'处理方式'},'element':{'type':'static_select','action_id':'value','options':options,'initial_option':next(o for o in options if o['value']==selected)}},
      {'type':'input','optional':True,'block_id':'company','label':{'type':'plain_text','text':'公司名称（可选）'},'element':{'type':'plain_text_input','action_id':'value','initial_value':r['input']['company']}},
      {'type':'input','block_id':'question','label':{'type':'plain_text','text':'研究问题 / 澄清回答'},'element':{'type':'plain_text_input','action_id':'value','multiline':True,'initial_value':r['input']['question'] or '分析附件中的主要观点，核对依据与反证'}}])
