"""Slack commands use exactly the same application commands as the workbench."""
import json
import shlex

from pitr.domain.contracts import CreateCase, StartRun, ContinueRun, Scope, ExportRequest
from pitr.domain.numbers import display
from pitr.integrations.slack.contracts import WorkflowUpdate, WorkflowRejected, OutputFile


class ResearchWorkflow:
    name='research'
    commands=('/research',)

    def __init__(self,station):self.station=station

    def handle(self,event,context):
        parts=shlex.split(event.text)
        action=parts[0].lower() if parts else 'help'
        if event.kind in ('changed','deleted'):
            context.publish(event.id,WorkflowUpdate(text='输入修改不会覆盖既有研究，请在工作台创建新输入修订。'))
            return
        if action=='help':
            context.publish(event.id,WorkflowUpdate(text='研究命令：new 主体标识 研究问题；status 执行ID；cancel 执行ID；continue 执行ID；export 执行ID。附件作为不可变原件导入。采纳和修订请在工作台完成。'))
            return
        if action=='new':
            if len(parts)<3:raise WorkflowRejected('用法：new 主体标识 研究问题')
            subject=parts[1].upper();self.station.store.get(subject,'subject')
            sources=[]
            for attachment in event.attachments:
                raw=context.attachment_bytes(attachment.id)
                source=self.station.import_source(raw,attachment.media_type,title=attachment.name,subjects=[subject],
                    operation_id=event.id+':source:'+attachment.id)
                sources.append(source.ref)
            request=context.prepare(lambda:CreateCase(operation_id=event.id+':case',question=' '.join(parts[2:]),
                scope=Scope(subjects=[subject]),sources=sources).model_dump(mode='json'))
            case=self.station.create_case(CreateCase.model_validate(request))
            run=self.station.start_run(case['id'],StartRun(operation_id=event.id+':run',expected_revision=1))
            context.bind(run['id'])
            context.publish(event.id,WorkflowUpdate(text='已保存并排队：'+case['title']+'\n执行：'+run['id'],status='queued'))
            return
        if len(parts)!=2:raise WorkflowRejected('请提供一个准确的执行 ID')
        run=self.station.get_run(parts[1])
        if action=='status':
            context.publish(event.id,WorkflowUpdate(text=f'{run.status} · 工具 {run.tool_calls}/{run.budget.tool_calls} · {run.error}'))
        elif action=='cancel':
            self.station.cancel(run.id,event.id)
            context.publish(event.id,WorkflowUpdate(text='已取消，已保存的输入与成果保留。',status='cancelled'))
        elif action=='continue':
            self.station.continue_run(run.id,ContinueRun(operation_id=event.id,expected_generation=run.generation))
            context.bind(run.id)
            context.publish(event.id,WorkflowUpdate(text='已从检查点继续，新增预算已记录。',status='queued'))
        elif action=='export':
            if not run.report:raise WorkflowRejected('该执行尚无报告')
            job=self.station.reports.export(ExportRequest(operation_id=event.id,report=run.report))
            context.bind('export:'+job['id'])
            context.publish(event.id,WorkflowUpdate(text='已加入独立 Word 导出队列。',status='queued'))
        else:raise WorkflowRejected('未知命令，可发送 help 查看用法')

    def open_modal(self,event,context):raise WorkflowRejected('请使用命令或在工作台操作')
    def validate_submission(self,event):return {'request':'此渠道使用文字命令'}

    def poll(self,context):
        for binding in context.bindings():
            rid,eid=binding['task_id'],binding['event_id']
            if rid.startswith('export:'):
                with self.station.store.connect() as db:row=db.execute('SELECT body FROM exports WHERE id=?',(rid[7:],)).fetchone()
                if not row:continue
                job=json.loads(row[0]);key=rid+':'+job['status']+':'+str(job['attempts'])
                if job['status'] not in ('completed','failed') or context.has_update(key):continue
                files=[]
                if job['artifact']:
                    artifact=self.station.store.get(job['artifact'],'artifact')
                    files=[OutputFile.from_bytes(self.station.store.read_blob(artifact.digest),filename='research.docx',title='研究报告 Word')]
                context.publish(key,WorkflowUpdate(text='Word 导出完成' if files else 'Word 导出失败：'+job['error'],
                    status='completed' if files else 'failed',files=files),event_id=eid)
                continue
            run=self.station.get_run(rid);key=rid+':'+str(run.generation)+':'+run.status
            if run.status in ('queued','running') or context.has_update(key):continue
            text='研究执行状态：'+run.status
            if run.report:
                view=self.station.reports.view(run.report)
                text+='\n报告：'+view.document.title+' · '+view.delivery+'\n'
                for p in view.document.summary:
                    text+=''.join(s.text if s.type=='text' else view.value_labels[s.ref.key] if s.type=='value' else '[原件引用]' for s in p.inlines)+'\n'
                text+='\n'+'\n'.join(view.document.gaps)
            text+='\n'+run.error+'\n'+'\n'.join(run.questions)
            context.publish(key,WorkflowUpdate(text=text[:12000],status='waiting_action' if run.status in ('waiting_user','budget_exhausted') else
                'cancelled' if run.status=='cancelled' else 'failed' if run.status=='failed' else 'completed'),event_id=eid)


class SlackConnection:
    def __init__(self,station):
        from pitr.integrations.slack.runtime import SlackRuntime
        self.runtime=SlackRuntime(station.root/'channels/slack',station.settings.read,station.settings.save)
        self.runtime.register(ResearchWorkflow(station),default=True)
        station.slack=self.runtime
        if station.settings.read().get('slack_enabled'):
            try:self.runtime.start(enable=False)
            except ValueError:pass

    def close(self):self.runtime.stop(disable=False)
