import io
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, urljoin
import xml.etree.ElementTree as ET
from selectolax.parser import HTMLParser


DEFAULT_SOURCES = [
    {'id': 'chinanews-finance', 'name': '中新网 · 财经', 'url': 'https://www.chinanews.com.cn/rss/finance.xml'},
    {'id': 'dw-business', 'name': 'DW · 经济', 'url': 'https://rss.dw.com/rdf/rss-en-bus'},
    {'id': 'fed', 'name': '美联储 · 公告', 'url': 'https://www.federalreserve.gov/feeds/press_all.xml'},
    {'id': 'ecb', 'name': '欧洲央行 · 公告', 'url': 'https://www.ecb.europa.eu/rss/press.html'},
    {'id': 'gdelt', 'name': 'GDELT · 全球发现', 'kind': 'gdelt', 'enabled': False, 'terms': ['semiconductor', 'tariff', 'ecommerce']},
]


def canonical_url(url):
    u = urlparse(url)
    if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password:
        raise ValueError('新闻地址必须是公开 HTTP(S) URL')
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunparse((u.scheme.lower(), u.netloc.lower(), u.path or '/', '', urlencode(sorted(query)), ''))


def timestamp(value):
    if not value: return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try: date = parsedate_to_datetime(value)
        except (ValueError, TypeError): return None
    return date.replace(tzinfo=date.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()


def html_text(raw):
    tree = HTMLParser(raw)
    for node in tree.css('script,style,nav,footer,header,aside,form'): node.decompose()
    # Prefer the publisher's actual article body. A page-wide fallback can mix
    # recommendations into a story and create spurious company matches.
    body = tree.css_first('[itemprop="articleBody"]') or tree.css_first('.left_zw')
    article = body or tree.css_first('article') or tree.css_first('main') or tree.body
    if not article: return tree.text(separator=' ', strip=True)
    parts = []
    nodes = article.css('p,h1,h2,h3,li')
    for node in nodes:
        value = node.text(separator=' ', strip=True)
        linked = sum(len(a.text(strip=True)) for a in node.css('a'))
        if not body and value and linked/len(value) > .5: continue
        parts.append(value)
    if nodes: return '\n\n'.join(dict.fromkeys(p for p in parts if p))
    return article.text(separator='\n', strip=True)


def extract(raw, media):
    if 'pdf' in media or raw.startswith(b'%PDF'):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            return '\n\n'.join(p.extract_text() or '' for p in pdf.pages)
    if 'html' in media or b'<html' in raw[:1000].lower(): return html_text(raw)
    return raw.decode('utf-8', errors='replace')


def feed_items(raw, base):
    if len(raw) > 4_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('订阅内容过大或含不支持的 XML 声明')
    root = ET.fromstring(raw)
    items = []
    for node in root.iter():
        if node.tag.split('}')[-1] not in ('item', 'entry'): continue
        fields = {}
        url = ''
        for child in node:
            key = child.tag.split('}')[-1]
            fields[key] = ''.join(child.itertext()).strip()
            if key == 'link' and child.attrib.get('rel', 'alternate') == 'alternate':
                url = child.attrib.get('href') or fields[key]
        if not url: continue
        try: url = canonical_url(urljoin(base, url))
        except ValueError: continue
        summary = fields.get('encoded') or fields.get('content') or fields.get('description') or fields.get('summary', '')
        items.append({'url': url, 'title': html_text(fields.get('title', '')),
                      'published_at': timestamp(fields.get('pubDate') or fields.get('published') or fields.get('updated') or fields.get('date')),
                      'excerpt': html_text(summary), 'publication_source': 'content'})
    return items


def list_items(source, station, fetch, since=''):
    if source.kind == 'rss':
        raw, _, final, _ = fetch(source.url)
        return feed_items(raw, final)
    if source.kind == 'gdelt':
        # Only user-configured public keywords leave this machine, never company profiles.
        terms = ['"'+t.replace('"', '').replace('(', '').replace(')', '')+'"' for t in source.terms]
        query = urlencode({'query': '('+' OR '.join(terms)+')', 'mode': 'artlist', 'format': 'json',
                           'maxrecords': 250, 'timespan': '24h', 'sort': 'datedesc'})
        raw, _, _, _ = fetch('https://api.gdeltproject.org/api/v2/doc/doc?'+query)
        return [{'url': canonical_url(a['url']), 'title': a['title'], 'published_at': None,
                 'excerpt': '', 'publication_source': 'content'} for a in json.loads(raw).get('articles', [])]
    from pitr.adapters.sources.protocol import adapter
    a = adapter(source.adapter)
    identity = station.store.get(source.company,'subject')
    subject = {'name':identity.name,'securities':[{'exchange':k,'ticker':v} for k,v in identity.identifiers.items()]}
    acquire = lambda url, query=None: fetch(url, **({'query': query} if query is not None else {}))
    candidates = a.find_candidates(subject, acquire)
    if not candidates: raise ValueError('公告目录未找到该公司')
    candidate = next((c for c in candidates if c.market in a.markets), candidates[0])
    from pitr.adapters.sources.time import publication_timestamp
    return [{'url': i.url, 'title': i.title, 'published_at': publication_timestamp(i), 'excerpt': '',
             'publication_source': i.publication_source} for i in a.list_items(candidate, acquire, since=since)]
