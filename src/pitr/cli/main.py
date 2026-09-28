"""Owner CLI: a thin authenticated client of the running /api/v1 application."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error
from urllib.parse import urlsplit, parse_qs


def request(root,path,method='GET',body=None):
    from pitr.agent_runtime.daemon import Instance
    instance=Instance(root)
    try:url=instance.existing_url()
    finally:instance.close()
    parsed=urlsplit(url);base=parsed.scheme+'://'+parsed.netloc
    ticket=parse_qs(parsed.fragment)['bootstrap'][0]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with opener.open(urllib.request.Request(base+'/api/local/session',data=json.dumps({'ticket':ticket}).encode(),headers={'Content-Type':'application/json'}),timeout=20) as response:
        csrf=json.load(response)['csrf']
    if not path.startswith('/') or '..' in path:raise ValueError('使用 /cases 等版本接口路径')
    headers={'Content-Type':'application/json','X-PITR-CSRF':csrf}
    try:
        with opener.open(urllib.request.Request(base+'/api/v1'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers=headers),timeout=150) as response:
            return response.read(),response.headers.get_content_type()
    except urllib.error.HTTPError as error:raise ValueError(error.read().decode()) from None


def app():
    parser=argparse.ArgumentParser(prog='research',description='PITR 研究工作站')
    parser.add_argument('--data-dir',default=os.environ.get('PITR_DATA_DIR','data/research'))
    sub=parser.add_subparsers(dest='action',required=True)
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=8765);serve.add_argument('--no-open',action='store_true')
    call=sub.add_parser('request');call.add_argument('path');call.add_argument('--method',default='GET');call.add_argument('--input');call.add_argument('--output')
    sub.add_parser('doctor')
    backup=sub.add_parser('backup');backup.add_argument('output')
    restore=sub.add_parser('restore');restore.add_argument('archive')
    args=parser.parse_args()
    try:
        if args.action=='serve':
            from pitr.agent_runtime.daemon import serve
            serve(args.data_dir,args.port,no_open=args.no_open);return
        if args.action=='doctor':
            from pitr.artifacts.render import doctor
            result=doctor()
        elif args.action=='restore':
            from pitr.application.maintenance import restore
            result=restore(Path(args.archive).read_bytes(),args.data_dir)
        elif args.action=='backup':
            from pitr.domain.common import uid
            raw,_=request(args.data_dir,'/maintenance/backup','POST',{'operation_id':uid('backup')})
            Path(args.output).write_bytes(raw);result={'path':str(Path(args.output).resolve())}
        else:
            body=json.loads(sys.stdin.read() if args.input=='-' else Path(args.input).read_text()) if args.input else None
            raw,media=request(args.data_dir,args.path,args.method,body)
            if args.output:Path(args.output).write_bytes(raw);result={'path':str(Path(args.output).resolve())}
            elif media=='application/json':result=json.loads(raw)
            else:raise ValueError('二进制响应请使用 --output 保存')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':app()
