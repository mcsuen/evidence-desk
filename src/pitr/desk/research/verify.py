"""Location/arithmetic integrity and delivery coverage, separate from semantic review."""
import re, json
from .contracts import DraftOutcome, ResearchOutcome, CoverageCheck
from .units import canonical_unit

TOKEN = re.compile(r'\{\{(calculation_[a-f0-9]+)\}\}')
DATES = re.compile(r'(?<![\dA-Za-z])(?:(?:FY)?20\d{2}(?:(?:[-/]\d{1,2}){1,3}|\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?|\s*第?[一二三四1234]季度)?|Q[1-4]|YTD[1-4]|H[12]|FY)?[AEF]?|FY\d{2}[AEF]?|[1-4]Q(?:\d{2})?[AEF]?)(?![\dA-Za-z])', re.I)
MONTH_DAYS = re.compile(r'(?<![\dA-Za-z.])(?:0?[1-9]|1[0-2])\s*月(?:\s*(?:0?[1-9]|[12]\d|3[01])\s*[日号])?')
LOCATORS = re.compile(r'(?:第\s*\d+(?:\s*[-–至、]\s*\d+)*\s*页|(?:pp?\.?|page|figure|table|图|表|页)\s*\d+(?:\s*[-–]\s*\d+)?|\[\d+(?:,\s*\d+)*\]|(?:(?<![A-Za-z])E\.?\s*O\.?|Executive\s+Order(?:\s+(?:No\.?|Number))?|行政令(?:第|编号)?)\s*#?\s*\d+号?)', re.I)
DOCUMENT_IDS = re.compile(r'(?<![\dA-Za-z])(?:6[-‐‑–]K|8[-‐‑–]K|10[-‐‑–][KQ]|20[-‐‑–]F|40[-‐‑–]F|[SF][-‐‑–]1)(?:/A)?(?![\dA-Za-z])', re.I)
ENUMERATION = re.compile(r'(^|[；;\n])\s*(?:[（(]\d{1,2}[）)]|\d{1,2}[)）、]|\d{1,2}\.(?!\d))\s*', re.M)
NUMBERS = re.compile(r'(?<![a-zA-Z_])[-+−]?\d[\d,]*(?:\.\d+)?')
REQUIRED = {'earnings':['changes','baseline','cash_margin','persistence','model_impact','questions'],
            'report_review':['claims','questions'],'investigation':['changes','persistence','questions']}
NUMERIC_CODES = {'unbound_number','metric','direction','calculation','numeric_source'}


def format_number(c):
    if c['value'] is None:return '缺失'
    units={'RMB_bn':'十亿元人民币','USD_bn':'十亿美元','RMB_mn':'百万元人民币','USD_mn':'百万美元','percent':'%','percentage_points':'个百分点','RMB_per_ADS':'元人民币/ADS','USD_per_ADS':'美元/ADS','multiple':'倍','ratio':'倍'}
    return f"{c['value']:,.{c['precision']}f} {units.get(c['unit'],c['unit'])}（{c['period']} · {c['basis'] or '情景假设'}）"


def date_bounds(value):
    from datetime import date
    from calendar import monthrange
    if match:=re.fullmatch(r'(20\d{2})Q([1-4])',value):
        year=int(match[1]);month=int(match[2])*3
        return date(year,month-2,1),date(year,month,monthrange(year,month)[1])
    day=date.fromisoformat(value)
    return day,day


def closure(ids, calcs):
    found=set(ids); evidence=set();pending=list(ids)
    while pending:
        c=calcs.get(pending.pop(),{})
        for dep in c.get('dependencies',[]):
            if dep in calcs and dep not in found:found.add(dep);pending.append(dep)
            elif dep.startswith('evidence_'):evidence.add(dep)
    return found,evidence

def quantitative_table_blocks(req, plane):
    if req['kind']!='table' or not req['source_id'] or not re.search(r'earnings|financial results|forecast|revision|valuation|SOTP|预期|预测|估值|利润|财务|业绩',req['question'],re.I):return set()
    blocks=plane.desk.document(req['source_id']).blocks
    start=next((i for i,b in enumerate(blocks) if b.text==req['question']),None)
    if start is None:return set()
    end=next((i for i in range(start+1,len(blocks)) if re.match(r'Figure\s+\d+\s*[:：]',blocks[i].text,re.I)),len(blocks))
    return {b.id for b in blocks[start:end]}


