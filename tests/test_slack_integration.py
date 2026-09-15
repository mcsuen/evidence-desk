"""Transport contracts through the production Socket Mode request listener.

All clients are offline fakes. These tests are not live Slack acceptance.
"""
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.web.slack_response import SlackResponse

from pitr.integrations.slack import AttachmentRef, InboundEvent, ReplyTarget, WorkflowModal, WorkflowUpdate, OutputFile
from pitr.integrations.slack.runtime import SlackRuntime, WorkflowContext
from pitr.integrations.slack.settings import MANIFEST, SettingsFile, InstallationLock
from pitr.integrations.slack.files import MAX_FILE_BYTES

TEAM, USER, BOT, DM, CHANNEL = 'T1234567', 'U1234567', 'U7654321', 'D1234567', 'C1234567'


class Echo:
    name = 'echo'
    commands = ('echo', 'help')

    def __init__(self):
        self.events = []
        self.contents = []

    def handle(self, event, context):
        self.events.append(event)
        for ref in event.attachments:
            if ref.status == 'ready':
                self.contents.append(context.attachment_bytes(ref.id))
        context.bind('job:' + event.id)
        context.publish(event.id + ':answer', WorkflowUpdate(text=event.text or 'received'))

    def open_modal(self, event, context):
        return WorkflowModal(title='Echo review', action_id='echo_submit', metadata=event.metadata,
                             blocks=[{'type': 'input', 'block_id': 'reason', 'label': {'type': 'plain_text', 'text': 'Reason'},
                                      'element': {'type': 'plain_text_input', 'action_id': 'value'}}])

    def validate_submission(self, event):
        return {} if event.values.get('reason', {}).get('value', {}).get('value') else {'reason': 'Required'}

    def poll(self, context):
        pass


class Client:
    def __init__(self):
        self.messages, self.files, self.views = [], [], []
        self.error = None
        self.file_error = None
        self.info = {'id': 'F1234567', 'name': 'sample.txt', 'mimetype': 'text/plain', 'size': 5,
                     'url_private': 'https://files.slack.com/files-pri/T1234567-F1234567/sample.txt'}

    def auth_test(self):
        return {'ok': True, 'team_id': TEAM, 'user_id': BOT}

    def conversations_open(self, **kwargs):
        return {'channel': {'id': DM}}

    def chat_postMessage(self, **kwargs):
        if self.error:
            raise self.error
        self.messages.append(kwargs)
        return {'ok': True, 'ts': '900.' + str(len(self.messages))}

    def files_upload_v2(self, **kwargs):
        if self.file_error:
            raise self.file_error
        self.files.append(kwargs)
        return {'ok': True, 'files': [{'id': 'FOUT123'}]}

    def files_info(self, **kwargs):
        return {'ok': True, 'file': self.info}

    def views_open(self, **kwargs):
        self.views.append(kwargs)
        return {'ok': True, 'view': {'id': 'V1234567'}}


class Socket:
    def __init__(self, **kwargs):
        self.socket_mode_request_listeners = []
        self.responses = []
        self.connected = False
        self.observe_ack = None

    def connect(self):
        self.connected = True

    def close(self):
        self.connected = False

    def is_connected(self):
        return self.connected

    def send_socket_mode_response(self, response):
        if self.observe_ack:
            self.observe_ack()
        self.responses.append(response)


@pytest.fixture
def config():
    return {'slack_team_id': TEAM, 'slack_user_id': USER, 'slack_channel_ids': [CHANNEL],
            'slack_app_token': 'xapp-offline', 'slack_bot_token': 'xoxb-offline'}


@pytest.fixture
def runtime(tmp_path, config):
    result = SlackRuntime(tmp_path / 'slack', lambda: config, client=Client(), socket_factory=Socket,
                          http_factory=lambda: httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'hello'))))
    result.register(Echo(), default=True)
    result.bot_user = BOT
    return result


def event(key='e1', *, channel=DM, user=USER, team=TEAM, thread='100.1', text='echo hello'):
    return InboundEvent(id=key, kind='message', text=text, target=ReplyTarget(team_id=team, user_id=user, channel_id=channel, thread_ts=thread))


