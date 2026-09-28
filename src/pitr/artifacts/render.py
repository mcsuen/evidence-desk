"""Project-owned rendering configuration; missing renderers never count as a pass."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile


def verify_text(pages, expected, revision):
    import re
    import unicodedata
    def normalize(value):
        return ''.join(unicodedata.normalize('NFKC',value).split()).replace('\u200b','').replace('\u00ad','')
    parts=[]
    for text in pages:
        text=re.sub(r'PITR\s*/\s*研究报告','',text)
        text=re.sub(r'修订\s*'+str(revision)+r'\s*[·•]\s*\d+\s*/\s*\d+','',text)
        parts.append(normalize(text))
    actual=''.join(parts)
    missing=[text for text in expected if normalize(text) not in actual]
    if missing:raise ValueError('PDF 正文或表格文字与报告不一致：'+repr(missing[:2])[:1200])
    return {'status':'passed','coverage':['rendered_body_and_table_text']}

ROOT = Path(__file__).resolve().parents[3]


def executable():
    configured = os.environ.get('PITR_SOFFICE')
    candidates = [configured] if configured else [
        ROOT / '.tools/libreoffice/LibreOffice.app/Contents/MacOS/soffice',
        '/Applications/LibreOffice.app/Contents/MacOS/soffice', '/usr/bin/libreoffice', '/usr/bin/soffice',
    ]
    return next((str(p) for p in candidates if p and Path(p).is_file()), None)


def doctor():
    from .fonts import available
    binary = executable()
    return {'word_compiler': True, 'renderer': {'available':bool(binary),'path':binary},
        'font': {'available':available(),'family':'Noto Sans CJK SC'},
        'setup': 'python scripts/setup_documents.py'}


def render(path, output):
    import pypdf
    import pypdfium2
    path, output = Path(path).resolve(), Path(output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    binary = executable()
    if not binary:
        raise RuntimeError('缺少 Word 渲染器，请运行 python scripts/setup_documents.py；本次导出可独立重试')
    if not doctor()['font']['available']:
        raise RuntimeError('缺少项目中文字体，请运行 python scripts/setup_documents.py')
    with tempfile.TemporaryDirectory(prefix='pitr-word-profile-') as profile:
        result=subprocess.run([binary,'-env:UserInstallation='+Path(profile).as_uri(), '--headless','--convert-to','pdf',
            '--outdir',str(output),str(path)],capture_output=True,text=True,timeout=150)
    pdf=output/(path.stem+'.pdf')
    if result.returncode or not pdf.exists():
        raise RuntimeError('Word 渲染失败：'+(result.stderr or result.stdout)[-1600:])
    reader=pypdf.PdfReader(pdf)
    if not reader.pages:
        raise ValueError('渲染结果没有页面')
    fonts = sorted({str(font.get_object().get('/BaseFont','')) for p in reader.pages
                    for font in p.get('/Resources',{}).get('/Font',{}).values()})
    if not any('NotoSansCJK' in f for f in fonts):
        raise ValueError('Word 渲染未使用项目字体；请重新注册字体后重试')
    images=[]
    pdfium=pypdfium2.PdfDocument(pdf)
    for i,page in enumerate(pdfium):
        image=output/f'page-{i+1}.png'
        page.render(scale=1.5).to_pil().save(image)
        images.append(image)
        page.close()
    pdfium.close()
    return {'pdf':pdf,'images':images,'page_count':len(reader.pages),
        'text':[p.extract_text() or '' for p in reader.pages], 'fonts':fonts,
        'checks':{'status':'passed','coverage':['docx_to_pdf','page_rasterization','nonempty_pages'],
                  'limitations':['自动渲染不等于人工逐页目视检查；本次页图可下载核查']}}
