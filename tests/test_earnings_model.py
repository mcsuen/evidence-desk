"""Operating-model and object-bound agent checks; synthetic inputs, not efficacy."""
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from test_desk import desk
from pitr.desk.contracts import Metric,TaskInput
from pitr.desk.company_model import *
from pitr.desk.storage import canonical
from pitr.desk.api import create_app
from pitr.desk.tasks import Queue

@pytest.fixture
def model(desk):
 with desk.store.connect(write=True) as db:
  db.execute('DELETE FROM observations')
  for i in range(6):
   period=shift('2024Q1',i)
   for name,value in [('online_marketing',60),('transaction_services',40),('revenue',100),('cost_of_revenue',40),('sales_marketing',30),('general_admin',5),('research_development',5),('operating_profit',20)]:
    m=Metric(id=name+period,name=name,label=name,period=period,value=value,unit='RMB_mn',citation=desk.test_refs[1])
    db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,'PDD',desk.test_doc.id,canonical(m)))
 spec=ModelSpec(snapshot=desk.view('PDD','2025Q2').snapshot,anchor_period='2025Q2')
 result=calculate(desk,spec)
 spec.assumptions=[a.model_copy(update={'period':p,'reason':'Researcher scenario'}) for p in result.forecast_periods for a in result.references]
 return desk,spec

def test_missing_inputs_do_not_become_forecasts_and_annual_ratios_recompute(model):
 d,spec=model
 complete=calculate(d,spec)
 assert next(c.value for c in complete.annual if c.key=='operating_profit' and c.period=='2025FY')==80
 assert next(c.value for c in complete.annual if c.key=='operating_margin' and c.period=='2026FY')==20
 assert not any(c.key=='eps_ads' for c in complete.cells)
 missing=calculate(d,spec.model_copy(update={'assumptions':[]}))
 assert all(c.value is None for c in missing.cells if c.kind=='forecast' and c.key=='operating_profit')
 assert all(c.value is None for c in missing.annual if c.key=='operating_profit')


def test_anchor_excludes_future_actual_and_assumption_identity(model):
 d,spec=model
 with d.store.connect(write=True) as db:
  m=Metric(id='future-revenue',name='online_marketing',label='future',period='2025Q3',value=9999,unit='RMB_mn',citation=d.test_refs[1]);db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,'PDD',d.test_doc.id,canonical(m)))
 spec=spec.model_copy(update={'snapshot':d.view().snapshot})
 result=calculate(d,spec)
 assert next(c.value for c in result.cells if c.key=='online_marketing' and c.period=='2025Q3')==60
 with pytest.raises(ValueError):calculate(d,spec.model_copy(update={'assumptions':spec.assumptions+[spec.assumptions[0]]}))
 with pytest.raises(ValueError):calculate(d,spec.model_copy(update={'assumptions':[spec.assumptions[0].model_copy(update={'period':'2025Q2'})]}))