def request(kind='events_api', *, user=USER, team=TEAM, channel=DM, ts='100.1', eid='Ev123', subtype=None, text='echo hello', files=None, mention=False, thread=None):
    payload = {'team_id': team, 'event_id': eid, 'event': {'type': 'app_mention' if mention else 'message', 'user': user,
               'channel': channel, 'channel_type': 'im' if channel == DM else 'channel', 'text': text, 'ts': ts}}
    if subtype:
        payload['event']['subtype'] = subtype
    if files:
        payload['event']['files'] = files
    if thread:
        payload['event']['thread_ts'] = thread
    return SocketModeRequest(kind, 'envelope:' + eid, payload)


def drain(runtime):
    for _ in range(25):
        runtime._channel_next.clear()
        runtime._method_next.clear()
        with runtime.journal.connect(write=True) as db:
            db.execute("UPDATE outbox SET next_at=0 WHERE status='pending'")
        if not runtime.drain_one():
            break


def test_socket_ack_follows_commit_and_precedes_work(runtime):
    socket = Socket()
    def observe():
        with runtime.journal.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
        assert runtime.adapters['echo'].events == []
    socket.observe_ack = observe
    began = time.monotonic()
    runtime.handle_socket_request(socket, request())
    assert time.monotonic() - began < 3
    assert len(socket.responses) == 1
    # A redelivery with a new envelope retains the logical event ID.
    again = request(); again.envelope_id = 'retry-envelope'
    runtime.handle_socket_request(socket, again)
    runtime.pump()
    assert len(socket.responses) == 2
    assert len(runtime.adapters['echo'].events) == 1
    assert runtime.client.messages[0]['thread_ts'] == '100.1'


def test_socket_does_not_ack_uncommitted_event(runtime):
    socket = Socket()
    with runtime.journal.connect(write=True) as db:
        db.execute("INSERT INTO state VALUES('locked','true')")
        began = time.monotonic()
        runtime.handle_socket_request(socket, request())
        assert time.monotonic() - began < 1
    assert socket.responses == []
    runtime.handle_socket_request(socket, request())
    assert len(socket.responses) == 1


@pytest.mark.parametrize('changes', [dict(user='UOTHER12'), dict(team='TOTHER12'), dict(channel='COTHER12', mention=True), dict(channel=CHANNEL), dict(subtype='message_changed'), dict(subtype='bot_message'), dict(user=BOT)])
def test_unauthorized_and_non_trigger_events_are_ignored(runtime, changes):
    socket = Socket()
    runtime.handle_socket_request(socket, request(**changes))
    runtime.pump()
    assert not runtime.adapters['echo'].events
    assert not runtime.client.messages


def test_mentions_threads_and_command_receipt(runtime):
    socket = Socket()
    runtime.handle_socket_request(socket, request(channel=CHANNEL, mention=True, thread='20.1', text='<@' + BOT + '> echo one'))
    runtime.handle_socket_request(socket, request(eid='Ev456', channel=CHANNEL, mention=True, ts='30.1', text='<@' + BOT + '> echo two'))
    cmd = SocketModeRequest('slash_commands', 'command-envelope', {'team_id': TEAM, 'user_id': USER, 'channel_id': CHANNEL,
                            'command': '/research', 'text': 'echo command', 'trigger_id': 'secret-trigger', 'response_url': 'secret-response-url'})
    runtime.handle_socket_request(socket, cmd)
    runtime.pump(); drain(runtime)
    by_text = {m['text']: m for m in runtime.client.messages}
    assert by_text['echo one']['thread_ts'] == '20.1'
    assert by_text['echo two']['thread_ts'] == '30.1'
    receipt = next(i for i,m in enumerate(runtime.client.messages, 1) if m['text'].startswith('请求已接收'))
    assert by_text['echo command']['thread_ts'] == '900.' + str(receipt)
    with runtime.journal.connect() as db:
        raw = '\n'.join(r['event'] for r in db.execute('SELECT event FROM inbox'))
    assert 'secret-trigger' not in raw and 'secret-response-url' not in raw


def test_revoked_access_blocks_pending_work_and_delivery(runtime, config):
    runtime.receive(event())
    config['slack_user_id'] = 'UNEW1234'
    runtime.pump()
    assert runtime.adapters['echo'].events == []
    config['slack_user_id'] = USER
    runtime.receive(event('e2')); runtime.process_one()
    config['slack_user_id'] = 'UNEW1234'
    drain(runtime)
    assert not runtime.client.messages
    assert runtime.journal.deliveries()[0]['error'] == 'authorization_changed'


