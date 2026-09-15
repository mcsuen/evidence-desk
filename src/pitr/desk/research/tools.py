"""Deterministic, leased tool plane. Only the controller imports Desk or opens SQLite."""
from __future__ import annotations
import json, re, math, time, threading
from .contracts import CalculationRef
from .service import Research
from ..contracts import Metric, utcnow
from ..storage import canonical, digest, Conflict
from ..service import stamp
from ..financials import build_rows, margin_bridge
from .workspace import ResearchWorkspace, source_role


class ToolPlane(ResearchWorkspace):
    def __init__(self,desk,task,owner,checkpoint):
        self.desk=desk;self.task=task;self.owner=owner;self.checkpoint=checkpoint;self.lock=threading.RLock();self.execution_lock=threading.RLock()
        self.request=Research(desk).get(task['id'])
        self.input=self.request['input'];self.state=task['research'];self.frozen=None
        from .trace.store import SafeTrace
        self.trace=SafeTrace(desk,task['id']);self.trace_parent='preparation:'+str(task.get('attempts',1));self.trace_attempt=None;self.last_trace_call=None;self.trace_current_call=None
        with desk.store.connect() as db:
            row=db.execute('SELECT body FROM research_inputs WHERE request_id=? ORDER BY version DESC LIMIT 1',(self.request['id'],)).fetchone()
        if row:self.frozen=json.loads(row['body'])

    def charge(self):
        if hasattr(self,'clock_started'):
            self.state['active_seconds']=self.clock_base+time.monotonic()-self.clock_started

    def fence(self,db=None):
        self.charge()
        if db is None:
            with self.desk.store.connect() as conn:return self.fence(conn)
        row=db.execute('SELECT status,owner,lease_until FROM tasks WHERE id=?',(self.task['id'],)).fetchone()
        if not row or row['status']!='running' or row['owner']!=self.owner or (row['lease_until'] or 0)<time.time():
            raise Conflict('研究执行权已撤销')
        if self.input.get('budget_seconds') is not None and self.state['active_seconds']>=self.input['budget_seconds']:raise TimeoutError('累计活跃执行预算耗尽')

    def receipts(self,kind=None):
        with self.desk.store.connect() as db:
            return {r['id']:json.loads(r['body']) for r in db.execute('SELECT * FROM research_receipts WHERE task_id=?',(self.task['id'],)) if kind is None or r['kind']==kind}

    def receipt(self,kind,body):
        rid=kind+'_'+digest(body)[:24];body={'id':rid,**body}
        with self.desk.store.connect(write=True) as db:
            self.fence(db);db.execute('INSERT OR IGNORE INTO research_receipts VALUES(?,?,?,?)',(self.task['id'],rid,kind,canonical(body)))
        if kind!='tool' and self.trace_current_call:
            producers=self.trace.meta('producers',{}) or {};producers[rid]=self.trace_current_call;self.trace.set_meta('producers',producers)
            self.trace.emit('artifact.produced',span_id=self.trace_current_call,data={'id':rid,'kind':kind,'source_id':body.get('source_id'),'page':body.get('page')})
        return body

    def call(self,name,args):
        with self.execution_lock:
            self.last_trace_call=None
            try:return self._invoke(name,args,lambda: self._dispatch(name,args))
            except Exception as error:
                if self.last_trace_call is None:
                    sid='rejected:'+str(time.time_ns())
                    self.trace.span(sid,name=name+' · 未执行',kind='rejected_tool',executor='controller',parent_id=self.trace_parent,attempt=self.trace_attempt,
                        status='failed',ended_at=utcnow(),input_ref=self.trace.content(args),error_ref=self.trace.content({'message':str(error),'executed':False}))
                    self.last_trace_call={'task_id':self.task['id'],'span_id':sid,'call_id':None}
                raise

    def _dispatch(self,name,args):
        if name not in CAPABILITIES:raise ValueError('未登记能力')
        return getattr(self,name)(**args)

    def _invoke(self,name,args,operation):
        # Reserve a durable call before work starts. Do not hold this mutex over
        # network I/O: the controller must still enforce cancellation/deadlines.
        with self.lock:
            if getattr(self,'update_pending',False):
                from .intake import UserUpdate
                raise UserUpdate('正在纳入新的研究要求')
            self.fence()
            if self.input.get('tool_budget') is not None and self.state['tool_calls']>=self.input['tool_budget']:raise ValueError('领域工具调用预算耗尽；请用已保存证据交付缺口')
            self.state['tool_calls']+=1
            ordinal=self.state['tool_calls']
            self.checkpoint({'research':self.state,'stage':name})
        span_id=f'tool:{ordinal}';self.trace_current_call=span_id;started=time.monotonic();started_at=utcnow()
        self.last_trace_call={'task_id':self.task['id'],'span_id':span_id,'call_id':self.task['id']+':'+str(ordinal)}
        self.trace.span(span_id,name=name,kind='tool',executor='deterministic',parent_id=self.trace_parent,
            started_at=started_at,timing='measured',ordinal=ordinal,attempt=self.trace_attempt,call_id=self.last_trace_call['call_id'],
            input_version=self.state['input_version'],input_ref=self.trace.content(args),metadata={'repair_round':self.state.get('repairs',0),'role':getattr(self,'role','researcher')})
        if ordinal>1:self.trace.link(f'tool:{ordinal-1}',span_id,label='控制服务执行顺序')
        try:
            result=operation()
            self.fence()
            self.receipt('tool',{'name':name,'arguments':args,'result':{k:v for k,v in result.items() if k!='_mcp_images'} if isinstance(result,dict) else result,'ordinal':ordinal,
                'input_version':self.state['input_version'],'at':utcnow(),'call_id':self.last_trace_call['call_id'],
                'role':getattr(self,'role','researcher'),'started_at':started_at,'duration_ms':(time.monotonic()-started)*1000})
            refs=[]
            for event in self.trace.all_events() or []:
                if event['span_id']==span_id and event['kind']=='artifact.produced':refs.append(event['data'])
            self.trace.span(span_id,status='completed',ended_at=utcnow(),duration_ms=(time.monotonic()-started)*1000,
                output_ref=self.trace.content({k:v for k,v in result.items() if k!='_mcp_images'} if isinstance(result,dict) else result),artifact_refs=refs)
            # Dependencies are explicit receipt IDs, not the temporal order of tool calls.
            producers=self.trace.meta('producers',{}) or {}
            def dependencies(v):
                if isinstance(v,dict):
                    for key,child in v.items():
                        if key in ('dependencies','evidence','calculations','evidence_ids','calculation_ids') and isinstance(child,list):
                            for dep in child:
                                if isinstance(dep,str) and dep in producers:self.trace.link(producers[dep],span_id,'dependency',dep)
                        elif isinstance(child,(dict,list)):dependencies(child)
                elif isinstance(v,list):
                    for child in v:dependencies(child)
                elif isinstance(v,str) and v in producers:self.trace.link(producers[v],span_id,'dependency',v)
            # Tool arguments contain exact receipt IDs; those are explicit data references.
            def walk(v):
                if isinstance(v,dict):
                    for child in v.values():walk(child)
                elif isinstance(v,list):
                    for child in v:walk(child)
                elif isinstance(v,str) and v in producers and producers[v]!=span_id:self.trace.link(producers[v],span_id,'dependency',v)
            walk(args)
            if isinstance(result,dict) and result.get('id'):
                producers[result['id']]=span_id;self.trace.set_meta('producers',producers)
            return result
        except Exception as e:
            self.trace.span(span_id,status='interrupted' if isinstance(e,(Conflict,TimeoutError)) else 'failed',ended_at=utcnow(),
                duration_ms=(time.monotonic()-started)*1000,error_ref=self.trace.content({'message':str(e),'type':type(e).__name__}))
            try:self.receipt('tool',{'name':name,'arguments':args,'error':str(e),'ordinal':ordinal,'at':utcnow()})
            except (Conflict,TimeoutError):pass
            raise
        finally:self.trace_current_call=None

    def prepare(self):
        if self.frozen:return self.frozen
        from .subjects import prepare
        return prepare(self)

    def _freeze(self,snap,issues):
        self.fence()
        sid='snapshot_'+digest(snap)[:32]
        docs=[self.desk.document(s) for s in snap['sources']]
        official={d.id for d in docs if source_role(d)=='official'}
        metrics=[Metric.model_validate(m) for m in snap['observations'] if m['citation']['source_id'] in official and self.input['company']!='INDUSTRY']
        if self.input['company']!='INDUSTRY' and len(metrics)!=len(snap['observations']):issues.append('上传材料中的数字未作为已核实财务观察；仅作为待审查的作者内容')
        periods=sorted({m.period for m in metrics if re.fullmatch(r'20\d{2}Q[1-4]',m.period)})
        period=self.input['period'] or (periods[-1] if periods else '')
        expectations=[]
        event_time=min((d.available_at for d in docs if period and period in d.title),default=snap['as_of'])
        with self.desk.store.connect() as db:
            for row in db.execute("SELECT body FROM imports WHERE kind='expectation' AND company=?",(self.input['company'],)):
                item=json.loads(row['body'])
                if row and item.get('kind')=='user_forecast' and stamp(item['effective_at'])<stamp(event_time) and item['id'] in snap['imports']:
                    expectations.extend(item['rows'])
        rows=build_rows(metrics,{d.id:d.available_at for d in docs},period,expectations,[],'user_forecast') if period else []
        if not expectations and self.input['intent']=='earnings':issues.append('缺少事件前冻结的用户预测；不计算虚假的预期差')
        if not any(not d.url.startswith('upload:') for d in docs):issues.append('没有可确认的官方披露；上传观点不能自证')
        for d in docs:
            issues.extend(d.issues)
            if d.media_type=='application/pdf' and not d.blocks:issues.append('PDF 无文本层，需要视觉读取：'+d.title)
        version=self.state['input_version']+1
        wiki=self.frozen['wiki'] if self.frozen else self.desk.wiki.list(self.input['company'],snap['as_of'],include_blocked=False)
        frozen={'version':version,'snapshot':sid,'as_of':snap['as_of'],'period':period,'company':self.input['company'],
          'sources':snap['sources'],'objects':snap['objects'],'wiki':wiki,'rows':[r.model_dump() for r in rows],
          'bridge':margin_bridge(rows) if rows else [],'issues':list(dict.fromkeys(issues)),'model_draft_id':self.input['model_draft_id']}
        from .subjects import contexts
        frozen['subject_contexts']=contexts(self,snap)
        if self.input['model_draft_id']:
            from ..company_model import get_draft
            draft=self.frozen.get('model_draft') if self.frozen else get_draft(self.desk,self.input['model_draft_id'])
            if draft['spec']['snapshot']!=self.input['snapshot']:raise Conflict('模型草稿不属于原请求的基准快照')
            frozen['model_draft']=draft
        with self.desk.store.connect(write=True) as db:
            self.fence(db)
            db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)',(sid,self.input['company'],canonical(snap)))
            db.execute('INSERT INTO research_inputs VALUES(?,?,?)',(self.request['id'],version,canonical(frozen)))
        self.state['input_version']=version;self.task['request']['snapshot']=sid;self.frozen=frozen
        self.trace.emit('input.frozen',span_id=self.trace_parent,occurred_at=utcnow(),data={'input_version':version,'snapshot':sid},content=frozen)
        self.checkpoint({'research':self.state,'stage':'prepared'})
        self.bootstrap_requirements()
        return frozen

    def context(self):
        f=self.prepare()
        self.bootstrap_requirements()
        with self.desk.store.connect() as db:
            snap=self.desk._snapshot(db,f['snapshot'])
        return {'request':{k:v for k,v in self.input.items() if k!='context'},'answers':self.request['answers'],
            'snapshot':f['snapshot'],'as_of':f['as_of'],'period':f['period'], 'requirements':self.requirements(),
            'subjects':[{k:v for k,v in subject.items() if k!='rows'} for subject in f.get('subject_contexts',[])],'research_scope':self.input.get('scope',{}),
            'sources':self.source_index(), 'issues':f['issues'],
            'metrics':sorted({m['name'] for m in snap['observations']}),
            'instructions':'按 source_index/read_page/read_table 阅读原件；ledger 按需获取既有证据和计算；search_wiki 检索相关研究。先登记新增要求，持续保存 checkpoint。',
            'usage':{'active_seconds':self.state['active_seconds'],'tool_calls':self.state['tool_calls'],'limits':{'seconds':self.input.get('budget_seconds'),'tools':self.input.get('tool_budget')}},
            'checkpoint':self.receipts('checkpoint').get(self.state.get('checkpoint_id')),
            'role':getattr(self,'role','researcher')}

    def discover_sources(self,company=''):
        from ..sources import pdd_catalog
        company=company.upper() or self.input['company']
        from .subjects import require_company
        from .semantics import companies
        company=require_company(self,company if company!='INDUSTRY' else '')
        record=companies(self.desk).get(company,{})
        if company!='PDD':
            return {'company_id':company,'links':[{'url':u,'title':record['name']+' 官方资料目录'} for u in record.get('catalog_urls',[])], 'issues':[] if record.get('catalog_urls') else ['继续用 search_public 查找 '+record.get('name',company)+' 的原始披露，并实际读取确认期间']}
        return {'company_id':company,'links':pdd_catalog(),'issues':[]}
    def _fetch(self,url,title='',company=''):
        from .subjects import source_company
        from pitr.wiki.discovery import fetch_public
        cid=source_company(self,url,company)
        settings=self.desk.root/'private/settings.json'
        contact=json.loads(settings.read_text()).get('sec_user_agent','') if settings.exists() else ''
        raw,media,final,_=fetch_public(url,timeout=45,contact=contact)
        cid=source_company(self,final,cid if cid!='INDUSTRY' else '')
        self.fence()
        return self.desk.ingest(raw,media,final,cid,title)

    def search_sources(self,query,source_id='',role='',period='',page=None,offset=0,limit=18):
        self.prepare()
        from pitr.wiki.search import tokens
        words=list(dict.fromkeys(tokens(query).split()))
        if not words:raise ValueError('需要关键词')
        if offset<0 or not 1<=limit<=60:raise ValueError('分页范围不合法')
        if source_id and source_id not in self.frozen['sources']:raise ValueError('来源不在输入中')
        # Explicit source filters are authoritative; query terms are ranked, never first-hit truncated.
        if not role and re.search(r'官方|\bofficial\b',query,re.I):role='official'
        candidates=[]
        for sid in self.frozen['sources']:
            d=self.desk.document(sid)
            if source_id and sid!=source_id:continue
            if role and source_role(d)!=role:continue
            if period and period.lower() not in (d.title+' '+' '.join(b.text for b in d.blocks[:8])).lower():continue
            for index,block in enumerate(d.blocks):
                if page is not None and block.page!=page:continue
                text=block.text.lower();matches=sum(1 for w in words if w in text)
                if not matches:continue
                score=matches/(1+len(text)/600)+ (4 if query.lower() in text else 0)
                candidates.append((score,sid,index,block))
        candidates.sort(key=lambda x:(-x[0],x[1],x[2]))
        chosen=candidates[offset:offset+limit]
        result=[self._evidence(sid,b,0,len(b.text)) for _,sid,_,b in chosen]
        for sid in {x[1] for x in chosen}:self._record_reading(sid,[x[3] for x in chosen if x[1]==sid],'excerpt')
        return result

    def _evidence(self,sid,block,start,end):
        d=self.desk.document(sid)
        if not 0<=start<end<=len(block.text):raise ValueError('引文范围不合法')
        return self.receipt('evidence',{'source_id':sid,'source_version':d.digest,'block_id':block.id,'start':start,'end':end,
          'quote':block.text[start:end],'page':block.page,'available_at':d.available_at,'origin':'uploaded_claim' if d.url.startswith('upload:') else d.origin_group,
          'title':d.title,'url':d.url,'source_role':source_role(d),'origin_group':d.origin_group,'published_at':d.published_at,
          'observed_at':d.observed_at,**self.source_dates(d),
          'original_url':self.state.get('source_origins',{}).get(sid,''),'bbox':block.bbox or [],
          'company_id':d.company if (d.company not in ('UNASSIGNED','INDUSTRY')) else ''})

    def read_source(self,source_id,offset=0,limit=24):
        self.prepare()
        if source_id not in self.frozen['sources'] or offset<0 or not 1<=limit<=60:raise ValueError('来源或读取范围不属于当前输入')
        d=self.desk.document(source_id)
        self._record_reading(source_id,d.blocks[offset:offset+limit])
        return {'title':d.title,'url':d.url,'source_version':d.digest,'total_blocks':len(d.blocks),'issues':d.issues,
            'blocks':[self._evidence(source_id,b,0,len(b.text)) for b in d.blocks[offset:offset+limit]]}

    def quote_source(self,source_id,block_id,start=0,end=None):
        self.prepare()
        if source_id not in self.frozen['sources']:raise ValueError('来源不在快照内')
        b=next((b for b in self.desk.document(source_id).blocks if b.id==block_id),None)
        if b is None:raise ValueError('原文块不存在')
        return self._evidence(source_id,b,start,len(b.text) if end is None else end)

    def financial_observations(self,metric='',period='',company=''):
        self.prepare()
        snapshot=self.frozen['snapshot']
        from .subjects import require_company
        company=require_company(self,company)
        snapshot=next(s['snapshot'] for s in self.frozen['subject_contexts'] if s['company_id']==company)
        with self.desk.store.connect() as db:snap=self.desk._snapshot(db,snapshot)
        result=[]
        for m in snap['observations']:
            if metric and m['name']!=metric:continue
            if period and m['period']!=period:continue
            if source_role(self.desk.document(m['citation']['source_id']))!='official':continue
            c=m['citation'];e=self.quote_source(c['source_id'],c['block_id'])
            result.append(self._calc(m['name'],m['value'],m['unit'],m['period'],'observation',[m['id'],e['id']],basis=m['basis'],frequency=m['frequency'],source_roles=['company_actual'],verification_status='issuer_disclosed'))
        if metric and not result:raise ValueError('当前范围没有此指标，使用 context 的 metrics 核对可用名称；非 GAAP 或券商数据可从原文 register_numbers 绑定')
        return result


    def financial_comparison(self,metric,company=''):
        self.prepare()
        rows=self.frozen['rows']
        from .subjects import require_company
        company=require_company(self,company)
        if len(self.frozen['subject_contexts'])!=1 or not rows:rows=next(s['rows'] for s in self.frozen['subject_contexts'] if s['company_id']==company)
        row=next((r for r in rows if r['key']==metric),None)
        if not row:raise ValueError('指标不在已核对表中')
        refs={}
        for key in ('actual','prior'):
            point=row.get(key)
            if not point:continue
            evidence=[self.quote_source(c['source_id'],c['block_id'])['id'] for c in point['citations']]
            refs[key]=self._calc(metric,point['value'],row['unit'],point['period'],point['calculation'],point['observation_ids']+evidence,basis=row['basis'],frequency='quarter',limitations=point['issues'])
        if row['baseline'] is not None:
            refs['baseline']=self._calc(metric,row['baseline'],row['unit'],row['actual']['period'],'frozen user_forecast',[],basis=row['basis'],assumption=True)
        for key,unit in [('difference',row['unit']),('yoy','percent'),('yoy_bps','basis_points')]:
            if row[key] is not None:
                refs[key]=self._calc(metric+'_'+key,row[key],unit,row['actual']['period'],key,[r['id'] for r in refs.values()],basis=row['basis'],direction='increase' if row[key]>0 else 'decrease' if row[key]<0 else 'unchanged')
        return {'row':row,'references':refs}

    def _calc(self,metric,value,unit,period,formula,dependencies,**extra):
        if value is not None and not math.isfinite(value):raise ValueError('计算不是有限数值')
        from .subjects import calc_identity
        extra=calc_identity(self,dependencies,extra)
        base=CalculationRef(id='',metric=metric,value=value,unit=unit,period=period,formula=formula,dependencies=dependencies,
          currency=unit.split('_')[0] if unit.split('_')[0] in ('RMB','USD','HKD','EUR','GBP') else '',share_basis='ADS' if 'ADS' in unit else '',**extra).model_dump();base.pop('id')
        return self.receipt('calculation',base)

    def calculate(self,operation,left,right=None,delta_pp=None):
        refs=self.receipts('calculation');a=refs.get(left);b=refs.get(right)
        from .subjects import guard_calculation
        guard_calculation(self,operation,a,b)
        if operation in ('add','multiply','divide','compare','sum_difference'):
            from .arithmetic import calculate
            return calculate(self,operation,a,b)
        if not a or a['value'] is None:raise ValueError('左输入缺失或不是计算引用')
        if operation=='fee_shock':
            if a['metric']!='revenue' or a['unit'] not in ('RMB_mn','USD_mn') or delta_pp is None or not math.isfinite(delta_pp) or abs(delta_pp)>100:raise ValueError('机械情景需要收入金额及有限百分点假设')
            delta=self._calc('fee_change',delta_pp,'percentage_points',a['period'],'explicit scenario assumption',[],assumption=True)
            return self._calc('operating_profit_impact',-a['value']*delta_pp/100,a['unit'],a['period'],'-revenue * fee_change_pp / 100',[left,delta['id']],basis=a['basis'],
                assumption=True,limitations=[f'用户/研究情景费率变动 {delta_pp} 个百分点；仅为机械经营利润影响，不是完整盈利预测'])
        if not b or b['value'] is None:raise ValueError('右输入缺失')
        first_quarter_base=(operation=='quarterize' and a['frequency']=='ytd' and b['frequency']=='quarter' and b['period'].endswith('Q1') and self.input['company']=='PDD')
        keys=('unit','currency','basis','share_basis') if first_quarter_base else ('unit','currency','basis','share_basis','frequency')
        if any(a[k]!=b[k] for k in keys):raise ValueError('期间频率、单位、币种、GAAP 或股/ADS 口径不一致')
        if operation in ('change','growth','quarterize') and a['metric']!=b['metric']:raise ValueError('跨期变化需要相同指标')
        if operation in ('change','growth') and (a['frequency']=='ytd' or a['period']<=b['period']):raise ValueError('跨期顺序不合法或累计期间不可直接比较')
        if operation=='subtract' and a['period']!=b['period']:raise ValueError('同期间差额不能混用其他季度；跨期变化请使用 change')
        if operation=='quarterize':
            ma=re.fullmatch(r'(20\d{2})(?:Q|YTD)([1-4])',a['period']);mb=re.fullmatch(r'(20\d{2})(?:Q|YTD)([1-4])',b['period'])
            if a['frequency']!='ytd' or not ma or not mb or ma[1]!=mb[1] or int(ma[2])!=int(mb[2])+1:raise ValueError('累计转季度要求同财年相邻累计流量')
            if any(x in a['unit'] for x in ('ADS','share','percent')) or a['metric'] in ('cash','short_investments','restricted_cash'):raise ValueError('存量、比例及每股值不能相减')
        if operation=='ratio':
            if a['period']!=b['period'] or b['value']==0:raise ValueError('比例要求同期间且分母非零')
            value=a['value']/b['value']*100;unit='percent'
        elif operation=='growth':
            if b['value']==0:raise ValueError('零基期不能计算增长率')
            value=(a['value']-b['value'])/abs(b['value'])*100;unit='percent'
        elif operation in ('change','subtract','quarterize'):
            value=a['value']-b['value'];unit='percentage_points' if a['unit']=='percent' else a['unit']
        else:raise ValueError('未登记计算方法')
        output_period=ma[1]+'Q'+ma[2] if operation=='quarterize' else a['period']
        return self._calc(a['metric']+'_'+operation,value,unit,output_period,operation,[left,right],basis=a['basis'],
            frequency='quarter' if operation=='quarterize' else a['frequency'],
            source_roles=sorted(set(a.get('source_roles',[])+b.get('source_roles',[]))),
            verification_status='quoted_not_independently_verified' if any(x.get('verification_status')=='quoted_not_independently_verified' for x in (a,b)) else 'source_bound',
            limitations=list(dict.fromkeys(a.get('limitations',[])+b.get('limitations',[]))),direction=('increase' if value>0 else 'decrease' if value<0 else 'unchanged') if operation in ('change','growth') else None)

    def mechanical_scenario(self,revenue,unit,delta_pp,period):
        if not re.fullmatch(r'20\d{2}Q[1-4]',period):raise ValueError('情景期间应为 YYYYQn')
        if not math.isfinite(revenue) or revenue<0 or unit not in ('RMB_mn','USD_mn'):raise ValueError('收入假设应为非负金额并标明币种单位')
        a=self._calc('revenue',revenue,unit,period,'explicit scenario assumption',[],assumption=True,limitations=['这是显式情景输入，不是公司已披露实际值'])
        return self.calculate('fee_shock',a['id'],delta_pp=delta_pp)

    def operating_model(self,assumptions=None):
        self.prepare()
        if self.input['company']!='PDD':raise ValueError('完整经营利润模型仅支持 PDD')
        from ..company_model import calculate,ModelSpec
        base=self.frozen.get('model_draft',{}).get('spec',{}).get('assumptions',[])
        result=calculate(self.desk,ModelSpec(snapshot=self.frozen['snapshot'],anchor_period=self.frozen['period'],assumptions=base if assumptions is None else assumptions)).model_dump()
        receipt=self.receipt('model',{'result':result,'input_version':self.state['input_version'],'assumptions':base if assumptions is None else assumptions})
        refs=[self._calc(c['key'],c['value'],'RMB_mn',c['period'],'pdd-operating.1',[receipt['id']]+c.get('dependencies',[]),basis='GAAP',assumption=True,limitations=result['issues']) for c in result['annual'] if c['key']=='operating_profit']
        return {**receipt,'calculations':refs}

    def search_public(self,query):
        if not self.input.get('scope',{}).get('allow_public_search',True):raise ValueError('用户限定只使用所给资料，本轮不执行外部搜索。缺失依据请明确保留。')
        from .web_sources import search_public
        return search_public(self,query)

    def fetch_public_source(self,url,company=''):
        from .web_sources import fetch_public_source
        self.prepare()
        return fetch_public_source(self,url,company)

    def clarify(self,question):
        if not question.strip():raise ValueError('需要具体澄清问题')
        self.state['questions']=[question];self.checkpoint({'research':self.state,'stage':'clarification_requested'})
        return {'saved':True,'instruction':'请结束本轮。执行槽位将释放，回答后续接同一会话。'}

