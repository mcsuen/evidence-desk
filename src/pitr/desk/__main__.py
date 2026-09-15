import argparse
import json


def main():
    parser=argparse.ArgumentParser(description='Independent PITR research desk')
    parser.add_argument('command',choices=['serve','view','worker','schema','mcp','tool','command'])
    parser.add_argument('--root',default='data/desk_control')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--company',default='PDD')
    parser.add_argument('--period',default='')
    parser.add_argument('--snapshot',default='')
    parser.add_argument('--tool',default='observations',choices=['search','read','observations','objects','operating_model'])
    parser.add_argument('--input',default='{}',help='JSON command body or tool arguments')
    parser.add_argument('--action',default='research',choices=['research','research-message','research-status'])
    args=parser.parse_args()
    if args.command=='schema':
        from pitr.schemas import export_schemas
        for path in export_schemas():print(path)
        return
    if args.command=='serve':
        from pitr.agent_runtime.daemon import serve
        serve(args.root,args.port)
        return
    from .service import Desk
    desk=Desk(args.root)
    if args.command in ('worker','command'):
        from pitr.agent_runtime.runtime import AgentRuntime
        desk.agents=AgentRuntime(desk)
    if args.command=='view':print(desk.view(args.company,args.period).model_dump_json())
    elif args.command=='worker':
        from .tasks import Queue
        from .research.service import Research
        from .research.intake import IntakeWorker
        Research(desk)
        IntakeWorker(desk).run_one()
        Queue(desk).run_one()
    elif args.command=='mcp':
        from .tools import mcp_server
        mcp_server(desk,args.snapshot).run()
    elif args.command=='tool':
        from .tools import SnapshotTools
        print(json.dumps(getattr(SnapshotTools(desk,args.snapshot),args.tool)(**json.loads(args.input)),ensure_ascii=False))
    elif args.command=='command':
        from .tasks import Queue
        body=json.loads(args.input)
        if args.action.startswith('research'):
            from .research.service import Research
            from .research.contracts import ResearchRequest,ResearchMessage
            service=Research(desk,Queue(desk))
            if args.action=='research':result=service.create(ResearchRequest.model_validate({**body,'channel':'cli'}))
            elif args.action=='research-message':result=service.message(body.pop('request_id'),ResearchMessage.model_validate(body))
            else:result=service.get(body['request_id'])
        print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
