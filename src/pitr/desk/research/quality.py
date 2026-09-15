"""Durable investigator/reviewer loop. Progress, not a round or time budget, ends research."""
from __future__ import annotations
import json, time, uuid
from pydantic import ValidationError
from .contracts import IndependentReview, Requirement
from .verify import validate
from ..contracts import utcnow
from ..storage import canonical, digest, Conflict
import re

def fault_fingerprint(error):
    message=str(error)
    message=re.sub(r'\d{4}-\d{2}-\d{2}[T ][0-9:.+Z-]+','<time>',message)
    message=re.sub(r'\b[a-f0-9]{12,}\b|\b[0-9a-f-]{36}\b','<id>',message)
    message=re.sub(r'/(?:[^\s"\']+/)+[^\s"\']*','<path>',message)
    return digest([type(error).__name__,message])


def validate_traced(plane, raw):
    """Measure only deterministic validation; persistence and model review are separate."""
    sid='validation:'+uuid.uuid4().hex
    plane.validation_trace=sid
    started=time.monotonic()
    plane.trace.span(sid,name='确定性核验',kind='validation',executor='deterministic',parent_id='root',
        started_at=utcnow(),timing='measured',input_ref=plane.trace.content(raw),
        metadata={'repair_round':plane.state.get('repairs',0)})
    if getattr(plane,'trace_parent',None):plane.trace.link(plane.trace_parent,sid)
    try:
        report=validate(raw,plane)
        from .presentation import enrich
        report=enrich(report,plane.input['scope']['subjects'],plane.input['scope']['type'])
    except Exception as error:
        plane.trace.span(sid,status='failed',ended_at=utcnow(),duration_ms=(time.monotonic()-started)*1000,
            error_ref=plane.trace.content({'type':type(error).__name__,'message':str(error)}))
        raise
    plane.trace.span(sid,status='needs_review' if report['issues'] else 'completed',ended_at=utcnow(),
        duration_ms=(time.monotonic()-started)*1000,issue_count=len(report['issues']),output_ref=plane.trace.content(report))
    return report


def persist(plane, raw, report, label):
    with plane.desk.store.connect(write=True) as db:
        plane.fence(db)
        version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM research_artifacts WHERE task_id=?',(plane.task['id'],)).fetchone()[0]
        report={**report,'artifact_version':version}
        db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(plane.task['id'],version,canonical({'raw':raw,'validated':report,'created_at':utcnow()})))
    plane.state['latest_artifact_version']=version
    plane.checkpoint({'research':plane.state})
    validation=getattr(plane,'validation_trace',None)
    refs=[{'kind':'artifact','version':version,'request_id':plane.request['id']}]
    if label=='草稿核验' and validation:
        plane.trace.span(validation,artifact_refs=refs)
    else:
        sid='artifact:'+str(version)
        plane.trace.span(sid,name=label,kind='repair' if '反馈与修订' in label else 'delivery',parent_id='root',status='needs_review' if report['status']=='needs_review' else 'completed',
            ended_at=utcnow(),issue_count=len(report['issues']),input_ref=plane.trace.content(raw),output_ref=plane.trace.content(report),artifact_refs=refs)
        if validation:plane.trace.link(validation,sid,'artifact')
        elif getattr(plane,'trace_parent',None):plane.trace.link(plane.trace_parent,sid,'artifact')
    return report


def fingerprint(report, review):
    return digest({'coverage':[(c['key'],c['status']) for c in report['coverage']],
        'issues':sorted((i.get('claim_id',''),i['code'],i.get('field','')) for i in report['issues']),
        'findings':sorted((i['code'],i['claim_id'],i['requirement_id'],i['severity']) for i in review['findings']),
        'evidence':sorted(e['id'] for e in report['evidence']),
        'calculations':sorted((c['id'],c['value']) for c in report['calculations']),
        'reading':sorted((r['source_id'],r['page'] or 0,r['status'],r['visual']) for r in report['reading'] if r['status']!='unread'),
        'requirements':sorted(r['id'] for r in report['requirements'])})


