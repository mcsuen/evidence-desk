"""Source adapters and deterministic acquisition checks, shared by Wiki jobs."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from selectolax.parser import HTMLParser
from pitr.desk.storage import digest
from .discovery import FetchError

PDD_HOSTS = {'investor.pddholdings.com', 'pinduoduo.gcs-web.com'}
REGULATORS = {'www.sec.gov', 'data.sec.gov', 'ec.europa.eu', 'digital-strategy.ec.europa.eu'}
STATISTICS = {'www.stats.gov.cn', 'stats.gov.cn', 'www.cncic.org'}


def normalize_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), p.query, ''))


def alternative_candidates(candidate, raw=None, base=None):
    """Known public publication routes are leads, still subject to body checks."""
    from pitr.desk.sources import pdd_news_url, pdd_pdf_links
    url = base or candidate['url']
    parsed = urlsplit(url)
    links = []
    ec = re.fullmatch(r'/commission/presscorner/detail/([a-z]{2})/([a-z]+_\d+_\d+)', parsed.path, re.I)
    if parsed.hostname == 'ec.europa.eu' and ec:
        lang, ref = ec.groups()
        links.append((f'https://ec.europa.eu/commission/presscorner/api/files/document/print/{lang.lower()}/{ref.lower()}/{ref.upper()}_{lang.upper()}.pdf', 'official_print_endpoint'))
    if parsed.hostname in PDD_HOSTS:
        if raw is not None and not raw.startswith(b'%PDF'):
            links += [(u, 'issuer_document_link') for u in pdd_pdf_links(raw, url)]
        if '/static-files/' in parsed.path and re.fullmatch(r'20\d{2}Q[1-4]', candidate.get('period', '')):
            links.append((pdd_news_url(candidate['period']), 'issuer_quarter_route'))
    return [{**candidate, 'url': link, 'alternative_of': candidate['url'],
             'original_url': candidate.get('original_url') or candidate['url'],
             'discovery_basis': basis, 'rationale': '原入口未取得正文，尝试发行方同一发布的公开版本'}
            for link, basis in links if normalize_url(link) != normalize_url(candidate['url'])]


def check_payload(raw, media):
    if 'html' in media or b'<html' in raw[:1000].lower() or b'<!doctype' in raw[:1000].lower():
        tree = HTMLParser(raw)
        title = tree.css_first('title')
        heading = tree.css_first('h1')
        label = ' '.join(n.text() for n in (title, heading) if n)
        if re.search(r'access denied|just a moment|verify you are human|sign in|log in|page not found|访问被拒绝|请登录', label, re.I):
            raise FetchError('取得了访问拦截、登录或错误页面，不能作为资料正文', kind='access_denied', phase='content')
    if 'pdf' in media.lower() and not raw.startswith(b'%PDF'):
        raise FetchError('响应声明为 PDF，但原件不是 PDF 文件', kind='invalid_content', phase='content')


def validate_original(doc, candidate, official):
    text = '\n'.join(b.text for b in doc.blocks)
    if len(text.strip()) < 100 or not doc.blocks or '\ufffd' in text[:6000]:
        raise FetchError('正文为空、过短或编码异常，保留原件待处理', kind='body_unavailable', phase='parse', next_action='parse_or_alternative')
    if doc.media_type == 'text/html' and re.search(r'access denied|just a moment|verify you are human', text[:300], re.I):
        raise FetchError('取得了访问拦截页面，不能作为资料正文', kind='access_denied', phase='content')
    header = text[:12000]
    quarter = re.search(r'(first|second|third|fourth)\s+quarter\s+(20\d{2})', header, re.I)
    annual = re.search(r'(?:fiscal\s+)?year\s+ended\s+(?:December\s+31,?\s*|31\s+December\s+)(20\d{2})', header, re.I)
    period = quarter[2] + 'Q' + str(['first','second','third','fourth'].index(quarter[1].lower()) + 1) if quarter else annual[1] + 'FY' if annual else ''
    declared = candidate.get('period', '')
    if official and period and declared and period != declared:
        raise FetchError(f'正文披露期间 {period} 与候选期间 {declared} 冲突，不能用于该期知识', kind='period_conflict', phase='quality', next_action='review_source')
    if candidate.get('discovery_basis') == 'official_print_endpoint':
        # A returned PDF may still be a generic notice or a wrong document.
        words = re.findall(r'[a-z]{4,}', candidate.get('title', '').lower())
        if words and sum(w in header.lower() for w in words) / len(words) < .6:
            raise FetchError('官方替代文件标题与候选发布不一致', kind='title_conflict', phase='quality', next_action='review_source')
        subject = candidate.get('subject', '')
        if subject and subject.casefold() not in header.casefold():
            raise FetchError('官方替代文件未确认候选主体', kind='identity_conflict', phase='quality', next_action='review_source')
    return period, text


def provenance(candidate, final_url, raw, sha, subject, observed_period, text):
    """Keep claimed provenance separate from publisher links that we can inspect."""
    original = candidate.get('original_url') or final_url
    relation = 'declared' if normalize_url(original) != normalize_url(final_url) else 'original'
    if relation == 'declared' and not raw.startswith(b'%PDF'):
        links = {normalize_url(urljoin(final_url, n.attributes.get('href', ''))) for n in HTMLParser(raw).css('a[href]')}
        if normalize_url(original) in links:
            relation = 'linked_original'
    host = urlsplit(final_url).hostname
    ec = re.search(r'/presscorner/(?:detail/[a-z]{2}/|api/files/document/print/[a-z]{2}/)([a-z]+_\d+_\d+)', final_url, re.I)
    if host == 'ec.europa.eu' and ec:
        key = ['ec-press-release', ec[1].lower()]
        relation = 'publisher_version'
    elif host in PDD_HOSTS and observed_period and 'financial results' in text[:6000].lower():
        key = ['pdd-earnings-release', subject, observed_period]
        relation = 'publisher_version'
    elif host in PDD_HOSTS and observed_period.endswith('FY'):
        # A catalog is a discovery location, not one publication shared by all
        # fiscal years. Keep annual reports separate while grouping their formats.
        key = ['pdd-annual-report', subject, observed_period]
        relation = 'publisher_version'
    elif original != final_url:
        # Conservatively group a declared reprint, never count it as independent
        # confirmation. The relation remains explicitly unverified when unlinked.
        key = ['publication-url', normalize_url(original)]
    else:
        key = ['publication-url', normalize_url(final_url)]
    return {'origin_group': digest(key), 'content_group': digest(['public-bytes', sha]),
            'original_url': original, 'retrieved_url': final_url, 'origin_relation': relation,
            'alternative_of': candidate.get('alternative_of', ''), 'discovery_basis': candidate.get('discovery_basis', '')}


def coverage_for(needs, materials):
    acquired = [m for m in materials if m.get('source_id')]
    for need in needs:
        matches = [m for m in acquired if
                   (need.get('period') and m.get('observed_period') == need['period'] and m.get('period_check') == 'matched_original' and m.get('provider') == 'official' and m.get('is_subject')) or
                   (not need.get('period') and need['id'] in m.get('supported_needs', []))]
        need.update(source_ids=sorted({m['source_id'] for m in matches}), status='materials_found' if matches else 'gap')
    return needs


def supported_needs(candidate, text, provider):
    terms = {'business': r'business|revenue|operating|e-commerce|业务|营收|营业|经营',
             'competition': r'competit|peer|竞争|同业', 'risk': r'risk|uncertain|regulat|风险|不确定|监管',
             'industry': r'industry|retail|market|statistics|行业|零售|统计|市场',
             'media': r'.'}
    # This proves topical presence in the acquired body, not semantic support for
    # an LLM claim. Source citations and human adoption still perform that check.
    needs = set(candidate.get('needs', [])) | ({provider} if provider in ('industry', 'media') else set())
    return [n for n in sorted(needs) if n in terms and re.search(terms[n], text, re.I) and
            (n not in ('industry', 'media') or provider == n)]
