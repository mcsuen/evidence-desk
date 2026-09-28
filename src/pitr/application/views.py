"""Company pages are projections, never another source of facts."""
from pitr.domain.common import instant, Forbidden
from pitr.domain.contracts import Assertion, ModelRevision, SourceVersion, Value, Scope
from pitr.domain.views import CompanyView, KnowledgeItem, CompanySource, CompanyValue, SourceSummary, ReportSummary
from pitr.domain.policy import source_allowed


def company_view(station, identity, scope: Scope):
    store = station.store
    subject = store.get(identity, 'subject')
    subject_at_time = True
    if scope.as_of:
        versions = [s for s in store.list('subject', all_revisions=True)
                    if s.id == identity and instant(s.created_at) <= instant(scope.as_of)]
        if versions:
            subject = max(versions, key=lambda s:s.revision)
        else:
            # The current directory label is useful for navigation but is not past identity evidence.
            subject_at_time = False
    items = station.knowledge(scope)
    knowledge = [KnowledgeItem(object=(ModelRevision if 'assumptions' in v else Assertion).model_validate(
        {k:x for k,x in v.items() if k != 'current_validity'}), current_validity=v['current_validity']) for v in items]
    sources = [CompanySource(object=SourceSummary.model_validate({k:x for k,x in v.items() if k in SourceSummary.model_fields}),
        current_validity=v['current_validity']) for v in station.source_list(scope, all_revisions=True)]
    cases = []
    for case in station.cases():
        if scope.as_of:
            inputs = [i for i in store.list('input', all_revisions=True) if i.id == case.input.id and instant(i.created_at) <= instant(scope.as_of)]
            if not inputs:continue
            inp = max(inputs, key=lambda i:i.revision)
            case = case.model_copy(update={'input':inp,'title':inp.question[:120],'updated_at':inp.created_at})
        if identity in case.input.scope.subjects:cases.append(case)
    reports = []
    for report in store.list('report', all_revisions=True):
        snapshot = store.get(report.snapshot, 'snapshot')
        if identity not in snapshot.scope.subjects:continue
        if scope.as_of and instant(report.created_at) > instant(scope.as_of):continue
        try:
            for obj in store.closure(report.ref):
                if isinstance(obj, SourceVersion):source_allowed(obj, scope)
        except Forbidden:continue
        reports.append(report)
    values = {}
    for item in [k.object for k in knowledge] + reports:
        for obj in store.closure(item.ref):
            if isinstance(obj, Value) and obj.subject == identity:
                values[obj.ref.key] = CompanyValue(object=obj, current_validity=store.validity(obj.ref))
    history = [{'kind':'source','ref':s.object.ref.model_dump(),'title':s.object.title,'at':s.object.created_at,
                'current_validity':s.current_validity} for s in sources]
    history += [{'kind':'report','ref':r.ref.model_dump(),'title':r.title,'at':r.created_at,'case_id':r.case_id,'run_id':r.run_id} for r in reports]
    for decision in store.list('decision', all_revisions=True):
        if scope.as_of and instant(decision.created_at) > instant(scope.as_of):continue
        if any(identity in getattr(store.get(ref),'subjects',[]) for ref in decision.targets):
            history.append({'kind':'decision','ref':decision.ref.model_dump(),'title':decision.reason,'at':decision.created_at,'action':decision.action})
    if scope.as_of:
        history = [h for h in history if instant(h['at']) <= instant(scope.as_of)]
    summaries = [ReportSummary.model_validate({k:v for k,v in r.model_dump().items() if k in ReportSummary.model_fields}) for r in reports]
    return CompanyView(subject=subject, subject_at_time=subject_at_time, scope=scope, knowledge=knowledge, sources=sources,
        values=list(values.values()), cases=cases, reports=summaries, history=sorted(history, key=lambda x:x['at'], reverse=True))