def review_source_feedback(plane, review, report):
    """A reviewer's new original must be read and carried into the revised report."""
    tools=plane.receipts('tool');readings=plane.receipts('reading');evidence=plane.receipts('evidence')
    acquired={t['result']['source_id'] for t in tools.values() if t.get('role')=='reviewer' and
              t.get('name')=='fetch_public_source' and not t.get('error') and t.get('result',{}).get('included')}
    checks={c['source_id']:c for c in review.get('source_checks',[])}
    claims={c['id']:c for c in report.get('claims',[])};problems=[]
    for sid in sorted(acquired):
        field='source_checks['+sid+']';check=checks.get(sid)
        def problem(message,value=None,code='review_source_check'):
            problems.append({'code':code,'field':field,'source_id':sid,'message':message,'value':value})
        if not check:
            problem('复核新增原件必须逐项记录 used / irrelevant / unavailable；取得链接或下载成功不等于已读。');continue
        if not check.get('reason','').strip():
            problem('说明该原件支持/限制哪个判断，或为何无关/无法读取。');continue
        own=[r for r in readings.values() if r.get('role')=='reviewer' and r['source_id']==sid]
        linked=[c for c in claims.values() if any(evidence.get(ref,{}).get('source_id')==sid for ref in
                c.get('evidence',[])+c.get('counterevidence',[])+c.get('calculation_evidence',[]))]
        if check['status']=='irrelevant':
            if linked or check.get('evidence'):problem('标为无关的原件不能同时作为报告依据。')
            continue
        if check['status']=='unavailable':
            doc=plane.desk.document(sid)
            if doc.blocks or not any(r.get('error') for r in own) or (doc.media_type=='application/pdf' and not any(r['mode']=='visual' for r in own)):
                problem('尚不能认定原件无法读取。有文本的网页请 read_source；PDF 先读取相应页，必要时视觉读取。工具选错或未尝试读取不是资料不足。')
            if linked or check.get('evidence'):problem('未能读取的原件不能支持报告事实。')
            continue
        refs=check.get('evidence',[]);targets=check.get('claim_ids',[])
        blocks={b for r in own if not r.get('error') for b in r.get('block_ids',[])}
        if not refs or any(ref not in evidence or evidence[ref]['source_id']!=sid or evidence[ref]['block_id'] not in blocks for ref in refs):
            problem('used 必须引用复核者成功读到的本原件 evidence_ID；阅读失败、其他原件引用和搜索结果不能代替。',refs);continue
        if not targets or any(cid not in claims for cid in targets):
            problem('请指定该原件影响的现有 claim_ids，再要求研究者补入相关原文。',targets);continue
        for cid in targets:
            if cid not in {c['id'] for c in linked}:
                problem('复核确认使用的新原件尚未绑定到报告判断；研究者须把相关原文 evidence_ID 加入该 claim 的支持/反证引用，保留来源限制。',
                        {'claim_id':cid,'evidence':refs},'review_source_binding')
    return problems


