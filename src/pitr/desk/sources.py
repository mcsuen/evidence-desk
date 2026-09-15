"""Original disclosures, stable document anchors and conservative PDD table extraction."""
from __future__ import annotations
import hashlib
import io
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo
import httpx
from selectolax.parser import HTMLParser
from .contracts import Document, SourceBlock, Citation, Metric, utcnow
from .storage import digest

HOSTS={'investor.pddholdings.com','pinduoduo.gcs-web.com','www.sec.gov','data.sec.gov',
       'www.alibabagroup.com','ir.jd.com','ir.aboutamazon.com','investor.mercadolibre.com'}
MONTHS='January February March April May June July August September October November December'.split()


def fetch(url,*,contact='',client=None):
    client=client or httpx.Client(timeout=40,follow_redirects=False)
    for redirect in range(5):
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in HOSTS or parsed.username or parsed.port not in (None,443):
            raise ValueError('仅获取已登记公司的官方 HTTPS 来源；其他材料可以上传原件')
        if parsed.hostname.endswith('sec.gov') and not contact:raise ValueError('SEC 访问需要在本机设置填写真实联系邮箱')
        headers={'User-Agent':contact} if parsed.hostname.endswith('sec.gov') else {}
        for attempt in range(4):
            try:response=client.get(url,headers=headers)
            except httpx.TransportError:
                if attempt==3:raise
                time.sleep(2**attempt);continue
            if response.status_code in (429,500,502,503,504) and attempt<3:
                time.sleep(min(2**attempt,8));continue
            break
        if response.is_redirect:
            url=urljoin(url,response.headers['location']);continue
        if response.status_code!=200:raise ValueError(f'官方来源暂不可用（HTTP {response.status_code}）')
        if len(response.content)>40_000_000:raise ValueError('原件超过 40 MB，请拆分后导入')
        return response.content,response.headers.get('content-type',''),url
    raise ValueError('来源重定向次数过多')


def publication(text,observed):
    # Only an explicit date line, in reading order. A month-name loop wrongly
    # preferred "quarter ended June 30" to the earlier August publication line.
    months='|'.join(MONTHS)
    found=re.search(r'^\s*('+months+r')\s+(\d{1,2}),?\s+(20\d{2})\s*$',text[:1600],re.M)
    if found:
        value=datetime(int(found[3]),MONTHS.index(found[1])+1,int(found[2]),23,59,59,tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc).isoformat()
        return value,'day'
    return observed,'observed'


