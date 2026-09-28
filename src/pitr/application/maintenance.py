"""Rebuildable views and verified, model-free backup / restore."""
from pathlib import Path
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile

from pitr.domain.common import canonical, digest, utcnow
from pitr.domain.contracts import Run, ExportJob


def rebuild(store, operation_id):
    import jieba
    def apply(db):
        db.execute('DELETE FROM search')
        count=0
        for row in db.execute("SELECT * FROM revisions WHERE kind IN ('source','assertion','model','subject')"):
            body=json.loads(row['body']);title=body.get('title',body.get('name',''))
            text=body.get('statement','') or '\n'.join(b['text'] for b in body.get('blocks',[]))
            db.execute('INSERT INTO search VALUES(?,?,?,?,?)',(row['id'],row['revision'],row['kind'],title,' '.join(jieba.cut(title+' '+text))))
            count+=1
        store.event(db,'','views.rebuilt',{'count':count})
        return {'rebuilt':count}
    return store.once(operation_id, {'command':'views.rebuild'}, apply)


def backup(station):
    with tempfile.TemporaryDirectory(prefix='pitr-backup-') as directory:
        base=Path(directory)
        def copy_db(source,target):
            target.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(source) as left,sqlite3.connect(target) as right:left.backup(right)
        # News is copied first: every referenced main-store original already existed then.
        news=station.root/'lab/news/news.sqlite'
        if news.exists():copy_db(news,base/'lab/news/news.sqlite')
        slack=station.root/'channels/slack/slack.sqlite'
        if slack.exists():copy_db(slack,base/'channels/slack/slack.sqlite')
        copy_db(station.store.path,base/'research.sqlite')
        objects={}
        with sqlite3.connect(base/'research.sqlite') as db:
            for (body,) in db.execute('SELECT body FROM revisions'):
                value=json.loads(body)
                if value.get('digest') and len(value['digest'])==64:objects[value['digest']]=station.store.blob_path(value['digest'])
                render=value.get('manifest',{}).get('render',{})
                for sha in [render.get('pdf_digest'),*render.get('page_digests',[])]:
                    if sha:objects[sha]=station.store.blob_path(sha)
            for (body,) in db.execute('SELECT body FROM trace'):
                sha=json.loads(body).get('content_digest')
                if sha:objects[sha]=station.store.blob_path(sha)
            for (body,) in db.execute('SELECT body FROM runs'):
                for package in json.loads(body).get('checkpoint',{}).get('skills',[]):
                    if package.get('package_digest'):objects[package['package_digest']]=station.store.blob_path(package['package_digest'])
            for (body,) in db.execute("SELECT body FROM metadata WHERE key LIKE 'discovery:%'"):
                for receipt in json.loads(body).get('receipts',[]):
                    if receipt.get('digest'):objects[receipt['digest']]=station.store.blob_path(receipt['digest'])
            # Acquisition receipts returned by idempotent commands can also own blobs.
            def collect(value):
                if isinstance(value,dict):
                    sha=value.get('digest')
                    if isinstance(sha,str) and len(sha)==64 and station.store.blob_path(sha).is_file():
                        objects[sha]=station.store.blob_path(sha)
                    for item in value.values():collect(item)
                elif isinstance(value,list):
                    for item in value:collect(item)
            for (body,) in db.execute('SELECT body FROM commands'):collect(json.loads(body))
        files={p.relative_to(base).as_posix():p.read_bytes() for p in base.rglob('*.sqlite')}
        for sha,path in objects.items():
            raw=path.read_bytes()
            if digest(raw)!=sha:raise ValueError('备份发现内容对象损坏：'+sha)
            files['objects/'+sha[:2]+'/'+sha]=raw
        originals=station.root/'lab/news/originals'
        if originals.exists():
            for path in originals.iterdir():
                if path.is_file() and len(path.name)==64:
                    files[path.relative_to(station.root).as_posix()]=path.read_bytes()
        attachments=station.root/'channels/slack/attachments'
        if attachments.exists():
            for path in attachments.rglob('*'):
                if path.is_file():files[path.relative_to(station.root).as_posix()]=path.read_bytes()
        manifest={'schema':'research-backup.1','created_at':utcnow(),'files':{name:digest(raw) for name,raw in files.items()},
            'notes':['不包含本机模型登录凭据、Slack 凭据或浏览器会话','恢复后外部投递不会自动重发']}
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',canonical(manifest))
            for name,raw in files.items():archive.writestr(name,raw)
        return output.getvalue()


