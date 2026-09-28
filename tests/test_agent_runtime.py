"""Protocol boundaries and task routing; these tests do not call a model service."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pitr.agent_runtime import bind_task,task_scope
from pitr.agent_runtime.runtime import AgentRuntime,verified_searches
from pitr.agent_runtime.transport import AgentError,Process
from pitr.agent_runtime.local_auth import LocalAuth
from pitr.agent_runtime.daemon import Instance
from pitr.application.service import Workstation
from pitr.domain.common import canonical
from pitr.llm import complete_json

FAKE=r'''
import json,sys,time,os
from pathlib import Path
provider=Path(sys.argv[0]).name
def emit(value):print(json.dumps(value),flush=True)
if '--version' in sys.argv:print(provider+' 1.0');sys.exit()
if '--help' in sys.argv:print('stdio --restricted --disable-slash-commands --json-schema --strict-mcp-config');sys.exit()
if 'status' in sys.argv:
 print('Logged in using ChatGPT' if provider=='codex' else '{"loggedIn":true,"authMethod":"claude.ai"}');sys.exit()
if provider=='codex':
 model='fake-default'
 for line in sys.stdin:
  v=json.loads(line);method=v.get('method');p=v.get('params',{});result={}
  if method=='initialize':result={'protocolVersion':'1'}
  elif method=='model/list':result={'data':[{'id':'fake-default','model':'fake-default','displayName':'Default','isDefault':True}], 'nextCursor':None}
  elif method in ('thread/start','thread/resume'):
   model=p.get('model') or model;result={'thread':{'id':p.get('threadId','session-codex')},'model':model}
  elif method=='turn/start':
   text=p['input'][0]['text']
   if 'wait-forever' in text:time.sleep(60)
   if 'invalid-output' in text:answer='not-json'
   else:answer=json.dumps({'ok':True,'model':model})
   # Events before the matching turn/start response must not be dropped.
   emit({'method':'item/completed','params':{'item':{'id':'a','type':'agentMessage','text':answer}}})
   emit({'method':'thread/tokenUsage/updated','params':{'tokenUsage':{'last':{'inputTokens':10,'outputTokens':3}}}})
   emit({'method':'turn/completed','params':{'turn':{'id':'turn-1','status':'completed'}}})
   result={'turn':{'id':'turn-1'}}
  if 'id' in v:emit({'id':v['id'],'result':result})
else:
 v=json.loads(sys.stdin.readline());text=v['message']['content'][0]['text']
 model=sys.argv[sys.argv.index('--model')+1] if '--model' in sys.argv else 'fake-default'
 if 'wait-forever' in text:time.sleep(60)
 emit({'type':'system','subtype':'init','session_id':'session-claude','model':model.removesuffix('[1m]')})
 emit({'type':'stream_event','event':{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'Working'}}})
 emit({'type':'result','subtype':'success','is_error':False,'structured_output':{'ok':True,'model':model},'usage':{'input_tokens':10,'output_tokens':3}})
'''
SCHEMA={'type':'object','properties':{'ok':{'type':'boolean'},'model':{'type':'string'}},'required':['ok','model'],'additionalProperties':False}


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    binaries=tmp_path/'bin';binaries.mkdir()
    for name in ('codex','claude'):
        binary=binaries/name;binary.write_text('#!'+sys.executable+'\n'+FAKE);binary.chmod(0o700)
    home=tmp_path/'home';home.mkdir()
    monkeypatch.setenv('PITR_RESEARCH_RUNTIME',str(tmp_path/'runs'))
    desk=Workstation(tmp_path/'research',runtime=False)
    desk.agents=AgentRuntime(desk,environ={'HOME':str(home),'PATH':str(binaries),'PITR_CODEX_BINARY':str(binaries/'codex'),'PITR_CLAUDE_BINARY':str(binaries/'claude')},isolate=False)
    desk.agents.refresh()
    yield desk.agents
    desk.agents.shutdown()


@pytest.mark.parametrize('provider',['codex','claude'])
def test_native_protocol_and_continuation(runtime,provider):
    task={'id':'task'};bind_task(runtime.context,task,provider,'chosen')
    events=[]
    result=runtime.execute(task,'hello',SCHEMA,on_event=events.append)
    assert result.data=={'ok':True,'model':'chosen'}
    assert result.model=='chosen' and result.session_id=='session-'+provider
    assert result.usage=={'input_tokens':10,'output_tokens':3}
    result=runtime.execute(task,'continue',SCHEMA,session_id=result.session_id)
    assert result.session_id=='session-'+provider
    assert runtime._binding(task)['resolved_model']=='chosen'
    assert (result.root/'events.jsonl').exists() and not runtime.processes
    if provider=='claude':assert any(e['type']=='item.updated' for e in events)


def test_model_discovery_uses_no_turn(runtime):
    assert runtime.models('codex')['models'][1]['id']=='fake-default'
    assert {'opus','sonnet','haiku'}<={o['id'] for o in runtime.models('claude')['models']}
    assert not runtime.models('claude')['permissions_verified']


def test_discovery_selects_the_only_ready_agent_and_retains_selection(runtime,monkeypatch):
    import pitr.agent_runtime.connection as discovery
    assert not runtime.status()['selection'].get('agent_provider')
    original=discovery.executable;missing={'claude'}
    monkeypatch.setattr(discovery,'executable',lambda name,env=None:None if name in missing else original(name,env))
    runtime.refresh()
    assert runtime.status()['selection']['agent_provider']=='codex'
    assert next(a for a in runtime.status()['agents'] if a['id']=='claude')['status']=='missing'
    missing.clear();runtime.refresh()
    assert all(a['status']=='logged_in' for a in runtime.status()['agents'])
    assert runtime.status()['selection']['agent_provider']=='codex'


def test_installed_signed_out_agents_do_not_become_the_default(runtime):
    for provider in ('codex','claude'):
        binary=Path(runtime.environ['PATH'])/provider
        binary.write_text('#!'+sys.executable+'\nimport sys\nif "status" in sys.argv:\n print(\'{"loggedIn":false}\');sys.exit(1)\n'+FAKE)
    runtime.refresh()
    assert all(a['installed'] and a['compatible'] and a['status']=='signed_out' for a in runtime.status()['agents'])
    assert not runtime.status()['selection'].get('agent_provider')


def test_claude_long_context_choice_survives_resolution_and_resume(runtime):
    runtime.save_selection({'agent_provider':'claude','agent_models':{'claude':'sonnet[1m]'}})
    task={'id':'long-context'};bind_task(runtime.context,task)
    first=runtime.execute(task,'hello',SCHEMA)
    assert first.model=='sonnet' and first.data['model']=='sonnet[1m]'
    runtime.save_selection({'agent_models':{'claude':'haiku'}})
    second=runtime.execute(task,'continue',SCHEMA,session_id=first.session_id)
    assert second.model=='sonnet' and second.data['model']=='sonnet[1m]'
    assert runtime._binding(task)['requested_model']=='sonnet[1m]'


def test_task_scope_overrides_api_priority_without_global_environment(runtime,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','unrelated-key-must-not-be-used')
    task={'id':'scoped'};bind_task(runtime.context,task,'claude','chosen')
    with task_scope(runtime.context,task):result=complete_json('test',SCHEMA,provider='openai',model='wrong')
    assert result.provider=='claude_cli' and result.model=='chosen'
    assert os.environ['OPENAI_API_KEY']=='unrelated-key-must-not-be-used'


@pytest.mark.parametrize('provider',['codex','claude'])
def test_cancel_interrupts_wait_and_cleans_processes(runtime,provider):
    task={'id':'cancel'};bind_task(runtime.context,task,provider)
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(runtime.execute,task,'wait-forever',SCHEMA)
        deadline=time.monotonic()+5
        while not runtime.processes and time.monotonic()<deadline:time.sleep(.01)
        process=next(iter(runtime.processes.values()))
        runtime.cancel(task['id'])
        with pytest.raises(AgentError,match='停止'):future.result(timeout=6)
    assert process.proc.poll() is not None and not runtime.processes


def test_bad_output_is_not_a_success(runtime):
    task={'id':'invalid'};bind_task(runtime.context,task,'codex')
    with pytest.raises(AgentError,match='结构化'):runtime.execute(task,'invalid-output',SCHEMA)


def test_search_receipts_require_successful_tool_events():
    with pytest.raises(AgentError):verified_searches([{'search_log':'I searched'}])
    start={'type':'item.started','item':{'id':'search','name':'WebSearch','arguments':{'query':'public'}}}
    with pytest.raises(AgentError):verified_searches([start,{'type':'item.completed','item':{'id':'search','is_error':True}}])
    assert len(verified_searches([start,{'type':'item.completed','item':{'id':'search','result':'found'}}]))==1


def test_single_instance_link_is_fresh_and_original_lock_is_retained(tmp_path):
    first=Instance(tmp_path/'desk');second=Instance(tmp_path/'desk')
    try:
        assert first.acquire() and not second.acquire()
        first.listen(LocalAuth(8765))
        assert second.existing_url()!=second.existing_url()
        second.close();second=None
        third=Instance(tmp_path/'desk')
        try:assert not third.acquire()
        finally:third.close()
    finally:
        if second:second.close()
        first.close()


def test_bootstrap_cookie_csrf_host_origin_and_replay(runtime):
    from pitr.adapters.api import create_app
    app=create_app(runtime.context.root,workers=False)
    auth=LocalAuth(8765)
    with TestClient(auth.middleware(app),base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/v1/today').status_code==401
        ticket=auth.url().split('bootstrap=')[1]
        session=client.post('/api/local/session',json={'ticket':ticket})
        assert session.status_code==200 and 'HttpOnly' in session.headers['set-cookie']
        token=session.json()['csrf']
        assert client.post('/api/local/session',json={'ticket':ticket}).status_code==401
        assert client.get('/api/v1/today').status_code==200
        assert client.post('/api/v1/settings',json={}).status_code==403
        assert client.post('/api/v1/settings',json={'operation_id':'save-settings'},headers={'X-PITR-CSRF':token}).status_code==200
        assert client.get('/api/v1/today',headers={'Host':'attacker.example:8765'}).status_code==403
        assert client.get('/api/v1/today',headers={'Origin':'https://attacker.example'}).status_code==403


def test_connection_excludes_personal_configuration_and_other_secrets(runtime):
    from pitr.agent_runtime.connection import connection
    home=Path(runtime.environ['HOME']);(home/'.claude').mkdir()
    (home/'.claude/settings.json').write_text(json.dumps({'model':'sonnet','hooks':{'bad':'shell'},'permissions':{'allow':['Bash']},'env':{'SLACK_BOT_TOKEN':'secret','ANTHROPIC_BASE_URL':'https://example.com'}}))
    env,config,_=connection('claude',{**runtime.environ,'SLACK_BOT_TOKEN':'secret','PITR_DESK_DIR':'secret'})
    assert 'SLACK_BOT_TOKEN' not in env and 'PITR_DESK_DIR' not in env
    assert 'hooks' not in config and 'permissions' not in config and config['model']=='sonnet'


@pytest.mark.parametrize('model',['bad model','x\n--flag','x'*201])
def test_invalid_models_are_rejected(runtime,model):
    with pytest.raises(ValueError):runtime.selection('codex',model)


def test_connection_change_cannot_silently_change_authentication(runtime):
    task={'id':'bound'};bind_task(runtime.context,task,'claude')
    runtime.environ['ANTHROPIC_API_KEY']='another-authentication'
    with pytest.raises(AgentError,match='连接配置已改变'):runtime.execute(task,'hello',SCHEMA)


def test_concurrent_sessions_do_not_block_child_calls(runtime):
    task={'id':'concurrent'};bind_task(runtime.context,task,'codex')
    with ThreadPoolExecutor(3) as pool:
        first=pool.submit(runtime.execute,task,'wait-forever',SCHEMA,session_id='parent')
        deadline=time.monotonic()+5
        while not runtime.processes and time.monotonic()<deadline:time.sleep(.01)
        second=pool.submit(runtime.execute,task,'wait-forever',SCHEMA,session_id='parent')
        child=pool.submit(runtime.execute,task,'child',SCHEMA)
        assert child.result(timeout=8).data['ok']
        assert len(runtime.processes)==1
        runtime.cancel(task['id'])
        for future in (first,second):
            with pytest.raises(AgentError):future.result(timeout=6)


@pytest.mark.skipif(sys.platform!='darwin',reason='macOS isolation')
def test_isolation_hides_personal_config_but_preserves_native_auth_path(runtime,tmp_path):
    from pitr.agent_runtime.isolation import prepare
    import subprocess
    home=Path(runtime.environ['HOME']);config=home/'.codex';config.mkdir()
    (config/'config.toml').write_text('developer_instructions="personal canary"')
    (config/'auth.json').write_text('non-secret authentication canary')
    root=tmp_path/'runs'/'isolated'
    prefix,checks=prepare(runtime.context,root,sys.executable,config,runtime.environ)
    assert checks['observed']['outside_workspace']=='denied'
    assert Path(runtime.environ['CLAUDE_CODE_TMPDIR']).is_relative_to(root.resolve())
    script='''import json,os,sys
out=[]
for path in sys.argv[1:]:
 try:
  with open(path) as f:f.read(1)
  out.append('readable')
 except FileNotFoundError:out.append('absent')
 except PermissionError:out.append('denied')
print(json.dumps(out))
'''
    result=subprocess.run([*prefix,str(Path(sys.executable).resolve()),'-c',script,str(config/'config.toml'),str(config/'auth.json'),str(runtime.context.store.path)],cwd=root,capture_output=True,text=True,check=True)
    assert checks['passed'] and json.loads(result.stdout)==['absent','readable','denied']


def test_guardian_reaps_group_when_daemon_crashes(tmp_path):
    import subprocess
    pidfile=tmp_path/'pid'
    code='''import os,time,sys
from pitr.agent_runtime.transport import Process
p=Process([sys.executable,'-c','import time;time.sleep(60)'],cwd=sys.argv[1],env=os.environ)
open(sys.argv[2],'w').write(str(p.proc.pid))
os._exit(0)
'''
    subprocess.run([sys.executable,'-c',code,str(tmp_path),str(pidfile)],check=True)
    pid=int(pidfile.read_text());deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        process=subprocess.run(['/bin/ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
        if process.returncode or process.stdout.strip().startswith('Z'):break
        time.sleep(.05)
    else:pytest.fail('Agent process survived its daemon')


def test_timeout_and_late_output_cannot_return_success(runtime):
    task={'id':'timeout'};bind_task(runtime.context,task,'codex')
    with pytest.raises(TimeoutError):runtime.execute(task,'wait-forever',SCHEMA,timeout=.3)
    assert not runtime.processes


@pytest.mark.skipif(sys.platform!='darwin',reason='macOS npm distribution isolation')
def test_npm_cli_launcher_can_read_its_package_without_accessing_control_data(runtime,tmp_path):
    import shutil,subprocess
    from pitr.agent_runtime.isolation import prepare
    node=shutil.which('node')
    if not node:pytest.skip('Node runtime unavailable')
    package=tmp_path/'node_modules/@example/agent';(package/'bin').mkdir(parents=True)
    launcher=package/'bin/agent.js';launcher.write_text('#!/usr/bin/env node\nconsole.log(require("../package.json").name)\n');launcher.chmod(0o700)
    (package/'package.json').write_text('{"name":"test-agent"}')
    config=tmp_path/'auth';config.mkdir()
    env={**runtime.environ,'PATH':str(Path(node).parent)}
    root=tmp_path/'run'
    prefix,checks=prepare(runtime.context,root,str(launcher),config,env)
    result=subprocess.run([*prefix,str(launcher)],cwd=root,env=env,capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='test-agent' and checks['passed']


def test_explicit_followup_can_start_after_cancelled_call_has_ended(runtime):
    task={'id':'followup'};bind_task(runtime.context,task,'claude')
    runtime.cancel(task['id'])
    # Queue cancellation remains durable; this represents a separately
    # authorized new interpretation for an explicit user follow-up.
    assert runtime.execute(task,'explicit follow-up',SCHEMA,fence=lambda:None).data['ok']


@pytest.mark.skipif(sys.platform!='darwin', reason='macOS shell workspace isolation')
def test_shell_workspace_is_writable_but_runtime_authority_and_other_tasks_are_not(runtime, tmp_path):
    import subprocess
    from pitr.agent_runtime.isolation import prepare
    from types import SimpleNamespace
    config=Path(runtime.environ['HOME'])/'.codex';config.mkdir()
    work=SimpleNamespace(root=tmp_path/'work');work.root.mkdir()
    authority=tmp_path/'execution.json';authority.write_text('{"active":true}')
    other=tmp_path/'other-task';other.mkdir();(other/'secret').write_text('canary')
    root=tmp_path/'runtime'
    prefix,checks=prepare(runtime.context,root,sys.executable,config,runtime.environ,workspace=work.root,authority=authority)
    import pitr.tool_cli
    tool=Path(pitr.tool_cli.__file__).resolve()
    script='''import os,json,sys
out={}
for mode,label,path in json.loads(sys.argv[1]):
 try:
  flags=os.O_RDONLY if mode=='read' else os.O_WRONLY
  if label=='workspace':flags|=os.O_CREAT|os.O_EXCL
  fd=os.open(path,flags,0o600);os.close(fd);out[label]='allowed'
 except PermissionError:out[label]='denied'
print(json.dumps(out))
'''
    probes=[['write','workspace',str(work.root/'canary')],['write','tool_write',str(tool)],
        ['read','tool_read',str(tool)],['write','authority_write',str(authority)],
        ['read','authority_read',str(authority)],['read','other_task',str(other/'secret')],
        ['read','main',str(runtime.context.store.path)]]
    result=subprocess.run([*prefix,str(Path(sys.executable).resolve()),'-c',script,json.dumps(probes)],cwd=root,capture_output=True,text=True,check=True)
    assert checks['passed']
    assert json.loads(result.stdout)=={'workspace':'allowed','tool_write':'denied','tool_read':'allowed',
        'authority_write':'denied','authority_read':'allowed','other_task':'denied','main':'denied'}


def test_isolation_opens_only_the_claude_scratch_directory(runtime,tmp_path):
    from pitr.agent_runtime.isolation import prepare, claude_scratch
    config=Path(runtime.environ['HOME'])/'.claude';config.mkdir(exist_ok=True)
    prefix,checks=prepare(runtime.context,tmp_path/'runs'/'scratch',sys.executable,config,runtime.environ)
    profile=Path(prefix[prefix.index('-f')+1]).read_text()
    assert '(allow file-read* file-write* (subpath '+json.dumps(str(claude_scratch()))+'))' in profile
    desk_root=json.dumps(str(runtime.context.root.resolve()))
    assert any(line.startswith('(deny file-read* file-write*') and '(subpath '+desk_root+')' in line for line in profile.splitlines())
    assert not any(line.startswith('(allow') and desk_root in line for line in profile.splitlines())
