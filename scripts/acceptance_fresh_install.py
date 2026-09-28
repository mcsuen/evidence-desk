#!/usr/bin/env python3
"""Install into an empty project, start, restore, and download frozen historical bytes."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pitr.application.service import Workstation
from pitr.application.maintenance import backup,restore
from pitr.cli.main import request
from pitr.domain.common import digest

ROOT=Path(__file__).resolve().parents[1]


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(25)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()


def wait_ready(process,data,timeout):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Fresh startup exited; inspect its private installation log')
        if (data/'research.sqlite').exists():
            try:
                raw,_=request(data,'/health')
                if json.loads(raw)['status']=='ok':return
            except (OSError,ValueError,RuntimeError):pass
        time.sleep(1)
    raise TimeoutError('Fresh installation/start exceeded its acceptance deadline')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-root',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();base=Path(tempfile.mkdtemp(prefix='pitr-fresh-acceptance-'));project=base/'project';project.mkdir()
    for name in ('start','pyproject.toml','uv.lock','README.md','THIRD_PARTY_NOTICES.md','.gitignore'):
        shutil.copy2(ROOT/name,project/name)
    for name in ('src','web','scripts','schemas','services','docs','benchmarks'):
        shutil.copytree(ROOT/name,project/name,ignore=shutil.ignore_patterns('node_modules','dist','__pycache__','test-results*','playwright-report'))
    data=base/'empty-data';log=base/'installation.log'
    port=18889
    with log.open('w') as output:
        process=subprocess.Popen(['./start','--data-dir',str(data),'--port',str(port),'--no-open'],cwd=project,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            wait_ready(process,data,1200)
            subjects=json.loads(request(data,'/subjects')[0]);assert subjects==[]
            health=json.loads(request(data,'/health')[0]);assert health['schema']=='research.1'
            doctor=subprocess.run([str(project/'.pitr/venv/bin/research'),'doctor'],cwd=project,capture_output=True,text=True,check=True)
            dependencies=json.loads(doctor.stdout);assert dependencies['renderer']['available'] and dependencies['font']['available']
        finally:stop(process)
        source=Workstation(args.source_root,runtime=False);raw=backup(source);archive=base/'backup.zip';archive.write_bytes(raw)
        restored=base/'restored-data';recovery=restore(raw,restored)
        before={artifact.id:artifact.digest for artifact in source.store.list('artifact')}
        after=Workstation(restored,runtime=False)
        assert all(after.store.get(aid,'artifact').digest==sha for aid,sha in before.items())
        process=subprocess.Popen(['./start','--data-dir',str(restored),'--port',str(port),'--no-open'],cwd=project,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            wait_ready(process,restored,120)
            for aid,sha in before.items():
                downloaded,_=request(restored,'/artifacts/'+aid+'/download');assert digest(downloaded)==sha
            assert len(source.store.list('report',all_revisions=True))==len(after.store.list('report',all_revisions=True))
            with after.store.connect() as db:assert not db.execute("SELECT 1 FROM runs WHERE status IN ('running','queued')").fetchone()
        finally:stop(process)
    result={'project':str(project),'empty_install':'passed','empty_start':'passed','doctor':dependencies,
        'restore':'passed','history_download':'passed','artifacts_verified':len(before),'reports_verified':len(source.store.list('report',all_revisions=True)),
        'restored':str(restored),'backup_sha256':digest(raw),'model_reexecution':False,'external_redelivery':False,
        'private_installation_log':str(log)}
    destination=Path(args.output);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
