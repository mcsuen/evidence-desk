"""Human evaluation records and empirical budgets, kept separate from machine checks."""
import io
import json
import math
from pathlib import Path
import random
import zipfile
from typing import Literal
from pydantic import Field

from pitr.domain.common import Command,canonical,uid,utcnow
from pitr.domain.contracts import Ref,Budget


class HumanEvaluation(Command):
    blind_id: str
    annotator: str = Field(min_length=1)
    edit_effort: Literal['none','light','heavy','unusable']
    major_error: bool
    editing_minutes: float = Field(ge=0)
    comments: str = ''


class BlindPack(Command):
    reports: list[Ref] = Field(min_length=1,max_length=60)


def record(station,request):
    def save(db):
        row=db.execute('SELECT body FROM metadata WHERE key=?',('blind:'+request.blind_id,)).fetchone()
        if not row:raise KeyError('盲评编号不存在，请先生成盲评包')
        value={'id':uid('human_evaluation'),'created_at':utcnow(),'report':json.loads(row[0])['report'],
               **request.model_dump(exclude={'operation_id'}),'origin':'owner_entered_human_label'}
        db.execute('INSERT INTO metadata VALUES(?,?)',('human-evaluation:'+value['id'],canonical(value)))
        return value
    return station.store.once(request.operation_id,{'command':'human_evaluation','request':request},save)


def summary(station):
    with station.store.connect() as db:
        rows=[json.loads(r[0]) for r in db.execute("SELECT body FROM metadata WHERE key LIKE 'human-evaluation:%' ORDER BY rowid")]
    latest={(r['blind_id'],r['annotator']):r for r in rows}
    paired={key for key,_ in latest if len({who for blind,who in latest if blind==key})>=2}
    usable=sum(all(r['edit_effort'] in ('none','light') and not r['major_error'] for (blind,_),r in latest.items() if blind==key) for key in paired)
    return {'status':'recorded' if paired else 'not_evaluated','paired_reports':len(paired),'labels':rows,
            'light_edit_ratio':usable/len(paired) if paired else None,'target':.8,
            'human_validation_complete':False,'note':'自报人工评阅记录。样本与分歧需由评阅者确认；自动测试不代替真人盲评。'}


def blind_pack(station,request):
    from pitr.artifacts.docx import compile_docx
    def save(db):
        refs=list(dict.fromkeys(r.key for r in request.reports));random.SystemRandom().shuffle(refs)
        mapping=[]
        for key in refs:
            identity,revision=key.rsplit('@',1);ref=Ref(id=identity,revision=int(revision));station.store.get(ref,'report',db=db)
            blind_id=uid('sample');item={'blind_id':blind_id,'report':ref.model_dump()}
            db.execute('INSERT INTO metadata VALUES(?,?)',('blind:'+blind_id,canonical(item)));mapping.append(item)
        return mapping
    mapping=station.store.once(request.operation_id,{'command':'blind_pack','request':request},save)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for item in mapping:
            raw,_=compile_docx(station.reports.view(item['report']))
            archive.writestr(item['blind_id']+'.docx',raw)
        archive.writestr('review-template.json',canonical([{'blind_id':i['blind_id'],'annotator':'','edit_effort':'','major_error':None,'editing_minutes':None,'comments':''} for i in mapping]))
        archive.writestr('README.txt','请两名评阅者各自填写评阅表。不要查看后台的宿主、系统版本与 Trace。先记录是否存在重大错误，再记录实际编辑时间和修改程度。')
    return output.getvalue()


def calibrate(station,depth,*,apply=False):
    samples=[]
    for run in station.runs():
        fixed_input=station.store.get(Ref(id=station.get_case(run.case_id).input.id,revision=run.input_revision),'input')
        if run.status!='completed' or not run.report or fixed_input.depth!=depth:continue
        view=station.reports.view(run.report)
        if view.delivery!='ready':continue
        samples.append({'run':run.id,'seconds':run.active_seconds,'calls':run.tool_calls})
    if len(samples)<20:return {'status':'insufficient_samples','samples':len(samples),'required':20,'budget':station.budget(depth).model_dump()}
    def p90(key):return sorted(s[key] for s in samples)[math.ceil(len(samples)*.9)-1]
    budget=Budget(active_seconds=max(60,math.ceil(p90('seconds')*1.5/.9)),tool_calls=max(20,math.ceil(p90('calls')*1.5/.9)),calibration='empirical_p90_20plus')
    result={'status':'calibrated','samples':len(samples),'rule':'ceil(P90 * 1.5 / 0.9); 10% wrap-up reserve','budget':budget.model_dump(),'runs':samples}
    if apply:
        with station.store.connect(write=True) as db:
            row=db.execute("SELECT body FROM metadata WHERE key='budgets'").fetchone();values=json.loads(row[0]) if row else {}
            values[depth]=budget.model_dump();db.execute("INSERT OR REPLACE INTO metadata VALUES('budgets',?)",(canonical(values),))
            station.store.event(db,'','budget.calibrated',result)
    return result
