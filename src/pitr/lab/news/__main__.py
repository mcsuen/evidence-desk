import argparse
import json
from pathlib import Path
from pitr.application.service import Workstation
from pitr.domain.common import uid
from .service import News
from .contracts import NewsRunInput
from .worker import NewsWorker
from .evaluation import label_sheet, evaluate


def main():
    parser = argparse.ArgumentParser(description='Local company news experiment')
    parser.add_argument('--data-dir', default='data/research')
    parser.add_argument('action', choices=['status', 'collect', 'rescore', 'install', 'export-labels', 'evaluate'])
    parser.add_argument('--file', help='JSONL human label file')
    args = parser.parse_args()
    news = News(Workstation(Path(args.data_dir)))
    try:
        if args.action == 'status': result = news.status().model_dump()
        elif args.action == 'export-labels':
            if not args.file: parser.error('--file is required')
            rows = label_sheet(news)
            Path(args.file).write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows)+'\n')
            result = {'exported': len(rows), 'path': args.file}
        elif args.action == 'evaluate':
            if not args.file: parser.error('--file is required')
            result = evaluate(news, [json.loads(line) for line in Path(args.file).read_text().splitlines() if line.strip()])
        else:
            news.enqueue(NewsRunInput(operation_id=uid('news-cli'), kind=args.action))
            worker = NewsWorker(news)
            while worker.run_one(): pass
            result = news.status().model_dump()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally: news.judge.close()


if __name__ == '__main__': main()
