"""Desk workflows behind the generic Slack event/update contracts."""
import json

from pitr.integrations.slack import OutputFile, WorkflowUpdate
from pitr.integrations.slack.contracts import WorkflowRejected


def report_file(text, title='研究结果'):
    return OutputFile(filename='research-report.txt', title=title, content=text)


class DeskAdapter:
    name = 'desk'
    commands = ('help', '帮助', '研究', 'research', '进度', 'status', '来源', 'source', '报告', 'report', 'wiki', '审核', 'review', '报错', 'issue')

    def __init__(self, desk, queue):
        self.desk = desk
        self.queue = queue

    def handle(self, event, context):
        try:
            self._handle(event, context)
        except WorkflowRejected:
            raise
        except ValueError:
            raise WorkflowRejected('参数或资料版本已变化，请检查公司、来源和任务 ID；审核操作请重新发送“审核”获取最新版本。') from None
        except KeyError:
            raise WorkflowRejected('找不到请求的资料或任务，请检查 ID 后重试。') from None

    def _handle(self, event, context):
        def reply(suffix, text, *, files=None, blocks=None, status='message'):
            context.publish(event.id + ':' + suffix, WorkflowUpdate(text=text, files=files or [], blocks=blocks, status=status))

        from pitr.wiki.slack_workflows import handle as handle_wiki
        if handle_wiki(self,event,context):return
        from .research.slack import handle as handle_research
        if handle_research(self,event,context):return

        parts = event.text.strip().split()
        verb = parts[0].lower() if parts else 'help'
        if event.kind in ('changed','deleted') or event.attachments or (event.kind in ('message','mention') and verb not in self.commands):
            from pitr.wiki.slack import capture_event
            captured=capture_event(self.desk.wiki,event,context)
            if captured or event.kind in ('changed','deleted'):return
            if event.attachments:
                reply('attachments','附件已接收，但尚未识别为公司研究材料；请补充公司与研究问题。')
                return
        if verb in ('进度', 'status'):
            tasks = self.desk.home()['tasks']
            if len(parts) > 1:
                tasks = [t for t in tasks if t['id'] == parts[1]]
            reply('status', '\n'.join(t['id'] + ' · ' + t['status'] for t in tasks[:8]) or '目前没有匹配的研究任务')
        elif verb == 'wiki':
            from pitr.wiki.search import search
            company=parts[1].upper() if len(parts)>1 and parts[1].upper() in ('PDD','BABA','JD','AMZN','MELI') else 'PDD'
            query=' '.join(parts[2:] if len(parts)>1 and parts[1].upper()==company else parts[1:])
            pages=search(self.desk.wiki,company,query)['items'] if query else self.desk.wiki.list(company,include_blocked=False)
            reply('wiki','\n\n'.join(p['title']+' · '+p['ref']+' · '+p['availability']+'\n'+p['content'] for p in pages[:5]) or '没有匹配的已发布页面')
        elif verb in ('报错','issue'):
            from pitr.wiki.contracts import IssueInput,Reference
            if len(parts)<3 or '@v' not in parts[1]:raise ValueError('需要版本引用和问题说明')
            identity,version=parts[1].rsplit('@v',1)
            issue=self.desk.wiki.report(IssueInput(operation_id=event.id,target=Reference(id=identity,version=int(version)),
                issue_type='semantic',description=' '.join(parts[2:]),discovered_by='slack'))
            reply('issue','已登记问题：'+issue['id']+'；在工作台查看影响范围并处理。')
        elif verb in ('来源', 'source') and len(parts) > 1:
            doc = self.desk.document(parts[1])
            reply('source', doc.title + '\n' + doc.url, files=[report_file('\n\n'.join(b.text for b in doc.blocks), doc.title)])
        elif verb in ('报告', 'report') and len(parts) > 1:
            with self.desk.store.connect() as db:
                row = db.execute('SELECT body FROM tasks WHERE id=?', (parts[1],)).fetchone()
            if not row:
                reply('missing', '运行不存在，请用“进度”查询任务 ID。')
                return
            task = json.loads(row['body'])
            if task['request']['workflow']=='research':
                from .research.service import Research
                from .research.report import slack_files
                reply('report','研究结果 · '+task['status'],files=slack_files(Research(self.desk).artifact(task['id'])))
            else:reply('report', '研究结果 · ' + task['status'], files=[report_file(json.dumps(task.get('result', task), ensure_ascii=False, indent=2))])
        else:
            reply('help', '可用命令：研究 PDD 问题；进度 [任务 ID]；来源 source_id；报告 task_id；Wiki 关键词；审核。\n'
                         '频道中请 @机器人，或输入 /research 后跟上述命令。\n'
                         '可接收 Slack 托管文件，每个最多 40 MB、每条最多 10 个；附件接收与业务资料导入分别处理。')

    def open_modal(self, event, context):
        if event.action_id in ('wiki_review','wiki_save'):
            from pitr.wiki.slack_workflows import modal
            return modal(self,event)
        if event.action_id=='research_clarify':
            from .research.slack import modal
            return modal(self,event)
        raise WorkflowRejected('审核入口已失效，请重新打开 Wiki 审核')

    def validate_submission(self, event):
        if event.action_id=='wiki_save_submit':
            choice=event.values.get('writeback',{}).get('value',{}).get('selected_option',{}).get('value')
            return {} if choice in ('topic','analysis') else {'writeback':'请选择保存位置'}
        if event.action_id=='research_answer':
            errors={}
            if not event.values.get('intent',{}).get('value',{}).get('selected_option'):errors['intent']='请选择处理方式'
            return errors
        values = event.values
        errors = {}
        def element(block):
            return (values.get(block) or {}).get('value') or {}
        def selected(block):
            return (element(block).get('selected_option') or {}).get('value')
        if event.action_id not in ('wiki_review_submit',):
            return {'action': '审核入口不正确，请重新打开'}
        if selected('action') not in ('adopt', 'reject'):
            errors['action'] = '请选择采纳或驳回'
        if not (element('reason').get('value') or '').strip():
            errors['reason'] = '请填写审核理由'
        if not any(o.get('value') == 'yes' for o in (element('reviewed').get('selected_options') or [])):
            errors['reviewed'] = '请先阅读完整变更及引用'
        return errors

    def poll(self, context):
        for binding in context.bindings():
            with self.desk.store.connect() as db:
                row = db.execute('SELECT body FROM tasks WHERE id=?', (binding['task_id'],)).fetchone()
            if not row:
                continue
            task = json.loads(row['body'])
            status = task['status']
            if status not in ('running', 'completed', 'failed', 'cancelled', 'waiting_user'):
                continue
            update_key = 'task:' + task['id'] + ':' + status
            if task['request']['workflow']=='research':
                from .research.service import Research
                from .research.slack import controls
                from .research.report import slack_files
                from .storage import digest
                research=Research(self.desk,self.queue);request=research.get(task['id'])
                update_key+=':'+digest(task.get('research',{}).get('questions',[]))[:12]
                if context.has_update(update_key):continue
                if status=='waiting_user':
                    context.publish(update_key,WorkflowUpdate(text='研究需要补充信息：'+request['id'],status='waiting_action',blocks=controls(context,request,event_id=binding['event_id'])),event_id=binding['event_id'])
                else:
                    report=research.artifact(request['id']) if (status=='completed' or task.get('research',{}).get('latest_artifact_version')) and task.get('result',{}).get('status')!='collected' else None
                    summary='研究 · '+{'completed':'已完成','failed':'失败','running':'进行中','cancelled':'已取消'}[status]+' · '+request['id']
                    if report:summary+='\n'+report.get('delivery',{}).get('reason',report['status'])+' · '+str(len(report['claims']))+' 条结论 · 人工审核待完成\n'+'\n'.join(c['text'] for c in report['claims'][:2])
                    if task.get('error'):summary+='\n'+task['error'][:800]
                    context.publish(update_key,WorkflowUpdate(text=summary[:2800],status=status,files=slack_files(report) if report else []),event_id=binding['event_id'])
                continue
            if context.has_update(update_key):
                continue
            result = task.get('result') or {}
            if task['request']['workflow']=='wiki_answer' and result.get('answer'):
                answer=result['answer']
                token=context.action('wiki_save', {'task_id':task['id']})
                blocks=[{'type':'actions','elements':[{'type':'button','text':{'type':'plain_text','text':'保存分析到 Wiki 草稿'},'action_id':'pitr_action','value':token}]}]
                citations='\n'.join(c['source_id']+' · '+c['block_id']+': '+c['quote'][:180] for c in answer['citations'][:4])
                context.publish(update_key,WorkflowUpdate(text=(answer['title']+'\n'+answer['content'][:1500]+'\n依据：\n'+citations)[:2800],status=status,blocks=blocks,
                    files=[report_file(json.dumps(answer,ensure_ascii=False,indent=2),'完整回答、原始证据与实际使用版本')]),event_id=binding['event_id'])
                continue
            if task['request']['workflow']=='wiki_job':
                from pitr.wiki.jobs import WikiJobs
                job=WikiJobs(self.desk.wiki).get(task['request']['parameters']['job_id'])
                summary='资料搜集整理完成，等待人工采纳' if job.get('proposal_id') else '资料检查不完整' if job['execution_status'] in ('partial','failed') else '正在搜集和处理资料' if status=='running' else '检查结束'
                context.publish(update_key,WorkflowUpdate(text=job['company']+' Wiki：'+summary+'\n任务 '+job['id']+'\n已取得 '+str(sum(bool(m.get('source_id')) for m in job['materials']))+' 份资料；失败 '+str(len(job['failures']))+' 项。'+ ('\n可发送“审核 '+job['company']+' Wiki”查看完整变更。' if job.get('proposal_id') else ''),status=status,
                    files=[report_file(json.dumps(job,ensure_ascii=False,indent=2),'资料、覆盖与检查结果')] if status!='running' else []),event_id=binding['event_id'])
                continue
            files = [report_file(json.dumps(result or {'error': task.get('error'), 'status': status}, ensure_ascii=False, indent=2))] if status in ('completed', 'failed', 'cancelled') else []
            context.publish(update_key,
                            WorkflowUpdate(text='研究' + {'running': '进行中', 'completed': '已完成', 'failed': '失败', 'cancelled': '已取消'}[status] + ' · ' + task['id'], status=status, files=files),
                            event_id=binding['event_id'])
