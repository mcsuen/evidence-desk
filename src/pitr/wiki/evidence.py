"""Give writers auditable values; render their selections without model arithmetic."""
import copy
import json
import re
from pitr.desk.contracts import utcnow
from .validation import FIELDS, calculate, display_number
from pitr.desk.storage import canonical, digest

SLOT = re.compile(r'\{\{n:([A-Za-z0-9_-]+)\}\}')
NAMES = {'revenue','online_marketing','transaction_services','cost_of_revenue','sales_marketing',
         'general_admin','research_development','operating_expenses','operating_profit','net_income',
         'investment_income','fx_gain_loss','other_gain_loss','equity_gain_loss','income_tax',
         'operating_cash_flow','sbc','cash','restricted_cash','merchant_payables','merchant_deposits'}


def citation_anchor(citation):
    value = 2166136261
    for byte in (citation['source_id'] + ':' + citation['block_id']).encode():
        value = ((value ^ byte) * 16777619) & 0xffffffff
    # Alphabetic anchors do not introduce unbound numeric claims into Markdown.
    return 'evidence-' + ''.join(chr(97 + int(c,16)) for c in f'{value:08x}')


def supporting_sources(st, selected, company):
    """Add the matching prior-year quarters and latest annual business context."""
    chosen = {s['id']:s for s in selected}
    periods = {match.group() for s in selected for match in re.finditer(r'20\d{2}Q[1-4]',s['title'])}
    prior = {str(int(p[:4])-1)+p[4:] for p in periods}
    cutoff = utcnow()
    available = [s for s in st['sources'].values() if s['company']==company and s['provider']=='official'
                 and s['state']=='available' and s['available_at']<=cutoff]
    for period in sorted(prior):
        matches = [s for s in available if period in s['title']]
        if matches:
            source=max(matches,key=lambda s:s['available_at']);chosen[source['id']]=source
    annual = [s for s in available if '年度报告' in s['title'] or 'annual report' in s['title'].lower()]
    if annual:
        source=max(annual,key=lambda s:s['available_at']);chosen[source['id']]=source
    return list(chosen.values())


def source_excerpt(source, limit=32000):
    """Keep readable neighborhoods and disclose omissions in long annual reports."""
    blocks = source['blocks']
    if sum(len(b['text']) for b in blocks)<=limit:
        return {**source,'context_complete':True}
    terms = re.compile(r'our business|business model|online marketing services|transaction services|'
        r'revenue recognition|temu|pinduoduo|merchants pay|competitive|first.party|supply chain',re.I)
    mechanics = re.compile(r'we charge|charge merchants|impressions or|cost.per.click|pay.per.click|'
        r'we primarily generate|our platforms|our business overview|we operate.*platform',re.I)
    selected=set()
    for i in range(min(12,len(blocks))):
        if sum(len(blocks[j]['text']) for j in selected)+len(blocks[i]['text'])>limit//10:break
        selected.add(i)
    score=lambda text:len({m.lower() for m in terms.findall(text)})+10*len({m.lower() for m in mechanics.findall(text)})
    candidates=sorted(range(len(blocks)),key=lambda i:(-score(blocks[i]['text']),i))
    size=sum(len(blocks[i]['text']) for i in selected)
    for index in candidates:
        if not score(blocks[index]['text']):break
        neighborhood=set(range(max(0,index-2),min(len(blocks),index+4)))-selected
        cost=sum(len(blocks[i]['text']) for i in neighborhood)
        if size+cost<=limit:selected|=neighborhood;size+=cost
    return {**source,'blocks':[blocks[i] for i in sorted(selected)],'context_complete':False,
            'omitted_blocks':len(blocks)-len(selected),'excerpt_rule':'business-and-accounting-neighborhoods.1'}


