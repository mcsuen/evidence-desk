"""Frozen retrieval evaluation, separate from unmeasured human research utility."""
import math
import platform
import statistics
from pitr.desk.contracts import utcnow
from pitr.desk.storage import digest, canonical
from .search import search, MODEL_KEY, TOKENIZER_VERSION
from .store import state, change


def evaluate(wiki, dataset, *, hybrid=False, save=True):
    if not dataset.get('queries') or not dataset.get('name'):
        raise ValueError('评估需要命名冻结题集与相关版本标签')
    with wiki.store.connect() as db:
        corpus = {key: r['body_object'] for key, r in state(db, 'revisions').items() if r['kind'] != 'policy'}
    results = []
    for query in dataset['queries']:
        expected = set(query['relevant'])
        if not expected or not expected <= set(corpus):
            raise ValueError('相关性标签必须指向存在的明确版本')
        found = search(wiki, query.get('company', 'PDD'), query['question'], as_of=query.get('as_of'), hybrid=hybrid)
        returned = [r['ref'] for r in found['items']]
        hits = [i+1 for i, ref in enumerate(returned) if ref in expected]
        dcg = sum(1/math.log2(i+1) for i in hits)
        ideal = sum(1/math.log2(i+1) for i in range(1, min(10,len(expected))+1))
        results.append({'question': query['question'], 'returned': returned, 'relevant': sorted(expected),
            'recall_at_10':len(set(returned)&expected)/len(expected),
            'precision_at_10':len(set(returned)&expected)/10,
            'reciprocal_rank':1/min(hits) if hits else 0, 'ndcg_at_10':dcg/ideal,
            'elapsed_ms':found['elapsed_ms'], 'mode':found['mode'], 'warnings':found['warnings']})
    times=sorted(r['elapsed_ms'] for r in results)
    report={'id':'wiki-eval:'+digest([dataset,corpus,hybrid,utcnow()])[:24], 'kind':'wiki_retrieval',
        'dataset_name':dataset['name'],'dataset_sha256':digest(dataset),'corpus_sha256':digest(corpus),
        'corpus':corpus,'created_at':utcnow(),'model':MODEL_KEY if hybrid else None,'tokenizer':TOKENIZER_VERSION,
        'architecture':platform.machine(),'requested_hybrid':hybrid,'queries':results,
        'metrics':{key:statistics.mean(r[key] for r in results) for key in ('recall_at_10','precision_at_10','reciprocal_rank','ndcg_at_10')},
        'latency_ms':{'p50':statistics.median(times),'p95':times[min(len(times)-1, math.ceil(.95*len(times))-1)]},
        'semantic_available':all(r['mode']=='rrf' for r in results) if hybrid else None,
        'scope':dataset.get('scope','development_fixture'), 'human_rework_minutes':None,
        'human_false_positive_rate':None,'human_missed_issues':None,
        'default_retrieval_changed':False}
    if save:
        with wiki.store.connect(write=True) as db:
            db.execute('INSERT INTO evaluations VALUES(?,?)',(report['id'],canonical(report)))
    return report


def inspection_metrics(wiki, company):
    with wiki.store.connect() as db:
        st=state(db)
    issues=[i for i in st['issues'].values() if i['company']==company]
    inspected=[i for i in issues if i['discovered_by'] in ('rule','semantic')]
    decided=[i for i in inspected if i['state']=='closed']
    false=[i for i in decided if i['content_resolution']=='false_alarm']
    runs=[r for r in st['inspections'].values() if r['company']==company]
    active={r['ref'] for r in wiki.list(company,include_blocked=False) if r['kind']!='policy'}
    covered={key for r in runs for key in r.get('scope',[])}
    feedback=[r['feedback'] for r in runs if r.get('feedback')]
    tp=sum(f['flagged']-f['false_positives'] for f in feedback)
    fp=sum(f['false_positives'] for f in feedback)
    fn=sum(f['missed_issues'] for f in feedback)
    return {'company':company,'inspections':len(runs),'coverage':len(active&covered)/len(active) if active else None,
        'flagged':len(inspected),'adjudicated':len(decided),'false_alarms':len(false),
        'adjudicated_false_alarm_rate':len(false)/len(decided) if decided else None,
        'missed_issue_rate':fn/(tp+fn) if tp+fn else None,
        'reviewed_precision':tp/(tp+fp) if tp+fp else None,
        'human_rework_minutes':sum(f['review_minutes'] for f in feedback) if feedback else None,
        'reviewed_runs':len(feedback),
        'limitation':'未标注完整金标准前无法估计漏报；人工返工时间需实际记录。'}


def record_feedback(wiki, run_id, request):
    with wiki.store.connect(write=True) as db:
        payload=[run_id,request.model_dump(mode='json')]
        cached=wiki._cached(db,request.operation_id,payload)
        if cached:return cached
        run=state(db,'inspections').get(run_id)
        if not run or not run.get('finished_at'):
            raise ValueError('巡检完成后才能记录人工复核')
        if request.false_positives>len(set(run['issues'])):
            raise ValueError('误报数不能超过本轮报告的问题数')
        if run.get('feedback'):
            raise ValueError('此轮已记录人工复核，不覆盖历史评价')
        run['feedback']={**request.model_dump(mode='json'),'created_at':utcnow(),
                         'flagged':len(set(run['issues'])),'checked':len(run['scope'])}
        wiki._emit(db,run['company'],'inspection.feedback',[change('inspections',run_id,run)])
        return wiki._remember(db,request.operation_id,payload,run)
