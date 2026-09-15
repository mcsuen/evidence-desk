"""Portable exports use the same validated report data consumed by Web."""
import html,io,base64
from ..storage import canonical

LABELS={'changes':'关键变化','baseline':'实际与有效基准','cash_margin':'利润与现金核对','persistence':'持续性与替代解释','model_impact':'模型影响','questions':'未决问题','claims':'观点核对','summary':'结论','supported':'支持','partial':'部分支持','insufficient':'证据不足','contradicted':'相矛盾','interpretation':'研究解释','integrity_checked':'完整性已检查','needs_repair':'需修复','answered':'已回答','gap':'资料缺口','missing':'未回答','invalid':'需修复','review_ready':'待人工复核','needs_review':'存在核验问题'}

def html_report(report):
    e=lambda v:html.escape(str(v))
    label=lambda v:e(LABELS.get(v,v))
    num=lambda v:'—' if v is None else f'{v:,.2f}'
    evidence_ids={x['id']:i+1 for i,x in enumerate(report['evidence'])}
    rows=[]
    calculations={c['id']:c for c in report['calculations']}
    for c in report['claims']:
        refs=lambda ids:' '.join('<a href="#'+e(ref)+'">['+str(evidence_ids[ref])+']</a>' for ref in dict.fromkeys(ids) if ref in evidence_ids)
        quant='<br>'.join(e(calculations[r]['metric'])+' '+num(calculations[r]['value'])+' '+e(calculations[r]['unit']) for r in c['calculations'] if r in calculations)
        original=e(c.get('original_claim',''))+refs(c.get('original_evidence',[]))
        pages=sorted({x['page'] for x in report['evidence'] if x['id'] in c.get('original_evidence',[]) and x.get('page')})
        if pages:original+='<br><small>第 '+e('、'.join(map(str,pages)))+' 页</small>'
        subsequent='<b>后续信息（不能倒推原报告因果解释）</b><br>' if c.get('temporal_scope')=='subsequent' else ''
        rows.append('<tr><th>'+label(c['section'])+'<br>'+original+'<br><small>'+label(c['verdict'])+'</small></th><td>'+subsequent+e(c['text'])+'</td><td>'+refs(c['evidence']+c.get('calculation_evidence',[]))+'<br>独立来源 '+e(c.get('independent_source_count') if c.get('independent_source_count') is not None else '待复核')+'</td><td>'+e(c['alternative'])+'<br>'+e(c.get('counterevidence_notes',''))+refs(c['counterevidence'])+'</td><td>'+quant+'</td><td>'+e(c['next_check'])+'<br><small>'+label(c['validation'])+'</small></td></tr>')
    metrics=''.join(f"<tr><th>{e(r['label'])}</th><td>{e(r['unit'])}</td><td>{e(r['actual']['period'])}</td><td>{num(r['actual']['value'])}</td><td>{num(r['baseline'])}</td><td>{num(r['yoy'])}</td></tr>" for r in report['metrics'] if r['actual']['value'] is not None)
    evidence=''.join('<article id="'+e(x['id'])+'"><b>['+str(evidence_ids[x['id']])+'] '+e(x.get('title') or x['source_id'])+' · '+e('第 '+str(x['page'])+' 页' if x.get('page') else x['block_id'])+'</b><blockquote>'+e(x['quote'])+'</blockquote><small>'+e('原件所述日期 '+(x.get('reported_date') or '未核实')+' · 可得时间 '+x['available_at']+' · 本次获取 '+x.get('observed_at','')+' · '+x.get('publication_note',''))+' · '+('上传作者观点，不能自证' if x['origin']=='uploaded_claim' else '原件证据')+'</small></article>' for x in report['evidence'])
    requirements={r['id']:r['question'] for r in report.get('requirements',[])}
    coverage=''.join('<li>'+e(requirements.get(c['key'],LABELS.get(c['key'],c['key'])))+'：<strong>'+label(c['status'])+'</strong> '+e(c.get('explanation',''))+'</li>' for c in report['coverage'])
    gaps=''.join('<li>'+e(s)+'</li>' for s in report['gaps']+[x['message'] for x in report['issues']])
    figure='<img alt="研究数据图，使用与表格相同的数值" src="data:image/png;base64,'+base64.b64encode(png_chart(report)).decode()+'">' if report['intent']=='earnings' else ''
    reviews=''.join('<article><b>独立复核：'+e('仍有待处理项' if r.get('feedback') else {'pass':'通过','blocked':'资料不足','revise':'需要修订'}.get(r['verdict'],r['verdict']))+'</b><p>'+e(r['summary'])+'</p>'+''.join('<p>'+e(f['message'])+'；'+e(f['requested_change'])+'</p>' for f in r['findings'])+''.join('<p>'+e(f['message'])+'</p>' for f in r.get('feedback',[]))+'</article>' for r in report.get('reviews',[]))
    verification=report['verification']
    return ('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+e(report['title'])+'</title>'
      '<style>body{font:14px system-ui;margin:24px auto;padding:0 20px;max-width:1440px;color:#262626;font-variant-numeric:tabular-nums}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}thead{background:#f2f2f2}th{min-width:90px}blockquote{white-space:pre-wrap;margin:12px 0}small{color:#666}article{border-top:1px solid #ddd;padding:12px;overflow-wrap:anywhere}pre{white-space:pre-wrap}img{max-width:100%;height:auto}a{color:#17639e}.coverage{display:flex;gap:20px;flex-wrap:wrap;list-style:none;padding:12px 0}h1{font-size:24px}h2{font-size:18px}details{margin:16px 0}</style>'
      '<h1>'+e(report['title'])+'</h1><p>'+label(report['status'])+' · 信息截止 '+e(report['as_of'])+' · 来源支持、推理与使用价值尚待人工评审</p>'
      '<p>'+e(report.get('delivery',{}).get('reason','交付状态待确认'))+'</p>'
      '<p>原始结论 '+e(verification.get('original_claims','—'))+' · 当前保留 '+e(verification.get('retained_claims','—'))+' · 删除 '+e(verification.get('removed_claims','—'))+'</p>'
      '<ul class="coverage">'+coverage+'</ul>'+figure+
      ('<table><thead><tr><th>指标</th><th>单位</th><th>期间</th><th>实际</th><th>有效基准</th><th>同比 %</th></tr></thead>'+metrics+'</table>' if metrics and report['intent']=='earnings' else '')+
      '<table><thead><tr><th>原观点与支持程度</th><th>研究判断</th><th>依据与独立来源</th><th>替代解释与反证</th><th>定量检查</th><th>下一步检验</th></tr></thead>'+''.join(rows)+'</table>'
      '<h2>资料缺口与核验问题</h2><ul>'+gaps+'</ul><h2>独立复核</h2>'+reviews+'<h2>来源与原文</h2>'+evidence+
      '<details><summary>检查计算依赖与版本</summary><pre>'+e(canonical(report))+'</pre></details></html>')