def test_generic_adapter_receives_file_bytes_without_slack_secrets(runtime):
    socket = Socket()
    runtime.handle_socket_request(socket, request(subtype='file_share', files=[{'id': 'F1234567'}]))
    runtime.pump()
    adapter = runtime.adapters['echo']
    assert adapter.contents == [b'hello']
    ref = adapter.events[0].attachments[0]
    assert ref.status == 'ready' and len(ref.sha256) == 64 and ref.size == 5
    assert 'xoxb' not in adapter.events[0].model_dump_json()
    with pytest.raises(ValueError):
        runtime.attachments.read('wrong-event', ref.id)


@pytest.mark.parametrize('case', ['oversize_metadata', 'oversize_stream', 'offhost', 'redirect', 'denied', 'missing', 'external'])
def test_file_failure_boundaries(runtime, case, monkeypatch):
    seen = []
    def transport(req):
        seen.append(req)
        if case == 'redirect':return httpx.Response(302, headers={'location': 'https://attacker.example/file'})
        if case == 'denied':return httpx.Response(403)
        if case == 'missing':return httpx.Response(404)
        return httpx.Response(200, content=b'too-big')
    runtime.attachments.http_factory = lambda: httpx.Client(transport=httpx.MockTransport(transport))
    if case == 'oversize_metadata':runtime.client.info['size'] = MAX_FILE_BYTES + 1
    if case == 'oversize_stream':
        runtime.client.info['size'] = 0
        monkeypatch.setattr('pitr.integrations.slack.files.MAX_FILE_BYTES', 3)
    if case == 'offhost':runtime.client.info['url_private'] = 'https://attacker.example/file'
    if case == 'external':runtime.client.info['is_external'] = True
    ref = AttachmentRef(id='attachment_test', file_id='F1234567')
    runtime.receive(event().model_copy(update={'attachments': [ref]})); runtime.pump()
    assert runtime.adapters['echo'].events[0].attachments[0].status == 'failed'
    assert not runtime.adapters['echo'].contents
    assert all(r.url.host == 'files.slack.com' for r in seen)
    assert not list(runtime.journal.files.glob('*.part'))


def api_error(code, status=200, retry_after='0'):
    return SlackApiError('SDK details should not be stored', SlackResponse(client=None, http_verb='POST', api_url='https://slack.com/api/test',
                          req_args={}, data={'ok': False, 'error': code}, headers={'Retry-After': retry_after}, status_code=status))


def test_rate_limit_then_success_respects_delay_and_counts_real_attempts(runtime):
    runtime.receive(event()); runtime.process_one()
    runtime.client.error = api_error('ratelimited', 429, '30')
    runtime.drain_one()
    with runtime.journal.connect() as db:
        row = db.execute('SELECT * FROM outbox').fetchone()
        assert row['status'] == 'pending' and row['next_at'] >= time.time() + 29 and row['attempts'] == 1
    assert not runtime.drain_one()
    runtime.client.error = None; drain(runtime)
    assert runtime.journal.deliveries()[0]['status'] == 'sent'
    assert runtime.journal.deliveries()[0]['attempts'] == 2


def test_partial_file_delivery_and_unknown_manual_retry(runtime):
    runtime.receive(event())
    runtime.publish('e1', 'result', WorkflowUpdate(text='result', files=[OutputFile(content='full report')]))
    runtime.client.file_error = TimeoutError('xoxb-do-not-store https://private.example/ticket')
    drain(runtime)
    deliveries = runtime.journal.deliveries()
    assert {d['status'] for d in deliveries} == {'sent', 'delivery_unknown'}
    assert 'do-not-store' not in json.dumps(deliveries)
    failed = next(d for d in deliveries if d['kind'] == 'file')
    runtime.client.file_error = None; runtime.journal.retry(failed['id']); drain(runtime)
    assert len(runtime.client.messages) == 1 and len(runtime.client.files) == 1
    with pytest.raises(ValueError):runtime.journal.retry(failed['id'])


def test_crashed_send_is_not_automatically_resent(runtime):
    runtime.receive(event()); runtime.process_one()
    row = runtime.journal.claim('outbox')
    with runtime.journal.connect(write=True) as db:db.execute('UPDATE outbox SET lease=0 WHERE id=?', (row['id'],))
    runtime.drain_one()
    assert runtime.journal.deliveries()[0]['status'] == 'delivery_unknown'
    assert not runtime.client.messages