def parse_document(content,media_type,url,company,title='',published_at=None,observed_at=None):
    observed=observed_at or utcnow(); sha=hashlib.sha256(content).hexdigest()
    sid='source_'+digest(['desk-publication.1',company,url,sha])[:24];blocks=[];issues=[]
    if content.startswith(b'%PDF'):
        import pdfplumber
        media_type='application/pdf'
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for index,page in enumerate(pdf.pages):
                lines=page.extract_text_lines()
                if not lines:issues.append(f'第 {index+1} 页未识别到文本层，需要在原件中核对。')
                for j,line in enumerate(lines):
                    text=line['text'].strip()
                    if text:
                        blocks.append(SourceBlock(id=f'p{index+1}-l{j+1}',text=text,page=index+1,
                          bbox=[line['x0']/page.width,line['top']/page.height,line['x1']/page.width,line['bottom']/page.height]))
        file_name=sid+'.pdf'
    elif 'html' in media_type or b'<html' in content[:1000].lower() or b'<!doctype' in content[:1000].lower():
        # Preserve the original byte encoding; pre-decoding as UTF-8 destroyed
        # otherwise readable GBK/GB18030 public disclosures and reprints.
        media_type='text/html';tree=HTMLParser(content)
        for node in tree.css('script,style,nav,header,footer,noscript,iframe,form'):node.decompose()
        title=title or (tree.css_first('title').text() if tree.css_first('title') else '')
        nodes=tree.css('p,h1,h2,h3,h4,h5,table')
        for i,node in enumerate(nodes):
            if node.parent and node.parent.tag in ('td','th'):continue
            if node.tag=='table':
                cells=[[c.text(separator=' ',strip=True) for c in row.css('th,td')] for row in node.css('tr')]
                text='\n'.join(' | '.join(row) for row in cells)
                if text.strip():blocks.append(SourceBlock(id=f'table-{i}',text=text,kind='table',cells=cells))
            else:
                text=node.text(separator=' ',strip=True)
                if text:blocks.append(SourceBlock(id=f'block-{i}',text=text))
        if not blocks and tree.body:blocks=[SourceBlock(id='body',text=tree.body.text(separator='\n',strip=True))]
        file_name=sid+'.html'
    else:
        media_type='text/plain';text=content.decode('utf-8',errors='replace')
        blocks=[SourceBlock(id=f'paragraph-{i}',text=t.strip()) for i,t in enumerate(re.split(r'\n\s*\n',text)) if t.strip()]
        file_name=sid+'.txt'
    text='\n'.join(b.text for b in blocks)
    stamp,precision=publication(text,observed)
    if url.startswith('upload:'):
        stamp,precision=observed,'observed'
        issues.append('上传原件未独立核实历史可用时间，按本次导入时间纳入。')
    if '年度报告' in title or 'annual report' in title.lower() or re.search(r'FORM\s+20-F',text[:4000],re.I):
        stamp,precision=observed,'observed'
        issues.append('年报封面的财年结束日不是发布日期；未核实申报时刻前，按本次获取时间纳入。')
    if published_at:
        dt=datetime.fromisoformat(published_at.replace('Z','+00:00'))
        if dt.tzinfo is None:raise ValueError('来源时间需要包含时区')
        # An owner assertion is not independent evidence of historical availability.
        stamp=max(stamp,dt.isoformat()) if precision!='observed' else observed
        issues.append('用户提供的发布时间保留作参考；可用时间仍依据原文或本次获取。')
    if not title:title=' '.join(text.splitlines()[:1])[:180] or '导入资料'
    return Document(id=sid,company=company,title=title,url=url,digest=sha,media_type=media_type,
        published_at=stamp,available_at=stamp,observed_at=observed,publication_precision=precision,
        origin_group=digest([company,re.sub(r'\s+',' ',text[:1000])])[:24],blocks=blocks,file_name=file_name,issues=issues,identity_version='desk-original.1')


def ingest(repo,content,media_type,url,company,title='',published_at=None):
    previous=[d for d in repo.documents(company) if d.url==url]
    sha=hashlib.sha256(content).hexdigest()
    if previous and previous[0].digest==sha and previous[0].identity_version=='desk-original.1':return previous[0]
    doc=parse_document(content,media_type,url,company,title,published_at)
    if previous:
        latest=previous[0]
        doc.supersedes=latest.id
        if latest.digest!=doc.digest:doc.available_at=doc.observed_at
    destination=repo.files/doc.file_name
    if not destination.exists():
        temporary=destination.with_suffix('.tmp');temporary.write_bytes(content);temporary.replace(destination)
    return repo.put_document(doc)


def pdd_catalog(contact=''):
    raw,_,base=fetch('https://investor.pddholdings.com/financial-information/quarterly-results',contact=contact)
    return parse_catalog(raw,base)


def parse_catalog(raw,base):
    tree=HTMLParser(raw.decode());items=[]
    for node in tree.css('a'):
        if 'Earnings Release' not in node.text():continue
        title=node.attributes.get('title','')
        match=re.search(r'(First|Second|Third|Fourth) Quarter (20\d{2})',title,re.I)
        if not match:continue
        year=int(match[2]);quarter=['first','second','third','fourth'].index(match[1].lower())+1
        if year>=2023:items.append({'url':urljoin(base,node.attributes['href']),'title':f'PDD · {year}Q{quarter} 财务业绩原件','period':f'{year}Q{quarter}'})
    if not items:raise ValueError('官方财报目录结构已变化，请通过原件链接导入；未使用历史样例替代')
    return items


def pdd_latest_annual():
    raw,_,base=fetch('https://investor.pddholdings.com/financial-information/annual-reports')
    items=[]
    for node in HTMLParser(raw).css('a'):
        m=re.search(r'(20\d{2}) Annual Report',node.text(),re.I)
        if m:items.append({'url':urljoin(base,node.attributes.get('href','')),'title':f'PDD · {m[1]} 年度报告','period':m[1]+'FY'})
    if not items:raise ValueError('未定位到最新年度报告')
    return sorted(items,key=lambda x:x['period'],reverse=True)[0]