def prepare_metrics(wiki, sources):
    """Extend the extraction cache without replacing saved or human-corrected rows."""
    from pitr.desk.sources import extract_pdd_metrics
    ids={s['id'] for s in sources}
    with wiki.store.connect(write=True) as db:
        existing={r['id'] for r in db.execute('SELECT id FROM observations')}
        added=[]
        for source in sources:
            if source['provider']!='official':continue
            doc=wiki.desk.document(source['id'])
            for metric in extract_pdd_metrics(doc):
                if metric.id in existing:continue
                db.execute('INSERT INTO observations VALUES(?,?,?,?)',
                    (metric.id,doc.company,doc.id,canonical(metric)))
                existing.add(metric.id);added.append(metric.model_dump())
        if added:
            wiki._emit(db,sources[0]['company'],'source.metrics_extracted',[],
                details={'method':'statement-lines.2','policy':wiki._policy(db),'observations':added})
        return [json.loads(r['body']) for r in db.execute('SELECT source_id,body FROM observations') if r['source_id'] in ids]


def number_catalog(metrics, sources):
    by_source={s['id']:s for s in sources}
    def precision(metric):
        text='\n'.join(b['text'] for b in by_source[metric['citation']['source_id']]['blocks'])
        if metric['unit']=='RMB_mn' and re.search(r'Amounts\s+in\s+millions',text,re.I):return 0
        return 3
    chosen={}
    for metric in metrics:
        if metric['name'] not in NAMES or metric['frequency'] not in ('quarter','annual','instant'):continue
        key=(metric['name'],metric['period'],metric['basis'],metric['unit'])
        previous=chosen.get(key)
        if previous is None or by_source[metric['citation']['source_id']]['available_at']>by_source[previous['citation']['source_id']]['available_at']:
            chosen[key]=metric
    catalog={}
    def add(label,period,unit,binding,citations,value,decimals=3):
        identity='n_'+digest([label,period,unit,binding])[:14]
        binding={**binding,'display_decimals':decimals}
        catalog[identity]={'token':'{{n:'+identity+'}}','label':label,'period':period,'unit':unit,
            'display':format(display_number(value,decimals),','+f'.{decimals}f'),
            'binding':binding,'citations':citations,
            'calculation':binding.get('expression','原始报表值'), 'review':'提取/计算结果，仍需人工采纳'}
    for metric in chosen.values():
        add(metric['label'],metric['period'],metric['unit'],
            {'kind':'observation','observation_id':metric['id'],**{k:metric[k] for k in ('name','value','unit','period','basis')}},
            [metric['citation']],metric['value'],precision(metric))
    def computed(label,period,operands,expression,unit,decimals=2):
        if any(m is None for m in operands.values()):return
        if len({m['basis'] for m in operands.values()})!=1 or len({m['unit'] for m in operands.values()})!=1:return
        try:value=calculate(expression,{k:m['value'] for k,m in operands.items()})
        except (ValueError,ZeroDivisionError):return
        binding={'kind':'calculation','operands':{k:m['id'] for k,m in operands.items()},'expression':expression,
            'unit':unit,'period':period,'basis':next(iter(operands.values()))['basis'],
            'periods':{k:m['period'] for k,m in operands.items()}}
        if unit=='RMB_mn':decimals=min(precision(m) for m in operands.values())
        add(label,period,unit,binding,list({canonical(m['citation']):m['citation'] for m in operands.values()}.values()),value,decimals)
    rows={(m['name'],m['period']):m for m in chosen.values() if m['basis']=='GAAP' and m['frequency']=='quarter' and m['unit']=='RMB_mn'}
    for period in sorted({p for _,p in rows}):
        prev=str(int(period[:4])-1)+period[4:]
        for name in NAMES:
            current=rows.get((name,period));prior=rows.get((name,prev))
            if current and prior:
                computed(current['label']+'同比增减额',period,{'current':current,'prior':prior},'current-prior','RMB_mn',3)
                if prior['value']>0 and name not in ('fx_gain_loss','other_gain_loss','equity_gain_loss','investment_income'):
                    computed(current['label']+'同比变动',period,{'current':current,'prior':prior},'(current/prior-1)*100','%',2)
        revenue=rows.get(('revenue',period))
        for name,label in [('operating_profit','经营利润率'),('sales_marketing','营销费用率'),('research_development','研发费用率'),('transaction_services','交易服务收入占比')]:
            metric=rows.get((name,period))
            computed(label,period,{'numerator':metric,'revenue':revenue},'numerator/revenue*100','%',2)
            computed(label+'同比变化',period,{'current':metric,'revenue':revenue,'prior':rows.get((name,prev)),'prior_revenue':rows.get(('revenue',prev))},
                     '(current/revenue-prior/prior_revenue)*100','百分点',2)
        bridge={alias:rows.get((name,period)) for alias,name in [('op','operating_profit'),('investment','investment_income'),('fx','fx_gain_loss'),('other','other_gain_loss'),('equity','equity_gain_loss'),('tax','income_tax')]}
        computed('经营利润至净利润桥接合计',period,bridge,'op+investment+fx+other+equity-tax','RMB_mn',3)
        computed('净利润桥接与原表残差',period,{**bridge,'reported':rows.get(('net_income',period))},'op+investment+fx+other+equity-tax-reported','RMB_mn',3)
    return catalog