def test_inbox_lease_recovery_and_stable_business_request(runtime, config):
    runtime.receive(event())
    ctx = WorkflowContext(runtime, 'echo', 'e1')
    assert ctx.prepare(lambda: {'snapshot': 'first'}) == {'snapshot': 'first'}
    assert ctx.prepare(lambda: {'snapshot': 'changed'}) == {'snapshot': 'first'}
    row = runtime.journal.claim('inbox')
    assert runtime.journal.claim('inbox') is None
    with runtime.journal.connect(write=True) as db:db.execute('UPDATE inbox SET lease=0 WHERE id=?', (row['id'],))
    replacement = SlackRuntime(runtime.journal.root, lambda: config, client=Client())
    replacement.register(Echo()); replacement.pump()
    assert len(replacement.adapters['echo'].events) == 1
    assert replacement.client.messages[0]['thread_ts'] == '100.1'


def test_action_binding_submission_validation_and_replay(runtime):
    runtime.receive(event())
    token = runtime.register_action('echo', 'e1', 'echo_review', {'version': 1})
    def action(user=USER):
        return SocketModeRequest('interactive', 'action-envelope', {'type': 'block_actions', 'team': {'id': TEAM}, 'user': {'id': user},
             'channel': {'id': DM}, 'actions': [{'action_id': 'pitr_action', 'value': token, 'action_ts': '200.1'}], 'trigger_id': 'trigger'})
    assert runtime.normalize(action('UOTHER12')) is None
    adapter, incoming = runtime.normalize(action())
    runtime.receive(incoming, adapter)
    runtime.open_interaction(incoming.id, 'trigger', time.time())
    view = runtime.client.views[0]['view']
    assert view['private_metadata'].startswith('action_')
    body = {'type': 'view_submission', 'team': {'id': TEAM}, 'user': {'id': USER},
            'view': {'id': 'VIEW1234', 'callback_id': 'pitr_submit', 'private_metadata': view['private_metadata'], 'state': {'values': {}}}}
    socket = Socket()
    runtime.handle_socket_request(socket, SocketModeRequest('interactive', 'submit', body))
    assert socket.responses[-1].payload['response_action'] == 'errors'
    body['view']['state']['values'] = {'reason': {'value': {'value': 'approved'}}}
    runtime.handle_socket_request(socket, SocketModeRequest('interactive', 'submit2', body))
    runtime.handle_socket_request(socket, SocketModeRequest('interactive', 'submit3', body))
    runtime.pump()
    assert len([e for e in runtime.adapters['echo'].events if e.kind == 'submission']) == 1
    body['view']['private_metadata'] = '{"proposal_id":"tampered"}'
    assert runtime.normalize(SocketModeRequest('interactive', 'tamper', body)) is None


def test_interaction_business_rejection_explains_terminal_state(runtime, monkeypatch):
    from pitr.integrations.slack.contracts import WorkflowRejected
    incoming = event('finished-action').model_copy(update={'kind': 'action'})
    runtime.receive(incoming)

    def already_handled(event, context):
        raise WorkflowRejected('This action is already completed; request current actions.')

    monkeypatch.setattr(runtime.adapters['echo'], 'open_modal', already_handled)
    runtime.open_interaction(incoming.id, 'trigger', time.time())
    drain(runtime)
    assert not runtime.client.views
    assert runtime.client.messages[0]['text'] == 'This action is already completed; request current actions.'
    with runtime.journal.connect() as db:
        assert db.execute('SELECT status FROM inbox WHERE id=?', (incoming.id,)).fetchone()['status'] == 'rejected'


def test_start_stop_reconnect_and_installation_lock(tmp_path, config):
    settings = SettingsFile(tmp_path / 'private' / 'settings.json'); settings.save(config)
    runtime = SlackRuntime(tmp_path / 'slack', settings.read, settings.save, client=Client(), socket_factory=Socket)
    runtime.register(Echo())
    try:
        runtime.start()
        original = runtime.socket
        assert runtime.start()['connected'] and runtime.socket is original
        assert settings.read()['slack_enabled']
        original.connected = False
        assert runtime.status()['state'] == 'reconnecting'
        original.connected = True
        assert runtime.status()['connected']
        lock = InstallationLock(TEAM, BOT)
        with pytest.raises(ValueError):lock.acquire()
        runtime.stop(disable=False)
        assert settings.read()['slack_enabled']
        lock.acquire(); lock.release()
        runtime.client = Client(); runtime.start(enable=False); runtime.stop()
        assert settings.read()['slack_enabled'] is False
        runtime.stop()
    finally:
        runtime.stop()