def validate(raw,plane):
    draft=DraftOutcome.model_validate(raw);f=plane.frozen
    evidence=plane.receipts('evidence');calcs=plane.receipts('calculation')
    claims={c.id:c for c in draft.claims};issues=[];bad=set();depmap={};rendered=[];normalizations=[]
    with plane.desk.store.connect() as db:
        artifacts=[json.loads(r['body']) for r in db.execute('SELECT body FROM research_artifacts WHERE task_id=? ORDER BY version',(plane.task['id'],))]
    original=artifacts[0]['raw'].get('claims',[]) if artifacts else [c.model_dump() for c in draft.claims]
    removed=[c for c in original if c['id'] not in claims]
    def issue(cid,code,message,field='',value=None):
        issues.append({'claim_id':cid,'code':code,'message':message,'field':field,'value':value})
        if cid:bad.add(cid)
    if len(claims)!=len(draft.claims):
        for c in draft.claims:issue(c.id,'duplicate_id','结论标识必须唯一','id',c.id)
    invalid_refs=set()
    families={}
    def family(ref):
        return families.get(ref['source_id'],ref.get('origin_group') or ref['origin'])
    # Reprints of the same bytes, declared originals and existing provenance
    # groups are one source even when their URLs differ.
    group_keys={}
    for ref in evidence.values():
        keys=[ref.get('origin_group') or ref['origin'],ref['source_version'],ref.get('original_url') or ref.get('url') or ref['source_id']]
        groups={group_keys[k] for k in keys if k in group_keys}
        group=min(groups) if groups else ref['source_id']
        if groups:
            families={sid:group if g in groups else g for sid,g in families.items()}
            group_keys={k:group if g in groups else g for k,g in group_keys.items()}
        families[ref['source_id']]=group
        group_keys.update({k:group for k in keys})
    with plane.desk.store.connect() as db:
        snap=plane.desk._snapshot(db,f['snapshot'])
        withdrawn={r[0] for r in db.execute('SELECT id FROM source_state WHERE withdrawn_at IS NOT NULL')}
        try:plane.desk._sources_valid(db,snap)
        except Exception as error:
            for c in draft.claims:issue(c.id,'source_invalidated',str(error))
    for key,e in evidence.items():
        if e['source_id'] not in f['sources'] or e['source_id'] in withdrawn:invalid_refs.add(key);continue
        d=plane.desk.document(e['source_id']);b=next((x for x in d.blocks if x.id==e['block_id']),None)
        if not b or d.digest!=e['source_version'] or b.text[e['start']:e['end']]!=e['quote']:invalid_refs.add(key)
    for c in draft.claims:
        from .subjects import ids
        if set(c.subject_ids)-set(ids(plane)):issue(c.id,'subject','结论主体不属于本轮研究范围','subject_ids')
        calcids=set(TOKEN.findall(' '.join([c.text,c.alternative,c.next_check,c.counterevidence_notes])))
        for reference in c.calculations:
            wrapped=TOKEN.fullmatch(reference);normalized=wrapped[1] if wrapped else reference
            calcids.add(normalized)
            if wrapped:normalizations.append({'claim_id':c.id,'field':'calculations','from':reference,'to':normalized})
        deps=set(c.depends_on);depmap[c.id]=deps
        if c.section=='summary' and not deps:issue(c.id,'dependency','摘要必须关联其基础研究结论','depends_on')
        if c.id in deps or any(x not in claims for x in deps):issue(c.id,'dependency','结论依赖不存在或引用自身','depends_on',c.depends_on)
        for field in ('evidence','counterevidence','original_evidence'):
            for index,ref in enumerate(getattr(c,field)):
                if ref not in evidence or ref in invalid_refs:
                    reason='该字段只能填写工具返回的 evidence_ID；反证解释应放入 counterevidence_notes' if not re.fullmatch(r'evidence_[a-f0-9]+',ref) else '引用不存在、超出快照或已失效'
                    issue(c.id,'evidence',reason,field+'['+str(index)+']',ref)
        _,operands=closure(calcids,calcs)
        refs=set(c.evidence+c.counterevidence)|operands
        if c.claim_type=='author_statement':refs.update(c.original_evidence)
        if not refs and not deps and c.verdict!='insufficient' and not (calcids and all(calcs.get(x,{}).get('assumption') for x in calcids)):
            issue(c.id,'missing_evidence','可核实结论需要原文或带原文依赖的计算；缺失应明确说明','evidence')
        original_groups={family(evidence[x]) for x in c.original_evidence if x in evidence}
        supporting=set(c.counterevidence if c.verdict=='contradicted' else c.evidence)|operands
        independent=[evidence[r] for r in supporting if r in evidence and r not in invalid_refs and evidence[r]['origin']!='uploaded_claim'
                     and family(evidence[r]) not in original_groups]
        if (plane.input['intent']=='report_review') and (c.section not in ('summary','questions')) and (c.temporal_scope!='subsequent') and (not c.original_claim or not c.original_evidence):
            issue(c.id,'original_claim','研报观点核对须保留原观点及原件定位','original_evidence')
        if (plane.input['intent']=='report_review') and (c.temporal_scope!='subsequent'):
            dates=[e.get('reported_date') for e in evidence.values() if e['source_id'] in plane.input['source_ids'] and e.get('reported_date')]
            if dates:
                later=[r for r in set(c.evidence+c.counterevidence)|operands if r in evidence and
                    (evidence[r].get('reported_date') or (evidence[r].get('published_at','')[:10] if evidence[r].get('publication_precision')!='observed' else ''))>min(dates)]
                if later:issue(c.id,'temporal','报告发布后的证据必须单列，不能用于证明发布时的解释','temporal_scope',later)
        if plane.input['intent']=='report_review' and c.verdict in ('supported','contradicted') and c.claim_type not in ('author_statement','calculation') and not independent:
            issue(c.id,'source_independence','作者主张不能自证；缺少独立来源。原观点存在和表内算术可分别声明为 author_statement/calculation','evidence')
        text_fields={'text':c.text,'alternative':c.alternative,'next_check':c.next_check,'counterevidence_notes':c.counterevidence_notes}
        for field,text in text_fields.items():
            clean=TOKEN.sub('',text)
            if re.search(r'(?<![\dA-Za-z])20\d{2}\s*(?:元人民币|美元|人民币|百万元|百万|亿元|亿|万元|万|元|%|％|RMB|USD)',clean,re.I):
                issue(c.id,'unbound_number','财务金额不能伪装为年份',field)
            clean=ENUMERATION.sub(lambda m:m[1],DOCUMENT_IDS.sub('',LOCATORS.sub('',MONTH_DAYS.sub('',DATES.sub('',clean)))))
            if re.search(r'[一二两三四五六七八九十][零一二两三四五六七八九十百千万亿]*(?:个)?(?:百分点|亿元|万元|元人民币|万美元|美元|元|%)',clean):
                issue(c.id,'unbound_number','中文财务数值同样需要计算引用',field)
            if match:=NUMBERS.search(clean):issue(c.id,'unbound_number','财务数字需使用 {{calculation_ID}}；保留原内容并绑定数字',field,match.group())
            for m in TOKEN.finditer(text):
                ref=calcs.get(m[1])
                if not ref:continue
                near=re.split(r'[。；;，,、]',text[max(0,m.start()-30):m.start()])[-1]
                aliases={'revenue':r'(?<!成本)(?<!服务)(?<!营销)(?<!广告)(?:营收|收入|revenue)','transaction_services':r'交易服务','online_marketing':r'在线营销|线上营销|网络营销|在线广告','operating_profit':r'(?:经营利润|营业利润)(?!率)|operating profit(?! margin)','operating_margin':r'经营利润率|营业利润率|operating (?:profit )?margin|(?<![A-Za-z])OPM(?![A-Za-z])','gross_margin':r'毛利率|gross margin',
                    'net_income':r'净利润(?!率)|net income(?! margin)','eps_ads':r'(?:每\s*ADS\s*(?:收益|盈利|净利)|earnings per ADS)','operating_cash_flow':r'(?:经营现金流|operating cash flow)'}
                named=[(hit.start(),key) for key,pattern in aliases.items() for hit in re.finditer(pattern,near,re.I)]
                # Ratios and residuals can name several operands. The nearest
                # noun alone does not determine a composite calculation's metric.
                related,_=closure({m[1]},calcs)
                metric_names=[calcs[x]['metric'].replace('net_profit','net_income').replace('operating_income','operating_profit') for x in related if x in calcs]
                if named and not any(key in metric for _,key in named for metric in metric_names) and ref['formula'] not in ('add','sum_difference','multiply','divide','ratio','reconcile_totals','reconcile_residual'):
                    issue(c.id,'metric','正文指标名称与计算指标不一致',field,m[1])
                if re.search('增加|上升|增长|提高|改善|increase|rose',near,re.I) and ref.get('direction')=='decrease':issue(c.id,'direction','增长描述与计算下降方向冲突',field,m[1])
                if re.search('下降|降低|减少|下滑|decrease|fell',near,re.I) and ref.get('direction')=='increase':issue(c.id,'direction','下降描述与计算增长方向冲突',field,m[1])
            for m in re.finditer(r'(20\d{2}Q[1-4]).{0,12}?(?:在|于|是)?\s*(20\d{2}Q[1-4])\s*(之后|以后|之前|以前)',text):
                if (m[3] in ('之后','以后') and m[1]<=m[2]) or (m[3] in ('之前','以前') and m[1]>=m[2]):issue(c.id,'chronology','季度先后关系错误',field)
        for ref in calcids:
            if ref not in calcs:issue(c.id,'calculation','计算引用不存在或不属于本次运行','calculations',ref)
        for ref in operands:
            if ref not in evidence or ref in invalid_refs:issue(c.id,'numeric_source','计算的原始证据失效','calculations',ref)
        for rel in c.chronology:
            try:ordered=date_bounds(rel.earlier)[1]<date_bounds(rel.later)[0]
            except ValueError:ordered=False
            if not ordered:issue(c.id,'chronology','earlier 必须早于 later；日期用 YYYY-MM-DD、季度用 YYYYQn。时段重叠时提供具体日期，不能填写证据编号。','chronology',rel.model_dump())
        if c.verdict=='interpretation' and (not c.alternative or not c.next_check):issue(c.id,'inference','研究解释需要替代解释及后续可检验条件')
        for artifact in artifacts:
            previous=next((p for p in artifact.get('validated',{}).get('claims',[]) if p['id']==c.id),None)
            if not previous:continue
            for field in ('evidence','original_evidence','calculations'):
                available=calcs if field=='calculations' else evidence
                prior={r for r in previous.get(field,[]) if r in available and r not in invalid_refs}
                current=calcids if field=='calculations' else set(getattr(c,field))
                if prior-current and not c.revision_reason:
                    issue(c.id,'regression','修订移除了已有有效引用；请恢复，或在 revision_reason 解释移除依据并交独立复核',field,sorted(prior-current))
        rendered.append({**c.model_dump(),'calculations':sorted(calcids),'calculation_evidence':sorted(operands),
            'independent_source_count':len({family(e) for e in independent}),
            'invalid_references':[i for i in issues if i['claim_id']==c.id and i['code']=='evidence'],
            **{k:TOKEN.sub(lambda m:format_number(calcs[m[1]]) if m[1] in calcs else '[无效计算引用]',v) for k,v in text_fields.items()},
            'source_support':'human_review_required','inference':'human_review_required'})
    def reaches(start,node,seen):
        if node in seen:return False
        return any(d==start or reaches(start,d,seen|{node}) for d in depmap.get(node,set()))
    for cid in claims:
        if reaches(cid,cid,set()):issue(cid,'dependency_cycle','结论依赖形成循环','depends_on')
    for _ in claims:
        for cid,deps in depmap.items():
            if deps&bad and cid not in bad:issue(cid,'invalid_dependency','依赖结论失效，摘要及提案须同步修复','depends_on')
    coverage=[]
    requirements=plane.requirements();reading=plane.reading_status()
    resolutions={r.requirement_id:r for r in draft.requirement_resolutions}
    checks={key:value for kind in ('reading','tool','discovery','evidence','table','calculation','reconciliation') for key,value in plane.receipts(kind).items()}
    reconciliations=plane.receipts('reconciliation')
    for req in requirements:
        r=resolutions.get(req['id']);status='missing';explanation='尚未登记检查结果';ids=[]
        if r:
            ids=r.claim_ids;explanation=r.explanation
            if r.status=='answered':status='answered' if ids and all(x in claims and x not in bad for x in ids) else 'invalid'
            elif r.status=='gap':
                status='gap' if r.explanation and r.needed_input and r.check_receipts and all(x in checks for x in r.check_receipts) and ids and all(x in claims and x not in bad for x in ids) else 'invalid'
                invalid=[]
                if not r.explanation:invalid.append('explanation 缺失')
                if not r.needed_input:invalid.append('needed_input 缺失：明确仍缺的原始资料')
                if not r.check_receipts:invalid.append('check_receipts 缺失：填写本次账本中的原件阅读、检索或核算凭据')
                invalid.extend(f'check_receipts[{i}]={ref} 不在本次检查账本' for i,ref in enumerate(r.check_receipts) if ref not in checks)
                if not ids:invalid.append('claim_ids 缺失：缺口需要关联报告中的 claim_ids，明确它阻止哪个判断')
                invalid.extend(f'claim_ids[{i}]={ref} 不存在或该结论尚有核验错误' for i,ref in enumerate(ids) if ref not in claims or ref in bad)
                if invalid:explanation='requirement_resolutions['+req['id']+']：'+'；'.join(invalid)
            if status in ('answered','gap') and req.get('required_concepts'):
                normalize=lambda text:re.sub(r'[\W_]+','',text.casefold())
                visible=normalize(' '.join(getattr(claims[x],field) for x in ids if x in claims for field in ('text','alternative','counterevidence_notes','next_check')))
                absent=[c['name'] for c in req['required_concepts'] if not any(normalize(term) in visible for term in c['terms'])]
                if absent:status='invalid';explanation='关联的研究判断尚未明确回答这些原观点概念：'+'、'.join(absent)+'。在 text/alternative/counterevidence_notes/next_check 给出评价、依据或具体限制；original_claim 中仅复述作者原句，以及要求清单自报 answered，都不算完成。'
            if req['source_id'] and req['pages']:
                pages=[p for p in reading if p['source_id']==req['source_id'] and p['page'] in req['pages']]
                if not pages or any(p['status']!='read' for p in pages):
                    if status!='gap' or not any(p['errors'] for p in pages):status='invalid';explanation='指定关键页面尚未完整阅读，请 read_page；图表必要时 visual=true'
            table_blocks=quantitative_table_blocks(req,plane)
            if status=='answered' and table_blocks:
                linked={x for c in rendered if c['id'] in ids for x in c['calculations']}
                computed={x for x in linked if x in calcs and calcs[x]['formula'] not in ('source_literal','observation','explicit scenario assumption')}
                _,inputs=closure(computed,calcs)
                if not any(evidence.get(x,{}).get('source_id')==req['source_id'] and evidence[x]['block_id'] in table_blocks for x in inputs):
                    status='invalid';explanation='此关键财务表已读，但回答尚未引用与此表输入关联的受控计算；仅抄写原表百分比不等于重算。请登记原数值并计算预期差、预测修订或估值加总。'
            check=req.get('check','answer')
            if check=='consensus_comparison_ratios' and status=='answered':
                linked={x for c in rendered if c['id'] in ids for x in c['calculations']}
                candidates=[]
                for calc_id in linked:
                    calc=calcs.get(calc_id,{})
                    roles=set(calc.get('source_roles',[]))
                    if calc.get('formula')!='compare' or 'reported_consensus' not in roles or not roles & {'reported_actual','company_actual'}:continue
                    _,origins=closure({calc_id},calcs)
                    if any(evidence.get(x,{}).get('source_id')==req['source_id'] and (not table_blocks or evidence[x]['block_id'] in table_blocks) for x in origins):candidates.append(calc)
                norm=lambda value:re.sub(r'[-_\s]+','',value.casefold())
                missing_targets=[target for target in req.get('required_comparisons',[]) if not any(
                    calc.get('metric','').removesuffix('_compare').replace('net_profit','net_income').replace('operating_income','operating_profit').endswith(target['metric'])
                    and (not target['period'] or calc.get('period')==target['period'])
                    and (not target['basis'] or norm(calc.get('basis',''))==norm(target['basis'])) for calc in candidates)]
                if missing_targets:
                    status='invalid';explanation='实际值与共识的重算尚未完成：'+'、'.join(x['metric']+' / '+x['period']+(' / '+x['basis'] if x['basis'] else '') for x in missing_targets)+'。需要引用原表 actual / consensus − 1 的 compare 结果；读过表、引用原作者百分比、只算费用桥或预测修订不能替代。'
            if check=='forecast_revision_ratios' and status=='answered':
                linked={x for c in rendered if c['id'] in ids for x in c['calculations']}
                matches=set()
                for calc_id in linked:
                    calc=calcs.get(calc_id,{})
                    if calc.get('formula')!='compare' or calc.get('source_roles')!=['broker_forecast']:continue
                    _,origins=closure({calc_id},calcs)
                    if not origins or not all(evidence.get(x,{}).get('source_id')==req['source_id'] and (not table_blocks or evidence[x]['block_id'] in table_blocks) for x in origins):continue
                    year=re.sub(r'(?:FY|E)$','',calc.get('period',''))
                    matches.add((calc.get('metric','').removesuffix('_compare'),year))
                missing_pairs=[metric+' / '+period for metric in req.get('required_metrics',[]) for period in req.get('required_periods',[]) or [''] if not any(m==metric and (not period or y==re.sub(r'(?:FY|E)$','',period)) for m,y in matches)]
                if missing_pairs:
                    status='invalid';explanation='预测修订尚缺原表 current / previous − 1 的受控百分比计算：'+'、'.join(missing_pairs)+'。用 compare，保留 broker_forecast 身份并在关联结论引用；绝对额变化不能替代。'
            if check in ('consensus_profit_reconciliation','segment_revenue_reconciliation','valuation_price_reconciliation') and status=='answered':
                linked={x for c in rendered if c['id'] in ids for x in c['calculations']}
                matching=[]
                for rec in reconciliations.values():
                    if rec['residual']['id'] not in linked:continue
                    inputs=[calcs[x] for x in rec['components']+[rec['reported_total']] if x in calcs]
                    total=calcs.get(rec['reported_total'],{})
                    _,origins=closure(set(rec['components']+[rec['reported_total']]),calcs)
                    original_only=bool(origins) and all(evidence.get(x,{}).get('source_id')==req['source_id'] for x in origins)
                    if check=='consensus_profit_reconciliation':
                        appropriate='operating_profit' in total.get('metric','') and all('reported_consensus' in x.get('source_roles',[]) for x in inputs)
                    elif check=='valuation_price_reconciliation':
                        appropriate=canonical_unit(total.get('unit','')).endswith('_per_ADS') and all('broker_forecast' in x.get('source_roles',[]) for x in inputs)
                    else:
                        appropriate='revenue' in total.get('metric','') and all('revenue' in x['metric'] and 'broker_forecast' in x.get('source_roles',[]) for x in inputs)
                    if original_only and appropriate:matching.append(rec)
                if not matching:
                    status='invalid';explanation=('尚未引用原研报每 ADS 分部估值及净现金加总对目标价的 reconcile_totals 残差；同时展示计算总价与舍入范围。' if check=='valuation_price_reconciliation' else '尚未引用针对原研报指定口径的 reconcile_totals 残差；公司实际收入分类加总或每 ADS 价格加总不能替代这项核对。')
            if check=='public_investigation' and status in ('answered','gap'):
                fetches=[x for x in plane.receipts('tool').values() if x['name']=='fetch_public_source']
                discoveries=[x for x in plane.receipts('discovery').values() if x.get('actual_searches')]
                acquired={x.get('result',{}).get('source_id') for x in fetches if not x.get('error') and x.get('result',{}).get('included')}
                if not fetches:
                    if not (status=='gap' and discoveries and not any(x.get('candidates') for x in discoveries)):
                        status='invalid';explanation='公开补查尚未取得并阅读原件。搜索只发现线索；已定位候选原件时，请 fetch_public_source 后 read_source/read_page，并把原件证据或阅读凭据关联本项。不能把尚未尝试获取说成资料不足，也不能只降为后续建议。'
                elif acquired:
                    read_sources={x['source_id'] for x in plane.receipts('reading').values() if not x.get('error') and (x.get('block_ids') or x.get('mode')=='visual')}
                    linked_sources={evidence[ref]['source_id'] for c in rendered if c['id'] in ids for ref in c['evidence']+c['counterevidence']+c['calculation_evidence'] if ref in evidence and ref not in invalid_refs}
                    checked_sources={x['source_id'] for ref in r.check_receipts if (x:=plane.receipts('reading').get(ref)) and not x.get('error')}
                    if not acquired & read_sources & (linked_sources|checked_sources):
                        status='invalid';explanation='公开原件已取得，但尚未实际阅读并关联本项判断；请 read_source/read_page，把相关 evidence_ID 或 reading_receipt 绑定报告或本项 check_receipts。下载完成不等于查证完成。'
                elif status!='gap':
                    status='invalid';explanation='公开原件获取未成功。继续尝试合理替代路径；仍无法取得时按 gap 记录具体失败、必要资料、受影响判断及实际检查凭据，不能自报 answered。'
            if check in ('consensus_comparison_ratios','forecast_revision_ratios','valuation_price_reconciliation','consensus_profit_reconciliation','segment_revenue_reconciliation') and status=='gap' and re.search(r'完整.*模型|Excel|官方.*分部|共识.*快照|Bloomberg|FactSet',r.needed_input,re.I):
                status='invalid';explanation='此项检查原研报已列数字的内部勾稽，完整模型、独立共识数据库或官方分部实际值不是必要输入；若原表缺数，请明确缺少哪一行/列。'
            gap_context=r.explanation+' '+r.needed_input+' '+' '.join(claims[x].counterevidence_notes for x in ids if x in claims)
            if check in ('consensus_comparison_ratios','forecast_revision_ratios','valuation_price_reconciliation','consensus_profit_reconciliation','segment_revenue_reconciliation') and status=='gap' and re.search(r'计算工具|工具.{0,40}(?:拒绝|报错|受阻|错误)|指标名.{0,8}(?:不同|不一致)|metric.{0,30}(?:mismatch|different)|接口.{0,12}(?:失败|拒绝)|重新登记.{0,20}(?:预测|口径|指标)|重跑\s*compare',gap_context,re.I):
                status='invalid';explanation='工具使用或输入登记错误不是资料缺口。原表已有数字时，按错误字段修正并重算；actual/consensus 或 current/previous 使用相同经济指标 metric，身份放在 role/column_label。只有明确缺少原表输入才能标为资料不足。'
        coverage.append(CoverageCheck(key=req['id'],status=status,claim_ids=ids,explanation=explanation))
    for c in rendered:c['validation']='needs_repair' if c['id'] in bad else 'integrity_checked'
    gaps=list(dict.fromkeys(f['issues']+draft.gaps))
    missing=any(c.status in ('missing','invalid','gap') for c in coverage)
    status='needs_review' if issues else 'partial' if missing or gaps else 'review_ready'
    used_calcs={x for c in rendered for x in c['calculations']};used_calcs,operand_evidence=closure(used_calcs,calcs)
    used_evidence={x for c in rendered for x in c['evidence']+c['counterevidence']+c['original_evidence']}|operand_evidence
    return ResearchOutcome(schema_version=3,title=draft.title,request_id=plane.request['id'],input_version=f['version'],snapshot=f['snapshot'],as_of=f['as_of'],intent=plane.input['intent'],
       claims=rendered,evidence=[evidence[x] for x in sorted(used_evidence) if x in evidence and x not in invalid_refs],calculations=[calcs[x] for x in sorted(used_calcs) if x in calcs],
       metrics=f['rows'],coverage=coverage,gaps=gaps,issues=issues,status=status,requirements=requirements,
       requirement_resolutions=draft.requirement_resolutions,reading=reading,
       verification={'source_location':'failed' if any(i['code'] in ('evidence','source_invalidated','numeric_source') for i in issues) else 'checked',
         'numeric_integrity':'failed' if any(i['code'] in NUMERIC_CODES for i in issues) else 'checked',
         'citation_integrity':'failed' if any(i['code'] in ('evidence','source_invalidated') for i in issues) else 'checked',
         'source_support':'human_review_required','inference':'human_review_required','original_claims':len(original),
         'retained_claims':len(draft.claims),'invalid_claims':len(bad),'removed_claims':len(removed),'deleted_claims':removed,
         'added_claims':len(set(claims)-{c['id'] for c in original}),'reference_syntax_normalizations':normalizations,'human_utility':'not_measured'},
       handoffs=[]).model_dump()
