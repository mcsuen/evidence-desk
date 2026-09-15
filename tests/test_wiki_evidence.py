"""Research evidence must survive rendering, arithmetic and version publication."""
import copy
from pathlib import Path
import pytest
from pitr.desk.service import Desk
from pitr.desk.contracts import Metric,Citation
from pitr.desk.sources import parse_document,extract_pdd_metrics
from pitr.desk.storage import canonical
from pitr.wiki.contracts import RevisionDraft,ProposalInput,Reference,DecisionRecord
from pitr.wiki.evidence import number_catalog,bind_numbers,source_excerpt,citation_anchor
from pitr.wiki.validation import validate_numbers,display_number
from pitr.wiki.store import state


def statement(tmp_path):
    desk=Desk(tmp_path/'desk')
    raw=b'''PDD HOLDINGS INC.

CONDENSED CONSOLIDATED STATEMENTS OF INCOME

(Amounts in millions of RMB and US$)

Revenues 200 300 40

Operating profit 20 40 6

Interest and investment income/(loss), net 5 (2) (1)

Foreign exchange loss (1) (1) (1)

Other income/(loss), net 2 (3) (1)

Share of results of equity investees 1 (1) (1)

Income tax expenses (7) (8) (1)

Net income 20 25 3
'''
    doc=parse_document(raw,'text/plain','https://example.com/synthetic-statement','PDD','2026Q2 software fixture')
    (desk.files/doc.file_name).write_bytes(raw);desk.put_document(doc)
    with desk.store.connect() as db:
        sources=list(state(db,'sources').values())
        metrics=[m.model_dump() for m in extract_pdd_metrics(doc)]
    return desk,doc,metrics,sources


def test_bridge_preserves_signs_and_source_precision(tmp_path):
    desk,doc,metrics,sources=statement(tmp_path)
    by_name={m['name']:m for m in metrics}
    assert by_name['investment_income']['value']==-2
    assert by_name['income_tax']['value']==8
    catalog=number_catalog(metrics,sources)
    bridge=next(v for v in catalog.values() if v['label']=='经营利润至净利润桥接合计')
    residual=next(v for v in catalog.values() if v['label']=='净利润桥接与原表残差')
    ratio=next(v for v in catalog.values() if v['label']=='经营利润率')
    assert bridge['display']=='25' and residual['display']=='0' and ratio['display']=='13.33'
    assert len(bridge['binding']['operands'])==6
    assert display_number(1.005,2)==display_number(1.01,2)


def test_rendered_numbers_are_auditable_and_frozen_at_publication(tmp_path):
    desk,doc,metrics,sources=statement(tmp_path)
    catalog=number_catalog(metrics,sources)
    amount=next(v for v in catalog.values() if v['label']=='收入')
    margin=next(v for v in catalog.values() if v['label']=='经营利润率')
    original=RevisionDraft(id='company:PDD',kind='page',page_type='company',title='带证据的公司研究',
        content='|指标|本季|\n|---|---|\n|收入，人民币百万元|'+amount['token']+'|\n|经营利润率|'+margin['token']+'%|',
        summary='以实际报表验证经营表现。',reason='补充实质指标对比').model_dump()
    rendered=bind_numbers(original,catalog)
    assert '{{n:' in original['content'] and '{{n:' not in rendered['content']
    assert ']('+ '#' +citation_anchor(amount['citations'][0])+')' in rendered['content']
    assert len(rendered['citations'])==2
    with desk.store.connect() as db:assert validate_numbers(db,rendered,state(db,'sources'))==2
    bad=copy.deepcopy(rendered)
    number=bad['numeric_assertions'][1]
    bad['content']=bad['content'][:number['start']]+'13.34'+bad['content'][number['end']:]
    with desk.store.connect() as db:
        with pytest.raises(ValueError,match='计算结果'):
            validate_numbers(db,bad,state(db,'sources'))
    policy=desk.wiki.policy()
    proposal=desk.wiki.propose(ProposalInput(operation_id='numeric-draft',company='PDD',policy=Reference(id=policy['id'],version=policy['version']),
        changes=[RevisionDraft.model_validate(rendered)],reason='完整指标证据'))
    desk.wiki.review(proposal['id'],DecisionRecord(operation_id='numeric-review',digest=proposal['digest'],action='adopt',reason='测试夹具审核'))
    with desk.store.connect(write=True) as db:db.execute('DELETE FROM observations')
    desk.wiki.rebuild()
    assert desk.wiki.validate_use('PDD',[{'id':'company:PDD','version':1}])['valid']
    assert any('13.33' in p.read_text() for p in (desk.wiki.markdown/'pages').glob('*.md'))
    assert any('id="'+citation_anchor(amount['citations'][0])+'"' in p.read_text() for p in (desk.wiki.markdown/'pages').glob('*.md'))


def test_unknown_number_and_invented_precision_fail(tmp_path):
    desk,doc,metrics,sources=statement(tmp_path)
    with pytest.raises(ValueError,match='未提供'):
        bind_numbers({'content':'收入 {{n:invented}}','citations':[]},number_catalog(metrics,sources))
    for precision in (-1,7,True,2.5):
        with pytest.raises(ValueError):display_number(1,precision)


def test_business_mechanics_are_not_displaced_by_repeated_risk_mentions():
    source={'id':'annual','blocks':[{'id':str(i),'text':'Temu Pinduoduo competitive business model risk. '*6} for i in range(100)]}
    source['blocks'] += [{'id':'mechanism','text':'We charge merchants based on impressions or clicks for online marketing services.'}]
    before=copy.deepcopy(source)
    excerpt=source_excerpt(source,limit=4000)
    assert not excerpt['context_complete'] and excerpt['omitted_blocks']>0
    assert any(b['id']=='mechanism' for b in excerpt['blocks'])
    assert source==before