CAPABILITIES={
 'context':('读取当前请求、要求、原件目录、相关指标索引与已保存进展；按需读取原件和账本',{}),
 'discover_sources':('仅在登记官网与 SEC 目录发现官方资料；行业请求可指定登记公司，未确认时返回缺口',{'company':'string?'}),
 'search_sources':('按相关性检索原文；role 可为 official/uploaded_claim/third_party；使用分页避免漏读',{'query':'string','source_id':'string?','role':'string?','period':'string?','page':'integer?','offset':'integer?','limit':'integer?'}),
 'read_source':('分页阅读原件，返回系统生成的引文（offset 默认零，limit 默认二十四）',{'source_id':'string','offset':'integer?','limit':'integer?'}),
 'quote_source':('将原文块中的精确范围绑定为不可变证据',{'source_id':'string','block_id':'string','start':'integer?','end':'integer?'}),
 'financial_comparison':('读取某一指标的实际、前期、有效基准和同比计算引用，缺失时保留未知',{'metric':'string','company':'string?'}),
 'financial_observations':('取得带指标、单位、期间、会计口径的数值引用',{'metric':'string?','period':'string?','company':'string?'}),
 'calculate':('受控计算 change/growth/ratio/subtract/quarterize/fee_shock；同期间预期/修订用 compare，跨指标加减用 add/sum_difference，倍数或换算用 multiply/divide。left/right 是计算引用 ID',{'operation':'string','left':'string','right':'string?','delta_pp':'number?'}),
 'mechanical_scenario':('明确输入的收入/费用率机械情景；不是盈利预测',{'revenue':'number','unit':'string','delta_pp':'number','period':'string'}),
 'operating_model':('使用已固定 PDD 模型计算经营利润；缺输入保留未知',{'assumptions':'array?'}),
 'clarify':('保存必要的具体问题并暂停研究等待用户，保留会话、成果和累计用量',{'question':'string'}),
 'source_index':('读取原件目录、页码和图表标题；不会将目录命中当成已阅读',{'source_id':'string?'}),
 'read_page':('完整读取 PDF 一页；visual=true 返回页面图像及文本。HTML 等不分页原件请用 read_source 并按 next_offset 继续',{'source_id':'string','page':'integer','visual':'boolean?'}),
 'read_table':('提取指定页的结构化表格，table_index 从零开始；失败时用 read_page visual',{'source_id':'string','page':'integer','table_index':'integer?'}),
 'register_requirements':('追加不可删除的研究要求；items: id/question/source_id/pages/kind/reason',{'items':'array'}),
 'register_numbers':('绑定原文数字，items 每项必填 evidence_id/text/metric/unit/period/role/basis/frequency；role 为 company_actual/reported_actual/reported_consensus/broker_forecast/user_forecast/scenario。可选 start、scale、precision、row_label、column_label、table_id、row、column。text 为原文精确数值，start 为引文内字符偏移；scale 仅用于明确单位换算。',{'items':'array'}),
 'calculate_batch':('依次批量计算；每项 operation/left/right，可选 alias 供后续 left/right 引用；逐项留账',{'items':'array'}),
 'reconcile_totals':('把已登记分项按 signs 加减，与 reported_total 勾稽。components 为计算编号数组；signs 默认全 +1。利润桥使用毛利 +1、费用 -1，直接列示的 OP 共识为 reported_total。分部收入使用 SOTP 各分部收入，合并年度预测为 reported_total。返回原值、加总、残差及原表显示精度的舍入范围，不自动认定作者错误。',{'components':'array','reported_total':'string','signs':'array?'}),
 'ledger':('分页读取已保存凭据，kind: evidence/calculation/reconciliation/table/reading/tool/checkpoint/review/requirements/discovery；ids 可指定精确编号',{'kind':'string?','ids':'array?','offset':'integer?','limit':'integer?'}),
 'save_checkpoint':('持续保存关键发现和下一步；可选 draft 为完整 AgentDraft 草稿',{'findings':'string','next_steps':'string','draft':'object?'}),
 'search_wiki':('按相关性读取已发布 Wiki 摘要及原件引用，不全量加载，不增加独立来源计数',{'query':'string','limit':'integer?','company':'string?'}),
 'search_public':('公开网络搜索，只返回候选网址；查询仅包含公开公司、期间与主题，不提交本地私有内容',{'query':'string'}),
 'fetch_public_source':('取得公开原件并纳入版本化输入；实际验证公开地址与重定向，不携带用户 cookie；历史截止不移动',{'url':'string','company':'string?'}),
}

def tool_schemas():
    out=[]
    for name,(description,fields) in CAPABILITIES.items():
        props={k:{'type':v.rstrip('?'),**({'items':{'type':'string' if k=='ids' else 'object'}} if v.startswith('array') else {})} for k,v in fields.items()}
        if name=='register_numbers':
            from .contracts import NumberRegistration
            props['items']['items']=NumberRegistration.model_json_schema()
        if name=='calculate_batch':
            from .contracts import CalculationStep
            props['items']['items']=CalculationStep.model_json_schema()
        if name=='reconcile_totals':
            props['components']['items']={'type':'string'};props['signs']['items']={'type':'integer','enum':[-1,1]}
        out.append({'name':name,'description':description,'inputSchema':{'type':'object','properties':props,'required':[k for k,v in fields.items() if not v.endswith('?')],'additionalProperties':False},'annotations':{'readOnlyHint':True,'destructiveHint':False}})
    return out
