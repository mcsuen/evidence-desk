"""Hook executable: standard library only, durable local queue before returning.

Never opens transcripts, captures hidden reasoning, calls a model, or imports Desk.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

DROP_KEYS = re.compile(r'(thinking|reasoning|secret|password|credential|authorization|api[_-]?key|access[_-]?token|refresh[_-]?token)', re.I)
SECRET = re.compile(r'(?i)(?:\b(?:sk-[\w-]{12,}|xox[baprs]-[\w-]{10,}|AKIA[A-Z0-9]{16})\b|Bearer\s+[^\s"\']+|eyJ[\w-]+\.[\w-]+\.[\w-]+)')
ASSIGNMENT = re.compile(r'(?im)^.*(?:api[_-]?key|password|secret|access[_-]?token|refresh[_-]?token)\s*[=:].*$')
PEM = re.compile(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', re.S)
FINANCE = re.compile(r'(财报|收入|利润|现金流|资产|负债|公司研究|毛利|投资论点|earnings|revenue|margin|cash flow|guidance|valuation|financial|业绩|预测|估值|research)', re.I)
COMPANIES = {'PDD': r'\bPDD\b|拼多多|\bTemu\b', 'BABA': r'\bBABA\b|阿里巴巴', 'JD': r'\bJD\b|京东', 'AMZN': r'\bAMZN\b|亚马逊', 'MELI': r'\bMELI\b|MercadoLibre'}


def sanitize(value):
    if isinstance(value, dict):
        if str(value.get('type','')).lower() in ('thinking','reasoning','analysis','redacted_thinking'):
            return {}
        return {k: sanitize(v) for k, v in value.items() if not DROP_KEYS.search(k)}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        return ASSIGNMENT.sub('[credential omitted]', SECRET.sub('[credential omitted]', PEM.sub('[private key omitted]', value)))
    return value


def company_for(text):
    matches = [company for company, pattern in COMPANIES.items() if re.search(pattern, text, re.I)]
    return matches[0] if len(matches) == 1 else ''


def connection(root):
    directory = Path(root) / 'capture'
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'queue.sqlite', timeout=0.7)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY, body TEXT, status TEXT, created_at TEXT, error TEXT DEFAULT \'\')')
    return db


def enqueue(root, provider, raw):
    if provider not in ('claude', 'codex'):
        raise ValueError('Unknown hook provider')
    if os.environ.get('PITR_CAPTURE_ORIGIN') in ('pitr-wiki', 'pitr-bot'):
        return {'status': 'ignored_echo'}
    event = raw.get('hook_event_name', '')
    if event not in ('UserPromptSubmit', 'PostToolUse', 'Stop', 'SessionEnd'):
        return {'status': 'unsupported_event'}
    # Deliberately ignore transcript_path and all undocumented payload fields.
    selected = {key: raw[key] for key in ('session_id', 'turn_id', 'prompt_id', 'tool_use_id', 'tool_call_id',
        'tool_name', 'cwd', 'model', 'prompt', 'tool_response', 'last_assistant_message', 'reason') if key in raw}
    selected = sanitize(selected)
    text = json.dumps({k: selected[k] for k in ('prompt', 'tool_response', 'last_assistant_message') if k in selected}, ensure_ascii=False)
    selected['hook_event_name'] = event
    selected['provider'] = provider
    company = company_for(text)
    selected['company'] = company
    stable = [provider, raw.get('session_id'), event, raw.get('turn_id') or raw.get('prompt_id'), raw.get('tool_use_id') or raw.get('tool_call_id'),
              hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()]
    eid = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
    selected['id'] = eid
    # Session closure remains useful even when it has no text. Other unrelated
    # engineering output is excluded before any persisted content is written.
    status = 'pending' if (FINANCE.search(text) or event == 'SessionEnd') else 'excluded'
    if status == 'excluded':
        selected = {'id': eid, 'provider': provider, 'hook_event_name': event, 'reason': 'outside_company_research'}
    from contextlib import closing
    with closing(connection(root)) as db, db:
        db.execute('INSERT OR IGNORE INTO captures(id,body,status,created_at) VALUES(?,?,?,?)',
            (eid, json.dumps(selected, ensure_ascii=False), status, datetime.now(timezone.utc).isoformat()))
    return {'id': eid, 'status': status}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=['claude', 'codex'], required=True)
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError('Hook payload exceeds 4 MB')
        enqueue(args.root, args.provider, json.loads(raw))
        print('{}')  # Provider-compatible successful hook response; no prompt injection.
    except Exception as error:
        message = f'PITR capture persistence failed: {type(error).__name__}'
        print(message, file=sys.stderr)
        try:
            path = Path(args.root) / 'capture-errors.log'
            with path.open('a') as stream:
                stream.write(datetime.now(timezone.utc).isoformat() + ' ' + message + '\n')
        except OSError:
            pass
        raise SystemExit(1)


if __name__ == '__main__':
    main()
