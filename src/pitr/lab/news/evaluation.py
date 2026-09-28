"""Evaluation uses human labels and frozen score IDs, including low-ranked events."""
import json
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from pitr.domain.common import utcnow
from .contracts import NewsScore, NewsArticle, NewsProfile
from .profiles import alias_matches


def label_sheet(news):
    with news.store.connect() as db:
        rows = db.execute('SELECT s.body FROM scores s JOIN articles a ON a.id=json_extract(s.body,\'$.article_id\') WHERE a.rowid IN (SELECT max(rowid) FROM articles GROUP BY url) ORDER BY a.observed_at DESC,s.rowid DESC').fetchall()
        latest = {}
        for row in rows:
            score = NewsScore.model_validate_json(row[0])
            latest.setdefault((score.event_id, score.company), score)
        result = []
        for score in latest.values():
            article = NewsArticle.model_validate_json(db.execute('SELECT body FROM articles WHERE id=?', (score.article_id,)).fetchone()[0])
            labels = {'useful': None, 'important': None, 'annotator': ''}
            for row in db.execute('SELECT body FROM feedback WHERE score_id=? ORDER BY rowid', (score.id,)):
                feedback = json.loads(row[0]); verdict = feedback['verdict']
                if verdict in ('useful', 'irrelevant'): labels['useful'] = verdict == 'useful'
                if verdict in ('raise', 'important', 'not_important'): labels['important'] = verdict != 'not_important'
                labels['annotator'] = feedback['annotator']
            result.append({'event_id': score.event_id, 'company': score.company, 'score_id': score.id,
                           'date': datetime.fromisoformat(article.observed_at).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(),
                           'title': article.title, 'url': article.url, **labels})
    return result


def evaluate(news, labels):
    groups = defaultdict(list)
    seen = set()
    with news.store.connect() as db:
        for label in labels:
            if not label.get('annotator') or type(label.get('useful')) is not bool or type(label.get('important')) is not bool:
                raise ValueError('每条样本需要人工标注者、useful 和 important 布尔判断')
            row = db.execute('SELECT body FROM scores WHERE id=?', (label['score_id'],)).fetchone()
            if not row: raise ValueError('标注引用的评分不存在')
            score = NewsScore.model_validate_json(row[0])
            if (label['event_id'], label['company']) != (score.event_id, score.company): raise ValueError('标注与评分对象不一致')
            key = (score.event_id, score.company)
            if key in seen: raise ValueError('同一事件与公司的标注重复，不能跨版本重复计算')
            seen.add(key)
            article = NewsArticle.model_validate_json(db.execute('SELECT body FROM articles WHERE id=?', (score.article_id,)).fetchone()[0])
            row = db.execute('SELECT body FROM profiles WHERE id=?', (score.profile_id,)).fetchone()
            aliases = NewsProfile.model_validate_json(row[0]).aliases if row else []
            baseline = len(alias_matches(article.title+' '+article.text, aliases))
            day = datetime.fromisoformat(article.observed_at).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
            groups[day].append((score, label, baseline))
    picked = []; baseline_picked = []; important = found = baseline_found = 0
    for rows in groups.values():
        ordered = sorted(rows, key=lambda r: (-(r[0].priority or 0), r[0].id))
        heads = {}
        for row in ordered: heads.setdefault(row[0].event_id, row)
        # One global event slot, even when it concerns multiple companies.
        def top(values):
            used = set(); output = []
            for r in values:
                if r[0].event_id in used: continue
                used.add(r[0].event_id); output.append(r)
                if len(output) == 20: break
            return output
        selected = top([r for r in heads.values() if r[0].queue == 'selected'])
        picked += selected
        baseline_selected = top(sorted([r for r in rows if r[2] > 0], key=lambda r: (-r[2], r[0].id)))
        baseline_picked += baseline_selected
        baseline_ids = {r[0].event_id for r in baseline_selected}
        selected_ids = {r[0].event_id for r in selected}
        for score, label, _ in rows:
            if label['important']:
                important += 1
                found += heads[score.event_id][0].queue == 'uncertain' or score.event_id in selected_ids
                baseline_found += score.event_id in baseline_ids
    precision = sum(l['useful'] for _, l, _ in picked)/len(picked) if picked else None
    baseline_precision = sum(l['useful'] for _, l, _ in baseline_picked)/len(baseline_picked) if baseline_picked else None
    recall = found/important if important else None
    events = len({k[0] for k in seen})
    enough = events >= 200 and len(picked) >= 20 and important > 0
    passed = enough and precision is not None and precision >= .7 and recall is not None and recall >= .9
    report = {'status': 'passed' if passed else 'unvalidated' if not enough else 'below_target', 'at': utcnow(),
              'labelled_events': events, 'labelled_pairs': len(seen), 'required': 200, 'precision_at_20': precision,
              'keyword_precision_at_20': baseline_precision, 'important_recall': recall, 'important_count': important,
              'keyword_important_recall': baseline_found/important if important else None,
              'uncertain_pairs': sum(score.queue == 'uncertain' for rows in groups.values() for score, _, _ in rows),
              'score_ids': [score.id for rows in groups.values() for score, _, _ in rows],
              'selected_count': len(picked), 'dates': sorted(groups),
              'note': '本结果仅覆盖本批人工标注；请保留低分及待确认样本，避免只标精选造成偏差。'}
    news.store.set('evaluation', report)
    return report
