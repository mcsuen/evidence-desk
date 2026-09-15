"""Standalone stdlib-only MCP/CLI proxy. No Desk import, DB access or host configuration."""
import json, os, sys, urllib.request, urllib.error

def request(payload):
    endpoint=os.environ['PITR_RESEARCH_ENDPOINT']
    req=urllib.request.Request(endpoint,data=json.dumps(payload).encode(),headers={
      'Content-Type':'application/json','Authorization':'Bearer '+os.environ['PITR_RESEARCH_CAPABILITY']})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=600) as r:return json.load(r)

def main():
    if len(sys.argv)>1 and sys.argv[1]=='tool':
        reply=request({'name':sys.argv[2],'arguments':json.loads(sys.argv[3])});print(json.dumps(reply.get('value',reply),ensure_ascii=False));return
    for line in sys.stdin:
        try:
            msg=json.loads(line);method=msg.get('method');ident=msg.get('id')
            if ident is None:continue
            if method=='initialize':result={'protocolVersion':msg.get('params',{}).get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'pitr-research-proxy','version':'1'}}
            elif method=='tools/list':result={'tools':request({'catalog':True})['tools']}
            elif method=='tools/call':
                value=request({'name':msg['params']['name'],'arguments':msg['params'].get('arguments',{})})
                correlation=value.get('_trace') if isinstance(value,dict) else None
                value=value.get('value',value) if isinstance(value,dict) else value
                images=value.pop('_mcp_images',[]) if isinstance(value,dict) else []
                result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)},*images],'isError':bool(value.get('error')) if isinstance(value,dict) else False}
                if correlation:result['_meta']={'pitr.trace':correlation}
            elif method=='ping':result={}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Unsupported method'}}),flush=True);continue
            print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
        except Exception as e:
            if 'msg' in locals() and msg.get('id') is not None:print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'error':{'code':-32000,'message':str(e)}}),flush=True)
if __name__=='__main__':main()
