"""Thin agent client. No database, permission decisions, or business mutations live here."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error
import uuid


def main():
    parser = argparse.ArgumentParser(description='PITR execution tools')
    parser.add_argument('command', choices=['catalog', 'call'])
    parser.add_argument('name', nargs='?')
    parser.add_argument('--input', default='-')
    parser.add_argument('--operation-id')
    args = parser.parse_args()
    try:
        authority = json.loads(Path(os.environ['PITR_EXECUTION_FILE']).read_text())
        if not authority['active']:
            raise ValueError('执行凭据已撤销')
        data = {} if args.command == 'catalog' else {
            'operation_id': args.operation_id or str(uuid.uuid4()), 'name': args.name,
            'arguments': json.loads(sys.stdin.read() if args.input == '-' else Path(args.input).read_text())}
        request = urllib.request.Request(authority['tool_url'] + ('/catalog' if args.command == 'catalog' else '/call'),
            data=json.dumps(data, ensure_ascii=False).encode(),
            headers={'Authorization': 'Bearer ' + authority['token'], 'Content-Type': 'application/json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=120) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            result = json.load(error)
        if result.get('ok') and args.command == 'catalog' and args.name:
            result['result'] = next(item for item in result['result'] if item['name'] == args.name)
        if result.get('ok') and args.name == 'source.page':
            value = result['result']
            target = Path.cwd() / f"page-{value['source']['id']}-{value['source']['revision']}-{value['page']}.png"
            target.write_bytes(base64.b64decode(value.pop('png_base64')))
            value['image_path'] = str(target)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('ok') else 1
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
