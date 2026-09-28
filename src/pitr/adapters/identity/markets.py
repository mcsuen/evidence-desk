"""Official market directories. Their rows are discovery leads, never issuer proof."""
import json
import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode, urljoin
from selectolax.parser import HTMLParser
from .rules import security_key, name_key,directory_name_key,directory_query_name,name_hints


def xlsx_records(raw):
    """Read the exchange's full company export, with bounded XML expansion."""
    import io,zipfile,xml.etree.ElementTree as ET
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(i.file_size for i in archive.infolist())>50_000_000:raise ValueError('交易所公司目录展开后超过限额')
        strings=[''.join(x.itertext()) for x in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si',ns)] if 'xl/sharedStrings.xml' in archive.namelist() else []
        rows=[]
        for row in ET.fromstring(archive.read('xl/worksheets/sheet1.xml')).findall('.//m:row',ns):
            cells={}
            for cell in row:
                key=re.sub(r'\d','',cell.attrib['r']);kind=cell.attrib.get('t')
                value=cell.findtext('m:v',default='',namespaces=ns)
                cells[key]=strings[int(value)] if kind=='s' else ''.join(cell.itertext()) if kind=='inlineStr' else value
            rows.append(cells)
        if not rows:raise ValueError('交易所公司目录没有表头')
        headers=rows[0]
        return [{label:row.get(col,'') for col,label in headers.items()} for row in rows[1:]]


@dataclass
class Candidate:
    name: str
    market: str
    code: str
    identifiers: dict = field(default_factory=dict)
    source: str = ''
    aliases: list = field(default_factory=list)
    security_type: str = 'unknown'
    historical_names: list = field(default_factory=list)
    alias_sources: dict = field(default_factory=dict)
    source_receipts: list = field(default_factory=list)


@dataclass
class Disclosure:
    url: str
    title: str
    market: str
    document_type: str = 'other'
    published_at: str = ''
    period: str = ''
    source: str = ''


def document_type(title):
    if re.search(r'monthly returns?|(?:证券|證券).{0,20}(?:变动|變動).{0,5}月(?:报|報)表',title,re.I): return 'listing_return'
    if re.search(r'(?:supplemental|supplementary|clarification)\s+announcement|(?:in\s+relation\s+to|regarding).{0,40}(?:annual|interim|quarterly)\s+report|(?:年度|半年度|中期|季度)报告.{0,20}(?:补充|更正|说明)公告|(?:補充|澄清).{0,30}(?:公告|公佈)',title,re.I|re.S): return 'other'
    # A title referring to a report is not necessarily that report. These are
    # issuer communications and updates about disclosure, not statement originals.
    if re.search(r'notification\s+letter|letter\s+to.{0,45}shareholders?|notice\s+of\s+(?:publication|availability)|(?:electronic\s+)?dissemination\s+of\s+corporate\s+communications|updates?\s+on.{0,100}(?:annual\s+report|interim\s+report|disclaimer|audit\s+opinion)|(?:寄发|寄發|刊发|刊發|发布|發布).{0,35}(?:报告|報告|年报|年報).{0,25}(?:通知|通告)|(?:致|致函).{0,25}股东|(?:致|致函).{0,25}股東|公司通訊|公司通讯',title,re.I|re.S): return 'other'
    # Forward-looking estimates and transaction outcomes are not published
    # financial results, even when their titles contain "results" or a period.
    if re.search(r'(?:estimated|forecast|projected|expected).{0,30}(?:results|earnings)|(?:results|earnings).{0,30}(?:estimate|forecast)|profit\s+(?:warning|alert|forecast)|positive\s+profit\s+alert|(?:业绩|業績|盈利).{0,8}(?:预告|預告|预测|預測|预警|預警)|盈警|盈喜',title,re.I|re.S): return 'earnings_forecast'
    if re.search(r'allotment results|allocation results|(?:配售|分配|招股).{0,12}(?:結果|结果)|offer price|业绩快报|業績快報',title,re.I|re.S): return 'other'
    if re.search(r'(?:delay|postponement|postponed).{0,100}(?:publication|publishing|despatch|dispatch|release)|(?:publication|release).{0,60}(?:delay|postpon)|(?:延遲|延迟|延期|延誤|延误).{0,30}(?:刊發|刊发|披露|發布|发布|寄發|寄发)|board meeting|meeting of the board',title,re.I|re.S): return 'other'
    if re.search(r'说明会|說明會|预约|預約|董事会|董事會|会议|會議|提示性|摘要|summary|poll results|general meeting|repurchase|voting results',title,re.I): return 'other'
    if re.search(r'interim report|中期报告|中期報告|半年度报告',title,re.I): return 'interim_report'
    if re.search(r'\b(?:10-K|20-F|40-F)\b|annual report|年度报告|年報',title,re.I): return 'annual_report'
    if re.search(r'\b10-Q\b|季度报告|季度報告',title,re.I): return 'quarterly_report'
    if re.search(r'(?:annual|interim|quarterly|financial|final).{0,30}results|results.{0,80}(?:year|quarter|months?).{0,30}ended|(?:年度|中期|季度|财务|財務|全年|半年).{0,30}(?:业绩|業績)',title,re.I|re.S): return 'results'
    if re.search(r'notice|通知|公告|change.*name',title,re.I): return 'identity_notice'
    return 'other'


class HKEX:
    name = 'HKEX'
    markets = ('HKEX',)
    configuration = ()

    def find_candidates(self, name, securities, acquire):
        codes = [c for m,c in map(security_key,securities) if m=='HKEX']
        query = codes[0].zfill(5) if codes else name
        url = 'https://www1.hkexnews.hk/search/prefix.do?' + urlencode(dict(lang='EN' if query.isascii() else 'ZH',type='A',name=query,market='SEHK',callback='callback'))
        raw = acquire(url)
        text = raw.decode('utf-8-sig').strip()
        match = re.fullmatch(r'callback\((.*)\);?',text,re.S)
        value = json.loads(match[1] if match else text)
        rows = value.get('stockInfo',[])
        shorter=directory_query_name(name)
        if not rows and not codes and shorter!=name:
            url='https://www1.hkexnews.hk/search/prefix.do?'+urlencode(dict(lang='EN' if shorter.isascii() else 'ZH',type='A',name=shorter,market='SEHK',callback='callback'))
            rows=official_json(acquire(url)).get('stockInfo',[])
        if codes: rows = [r for r in rows if str(int(r['code'])) in codes]
        else:
            exact = [r for r in rows if directory_name_key(r['name'],'HKEX')==directory_name_key(name,'HKEX')]
            rows = exact or rows
        candidates=[Candidate(r['name'],'HKEX',str(int(r['code'])),{'HKEX':str(r['stockId'])},url) for r in rows[:8]]
        # The exchange's bilingual short names share the same actual stockId.
        # Never infer a Chinese translation from a model's English search result.
        if candidates:
            other_lang='ZH' if query.isascii() else 'EN'
            other_url='https://www1.hkexnews.hk/search/prefix.do?'+urlencode(dict(lang=other_lang,type='A',name=candidates[0].code.zfill(5),market='SEHK',callback='callback'))
            other=official_json(acquire(other_url)).get('stockInfo',[])
            for c in candidates:
                c.aliases=[r['name'] for r in other if str(r['stockId'])==c.identifiers['HKEX'] and str(int(r['code']))==c.code and r['name']!=c.name]
                c.alias_sources={n:other_url for n in c.aliases}
        return candidates

    def list_disclosures(self, candidate, acquire, as_of=None):
        url = 'https://www1.hkexnews.hk/search/titlesearch.xhtml?' + urlencode(dict(category=0,market='SEHK',stockId=candidate.identifiers['HKEX']))
        tree = HTMLParser(acquire(url)); rows=[]
        for n in tree.css('a[href]'):
            link = urljoin(url,n.attributes['href']); title = n.text(strip=True)
            match = re.search(r'/listedco/listconews/(?:sehk|gem)/(\d{4})/(\d{2})(\d{2})/[^/]+\.pdf$',link,re.I)
            if not match: continue
            date = '-'.join(match.groups())
            if as_of and date>as_of[:10]: continue
            rows.append(Disclosure(link,title,'HKEX',document_type(title),date,source=url))
        return sorted({r.url:r for r in rows}.values(),key=lambda r:r.published_at,reverse=True)


class SEC:
    name = 'SEC'
    markets = ('NASDAQ','NYSE','AMEX','US')
    configuration = ('sec_user_agent',)

    def find_candidates(self, name, securities, acquire):
        url = 'https://www.sec.gov/files/company_tickers_exchange.json'
        value = json.loads(acquire(url)); rows=[dict(zip(value['fields'],r)) for r in value['data']]
        keys = {security_key(s) for s in securities}
        codes = {c for m,c in keys if m in self.markets}
        if codes: rows = [r for r in rows if r['ticker'].upper() in codes and any(m in ('US',security_key({'exchange':r['exchange']})[0]) and c==r['ticker'].upper() for m,c in keys)]
        else:
            exact = [r for r in rows if directory_name_key(r['name'],'US')==directory_name_key(name,'US')]
            rows = exact or [r for r in rows if name_key(name) in name_key(r['name'])]
        return [Candidate(r['name'],security_key({'exchange':r['exchange']})[0],r['ticker'],{'SEC':str(r['cik']).zfill(10)},url) for r in rows[:8]]

    def list_disclosures(self, candidate, acquire, as_of=None):
        cik = candidate.identifiers['SEC']
        url = f'https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json'
        raw=acquire(url);value = json.loads(raw); recent = value.get('filings',{}).get('recent',{})
        candidate.historical_names=[{'name':r['name'],'valid_from':r.get('from'),'valid_to':r.get('to'),
            'url':url,'digest':hashlib.sha256(raw).hexdigest(),'pointer':f'/formerNames/{i}'}
            for i,r in enumerate(value.get('formerNames',[])) if r.get('name')]
        rows = [recent]
        # Query older official directory pages when a historical cutoff requires them.
        for page in value.get('filings',{}).get('files',[]):
            if as_of and page.get('filingFrom','')<=as_of[:10] and (not recent.get('filingDate') or min(recent['filingDate'])>as_of[:10]):
                rows.append(json.loads(acquire('https://data.sec.gov/submissions/'+page['name'])))
        found=[]
        for data in rows:
            for i, form in enumerate(data.get('form',[])):
                if form not in ('10-K','10-Q','20-F','40-F','6-K','8-K'): continue
                date=data['filingDate'][i]
                if as_of and date>as_of[:10]: continue
                accession=data['accessionNumber'][i].replace('-',''); primary=data['primaryDocument'][i]
                if not re.fullmatch(r'\d+',accession) or not re.fullmatch(r'[A-Za-z0-9_.-]+',primary): continue
                link=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{primary}'
                period=data.get('reportDate',['']*len(data['form']))[i]
                found.append(Disclosure(link,form+' '+period,candidate.market,document_type(form),date,period,source=url))
        found.sort(key=lambda r:r.published_at,reverse=True)
        # A 6-K/8-K can be an unrelated event. Follow actual exhibit links only
        # when the filing itself identifies financial results.
        for filing in [d for d in found if d.document_type=='other'][:3]:
            try:tree=HTMLParser(acquire(filing.url))
            except Exception as error:
                from pitr.domain.common import Conflict
                if isinstance(error,(Conflict,TimeoutError)):raise
                continue
            body=tree.text(separator=' ',strip=True)
            if not re.search(r'results of operations|financial results|quarter.{0,60}results|results.{0,60}quarter',body,re.I):continue
            if re.search(r'consolidated.{0,60}(income|operations)|total revenues|net revenues',body,re.I):
                filing.document_type='results'
            for node in tree.css('a[href]'):
                href=node.attributes['href'];label=node.text(strip=True)
                if not re.search(r'ex(?:hibit)?[\s_-]*99|press release|earnings|financial results',href+' '+label,re.I):continue
                link=urljoin(filing.url,href)
                if link.rsplit('/',1)[0]!=filing.url.rsplit('/',1)[0]:continue
                found.append(Disclosure(link,'Financial results exhibit: '+label,candidate.market,'results',filing.published_at,filing.period,source=filing.url))
        return sorted({d.url:d for d in found}.values(),key=lambda r:r.published_at,reverse=True)


def official_json(raw):
    from pitr.adapters.public_fetch import FetchError
    text=raw.decode('utf-8-sig').strip()
    wrapped=re.fullmatch(r'(?:[\w.]+)?\((.*)\);?',text,re.S)
    value=json.loads(wrapped[1] if wrapped else text)
    if isinstance(value,dict) and (value.get('error') or value.get('success') in (False,'false')):
        raise FetchError(str(value.get('error') or '官方目录返回业务错误'),kind='directory_unavailable',phase='discovery',retryable=True)
    return value


class SSE:
    name='SSE'
    markets=('SSE',)
    configuration=()

    def find_candidates(self,name,securities,acquire):
        codes=[c for m,c in map(security_key,securities) if m=='SSE']
        params={'sqlId':'COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L','STOCK_TYPE':'1,8','STOCK_CODE':codes[0] if codes else name,
            'COMPANY_STATUS':'2,4,5,7,8','type':'inParams','isPagination':'true','pageHelp.pageSize':100,
            'pageHelp.pageNo':1,'pageHelp.beginPage':1,'pageHelp.cacheSize':1,'jsonCallBack':'callback'}
        url='https://query.sse.com.cn/sseQuery/commonQuery.do?'+urlencode(params)
        rows=official_json(acquire(url)).get('result') or [];origins={}
        if not rows and not codes:
            # STOCK_CODE searches the security label, not the full legal name.
            # Read the complete official directory before declaring no candidate.
            params.update(STOCK_CODE='',**{'pageHelp.pageSize':2000})
            all_rows=[];page=1
            while True:
                params.update({'pageHelp.pageNo':page,'pageHelp.beginPage':page})
                url='https://query.sse.com.cn/sseQuery/commonQuery.do?'+urlencode(params)
                data=official_json(acquire(url));page_rows=data.get('result') or [];all_rows.extend(page_rows)
                origins.update({r['A_STOCK_CODE']:url for r in page_rows if r.get('A_STOCK_CODE')})
                pages=int(data.get('pageHelp',{}).get('pageCount',1))
                if page>=pages:break
                if page>=20:raise ValueError('上交所目录尚未完整读取，不能据此认定查无公司')
                page+=1
            wanted={directory_name_key(h,'SSE') for h in name_hints(name)}-{''}
            rows=[r for r in all_rows if wanted & {directory_name_key(r.get(k) or '','SSE') for k in ('FULL_NAME','SEC_NAME_CN','FULL_NAME_IN_ENGLISH','COMPANY_ABBR_EN')}]
        return [Candidate(r.get('FULL_NAME') or r.get('SEC_NAME_FULL') or r['SEC_NAME_CN'],'SSE',r['A_STOCK_CODE'],
            {'SSE':r['COMPANY_CODE']},origins.get(r['A_STOCK_CODE'],url),aliases=list(filter(None,[r['SEC_NAME_CN'],r.get('FULL_NAME_IN_ENGLISH')])),security_type='ordinary_share') for r in rows if r.get('A_STOCK_CODE') and (not codes or r['A_STOCK_CODE'] in codes)]

    def list_disclosures(self,candidate,acquire,as_of=None):
        from datetime import datetime,timedelta
        end=(as_of or datetime.now().isoformat())[:10];start=(datetime.fromisoformat(end)-timedelta(days=730)).date().isoformat()
        url='https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do?'+urlencode({'SECURITY_CODE':candidate.code,
            'START_DATE':start,'END_DATE':end,'TITLE':'','BULLETIN_TYPE':'','isPagination':'true','pageHelp.pageSize':100,
            'pageHelp.pageNo':1,'pageHelp.beginPage':1,'pageHelp.endPage':1,'pageHelp.cacheSize':1,'jsonCallBack':'callback'})
        rows=official_json(acquire(url)).get('result',[])
        rows=[r for group in rows for r in (group if isinstance(group,list) else [group])]
        return [Disclosure(urljoin('https://static.sse.com.cn',r['URL']),r['TITLE'],'SSE',document_type(r['TITLE']),r.get('SSEDATE',''),source=url) for r in rows if r.get('URL')]


class SZSE:
    name='SZSE'
    markets=('SZSE',)
    configuration=()

    def find_candidates(self,name,securities,acquire):
        codes=[c for m,c in map(security_key,securities) if m=='SZSE']
        url='https://www.szse.cn/api/report/ShowReport/data?'+urlencode({'SHOWTYPE':'JSON','CATALOGID':'1110x','TABKEY':'tab1','txtDMorJC':codes[0] if codes else name})
        value=official_json(acquire(url))
        if not (value[0].get('data') or []) and not codes:
            # The JSON endpoint accepts only security codes/short names. Its
            # official full export includes legal Chinese and English names.
            url='https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110x&TABKEY=tab1'
            rows=xlsx_records(acquire(url))
            if rows and not {'公司全称','英文名称','A股代码'} <= rows[0].keys():raise ValueError('深交所公司目录表头已变化，不能据此认定查无公司')
            wanted={directory_name_key(h,'SZSE') for h in name_hints(name)}-{''}
            return [Candidate(r['公司全称'],'SZSE',r['A股代码'].zfill(6),{'SZSE':r['公司代码']},url,
                aliases=[r.get('公司简称',''),r.get('英文名称','')],security_type='ordinary_share') for r in rows if r.get('A股代码') and wanted & {directory_name_key(r.get(k,''),'SZSE') for k in ('公司全称','公司简称','英文名称')}]
        return [Candidate(r['gsqc'],'SZSE',r['zqdm'],{'SZSE':r['zqdm']},url,
            aliases=[HTMLParser(r['gsjc']).text(strip=True)],security_type='ordinary_share') for r in (value[0].get('data') or []) if not codes or r['zqdm'] in codes]

    def list_disclosures(self,candidate,acquire,as_of=None):
        from datetime import datetime,timedelta
        end=(as_of or datetime.now().isoformat())[:10];start=(datetime.fromisoformat(end)-timedelta(days=730)).date().isoformat()
        url='https://www.szse.cn/api/disc/announcement/annList'
        rows=[]
        for page in range(1,7):
            value=official_json(acquire(url,{'stock':[candidate.code],'seDate':[start,end],'channelCode':['listedNotice_disc'],'pageSize':50,'pageNum':page}))
            data=value.get('data',[]);rows.extend(data)
            if not data or len(rows)>=value.get('announceCount',len(rows)):break
            kinds={document_type(r['title']) for r in rows}
            if 'annual_report' in kinds and kinds.intersection(('interim_report','quarterly_report')):break
        return [Disclosure(urljoin('https://disc.static.szse.cn/',r['attachPath']),r['title'],'SZSE',document_type(r['title']),r.get('publishTime','')[:10],source=url)
            for r in rows if r.get('attachPath')]


class CNInfo:
    name='CNINFO'
    markets=('SSE','SZSE','BSE')
    configuration=()

    def find_candidates(self,name,securities,acquire):
        url='https://www.cninfo.com.cn/new/data/szse_stock.json'
        rows=official_json(acquire(url))['stockList']; keys={security_key(s) for s in securities}
        found=[]
        for row in rows:
            code=row['code'];label=row.get('zwjc') or row.get('orgName') or row.get('name','')
            if keys:
                markets=[m for m,c in keys if c==code and m in self.markets]
                if not markets:continue
                market=markets[0]
            else:
                if name_key(name) not in name_key(label) and name_key(label) not in name_key(name):continue
                market='SSE' if code.startswith('6') else 'SZSE' if code.startswith(('0','3')) else 'BSE' if code.startswith(('4','8','92')) else ''
                if not market:continue
            found.append(Candidate(label,market,code,{'CNINFO':row['orgId']},url))
        return found[:8]

    def list_disclosures(self,candidate,acquire,as_of=None):
        from datetime import datetime,timedelta,timezone
        end=(as_of or datetime.now().isoformat())[:10];start=(datetime.fromisoformat(end)-timedelta(days=730)).date().isoformat()
        url='https://www.cninfo.com.cn/new/hisAnnouncement/query'
        query={'pageNum':'1','pageSize':'30','column':'szse','tabName':'fulltext','plate':'',
            'stock':candidate.code+','+candidate.identifiers['CNINFO'],'searchkey':'','secid':'','category':'','trade':'',
            'seDate':start+'~'+end,'sortName':'','sortType':'','isHLtitle':'true'}
        rows=official_json(acquire(url,query)).get('announcements') or []
        found=[]
        for r in rows:
            if r.get('secCode')!=candidate.code or not r.get('adjunctUrl'):continue
            title=HTMLParser(r['announcementTitle']).text(strip=True)
            date=datetime.fromtimestamp(r['announcementTime']/1000,timezone(timedelta(hours=8))).date().isoformat()
            found.append(Disclosure(urljoin('https://static.cninfo.com.cn/',r['adjunctUrl']),title,candidate.market,document_type(title),date,source=url))
        return found


class BSE:
    name='BSE'
    markets=('BSE',)
    configuration=()

    def find_candidates(self,name,securities,acquire):
        codes=[c for m,c in map(security_key,securities) if m=='BSE']
        url='https://www.bse.cn/nqxxController/nqxxCnzq.do'
        value=official_json(acquire(url,{'page':'0','typejb':'T','xxfcbj[]':'2','xxzqdm':codes[0] if codes else name,'sortfield':'xxzqdm','sorttype':'asc'}))
        rows=value[0]['content'];found=[]
        for r in rows:
            code=r.get('xxzqdm');label=r.get('xxzqjc')
            if not code or not label:raise ValueError('北交所目录字段已变化，未把未知数据当作空候选')
            if (codes and code in codes) or (not codes and name_key(name) in name_key(label)):
                found.append(Candidate(label,'BSE',code,{},url,security_type='ordinary_share'))
        return found

    def list_disclosures(self,candidate,acquire,as_of=None):
        from datetime import datetime,timedelta
        end=(as_of or datetime.now().isoformat())[:10];start=(datetime.fromisoformat(end)-timedelta(days=730)).date().isoformat()
        url='https://www.bse.cn/disclosureInfoController/infoResult.do';found=[]
        for page in range(6):
            query={'disclosureType':'5','companyCd':candidate.code,'keyword':'','page':str(page),
                'startTime':start,'endTime':end,'sortfield':'publishDate','sorttype':'desc'}
            value=official_json(acquire(url,query))
            if not isinstance(value,list) or not value or 'listInfo' not in value[0]:
                raise ValueError('北交所公告目录结构已变化，未把未知数据当作空目录')
            info=value[0]['listInfo'];rows=info.get('content',[])
            for r in rows:
                if r.get('companyCd')!=candidate.code or not r.get('destFilePath'):continue
                title=r.get('disclosureTitle') or r.get('disclosurePostTitle','')
                date=str(r.get('publishDate',''))[:10]
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):continue
                if date>end:continue
                found.append(Disclosure(urljoin('https://www.bse.cn',r['destFilePath']),title,'BSE',document_type(title),date,source=url))
            if not rows or page+1>=info.get('totalPages',1):break
        # CNInfo is a separate adapter; its own errors and discovery receipts stay visible.
        return found


ADAPTERS = [HKEX(), SEC(), SSE(), SZSE(), BSE(), CNInfo()]


def adapters_for(securities):
    markets = {security_key(s)[0] for s in securities}
    return [a for a in ADAPTERS if not markets or markets.intersection(a.markets)]
