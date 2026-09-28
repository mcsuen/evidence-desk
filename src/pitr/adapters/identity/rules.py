"""Market-specific symbols and one source policy for every execution surface."""
import re
import unicodedata
from functools import lru_cache
from opencc import OpenCC
from urllib.parse import urlsplit

REGULATORS = ('sec.gov', 'hkexnews.hk', 'hkex.com.hk', 'sse.com.cn', 'szse.cn', 'bse.cn', 'cninfo.com.cn', 'nasdaq.com', 'nyse.com')
POLICY_VERSION = 'source-trust.2'
_chinese = OpenCC('t2s')


def official_host(url):
    p = urlsplit(url)
    return p.scheme == 'https' and any(p.hostname == h or (p.hostname or '').endswith('.' + h) for h in REGULATORS)


def security_key(security):
    market = (security.get('market') or security.get('exchange', '')).upper().strip()
    market = {'SEHK':'HKEX', 'HK':'HKEX', 'HKG':'HKEX', 'XHKG':'HKEX', 'SH':'SSE', 'SHSE':'SSE', 'XSHG':'SSE',
              'SZ':'SZSE', 'XSHE':'SZSE', 'BJ':'BSE', 'XBSE':'BSE', 'XNAS':'NASDAQ', 'XNYS':'NYSE'}.get(market, market)
    full=re.sub(r'[^\w]','',market)
    full=re.sub(r'^(?:MAINBOARDOF|GROWTHENTERPRISEMARKETOF|GEMOF)(?=THESTOCKEXCHANGEOFHONGKONG)', '',full)
    names={
        'THESTOCKEXCHANGEOFHONGKONGLIMITED':'HKEX','STOCKEXCHANGEOFHONGKONGLIMITED':'HKEX','HONGKONGSTOCKEXCHANGE':'HKEX','HKSE':'HKEX',
        '香港联合交易所有限公司':'HKEX','香港聯合交易所有限公司':'HKEX','香港联交所':'HKEX','香港聯交所':'HKEX','香港交易所':'HKEX',
        '香港联合交易所':'HKEX','香港聯合交易所':'HKEX','STOCKEXCHANGEOFHONGKONG':'HKEX','THESTOCKEXCHANGEOFHONGKONG':'HKEX',
        'SHANGHAISTOCKEXCHANGE':'SSE','上海证券交易所':'SSE','上海證券交易所':'SSE','上交所':'SSE',
        'SHENZHENSTOCKEXCHANGE':'SZSE','深圳证券交易所':'SZSE','深圳證券交易所':'SZSE','深交所':'SZSE',
        'BEIJINGSTOCKEXCHANGE':'BSE','北京证券交易所':'BSE','北京證券交易所':'BSE','北交所':'BSE',
        'NEWYORKSTOCKEXCHANGE':'NYSE','NYSEAMERICAN':'AMEX','THENEWYORKSTOCKEXCHANGE':'NYSE',
        'THENASDAQSTOCKMARKETLLC':'NASDAQ','NASDAQSTOCKMARKETLLC':'NASDAQ','NASDAQGLOBALSELECTMARKET':'NASDAQ','NASDAQGLOBALMARKET':'NASDAQ','NASDAQCAPITALMARKET':'NASDAQ',
    }
    market=names.get(full,market)
    code = unicodedata.normalize('NFKC', security.get('code') or security.get('ticker', '')).upper().strip()
    suffixes = {'HKEX':('.HK',), 'SSE':('.SH','.SS'), 'SZSE':('.SZ',), 'BSE':('.BJ',)}
    for suffix in suffixes.get(market, ()):
        if code.endswith(suffix): code = code[:-len(suffix)]
    if market == 'HKEX' and code.isdigit(): code = str(int(code))
    if market in ('SSE','SZSE','BSE') and code.isdigit(): code = code.zfill(6)
    return market, code


@lru_cache(maxsize=2048)
def name_key(name):
    # Orthographic variants are comparable; translation and corporate relationships
    # still require evidence. Remove layout spaces before phrase conversion.
    value=re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', name).casefold())
    return _chinese.convert(value)


def clean_name(name):
    return re.sub(r'^(?:候选(?:公司)?|待核实|未核实)\s*[:：]\s*', '', name).strip()


def directory_name_key(name,market):
    """Compare an official short name, without discarding business/group words."""
    name=unicodedata.normalize('NFKC',name)
    if market=='HKEX':name=re.sub(r'-(?:SW|SS|W|S|B|R)$','',name.strip(),flags=re.I)
    key=name_key(name)
    return re.sub(r'(?:股份有限公司|有限责任公司|有限公司|corporation|incorporated|limited|corp|ltd|inc)$','',key)


def name_hints(name):
    # Historical understanding may have joined bilingual names for display.
    # Fragments remain discovery clues and must match an official directory.
    return list(dict.fromkeys([name,*re.split(r'\s+[·/|]\s+',name)]))


def directory_query_name(name):
    return re.sub(r'(?:股份有限公司|有限责任公司|有限公司|(?:Co[.,]?\s*)?(?:Limited|Ltd\.?)|Corporation|Incorporated|Corp\.?|Inc\.?)$','',name.strip(),flags=re.I).strip(' ,.')


def security_type_key(value):
    key=re.sub(r'[\s_-]','',value or '').lower()
    groups={'ordinary_share':('ordinaryshare','ordinaryshares','commonstock','commonshares','equity','股票','普通股','a股','h股'),
            'adr':('adr','ads','americandepositaryshares','americandepositaryreceipts'),
            'preferred_share':('preferredshare','preferredstock','优先股'),
            'warrant':('warrant','warrants','权证','認股權證'),'bond':('bond','bonds','debt','notes','债券','債券'),
            'fund':('fund','etf','基金')}
    return next((kind for kind,names in groups.items() if key in names),'unknown' if key in ('','unknown') else value)


def date_in_quote(value, quote):
    from datetime import date
    try:d=date.fromisoformat(value)
    except (ValueError,TypeError):return False
    # Official English filings use dates such as "24th January, 2008".
    # Normalize only date typography; do not infer a missing effective date.
    compact=re.sub(r'[,\s]','',re.sub(r'(?<=\d)(?:st|nd|rd|th)\b','',quote,flags=re.I)).casefold()
    variants=[value,f'{d.year}/{d.month}/{d.day}',d.strftime('%Y/%m/%d')]
    variants.extend(f'{d.year}年{month}月{day}日' for month in (str(d.month),f'{d.month:02}') for day in (str(d.day),f'{d.day:02}'))
    for month in (d.strftime('%B'),d.strftime('%b')):
        for day in (str(d.day),f'{d.day:02}'):
            variants.extend((f'{month}{day}{d.year}',f'{day}{month}{d.year}'))
    return any(v.casefold() in compact for v in variants)