def pdd_news_url(period):
    if not re.fullmatch(r'20\d{2}Q[1-4]', period):raise ValueError('PDD 季度格式无效')
    year=period[:4];q=int(period[-1]);word=['first','second','third','fourth'][q-1]
    suffix=f'pdd-holdings-announces-{word}-quarter-{year}-unaudited-financial'
    if q==4:suffix=f'pdd-holdings-announces-fourth-quarter-{year}-and-fiscal-year-{year}'
    return 'https://investor.pddholdings.com/news-releases/news-release-details/'+suffix


def pdd_pdf_links(raw, base):
    links=[]
    for node in HTMLParser(raw).css('a'):
        href=node.attributes.get('href','')
        if re.fullmatch(r'/node/\d+/pdf',href):links.append(urljoin(base,href))
    return links


def pdd_pdf_fallback(period):
    """Resolve the PDF link from the issuer's own news article when its CDN fails."""
    raw,_,base=fetch(pdd_news_url(period))
    for link in pdd_pdf_links(raw, base):return fetch(link)
    raise ValueError('公司新闻原页没有可定位的 PDF 版本')


def extract_annual_cashflow(doc):
    """Consolidated three-year cash-flow rows; leave interpretation/classification open."""
    match=re.search(r'(20\d{2})',doc.title)
    if not match:return []
    year=int(match[1]);active=False;scale=None;header_ok=False;result=[];section=''
    labels={
        'Depreciation and amortization':('depreciation','折旧与摊销'),
        'Purchase of property, equipment and software and intangible assets':('capex','资本开支'),
        'Net cash generated from operating activities':('operating_cash_flow','经营现金流'),
        'Share-based compensation':('sbc','股权激励费用'),
        'Short-term investments':('cashflow_short_investments','经营现金流中的短期投资变动'),
        'Payable to merchants':('cashflow_merchant_payables','应付商家款项的现金流变动'),
        'Merchant deposits':('cashflow_merchant_deposits','商家保证金的现金流变动'),
    }
    for b in doc.blocks:
        if 'CONSOLIDATED STATEMENTS OF CASH FLOWS' in b.text:active=True;section='cash';header_ok=False;continue
        if 'CONSOLIDATED STATEMENTS OF COMPREHENSIVE INCOME' in b.text:active=True;section='income';header_ok=False;continue
        if active and 'CONSOLIDATED STATEMENTS OF CHANGES IN' in b.text:active=False;continue
        if active and 'NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS' in b.text:break
        if not active:continue
        if 'Amounts in thousands of RMB' in b.text:scale=.001
        if re.sub(r'\s+',' ',b.text).strip()=='RMB RMB RMB US$':header_ok=True
        if not header_ok or scale is None:continue
        chosen=labels if section=='cash' else {label:MAP[re.sub(r'\s+','',label).lower()] for label in ('Revenues','Costs of revenues','Sales and marketing expenses','General and administrative expenses','Research and development expenses','Operating profit','Net income')}
        for label,(name,display) in chosen.items():
            if not b.text.startswith(label+' '):continue
            tail=b.text[len(label):].strip();tokens=tail.split()
            if len(tokens)!=4 or not all(re.fullmatch(r'\(?[\d,]+(?:\.\d+)?\)?|—|-',t) for t in tokens):continue
            values=[0. if t in ('—','-') else float(t.strip('()').replace(',',''))*(-1 if t.startswith('(') else 1) for t in tokens]
            for offset,value in enumerate(values[:3]):
                period=f'{year-2+offset}FY';value*=scale
                if name in ('capex','cost_of_revenue','sales_marketing','general_admin','research_development'):value=abs(value)
                result.append(Metric(id='metric_'+digest([doc.id,name,period])[:20],name=name,label=display,period=period,value=value,unit='RMB_mn',frequency='annual',citation=Citation(source_id=doc.id,block_id=b.id,quote=b.text)))
    return result


