"""Continue ./start using the private Python. No global package installation."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

REPO=Path(__file__).resolve().parents[1]
PRIVATE=REPO/'.pitr'
NODE_VERSION='24.13.0'
NODE_HASHES={'arm64':'d595961e563fcae057d4a0fb992f175a54d97fcc4a14dc2d474d92ddeea3b9f8',
             'x86_64':'6f03c1b48ddbe1b129a6f8038be08e0899f05f17185b4d3e4350180ab669a7f3'}


def fingerprint(paths):
    h=hashlib.sha256()
    for path in sorted(paths):
        h.update(str(path.relative_to(REPO)).encode());h.update(b'\0');h.update(path.read_bytes());h.update(b'\0')
    return h.hexdigest()


def main():
    PRIVATE.mkdir(exist_ok=True,mode=0o700)
    env=dict(os.environ)
    env.update(UV_PROJECT_ENVIRONMENT=str(PRIVATE/'venv'),UV_CACHE_DIR=str(PRIVATE/'cache/uv'),
               UV_PYTHON_INSTALL_DIR=str(PRIVATE/'python'),UV_PYTHON_PREFERENCE='only-managed')
    uv=PRIVATE/'uv-0.12.13/uv'
    node=PRIVATE/f'node-{NODE_VERSION}'
    with (PRIVATE/'install.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not (node/'bin/node').exists():
            print('正在安装私有 Node.js…',flush=True)
            arch=platform.machine();asset=f'node-v{NODE_VERSION}-darwin-{"arm64" if arch=="arm64" else "x64"}'
            with tempfile.TemporaryDirectory(dir=PRIVATE) as folder:
                archive=Path(folder)/'node.tar.gz'
                # curl uses macOS trust/proxy configuration before Python certs exist.
                subprocess.run(['curl','--fail','--location','--retry','3','--proto','=https','--tlsv1.2',
                    f'https://nodejs.org/dist/v{NODE_VERSION}/{asset}.tar.gz','-o',str(archive)],check=True)
                if hashlib.sha256(archive.read_bytes()).hexdigest()!=NODE_HASHES[arch]:raise RuntimeError('Node.js 下载校验失败')
                with tarfile.open(archive) as bundle:bundle.extractall(folder,filter='data')
                shutil.move(str(Path(folder)/asset),node)
        env['PATH']=str(node/'bin')+os.pathsep+env.get('PATH','/usr/bin:/bin')
        stamp=PRIVATE/'installed.json'
        try:installed=json.loads(stamp.read_text())
        except (FileNotFoundError,ValueError):installed={}
        dependencies=fingerprint([REPO/'pyproject.toml',REPO/'uv.lock'])+sys.version+platform.machine()
        if installed.get('python')!=dependencies or not (PRIVATE/'venv/bin/python').exists():
            print('正在安装项目依赖…',flush=True)
            subprocess.run([str(uv),'sync','--frozen','--python',sys.executable,'--no-progress'],cwd=REPO,env=env,check=True)
            installed['python']=dependencies
        npm=fingerprint([REPO/'web/package.json',REPO/'web/package-lock.json'])+NODE_VERSION
        if installed.get('npm')!=npm or not (REPO/'web/node_modules').exists():
            print('正在安装界面依赖…',flush=True)
            subprocess.run([str(node/'bin/npm'),'ci','--no-audit','--no-fund'],cwd=REPO/'web',env=env,check=True)
            installed['npm']=npm
        def inputs():
            paths=[p for folder in ('src','public','scripts') for p in (REPO/'web'/folder).rglob('*') if p.is_file() and 'src/types' not in str(p.relative_to(REPO/'web'))]
            return paths+list((REPO/'schemas').glob('*.json'))+[p for p in (REPO/'web').iterdir() if p.is_file() and p.suffix in ('.json','.ts','.html')]
        frontend=fingerprint(inputs())
        if installed.get('frontend')!=frontend or not (REPO/'web/dist/index.html').exists():
            print('正在构建 WebUI…',flush=True)
            subprocess.run([str(node/'bin/npm'),'run','build'],cwd=REPO/'web',env=env,check=True)
            installed['frontend']=fingerprint(inputs())
        temporary=stamp.with_suffix('.tmp');temporary.write_text(json.dumps(installed));temporary.replace(stamp)
    python=PRIVATE/'venv/bin/python'
    os.chdir(REPO)
    os.execve(str(python),[str(python),'-m','pitr.agent_runtime.daemon',*sys.argv[1:]],env)


if __name__=='__main__':
    try:main()
    except (RuntimeError,subprocess.CalledProcessError) as error:
        print(f'启动未完成：{error}\n可再次运行 ./start，已下载的环境会保留。',file=sys.stderr)
        sys.exit(1)
