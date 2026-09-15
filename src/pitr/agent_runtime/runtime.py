"""One local transport implementation for research, discovery and Wiki calls."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .connection import NAMES, connection, connection_fingerprint, executable, probe, codex_command, toml
from .transport import AgentError, Process

MODEL_ID = re.compile(r'[A-Za-z0-9_./:@+-]+(?:\[1m\])?')


@dataclass
class Result:
    data: dict
    provider: str
    model: str
    session_id: str | None
    usage: dict
    events: list
    root: Path
    isolation: dict


class AgentRuntime:
    def __init__(self, desk, settings=None, *, environ=None, isolate=True):
        from pitr.integrations.slack.settings import SettingsFile
        self.desk = desk
        self.settings = settings or SettingsFile(desk.root / 'private/settings.json')
        self.environ = dict(os.environ if environ is None else environ)
        self.isolate = isolate
        self.lock = threading.RLock()
        self.descriptors = []
        self.checked = 0.
        self.refreshing = False
        self.processes = {}
        self.cancelled = set()
        self.cancel_epochs = {}
        self.stopping = False
        self.model_cache = {}
        self.session_locks = {}
        with desk.store.connect(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_bindings(task_id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_calls(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,body TEXT NOT NULL)')

    def refresh(self, background=False):
        with self.lock:
            if self.refreshing:
                return self.status()
            self.refreshing = True
        def work():
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    found = list(pool.map(lambda name: probe(name, self.environ,lambda:self.stopping), NAMES))
                with self.lock:
                    self.descriptors = found
                    self.checked = time.time()
                    self.model_cache.clear()
                ready = [d['id'] for d in found if d['status'] == 'logged_in']
                with self.settings.lock:
                    if len(ready) == 1 and not self.settings.read().get('agent_provider'):
                        self.settings.save({'agent_provider': ready[0]})
            finally:
                self.refreshing = False
        if background:
            threading.Thread(target=work, daemon=True, name='agent-discovery').start()
        else:
            work()
        return self.status()

    def status(self):
        return {'agents': list(self.descriptors), 'checking': self.refreshing, 'checked_at': self.checked or None,
                'selection': {k: v for k, v in self.settings.read().items() if k in ('agent_provider', 'agent_models')}}

    def selection(self, provider=None, model=None, reasoning=None):
        if self.stopping:
            raise AgentError('本机服务正在停止，输入已保留')
        settings = self.settings.read()
        provider = provider or settings.get('agent_provider')
        if provider not in NAMES:
            raise AgentError('请先在页面上方选择本机 Codex 或 Claude Code')
        descriptor = next((d for d in self.descriptors if d['id'] == provider), None)
        if descriptor is None:
            descriptor = probe(provider, self.environ,lambda:self.stopping)
        if descriptor['status'] != 'logged_in':
            raise AgentError(NAMES[provider] + ' 尚未就绪：请检查安装、登录和 CLI 版本')
        env, config, _ = connection(provider, self.environ)
        requested = model if model is not None else settings.get('agent_models', {}).get(provider)
        if requested and (not isinstance(requested,str) or len(requested)>200 or not MODEL_ID.fullmatch(requested)):
            raise ValueError('模型 ID 格式不正确')
        return {'version': 1, 'provider': provider, 'requested_model': requested or None,
                'model': requested or config.get('model') or (env.get('ANTHROPIC_MODEL') if provider == 'claude' else None),
                'reasoning': reasoning or config.get('model_reasoning_effort' if provider == 'codex' else 'effortLevel'),
                'cli': descriptor['version'],'auth_method':descriptor.get('auth_method'),
                'connection_fingerprint':connection_fingerprint(env,config)}

    def save_selection(self, values):
        provider = values.get('agent_provider')
        if provider is not None and provider not in NAMES:
            raise ValueError('Agent 必须是 codex 或 claude')
        models = values.get('agent_models')
        if models is not None:
            if not isinstance(models, dict) or any(k not in NAMES or (v is not None and (not isinstance(v, str) or len(v) > 200 or not MODEL_ID.fullmatch(v))) for k, v in models.items()):
                raise ValueError('模型 ID 格式不正确')
            values = {**values, 'agent_models': {**self.settings.read().get('agent_models', {}), **models}}
        return self.settings.save(values)

    def _binding(self, task):
        binding = dict(task['agent'])
        with self.desk.store.connect() as db:
            row = db.execute('SELECT body FROM agent_bindings WHERE task_id=?', (task['id'],)).fetchone()
        if row:
            saved = json.loads(row['body'])
            if saved['provider'] != binding['provider'] or saved.get('requested_model') != binding.get('requested_model'):
                raise AgentError('任务的 Agent 或模型已改变，请新建研究')
            binding = saved
        return binding

    def _pin_model(self, task, binding, model):
        if not model:
            return
        with self.desk.store.connect(write=True) as db:
            row = db.execute('SELECT body FROM agent_bindings WHERE task_id=?', (task['id'],)).fetchone()
            saved = json.loads(row['body']) if row else binding
            if saved.get('resolved_model') and saved['resolved_model'] != model:
                raise AgentError('实际运行模型已发生变化，请新建任务；已保留本次记录')
            binding.update(resolved_model=model)
            db.execute('INSERT OR REPLACE INTO agent_bindings VALUES(?,?)', (task['id'], json.dumps(binding)))
            row=db.execute('SELECT body FROM tasks WHERE id=?',(task['id'],)).fetchone()
            if row:
                body=json.loads(row['body']);body['agent']=dict(binding)
                db.execute('UPDATE tasks SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),task['id']))
        task['agent'].update(binding)

    def models(self, provider):
        if provider not in NAMES:
            raise ValueError('未知 Agent')
        cached = self.model_cache.get(provider)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        env, config, config_home = connection(provider, self.environ)
        options = [{'id': '', 'name': '沿用本机默认模型', 'source': 'default'}]
        if provider == 'claude':
            configured=[config.get('model'),env.get('ANTHROPIC_MODEL'),*config.get('availableModels',[]),
                        *config.get('modelOverrides',{}).values(),*[v for k,v in env.items() if k.startswith('ANTHROPIC_DEFAULT_') and k.endswith('_MODEL')]]
            configured=[v for v in configured if isinstance(v,str) and v]
            named = list(dict.fromkeys([*configured, 'opus', 'sonnet', 'haiku']))
            options += [{'id': v, 'name': v, 'source': 'configuration' if v in config.get('availableModels', []) or v == config.get('model') else 'alias'} for v in named if isinstance(v, str) and v]
        else:
            binary = executable(provider, self.environ)
            if not binary:
                raise AgentError('Codex 尚未安装')
            from pitr.desk.research.native import runtime_root
            root = runtime_root(self.desk) / 'model-discovery' / uuid.uuid4().hex; root.mkdir(parents=True, exist_ok=True, mode=0o700)
            from .isolation import prepare
            prefix,_=prepare(self.desk,root,binary,config_home,env) if self.isolate else ([],{})
            p = Process(prefix+codex_command(binary, config), cwd=root, env=env, timeout=30)
            key=('model-discovery',root.name)
            with self.lock:
                if self.stopping:p.close();raise AgentError('本机服务正在停止')
                self.processes[key]=p
            try:
                p.rpc('initialize', {'clientInfo': {'name': 'pitr', 'version': '1'}})
                p.send({'method': 'initialized', 'params': {}})
                cursor = None
                for _ in range(8):
                    page = p.rpc('model/list', {'limit': 100, **({'cursor': cursor} if cursor else {})})
                    for item in page.get('data', []):
                        value = item.get('model') or item.get('id')
                        if value:
                            options.append({'id': value, 'name': item.get('displayName') or value, 'source': 'cli'})
                    cursor = page.get('nextCursor')
                    if not cursor:
                        break
            finally:
                p.close()
                with self.lock:self.processes.pop(key,None)
        result = {'models': options, 'custom_model': provider == 'claude', 'permissions_verified': False}
        self.model_cache[provider] = (time.monotonic(), result)
        return result

    def cancel(self, task_id):
        with self.lock:
            self.cancelled.add(task_id)
            self.cancel_epochs[task_id]=self.cancel_epochs.get(task_id,0)+1
            processes = [p for (tid, _), p in self.processes.items() if tid == task_id]
        for process in processes:
            process.cancelled.set()

    def shutdown(self):
        with self.lock:
            self.stopping = True
            processes = list(self.processes.values())
        for process in processes:
            process.cancelled.set()
        for process in processes:
            process.close()

    def complete_json(self, task, prompt, schema, system=None, timeout=600, fence=lambda: None, **kwargs):
        from pitr.llm import LLMResult
        result = self.execute(task, prompt, schema, instructions=system or '', timeout=timeout, fence=fence)
        return LLMResult(result.data, result.provider + '_cli', result.model, json.dumps(result.data, ensure_ascii=False))

    def execute(self, task, prompt, schema, *, instructions='', role='completion', session_id=None,
                live_search=False, mcp=None, timeout=600, fence=lambda: None, on_event=lambda e: None,
                on_session=lambda session: None):
        # Cancellation invalidates calls already in flight. The queue/lease
        # fence decides whether a later explicit follow-up is authorized.
        epoch=self.cancel_epochs.get(task['id'],0)
        from pitr.desk.research.native import runtime_root
        from pitr.llm import strict_json_schema
        from .isolation import prepare
        binding = self._binding(task); provider = binding['provider']
        env, config, config_home = connection(provider, self.environ)
        binary = executable(provider, self.environ)
        if not binary:
            raise AgentError(NAMES[provider] + ' 不可用；请重新安装官方 CLI')
        observed=probe(provider,self.environ,lambda:self.stopping)
        if observed['status']!='logged_in':raise AgentError(NAMES[provider]+' 登录或 CLI 状态已改变，请在本机设置页刷新检测；任务输入已保留')
        if binding.get('cli')!=observed['version'] or binding.get('auth_method')!=observed.get('auth_method'):
            raise AgentError('CLI 版本或认证方式已改变，请从保留的资料新建任务；旧会话不会自动转移')
        if binding.get('connection_fingerprint')!=connection_fingerprint(env,config):
            raise AgentError('本机连接配置已改变，请恢复原设置或新建任务；不会改变运行中任务的认证方式')
        # Resolve model defaults once for the complete research/Wiki chain.
        model = binding.get('resolved_model') or binding.get('model')
        # Claude reports the resolved base model without the requested context
        # window suffix. Keep that option when pinning subsequent calls.
        if provider == 'claude' and model and (binding.get('model') or '').endswith('[1m]') and not model.endswith('[1m]'):
            model += '[1m]'
        call_id = uuid.uuid4().hex
        root = runtime_root(self.desk) / (task['id'] + '-' + role) / call_id
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        schema = strict_json_schema(schema)
        (root / 'schema.json').write_text(json.dumps(schema, ensure_ascii=False))
        (root / 'instructions.md').write_text(instructions)
        if provider == 'codex':
            command = codex_command(binary, config)
            command += ['-c', 'web_search=' + toml('live' if live_search else 'disabled')]
            if mcp:
                command+=['-c','features.code_mode_host=true']
                for key, value in self._mcp(root, env, mcp).items():
                    command += ['-c', 'mcp_servers.pitr_research.' + key + '=' + toml(value)]
        else:
            # Restricted mode + hidden configuration keeps native authentication
            # and explicitly injected MCP. Safe mode disables even our MCP.
            settings = {**config, 'disableAllHooks': True, 'autoMemoryEnabled': False}
            command = [binary, '--restricted', '--disable-slash-commands', '--setting-sources', '', '--settings', json.dumps(settings),
                       '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
                       '--include-partial-messages', '--json-schema', json.dumps(schema),
                       '--system-prompt', instructions or 'Return the requested structured result.',
                       '--tools', 'WebSearch' if live_search else '', '--permission-mode', 'dontAsk', '--strict-mcp-config']
            servers = {'mcpServers': {}}
            if mcp:
                values = self._mcp(root, env, mcp)
                servers['mcpServers']['pitr_research'] = {k: values[k] for k in ('command', 'args')}
            command += ['--mcp-config', json.dumps(servers), '--allowedTools', 'mcp__pitr_research__*' + (',WebSearch' if live_search else '')]
            if model:
                command += ['--model', model]
            if binding.get('reasoning'):
                command += ['--effort', binding['reasoning']]
            if session_id:
                command += ['--resume', session_id]
        prefix, isolation = prepare(self.desk, root, binary, config_home, env, mcp[0] if mcp else 0) if self.isolate else ([], {'passed': False, 'mechanism': 'test transport'})
        key = (task['id'], call_id)
        def check():
            if self.stopping or self.cancel_epochs.get(task['id'],0)!=epoch:
                raise AgentError('任务已停止，输入和已完成的结果仍保留')
            fence()
        check()
        session_key = (provider, session_id or call_id)
        with self.lock:
            session_lock = self.session_locks.setdefault(session_key, threading.Lock())
        while not session_lock.acquire(timeout=.2):
            check()
        p = None; events = []; usage = {}; resolved = model; native_session = session_id
        call={'id':call_id,'task_id':task['id'],'provider':provider,'role':role,'requested_model':binding.get('requested_model'),
              'started_at':time.time(),'status':'running','runtime_dir':str(root),'usage':None,'cost':None,'session_before':session_id}
        log = None
        def emit(event):
            nonlocal native_session, resolved
            check()
            if event.get('type') == 'thread.started':
                native_session = event.get('thread_id'); on_session(native_session)
            if event.get('model'):
                resolved = event['model']; self._pin_model(task, binding, resolved)
            if event.get('type') == 'turn.completed':
                usage.update(event.get('usage') or {})
            log.write(json.dumps(event, ensure_ascii=False) + '\n'); log.flush()
            if event.get('type') != 'item.updated' and len(events) < 10000:
                events.append(event)
            on_event(event)
        try:
            with self.desk.store.connect(write=True) as db:db.execute('INSERT INTO agent_calls VALUES(?,?,?)',(call_id,task['id'],json.dumps(call)))
            log=(root / 'events.jsonl').open('w')
            p = Process(prefix + command, cwd=root, env=env, timeout=timeout, fence=check)
            with self.lock:
                self.processes[key] = p
            if provider == 'codex':
                data = self._codex(p, prompt, schema, instructions, root, binding, session_id, emit)
            else:
                data = self._claude(p, prompt, emit)
            check()
            if not isinstance(data, dict):
                raise AgentError('Agent 未交付结构化结果')
            (root / 'answer.json').write_text(json.dumps(data, ensure_ascii=False))
            call['status']='completed'
            return Result(data, provider, resolved or 'agent-default', native_session, usage, events, root, isolation)
        except AgentError as error:
            # CLI errors can include credential-bearing URLs; expose only safe diagnostics.
            message = str(error)
            for k, v in env.items():
                if any(word in k.upper() for word in ('KEY', 'TOKEN', 'SECRET')) and len(v) > 5:
                    message = message.replace(v, '[redacted]')
            message = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[redacted]', message)
            call.update(status='interrupted' if self.stopping else 'cancelled' if self.cancel_epochs.get(task['id'],0)!=epoch else 'failed',error=message[:1800])
            raise AgentError(message[:1800]) from None
        except BaseException as error:
            call.update(status='interrupted' if self.stopping or self.cancel_epochs.get(task['id'],0)!=epoch else 'failed',error=str(error)[:1800])
            raise
        finally:
            if log:log.close()
            if p:
                p.close()
            with self.lock:
                self.processes.pop(key, None)
            session_lock.release()
            call.update(ended_at=time.time(),model=resolved,session_after=native_session,usage=usage or None)
            with self.desk.store.connect(write=True) as db:db.execute('UPDATE agent_calls SET body=? WHERE id=?',(json.dumps(call,ensure_ascii=False),call_id))

    @staticmethod
    def _mcp(root, env, mcp):
        import shutil, sys
        from pitr.desk.research import proxy
        shutil.copy2(Path(proxy.__file__), root / 'proxy.py')
        env.update(PITR_RESEARCH_ENDPOINT=f'http://127.0.0.1:{mcp[0]}/', PITR_RESEARCH_CAPABILITY=mcp[1],
                   NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
        return {'command': str(Path(sys.executable).resolve()), 'args': [str(root / 'proxy.py')],
                'env_vars': ['PITR_RESEARCH_ENDPOINT', 'PITR_RESEARCH_CAPABILITY'], 'required': True,
                'startup_timeout_sec': 30, 'tool_timeout_sec': 600}

    @staticmethod
    def _codex(p, prompt, schema, instructions, root, binding, session_id, emit):
        text = []; usage = {};completed=[]
        names = {'agentMessage': 'agent_message', 'mcpToolCall': 'mcp_tool_call', 'webSearch': 'web_search',
                 'commandExecution': 'command_execution', 'fileChange': 'file_change'}
        def event(value):
            method = value.get('method', ''); params = value.get('params') or {}
            if method=='turn/completed':
                completed.append(params.get('turn',{}));return
            if 'id' in value and method:
                # The bridge only grants its own fixed tools. Never broaden permissions.
                p.send({'id': value['id'], 'error': {'code': -32601, 'message': 'PITR does not grant additional tool permissions'}})
                return
            if method in ('item/started', 'item/completed'):
                item = dict(params.get('item') or {})
                item['type'] = names.get(item.get('type'), item.get('type'))
                if method == 'item/completed' and item['type'] == 'agent_message':
                    text.append(item.get('text', ''))
                emit({'type': method.replace('/', '.'), 'item': item})
            elif method == 'thread/tokenUsage/updated':
                u = params.get('tokenUsage', {}).get('last', {})
                for src, dest in [('inputTokens','input_tokens'), ('cachedInputTokens','cached_input_tokens'), ('outputTokens','output_tokens'), ('reasoningOutputTokens','reasoning_output_tokens')]:
                    if src in u: usage[dest] = u[src]
            elif method == 'item/agentMessage/delta':
                emit({'type': 'item.updated', 'item': {'id': params.get('itemId'), 'type': 'agent_message', 'delta': params.get('delta', '')}})
            elif method == 'turn/plan/updated':
                emit({'type': 'item.updated', 'item': {'type': 'plan', 'items': params.get('plan', [])}})
            elif method == 'error':
                emit({'type': 'error', 'message': str(params.get('error', {}).get('message', 'Agent error'))})
        p.rpc('initialize', {'clientInfo': {'name': 'pitr', 'version': '1'}}, event)
        p.send({'method': 'initialized', 'params': {}})
        params = {'cwd': str(root), 'developerInstructions': instructions,
                  'approvalPolicy': 'never', 'sandbox': 'read-only'}
        model = binding.get('resolved_model') or binding.get('model')
        if model: params['model'] = model
        if session_id: params['threadId'] = session_id
        started = p.rpc('thread/resume' if session_id else 'thread/start', params, event)
        tid = started.get('thread', {}).get('id')
        if not tid: raise AgentError('Codex 未返回会话标识')
        emit({'type': 'thread.started', 'thread_id': tid, 'model': started.get('model') or model})
        turn = {'threadId': tid, 'input': [{'type': 'text', 'text': prompt}], 'outputSchema': schema}
        if model: turn['model'] = model
        if binding.get('reasoning'): turn['effort'] = binding['reasoning']
        turn_result=p.rpc('turn/start', turn, event)
        turn_id=turn_result.get('turn',{}).get('id')
        if turn_id:p.interrupt={'id':'pitr-interrupt','method':'turn/interrupt','params':{'threadId':tid,'turnId':turn_id}}
        emit({'type': 'turn.started'})
        while True:
            if completed:
                result=completed.pop(0)
                if result.get('status') != 'completed':
                    raise AgentError(str((result.get('error') or {}).get('message', 'Codex 本轮未完成')))
                emit({'type': 'turn.completed', 'usage': usage})
                try:
                    return json.loads(text[-1])
                except (ValueError, IndexError):
                    raise AgentError('Codex 未返回有效的结构化结果') from None
            event(p.receive())

    @staticmethod
    def _claude(p, prompt, emit):
        p.send({'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': prompt}]}})
        p.proc.stdin.close()
        while True:
            value = p.receive(); kind = value.get('type')
            if kind == 'system' and value.get('subtype') == 'init':
                emit({'type': 'thread.started', 'thread_id': value.get('session_id'), 'model': value.get('model')})
                emit({'type': 'turn.started'})
            elif kind == 'assistant':
                for block in value.get('message', {}).get('content', []):
                    if block.get('type') == 'text':
                        emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': block.get('text', '')}})
                    elif block.get('type') in ('tool_use', 'server_tool_use'):
                        emit({'type': 'item.started', 'item': {'type': 'mcp_tool_call', 'id': block.get('id'), 'name': block.get('name'), 'arguments': block.get('input')}})
                    elif block.get('type')=='web_search_tool_result':
                        content=block.get('content')
                        emit({'type':'item.completed','item':{'type':'mcp_tool_call','id':block.get('tool_use_id'),
                              'result':content,'is_error':isinstance(content,dict) and content.get('type')=='web_search_tool_result_error'}})
            elif kind=='stream_event':
                event=value.get('event',{})
                if event.get('type')=='content_block_delta' and event.get('delta',{}).get('type')=='text_delta':
                    emit({'type':'item.updated','item':{'type':'agent_message','id':str(event.get('index','')),'delta':event['delta'].get('text','')}})
            elif kind == 'user':
                for block in value.get('message', {}).get('content', []):
                    if block.get('type') == 'tool_result':
                        emit({'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'id': block.get('tool_use_id'), 'result': block.get('content'), 'is_error': block.get('is_error', False)}})
            elif kind == 'result':
                if value.get('is_error') or value.get('subtype') != 'success':
                    raise AgentError(str(value.get('result') or value.get('errors') or 'Claude Code 本轮未完成'))
                u = value.get('usage') or {}
                emit({'type': 'turn.completed', 'usage': {k: v for k, v in u.items() if isinstance(v, (int, float))}})
                output = value.get('structured_output')
                if output is None:
                    try: output = json.loads(value.get('result', ''))
                    except ValueError: raise AgentError('Claude Code 未返回有效的结构化结果') from None
                return output


def verified_searches(events):
    """A search description in model prose is never a search receipt."""
    starts = {e['item'].get('id'): e['item'] for e in events if e.get('type') == 'item.started' and e.get('item', {}).get('name') == 'WebSearch'}
    found = []
    for event in events:
        item = event.get('item', {})
        if event.get('type') != 'item.completed': continue
        if item.get('type') == 'web_search' and item.get('status') not in ('failed','inProgress','in_progress'): found.append(item)
        elif item.get('id') in starts and not item.get('is_error'):
            found.append({**starts[item['id']], 'result': item.get('result')})
    if not found:
        raise AgentError('公开搜索没有实际成功的检索事件；已保留记录，可以重试或提供原件')
    return found


def search_log(events):
    """Display only queries observable in successful native tool events."""
    return [json.dumps(item.get('action') or item.get('arguments') or {'query':'未暴露检索式','id':item.get('id')},ensure_ascii=False)
            for item in verified_searches(events)]
