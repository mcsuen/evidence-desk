"""Publish an atomic directory generation; readers can verify publication sequence."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .store import state
from .evidence import citation_anchor

TYPES = {'source': '来源解读', 'company': '公司', 'concept': '概念与方法', 'topic': '研究专题', 'analysis': '综合分析'}
STATUS = {'available': '可用', 'disputed': '有争议', 'needs_review': '待复核', 'quarantined': '已隔离', 'superseded': '被替代', 'withdrawn': '已撤回'}


def filename(revision):
    # Stable identity-derived names cannot escape the export directory.
    return hashlib.sha256(revision['id'].encode()).hexdigest()[:24] + '.md'


def render(wiki):
    root = wiki.store.root.resolve()
    generations = root / '.wiki-projections'
    generations.mkdir(exist_ok=True)
    with wiki.store.connect(write=True) as db:
        st = state(db)
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM wiki_events').fetchone()[0]
        generation = Path(tempfile.mkdtemp(prefix=f'{sequence}-', dir=generations))
        heads = {}
        for ref, rev in st['revisions'].items():
            if rev['id'] not in heads or rev['version'] > heads[rev['id']]['version']:
                heads[rev['id']] = {**rev, **st['status'].get(ref, {})}
        index = ['# 公司研究 Wiki', '', f'发布序列：{sequence}', '', '在 PITR 工作台编辑与审核。离线副本的状态需在引用前重新确认。', '']
        groups = {}
        for rev in heads.values():
            directory = 'schema' if rev['kind'] == 'policy' else ('knowledge' if rev['kind'] == 'knowledge' else 'pages')
            path = generation / directory / filename(rev)
            path.parent.mkdir(exist_ok=True)
            metadata = {k: rev.get(k) for k in ('id', 'version', 'company', 'kind', 'page_type', 'nature', 'published_at', 'policy', 'publication_sequence', 'availability', 'review_status')}
            content = ['---', *[f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in metadata.items()], '---', '', '# ' + rev['title'], '', rev['content'], '']
            if rev.get('scope'):
                content += ['适用范围：' + rev['scope'], '']
            for label, field in [('适用条件', 'applicability'), ('公式', 'formula'), ('失败情形', 'failure_cases'), ('案例', 'example')]:
                if rev.get(field):
                    content += ['## ' + label, '', rev[field], '']
            content += ['## 原始依据', '']
            for c in rev.get('citations', []):
                content += [f'<a id="{citation_anchor(c)}"></a>', f"- `{c['source_id']}` / `{c['block_id']}`：{c['quote']}", '']
            content += ['', '## 关联版本', '']
            for relation in rev.get('relations', []):
                target = relation['target']
                other = heads.get(target['id'])
                content += [f"- {relation['relation']}：{target['id']}@v{target['version']}" +
                    (f" · [当前页](../{'pages' if other['kind'] == 'page' else 'knowledge'}/{filename(other)})" if other else '')]
            path.write_text('\n'.join(content), encoding='utf-8')
            key = (rev['company'], TYPES.get(rev.get('page_type'), '知识条目' if rev['kind'] == 'knowledge' else '维护规范'))
            groups.setdefault(key, []).append((rev, str(path.relative_to(generation))))
        for (company, kind), entries in sorted(groups.items()):
            index += [f'## {company} · {kind}', '']
            for rev, path in sorted(entries, key=lambda item: item[0]['title']):
                index += [f"- [{rev['title']}]({path}) · v{rev['version']} · {STATUS.get(rev.get('availability'), '待复核')} — {rev.get('summary') or rev['content'].splitlines()[0][:100]}"]
            index += ['']
        log = ['# 维护日志', '', f'发布序列：{sequence}', '']
        for event in db.execute('SELECT * FROM wiki_events ORDER BY sequence'):
            payload = json.loads(wiki.objects.get(event['payload_object']))
            log += [f"- {event['occurred_at']} · {event['company']} · {event['kind']} · 序列 {event['sequence']}" +
                    (' — ' + payload['details']['reason'] if payload['details'].get('reason') else '')]
        (generation / 'index.md').write_text('\n'.join(index), encoding='utf-8')
        (generation / 'log.md').write_text('\n'.join(log), encoding='utf-8')
        manifest = {}
        for path in generation.rglob('*.md'):
            manifest[str(path.relative_to(generation))] = hashlib.sha256(path.read_bytes()).hexdigest()
            path.chmod(0o444)
        (generation / 'manifest.json').write_text(json.dumps({'sequence': sequence, 'files': manifest}, sort_keys=True), encoding='utf-8')
        pending = root / ('.wiki-link-' + generation.name)
        pending.symlink_to(generation.relative_to(root), target_is_directory=True)
        if wiki.markdown.exists() and not wiki.markdown.is_symlink():
            pending.unlink()
            raise ValueError('wiki 路径已存在用户目录，请先选择独立导出位置')
        os.replace(pending, wiki.markdown)
        db.execute('INSERT OR REPLACE INTO wiki_projection_meta VALUES(?,?)', ('markdown_sequence', str(sequence)))
    return {'sequence': sequence, 'path': str(wiki.markdown.absolute())}
