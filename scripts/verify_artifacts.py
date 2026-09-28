#!/usr/bin/env python3
"""Compile, render and materialize versioned reports for page-by-page visual QA."""
import argparse
from collections import Counter
import json
from pathlib import Path
import unicodedata
from PIL import Image,ImageDraw
from pitr.application.service import Workstation
from pitr.artifacts.queue import ExportQueue
from pitr.domain.common import uid
from pitr.domain.contracts import ExportRequest


def normalize(text):
    return ''.join(unicodedata.normalize('NFKC',text).split()).replace('\u200b','').replace('\u00ad','')


def materialize(station,artifact,folder):
    import pypdf
    folder.mkdir(parents=True,exist_ok=True)
    manifest=artifact.manifest
    (folder/'report.docx').write_bytes(station.store.read_blob(artifact.digest))
    pdf=station.store.read_blob(manifest['render']['pdf_digest']);(folder/'report.pdf').write_bytes(pdf)
    from pitr.artifacts.render import verify_text
    verify_text([p.extract_text() or '' for p in pypdf.PdfReader(folder/'report.pdf').pages],manifest['text'],artifact.report.revision)
    pages=[]
    for index,sha in enumerate(manifest['render']['page_digests'],1):
        path=folder/f'page-{index:02}.png';path.write_bytes(station.store.read_blob(sha));pages.append(path)
    contacts=[]
    for first in range(0,len(pages),2):
        pictures=[Image.open(p).convert('RGB') for p in pages[first:first+2]]
        width=sum(p.width for p in pictures);height=max(p.height for p in pictures)+30
        board=Image.new('RGB',(width,height),'#d6d9dd');draw=ImageDraw.Draw(board)
        x=0
        for index,picture in enumerate(pictures,first+1):board.paste(picture,(x,30));draw.text((x+10,8),f'Page {index}',fill='black');x+=picture.width
        path=folder/f'contact-{first//2+1}.png';board.save(path);contacts.append(str(path.resolve()))
    record={'artifact':artifact.ref.model_dump(),'report':artifact.report.model_dump(),'digest':artifact.digest,'paper':artifact.paper,
            'compiler':artifact.compiler_version,'page_count':len(pages),'pdf_text_consistency':'passed','visual_inspection':'pending',
            'docx':str((folder/'report.docx').resolve()),'pdf':str((folder/'report.pdf').resolve()),'contacts':contacts,'manifest':manifest}
    (folder/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    return record


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    station=Workstation(args.root,runtime=False);queue=ExportQueue(station,start=False);records=[]
    for run in station.runs():
        if not run.report:continue
        for paper in ('Letter','A4'):
            job=station.reports.export(ExportRequest(operation_id=uid('verify-word'),report=run.report,paper=paper))
            if job['status']=='failed':station.reports.retry_export(job['id'],uid('verify-retry'))
            while work:=queue.claim():queue.perform(work)
            with station.store.connect() as db:finished=json.loads(db.execute('SELECT body FROM exports WHERE id=?',(job['id'],)).fetchone()[0])
            if finished['status']!='completed':raise ValueError(finished)
            artifact=station.store.get(finished['artifact'],'artifact')
            records.append(materialize(station,artifact,Path(args.output)/(run.lane+'-'+paper)))
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    (out/'index.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
    print(json.dumps([{k:r[k] for k in ('docx','paper','page_count','pdf_text_consistency','digest')} for r in records],ensure_ascii=False))


if __name__=='__main__':main()
