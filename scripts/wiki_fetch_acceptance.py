"""Run real Wiki recovery in a separate copy, without Slack or human adoption.

Example: python scripts/wiki_fetch_acceptance.py --from-root data/wiki_acceptance_live
    --job wiki-job_... --root data/wiki_fetch_acceptance_...
"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

from pitr.desk.service import Desk
from pitr.desk.tasks import Queue
from pitr.wiki.jobs import WikiJobs
from pitr.wiki.contracts import WikiJobRequest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-root', type=Path, required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--seed-url', action='append', default=[], help='Additional public URL discovered during diagnosis; retained as an explicit input, never a fixture.')
    args = parser.parse_args()
    with sqlite3.connect(f'file:{args.from_root.resolve()}/desk.sqlite?mode=ro', uri=True) as original:
        if original.execute("SELECT 1 FROM tasks WHERE status IN ('queued','running') LIMIT 1").fetchone():
            parser.error('来源验收库仍有未结束任务；请在任务结束后复制，避免重放其他工作')
        args.root.mkdir(parents=True, exist_ok=False)
        with sqlite3.connect(args.root / 'desk.sqlite') as target:original.backup(target)
    for name in ('objects', 'originals'):
        if (args.from_root / name).exists():shutil.copytree(args.from_root / name, args.root / name)
    # Intentionally do not copy private settings or start Bot/Outbox workers.
    desk = Desk(args.root)
    from pitr.agent_runtime.runtime import AgentRuntime
    desk.agents = AgentRuntime(desk)
    desk.agents.refresh()
    queue = Queue(desk)
    jobs = WikiJobs(desk.wiki, queue)
    previous = jobs.get(args.job)
    request = WikiJobRequest.model_validate({**previous['request'], 'operation_id': 'acceptance:' + uuid.uuid4().hex,
                                            'seed_urls': list(dict.fromkeys(previous['request'].get('seed_urls', []) + args.seed_url)),
                                            'channel': 'cli', 'resume_job_id': previous['id']})
    created = jobs.create(request)
    print(json.dumps({'job_id': created['id'], 'root': str(args.root.resolve()), 'scope': request.model_dump()}, ensure_ascii=False), flush=True)
    started = time.monotonic()
    queue.run_one()
    result = jobs.get(created['id'])
    (args.root / 'acceptance-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    acquired = [m for m in result['materials'] if m.get('source_id')]
    print(json.dumps({'job_id': result['id'], 'seconds': round(time.monotonic() - started, 2),
        'status': result['execution_status'], 'publication': result['publication_status'], 'error': result.get('error'),
        'originals': len(acquired), 'providers': sorted({m['provider'] for m in acquired}),
        'coverage': result['coverage'], 'proposal_id': result.get('proposal_id')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':main()
