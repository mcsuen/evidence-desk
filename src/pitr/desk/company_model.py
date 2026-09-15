"""PDD operating model. Only versioned formulas compute; missing inputs propagate.

The model stops at operating profit. Below-the-line items, cash flow and ADS
earnings need their own reconciled schedules, and are never inferred from OP.
"""
from __future__ import annotations
import json
import re
from typing import Literal
from pydantic import Field
from .contracts import Contract, Citation, Metric
from .financials import point
from .storage import canonical

ENGINE = 'pdd-operating.1'
PARAMS = [
    ('online_marketing_yoy','在线营销收入同比','percent',-100,1000),
    ('transaction_services_yoy','交易服务收入同比','percent',-100,1000),
    ('gross_margin','毛利率','percent',0,100),
    ('sales_marketing_rate','销售与营销费用率','percent',0,200),
    ('general_admin_rate','一般及行政费用率','percent',0,200),
    ('research_development_rate','研发费用率','percent',0,200),
]
OUTPUTS = [
    ('online_marketing','在线营销服务及其他','RMB_mn'),
    ('transaction_services','交易服务收入','RMB_mn'),
    ('revenue','收入','RMB_mn'),('cost_of_revenue','收入成本','RMB_mn'),
    ('sales_marketing','销售与营销费用','RMB_mn'),('general_admin','一般及行政费用','RMB_mn'),
    ('research_development','研发费用','RMB_mn'),('operating_profit','经营利润','RMB_mn'),
    ('operating_margin','经营利润率','percent'),
]


class Assumption(Contract):
    parameter: str
    period: str
    value: float | None = None
    reason: str = ''
    provenance: Literal['user','mechanical_reference'] = 'user'
    citations: list[Citation] = Field(default_factory=list)


class ModelSpec(Contract):
    engine: Literal['pdd-operating.1'] = ENGINE
    snapshot: str
    anchor_period: str
    assumptions: list[Assumption] = Field(default_factory=list)
    scenario: str = '基准草稿'
    investigation_id: str | None = None


class CalculateInput(Contract):
    spec: ModelSpec


class ModelCell(Contract):
    key: str
    period: str
    value: float | None
    kind: Literal['actual','forecast','mixed']
    formula: str
    dependencies: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class ModelView(Contract):
    spec: ModelSpec
    company: str
    as_of: str
    history_periods: list[str]
    forecast_periods: list[str]
    parameters: list[dict]
    outputs: list[dict]
    cells: list[ModelCell]
    annual: list[ModelCell]
    checks: list[dict]
    references: list[Assumption]
    published: dict | None = None
    issues: list[str]


def shift(period, quarters):
    if not re.fullmatch(r'20\d{2}Q[1-4]',period):raise ValueError('需要独立季度期间')
    index=int(period[:4])*4+int(period[-1])-1+quarters
    return f'{index//4}Q{index%4+1}'


def inputs(desk,snapshot):
    with desk.store.connect() as db:snap=desk._snapshot(db,snapshot)
    if snap['company']!='PDD':raise ValueError('当前公司模型只支持 PDD；其他公司需要独立披露映射')
    metrics=[Metric.model_validate(m) for m in snap['observations']]
    dates={sid:desk.document(sid).available_at for sid in snap['sources']}
    return snap,metrics,dates


