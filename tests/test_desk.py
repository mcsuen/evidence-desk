"""Shared financial calculations, source identity and point-in-time boundaries."""
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from pitr.desk.service import Desk
from pitr.desk.storage import canonical,Conflict
from pitr.desk.contracts import *
from pitr.desk.sources import parse_document,publication
from pitr.desk.financials import build_rows,quarterize
from pitr.wiki.validation import validate_numbers
from pitr.desk.api import create_app

@pytest.fixture
def desk(tmp_path):
 d=Desk(tmp_path/'desk')
 raw=b'Management expects investment to remain elevated.\n\nRevenue 100. Operating profit 20.'
 doc=parse_document(raw,'text/plain','https://investor.pddholdings.com/test','PDD','2025Q2 Original',observed_at='2025-08-01T12:00:00+00:00')
 (d.files/doc.file_name).write_bytes(raw);d.put_document(doc)
 refs=[Citation(source_id=doc.id,block_id=b.id,quote=b.text) for b in doc.blocks]
 with d.store.connect(write=True) as db:
  for period,rv,op in [('2024Q2',80,24),('2025Q2',100,20)]:
   for name,value in [('revenue',rv),('operating_profit',op),('cost_of_revenue',40),('sales_marketing',30),('general_admin',5),('research_development',5)]:
    m=Metric(id=name+period,name=name,label=name,period=period,value=value,unit='RMB_mn',citation=refs[1])
    db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,'PDD',doc.id,canonical(m)))
 d.test_doc=doc;d.test_refs=refs
 return d


ANALYST=['before_release','after_release','day_precision','quarter_not_release','missing_forecast','negative_direction','basis_mismatch','multi_number','ads_unit','quarter_cumulative','restatement']
@pytest.mark.parametrize('case',ANALYST)
def test_analyst(case,desk):
 view=desk.view('PDD','2025Q2','2025-08-02T00:00:00+00:00');rows={r.key:r for r in view.rows}
 if case=='before_release':assert not desk.view('PDD','2025Q2','2025-08-01T11:59:00+00:00').documents
 elif case=='after_release':assert rows['revenue'].actual.value==100
 elif case=='day_precision':assert publication('August 1, 2025\nquarter ended June 30, 2025','2026-01-01T00:00:00+00:00')[0].startswith('2025-08-02T03:59:59')
 elif case=='quarter_not_release':assert publication('quarter ended June 30, 2025','2026-01-01T00:00:00+00:00')[1]=='observed'
 elif case=='missing_forecast':assert all(r.baseline is None and r.difference is None for r in view.rows)
 elif case=='negative_direction':assert rows['operating_margin'].yoy_bps==pytest.approx(-1000)
 elif case=='basis_mismatch':
  exp=[{'metric':'revenue','period':'2025Q2','unit':'USD','basis':'GAAP','value':90}]
  _,_,docs,metrics=desk.snapshot('PDD','2025-08-02T00:00:00+00:00');r=build_rows(metrics,{d.id:d.available_at for d in docs},'2025Q2',exp,set(),'user_forecast')[0]
  assert r.baseline is None and r.issues
 elif case=='multi_number':
  body={'content':'100 and 999','numeric_assertions':[{'field':'content','start':0,'end':3,'observation_id':'revenue2025Q2','name':'revenue','value':100,'unit':'RMB_mn','period':'2025Q2'}]}
  with desk.store.connect() as db:snap=desk._snapshot(db,view.snapshot)
  with desk.store.connect() as db:
   with pytest.raises(ValueError):validate_numbers(db,body,{})
 elif case=='ads_unit':assert rows['eps_ads'].unit=='RMB_per_ADS' and rows['eps_ads'].actual.value is None
 elif case=='quarter_cumulative':
  a={'id':'q2','metric':'cf','unit':'RMB','basis':'GAAP','currency':'RMB','fiscal_year':2025,'quarter':2,'nature':'flow','value':100,'available_at':'2025-08-01'};b={**a,'id':'q1','quarter':1,'value':40,'available_at':'2025-05-01'}
  assert quarterize(a,b)['value']==60
  with pytest.raises(ValueError):quarterize(a,{**b,'currency':'USD'})
 elif case=='restatement':
  _,_,docs,metrics=desk.snapshot('PDD','2025-08-02T00:00:00+00:00');m=next(m for m in metrics if m.name=='revenue' and m.period=='2025Q2');metrics.append(m.model_copy(update={'id':'revision','value':999}))
  assert next(r for r in build_rows(metrics,{d.id:d.available_at for d in docs},'2025Q2',[],set(),'user_forecast') if r.key=='revenue').actual.value is None
