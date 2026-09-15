"""Typed financial comparisons. Every derived point carries all operand IDs."""
import re
from .contracts import Metric, Point, MetricRow

# Preserve statement ordering; movement is not an investment recommendation.
DEFINITIONS = [
 ('revenue','收入','经营表现','RMB_mn','flow'),
 ('online_marketing','在线营销服务及其他','经营表现','RMB_mn','flow'),
 ('transaction_services','交易服务收入','经营表现','RMB_mn','flow'),
 ('gross_margin','毛利率','利润与费用','percent','ratio'),
 ('sales_marketing_rate','销售与营销费用率','利润与费用','percent','ratio'),
 ('general_admin_rate','一般及行政费用率','利润与费用','percent','ratio'),
 ('research_development_rate','研发费用率','利润与费用','percent','ratio'),
 ('operating_profit','经营利润','利润与费用','RMB_mn','flow'),
 ('operating_margin','经营利润率','利润与费用','percent','ratio'),
 ('net_income','净利润','利润与费用','RMB_mn','flow'),
 ('eps_ads','摊薄每 ADS 收益','利润与费用','RMB_per_ADS','per_share'),
 ('operating_cash_flow','经营现金流','现金与资产','RMB_mn','flow'),
 ('cash','现金及现金等价物','现金与资产','RMB_mn','stock'),
 ('short_investments','短期投资','现金与资产','RMB_mn','stock'),
 ('restricted_cash','受限现金','现金与资产','RMB_mn','stock'),
 ('merchant_payables','应付商家款项','现金与资产','RMB_mn','stock'),
 ('merchant_deposits','商家保证金','现金与资产','RMB_mn','stock'),
 ('cost_of_revenue','收入成本','完整报表','RMB_mn','flow'),
 ('sales_marketing','销售与营销费用','完整报表','RMB_mn','flow'),
 ('general_admin','一般及行政费用','完整报表','RMB_mn','flow'),
 ('research_development','研发费用','完整报表','RMB_mn','flow'),
]
RATIOS = {'gross_margin':('cost_of_revenue',True), 'operating_margin':('operating_profit',False),
          **{k+'_rate':(k,False) for k in ('sales_marketing','general_admin','research_development')}}


def comparable(a, b):
    return (a.unit,a.basis,a.frequency) == (b.unit,b.basis,b.frequency)


def point(name, period, metrics: list[Metric], dates: dict[str,str]) -> Point:
    if name in RATIOS:
        operand, invert = RATIOS[name]
        a, b = point(operand,period,metrics,dates), point('revenue',period,metrics,dates)
        valid = a.value is not None and b.value not in (None,0)
        return Point(period=period,value=((1-a.value/b.value) if invert else a.value/b.value)*100 if valid else None,
            observation_ids=a.observation_ids+b.observation_ids,citations=a.citations+b.citations,
            calculation=('(收入 − 收入成本) ÷ 收入 × 100' if invert else operand+' ÷ 收入 × 100'),
            issues=list(dict.fromkeys(a.issues+b.issues+([] if valid else ['缺少比例计算的同口径输入']))))
    hits=[m for m in metrics if m.name==name and m.period==period and m.frequency in ('quarter','instant') and m.basis=='GAAP']
    if not hits:
        return Point(period=period,value=None,issues=['原件未抽取到该期间的独立季度值'])
    hits.sort(key=lambda m:dates[m.citation.source_id])
    selected=hits[-1]
    issues=[]
    if any(not comparable(m,selected) or abs(m.value-selected.value)>.01 for m in hits):
        # Revisions are explicit; do not silently choose a convenient number.
        return Point(period=period,value=None,observation_ids=[m.id for m in hits],citations=[m.citation for m in hits],issues=['同一指标存在不同披露值，需核对修订'])
    return Point(period=period,value=selected.value,observation_ids=[selected.id],citations=[selected.citation],
                 calculation='原始披露 · '+selected.unit,issues=issues)


def build_rows(metrics, dates, period, expectations, checked, baseline_type):
    periods=sorted({m.period for m in metrics if re.fullmatch(r'20\d{2}Q[1-4]',m.period) and m.period<=period})[-8:]
    previous=str(int(period[:4])-1)+period[4:]
    result=[]
    for key,label,group,unit,nature in DEFINITIONS:
        current=point(key,period,metrics,dates)
        prior=point(key,previous,metrics,dates)
        issues=list(current.issues)
        expected=[e for e in expectations if e['metric']==key and e['period']==period]
        baseline=None
        if expected:
            e=expected[-1]
            if e['unit']!=unit or e['basis']!='GAAP':issues.append('比较基准的单位或会计口径不同')
            else:baseline=e['value']
        yoy=(current.value-prior.value)/abs(prior.value)*100 if current.value is not None and prior.value not in (None,0) and nature!='ratio' else None
        bps=(current.value-prior.value)*100 if current.value is not None and prior.value is not None and nature=='ratio' else None
        difference=current.value-baseline if current.value is not None and baseline is not None else None
        series=[point(key,p,metrics,dates) for p in periods]
        for p in [current,prior,*series]:p.reviewed=bool(p.observation_ids) and all(i in checked for i in p.observation_ids)
        result.append(MetricRow(key=key,label=label,group=group,unit=unit,basis='GAAP',nature=nature,actual=current,prior=prior,
            baseline=baseline,baseline_type=baseline_type,difference=difference,
            difference_pct=difference/abs(baseline)*100 if difference is not None and baseline else None,
            yoy=yoy,yoy_bps=bps,series=series,
            checked=bool(current.observation_ids) and all(i in checked for i in current.observation_ids),issues=issues))
    return result


def margin_bridge(rows):
    by={r.key:r for r in rows}
    names=['operating_margin','gross_margin','sales_marketing_rate','general_admin_rate','research_development_rate']
    if any(by[k].actual.value is None or by[k].prior.value is None for k in names):return []
    opening=by['operating_margin'].prior.value
    result=[{'key':'prior','label':'上年同期','value':opening,'total':True}]
    for k in names[1:]:
        r=by[k];delta=(r.actual.value-r.prior.value)*(1 if k=='gross_margin' else -1)
        result.append({'key':k,'label':r.label,'value':delta,'total':False})
    closing=by['operating_margin'].actual.value
    residual=closing-opening-sum(r['value'] for r in result[1:])
    if abs(residual)>.02:result.append({'key':'residual','label':'其他／舍入','value':residual,'total':False})
    result.append({'key':'current','label':'本季','value':closing,'total':True})
    return result


def quarterize(current: dict, previous: dict):
    for key in ('metric','unit','basis','currency','share_basis','fiscal_year'):
        if current.get(key)!=previous.get(key):raise ValueError('累计转季度输入口径不同：'+key)
    if current.get('quarter') != previous.get('quarter',0)+1:
        raise ValueError('累计输入不相邻')
    if current.get('nature') in ('stock','ratio','per_share'):
        raise ValueError('存量、比例与每股指标不能直接相减')
    return {**current,'value':current['value']-previous['value'],'frequency':'quarter',
            'available_at':max(current['available_at'],previous['available_at']),
            'dependencies':[current['id'],previous['id']]}