def calculate(desk,spec: ModelSpec) -> ModelView:
    snap,metrics,dates=inputs(desk,spec.snapshot)
    anchor=spec.anchor_period
    shift(anchor,0)
    if not any(m.period==anchor and m.frequency=='quarter' for m in metrics):raise ValueError('快照中没有该季度的实际资料')
    end=f'{int(anchor[:4])+2}Q4'
    forecast=[];period=shift(anchor,1)
    while period<=end:forecast.append(period);period=shift(period,1)
    history=[shift(anchor,i) for i in range(-7,1)]
    allowed={p[0]:p for p in PARAMS};assumptions={}
    for a in spec.assumptions:
        if a.parameter not in allowed or a.period not in forecast:raise ValueError('假设指标或期间不属于模型')
        if (a.parameter,a.period) in assumptions:raise ValueError('重复假设单元格')
        lo,hi=allowed[a.parameter][3:]
        if a.value is not None and not lo<=a.value<=hi:raise ValueError('假设超出允许范围：'+a.parameter)
        desk.validate_citations(a.citations,snap)
        assumptions[a.parameter,a.period]=a
    actual_cache={}
    def actual(key,period):
        # Forecast bases never use observations from after the selected anchor,
        # even when the enclosing source snapshot contains newer documents.
        if period>anchor:raise ValueError('不能将未来实际值放入预测列')
        if (key,period) not in actual_cache:actual_cache[key,period]=point(key,period,metrics,dates)
        return actual_cache[key,period]
    cells={};checks=[]
    def add(key,period,value,kind,formula,deps=(),missing=(),citations=()):
        c=ModelCell(key=key,period=period,value=value,kind=kind,formula=formula,
            dependencies=list(deps),missing=list(dict.fromkeys(missing)),citations=list(citations))
        cells[key,period]=c;return c
    for period in history:
        for key,_,_ in OUTPUTS:
            p=actual(key,period)
            add(key,period,p.value,'actual',p.calculation,p.observation_ids,p.issues if p.value is None else [],p.citations)
        def check(name,keys,signs):
            ps=[actual(k,period) for k in keys]
            residual=sum(p.value*s for p,s in zip(ps,signs)) if all(p.value is not None for p in ps) else None
            checks.append({'period':period,'check':name,'residual':residual,'unit':'RMB_mn',
                'status':'missing' if residual is None else 'consistent' if abs(residual)<=3 else 'conflict'})
        check('两类收入合计', ['revenue','online_marketing','transaction_services'],[1,-1,-1])
        check('经营利润勾稽',['revenue','cost_of_revenue','sales_marketing','general_admin','research_development','operating_profit'],[1,-1,-1,-1,-1,-1])
    for period in forecast:
        for param in allowed:
            a=assumptions.get((param,period));value=a.value if a else None
            add(param,period,value,'forecast','用户假设',missing=[] if value is not None else [param+'@'+period],citations=a.citations if a else [])
        def formula(key,deps,fn,text):
            ps=[cells[d] for d in deps]
            missing=[m for p in ps for m in p.missing]
            ready=all(p.value is not None for p in ps)
            refs={canonical(c):c for p in ps for c in p.citations}
            return add(key,period,fn(*[p.value for p in ps]) if ready else None,'forecast',text,
                [k+'@'+p for k,p in deps],missing or ([] if ready else [key+'@'+period]),refs.values())
        for key in ('online_marketing','transaction_services'):
            prior=shift(period,-4)
            if (key,prior) not in cells:
                p=actual(key,prior);add(key,prior,p.value,'actual',p.calculation,p.observation_ids,p.issues if p.value is None else [],p.citations)
            formula(key,[(key,prior),(key+'_yoy',period)],lambda a,g:a*(1+g/100),'上年同季收入 × (1 + 同比假设 / 100)')
        formula('revenue',[(k,period) for k in ('online_marketing','transaction_services')],lambda a,b:a+b,'在线营销收入 + 交易服务收入')
        for key,param,invert in [('cost_of_revenue','gross_margin',True),('sales_marketing','sales_marketing_rate',False),('general_admin','general_admin_rate',False),('research_development','research_development_rate',False)]:
            formula(key,[('revenue',period),(param,period)],lambda r,p:r*(1-p/100 if invert else p/100),'收入 × '+('(1 − 毛利率 / 100)' if invert else '费用率 / 100'))
        formula('operating_profit',[(k,period) for k in ('revenue','cost_of_revenue','sales_marketing','general_admin','research_development')],lambda r,c,s,g,d:r-c-s-g-d,'收入 − 收入成本 − 销售费用 − 管理费用 − 研发费用')
        formula('operating_margin',[('operating_profit',period),('revenue',period)],lambda op,r:op/r*100 if r else None,'经营利润 ÷ 收入 × 100')
    annual=[]
    for year in range(int(anchor[:4]),int(anchor[:4])+3):
        qs=[f'{year}Q{i}' for i in range(1,5)]
        year_cells={}
        for key,_,_ in OUTPUTS:
            parts=[]
            for q in qs:
                c=cells.get((key,q))
                if c is None and q<=anchor:
                    p=actual(key,q);c=ModelCell(key=key,period=q,value=p.value,kind='actual',formula=p.calculation,citations=p.citations,missing=p.issues if p.value is None else [])
                parts.append(c)
            missing=[f'{key}@{q}' for q,c in zip(qs,parts) if c is None or c.value is None]
            if key=='operating_margin':
                op,rev=year_cells['operating_profit'].value,year_cells['revenue'].value
                value=op/rev*100 if op is not None and rev not in (None,0) else None
                formula='全年经营利润 ÷ 全年收入 × 100'
            else:value=sum(c.value for c in parts) if not missing else None;formula='四个独立季度相加'
            cell=ModelCell(key=key,period=f'{year}FY',value=value,kind='mixed' if year==int(anchor[:4]) and not anchor.endswith('Q4') else 'actual' if qs[-1]<=anchor else 'forecast',formula=formula,
                dependencies=[key+'@'+q for q in qs],missing=missing,citations=list({canonical(cit):cit for c in parts if c for cit in c.citations}.values()))
            year_cells[key]=cell;annual.append(cell)
    references=[]
    for param,_,_,_,_ in PARAMS:
        if param.endswith('_yoy'):
            key=param[:-4];a,b=actual(key,anchor),actual(key,shift(anchor,-4))
            value=(a.value/b.value-1)*100 if a.value is not None and b.value not in (None,0) else None
            refs=a.citations+b.citations
        else:a=actual(param,anchor);value=a.value;refs=a.citations
        references.append(Assumption(parameter=param,period=forecast[0],value=value,provenance='mechanical_reference',
            reason='最近已披露季度的同口径读数；延续仅作为机械情景，需要研究者重新判断',citations=refs))
    published=next((o for o in snap.get('objects',{}).values() if o['id']=='model:PDD:operating'),None)
    return ModelView(spec=spec,company='PDD',as_of=snap['as_of'],history_periods=history,forecast_periods=forecast,
        parameters=[{'key':k,'label':l,'unit':u,'min':lo,'max':hi} for k,l,u,lo,hi in PARAMS],
        outputs=[{'key':k,'label':l,'unit':u} for k,l,u in OUTPUTS],cells=list(cells.values()),annual=annual,checks=checks,references=references,published=published,
        issues=['经营模型目前止于经营利润；税项、非经营损益、现金流、净利润与每 ADS 预测尚未接入',
            '交易服务收入不等于 Temu 收入；未披露的分部驱动保持未知',
            '机械延续用于试算，不是用户预测或市场一致预期'])


def get_draft(desk,draft_id):
    with desk.store.connect() as db:row=db.execute("SELECT body FROM imports WHERE id=? AND kind='operating_draft'",(draft_id,)).fetchone()
    if not row:raise ValueError('模型草稿不存在')
    return json.loads(row['body'])
