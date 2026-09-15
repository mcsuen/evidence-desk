"""Incremental CLI ingestion. Controller call IDs, never CLI items, count domain tools."""
import json
from pathlib import Path
from ...contracts import utcnow

KNOWN={'thread.started','turn.started','turn.completed','turn.failed','error','item.started','item.updated','item.completed'}
ITEMS={'mcp_tool_call','agent_message','reasoning','error','todo_list','plan','command_execution','file_change','web_search','collab_tool_call'}

class Tail:
    def __init__(self,trace,path,attempt,historical=False):
        self.trace=trace;self.path=Path(path);self.attempt=attempt;self.historical=historical
        self.stream=f'cli:{attempt}:{self.path.name}';self.session_id=None
    def poll(self):
        if not self.path.exists():return []
        stat=self.path.stat();identity=f'{stat.st_dev}:{stat.st_ino}'
        with self.trace.desk.store.connect() as db:
            row=db.execute('SELECT position,identity FROM trace_cursors WHERE task_id=? AND stream=?',(self.trace.task_id,self.stream)).fetchone()
        pos=row[0] if row and row[1]==identity and row[0]<=stat.st_size else 0
        if row and (row[1]!=identity or row[0]>stat.st_size):self.trace.gap('stream-reset:'+self.stream,'CLI 文件发生替换或截断；按新的文件身份保留事件')
        result=[]
        with self.path.open('rb') as stream:
            stream.seek(pos)
            while True:
                offset=stream.tell();line=stream.readline()
                if not line or not line.endswith(b'\n'):break
                pos=stream.tell();event_id=f'{self.stream}:{identity}:{offset}'
                try:event=json.loads(line)
                except (ValueError,UnicodeError):
                    self.trace.emit('cli.invalid',event_id=event_id,source='cli',span_id=f'attempt:{self.attempt}',content={'raw':line.decode(errors='replace')})
                    self.trace.gap('cli-invalid:'+event_id,'CLI 存在无法解析的事件，原始内容已保留');continue
                self.accept(event,event_id);result.append(event)
        with self.trace.desk.store.connect(write=True) as db:
            db.execute('INSERT OR REPLACE INTO trace_cursors VALUES(?,?,?,?)',(self.trace.task_id,self.stream,pos,identity))
        return result
    def accept(self,event,event_id):
        kind=event.get('type','unknown');item=event.get('item') or {};span_id=f'attempt:{self.attempt}'
        metadata=(item.get('result') or {}).get('_meta',{}) if isinstance(item.get('result'),dict) else {}
        correlation=metadata.get('pitr.trace',{})
        if correlation.get('task_id')==self.trace.task_id and correlation.get('span_id'):span_id=correlation['span_id']
        self.trace.emit('cli.'+kind,event_id=event_id,source='cli',span_id=span_id,occurred_at=None if self.historical else utcnow(),
             content=event,data={'attempt':self.attempt,'observed_time':not self.historical,'item_id':item.get('id')})
        if kind=='thread.started':self.session_id=event.get('thread_id')
        if kind not in KNOWN or (kind.startswith('item.') and item.get('type') not in ITEMS):
            self.trace.gap('unknown-cli:'+str(kind)+':'+str(item.get('type')),'遇到未支持的 CLI 事件；保留原始事件，不推测节点含义')
        if item.get('type') in ('todo_list','plan'):
            # Preserve every declaration, including removal. These are not execution spans.
            self.trace.emit('plan',event_id='plan:'+event_id,source='cli',span_id=f'attempt:{self.attempt}',
                 occurred_at=None if self.historical else utcnow(),data={'attempt':self.attempt,'item_id':item.get('id'),'items':item.get('items',item.get('steps',[]))},content=item)