def test_settings_api_manifest_attachment_and_live_gate(tmp_path, config):
    from pitr.desk.api import create_app
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client:
        result = client.post('/api/desk/settings', json=config)
        assert result.status_code == 200
        assert 'xoxb-offline' not in result.text and 'xapp-offline' not in result.text
        assert (tmp_path/'private/settings.json').stat().st_mode & 0o777 == 0o600
        assert client.post('/api/desk/settings', json={'slack_channel_ids':['bad']}).status_code == 422
        assert client.get('/api/desk/slack-manifest').text == MANIFEST
        assert Path('slack-app-manifest.yaml').read_text() == MANIFEST
        assert client.get('/api/desk/slack/deliveries').json() == []
        assert client.get('/api/desk/slack/attachments').json() == []
        assert client.get('/api/desk/slack/attachments/unknown/file').status_code == 404
        assert client.post('/api/desk/slack/live-checks', json={'check':'dm','evidence':'not actually tested'}).status_code == 422
        assert client.post('/api/desk/slack/test', json={}).status_code == 422
        result = client.post('/api/desk/settings', json={'slack_channel_ids': []})
        assert result.json()['slack_bot_token'] is True
        assert result.json()['slack_channel_ids'] == []


def test_binary_result_files_preserve_bytes_and_thread(runtime):
    runtime.receive(event())
    binary = b'PK\x03\x04\x00\xff\xfe workbook test'
    runtime.publish('e1', 'binary', WorkflowUpdate(text='Workbook', files=[OutputFile.from_bytes(binary, filename='model.xlsx')]))
    drain(runtime)
    assert runtime.client.files[0]['file'].getvalue() == binary
    assert runtime.client.files[0]['thread_ts'] == '100.1'
    assert runtime.client.files[0]['filename'] == 'model.xlsx'


def test_start_failure_releases_installation_and_accepts_new_credentials(tmp_path, config):
    settings = SettingsFile(tmp_path/'settings.json');settings.save(config)
    class BrokenSocket(Socket):
        def connect(self):raise ConnectionError('offline with xapp-secret')
    runtime = SlackRuntime(tmp_path/'slack', settings.read, settings.save, client_factory=lambda cfg:Client(), socket_factory=BrokenSocket)
    runtime.register(Echo())
    try:
        with pytest.raises(ValueError):runtime.start()
        assert runtime.status()['state']=='reconnecting'
        assert runtime.client is None
        assert 'secret' not in json.dumps(runtime.status())
        lock=InstallationLock(TEAM,BOT);lock.acquire();lock.release()
        assert runtime.retry_thread is not None
        runtime.stop()
        runtime.socket_factory=Socket
        assert runtime.start()['connected']
    finally:runtime.stop()


def test_restart_waits_for_previous_consumer_then_recovers_automatically(tmp_path, config):
    settings = SettingsFile(tmp_path / 'settings.json'); settings.save({**config, 'slack_enabled': True})
    previous = InstallationLock(TEAM, BOT); previous.acquire()
    runtime = SlackRuntime(tmp_path / 'slack', settings.read, settings.save,
                           client_factory=lambda cfg: Client(), socket_factory=Socket)
    runtime.register(Echo())
    try:
        with pytest.raises(ValueError, match='InstallationBusy'):
            runtime.start(enable=False)
        assert runtime.retry_thread and runtime.retry_thread.is_alive()
        assert runtime.socket is None
        previous.release()
        runtime.retry_thread.join(timeout=8)
        assert runtime.status()['connected'] and settings.read()['slack_enabled']
        with pytest.raises(ValueError): previous.acquire()
    finally:
        runtime.stop()
        previous.release()