def png_chart(report):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    rows=[r for r in report['metrics'] if report['intent']=='earnings' and r['key'] in ('revenue','operating_profit') and r['actual']['value'] is not None]
    fig=Figure(figsize=(10,3.6),dpi=140);FigureCanvasAgg(fig)
    if rows:
        axes=fig.subplots(1,len(rows),squeeze=False)[0]
        for ax,r in zip(axes,rows):
            ax.plot([x['period'] for x in r['series']],[float('nan') if x['value'] is None else x['value'] for x in r['series']],marker='o',color='#17639e')
            ax.set_title(r['key']);ax.set_ylabel(r['unit']);ax.tick_params(axis='x',rotation=40,labelsize=8);ax.grid(alpha=.2)
    else:
        ax=fig.subplots();counts={k:sum(c['verdict']==k for c in report['claims']) for k in ('supported','partial','insufficient','contradicted','interpretation')}
        ax.barh(list(counts),list(counts.values()),color='#337eae');ax.set_xlabel('Claim count (not a quality score)')
    fig.tight_layout();out=io.BytesIO();fig.savefig(out,format='png');return out.getvalue()

def slack_files(report):
    from pitr.integrations.slack import OutputFile
    return [OutputFile(filename='research-report.html',title=report['title'],content=html_report(report)),
        OutputFile(filename='research-chart.png',title='研究数据',data_base64=base64.b64encode(png_chart(report)).decode())]
