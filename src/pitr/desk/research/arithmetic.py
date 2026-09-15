"""Dimension-checked table calculations; provenance survives arithmetic."""

def calculate(plane, operation, a, b):
    if not a or not b or a['value'] is None or b['value'] is None: raise ValueError('计算输入缺失或不属于本次运行')
    if a['period'] != b['period']: raise ValueError(f"period 不同：left={a['period']} ({a['id']}), right={b['period']} ({b['id']})；同指标跨期变化请用 change/growth")
    unit = a['unit']; metric = a['metric'] + '_' + operation
    if operation in ('add', 'sum_difference', 'compare'):
        mismatch={k:{'left':a[k],'right':b[k]} for k in ('unit','currency','basis','share_basis','frequency') if a[k]!=b[k]}
        if mismatch:raise ValueError(f"计算输入口径不同 {mismatch}；left={a['id']}, right={b['id']}。按原件重新登记正确口径；不确定时使用同一表的 reported_actual/consensus 并保留口径限制，不要猜测 GAAP。")
        if operation == 'compare':
            if a['metric'] != b['metric']: raise ValueError(f"预期差/预测修订必须比较相同经济指标：left.metric={a['metric']} ({a['id']}), right.metric={b['metric']} ({b['id']})。若只是 actual/consensus 或 current/previous 身份不同，请从原文重新登记相同 metric，把身份保留在 role/column_label；不要删除真实口径差异。")
            if not b['value']: raise ValueError('零基期无法计算百分比')
            value = (a['value']-b['value'])/abs(b['value'])*100; unit = 'percent'
        else: value = a['value'] + b['value'] if operation=='add' else a['value']-b['value']
    elif operation == 'multiply':
        if b['unit'] not in ('multiple','percent','ratio'): raise ValueError('乘法右输入必须为倍数或比例；币种换算使用 divide 和有依据的汇率')
        value = a['value']*b['value']/(100 if b['unit']=='percent' else 1)
    else:
        if not b['value']: raise ValueError('分母不能为零')
        if a['unit']==b['unit']:
            if a['basis']!=b['basis'] or a['frequency']!=b['frequency']: raise ValueError('比例输入口径不一致')
            unit='ratio'
        elif a['unit']=='RMB_mn' and b['unit']=='RMB_per_USD':unit='USD_mn'
        elif a['unit'] in ('USD_mn','RMB_mn') and b['unit']=='ADS_mn':unit=a['unit'].split('_')[0]+'_per_ADS'
        else:raise ValueError('未登记的量纲换算；需要明确汇率或 ADS 数量依据')
        value=a['value']/b['value']
    return plane._calc(metric,value,unit,a['period'],operation,[a['id'],b['id']],basis=a['basis'],frequency=a['frequency'],
        assumption=a.get('assumption',False) or b.get('assumption',False),
        source_roles=sorted(set(a.get('source_roles',[])+b.get('source_roles',[]))),
        verification_status='quoted_not_independently_verified' if any(x.get('verification_status')=='quoted_not_independently_verified' for x in (a,b)) else 'source_bound',
        limitations=list(dict.fromkeys(a.get('limitations',[])+b.get('limitations',[]))),
        direction=('increase' if value>0 else 'decrease' if value<0 else 'unchanged') if operation in ('compare','sum_difference') else None)