def test_wrong_workspace_and_missing_scopes_prevent_connection(tmp_path,config):
    runtime=SlackRuntime(tmp_path/'wrong',lambda:{**config,'slack_team_id':'TWRONG12'},client=Client(),socket_factory=Socket)
    runtime.register(Echo())
    with pytest.raises(ValueError,match='工作区'):runtime.start()
    assert runtime.socket is None
    class MissingScopes(Client):
        def auth_test(self):
            return SlackResponse(client=None,http_verb='POST',api_url='https://slack.com/api/auth.test',req_args={},
                 data={'ok':True,'team_id':TEAM,'user_id':BOT},headers={'X-OAuth-Scopes':'chat:write'},status_code=200)
    runtime=SlackRuntime(tmp_path/'scopes',lambda:config,client_factory=lambda cfg:MissingScopes(),socket_factory=Socket)
    runtime.register(Echo())
    assert runtime.check()['ok'] is False
    assert 'files:read' in runtime.check()['missing_scopes']
    with pytest.raises(ValueError,match='缺少权限'):runtime.start()
    assert runtime.socket is None


def test_expired_interactions_get_a_reopen_message(runtime):
    runtime.receive(event().model_copy(update={'kind':'action','action_id':'echo_review'}))
    with runtime.journal.connect(write=True) as db:db.execute('UPDATE inbox SET created=0')
    runtime.pump();drain(runtime)
    assert not runtime.client.views
    assert '重新点击' in runtime.client.messages[0]['text']


def test_application_restarts_enabled_transport_without_disabling_it(tmp_path,config,monkeypatch):
    from pitr.desk.api import create_app
    from pitr.desk.slack import Slack
    from pitr.desk.tasks import Queue
    from pitr.desk.integrations import Monitor
    calls=[]
    monkeypatch.setattr(Queue,'start',lambda self:None)
    monkeypatch.setattr(Monitor,'start',lambda self:None)
    monkeypatch.setattr(Slack,'start',lambda self,enable=True:calls.append(enable))
    settings=SettingsFile(tmp_path/'private/settings.json');settings.save({**config,'slack_enabled':True})
    with TestClient(create_app(tmp_path)) as client:
        assert calls==[False]
        assert client.get('/api/desk/settings').json()['slack_enabled'] is True
    assert settings.read()['slack_enabled'] is True


def test_desk_enqueue_crash_replay_uses_original_request_and_returns_result(tmp_path,config,monkeypatch):
    from pitr.desk.service import Desk
    from pitr.desk.tasks import Queue
    from pitr.desk.slack import Slack
    desk=Desk(tmp_path/'desk');queue=Queue(desk)
    desk.ingest(b'PDD original source','text/plain','https://example.com/source','PDD','Offline source')
    runtime=Slack(desk,queue,lambda:config,client=Client())
    runtime.receive(event('event-crash-test',text='研究 PDD 问题'))
    class ProcessCrash(BaseException):pass
    original=WorkflowContext.bind
    monkeypatch.setattr(WorkflowContext,'bind',lambda *args:(_ for _ in ()).throw(ProcessCrash()))
    with pytest.raises(ProcessCrash):runtime.process_one()
    with desk.store.connect() as db:
        tasks=list(db.execute('SELECT body FROM tasks'))
    assert len(tasks)==1
    first=json.loads(tasks[0]['body'])
    assert 'slack_channel' not in first['request']['parameters']
    desk.ingest(b'New source after interruption','text/plain','https://example.com/new','PDD','New source')
    with runtime.journal.connect(write=True) as db:db.execute('UPDATE inbox SET lease=0')
    monkeypatch.setattr(WorkflowContext,'bind',original)
    runtime.process_one()
    with desk.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==1
    from pitr.desk.research.intake import IntakeWorker
    from pitr.desk.research.contracts import ResearchInterpretation,ResearchSubject
    resolved=ResearchInterpretation(title='Offline result',subjects=[ResearchSubject(company_id='PDD',name='PDD',verified=True)],questions=[]).model_dump()
    IntakeWorker(desk,resolver=lambda *a:resolved).run_one()
    def complete(desk,task,owner,checkpoint):
        from pitr.desk.research.tools import ToolPlane
        from pitr.desk.research.verify import validate
        from pitr.desk.storage import canonical
        plane=ToolPlane(desk,task,owner,checkpoint);plane.prepare()
        report=validate({'title':'Offline result','claims':[]},plane)
        with desk.store.connect(write=True) as db:db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(task['id'],1,canonical({'raw':{},'validated':report})))
        return report
    monkeypatch.setattr('pitr.desk.research.native.run',complete)
    queue.run_one();runtime.pump();drain(runtime)
    assert any('已完成' in message['text'] for message in runtime.client.messages)
    assert any('Offline result' in f.get('content','') for f in runtime.client.files)
    assert all(message.get('thread_ts')=='100.1' for message in runtime.client.messages)


