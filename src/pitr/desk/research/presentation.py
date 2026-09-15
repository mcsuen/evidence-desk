"""Reading structure derived only from the validated artifact, without a second model summary."""
from collections import defaultdict

LABELS={'summary':'核心判断','changes':'关键变化','baseline':'实际与预期','cash_margin':'利润与现金','persistence':'持续性与替代解释','model_impact':'模型假设','claims':'观点核对','questions':'未决问题'}

def enrich(report,subjects=None,scope_type=None):
    report=dict(report)
    report['subjects']=subjects if subjects is not None else report.get('subjects',[])
    report['scope_type']=scope_type or report.get('scope_type','company')
    claims=report.get('claims',[])
    valid=[c for c in claims if c.get('validation')=='integrity_checked' and c.get('section')!='questions']
    valid=list({c.get('statement',c.get('text',c['id'])):c for c in reversed(valid)}.values())[::-1]
    summaries=[c for c in valid if c.get('section')=='summary']
    report['key_claim_ids']=[c['id'] for c in (summaries or valid)[:3]]
    sections={}
    for c in claims:
        key=c.get('section','claims');sections.setdefault(key,{'id':key,'title':LABELS.get(key,key),'claim_ids':[]})['claim_ids'].append(c['id'])
    report['sections']=list(sections.values())
    groups=defaultdict(list)
    for c in report.get('calculations',[]):
        if c.get('company_id') and c.get('value') is not None and c.get('formula') in ('source_literal','observation','margin','ratio','divide','growth'):
            groups[c['metric']].append(c)
    compared=[]
    for metric,values in groups.items():
        if len({c['company_id'] for c in values})<2:continue
        signatures={(c['period'],c['unit'],c['basis'],c['frequency'],tuple(sorted(c.get('source_roles',[])))) for c in values}
        compatible=len(signatures)==1 and all(c['basis'] not in ('','disclosed') for c in values)
        compared.append({'metric':metric,'calculation_ids':[c['id'] for c in values],'comparable':compatible,
                         'note':'相同指标与披露口径；仍需核对公司财年和业务定义' if compatible else '期间、单位、会计或来源口径不同，分别展示，不能直接推导差异'})
    report['comparisons']=compared
    return report
