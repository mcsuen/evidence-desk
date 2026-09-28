"""Read original bytes without assigning truth or historical availability."""
from __future__ import annotations

import io
import re
from selectolax.parser import HTMLParser

from pitr.domain.common import digest
from pitr.domain.contracts import SourceBlock


def _parse(raw: bytes, media: str):
    if not raw or len(raw) > 40_000_000:
        raise ValueError('原件必须非空且不超过 40 MB')
    blocks, issues, pages, title = [], [], 0, ''
    if raw.startswith(b'%PDF'):
        import pdfplumber
        media = 'application/pdf'
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            pages = len(pdf.pages)
            if pages > 1500:
                raise ValueError('PDF 页数超过限制，请拆分材料')
            for index, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ''
                blocks.append(SourceBlock(id=f'page-{index}', text=text, page=index))
                if not text.strip():
                    issues.append(f'第 {index} 页没有文本层，需要读取页面图像')
    elif 'html' in media or b'<html' in raw[:1000].lower() or b'<!doctype' in raw[:1000].lower():
        media = 'text/html'
        tree = HTMLParser(raw)
        if tree.css_first('title'):
            title = tree.css_first('title').text(strip=True)
        if re.search(r'access denied|just a moment|request (?:blocked|rate)|访问被拒绝|人机验证',title,re.I):
            raise ValueError('取得的是访问拦截或人机验证页面，不能保存为披露原件')
        for node in tree.css('script,style,nav,header,footer,noscript,iframe,form'):
            node.decompose()
        for index, node in enumerate(tree.css('p,h1,h2,h3,h4,h5,table')):
            if node.parent and node.parent.tag in ('td', 'th'):
                continue
            if node.tag == 'table':
                rows = [[c.text(separator=' ', strip=True) for c in row.css('th,td')] for row in node.css('tr')]
                text = '\n'.join(' | '.join(row) for row in rows)
            else:
                text = node.text(separator=' ', strip=True)
            if text.strip():
                blocks.append(SourceBlock(id=f'block-{index}', text=text))
        if not blocks and tree.body:
            blocks.append(SourceBlock(id='body', text=tree.body.text(separator='\n', strip=True)))
    else:
        if media not in ('text/plain', 'text/markdown', 'application/octet-stream'):
            raise ValueError('支持 PDF、HTML、UTF-8 TXT 和 Markdown 原件')
        text = raw.decode('utf-8')
        media = 'text/markdown' if media == 'text/markdown' else 'text/plain'
        blocks = [SourceBlock(id=f'paragraph-{i}', text=t.strip())
                  for i, t in enumerate(re.split(r'\n\s*\n', text)) if t.strip()]
    if sum(len(b.text) for b in blocks) > 12_000_000:
        raise ValueError('原件文本超过限制，请拆分材料')
    text = '\n'.join(b.text for b in blocks)
    return {'blocks': blocks, 'issues': issues, 'page_count': pages, 'media_type': media,
            'title': title or (text.splitlines() or ['原件'])[0][:180],
            'origin_group': digest(re.sub(r'\s+', ' ', text))[:24]}


def _tables(raw, page):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        if not 1 <= page <= len(pdf.pages):
            raise ValueError('页码超出范围')
        return [{'index': i, 'cells': table.extract(), 'bbox': list(table.bbox)}
                for i, table in enumerate(pdf.pages[page - 1].find_tables())]


def _render_page(raw, page, dpi=130):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        if not 1 <= page <= len(pdf.pages):
            raise ValueError('页码超出范围')
        output = io.BytesIO()
        pdf.pages[page - 1].to_image(resolution=dpi).original.save(output, format='PNG')
        return output.getvalue()


def _worker(operation,raw,**arguments):
    import base64,json,subprocess,sys
    request=json.dumps({'operation':operation,'raw':base64.b64encode(raw).decode(),**arguments})
    process=subprocess.run([sys.executable,'-m','pitr.adapters.document_worker'],input=request,capture_output=True,text=True,timeout=90)
    if process.returncode:raise ValueError('原件解析失败：'+process.stderr[-1000:])
    value=json.loads(process.stdout)
    if 'error' in value:raise ValueError(value['error'])
    return value['result']


def parse(raw:bytes,media:str):
    if raw.startswith(b'%PDF'):
        if len(raw)>40_000_000:raise ValueError('PDF 超过 40 MB')
        result=_worker('parse',raw,media=media)
        result['blocks']=[SourceBlock.model_validate(b) for b in result['blocks']]
        return result
    return _parse(raw,media)


def tables(raw,page):return _worker('tables',raw,page=page)


def render_page(raw,page,dpi=130):
    import base64
    return base64.b64decode(_worker('render',raw,page=page,dpi=dpi))