NUM=re.compile(r'(?<![A-Za-z\d])\(?-?\d[\d,]*(?:\.\d+)?\)?')
MAP={
 'revenues':('revenue','收入'), 'costsofrevenues':('cost_of_revenue','收入成本'),
 'salesandmarketingexpenses':('sales_marketing','销售与营销费用'),
 'generalandadministrativeexpenses':('general_admin','一般与行政费用'),
 'researchanddevelopmentexpenses':('research_development','研发费用'),
 'totaloperatingexpenses':('operating_expenses','经营费用合计'), 'operatingprofit':('operating_profit','经营利润'),
 'netincome':('net_income','净利润'), 'online marketingservicesandothers':('online_marketing','在线营销服务及其他'),
 'onlinemarketingservicesandothers':('online_marketing','在线营销服务及其他'),
 'transactionservices':('transaction_services','交易服务收入'),
 'netcashgeneratedfromoperatingactivities':('operating_cash_flow','经营现金流'),
 'cashandcashequivalents':('cash','现金及现金等价物'), 'restrictedcash':('restricted_cash','受限现金'),
 'short-terminvestments':('short_investments','短期投资'), 'payabletomerchants':('merchant_payables','应付商家款项'),
 'merchantdeposits':('merchant_deposits','商家保证金'),
 'interestandinvestmentincome,net':('investment_income','利息及投资收益'),
 'interestandinvestmentincome/(loss),net':('investment_income','利息及投资净损益'),
 'foreignexchangeloss':('fx_gain_loss','汇兑净损益'),
 'foreignexchangegain/(loss)':('fx_gain_loss','汇兑净损益'),
 'otherincome/(loss),net':('other_gain_loss','其他净损益'),
 'otherincome,net':('other_gain_loss','其他净损益'),
 'shareofresultsofequityinvestees':('equity_gain_loss','权益法投资净损益'),
 'incometaxexpenses':('income_tax','所得税费用'),
}


def extract_pdd_metrics(doc):
    if doc.company!='PDD':return []
    if not any(re.search(r'PDD\s+HOLDINGS|PINDUODUO\s+INC',b.text,re.I) for b in doc.blocks[:100]):return []
    if '年度报告' in doc.title or 'annual report' in doc.title.lower():return extract_annual_cashflow(doc)
    full='\n'.join(b.text for b in doc.blocks)
    period=re.search(r'(20\d{2})Q([1-4])',doc.title)
    if not period:
        found=re.search(r'(First|Second|Third|Fourth) Quarter (20\d{2})',full,re.I)
        if not found:return []
        year=int(found[2]);quarter=['first','second','third','fourth'].index(found[1].lower())+1
    else:year=int(period[1]);quarter=int(period[2])
    result={};scale=.001 if re.search(r'Amounts in thousands',full,re.I) else 1.0
    section='';pending='';subsection='';context='';units_seen=False
    for block in doc.blocks:
        text=block.text;flat=re.sub(r'\s+','',text).lower()
        context=(context+' '+text)[-1400:]
        if 'amountsinmillions' in flat:scale=1.;units_seen=True
        if 'amountsinthousands' in flat:scale=.001;units_seen=True
        if 'balancesheets' in flat:section='balance';subsection='';pending=''
        elif 'statementsofincome' in flat:section='income';subsection='';pending=''
        elif 'statementsofcashflows' in flat:section='cashflow';subsection='';pending=''
        elif 'notestofinancialinformation' in flat:section='notes';subsection='';pending=''
        elif 'reconciliationofnon-gaap' in flat:section='reconciliation';subsection='';pending=''
        if 'share-basedcompensationexpenses' in flat and section=='notes':subsection='sbc'
        if 'earningsperads' in flat and section=='income':subsection='ads'
        if 'weighted-averagenumber' in flat and section=='income':subsection='shares'
        if not section or not units_seen:continue
        nums=list(NUM.finditer(text))
        if len(nums) not in (3,6):
            if not nums and len(text)<160:pending=text
            continue
        prefix=text[:nums[0].start()].strip().strip('-').strip()
        label=re.sub(r'\s+','',prefix).lower()
        key=MAP.get(label)
        if not key and pending:key=MAP.get(re.sub(r'\s+','',pending+prefix).lower())
        unit='RMB_mn';basis='GAAP'
        if label in ('diluted','-diluted') and subsection in ('ads','shares'):
            key=('eps_ads','摊薄每 ADS 收益') if subsection=='ads' else ('diluted_shares','加权摊薄普通股数量')
            unit='RMB_per_ADS' if subsection=='ads' else 'million_shares'
        if not key or subsection=='sbc' or section=='reconciliation':continue
        if section=='balance' and key[0] not in ('cash','restricted_cash','short_investments','merchant_payables','merchant_deposits'):continue
        if section!='balance' and key[0] in ('cash','restricted_cash','short_investments','merchant_payables','merchant_deposits'):continue
        if section=='cashflow' and key[0]!='operating_cash_flow':continue
        values=[float(m.group().replace(',','').replace('(','-').replace(')','')) for m in nums]
        conversion=1 if unit=='RMB_per_ADS' else scale
        value=values[1]*conversion
        if key[0] in ('cost_of_revenue','sales_marketing','general_admin','research_development','operating_expenses','income_tax'):value=abs(value)
        freq='instant' if section=='balance' else 'quarter'
        citation=Citation(source_id=doc.id,block_id=block.id,quote=block.text)
        identity=(key[0],f'{year}Q{quarter}',freq)
        result.setdefault(identity,Metric(id='metric_'+digest([doc.id,identity])[:20],name=key[0],label=key[1],period=identity[1],value=value,unit=unit,basis=basis,frequency=freq,citation=citation))
        if len(values)==6 and section!='balance':
            annual=quarter==4;extra_period=f'{year}FY' if annual else f'{year}YTD{quarter}'
            ident=(key[0],extra_period,'annual' if annual else 'ytd')
            extra=values[4]*conversion
            if key[0] in ('cost_of_revenue','sales_marketing','general_admin','research_development','operating_expenses','income_tax'):extra=abs(extra)
            result.setdefault(ident,Metric(id='metric_'+digest([doc.id,ident])[:20],name=key[0],label=key[1],period=extra_period,value=extra,unit=unit,frequency=ident[2],citation=citation))
        pending=''
    # Mark only the five independently extractable statement lines whose identity
    # holds. Other metrics remain explicitly extracted, not semantically certified.
    q={m.name:m for m in result.values() if m.frequency=='quarter'}
    needed=['revenue','cost_of_revenue','sales_marketing','general_admin','research_development','operating_profit']
    if all(k in q for k in needed):
        expected=q['revenue'].value-sum(q[k].value for k in needed[1:-1])
        tolerance=3.0 if scale==1 else .005
        if abs(expected-q['operating_profit'].value)<=tolerance:
            for name in needed:q[name].correction_reason='会计恒等式重算一致；尚未经人工核对'
    return list(result.values())


