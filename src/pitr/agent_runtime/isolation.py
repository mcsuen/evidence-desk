"""macOS policy for the official runtime and a single PITR capability scope."""
import json
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile


def profile(run,desk,port=0):
    home=Path.home().resolve();run=Path(run).resolve()
    denied={home,desk.root.resolve(),Path(__file__).resolve().parents[4]}
    text='(version 1)\n(allow default)\n(deny file-read* file-write* '+ ' '.join('(subpath '+json.dumps(str(p))+')' for p in denied)+')\n'
    text+='(allow file-read* (subpath '+json.dumps(str(Path(sys.base_prefix).resolve()))+'))\n'
    text+='(allow file-read* file-write* (subpath '+json.dumps(str(run))+'))\n(allow file-read-metadata)\n'
    text+='(deny network-outbound (remote ip "localhost:*"))\n'
    from urllib.request import getproxies
    from urllib.parse import urlparse
    for url in getproxies().values():
        parsed=urlparse(url)
        if parsed.hostname in ('127.0.0.1','localhost') and parsed.port:
            text+='(allow network-outbound (remote ip \"localhost:'+str(parsed.port)+'\"))\n'
    if port:text+='(allow network-outbound (remote ip "localhost:'+str(port)+'"))\n'
    return text


def prepare(desk, root, binary, config_home, env, port=0):
    from pitr.desk.research.native import runtime_root
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').exists():
        raise RuntimeError('本机 Agent 桥接目前需要 macOS')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = profile(root, desk, port)
    # Limit reads as well as writes outside HOME, including unrelated desks
    # placed in /tmp or on mounted volumes. Native loaders need the root
    # directory itself, but that does not grant access to its descendants.
    files = '(deny file-read* file-write*)\n(allow file-read* (literal "/"))\n'
    for path in ('/System', '/usr/bin', '/usr/sbin', '/usr/lib', '/usr/libexec', '/usr/share',
                 '/bin', '/sbin', '/Library/Apple', '/Library/Preferences', '/Library/Keychains',
                 '/Library/Security', '/private/etc', '/private/var/db', '/private/var/run', '/dev'):
        files += '(allow file-read* (subpath ' + json.dumps(str(Path(path).resolve())) + '))\n'
    files += '(allow file-write* (literal "/dev/null") (literal "/dev/tty"))\n'
    text = text.replace('(allow default)', '(allow default)\n' + files, 1)
    temporary = root / 'tmp'; temporary.mkdir(exist_ok=True, mode=0o700)
    env['TMPDIR'] = str(temporary.resolve()) + '/'
    # Claude uses /tmp on macOS even when TMPDIR is set.
    env['CLAUDE_CODE_TMPDIR'] = str(temporary.resolve())
    text+='(deny file-read* file-write* (subpath '+json.dumps(str(runtime_root(desk).resolve()))+'))\n'
    text+='(allow file-read* file-write* (subpath '+json.dumps(str(root.resolve()))+'))\n'
    # Native credentials are read/refreshed by the original binary. We do not
    # copy OAuth tokens into run directories. Personal extensions are disabled
    # separately by the CLI launch policy; no generic file or shell tool exists.
    native_paths = [config_home]
    if config_home.name == '.claude' or env.get('CLAUDE_CONFIG_DIR'):
        native_paths += [Path(env.get('HOME', str(Path.home()))) / '.claude.json',
                         Path(env.get('HOME', str(Path.home()))) / 'Library/Keychains']
    else:
        native_paths += [Path(env.get('HOME', str(Path.home()))) / 'Library/Keychains']
    for path in native_paths:
        path = Path(path).resolve()
        if path == Path.home() or path in Path.home().parents or path == desk.root.resolve() or desk.root.resolve() in path.parents or path in desk.root.resolve().parents:
            raise RuntimeError('CLI 凭据目录与研究数据目录重叠')
        selector = 'literal' if path.suffix == '.json' else 'subpath'
        text += '(allow file-read* file-write* (' + selector + ' ' + json.dumps(str(path)) + '))\n'
    hidden=[config_home/name for name in ('config.toml','settings.json','settings.local.json','AGENTS.md','AGENTS.override.md','CLAUDE.md',
                                          'skills','rules','plugins','hooks','memories','instructions','environments.toml',
                                          'commands','agents','output-styles','workflows')]
    # Report absence, not a permission error: native loaders keep auth enabled
    # and use only the explicit PITR connection overrides supplied on argv.
    for path in hidden:
        text+='(deny file-read* file-write* (subpath '+json.dumps(str(path.resolve()))+') (with errno ENOENT))\n'
    readable = {Path(binary).resolve(), Path(sys.executable).resolve(), Path(sys.base_prefix).resolve()}
    # npm installs expose a JS launcher, which starts the platform binary from
    # its package. Allow only that distribution and the selected Node runtime.
    resolved=Path(binary).resolve()
    if 'node_modules' in resolved.parts:
        index=resolved.parts.index('node_modules')
        # Scoped CLI distributions use sibling platform packages, e.g.
        # @openai/codex and @openai/codex-darwin-arm64.
        readable.add(Path(*resolved.parts[:index+2]))
    node=shutil.which('node',path=env.get('PATH',''))
    if node:readable.add(Path(node).resolve())
    for key in ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_EXTRA_CA_CERTS'):
        if env.get(key):
            readable.add(Path(env[key]).resolve())
    for path in readable:
        selector = 'subpath' if path.is_dir() else 'literal'
        text += '(allow file-read* (' + selector + ' ' + json.dumps(str(path)) + '))\n'
    from urllib.parse import urlsplit
    endpoints=[env.get(key,'') for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'OPENAI_BASE_URL', 'ANTHROPIC_BASE_URL')]
    endpoints+=json.loads(env.get('PITR_AGENT_ENDPOINTS','[]'))
    for url in endpoints:
        endpoint = urlsplit(url)
        if endpoint.hostname in ('localhost', '127.0.0.1', '::1') and endpoint.port:
            text += '(allow network-outbound (remote ip "localhost:' + str(endpoint.port) + '"))\n'
    policy = root / 'sandbox.sb'
    policy.write_text(text); policy.chmod(0o600)
    probes = runtime_root(desk) / 'bridge-probes'
    probes.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = probes / 'private'
    private.write_text('canary')
    visible = root / 'allowed.txt'; visible.write_text('visible')
    # Probe an unrelated OS temp directory too, not just the guarded runtime
    # tree. Probe writes with O_EXCL and no data; never modify a database.
    with tempfile.TemporaryDirectory(prefix='pitr-isolation-check-') as outside:
        outsider = Path(outside) / 'private'; outsider.write_text('canary')
        code = '''import os,json
out={}
for label,path in %r:
 try:
  fd=os.open(path,os.O_RDONLY);os.close(fd);out[label]='readable'
 except PermissionError:out[label]='denied'
try:
 fd=os.open(%r,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd);out['private_write']='allowed'
except PermissionError:out['private_write']='denied'
print(json.dumps(out))
''' % ([('production', str(desk.store.path.resolve())), ('other_run', str(private)), ('outside_workspace', str(outsider)), ('input', str(visible))], str(probes / ('write-' + root.name)))
        check = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(policy), str(Path(sys.executable).resolve()), '-c', code],
                               cwd=root, capture_output=True, text=True, timeout=10)
    observed = json.loads(check.stdout) if check.returncode == 0 else {}
    result = {'mechanism': 'macOS Seatbelt + PITR capability', 'observed': observed,
              'passed': observed == {'production': 'denied', 'other_run': 'denied', 'outside_workspace': 'denied', 'input': 'readable', 'private_write': 'denied'}}
    (root / 'isolation.json').write_text(json.dumps(result))
    if not result['passed']:
        raise RuntimeError('本机 Agent 隔离自检失败，未启动研究')
    return ['/usr/bin/sandbox-exec', '-f', str(policy)], result
