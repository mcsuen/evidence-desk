"""Request-scoped reading, requirements and auditable table/number capabilities."""
from __future__ import annotations
import base64, io, re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from .contracts import Requirement, AgentDraft, NumberRegistration, CalculationStep
from ..storage import digest
from ..contracts import utcnow

FINANCIAL_ROLES = {'company_actual', 'reported_actual', 'reported_consensus', 'broker_forecast', 'user_forecast', 'scenario'}


def source_role(document):
    from .service import HOST_COMPANY
    if document.url.startswith('upload:'): return 'uploaded_claim'
    host=urlparse(document.url).hostname or ''
    from .semantics import REGULATORS
    if any(host==h or host.endswith('.'+h) for h in REGULATORS):return 'official'
    if host in {*HOST_COMPANY, 'www.sec.gov', 'data.sec.gov'} or host.endswith(('.gov','.gov.cn','.europa.eu')): return 'official'
    return 'third_party'

def reported_date(document):
    """Date stated on the original is distinct from independently known availability."""
    from datetime import datetime
    from ..sources import MONTHS
    text='\n'.join(b.text for b in document.blocks)[:2000]
    months={name.casefold():i for i,name in enumerate(MONTHS,1)}
    months.update({name[:3].casefold():i for i,name in enumerate(MONTHS,1)})
    months['sept']=9
    names='|'.join(sorted(months,key=len,reverse=True))
    # Only standalone datelines qualify. A period ending inside prose must not
    # become the report date. Preserve reading order across languages/formats.
    for line in text.splitlines():
        parts=None
        if m:=re.fullmatch(r'\s*(\d{1,2})\s+('+names+r')\.?\s+(20\d{2})\s*',line,re.I):
            parts=(int(m[3]),months[m[2].casefold()],int(m[1]))
        elif m:=re.fullmatch(r'\s*('+names+r')\.?\s+(\d{1,2}),?\s+(20\d{2})\s*',line,re.I):
            parts=(int(m[3]),months[m[1].casefold()],int(m[2]))
        elif m:=re.fullmatch(r'\s*(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\s*',line):
            parts=tuple(map(int,m.groups()))
        elif m:=re.fullmatch(r'\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*',line):
            parts=tuple(map(int,m.groups()))
        if parts:
            try:return datetime(*parts).date().isoformat()
            except ValueError:continue
    return ''


def parsed_number(text):
    text = text.strip().replace(',', '').replace('−', '-').replace('，', '')
    if text.startswith('(') and text.endswith(')'): text = '-' + text[1:-1]
    text = text.rstrip('%').strip()
    try: value = Decimal(text)
    except InvalidOperation: raise ValueError('单元格不是独立数值；保留原文并精确选择数值范围')
    if not value.is_finite(): raise ValueError('数值必须有限')
    return float(value)


