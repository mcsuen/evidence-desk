"""Bounded PDF parsing process. No models, network, or application store."""
import base64
import json
import sys


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(60,65))
        if sys.platform!='darwin':resource.setrlimit(resource.RLIMIT_AS,(2_000_000_000,2_000_000_000))
        data=json.loads(sys.stdin.read(60_000_000))
        raw=base64.b64decode(data.pop('raw'));op=data.pop('operation')
        from .originals import _parse,_tables,_render_page
        result={'parse':_parse,'tables':_tables,'render':_render_page}[op](raw,**data)
        if op=='render':result=base64.b64encode(result).decode()
        print(json.dumps({'result':result},ensure_ascii=False,default=lambda o:o.model_dump(mode='json')))
    except Exception as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False))


if __name__=='__main__':main()