def prompt_catalog(catalog):
    return [{k:item[k] for k in ('token','label','period','unit','display','calculation','review')} for item in catalog.values()]


def bind_numbers(draft, catalog):
    result=copy.deepcopy(draft)
    bindings=[];citations={canonical(c):c for c in result.get('citations',[])}
    for field in FIELDS:
        text=result.get(field) or '';parts=[];cursor=0;length=0
        for match in SLOT.finditer(text):
            item=catalog.get(match[1])
            if item is None:raise ValueError('模型引用了未提供的数值：'+match[1])
            prefix=text[cursor:match.start()];parts.append(prefix);length+=len(prefix)
            number=item['display'];anchor=citation_anchor(item['citations'][0])
            replacement=f'[{number}](#{anchor})'
            bindings.append({**copy.deepcopy(item['binding']),'field':field,'start':length+1,'end':length+1+len(number)})
            for citation in item['citations']:citations[canonical(citation)]=citation
            parts.append(replacement);length+=len(replacement);cursor=match.end()
        parts.append(text[cursor:]);result[field]=''.join(parts)
        if '{{n:' in result[field]:raise ValueError('模型返回了无法识别的数值标记')
    result['numeric_assertions']=bindings
    result['citations']=list(citations.values())
    return result


def model_page(page):
    """Preserve editable prose and status without duplicated revision caches."""
    from .contracts import RevisionDraft
    keys = set(RevisionDraft.model_fields) | {'version', 'ref', 'availability', 'policy', 'published_at'}
    return {key: value for key, value in page.items() if key in keys}


def cited_excerpt(source, pages, limit=48000):
    """Prioritize exact cited blocks, then neighboring original text."""
    ids = {c['block_id'] for p in pages for c in p.get('citations', []) if c['source_id'] == source['id']}
    blocks = source['blocks']
    selected = {i for i, b in enumerate(blocks) if b['id'] in ids}
    size = sum(len(blocks[i]['text']) for i in selected)
    for i in sorted(selected.copy()):
        for j in (i - 1, i + 1):
            if 0 <= j < len(blocks) and j not in selected and size + len(blocks[j]['text']) <= limit:
                selected.add(j); size += len(blocks[j]['text'])
    result = {k: source.get(k) for k in ('id', 'company', 'subject_company', 'provider', 'title', 'url', 'available_at', 'state', 'digest', 'origin_group')}
    return {**result, 'blocks': [blocks[i] for i in sorted(selected)], 'context_complete': len(selected) == len(blocks),
            'omitted_blocks': len(blocks) - len(selected), 'excerpt_rule': 'actual-citations-and-neighbors.1'}