def review_feedback(plane, review, report):
    problems=[]
    requirements={r['id'] for r in plane.requirements()}
    unchecked=requirements-set(review['checked_requirements'])
    if unchecked:problems.append({'code':'review_coverage','field':'checked_requirements','message':'独立复核尚未逐项检查要求','value':sorted(unchecked)})
    readings=plane.receipts('reading');tools=plane.receipts('tool')
    checked=[readings.get(r) or (tools.get(r) if tools.get(r,{}).get('name') in ('read_source','read_page','read_table','fetch_public_source') else None) for r in review['check_receipts']]
    available_receipts=plane.receipts()
    for index,ref in enumerate(review['check_receipts']):
        if ref not in available_receipts:
            problems.append({'code':'review_receipt','field':f'check_receipts[{index}]','value':ref,'message':'该编号不在本次账本；请使用工具实际返回的完整编号，不要改写编号前缀。'})
    if not any(c and c.get('role')=='reviewer' and not c.get('error') and
               (c.get('block_ids') or c.get('mode')=='visual' or c.get('result',{}).get('blocks')) for c in checked):
        problems.append({'code':'review_reading','field':'check_receipts','message':'独立复核需要自己的原件阅读或补查凭据，不能只阅读研究者草稿'})
    for req in plane.requirements():
        if req['source_id'] and req['pages']:
            entries=[r for r in readings.values() if r.get('role')=='reviewer' and r['source_id']==req['source_id']]
            doc=plane.desk.document(req['source_id'])
            pages={p for p in req['pages'] if any(p in r['pages'] and (r['mode']=='visual' or r.get('error')) for r in entries) or
                {b.id for b in doc.blocks if b.page==p}<={b for r in entries if not r.get('error') for b in r['block_ids']}}
            if set(req['pages'])-pages:
                problems.append({'code':'review_reading','field':'check_receipts','message':'复核者尚未自行读取关键页','value':req['id']})
    available=plane.receipts('evidence')
    for finding in review['findings']:
        for ref in finding['evidence']:
            if ref not in available:problems.append({'code':'review_evidence','field':'findings.evidence','message':'复核意见引用不在本次账本','value':ref})
    for r in review['additional_requirements']:
        value=Requirement.model_validate(r).model_dump()
        if value['source_id'] and value['source_id'] not in plane.frozen['sources']:
            problems.append({'code':'review_requirement','message':'新增要求引用未知来源','value':value['id']});continue
        current=plane.state.setdefault('requirements',{})
        if value['id'] in current and current[value['id']]!=value:
            problems.append({'code':'review_requirement','message':'不得覆盖已登记要求','value':value['id']});continue
        if value['id'] not in current:
            current[value['id']]=value
            problems.append({'code':'new_requirement','message':'独立复核新增待回答要求','value':value})
    problems.extend(review_source_feedback(plane,review,report))
    return problems


