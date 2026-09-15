"""Run the existing research and independent-review contracts through either CLI."""
from pathlib import Path
import time

from pitr.desk.contracts import utcnow
from pitr.desk.storage import canonical, digest, Conflict
from pitr.desk.research.contracts import AgentDraft, IndependentReview
from pitr.desk.research.native import broker
from pitr.desk.research.tools import tool_schemas


class WaitingForUser(Exception):
    pass


class BridgeNative:
    def session_id(self):
        return self.state.get('sessions',{}).get(self.role)

    def set_session(self,value):
        self.state.setdefault('sessions',{})[self.role]=value
        if self.role=='researcher':self.state['session_id']=value

    def __init__(self, plane, role='researcher'):
        self.plane=plane; self.desk=plane.desk; self.task=plane.task; self.state=plane.state
        self.role=role; self.runtime=self.desk.agents; self.current_ordinal=None
        binding=self.runtime._binding(self.task)
        self.model=binding.get('resolved_model') or binding.get('model')
        self.reasoning=binding.get('reasoning'); self.cli_version=binding['cli']
        self.output_model=IndependentReview if role=='reviewer' else AgentDraft
        from pitr.desk.research import native
        folder=Path(native.__file__).parent
        name='REVIEWER.md' if role=='reviewer' else 'SKILL.md'
        self.instructions=(folder/name).read_text()
        self.instructions+='\n只回答 context.research_scope.questions 与用户明确追加的问题，不强迫补齐通用章节、估值或预测。allow_public_search=false 时禁止公开搜索；材料不足时说明限制。模拟数据与原文声明不得冒充实际公司事实。保留事实与数值完整性核验、替代解释与独立复核。save_checkpoint 的 findings 用简短自然语言，不包含工具 ID 或计算 ID。'
        pinned={'provider':binding['provider'],'cli':binding['cli'],'tools':digest(tool_schemas()),
                'code_hash':digest({str(p):p.read_text() for p in [*folder.glob('*.py'),*Path(__file__).parent.glob('*.py')]}),
                'instructions':digest([(folder/n).read_text() for n in ('SKILL.md','REVIEWER.md')])}
        if self.state.get('bridge_pinned',pinned)!=pinned:
            raise Conflict('Agent 协议或研究指令已更新；请从已保存资料新建研究，不会静默续接旧会话')
        self.state['bridge_pinned']=pinned
        controller=digest(str(self.desk.store.path.resolve()))[:20]
        if self.state.get('controller_id',controller)!=controller:
            self.state.setdefault('lost_sessions',[]).extend(self.state.get('sessions',{}).values())
            self.state['sessions']={};self.state['session_id']=None
            self.state['recovery_note']='工作区位置已改变，从已保存证据建立新的独立会话'
        self.state['controller_id']=controller

    def attempt(self,prompt):
        from pitr.desk.research.intake import ready_update, UserUpdate
        from pitr.desk.research.trace.ingest import Tail
        self.plane.role=self.role
        with self.desk.store.connect(write=True) as db:
            self.plane.fence(db)
            ordinal=db.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM research_attempts WHERE task_id=?',(self.task['id'],)).fetchone()[0]
            record={'ordinal':ordinal,'started_at':utcnow(),'status':'running','role':self.role,
                    'session_before':self.session_id(),'agent':self.task['agent'],'usage':None}
            db.execute('INSERT INTO research_attempts VALUES(?,?,?)',(self.task['id'],ordinal,canonical(record)))
        self.current_ordinal=ordinal
        parent=f'attempt:{ordinal}';self.plane.trace_parent=parent;self.plane.trace_attempt=ordinal
        self.plane.trace.span(parent,name=f'{"独立复核" if self.role=="reviewer" else "自主调查"} · 尝试 {ordinal}',kind='agent',
            executor=self.task['agent']['provider'],parent_id='root',attempt=ordinal,started_at=record['started_at'],
            timing='measured',input_ref=self.plane.trace.content({'prompt':prompt}),metadata=record)
        prior=self.state.pop('trace_next_link',None)
        if prior:self.plane.trace.link(prior['id'],parent,prior['kind'])
        elif ordinal==1:self.plane.trace.link('preparation:'+str(self.task.get('attempts',1)),parent)
        tail=Tail(self.plane.trace,Path('/unused'),ordinal)
        started=time.monotonic();last_save=started;sequence=0;result=None;error=None
        def fence():
            nonlocal last_save
            with self.plane.lock:
                self.plane.fence();self.plane.charge()
                if ready_update(self.plane) and self.plane.execution_lock.acquire(blocking=False):
                    self.plane.update_pending=True;self.plane.execution_lock.release()
                    raise UserUpdate('已收到新的研究要求，正在纳入')
                if self.state.get('questions'):raise WaitingForUser()
                if time.monotonic()-last_save>=1:
                    self.plane.checkpoint({'research':self.state});last_save=time.monotonic()
        def session(value):
            self.set_session(value)
            self.plane.checkpoint({'research':self.state})
        def event(value):
            nonlocal sequence
            sequence+=1
            try:tail.accept(value,f'bridge:{ordinal}:{sequence}')
            except Exception:self.plane.trace.gap('bridge-event','部分事件未能显示，完整事件文件仍保留')
        try:
            with broker(self.plane) as mcp:
                result=self.runtime.execute(self.task,prompt,self.output_model.model_json_schema(),instructions=self.instructions,
                    role=self.role,session_id=self.session_id(),mcp=mcp,timeout=None,fence=fence,on_event=event,on_session=session)
            value=self.output_model.model_validate(result.data).model_dump()
            record.update(status='completed',usage=[result.usage] if result.usage else None,model=result.model,isolation=result.isolation,artifact_dir=str(result.root))
            return value
        except WaitingForUser:
            record['status']='waiting_user'
            return None
        except BaseException as exc:
            error=exc;record.update(status='updated' if isinstance(exc,UserUpdate) else 'interrupted' if self.runtime.stopping or self.task['id'] in self.runtime.cancelled else 'failed',error=str(exc))
            raise
        finally:
            record.update(finished_at=utcnow(),elapsed_seconds=time.monotonic()-started,session_after=self.session_id())
            with self.desk.store.connect(write=True) as db:
                db.execute('UPDATE research_attempts SET body=? WHERE task_id=? AND ordinal=?',(canonical(record),self.task['id'],ordinal))
            self.plane.trace.span(parent,status=record['status'],ended_at=record['finished_at'],duration_ms=record['elapsed_seconds']*1000,
                metadata=record,output_ref=self.plane.trace.content(result.data) if result else None,
                error_ref=self.plane.trace.content({'message':str(error)}) if error else None)