def test_only_previously_directed_messages_can_be_edited_or_deleted(runtime):
    socket=Socket()
    runtime.handle_socket_request(socket,request(text='PDD revenue margin discussion'))
    edited=SocketModeRequest('events_api','edit-envelope',{'team_id':TEAM,'event_id':'Edit1','event':{
        'type':'message','subtype':'message_changed','channel':DM,
        'message':{'user':USER,'ts':'100.1','text':'PDD revenue mix discussion'}}})
    adapter,event=runtime.normalize(edited)
    assert adapter=='echo' and event.kind=='changed' and event.metadata['message_ts']=='100.1'
    assert event.target.thread_ts=='100.1'
    unknown=SocketModeRequest('events_api','unknown-envelope',{'team_id':TEAM,'event_id':'Edit2','event':{
        'type':'message','subtype':'message_changed','channel':DM,
        'message':{'user':USER,'ts':'never-captured','text':'PDD revenue'}}})
    assert runtime.normalize(unknown) is None
    deleted=SocketModeRequest('events_api','delete-envelope',{'team_id':TEAM,'event_id':'Delete1','event':{
        'type':'message','subtype':'message_deleted','channel':DM,'deleted_ts':'100.1'}})
    assert runtime.normalize(deleted)[1].kind=='deleted'
    edited.payload['event']['message']['user']='UOTHER12'
    assert runtime.normalize(edited) is None


def test_native_research_slack_uses_same_control_plane_and_bound_clarification(tmp_path,config):
    from pitr.desk.service import Desk
    from pitr.desk.tasks import Queue
    from pitr.desk.slack import Slack
    from pitr.desk.research.service import Research
    desk=Desk(tmp_path/'desk');queue=Queue(desk);runtime=Slack(desk,queue,lambda:config,client=Client())
    runtime.receive(event('native-request-event',text='分析一下新财报'))
    runtime.process_one();runtime.pump()
    requests=Research(desk).list();assert len(requests)==1
    request=requests[0];assert request['task']['status']=='waiting_user' and queue.claim() is None
    with runtime.journal.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM actions').fetchone()[0]>=1
        binding=db.execute('SELECT * FROM bindings').fetchone()
        assert binding['task_id']==request['task_id']
    # Duplicate event and repeat poll do not enqueue additional research.
    runtime.receive(event('native-request-event',text='分析一下新财报'));runtime.process_one();runtime.pump()
    assert len(Research(desk).list())==1
    from pitr.desk.research.contracts import ResearchMessage
    resumed=Research(desk).message(request['id'],ResearchMessage(operation_id='native-answer-slack',text='PDD，先复核利润变化',company='PDD',intent='earnings',expected_input_version=request['input_version']))
    assert resumed['task_id']==request['task_id'] and resumed['interpretation_status']=='pending'
    from pitr.desk.research.intake import IntakeWorker
    from pitr.desk.research.contracts import ResearchInterpretation,ResearchSubject
    IntakeWorker(desk,resolver=lambda *a:ResearchInterpretation(title='利润变化',intent='earnings',subjects=[ResearchSubject(company_id='PDD',name='拼多多',verified=True)],questions=['利润变化的原因']).model_dump()).run_one()
    assert Research(desk).get(request['id'])['task']['status']=='queued'


def test_native_explicit_analysis_does_not_auto_collect_into_wiki(tmp_path,config):
    from pitr.desk.service import Desk
    from pitr.desk.tasks import Queue
    from pitr.desk.slack import Slack
    from pitr.desk.research.service import Research
    d=Desk(tmp_path/'desk');s=Slack(d,Queue(d),lambda:config,client=Client())
    s.receive(event('native-analysis-routing',text='分析一下 PDD 本次财报'));s.process_one()
    r=Research(d).list()[0]
    assert r['input']['company']=='' and r['input']['workflow_version']==3
    assert r['interpretation_status']=='pending' and r['input']['question']=='分析一下 PDD 本次财报'
    assert r['task']['request']['workflow']=='research'
    assert not [p for p in d.wiki.list('PDD') if p.get('company')=='PDD']
