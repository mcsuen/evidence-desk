"""Reconcile quoted components with a quoted total, without claiming the author is wrong."""
import re

def reconcile(plane, components, reported_total, signs=None):
    refs=plane.receipts('calculation')
    if not components or any(not isinstance(x,str) or x not in refs for x in components) or reported_total not in refs:
        raise ValueError('components 和 reported_total 必须为已登记计算编号；缺少输入时先读取并登记原表数值')
    values=[refs[x] for x in components];total=refs[reported_total]
    signs=[1]*len(values) if signs is None else signs
    if len(signs)!=len(values) or any(s not in (-1,1) for s in signs):raise ValueError('每个分项对应一个 +1 或 -1 符号')
    for ref in values+[total]:
        if ref['value'] is None:raise ValueError('输入为空：'+ref['id'])
        mismatch={k:[ref[k],total[k]] for k in ('period','frequency','unit','currency','basis','share_basis') if ref[k]!=total[k]}
        if mismatch:raise ValueError('勾稽输入口径不同 '+str(mismatch)+'；输入 '+ref['id']+' 与总计 '+reported_total)
    deps=components+[reported_total]
    limitations=list(dict.fromkeys(s for c in values+[total] for s in c.get('limitations',[])))
    limitations.append('不一致可能来自口径、预测聚合方式或舍入；残差本身不证明作者计算错误。')
    metadata={'basis':total['basis'],'frequency':total['frequency'],'assumption':any(c.get('assumption') for c in values+[total]),
        'source_roles':sorted({r for c in values+[total] for r in c.get('source_roles',[])}),
        'verification_status':'quoted_not_independently_verified' if any(c.get('verification_status')=='quoted_not_independently_verified' for c in values+[total]) else 'source_bound',
        'limitations':limitations}
    value=sum(s*c['value'] for s,c in zip(signs,values))
    component_total=plane._calc(total['metric']+'_component_total',value,total['unit'],total['period'],'reconcile_totals',deps,**metadata)
    residual=plane._calc(total['metric']+'_reconciliation',value-total['value'],total['unit'],total['period'],'reconcile_residual',[component_total['id'],reported_total],**metadata)
    bound=0.;known=True
    for ref in values+[total]:
        locator=ref.get('source_locator',{});literal=locator.get('literal','').replace(',','').strip('()% ')
        if not re.fullmatch(r'[-+−]?\d+(?:\.\d+)?',literal):known=False;break
        digits=len(literal.rsplit('.',1)[1]) if '.' in literal else 0
        bound+=.5*10**(-digits)*abs(locator.get('scale',1))
    rounding=plane._calc(total['metric']+'_rounding_bound',bound,total['unit'],total['period'],'original_display_rounding_bound',deps,**metadata) if known else None
    return plane.receipt('reconciliation',{'components':components,'signs':signs,'reported_total':reported_total,
        'component_total':component_total,'residual':residual,'rounding_bound':rounding,
        'within_original_rounding':abs(residual['value'])<=bound+1e-9 if known else None,
        'note':'按原表显示精度核对加总；来源核实状态和口径限制仍保留，不能由此直接认定券商算错。'})
