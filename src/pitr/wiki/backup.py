"""Consistent SQLite snapshot plus verified content objects and original files."""
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from pitr.desk.storage import canonical


def backup(wiki, destination):
    destination=Path(destination).resolve()
    if destination.exists():
        raise ValueError('备份目标必须是不存在的新目录')
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.wiki-backup-',dir=destination.parent))
    try:
        with wiki.store.connect() as source:
            source.execute('BEGIN')
            sequence=source.execute('SELECT COALESCE(MAX(sequence),0) FROM wiki_events').fetchone()[0]
            target=sqlite3.connect(staging/'desk.sqlite')
            try:source.backup(target)
            finally:target.close()
            manifest={}
            for folder in ('objects','originals','snapshots'):
                root=wiki.store.root/folder
                if not root.exists():continue
                for path in root.rglob('*'):
                    if not path.is_file() or path.name.startswith('.pending-'):continue
                    relative=path.relative_to(wiki.store.root)
                    raw=path.read_bytes()
                    sha=hashlib.sha256(raw).hexdigest()
                    if folder=='objects' and path.parent.name+path.name!=sha:
                        raise ValueError('内容对象摘要损坏，备份未完成：'+str(relative))
                    out=staging/relative;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(raw)
                    manifest[str(relative)]=sha
            manifest['desk.sqlite']=hashlib.sha256((staging/'desk.sqlite').read_bytes()).hexdigest()
            (staging/'backup.json').write_text(canonical({'format':'pitr-wiki-backup.1','sequence':sequence,'files':manifest,
                'restore':'使用此目录作为 PITR_DESK_DIR，先执行 research wiki rebuild；恢复前核对 delivery_unknown 通知。'}))
        os.replace(staging,destination)
        return {'path':str(destination),'sequence':sequence,'files':len(manifest)}
    except Exception:
        shutil.rmtree(staging)
        raise