class ResearchWorkspace:
    def source_dates(self, doc):
        """Read publication declarations without moving historical availability."""
        cache=self.state.setdefault('source_dates',{})
        if doc.id in cache:return cache[doc.id]
        value={'published_at':doc.published_at,'reported_date':reported_date(doc),
               'publication_precision':doc.publication_precision,'modified_at':'','publication_note':''}
        if doc.media_type=='text/html':
            from selectolax.parser import HTMLParser
            from datetime import datetime
            tree=HTMLParser((self.desk.files/doc.file_name).read_bytes())
            for prop,key in [('article:published_time','published_at'),('article:modified_time','modified_at')]:
                node=tree.css_first('meta[property="'+prop+'"]')
                if node:
                    try:
                        date=datetime.fromisoformat(node.attributes.get('content','').replace('Z','+00:00'))
                        if date.tzinfo is None:continue
                        value[key]=date.isoformat()
                        if key=='published_at':
                            value.update(reported_date=value['reported_date'] or date.date().isoformat(),publication_precision='original_metadata',
                                publication_note='发布时间为原网页声明；本次取得的网页版本不等于发布当日快照，可得时间仍按已核实记录保留。')
                    except ValueError:pass
        cache[doc.id]=value
        return value

    def source_pages(self, doc):
        pages=sorted({b.page for b in doc.blocks if b.page})
        if doc.media_type=='application/pdf':
            cache=self.state.setdefault('page_counts',{})
            if doc.id not in cache:
                import pdfplumber
                with pdfplumber.open(self.desk.files/doc.file_name) as pdf:cache[doc.id]=len(pdf.pages)
            pages=list(range(1,cache[doc.id]+1))
        return pages

    def requirements(self):
        return list(self.state.get('requirements', {}).values())

    def bootstrap_requirements(self):
        if self.state.get('requirements'): return
        from .verify import REQUIRED
        requirements = []
        for question in self.input.get('scope',{}).get('questions',[]):
            requirements.append(Requirement(id='request_'+digest(question)[:12],question=question))
        # Preserve the actual user requirements, rather than only section labels.
        for sid in self.input['source_ids']:
            if sid not in self.frozen['sources']: continue
            doc = self.desk.document(sid)
            for block_index,block in enumerate(doc.blocks):
                if re.match(r'Figure\s+\d+\s*[:：]', block.text, re.I):
                    following=[]
                    for next_block in doc.blocks[block_index+1:]:
                        if re.match(r'Figure\s+\d+\s*[:：]|Source:',next_block.text,re.I):break
                        following.append(next_block.text)
                    table_text='\n'.join(following)
                    revision=bool(re.search(r'(?:forecast|earnings).*revision|预测修订',block.text,re.I))
                    consensus=bool(re.search(r'consensus|共识|市场预期',table_text,re.I)) and not revision
                    metrics=[metric for pattern,metric in [(r'\brevenue\b|收入','revenue'),(r'gross profit|毛利','gross_profit'),(r'operating profit|经营利润|营业利润','operating_profit'),(r'net profit|净利','net_income')] if re.search(pattern,table_text,re.I)] if revision else []
                    comparisons=[{'metric':metric,'period':self.input.get('period',''),'basis':'non-GAAP' if metric=='net_income' and re.search(r'non.GAAP\s+net\s+profit|非.{0,8}净利',table_text,re.I) else ''}
                        for pattern,metric in [(r'\brevenue\b|收入','revenue'),(r'gross profit|毛利','gross_profit'),(r'operating profit|经营利润|营业利润','operating_profit'),(r'net profit|净利','net_income')] if re.search(pattern,table_text,re.I)] if consensus else []
                    requirements.append(Requirement(id='table_' + digest([sid, block.id])[:12], question=block.text,
                        source_id=sid, pages=[block.page] if block.page else [], kind='table', reason='附件显式图表必须检查；无法读取应记录具体原因',
                        check='forecast_revision_ratios' if revision and metrics else 'consensus_comparison_ratios' if comparisons else 'answer',required_metrics=metrics,
                        required_periods=list(dict.fromkeys(re.findall(r'\b20\d{2}E\b',table_text))) if revision else [],required_comparisons=comparisons))
                    if revision and metrics:
                        requirements[-1].reason+='；按表中年度逐项重算收入、利润的修订百分比（current / previous − 1），保留绝对额、原始预测身份及舍入差异。仅算绝对变化或抄写百分比不算完成。'
                    if comparisons:
                        requirements[-1].reason+='；逐项重算 required_comparisons 指标的实际值与共识差异（actual / consensus − 1），绑定 compare 计算。优先使用原表 reported_actual 和 reported_consensus，保留口径与共识未独立核实限制；其他表内计算或只复述方向不能替代。'
            if self.input['intent']=='report_review':
                content='\n'.join(b.text for b in doc.blocks)
                for index,block in enumerate(doc.blocks):
                    if block.page in (1,2) and re.search(r'we expect|we are looking|we believe|in our view|我们预计|我们认为',block.text,re.I):
                        original='\n'.join(b.text for b in doc.blocks[max(0,index-1):index+5] if b.page==block.page)
                        concepts=[]
                        for pattern,name,terms in [
                            (r'semi.{0,100}?(?:entrusted|managed)|半托管','半托管模式',['半托管','semi-entrusted','semi-managed']),
                            (r'local fulfil|本地履约','本地履约',['本地履约','本地配送','local fulfilment','local fulfillment']),
                            (r'other countries|non.US|非美','非美国业务扩张',['其他国家','其它国家','非美','美国以外','其他市场','other countries','non-US']),
                            (r'merchant support|商家支持','商家支持',['商家支持','商家扶持','支持商家','扶持商家','merchant support'])]:
                            if re.search(pattern,original,re.I|re.S):concepts.append({'name':name,'terms':terms})
                        requirements.append(Requirement(id='author_view_'+digest([sid,block.id])[:12],
                            question='核对作者以下判断及其中的驱动、条件或抵消因素；逐项说明证据支持和待查限制，不能只复述笼统方向：\n'+original,
                            source_id=sid,pages=[block.page],required_concepts=concepts,reason='附件摘要中的显式作者判断，保留原文定位以供独立复核'))
                for key,question in [('consensus_profit_reconciliation','用原研报的毛利、销售营销、行政和研发共识重建经营利润，再与原研报直接列示的经营利润共识比较。使用 reconcile_totals，保留残差及聚合口径待查；不能用公司实际收入加总替代。'),
                    ('segment_revenue_reconciliation','把原研报 SOTP 估值表中的分部预测收入加总，与同一研报财务预测表的同年度合并收入核对。使用 reconcile_totals，保留口径和舍入限制；这里检查券商表内预测，不要求公司披露分部实际值，也不能用 SOTP 每 ADS 价格加总代替。'),
                    ('valuation_price_reconciliation','把原研报 SOTP 表的各分部和净现金每 ADS 估值加总，与表中每 ADS 总目标价比较。使用 reconcile_totals，报告计算总价、残差及原表显示精度容许的舍入范围；只读总价或加总收入不能替代。'),
                    ('public_investigation','对影响核心判断的政策、行业与业务模式解释尝试合理的公开原件补查；记录查询路径和取得或未能取得的资料，搜索摘要不作为证据。')]:
                    # Attach financial checks only when this report has the
                    # corresponding table. Other reports retain their own
                    # question/figure requirements and can add new checks.
                    if key=='consensus_profit_reconciliation' and not (re.search(r'consensus|共识',content,re.I) and re.search(r'gross profit|毛利',content,re.I) and re.search(r'operating profit|经营利润|营业利润',content,re.I)):continue
                    if key=='segment_revenue_reconciliation' and not (re.search(r'SOTP|分部估值|分部加总',content,re.I) and re.search(r'revenue|收入',content,re.I)):continue
                    if key=='valuation_price_reconciliation' and not (re.search(r'SOTP|分部估值|分部加总',content,re.I) and re.search(r'/ADS|每\s*ADS',content,re.I)):continue
                    if key=='public_investigation' and not self.input.get('scope',{}).get('allow_public_search',True):continue
                    requirements.append(Requirement(id=key+'_'+digest(sid)[:12],question=question,source_id=sid,kind='model',reason='研报复核要求模板',check=key))
        if not requirements:
            requirements = [Requirement(id=k, question=k) for k in REQUIRED[self.input['intent']]]
        self.state['requirements'] = {r.id: r.model_dump() for r in requirements}
        self.checkpoint({'research': self.state})

    def register_requirements(self, items):
        self.prepare()
        if getattr(self, 'role', 'researcher') == 'reviewer': raise ValueError('复核发现的新增要求应放入 additional_requirements，由控制器登记')
        current = dict(self.state.get('requirements', {}))
        for item in items:
            r = Requirement.model_validate(item)
            if r.source_id and r.source_id not in self.frozen['sources']: raise ValueError('要求的来源不在本次输入')
            if r.id in current and current[r.id] != r.model_dump(): raise ValueError('已登记要求不可覆盖；新增要求使用新 id')
            current[r.id] = r.model_dump()
        self.state['requirements'] = current
        self.checkpoint({'research': self.state})
        return self.receipt('requirements', {'items': list(current.values())})

    def source_index(self, source_id=''):
        self.prepare()
        ids = [source_id] if source_id else list(self.frozen['sources'])
        result = []
        for sid in ids:
            if sid not in self.frozen['sources']: raise ValueError('来源不在本次输入')
            doc = self.desk.document(sid)
            item = {'source_id': sid, 'title': doc.title, 'url': doc.url, 'source_role': source_role(doc),
                **self.source_dates(doc), 'available_at': doc.available_at, 'observed_at': doc.observed_at,
                'total_blocks': len(doc.blocks),
                'page_count': max(self.source_pages(doc), default=0), 'issues': doc.issues}
            if source_id or sid in self.input['source_ids']:
                pages = self.source_pages(doc)
                item['pages'] = [{'page': p, 'blocks': sum(b.page == p for b in doc.blocks),
                    'headings': [b.text[:180] for b in doc.blocks if b.page == p and (re.search(r'Figure\s+\d+|Summary|Risks|Disclosures', b.text, re.I))][:12]} for p in pages]
            result.append(item)
        return result

    def _record_reading(self, sid, blocks, mode='text', page=None, error=''):
        return self.receipt('reading', {'source_id': sid, 'block_ids': [b.id for b in blocks],
            'pages': sorted({b.page for b in blocks if b.page} | ({page} if page else set())),
            'mode': mode, 'role': getattr(self, 'role', 'researcher'), 'error': error})

    def reading_status(self):
        readings = list(self.receipts('reading').values())
        result = []
        for sid in self.frozen['sources']:
            doc = self.desk.document(sid)
            entries = [r for r in readings if r['source_id'] == sid]
            seen = {b for r in entries if not r.get('error') for b in r['block_ids']}
            pages = self.source_pages(doc) or [None]
            for page in pages:
                blocks = {b.id for b in doc.blocks if b.page == page}
                visual = any(r['mode'] == 'visual' and page in r['pages'] and not r.get('error') for r in entries)
                count = len(blocks & seen)
                result.append({'source_id': sid, 'title': doc.title, 'page': page,
                    'status': 'read' if visual or (blocks and blocks <= seen) else 'partial' if count else 'unread',
                    'read_blocks': count, 'total_blocks': len(blocks), 'visual': visual,
                    'errors': list(dict.fromkeys(r['error'] for r in entries if r.get('error') and page in r['pages']))})
        return result

    def read_page(self, source_id, page, visual=False):
        self.prepare()
        if source_id not in self.frozen['sources'] or page < 1: raise ValueError('来源或页码不合法')
        doc = self.desk.document(source_id)
        if doc.media_type != 'application/pdf' and not any(b.page for b in doc.blocks):
            raise ValueError(f'该原件不分页，不能用 read_page 或 visual 读取。请 read_source(source_id="{source_id}")，按 next_offset 继续读取；来源包含 {len(doc.blocks)} 个文本段。')
        blocks = [b for b in doc.blocks if b.page == page]
        result = {'source_id': source_id, 'page': page, 'title': doc.title,
                  'blocks': [self._evidence(source_id, b, 0, len(b.text)) for b in blocks]}
        if visual:
            if doc.media_type != 'application/pdf': raise ValueError('视觉读取仅用于 PDF 页面')
            try:
                import pdfplumber
                with pdfplumber.open(self.desk.files / doc.file_name) as pdf:
                    if page > len(pdf.pages): raise ValueError('页码超出原件')
                    img = pdf.pages[page - 1].to_image(resolution=130).original
                    output = io.BytesIO(); img.save(output, format='PNG')
                result['_mcp_images'] = [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(output.getvalue()).decode()}]
            except Exception as error:
                self._record_reading(source_id, [], 'visual', page, str(error)); raise
        elif not blocks:
            self._record_reading(source_id, [], 'text', page, '页面没有可提取文本，请尝试视觉读取')
            result['issue'] = '页面没有可提取文本，请尝试视觉读取'
            return result
        result['reading_receipt'] = self._record_reading(source_id, blocks, 'visual' if visual else 'text', page)['id']
        return result

    def read_table(self, source_id, page, table_index=0):
        self.prepare()
        if source_id not in self.frozen['sources']: raise ValueError('来源不在本次输入')
        doc = self.desk.document(source_id)
        if doc.media_type != 'application/pdf':
            tables = [b for b in doc.blocks if b.kind == 'table']
            if not 0 <= table_index < len(tables): raise ValueError('没有此表格；请读取原文')
            block = tables[table_index]; evidence = self._evidence(source_id, block, 0, len(block.text))
            return self.receipt('table', {'source_id': source_id, 'source_version': doc.digest, 'page': block.page,
                'table_index': table_index, 'cells': block.cells, 'evidence_ids': [evidence['id']], 'bbox': block.bbox})
        import pdfplumber
        with pdfplumber.open(self.desk.files / doc.file_name) as pdf:
            if not 1 <= page <= len(pdf.pages): raise ValueError('页码超出原件')
            p = pdf.pages[page - 1]
            tables = p.find_tables()
            if not tables: tables = p.find_tables({'vertical_strategy': 'text', 'horizontal_strategy': 'text'})
            if not 0 <= table_index < len(tables): raise ValueError('此页没有该结构化表格；使用 read_page(visual=true) 核对，不能推断原件缺少数据')
            table = tables[table_index]
            bbox = [table.bbox[0]/p.width, table.bbox[1]/p.height, table.bbox[2]/p.width, table.bbox[3]/p.height]
            blocks = [b for b in doc.blocks if b.page == page and b.bbox and b.bbox[1] < bbox[3] and b.bbox[3] > bbox[1]]
            evidence = [self._evidence(source_id, b, 0, len(b.text))['id'] for b in blocks]
            value = {'source_id': source_id, 'source_version': doc.digest, 'page': page, 'table_index': table_index,
                     'table_count': len(tables), 'cells': table.extract(), 'bbox': bbox, 'evidence_ids': evidence}
        self._record_reading(source_id, blocks, 'table', page)
        return self.receipt('table', value)

    def register_numbers(self, items):
        """Bind quoted literals. A report's consensus/forecast never becomes issuer actuals."""
        results = []
        for index,item in enumerate(items):
            role = item.get('role')
            missing=[k for k in ('evidence_id','text','metric','unit','period','role','basis','frequency') if not item.get(k)]
            if missing:raise ValueError('数字登记缺少字段：'+', '.join(missing)+'；frequency 填 quarter/annual/ytd，basis 按原件填 GAAP/non-GAAP/disclosed')
            item=NumberRegistration.model_validate(item).model_dump(exclude_none=True)
            if role not in FINANCIAL_ROLES: raise ValueError('role 必须区分 company_actual/reported_actual/reported_consensus/broker_forecast/user_forecast/scenario')
            refs = self.receipts('evidence')
            eid = item.get('evidence_id'); evidence = refs.get(eid)
            if not evidence: raise ValueError('evidence_id 不属于本次读取账本')
            doc = self.desk.document(evidence['source_id'])
            if role == 'company_actual' and source_role(doc) != 'official': raise ValueError('上传或第三方数字不能登记为官方公司实际值')
            from .subjects import require_company,ids
            item['company_id']=require_company(self,item.get('company_id',''),allow_topic=not ids(self))
            if evidence.get('company_id') and evidence['company_id']!=item['company_id']:raise ValueError('数字主体与绑定原件不一致')
            literal = str(item['text']); value = parsed_number(literal)
            locator = {k: item.get(k, '') for k in ('row_label', 'column_label', 'table_id', 'row', 'column')}
            table_id = item.get('table_id')
            if table_id:
                table = self.receipts('table').get(table_id)
                if not table or eid not in table['evidence_ids']: raise ValueError(f'items[{index}].table_id={table_id} 与 evidence_id={eid} 身份不一致')
                if item.get('row') is None or item.get('column') is None:raise ValueError(f'items[{index}].row/column 缺失：指定 table_id 时必须提供零起始数值坐标；仅按原文绑定时可省略 table_id，保留行列标题。')
                try: cell = table['cells'][int(item['row'])][int(item['column'])] or ''
                except (KeyError, IndexError, TypeError, ValueError): raise ValueError(f'items[{index}].row/column={item.get("row")}/{item.get("column")} 超出表格单元格范围；请 read_table 核对坐标')
                if literal not in cell: raise ValueError(f'items[{index}].text={literal} 不在所指单元格；该单元格为 {cell}')
            if literal not in evidence['quote']: raise ValueError('数字不在绑定的原文中')
            # Reject choosing the second number implicitly in multi-column prose.
            start = item.get('start')
            occurrences=[m.start() for m in re.finditer(re.escape(literal),evidence['quote'])]
            if start is None:
                if len(occurrences) != 1: raise ValueError(f'items[{index}].start 缺失：数字 {literal} 重复出现；原文中的 start 候选为 {occurrences}。请按对应期间和列选择，不要猜测字符位置。')
                start = evidence['quote'].index(literal)
            if evidence['quote'][start:start+len(literal)] != literal: raise ValueError(f'items[{index}].start={start} 的原文与 text={literal} 不一致；可匹配的原文 start 候选为 {occurrences}，请按对应期间和列核对。')
            before=evidence['quote'][start-1:start] if start else ''
            after=evidence['quote'][start+len(literal):start+len(literal)+1]
            if (before and re.match(r'[\d.,]',before)) or (after and re.match(r'[\d.,]',after) and not (after=='.' and not evidence['quote'][start+len(literal)+1:start+len(literal)+2].isdigit())):
                raise ValueError('必须绑定完整数字，不能截取金额的一部分')
            scale = item.get('scale', 1)
            if scale not in (1, .001, 1000, .000001, 1000000): raise ValueError('scale 仅用于已标明单位的千/百万换算')
            locator.update(source_id=doc.id, source_version=doc.digest, block_id=evidence['block_id'], page=evidence.get('page'),
                start=evidence['start']+start, end=evidence['start']+start+len(literal), literal=literal, scale=scale)
            from .units import canonical_unit
            locator['original_unit']=item['unit']
            result = self._calc(item['metric'], value*scale, canonical_unit(item['unit']), item['period'], 'source_literal', [eid],
                basis=item.get('basis','disclosed'), frequency=item.get('frequency','annual'), precision=item.get('precision',3),
                source_roles=[role], source_locator=locator,company_id=item.get('company_id',''),
                verification_status='issuer_disclosed' if role=='company_actual' else 'quoted_not_independently_verified',
                limitations=[] if role=='company_actual' else ['按原件所列数值登记；不代表共识、预测或情景已获独立验证'])
            results.append(result)
        return results

    def calculate_batch(self, items):
        aliases = {}; result = []; errors=[]
        for index,item in enumerate(items):
            alias=item.get('alias','')
            try:
                operation=CalculationStep.model_validate(item).model_dump(exclude_none=True);operation.pop('alias',None)
                for key in ('left','right'):
                    if operation.get(key) in aliases: operation[key] = aliases[operation[key]]
                value = self.calculate(**operation)
            except (ValueError,TypeError) as error:
                errors.append({'index':index,'alias':alias,'input':item,'message':str(error)});continue
            if alias: aliases[alias] = value['id']
            result.append(value)
        return {'results': result, 'aliases': aliases,'errors':errors,'status':'partial' if errors else 'completed'}

    def reconcile_totals(self, components, reported_total, signs=None):
        from .reconcile import reconcile
        return reconcile(self,components,reported_total,signs)

    def ledger(self, kind='evidence', ids=None, offset=0, limit=30):
        if kind not in ('evidence','calculation','reconciliation','table','reading','tool','checkpoint','review','requirements','discovery'): raise ValueError('未知账本类型')
        values = list(self.receipts(kind).values())
        if ids: values = [v for v in values if v['id'] in ids]
        if offset < 0 or not 1 <= limit <= 100: raise ValueError('分页范围不合法')
        page = values[offset:offset+limit]
        if kind == 'tool': page = [{k:v for k,v in t.items() if k!='result'} for t in page]
        return {'items': page, 'total': len(values), 'next_offset': offset+len(page) if offset+len(page)<len(values) else None}

    def save_checkpoint(self, findings, next_steps, draft=None):
        if getattr(self,'role','researcher') == 'reviewer': raise ValueError('复核意见通过独立复核结果提交，不覆盖研究草稿')
        value = {'findings': findings, 'next_steps': next_steps, 'role': 'researcher','at':utcnow()}
        if draft is not None: value['draft'] = AgentDraft.model_validate(draft).model_dump()
        receipt = self.receipt('checkpoint', value)
        self.state['checkpoint_id'] = receipt['id']
        self.state['progress']={'findings':findings,'next_steps':next_steps,'saved_at':utcnow()}
        self.checkpoint({'research': self.state})
        return {'id': receipt['id'], 'saved': True}

    def search_wiki(self, query, limit=5, company=''):
        from pitr.wiki.search import search
        from pitr.wiki.evidence import model_page
        from .subjects import require_company
        company=require_company(self,company,allow_topic=True)
        found = search(self.desk.wiki, company or self.input['company'], query, as_of=self.frozen['as_of'], limit=limit)
        return {**found, 'items': [model_page(p) for p in found['items']],
            'note': 'Wiki 是已有研究线索；结论仍需追溯原件，不增加独立来源计数'}
