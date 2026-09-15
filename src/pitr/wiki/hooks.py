"""Reversible config merge; provider trust is intentionally left to the provider."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile

EVENTS = ('UserPromptSubmit', 'PostToolUse', 'Stop', 'SessionEnd')
VERSION = 1


def config_path(provider, scope='project', project=None, user_home=None):
    if provider not in ('claude', 'codex') or scope not in ('project', 'user'):
        raise ValueError('provider 必须是 claude/codex，scope 必须是 project/user')
    base = Path(project or Path.cwd()) if scope == 'project' else Path(user_home or Path.home())
    folder = base / ('.claude' if provider == 'claude' else '.codex')
    if scope=='user' and provider=='codex' and user_home is None and os.environ.get('CODEX_HOME'):
        folder=Path(os.environ['CODEX_HOME'])
    return folder / ('settings.json' if provider == 'claude' else 'hooks.json')


def _write(path, data):
    fd, name = tempfile.mkstemp(prefix='.pitr-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def install(provider, root, *, scope='project', project=None, user_home=None, uninstall=False):
    path = config_path(provider, scope, project, user_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = path.parent / ('.pitr-' + path.name + '.json')
    with (path.parent / '.pitr-hooks.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = path.read_bytes() if path.exists() else b'{}'
        original = json.loads(before)
        if not isinstance(original, dict) or not isinstance(original.get('hooks', {}), dict):
            raise ValueError('现有 hook 配置结构不合法，未作修改')
        config = copy.deepcopy(original)
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'entries': {}}
        own = manifest.get('entries', {})
        hooks = config.setdefault('hooks', {})
        entries = {}
        command = shlex.join([str(Path(sys.executable).absolute()), '-m', 'pitr.wiki.capture', '--provider', provider, '--root', str(Path(root).resolve())])
        for event in EVENTS:
            current = hooks.get(event, [])
            if not isinstance(current, list):
                raise ValueError('现有事件配置不是列表，未作修改')
            # Exact owned entries only: same-looking user hooks are never removed.
            previous = own.get(event)
            if previous is not None and previous not in current and not uninstall:
                raise ValueError('PITR hook 已被手动修改，请核对配置后再升级；未添加重复入口')
            if previous in current:
                current = current.copy()
                current.remove(previous)
            if not uninstall:
                entry = {'hooks': [{'type': 'command', 'command': command, 'timeout': 3}]}
                if event == 'PostToolUse':
                    entry['matcher'] = '*'
                current.append(entry)
                entries[event] = entry
            if current:
                hooks[event] = current
            else:
                hooks.pop(event, None)
        if not hooks and not manifest.get('original_had_hooks', 'hooks' in original):
            config.pop('hooks', None)
        changed = config != original
        if changed:
            backup = path.parent / (path.name + '.pitr-backup-' + hashlib.sha256(before).hexdigest()[:12])
            if not backup.exists():
                backup.write_bytes(before)
            _write(path, config)
        _write(manifest_path, {'version': VERSION, 'provider': provider, 'scope': scope,
                              'root': str(Path(root).resolve()), 'original_had_hooks': manifest.get('original_had_hooks', 'hooks' in original), 'entries': entries})
        return {'path': str(path), 'changed': changed, 'installed': not uninstall,
                'trust': '请在提供方原生界面检查并信任更新后的 hook 配置；PITR 不自动授予信任。'}


def doctor(root, project=None):
    from .capture import connection
    checks = []
    for provider in ('claude', 'codex'):
        for scope in ('project', 'user'):
            path = config_path(provider, scope, project)
            manifest = path.parent / ('.pitr-' + path.name + '.json')
            item = {'provider': provider, 'scope': scope, 'path': str(path), 'status': 'not_installed'}
            if manifest.exists():
                try:
                    saved = json.loads(manifest.read_text())
                    config = json.loads(path.read_text())
                    item['status'] = 'configured' if saved['entries'] and all(entry in config.get('hooks', {}).get(event, []) for event, entry in saved['entries'].items()) else 'missing_or_modified'
                    item['root'] = saved.get('root')
                except (OSError, ValueError, KeyError):
                    item['status'] = 'invalid_config'
            checks.append(item)
    with connection(root) as db:
        queue = {r['status']: r['count'] for r in db.execute('SELECT status,COUNT(*) count FROM captures GROUP BY status')}
    return {'checks': checks, 'queue': queue, 'python': sys.executable,
            'trust': '原生信任状态无法从配置文件认证；请发送测试材料验证。',
            'coverage': '只采集已公开的生命周期字段；不读取会话文件，不承诺托管工具全量捕获。'}
