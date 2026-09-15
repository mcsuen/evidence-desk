"""Read connection settings only. Official CLIs own authentication and refresh."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib
import hashlib
import signal
import time

NAMES = {'codex': 'Codex', 'claude': 'Claude Code'}
GUIDES = {
    'codex': ('https://learn.chatgpt.com/docs/cli', 'codex login'),
    'claude': ('https://code.claude.com/docs/en/quickstart', 'claude auth login'),
}
BASE_ENV = {'PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL',
            'SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_EXTRA_CA_CERTS',
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
            'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}
CONNECTION_ENV = {
    'CODEX_HOME', 'OPENAI_API_KEY', 'OPENAI_BASE_URL',
    'CLAUDE_CONFIG_DIR', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
    'ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
    'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
    'CLAUDE_CODE_OAUTH_TOKEN',
}
CODEX_KEYS = {'model', 'model_provider', 'model_providers', 'model_reasoning_effort',
              'cli_auth_credentials_store', 'forced_login_method', 'forced_chatgpt_workspace_id',
              'openai_base_url','chatgpt_base_url'}
CLAUDE_KEYS = {'model', 'effortLevel', 'modelOverrides', 'availableModels', 'enforceAvailableModels', 'apiKeyHelper'}


def read_json(path):
    try:
        value = Path(path).read_text()
        return json.loads(value) if value.strip() else {}
    except FileNotFoundError:
        return {}


def executable(provider, environ=None):
    env = os.environ if environ is None else environ
    home = Path(env.get('HOME', str(Path.home())))
    override = env.get('PITR_CODEX_BINARY' if provider == 'codex' else 'PITR_CLAUDE_BINARY')
    choices = [override, shutil.which(provider, path=env.get('PATH')),
               str(home / '.local/bin' / provider), '/opt/homebrew/bin/' + provider, '/usr/local/bin/' + provider]
    if provider == 'codex':
        choices += ['/Applications/Codex.app/Contents/Resources/codex', '/Applications/ChatGPT.app/Contents/Resources/codex']
    for candidate in choices:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    return None


def connection(provider, environ=None):
    source = os.environ if environ is None else environ
    keys={k for k in CONNECTION_ENV if k.startswith(('CODEX_','OPENAI_') if provider=='codex' else ('CLAUDE_','ANTHROPIC_'))}
    env = {k: v for k, v in source.items() if k in BASE_ENV | keys}
    home = Path(env.get('HOME', str(Path.home())))
    config_home = Path(env.get('CODEX_HOME' if provider == 'codex' else 'CLAUDE_CONFIG_DIR', str(home / ('.codex' if provider == 'codex' else '.claude'))))
    if provider == 'codex':
        path = config_home / 'config.toml'
        config = tomllib.loads(path.read_text()) if path.exists() else {}
        if config.get('profile'):
            config = {**config, **config.get('profiles', {}).get(config['profile'], {})}
        config = {k: v for k, v in config.items() if k in CODEX_KEYS}
        # env_key refers to the user's own credential, never to PITR settings.
        for item in config.get('model_providers', {}).values():
            key = item.get('env_key')
            if key and key in source:
                env[key] = source[key]
            for key in item.get('env_http_headers',{}).values():
                if key in source:env[key]=source[key]
        env['PITR_AGENT_ENDPOINTS']=json.dumps([*filter(None,[config.get('openai_base_url'),config.get('chatgpt_base_url')]),
            *[p['base_url'] for p in config.get('model_providers',{}).values() if p.get('base_url')]])
    else:
        raw = read_json(config_home / 'settings.json')
        env.update({k: str(v) for k, v in raw.get('env', {}).items() if k in BASE_ENV | keys})
        # Explicit environment variables take precedence over user settings.
        env.update({k: source[k] for k in BASE_ENV | keys if k in source})
        config = {k: v for k, v in raw.items() if k in CLAUDE_KEYS}
    env['PITR_CAPTURE_ORIGIN'] = 'pitr-wiki'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env, config, config_home


def connection_fingerprint(env,config):
    # Only a digest is persisted; credentials remain owned by the native CLI.
    values={k:v for k,v in env.items() if k not in ('PATH','TMPDIR','LANG','LC_ALL','PITR_CAPTURE_ORIGIN','PYTHONDONTWRITEBYTECODE','ANTHROPIC_MODEL')}
    config={k:v for k,v in config.items() if k not in ('model','model_reasoning_effort','effortLevel','availableModels')}
    return hashlib.sha256(json.dumps([values,config],sort_keys=True).encode()).hexdigest()


def toml(value):
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(str(k)) + '=' + toml(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(toml(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=False)


def codex_command(binary, config):
    # app-server does not accept exec's --ignore-user-config/--ignore-rules.
    # Seatbelt hides those files while preserving the native credential store.
    cmd = [binary, 'app-server', '--stdio']
    for k, v in config.items():
        cmd += ['-c', k + '=' + toml(v)]
    DISABLED=['shell_tool','apps','plugins','browser_use','browser_use_external','computer_use','multi_agent','hooks','view_image','image_generation','workspace_dependencies','goals','memories','shell_snapshot','skill_search','sleep_tool','request_permissions_tool','code_mode','code_mode_host','remote_plugin','skill_mcp_dependency_install']
    for feature in DISABLED:
        if feature=='code_mode_host':continue  # app-server's MCP transport uses this host
        cmd += ['--disable', feature]
    cmd += ['-c', 'features.skip_host_skill_discovery=true', '-c', 'project_doc_max_bytes=0',
            '-c', 'analytics.enabled=false', '-c', 'approval_policy="never"',
            '-c', 'sandbox_mode="read-only"']
    return cmd


def metadata(command,env,stopped):
    """Short, cancellable probes; helpers cannot outlive their metadata call."""
    process=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    deadline=time.monotonic()+10
    try:
        while True:
            if stopped():raise InterruptedError('Agent detection stopped')
            if time.monotonic()>deadline:raise subprocess.TimeoutExpired(command,10)
            try:
                out,error=process.communicate(timeout=.2)
                return subprocess.CompletedProcess(command,process.returncode,out,error)
            except subprocess.TimeoutExpired:pass
    finally:
        for sig in (signal.SIGTERM,signal.SIGKILL):
            try:os.killpg(process.pid,sig)
            except (ProcessLookupError,PermissionError):pass
        process.wait()
        process.stdout.close();process.stderr.close()


def probe(provider, environ=None, stopped=lambda:False):
    result = {'id': provider, 'name': NAMES[provider], 'installed': False, 'authenticated': False,
              'compatible': False, 'status': 'missing', 'version': None,
              'install_url': GUIDES[provider][0], 'login_command': GUIDES[provider][1]}
    binary = executable(provider, environ)
    if not binary:
        return result
    result['installed'] = True
    try:
        env, config, _ = connection(provider, environ)
        version = metadata([binary,'--version'],env,stopped)
        result['version'] = version.stdout.strip()[:120]
        # These operations neither launch a model turn nor load project content.
        help_args = [binary, 'app-server', '--help'] if provider == 'codex' else [binary, '--help']
        help_result = metadata(help_args,env,stopped)
        result['compatible'] = help_result.returncode == 0 and all(flag in help_result.stdout for flag in
            (('stdio',) if provider == 'codex' else ('--restricted', '--disable-slash-commands', '--json-schema', '--strict-mcp-config')))
        args = [binary, 'login', 'status'] if provider == 'codex' else [binary, 'auth', 'status']
        auth = metadata(args,env,stopped)
        if provider == 'codex':
            result['authenticated'] = auth.returncode == 0 and 'logged in' in (auth.stdout + auth.stderr).lower()
            result['auth_method']='chatgpt' if 'chatgpt' in (auth.stdout+auth.stderr).lower() else 'api' if result['authenticated'] else None
        else:
            status=json.loads(auth.stdout)
            result['authenticated'] = auth.returncode == 0 and bool(status.get('loggedIn'))
            result['auth_method']=status.get('authMethod')
        result['status'] = 'incompatible' if not result['compatible'] else 'logged_in' if result['authenticated'] else 'signed_out'
    except (OSError, ValueError, subprocess.TimeoutExpired):
        result['status'] = 'check_failed'
    return result