def margin_series(metrics):
    periods={}
    for m in metrics:
        if m.frequency=='quarter':periods.setdefault(m.period,{})[m.name]=m
    rows=[]
    for period,items in sorted(periods.items()):
        revenue=items.get('revenue');op=items.get('operating_profit')
        if not revenue or not revenue.value:continue
        row={'period':period,'revenue':revenue.value,'operating_margin':op.value/revenue.value if op else None,
             'sources':[revenue.citation.model_dump()]+([op.citation.model_dump()] if op else [])}
        for name in ('cost_of_revenue','sales_marketing','general_admin','research_development'):
            row[name+'_rate']=items[name].value/revenue.value if name in items else None
        rows.append(row)
    for index,row in enumerate(rows):
        prior=next((r for r in rows[:index] if r['period']==str(int(row['period'][:4])-1)+row['period'][4:]),None)
        row['yoy_revenue']=row['revenue']/prior['revenue']-1 if prior and prior['revenue'] else None
        row['margin_change_pp']=(row['operating_margin']-prior['operating_margin'])*100 if prior and row['operating_margin'] is not None and prior['operating_margin'] is not None else None
    return rows


def disclosure_checks(documents):
    observations={}
    for doc in sorted(documents,key=lambda d:d.available_at):
        for m in extract_pdd_metrics(doc):
            key=(m.name,m.period,m.unit,m.frequency)
            observations.setdefault(key,[]).append({'value':m.value,'source_title':doc.title,'available_at':doc.available_at,'citation':m.citation.model_dump(),'label':m.label})
    result=[]
    for (name,period,unit,frequency),items in observations.items():
        tolerance=1.1 if unit=='RMB_mn' else .011
        if len(items)>1 and max(v['value'] for v in items)-min(v['value'] for v in items)>tolerance:
            result.append({'id':digest([name,period,items])[:16],'name':name,'label':items[0]['label'],'period':period,'unit':unit,'frequency':frequency,
                'observations':items,'status':'needs_review','message':'同口径资料出现不同披露值；需要核对修订、归属和原文，不能静默当作同一历史值。'})
    return result
