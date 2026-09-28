from __future__ import annotations
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np
from pitr.domain.common import utcnow
from pitr.domain.common import canonical, digest, uid
from .acquire import DEFAULT_SOURCES, canonical_url, extract, list_items
from .contracts import *
from .profiles import profiles, passages, alias_matches
from .runtime import LocalJudge
from .store import NewsStore

WEIGHTS = {'relevance': .30, 'materiality': .30, 'research_impact': .25, 'novelty': .10, 'freshness': .05}
POLICY = 'news-priority.1'


class News:
    def __init__(self, station, judge=None):
        self.station = station
        self.store = NewsStore(station.root)
        self.judge = judge or LocalJudge()
        self.cluster_identities = None

    def settings(self):
        saved = self.store.get('settings')
        if saved is not None: return NewsSettings.model_validate(saved)
        sources = [NewsSource(**s) for s in DEFAULT_SOURCES]
        return NewsSettings(sources=sources)

    def configure(self, request):
        from pitr.adapters.sources.protocol import adapter
        companies = {s.id for s in self.station.store.list('subject')}
        if any(c not in companies for c in request.settings.companies): raise ValueError('覆盖公司不存在')
        for source in request.settings.sources:
            if source.kind == 'rss': canonical_url(source.url)
            if source.kind == 'disclosure':
                adapter(source.adapter)
                if source.company not in companies: raise ValueError('公告公司不存在')
        def save(db):
            db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)', ('settings', canonical(request.settings)))
            return request.settings.model_dump()
        return self.store.once(request, save)

    def enqueue(self, request):
        def insert(db):
            # Manual retries and scheduled work coalesce while the same work is active.
            for row in db.execute("SELECT body FROM runs WHERE status IN ('queued','running')"):
                body = json.loads(row['body'])
                if body['kind'] == request.kind: return body
            body = {'id': uid('newsrun'), 'kind': request.kind, 'status': 'queued', 'created_at': utcnow(), 'progress': {}, 'error': ''}
            db.execute('INSERT INTO runs VALUES(?,?,0,?,?)', (body['id'], 'queued', '', canonical(body)))
            return body
        return self.store.once(request, insert)

    def vectors(self, texts):
        keys = [digest(['e5-614241f6', t]) for t in texts]
        with self.store.connect() as db:
            cached = {k: json.loads(r[0]) for k in set(keys) if (r := db.execute('SELECT body FROM vectors WHERE id=?', (k,)).fetchone())}
        missing = {k: t for k, t in zip(keys, texts) if k not in cached}
        if missing:
            encoded = self.judge.encode(list(missing.values()))
            if len(encoded) != len(missing): raise ValueError('语义模型返回数量不一致')
            with self.store.connect(write=True) as db:
                for k, v in zip(missing, encoded):
                    vector = np.asarray(v, dtype=float)
                    if vector.ndim != 1 or not np.isfinite(vector).all() or not np.linalg.norm(vector): raise ValueError('无效语义向量')
                    value = (vector / np.linalg.norm(vector)).tolist()
                    db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?)', (k, canonical(value)))
                    cached[k] = value
        return np.asarray([cached[k] for k in keys], dtype=float)

    def freeze_profiles(self):
        result = profiles(self.station, self.settings().companies)
        with self.store.connect(write=True) as db:
            for p in result: db.execute('INSERT OR IGNORE INTO profiles VALUES(?,?,?)', (p.id, p.company, canonical(p)))
        self.store.set('context_coverage', [{'company': p.company, 'name': p.name, 'profile_id': p.id, 'items': len(p.items)} for p in result])
        return result

    def _cluster(self, article):
        if self.cluster_identities is None:
            self.cluster_identities = {s.id:s.model_dump() for s in self.station.store.list('subject')}
        def entities(body):
            found = set()
            for company, identity in self.cluster_identities.items():
                aliases = [company, identity['name'], *identity.get('brands', [])]
                aliases += [a if isinstance(a, str) else a.get('text', '') for a in identity.get('aliases', [])]
                if alias_matches(body['title']+' '+body.get('text', ''), [a for a in aliases if a]): found.add(company)
            return found
        with self.store.connect() as db:
            has_body = bool(article['original_file']) and len(article['text'].strip()) >= 80
            exact = db.execute("SELECT event_id FROM articles WHERE url=? OR (? AND (digest=? OR json_extract(body,'$.content_digest')=?)) ORDER BY rowid LIMIT 1", (article['url'], has_body, article['digest'], article['content_digest'])).fetchone()
            if exact: return exact[0]
            recent = db.execute('SELECT * FROM events WHERE updated_at>? ORDER BY updated_at DESC LIMIT 150', ((datetime.now(timezone.utc)-timedelta(days=3)).isoformat(),)).fetchall()
            candidates = []
            known = entities(article)
            for event in recent:
                row = db.execute('SELECT body FROM articles WHERE event_id=? ORDER BY rowid DESC LIMIT 1', (event['id'],)).fetchone()
                prior = json.loads(row[0])
                other = entities(prior)
                if known and other and not known.intersection(other): continue
                if article.get('published_at') and prior.get('published_at'):
                    gap = abs((datetime.fromisoformat(article['published_at'])-datetime.fromisoformat(prior['published_at'])).total_seconds())
                    if gap > 3*86400: continue
                candidates.append(event)
            recent = candidates
        if recent and self.judge.ready:
            try:
                vectors = self.vectors(['passage: '+article['title'], *['passage: '+e['title'] for e in recent]])
                similarities = vectors[1:] @ vectors[0]
                best = int(similarities.argmax())
                if similarities[best] >= .94: return recent[best]['id']
            except Exception:
                pass  # Exact dedup still works; semantic runtime state is recorded by scoring.
        return uid('event')

    def add_article(self, source, item, raw, media, text, issues=()):
        now = utcnow()
        url = canonical_url(item['url'])
        sha = hashlib.sha256(raw or text.encode()).hexdigest()
        content_sha = digest(' '.join(text.split()))
        identity = 'article_'+digest([url, sha, content_sha, item.get('published_at'), item.get('title')])[:24]
        with self.store.connect() as db:
            row = db.execute('SELECT body FROM articles WHERE id=?', (identity,)).fetchone()
            if row: return NewsArticle.model_validate_json(row[0]), False
            for row in db.execute('SELECT body FROM articles WHERE url=? ORDER BY rowid DESC', (url,)):
                prior = NewsArticle.model_validate_json(row[0])
                same_text = (prior.content_digest or digest(' '.join(prior.text.split()))) == content_sha
                if same_text and bool(prior.original_file) == bool(raw) and prior.published_at == item.get('published_at') and prior.title == (item.get('title') or url):
                    return prior, False
        issues = list(issues)
        if len(text) > 100_000: issues.append('原文超过处理上限，本次只检索前 100,000 字符；原件完整保留')
        original = ''
        if raw:
            original = sha
            path = self.store.originals / sha
            if not path.exists():
                temp = path.with_name(path.name+'.'+uid('tmp'))
                with temp.open('wb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                temp.replace(path)
        body = dict(id=identity, event_id='', source_id=source.id, source_name=source.name, title=item.get('title') or url,
                    url=url, published_at=item.get('published_at'), observed_at=now, text=text[:100_000], excerpt=item.get('excerpt', '')[:3000],
                    digest=sha, content_digest=content_sha, media=media, original_file=original, publication_source=item.get('publication_source', 'content'), issues=issues)
        body['event_id'] = self._cluster(body)
        article = NewsArticle(**body)
        with self.store.connect(write=True) as db:
            db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)', (article.event_id, article.title, now, now))
            db.execute('UPDATE events SET updated_at=? WHERE id=?', (now, article.event_id))
            db.execute('INSERT OR IGNORE INTO articles VALUES(?,?,?,?,?,?)', (identity, article.event_id, url, sha, now, canonical(article)))
        return article, True

    def collect(self, fence=lambda: None, progress=lambda value: None, fetch=None):
        from pitr.adapters.public_fetch import fetch_public
        from pitr.integrations.slack.settings import SettingsFile
        contact = SettingsFile(self.station.root / 'private/settings.json').read().get('sec_user_agent', '')
        fetch = fetch or (lambda url, **kw: fetch_public(url, timeout=20, contact=contact, **kw))
        settings = self.settings()
        self.cluster_identities = None
        summary = {'acquired': 0, 'unchanged': 0, 'errors': 0, 'scored': 0}
        day = datetime.now(ZoneInfo('Asia/Shanghai')).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        with self.store.connect() as db: remaining = max(0, settings.daily_limit-db.execute('SELECT count(*) FROM articles WHERE observed_at>=?', (day,)).fetchone()[0])
        for source in settings.sources:
            if not source.enabled: continue
            fence()
            log = {'source_id': source.id, 'name': source.name, 'at': utcnow(), 'acquired': 0, 'errors': [], 'truncated': False}
            try:
                # Keep failed original downloads retryable even after the feed has rotated.
                with self.store.connect() as db:
                    latest = {}
                    for row in db.execute('SELECT body FROM articles ORDER BY rowid DESC'):
                        body = json.loads(row[0])
                        if body['source_id'] == source.id: latest.setdefault(body['url'], body)
                pending = [a for a in latest.values() if not a['original_file']]
                listed = True
                try:
                    fresh = list_items(source, self.station, fetch, since=self.store.get('source:'+source.id, {}).get('last_success', ''))
                except Exception as error:
                    if not pending: raise
                    fresh = []; listed = False
                    log['errors'].append(str(error)[:1000])
                urls = {a['url'] for a in fresh}
                items = fresh+[a for a in pending if a['url'] not in urls]
                log['listed'] = len(items)
                log['truncated'] = (source.kind == 'gdelt' and len(items) >= 250) or len(items) > remaining
                if remaining <= 0: log['errors'].append('已达到今日处理上限，待下次采集')
                for item in items:
                    if remaining <= 0: break
                    fence()
                    raw, media = b'', 'text/plain'
                    issues = []
                    try:
                        raw, media, _, _ = fetch(item['url'])
                        text = extract(raw, media)
                        if len(text.strip()) < 80: issues.append('正文不足，需打开原文核对')
                    except Exception as error:
                        text = item.get('excerpt', '')
                        issues.append('正文获取失败：'+str(error)[:500])
                        log['errors'].append(item['url']+'：'+str(error)[:250])
                    fence()
                    article, added = self.add_article(source, item, raw, media, text, issues)
                    if added:
                        remaining -= 1; summary['acquired'] += 1; log['acquired'] += 1
                    else: summary['unchanged'] += 1
                    progress(summary)
                log['last_success'] = utcnow() if listed else self.store.get('source:'+source.id, {}).get('last_success')
            except Exception as error:
                log['errors'].append(str(error)[:1000])
                log['last_success'] = self.store.get('source:'+source.id, {}).get('last_success')
            summary['errors'] += len(log['errors'])
            self.store.set('source:'+source.id, log)
            with self.store.connect(write=True) as db:
                db.execute('INSERT INTO source_log(source_id,at,body) VALUES(?,?,?)', (source.id, log['at'], canonical(log)))
        summary.update(self.rescore(fence, progress))
        return summary

    def rescore(self, fence=lambda: None, progress=lambda value: None, *, force=False):
        profile_list = self.freeze_profiles()
        with self.store.connect() as db:
            rows = db.execute('SELECT body FROM articles WHERE observed_at>? AND rowid IN (SELECT max(rowid) FROM articles GROUP BY url) ORDER BY observed_at DESC LIMIT 10000',
                              ((datetime.now(timezone.utc)-timedelta(days=7)).isoformat(),)).fetchall()
        count = 0
        for row in rows:
            fence()
            count += self.score_article(NewsArticle.model_validate_json(row[0]), profile_list, fence, force=force)
            progress({'scored': count})
        return {'scored': count}

    def score_article(self, article, profile_list, fence=lambda: None, *, force=False):
        blocks = passages(article.title+'\n'+article.text)
        candidates = []
        retrieval_error = ''
        block_vectors = None
        if self.judge.ready and profile_list:
            try: block_vectors = self.vectors(['passage: '+b['text'] for b in blocks])
            except Exception as error: retrieval_error = str(error)
        for profile in profile_list:
            direct = bool(alias_matches(article.title+' '+article.text, profile.aliases))
            entries = [{**item, **part} for item in profile.items for part in passages(item['title']+'\n'+item['text'])]
            if not entries: entries = [{'ref': '', 'kind': 'identity', 'title': profile.name, 'text': profile.name, 'start': 0, 'end': len(profile.name)}]
            value, pairings = float(direct), [(0, 0)]
            if block_vectors is not None:
                try:
                    context_vectors = self.vectors(['query: '+profile.name+' '+entry['text'] for entry in entries])
                    sim = block_vectors @ context_vectors.T
                    best = sorted(np.ndindex(sim.shape), key=lambda ij: -sim[ij])[:3]
                    value = max(value, float(sim[best[0]]))
                    pairings = best
                except Exception as error: retrieval_error = str(error)
            if direct or value >= .78: candidates.append((value, direct, profile, entries, pairings))
        candidates.sort(key=lambda v: (-v[0], v[2].company))
        candidates = [c for i, c in enumerate(candidates) if i < 3 or c[1]]
        ambiguous = set()
        hits = {}
        for _, direct, profile, _, _ in candidates:
            if direct:
                for alias in alias_matches(article.title+' '+article.text, profile.aliases):
                    hits.setdefault(alias.casefold(), set()).add(profile.company)
        for companies in hits.values():
            if len(companies) > 1: ambiguous.update(companies)
        if not candidates: candidates = [(0, False, None, [], [])]
        count = 0
        for value, direct, profile, entries, pairs in candidates:
            fence()
            profile_id = profile.id if profile else ''
            # Pinned model version is stable before and after its first warm-up.
            signature = digest([article.id, profile_id, POLICY, 'laya-1c5edc17', utcnow()[:10]])
            with self.store.connect() as db:
                old = db.execute('SELECT body FROM scores WHERE signature=? ORDER BY rowid DESC LIMIT 1', (signature,)).fetchone()
            prior_score = json.loads(old[0]) if old else None
            retryable = prior_score and any(reason.startswith(('语义召回不可用', '本地推理失败')) for reason in prior_score.get('reasons', []))
            if prior_score and prior_score.get('priority') is not None and not force and not retryable: continue
            reasons = list(article.issues)
            if not article.original_file: reasons.append('仅有订阅摘要，尚无新闻正文原件')
            if not profile: reasons.append('尚未匹配公司研究框架，可从全部新闻抽查')
            elif not profile.items: reasons.append('公司尚无可用研究条目，需要补充公司认识')
            if profile and profile.company in ambiguous: reasons.append('同名或别名匹配到多家公司，需核对实体身份')
            if retrieval_error: reasons.append('语义召回不可用：'+retrieval_error)
            if not self.judge.ready: reasons.append('本地模型尚未安装')
            score = NewsScore(id=uid('score'), event_id=article.event_id, article_id=article.id, company=profile.company if profile else '',
                             profile_id=profile_id, created_at=utcnow(), signature=signature, reasons=reasons)
            if profile and profile.items and article.original_file and len(article.text.strip()) >= 80 and self.judge.ready:
                try:
                    decisions = []
                    for bi, ei in pairs:
                        fence()
                        entry, block = entries[ei], blocks[bi]
                        response = self.judge.predict('Company: '+profile.name+'; aliases: '+', '.join(profile.aliases)+'\n'+entry['text'], block['text'])
                        answers = response['result']['answers']
                        dims = {key: float(answers[key]['noul']) for key in ('relevance', 'materiality', 'research_impact')}
                        conf = {key: float(answers[key]['confidence']) for key in dims}
                        if not all(math.isfinite(v) and 0 <= v <= 1 for v in [*dims.values(), *conf.values()]): raise ValueError('模型分数超出范围')
                        decisions.append((sum(WEIGHTS[k]*v for k, v in dims.items()), dims, conf))
                        score.inputs.append({'article_id': article.id, 'passage': block, 'reference': entry,
                                             'state': response['state'], 'input_tokens': response['input_tokens'], 'state_budget': response['state_budget']})
                        score.raw.append(response['result'])
                        score.references.append({k: v for k, v in entry.items() if k not in ('text', 'start', 'end')})
                        score.model = {k: response[k] for k in ('model', 'sdk', 'device')}
                    _, dims, conf = max(decisions, key=lambda d: d[0])
                    with self.store.connect() as db:
                        prior = db.execute('SELECT body FROM articles WHERE event_id=? AND observed_at<? ORDER BY observed_at DESC LIMIT 1', (article.event_id, article.observed_at)).fetchone()
                    novelty = 1.0
                    if prior:
                        prior_text = json.loads(prior[0])['text']
                        from difflib import SequenceMatcher
                        novelty = 1-SequenceMatcher(None, prior_text[:30000], article.text[:30000], autojunk=True).ratio()
                    freshness = .5
                    if article.published_at:
                        age = (datetime.now(timezone.utc)-datetime.fromisoformat(article.published_at)).total_seconds()/3600
                        if age < -1: score.reasons.append('来源发布时间晚于当前时间，需核对')
                        freshness = math.exp(-max(0, age)/48)
                    else: score.reasons.append('来源发布时间未知')
                    score.dimensions = {**dims, 'novelty': novelty, 'freshness': freshness}
                    score.confidence = conf
                    score.priority = round(100*sum(WEIGHTS[k]*v for k, v in score.dimensions.items()), 1)
                    if min(conf.values()) < .6: score.reasons.append('模型判断不确定，需人工确认')
                    score.queue = 'uncertain' if score.reasons else 'selected' if score.priority >= 60 and dims['relevance'] >= .5 else 'all'
                    self.store.set('runtime', {**score.model, 'last_success': utcnow(), 'error': ''})
                except Exception as error:
                    score.reasons.append('本地推理失败：'+str(error)[:1000])
                    self.store.set('runtime', {'error': str(error)[:1000], 'last_attempt': utcnow()})
            # Pending results are append-only too; repeated identical failures are coalesced.
            if old and score.priority is None and score.reasons == json.loads(old[0]).get('reasons'): continue
            fence()
            with self.store.connect(write=True) as db:
                db.execute('INSERT INTO scores VALUES(?,?,?,?,?,?)', (score.id, score.event_id, score.company, score.created_at, signature, canonical(score)))
            count += 1
        return count

    def _event(self, db, row, company=''):
        scores = [NewsScore.model_validate_json(r[0]) for r in db.execute('SELECT s.body FROM scores s JOIN articles a ON a.id=json_extract(s.body,\'$.article_id\') WHERE s.event_id=? AND a.rowid IN (SELECT max(rowid) FROM articles GROUP BY url) ORDER BY a.observed_at DESC,s.rowid DESC', (row['id'],))]
        latest = {}
        for score in scores: latest.setdefault(score.company, score)
        relevant = [s for c, s in latest.items() if not company or c == company]
        chosen = max(relevant, key=lambda s: (s.priority is not None, s.priority or 0), default=None)
        return NewsEvent(**dict(row), article_count=db.execute('SELECT count(*) FROM articles WHERE event_id=?', (row['id'],)).fetchone()[0],
                         score=chosen, companies=sorted(c for c in latest if c))

    def events(self, company='', queue='selected', date='', offset=0, limit=50, order='high'):
        if queue not in ('selected', 'uncertain', 'all'): raise ValueError('未知新闻队列')
        if order not in ('high', 'low'): raise ValueError('未知新闻排序')
        if date:
            start = datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc)
        else: start = datetime.now(timezone.utc)-timedelta(hours=24)
        end = start+timedelta(days=1) if date else datetime.now(timezone.utc)+timedelta(seconds=1)
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE updated_at>=? AND updated_at<? ORDER BY updated_at DESC', (start.isoformat(), end.isoformat())).fetchall()
            items = [self._event(db, r, company) for r in rows]
        items = [e for e in items if not company or company in e.companies]
        items.sort(key=lambda e: (-(e.score.priority if e.score and e.score.priority is not None else -1), e.id))
        selected = [e for e in items if e.score and e.score.queue == 'selected'][:20]
        uncertain = [e for e in items if not e.score or e.score.queue == 'uncertain']
        groups = {'selected': selected, 'uncertain': uncertain, 'all': items}
        found = groups[queue]
        if queue == 'all' and order == 'low':
            found = sorted(found, key=lambda e: (e.score.priority if e.score and e.score.priority is not None else 101, e.id))
        return NewsEvents(items=found[offset:offset+limit], total=len(found), offset=offset, counts={k: len(v) for k, v in groups.items()})

    def detail(self, event_id, score_id='', company=''):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
            if not row: raise KeyError('新闻事件不存在')
            event = self._event(db, row, company)
            articles = [NewsArticle.model_validate_json(r[0]) for r in db.execute('SELECT body FROM articles WHERE event_id=? ORDER BY observed_at DESC', (event_id,))]
            scores = [NewsScore.model_validate_json(r[0]) for r in db.execute('SELECT s.body FROM scores s JOIN articles a ON a.id=json_extract(s.body,\'$.article_id\') WHERE s.event_id=? ORDER BY a.observed_at DESC,s.rowid DESC', (event_id,))]
            selected = next((s for s in scores if s.id == score_id), None) if score_id else event.score
            if score_id and not selected: raise KeyError('该事件下不存在指定评分版本')
            profile = db.execute('SELECT body FROM profiles WHERE id=?', (selected.profile_id,)).fetchone() if selected else None
            current_ids = {r[0] for r in db.execute('SELECT id FROM articles WHERE event_id=? AND rowid IN (SELECT max(rowid) FROM articles GROUP BY url)', (event_id,))}
            latest = next((s for s in scores if selected and s.company == selected.company and s.article_id in current_ids), None) or event.score
            feedback = [json.loads(r[0]) for r in db.execute('SELECT body FROM feedback WHERE event_id=? ORDER BY rowid DESC', (event_id,))]
        return NewsDetail(event=event, articles=articles, scores=scores, selected=selected, latest_score_id=latest.id if latest else None,
                          profile=NewsProfile.model_validate_json(profile[0]) if profile else None, feedback=feedback)

    def feedback(self, event_id, request):
        detail = self.detail(event_id, request.score_id)
        def save(db):
            body = {'id': uid('feedback'), 'event_id': event_id, 'score_id': detail.selected.id,
                    'company': detail.selected.company, 'verdict': request.verdict, 'note': request.note, 'at': utcnow(), 'annotator': 'human'}
            db.execute('INSERT INTO feedback VALUES(?,?,?,?)', (body['id'], event_id, request.score_id, canonical(body)))
            return body
        return self.store.once(request, save)

    def draft(self, event_id, request):
        detail = self.detail(event_id, request.score_id)
        score = detail.selected
        if not score or not score.company: raise ValueError('请先选择已有公司评分，再转入研究')
        selected = [a for a in detail.articles if a.id in (request.article_ids or [score.article_id])]
        if request.article_ids and set(request.article_ids) != {a.id for a in selected}: raise ValueError('所选新闻不属于该事件')
        if not selected or any(not a.original_file for a in selected): raise ValueError('所选新闻缺少正文原件，请补采或选择其他报道')
        from pitr.domain.contracts import Ref
        refs = [Ref(id=key.rsplit('@',1)[0],revision=int(key.rsplit('@',1)[1]))
                for key in dict.fromkeys(r['ref'] for r in score.references if r.get('kind') in ('knowledge','relation','model'))]
        titles = '；'.join(dict.fromkeys(r['title'] for r in score.references))
        def save(db):
            materials = []
            # Check the operation before touching the main store. Content addressing
            # also makes recovery safe across a crash between the two databases.
            for article in selected:
                raw = (self.store.originals / article.original_file).read_bytes()
                if hashlib.sha256(raw).hexdigest() != article.digest: raise ValueError('新闻原件摘要不一致')
                doc = self.station.import_source(raw, article.media, url=article.url, subjects=[score.company],title=article.title,
                    published_at=article.published_at,operation_id='news-import:'+article.id+':'+score.company,extend_subjects=True)
                if not any(m['source'] == doc.ref for m in materials):
                    materials.append({'source': doc.ref, 'title': article.title, 'url': article.url})
            draft = NewsResearchDraft(id=uid('newsdraft'), company=score.company,
                question=f'核对新闻“{detail.event.title}”对 {score.company} 的影响。结合{titles or "现有公司研究框架"}，区分已证实变化、反证与仍待核实的问题。',
                event_id=event_id, score_id=score.id, profile_id=score.profile_id, created_at=utcnow(), materials=materials, knowledge=refs,
                context={'news_origin': {'event_id': event_id, 'score_id': score.id, 'profile_id': score.profile_id,
                         'article_ids': [a.id for a in selected], 'experimental': True}})
            db.execute('INSERT INTO drafts VALUES(?,?)', (draft.id, canonical(draft)))
            return draft.model_dump()
        return self.store.once(request, save)

    def get_draft(self, draft_id):
        with self.store.connect() as db: row = db.execute('SELECT body FROM drafts WHERE id=?', (draft_id,)).fetchone()
        if not row: raise KeyError('新闻研究草稿不存在')
        return NewsResearchDraft.model_validate_json(row[0])

    def status(self):
        settings = self.settings()
        with self.store.connect() as db:
            runs = [json.loads(r[0]) for r in db.execute('SELECT body FROM runs ORDER BY rowid DESC LIMIT 30')]
            counts = {name: db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('articles', 'events', 'scores', 'feedback')}
            labels = db.execute('SELECT count(DISTINCT event_id) FROM feedback').fetchone()[0]
            histories = {source.id: [json.loads(r[0]) for r in db.execute('SELECT body FROM source_log WHERE source_id=? ORDER BY id DESC LIMIT 5', (source.id,))] for source in settings.sources}
        runtime = {'installed': self.judge.ready, 'calibration': '未校准', 'context_coverage': self.store.get('context_coverage', []), **self.store.get('runtime', {}), **getattr(self.judge, 'last', {})}
        evaluation = self.store.get('evaluation', {'status': 'unvalidated', 'labelled_events': labels, 'required': 200,
            'note': '实验效果尚未验证；需至少 200 个事件的人工标注并与关键词基线比较。'})
        return NewsStatus(settings=settings, runtime=runtime, sources=[{**s.model_dump(), **self.store.get('source:'+s.id, {}), 'history': histories[s.id]} for s in settings.sources],
                          runs=runs, counts=counts, evaluation=evaluation)
