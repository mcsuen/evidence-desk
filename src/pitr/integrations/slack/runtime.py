"""Durable transport runtime; no imports from Desk or other business modules."""
from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import base64
import io
import logging
import re
import threading
import time
import uuid
import httpx

from .contracts import AttachmentRef, InboundEvent, OutputFile, ReplyTarget, WorkflowUpdate, WorkflowRejected
from .files import Attachments, FileRejected, MAX_EVENT_FILES
from .settings import InstallationBusy, InstallationLock, REQUIRED_SCOPES, validate
from .store import Journal, encode, stable

# SDK exceptions may contain WebSocket ticket URLs. Expose curated diagnostics
# through the journal/status API instead of forwarding SDK request logs.
SDK_LOGGER = logging.getLogger('pitr.slack.sdk')
SDK_LOGGER.disabled = True


def error_code(error):
    """Never persist SDK request URLs, headers or exception reprs."""
    response = getattr(error, 'response', None)
    if response is not None:
        try:
            code = response.get('error', '')
            if re.fullmatch(r'[a-z_]{1,80}', code):
                return code
        except AttributeError:
            pass
    return type(error).__name__


class WorkflowContext:
    def __init__(self, runtime, adapter, event_id=None):
        self._runtime = runtime
        self.adapter = adapter
        self.event_id = event_id

    def publish(self, key: str, update: WorkflowUpdate, *, event_id=None):
        self._runtime.publish(event_id or self.event_id, self.adapter + ':' + key, update)

    def has_update(self, key):
        with self._runtime.journal.connect() as db:
            return db.execute('SELECT 1 FROM outbox WHERE id=?', (self.adapter + ':' + key + ':message',)).fetchone() is not None

    def prepare(self, factory):
        """Persist the exact business request before idempotent enqueue/replay."""
        journal = self._runtime.journal
        with journal.connect() as db:
            row = db.execute('SELECT body FROM prepared WHERE event_id=?', (self.event_id,)).fetchone()
        if row:
            return json.loads(row['body'])
        body = factory()
        with journal.connect(write=True) as db:
            db.execute('INSERT OR IGNORE INTO prepared VALUES(?,?)', (self.event_id, encode(body)))
            return json.loads(db.execute('SELECT body FROM prepared WHERE event_id=?', (self.event_id,)).fetchone()['body'])

    def bind(self, task_id):
        with self._runtime.journal.connect(write=True) as db:
            db.execute('INSERT OR IGNORE INTO bindings VALUES(?,?,?)', (self.adapter, task_id, self.event_id))

    def bindings(self):
        with self._runtime.journal.connect() as db:
            return [dict(row) for row in db.execute('SELECT task_id,event_id FROM bindings WHERE adapter=?', (self.adapter,))]

    def action(self, action_id, metadata, *, event_id=None):
        return self._runtime.register_action(self.adapter, event_id or self.event_id, action_id, metadata)

    def attachment_bytes(self, attachment_id):
        return self._runtime.attachments.read(self.event_id, attachment_id)