def restore(raw,target):
    target=Path(target).expanduser().resolve()
    if target.exists() and any(target.iterdir()):raise ValueError('恢复目标必须为空目录')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pitr-restore-',dir=target.parent) as directory:
        base=Path(directory)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(i.file_size for i in archive.infolist())>10_000_000_000:raise ValueError('备份展开大小超过限制')
            manifest=json.loads(archive.read('manifest.json'))
            if manifest['schema']!='research-backup.1':raise ValueError('备份格式不支持')
            if set(archive.namelist())!={'manifest.json',*manifest['files']} or len(archive.namelist())!=len(set(archive.namelist())):
                raise ValueError('备份文件清单不一致')
            for name,sha in manifest['files'].items():
                path=(base/name).resolve()
                if base.resolve() not in path.parents:raise ValueError('备份路径越界')
                content=archive.read(name)
                if digest(content)!=sha:raise ValueError('备份摘要不一致：'+name)
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        from .store import Store
        store=Store(base)
        with store.connect(write=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('数据库完整性检查失败')
            for row in db.execute('SELECT id,revision,kind FROM revisions'):
                from pitr.domain.contracts import Ref
                obj=store.get(Ref(id=row[0],revision=row[1]),row[2],db=db)
                if row[2] in ('source','artifact'):store.read_blob(obj.digest)
            missing=db.execute('SELECT 1 FROM dependencies d LEFT JOIN revisions r ON r.id=d.target AND r.revision=d.target_revision WHERE r.id IS NULL').fetchone()
            if missing:raise ValueError('恢复对象存在断开的引用')
            db.execute('UPDATE grants SET active=0')
            for (body,) in db.execute("SELECT body FROM runs WHERE status='running'"):
                run=Run.model_validate_json(body);run.status='queued';run.stage='restored';run.generation+=1
                db.execute('UPDATE runs SET status=?,owner=NULL,lease_until=NULL,generation=?,body=? WHERE id=?',('queued',run.generation,canonical(run),run.id))
            for (body,) in db.execute("SELECT body FROM exports WHERE status='running'"):
                job=ExportJob.model_validate_json(body);job.status='queued'
                db.execute('UPDATE exports SET status=?,owner=NULL,lease_until=NULL,body=? WHERE id=?',('queued',canonical(job),job.id))
            db.execute("UPDATE outbox SET status='held_after_restore' WHERE kind!='report_review' AND status NOT IN ('completed','sent')")
            db.execute("UPDATE outbox SET status='queued' WHERE kind='report_review' AND status='running'")
            store.event(db,'','system.restored',{'created_at':manifest['created_at']})
        slack=base/'channels/slack/slack.sqlite'
        if slack.exists():
            with sqlite3.connect(slack) as db:
                db.execute("UPDATE inbox SET status='held_after_restore',owner=NULL,lease=0 WHERE status NOT IN ('completed','rejected','ignored')")
                db.execute("UPDATE outbox SET status='held_after_restore',owner=NULL,lease=0 WHERE status!='sent'")
                # Keep bindings for the audit trail; restored bindings never trigger fresh deliveries.
                db.execute("INSERT OR REPLACE INTO state SELECT 'held_binding:'||adapter||':'||task_id,'true' FROM bindings")
        if target.exists():target.rmdir()
        shutil.copytree(base,target)
    return {'root':str(target),'files':len(manifest['files']),'external_delivery':'held'}