def run_quality(plane, investigator, reviewer):
    state=plane.state.setdefault('quality',{'phase':'research','seen':[],'alternatives':[],'reviews':[]})
    plane.bootstrap_requirements()
    initial='完成用户原始研究。先 context，再实际阅读附件和关键表格；自主查证、计算并保存 checkpoint。最终填写每项 requirement_resolutions。'
    initial+=' 根据 context.research_scope 逐项回答，以1至3条 section=summary 的简短核心判断开头；summary 必须有原文依据和 depends_on，不得省略重要限制。每条观点填写 subject_ids；比较数字使用明确 company_id，品牌不等于集团。正文按核心问题展开，报告标题只描述研究主题。'
    from .intake import apply_updates,UserUpdate
    while True:
        plane.fence()
        apply_updates(plane)
        if plane.state.get('questions'):return {'status':'waiting_user','questions':plane.state['questions']}
        if state['phase']=='research':
            plane.checkpoint({'research':plane.state,'stage':'investigating'})
            try:
                raw=investigator.attempt(state.get('next_prompt',initial))
                if raw is None:return {'status':'waiting_user','questions':plane.state['questions']}
                state.pop('last_runtime_error',None)
                candidate=plane.receipt('candidate',{'raw':raw})
                state.update(candidate_id=candidate['id'],phase='review')
                plane.checkpoint({'research':plane.state,'stage':'validating'})
            except UserUpdate:
                apply_updates(plane);continue
            except ValidationError as error:
                # Structured-output mistakes are repair feedback, never infrastructure recovery.
                errors=[{'field':'.'.join(map(str,e['loc'])),'message':e['msg'],'value':str(e.get('input',''))[:300]} for e in error.errors()]
                marker=digest(errors)
                if state.get('schema_error')==marker:raise RuntimeError('结构化输出持续无法读取；原始输出和具体字段错误已保存，需处理：'+canonical(errors))
                state['schema_error']=marker;state['next_prompt']='修复输出结构，保留研究内容和已保存证据：'+canonical(errors)
                plane.state['repairs']+=1;plane.checkpoint({'research':plane.state});continue
            except (Conflict,TimeoutError):raise
            except Exception as error:
                marker=fault_fingerprint(error)
                if state.get('last_runtime_error')==marker:raise
                state['last_runtime_error']=marker;plane.state['recoveries']+=1
                from .native import re_missing_session
                if re_missing_session(str(error)):investigator.set_session(None)
                state['next_prompt']='执行故障后恢复，沿用 context 和 checkpoint 中的原件、计算和要求。'+state.get('next_prompt',initial)
                plane.checkpoint({'research':plane.state,'stage':'recovering','recovery_error':str(error)});time.sleep(.5);continue
        raw=plane.receipts('candidate')[state['candidate_id']]['raw']
        report=validate_traced(plane,raw)
        report['delivery']={'status':'in_review','reason':'草稿正在独立复核，尚未完成交付'}
        report['reviews']=state['reviews']
        report=persist(plane,raw,report,'草稿核验')
        machine_missing=[c for c in report['coverage'] if c['status'] in ('missing','invalid')]
        if report['issues'] or machine_missing:
            signature=fingerprint(report,{'findings':[]})
            seen=state.setdefault('integrity_seen',[]);alternatives=state.setdefault('integrity_alternatives',[])
            if signature in seen and signature in alternatives:
                report['status']='needs_review';report['handoffs']=[]
                report['delivery']={'status':'stalled','reason':'引用、计算或必答字段在尝试替代修复后仍无改善；保存具体错误及已有研究，需处理。','unanswered':machine_missing}
                state['phase']='stalled';plane.checkpoint({'research':plane.state})
                return persist(plane,raw,report,'核验修复停滞：保留成果')
            alternative=signature in seen
            if alternative:alternatives.append(signature)
            seen.append(signature)
            state['next_prompt']=('错误未改善，换用原表单元格、确切账本编号或其他可核实路径；不要重复无效改写。' if alternative else '先定点修复引用、计算及必答字段，随后独立复核研究内容。')+'保留原 claim id、有效引用和定量细节；移除错误依据时说明 revision_reason。\n'+canonical({'issues':report['issues'],'missing':machine_missing})
            report['delivery']={'status':'repairing','reason':'引用、计算及必答字段正在定点修复；独立内容复核尚未完成。'}
            repaired=persist(plane,raw,report,'核验反馈与修订')
            plane.state['trace_next_link']={'id':'artifact:'+str(repaired['artifact_version']),'kind':'repair'}
            state['phase']='research';plane.state['repairs']+=1
            plane.checkpoint({'research':plane.state,'stage':'repairing'});continue
        plane.checkpoint({'research':plane.state,'stage':'independent_review'})
        review_input={'question':plane.input['question'],'draft':raw,'requirements':plane.requirements(),
            'previous_review':state['reviews'][-1] if state['reviews'] else None,
            'instructions':'独立读取原件，逐一核对每个原观点、驱动、条件和抵消因素是否得到明确判断。不能因为 requirement_resolutions 自称 answered 就判为覆盖。集中检查遗漏、归因、充分依据、口径和后续信息；不要把机械格式修正当成研究复核。记录 check_receipts/checked_requirements。'}
        review_input['existing_reviewer_readings']=[{'id':r['id'],'source_id':r['source_id'],'pages':r['pages'],'error':r.get('error')} for r in plane.receipts('reading').values() if r.get('role')=='reviewer']
        with plane.desk.store.connect() as db:
            previous=next((a['raw'] for row in db.execute('SELECT body FROM research_artifacts WHERE task_id=? ORDER BY version DESC',(plane.task['id'],)) if (a:=json.loads(row['body']))['raw']!=raw),None)
        if previous:review_input['previous_draft_for_regression_check']=previous
        try:
            review=IndependentReview.model_validate(reviewer.attempt(canonical({**review_input,'reviewer_corrections':state.get('reviewer_corrections',[])}))).model_dump()
        except UserUpdate:
            apply_updates(plane);continue
        except (Conflict,TimeoutError):raise
        except Exception as error:
            marker=fault_fingerprint(error)
            if state.get('review_error')==marker:raise
            state['review_error']=marker;plane.checkpoint({'research':plane.state,'stage':'review_recovery'});continue
        feedback=review_feedback(plane,review,report)
        review_receipt=plane.receipt('review',{'review':review,'candidate_id':state['candidate_id'],
            'session_id':reviewer.session_id(),'attempt':getattr(reviewer,'current_ordinal',None),'feedback':feedback})
        state['reviews'].append({'id':review_receipt['id'],**review,'feedback':feedback})
        reviewer_errors=[f for f in feedback if f['code'] not in ('new_requirement','review_source_binding')]
        if reviewer_errors:
            marker=digest(reviewer_errors)
            if state.get('reviewer_error_signature')==marker:
                report['reviews']=state['reviews'];report['status']='needs_review';report['handoffs']=[]
                report['delivery']={'status':'stalled','reason':'独立复核未能完成其原件检查或纠正复核记录；不能将草稿当成完成报告','review_feedback':reviewer_errors}
                state['phase']='stalled';plane.checkpoint({'research':plane.state})
                return persist(plane,raw,report,'复核停滞：保留成果')
            state['reviewer_error_signature']=marker;state['reviewer_corrections']=reviewer_errors
            plane.checkpoint({'research':plane.state});continue
        state.pop('reviewer_error_signature',None);state.pop('reviewer_corrections',None)
        report=validate_traced(plane,raw);report['reviews']=state['reviews']
        missing=[c for c in report['coverage'] if c['status'] in ('missing','invalid')]
        blockers=[f for f in review['findings'] if f['severity']=='blocking']
        ready=not report['issues'] and not missing and not feedback and not blockers and review['verdict']=='pass'
        external_gap=not report['issues'] and not missing and not feedback and review['verdict']=='blocked' and bool(review['blocking_reason']) and all(f['code']=='gap' for f in blockers)
        if ready or external_gap:
            report['status']='partial' if report['gaps'] or any(c['status']=='gap' for c in report['coverage']) or external_gap else 'review_ready'
            report['delivery']={'status':'partial' if report['status']=='partial' else 'ready','reason':review['blocking_reason'] if external_gap else '要求、原件、计算和独立复核已完成；人工采纳仍待处理'}
            report['verification']['independent_review']='passed_with_gaps' if external_gap else 'passed'
            report['handoffs']=[{'claim_id':c['id'],'kinds':['wiki'],'status':'available_for_review'} for c in report['claims'] if c['validation']=='integrity_checked' and c['verdict']!='insufficient' and c['evidence'] and c['alternative'] and c['next_check']]
            state['phase']='delivered';plane.checkpoint({'research':plane.state})
            return persist(plane,raw,report,'研究交付')
        signature=fingerprint(report,review)
        if signature in state['seen'] and signature in state['alternatives']:
            report['status']='needs_review';report['handoffs']=[]
            report['delivery']={'status':'stalled','reason':'关键证据、计算、要求覆盖与复核问题在替代路径尝试后仍无改善；保留成果，需处理具体阻塞。',
                'blocking_findings':blockers,'review_feedback':feedback,'unanswered':missing}
            state['phase']='stalled';plane.checkpoint({'research':plane.state})
            return persist(plane,raw,report,'研究停滞：保留成果')
        alternative=signature in state['seen']
        if alternative:state['alternatives'].append(signature)
        state['seen'].append(signature)
        state['next_prompt']=('当前调查没有实质改善，必须换未尝试的来源、页面阅读或计算方法；不要重复无效查询。' if alternative else '根据独立复核定点补查修订。')+'保留有效引用、计算和原 claim id；如移除错误依据必须说明 revision_reason。\n'+canonical({'issues':report['issues'],'missing':missing,'review':review,'review_feedback':feedback})
        report['delivery']={'status':'repairing','reason':'独立复核仍有未解决问题，继续补查修订'}
        repaired=persist(plane,raw,report,'复核反馈与修订')
        plane.state['trace_next_link']={'id':'artifact:'+str(repaired['artifact_version']),'kind':'repair'}
        state['phase']='research';plane.state['repairs']+=1
        plane.checkpoint({'research':plane.state,'stage':'repairing'})