class SlackRuntime:
    def __init__(self, root, settings, save_settings=None, *, client=None, client_factory=None, socket_factory=None, http_factory=None):
        self.journal = Journal(root)
        self.settings = settings
        self.save_settings = save_settings
        self.client = client
        self.client_factory = client_factory
        self.socket_factory = socket_factory
        self.socket = None
        self.installation_lock = None
        self.adapters = {}
        self.routes = {}
        self.default_adapter = None
        self.stop_event = threading.Event()
        self.thread = None
        self.interactions = None
        self._lifecycle = threading.RLock()
        self._pump_lock = threading.Lock()
        self._status_lock = threading.RLock()
        self._channel_next = {}
        self._method_next = {}
        self.state = 'not_configured'
        self.error = None
        self.bot_user = None
        self._config_fingerprint = None
        self._was_connected = False
        self.retry_stop = threading.Event()
        self.retry_thread = None
        self.attachments = Attachments(self.journal, settings, lambda: self.client, http_factory)

    def register(self, adapter, *, default=False):
        if adapter.name in self.adapters:
            raise ValueError('适配器名称重复')
        for command in adapter.commands:
            if command.lower() in self.routes:
                raise ValueError('命令已注册：' + command)
        self.adapters[adapter.name] = adapter
        self.routes.update({c.lower(): adapter.name for c in adapter.commands})
        if default or self.default_adapter is None:
            self.default_adapter = adapter.name

    def allowed(self, target):
        cfg = self.settings()
        return bool(cfg.get('slack_team_id') and cfg.get('slack_user_id')
                    and target.team_id == cfg['slack_team_id'] and target.user_id == cfg['slack_user_id']
                    and (target.channel_id.startswith('D') or target.channel_id in cfg.get('slack_channel_ids', [])))

    def _event(self, event_id):
        with self.journal.connect() as db:
            row = db.execute('SELECT * FROM inbox WHERE id=?', (event_id,)).fetchone()
        if not row:
            raise KeyError('接入事件不存在')
        return row, InboundEvent.model_validate_json(row['event'])

    def register_action(self, adapter, event_id, action_id, metadata):
        _, event = self._event(event_id)
        token = 'action_' + stable([event_id, adapter, action_id, metadata])[:40]
        with self.journal.connect(write=True) as db:
            db.execute('INSERT OR IGNORE INTO actions VALUES(?,?,?,?,?,?,?)',
                       (token, adapter, event_id, action_id, encode(event.target), encode(metadata), time.time() + 7 * 86400))
        return token

    def _action(self, token, team, user, channel=None):
        with self.journal.connect(timeout=.25) as db:
            row = db.execute('SELECT * FROM actions WHERE id=?', (token,)).fetchone()
        if not row or row['expires'] < time.time():
            return None
        target = ReplyTarget.model_validate_json(row['target'])
        if (team != target.team_id or user != target.user_id
                or (channel is not None and channel != target.channel_id) or not self.allowed(target)):
            return None
        return row

    def normalize(self, request):
        """Copy only the fields workflows need. Drop response_url, tokens and trigger_id."""
        body = request.payload
        if request.type == 'events_api':
            payload = body.get('event', {})
            kind = payload.get('type')
            if kind not in ('message', 'app_mention') or payload.get('bot_id') or payload.get('user') == self.bot_user:
                return None
            if payload.get('subtype') in ('message_changed','message_deleted'):
                message = payload.get('message') or payload.get('previous_message') or {}
                message_ts = payload.get('deleted_ts') or message.get('ts')
                # Only revisit an originally owner-directed, durably accepted message.
                with self.journal.connect(timeout=.25) as db:
                    original = db.execute("SELECT adapter,event FROM inbox WHERE json_extract(event,'$.target.team_id')=? AND json_extract(event,'$.target.channel_id')=? AND json_extract(event,'$.metadata.message_ts')=? AND json_extract(event,'$.kind') IN ('message','mention') LIMIT 1",
                        (body.get('team_id',''),payload.get('channel',''),message_ts)).fetchone()
                if not original:return None
                original_event=InboundEvent.model_validate_json(original['event'])
                if not self.allowed(original_event.target) or message.get('bot_id') or (message.get('user') and message['user']!=original_event.target.user_id):return None
                eid='event:'+original_event.target.team_id+':'+(body.get('event_id') or stable([payload.get('subtype'),message_ts,message.get('edited')]))
                refs=[AttachmentRef(id='attachment_'+stable([eid,f.get('id')])[:40],file_id=f.get('id','')) for f in message.get('files',[])[:MAX_EVENT_FILES+1]]
                event=InboundEvent(id=eid,kind='deleted' if payload['subtype']=='message_deleted' else 'changed',
                    target=original_event.target,text=message.get('text',''),attachments=refs,
                    metadata={'message_ts':message_ts,'original_event_id':original_event.id,'files_present':'files' in message})
                return original['adapter'],event
            if payload.get('subtype') not in (None, 'file_share'):
                return None
            if kind == 'message' and payload.get('channel_type') != 'im':
                return None
            target = ReplyTarget(team_id=body.get('team_id', ''), user_id=payload.get('user', ''),
                                 channel_id=payload.get('channel', ''), thread_ts=payload.get('thread_ts') or payload.get('ts'))
            if not target.thread_ts or not self.allowed(target):
                return None
            eid = 'event:' + target.team_id + ':' + (body.get('event_id') or stable([target.channel_id, payload.get('ts')]))
            text = payload.get('text', '')
            if kind == 'app_mention' and self.bot_user:
                text = re.sub(r'^\s*<@' + re.escape(self.bot_user) + r'>\s*', '', text)
            refs = [AttachmentRef(id='attachment_' + stable([eid, f.get('id')])[:40], file_id=f.get('id', ''))
                    for f in payload.get('files', [])[:MAX_EVENT_FILES + 1]]
            event = InboundEvent(id=eid, kind='mention' if kind == 'app_mention' else 'message', target=target, text=text, attachments=refs, metadata={'message_ts':payload.get('ts','')})
            return self._route(event), event
        if request.type == 'slash_commands':
            if body.get('command') != '/research':
                return None
            target = ReplyTarget(team_id=body.get('team_id', ''), user_id=body.get('user_id', ''), channel_id=body.get('channel_id', ''))
            if not self.allowed(target):
                return None
            eid = 'command:' + stable([target.team_id, body.get('trigger_id') or request.envelope_id])
            target.root_delivery_id = 'receipt:' + eid
            event = InboundEvent(id=eid, kind='command', target=target, text=body.get('text', ''))
            return self._route(event), event
        if request.type == 'interactive':
            team = body.get('team', {}).get('id', '')
            user = body.get('user', {}).get('id', '')
            if body.get('type') == 'block_actions':
                action = (body.get('actions') or [{}])[0]
                if action.get('action_id') != 'pitr_action':
                    return None
                binding = self._action(action.get('value'), team, user, body.get('channel', {}).get('id', ''))
                if not binding:
                    return None
                eid = 'action:' + stable([team, action.get('value'), action.get('action_ts') or request.envelope_id])
                event = InboundEvent(id=eid, kind='action', target=ReplyTarget.model_validate_json(binding['target']),
                                     action_id=binding['action_id'], metadata=json.loads(binding['metadata']))
            elif body.get('type') == 'view_submission' and body.get('view', {}).get('callback_id') == 'pitr_submit':
                view = body['view']
                binding = self._action(view.get('private_metadata'), team, user)
                if not binding:
                    return None
                event = InboundEvent(id='submission:' + team + ':' + view['id'], kind='submission',
                                     target=ReplyTarget.model_validate_json(binding['target']), action_id=binding['action_id'],
                                     metadata=json.loads(binding['metadata']), values=view.get('state', {}).get('values', {}))
            else:
                return None
            return binding['adapter'], event
        return None

    def _route(self, event):
        verb = event.text.strip().split(maxsplit=1)
        return self.routes.get(verb[0].lower() if verb else '', self.default_adapter)

    def receive(self, event, adapter=None):
        if not self.allowed(event.target):
            return False
        adapter = adapter or self._route(event)
        if adapter not in self.adapters:
            raise ValueError('没有可用的工作流适配器')
        # Bound the ingress lock wait well below Slack's three-second deadline.
        with self.journal.connect(write=True, timeout=.25) as db:
            inserted = db.execute('INSERT OR IGNORE INTO inbox(id,adapter,event,created) VALUES(?,?,?,?)',
                                  (event.id, adapter, encode(event), time.time())).rowcount == 1
            if inserted and event.kind == 'command':
                target = event.target.model_copy(update={'root_delivery_id': None})
                self._outgoing(db, event.target.root_delivery_id, event.id, target,
                               {'kind': 'message', 'text': '请求已接收，处理结果将在此线程更新。', 'blocks': None})
        return inserted

    def handle_socket_request(self, client, request):
        """Production Socket Mode listener; ACK only after authorization + commit."""
        from slack_sdk.socket_mode.response import SocketModeResponse
        try:
            normalized = self.normalize(request)
            if normalized is None:
                payload = {'text': '此入口未获授权或交互已失效。', 'response_type': 'ephemeral'} if request.type == 'slash_commands' else None
                if request.type == 'interactive' and request.payload.get('type') == 'view_submission':
                    payload = {'response_action': 'update', 'view': {'type': 'modal', 'title': {'type': 'plain_text', 'text': '审核已失效'},
                               'close': {'type': 'plain_text', 'text': '关闭'}, 'blocks': [{'type': 'section', 'text': {'type': 'plain_text', 'text': '审核入口已过期或未获授权，请返回原线程重新打开。'}}]}}
                client.send_socket_mode_response(SocketModeResponse(request.envelope_id, payload=payload))
                return
            adapter, event = normalized
            if event.kind == 'submission':
                errors = self.adapters[adapter].validate_submission(event)
                if errors:
                    client.send_socket_mode_response(SocketModeResponse(request.envelope_id, payload={'response_action': 'errors', 'errors': errors}))
                    return
            inserted = self.receive(event, adapter)
            # A failed commit exits before this call so Slack can retry.
            client.send_socket_mode_response(SocketModeResponse(request.envelope_id))
            if inserted:
                if event.kind == 'action' and self.interactions:
                    self.interactions.submit(self.open_interaction, event.id, request.payload.get('trigger_id'), time.time())
                self.journal.set_state('last_received_at', time.time())
        except Exception as error:
            self.error = error_code(error)
            # Do not ACK an uncommitted event, and do not log the incoming body.

    def _outgoing(self, db, key, event_id, target, payload):
        db.execute('INSERT OR IGNORE INTO outbox(id,event_id,target,payload,created) VALUES(?,?,?,?,?)',
                   (key, event_id, encode(target), encode(payload), time.time()))

    def publish(self, event_id, key, update):
        _, event = self._event(event_id)
        if not self.allowed(event.target):
            return
        with self.journal.connect() as db:
            if db.execute('SELECT 1 FROM outbox WHERE id=?', (key + ':message',)).fetchone():
                return  # The entire update is inserted in one transaction below.
        # Long messages remain complete as a file; the on-screen summary is bounded.
        files = list(update.files)
        text = update.text
        if len(text) > 12000:
            files.insert(0, OutputFile(filename='message.txt', title='完整消息', content=text))
            text = text[:2500] + '\n完整内容见附件。'
        with self.journal.connect(write=True) as db:
            self._outgoing(db, key + ':message', event_id, event.target,
                           {'kind': 'message', 'text': text, 'blocks': update.blocks, 'workflow_status': update.status})
            for index, file in enumerate(files):
                self._outgoing(db, key + ':file:' + str(index), event_id, event.target,
                               {'kind': 'file', **file.model_dump()})

    @contextmanager
    def lease(self, table, row):
        done = threading.Event()
        def renew():
            while not done.wait(15):
                with self.journal.connect(write=True) as db:
                    db.execute(f'UPDATE {table} SET lease=? WHERE id=? AND owner=?', (time.time() + 120, row['id'], row['owner']))
        thread = threading.Thread(target=renew, daemon=True, name='slack-lease')
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join(timeout=2)

    def process_one(self):
        row = self.journal.claim('inbox')
        if not row:
            return False
        event = InboundEvent.model_validate_json(row['event'])
        if not self.allowed(event.target):
            self.journal.finish('inbox', row, 'rejected', error='authorization_changed')
            return True
        with self.lease('inbox', row):
            try:
                if len(event.attachments) > MAX_EVENT_FILES:
                    raise FileRejected('每条消息最多接收 10 个文件')
                resolved = []
                for ref in event.attachments:
                    if self.thread and self.stop_event.is_set():
                        self.journal.finish('inbox', row, 'pending')
                        return True
                    try:
                        resolved.append(self.attachments.download(event.id, ref))
                    except Exception as error:
                        if self._retryable_read(error) and row['attempts'] < 5:
                            raise
                        ref = ref.model_copy(update={'status': 'failed', 'error': str(error) if isinstance(error, FileRejected) else error_code(error)})
                        self.attachments.save(event.id, ref)
                        resolved.append(ref)
                event = event.model_copy(update={'attachments': resolved})
                if not self.allowed(event.target):
                    self.journal.finish('inbox', row, 'rejected', error='authorization_changed')
                    return True
                context = WorkflowContext(self, row['adapter'], event.id)
                self.adapters[row['adapter']].handle(event, context)
                self.journal.finish('inbox', row, 'processed')
                self.journal.set_state('last_processed_at', time.time())
            except Exception as error:
                retry = self._retryable_read(error) and row['attempts'] < 5
                code = error_code(error)
                self.journal.finish('inbox', row, 'pending' if retry else 'failed', error=code,
                                    delay=self.retry_delay(error, row['attempts']))
                if not retry:
                    self.publish(event.id, 'error:' + event.id, WorkflowUpdate(text='请求未完成：' + (str(error) if isinstance(error, (FileRejected, WorkflowRejected)) else code), status='failed'))
        return True

    @staticmethod
    def _retryable_read(error):
        if isinstance(error, (httpx.TransportError, TimeoutError, ConnectionError)):
            return True
        response = getattr(error, 'response', None)
        return response is not None and (getattr(response, 'status_code', 0) == 429 or getattr(response, 'status_code', 0) >= 500)

    @staticmethod
    def retry_delay(error, attempt):
        try:
            retry_after = float(next((v for k,v in error.response.headers.items() if k.lower()=='retry-after'), '0'))
        except (AttributeError, TypeError, ValueError):
            retry_after = 0
        return max(retry_after, min(300, 2 ** min(attempt, 8)))

    def open_interaction(self, event_id, trigger_id, received_at):
        with self.journal.connect(write=True) as db:
            row = db.execute('SELECT * FROM inbox WHERE id=?', (event_id,)).fetchone()
            if not row or row['status'] != 'pending':
                return
            owner = uuid.uuid4().hex
            db.execute("UPDATE inbox SET status='processing',owner=?,lease=? WHERE id=?", (owner, time.time() + 120, event_id))
            row = {**dict(row), 'owner': owner}
        event = InboundEvent.model_validate_json(row['event'])
        try:
            if not self.allowed(event.target):
                self.journal.finish('inbox', row, 'rejected', error='authorization_changed')
                return
            if not trigger_id or time.time() - received_at > 2.5:
                raise TimeoutError('expired_trigger')
            view = self.adapters[row['adapter']].open_modal(event, WorkflowContext(self, row['adapter'], event_id))
            token = self.register_action(row['adapter'], event_id, view.action_id, view.metadata)
            self.client.views_open(trigger_id=trigger_id, view={
                'type': 'modal', 'callback_id': 'pitr_submit', 'private_metadata': token,
                'title': {'type': 'plain_text', 'text': view.title[:24]},
                'submit': {'type': 'plain_text', 'text': view.submit[:24]}, 'blocks': view.blocks})
            self.journal.finish('inbox', row, 'processed')
        except Exception as error:
            rejected = isinstance(error, WorkflowRejected)
            self.journal.finish('inbox', row, 'rejected' if rejected else 'failed', error=error_code(error))
            message = str(error) if rejected else '操作界面未打开，请重新点击按钮。'
            self.publish(event_id, 'modal-error:' + event_id, WorkflowUpdate(text=message))

    def _expire_actions(self):
        with self.journal.connect() as db:
            rows = db.execute("SELECT id FROM inbox WHERE json_extract(event,'$.kind')='action' AND ((status='pending' AND created<?) OR (status='processing' AND lease<?))", (time.time() - 5, time.time())).fetchall()
        for row in rows:
            self.publish(row['id'], 'modal-error:' + row['id'], WorkflowUpdate(text='操作界面已过期，请重新点击按钮。'))
            with self.journal.connect(write=True) as db:
                db.execute("UPDATE inbox SET status='failed',error='expired_trigger' WHERE id=?", (row['id'],))

    def drain_one(self):
        if not self.client:
            return False
        row = self.journal.claim('outbox')
        if not row:
            return False
        target = ReplyTarget.model_validate_json(row['target'])
        payload = json.loads(row['payload'])
        if not self.allowed(target):
            self.journal.finish('outbox', row, 'failed', error='authorization_changed')
            return True
        method = 'files_upload_v2' if payload['kind'] == 'file' else 'chat_postMessage'
        if target.root_delivery_id:
            with self.journal.connect() as db:
                root = db.execute('SELECT status,message_ts FROM outbox WHERE id=?', (target.root_delivery_id,)).fetchone()
            if not root or root['status'] != 'sent' or not root['message_ts']:
                self.journal.finish('outbox', row, 'pending', error='waiting_for_thread', delay=2)
                return True
            target.thread_ts = root['message_ts']
        wait_until = max(self._channel_next.get(target.channel_id, 0), self._method_next.get(method, 0))
        if wait_until > time.time():
            self.journal.finish('outbox', row, 'pending', delay=wait_until - time.time())
            return True
        with self.lease('outbox', row):
            row['attempts'] += 1
            with self.journal.connect(write=True) as db:
                db.execute('UPDATE outbox SET attempts=? WHERE id=? AND owner=?', (row['attempts'], row['id'], row['owner']))
            try:
                args = {'channel': target.channel_id}
                if target.thread_ts:
                    args['thread_ts'] = target.thread_ts
                if payload['kind'] == 'file':
                    content = {'content': payload['content']} if payload.get('content') is not None else {'file': io.BytesIO(base64.b64decode(payload['data_base64'], validate=True))}
                    response = self.client.files_upload_v2(**args, filename=payload['filename'], title=payload['title'][:200], **content)
                else:
                    response = self.client.chat_postMessage(**args, text=payload['text'], blocks=payload.get('blocks'),
                        mrkdwn=False, unfurl_links=False, unfurl_media=False, client_msg_id=str(uuid.UUID(stable(row['id'])[:32])))
                if not response.get('ok', True):
                    raise RuntimeError('unconfirmed_send')
                stamp = response.get('ts')
                if row['id'].startswith('receipt:') and not stamp:
                    raise RuntimeError('missing_receipt_timestamp')
                self.journal.finish('outbox', row, 'sent', message_ts=stamp)
                self.journal.set_state('last_sent_at', time.time())
                self._channel_next[target.channel_id] = time.time() + 1
            except Exception as error:
                code = error_code(error)
                response = getattr(error, 'response', None)
                status_code = getattr(response, 'status_code', 0)
                limited = status_code == 429 or code == 'ratelimited'
                safe_retry = limited or isinstance(error, (httpx.ConnectError, ConnectionRefusedError))
                delay = self.retry_delay(error, row['attempts'])
                if limited:
                    self._method_next[method] = time.time() + delay
                if safe_retry and row['attempts'] < 12:
                    status = 'pending'
                elif safe_retry or (response is not None and 0 < status_code < 500):
                    status = 'failed'
                else:
                    status = 'delivery_unknown'
                self.journal.finish('outbox', row, status, error=code, delay=delay)
                self.error = code
        return True

    def pump(self):
        if not self._pump_lock.acquire(blocking=False):
            return
        try:
            self._expire_actions()
            for _ in range(10):
                if self.thread and self.stop_event.is_set():
                    return
                if not self.process_one():
                    break
            for name, adapter in self.adapters.items():
                try:
                    adapter.poll(WorkflowContext(self, name))
                except Exception as error:
                    self.error = error_code(error)
            for _ in range(20):
                if self.thread and self.stop_event.is_set():
                    return
                if not self.drain_one():
                    break
        finally:
            self._pump_lock.release()

    def check(self):
        cfg = self.settings()
        validate(cfg)
        missing = [k for k in ('slack_app_token', 'slack_bot_token', 'slack_team_id', 'slack_user_id') if not cfg.get(k)]
        if missing:
            return {'ok': False, 'missing': missing, 'channel_count': len(cfg.get('slack_channel_ids', []))}
        from slack_sdk import WebClient
        client = self.client_factory(cfg) if self.client_factory else WebClient(token=cfg['slack_bot_token'], timeout=10, retry_handlers=[], logger=SDK_LOGGER)
        try:
            identity = client.auth_test()
            if identity['team_id'] != cfg['slack_team_id']:
                raise ValueError('Bot 所属工作区与配置不一致')
            scopes = set(next((v for k,v in getattr(identity,'headers',{}).items() if k.lower()=='x-oauth-scopes'), '').split(',')) - {''}
            missing_scopes = sorted(REQUIRED_SCOPES - scopes) if scopes else []
            result = {'ok': not missing_scopes, 'bot_user_id': identity['user_id'], 'team_id': identity['team_id'],
                      'missing_scopes': missing_scopes, 'scopes_verified': bool(scopes),
                      'channel_count': len(cfg.get('slack_channel_ids', [])), 'checked_at': time.time()}
        except ValueError:
            raise
        except Exception as error:
            result = {'ok': False, 'error': error_code(error), 'checked_at': time.time()}
        self.journal.set_state('diagnostic', result)
        return result

    def start(self, *, enable=True):
        with self._lifecycle:
            if not enable and self.retry_stop.is_set() and threading.current_thread() is self.retry_thread:
                return self.status()
            if enable:
                self.retry_stop.clear()
            if self.thread and self.thread.is_alive():
                return self.status()
            cfg = self.settings()
            validate(cfg)
            if not all(cfg.get(k) for k in ('slack_app_token', 'slack_bot_token', 'slack_team_id', 'slack_user_id')):
                raise ValueError('请先保存 App Token、Bot Token、工作区 ID 和本人 ID')
            if enable and self.save_settings:
                self.save_settings({'slack_enabled': True})
            from slack_sdk import WebClient
            from slack_sdk.socket_mode import SocketModeClient
            self.state = 'connecting'
            self.error = None
            try:
                self.client = self.client or (self.client_factory(cfg) if self.client_factory else WebClient(token=cfg['slack_bot_token'], timeout=15, retry_handlers=[], logger=SDK_LOGGER))
                identity = self.client.auth_test()
                if identity['team_id'] != cfg['slack_team_id']:
                    raise ValueError('Bot 所属工作区与配置不一致')
                scopes = set(next((v for k,v in getattr(identity, 'headers', {}).items() if k.lower()=='x-oauth-scopes'), '').split(',')) - {''}
                if scopes and REQUIRED_SCOPES - scopes:
                    raise ValueError('应用缺少权限，请更新 manifest 后重新安装：' + ', '.join(sorted(REQUIRED_SCOPES - scopes)))
                self.bot_user = identity['user_id']
                self.installation_lock = InstallationLock(identity['team_id'], self.bot_user)
                self.installation_lock.acquire()
                self.interactions = ThreadPoolExecutor(max_workers=2, thread_name_prefix='slack-interaction')
                factory = self.socket_factory or SocketModeClient
                self.socket = factory(app_token=cfg['slack_app_token'], web_client=self.client,
                                      auto_reconnect_enabled=True, trace_enabled=False, all_message_trace_enabled=False, logger=SDK_LOGGER)
                self.socket.socket_mode_request_listeners.append(self.handle_socket_request)
                self.socket.connect()
                self._config_fingerprint = stable({k: cfg.get(k) for k in ('slack_app_token', 'slack_bot_token', 'slack_team_id', 'slack_user_id', 'slack_channel_ids')})
                self.stop_event.clear()
                self.thread = threading.Thread(target=self._loop, daemon=True, name='slack-durable-worker')
                self.thread.start()
                return self.status()
            except Exception as error:
                self._close_transport()
                self.client = None
                self.state = 'failed'
                self.error = error_code(error)
                if isinstance(error, ValueError) and not isinstance(error, InstallationBusy):
                    raise
                if self.settings().get('slack_enabled') and self.error not in ('invalid_auth','token_revoked','account_inactive','missing_scope','not_allowed_token_type','not_authed'):
                    self._schedule_reconnect()
                raise ValueError('Slack 连接失败：' + self.error) from None

    def _schedule_reconnect(self):
        self.state = 'reconnecting'
        if self.retry_thread and self.retry_thread.is_alive():
            return
        def retry():
            delay = 5
            while not self.retry_stop.wait(delay):
                if not self.settings().get('slack_enabled'):
                    return
                try:
                    self.start(enable=False)
                    if self.thread:
                        return
                except ValueError:
                    if self.error in ('ValueError','invalid_auth','token_revoked','account_inactive','missing_scope','not_allowed_token_type','not_authed'):
                        return
                delay = min(60, delay * 2)
        self.retry_thread = threading.Thread(target=retry, daemon=True, name='slack-connect-retry')
        self.retry_thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.status()
                self.pump()
            except Exception as error:
                self.error = error_code(error)
            self.stop_event.wait(.5)

    def _close_transport(self):
        if self.socket:
            self.socket.close()
            self.socket = None
        if self.interactions:
            self.interactions.shutdown(wait=True, cancel_futures=True)
            self.interactions = None
        if self.installation_lock:
            self.installation_lock.release()
            self.installation_lock = None

    def stop(self, *, disable=True):
        self.retry_stop.set()
        with self._lifecycle:
            if disable and self.save_settings:
                self.save_settings({'slack_enabled': False})
            self.stop_event.set()
            # Active file requests are bounded; do not let a stopped worker use
            # credentials from a later connection or release its installation lock.
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=45)
                if self.thread.is_alive():
                    self.state = 'stopping'
                    raise ValueError('正在结束当前文件传输，请稍后重试断开')
            self._close_transport()
            self.thread = None
            self.client = None
            self.state = 'disconnected'
            self._was_connected = False

    def status(self):
        with self._status_lock:
            return self._status()

    def _status(self):
        cfg = self.settings()
        connected = bool(self.socket and self.socket.is_connected())
        if connected:
            if not self._was_connected:
                self.journal.set_state('last_connected_at', time.time())
                self.journal.set_state('connection_count', self.journal.state('connection_count', 0) + 1)
            self.state = 'connected'
        elif self.socket:
            self.state = 'reconnecting'
        elif self.state == 'not_configured' and all(cfg.get(k) for k in ('slack_app_token', 'slack_bot_token', 'slack_team_id', 'slack_user_id')):
            self.state = 'disconnected'
        self._was_connected = connected
        with self.journal.connect() as db:
            counts = {table: {r['status']: r['n'] for r in db.execute(f'SELECT status,COUNT(*) n FROM {table} GROUP BY status')} for table in ('inbox', 'outbox')}
        return {'state': self.state, 'connected': connected, 'enabled': bool(cfg.get('slack_enabled')), 'error': self.error,
                **counts, 'diagnostic': self.journal.state('diagnostic'),
                'last_connected_at': self.journal.state('last_connected_at'), 'last_received_at': self.journal.state('last_received_at'),
                'last_processed_at': self.journal.state('last_processed_at'), 'last_sent_at': self.journal.state('last_sent_at'),
                'connection_count': self.journal.state('connection_count', 0), 'live_checks': self.journal.state('live_checks', {}),
                'live_approval_test': 'owner_recorded_passed' if self.journal.state('live_checks', {}).get('approval', {}).get('status') == 'passed' else 'not_verified'}

    def test_message(self, channel=None):
        if not self.socket or not self.socket.is_connected():
            raise ValueError('请先连接 Slack')
        cfg = self.settings()
        if channel and channel not in cfg.get('slack_channel_ids', []):
            raise ValueError('测试频道不在白名单中')
        if not channel:
            try:
                channel = self.client.conversations_open(users=cfg['slack_user_id'])['channel']['id']
            except Exception as error:
                raise ValueError('无法打开本人私信：' + error_code(error)) from None
        eid = 'test:' + uuid.uuid4().hex
        event = InboundEvent(id=eid, kind='command', target=ReplyTarget(team_id=cfg['slack_team_id'], user_id=cfg['slack_user_id'],
                           channel_id=channel, root_delivery_id='receipt:' + eid), text='help')
        self.receive(event)
        return {'event_id': eid, 'status': 'queued'}
