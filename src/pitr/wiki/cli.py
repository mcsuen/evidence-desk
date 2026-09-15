"""Human CLI and bounded agent interface; no agent publishing command."""
import json
import os
from pathlib import Path
import typer
from .contracts import WikiJobRequest

app = typer.Typer(help='公司研究 Wiki：收录、阅读、纠错和维护', no_args_is_help=True)
hooks = typer.Typer(help='安装、检查与精确卸载生命周期 hook', no_args_is_help=True)
app.add_typer(hooks, name='hooks')
models = typer.Typer(help='可选本地语义索引；模型安装会下载固定版本', no_args_is_help=True)
app.add_typer(models, name='model')


@app.command('build')
def build(company: str, focus: str = '业务模式、盈利驱动、竞争、风险与现金转化', root: str = ''):
    from .jobs import WikiJobs
    from .contracts import WikiJobRequest
    from pitr.desk.storage import uid
    output(WikiJobs(wiki(root)).create(WikiJobRequest(operation_id=uid('cli'), company=company,
        research_focus=focus, channel='cli')))


@app.command('update')
def update(company: str, focus: str = '检查新披露与已有认识的变化', root: str = ''):
    from .jobs import WikiJobs
    from .contracts import WikiJobRequest
    from pitr.desk.storage import uid
    output(WikiJobs(wiki(root)).create(WikiJobRequest(operation_id=uid('cli'), company=company,
        intent='update', research_focus=focus, budget_seconds=600, channel='cli')))


@app.command('jobs')
def jobs(company: str = 'PDD', root: str = ''):
    from .jobs import WikiJobs
    output(WikiJobs(wiki(root)).list(company))


@app.command('schedule')
def schedule(file: Path, root: str = ''):
    from .jobs import WikiJobs
    from .contracts import WikiUpdateSchedule
    output(WikiJobs(wiki(root)).schedule(WikiUpdateSchedule.model_validate_json(file.read_text())))


def root_path(root):
    return Path(root or os.environ.get('PITR_DESK_DIR', 'data/desk_control')).resolve()


def wiki(root):
    from pitr.desk.service import Desk
    from pitr.agent_runtime.runtime import AgentRuntime
    desk=Desk(root_path(root));desk.agents=AgentRuntime(desk)
    return desk.wiki


def output(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


@hooks.command('install')
def hook_install(provider: str, scope: str = 'project', root: str = '', project: Path = Path('.')):
    from .hooks import install
    output(install(provider, root_path(root), scope=scope, project=project.resolve()))


@hooks.command('uninstall')
def hook_uninstall(provider: str, scope: str = 'project', root: str = '', project: Path = Path('.')):
    from .hooks import install
    output(install(provider, root_path(root), scope=scope, project=project.resolve(), uninstall=True))


@hooks.command('doctor')
def hook_doctor(root: str = '', project: Path = Path('.')):
    from .hooks import doctor
    output(doctor(root_path(root), project.resolve()))


@hooks.command('test')
def hook_test(provider: str = 'claude', root: str = ''):
    from .capture import enqueue
    output(enqueue(root_path(root), provider, {'hook_event_name': 'Stop', 'session_id': 'pitr-install-test',
        'turn_id': 'pitr-install-test', 'last_assistant_message': 'PDD 安装测试：利润率研究线索；这条消息不是公司披露。'}))


@app.command('list')
def pages(company: str = 'PDD', root: str = '', as_of: str | None = None):
    output(wiki(root).list(company, as_of))


@app.command('search')
def search(query: str, company: str = 'PDD', root: str = '', as_of: str | None = None, hybrid: bool = False):
    from .search import search
    output(search(wiki(root), company, query, as_of=as_of, hybrid=hybrid))


@app.command('capture')
def capture(file: Path, root: str = ''):
    from .contracts import CaptureEnvelope
    output(wiki(root).capture(CaptureEnvelope.model_validate_json(file.read_text())))


@app.command('propose')
def propose(file: Path, root: str = ''):
    from .contracts import ProposalInput
    output(wiki(root).propose(ProposalInput.model_validate_json(file.read_text())))


@app.command('report')
def report(file: Path, root: str = ''):
    from .contracts import IssueInput
    output(wiki(root).report(IssueInput.model_validate_json(file.read_text())))


@app.command('history')
def history(identity: str, root: str = '', as_of: str | None = None):
    output(wiki(root).history(identity, as_of))


@app.command('rebuild')
def rebuild(root: str = ''):
    output(wiki(root).rebuild())


@app.command('inspect')
def inspect(company: str = 'PDD', kind: str = 'rules', root: str = ''):
    from .inspection import inspect
    current=wiki(root)
    if kind=='semantic':
        from pitr.desk.tasks import Queue
        from pitr.desk.contracts import TaskInput
        from pitr.desk.storage import uid
        output(Queue(current.desk).enqueue(TaskInput(operation_id=uid('inspect'),workflow='wiki_inspect',company=company,parameters={'kind':kind},budget_seconds=600)))
    else:output(inspect(current, company, kind))


@app.command('drain')
def drain(root: str = ''):
    from pitr.desk.tasks import Queue
    from .worker import Worker
    current = wiki(root)
    worker = Worker(current, Queue(current.desk))
    worker.drain_capture()
    count = 0
    while count < 100 and worker.relay_one():
        count += 1
    output({'relayed': count, 'note': '待整理任务由工作台后台继续执行'})


@models.command('install')
def install_model(root: str = ''):
    from .search import install_model
    output(install_model(wiki(root)))


@models.command('index')
def index_model(root: str = ''):
    from .search import build_vectors
    output(build_vectors(wiki(root)))


@app.command('backup')
def backup(destination: Path, root: str = ''):
    from .backup import backup
    output(backup(wiki(root),destination))


@app.command('evaluate')
def evaluate(file: Path, root: str = '', hybrid: bool = False, out: Path | None = None):
    from .evaluation import evaluate
    result=evaluate(wiki(root),json.loads(file.read_text()),hybrid=hybrid)
    if out:
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    output(result)


@app.command('mcp')
def mcp(root: str = ''):
    from mcp.server.fastmcp import FastMCP
    from .contracts import ProposalInput, CaptureEnvelope, IssueInput, QueryInput, AnswerInput
    from .research import query, save_answer
    from .search import search
    current = wiki(root)
    server = FastMCP('pitr-company-wiki')
    @server.tool()
    def wiki_job(request: 'WikiJobRequest') -> dict:
        """Queue a public build/update task. Originals and proposals do not grant publication."""
        from .jobs import WikiJobs
        return WikiJobs(current).create(request)
    @server.tool()
    def wiki_search(company: str, question: str, as_of: str | None = None) -> dict:
        """Read company knowledge with availability and precise version references."""
        return search(current, company, question, as_of=as_of)
    @server.tool()
    def wiki_pages(company: str, as_of: str | None = None) -> list:
        return current.list(company, as_of, include_blocked=False)
    @server.tool()
    def wiki_query(request: QueryInput) -> dict:
        return query(current, request)
    @server.tool()
    def wiki_answer(request: AnswerInput) -> dict:
        return save_answer(current, request)
    @server.tool()
    def wiki_validate(company: str, references: list[dict], as_of: str | None = None) -> dict:
        """Check exact knowledge versions immediately before citing; default is live."""
        return current.validate_use(company,references,as_of)
    @server.tool()
    def wiki_capture(request: CaptureEnvelope) -> dict:
        return current.capture(request)
    @server.tool()
    def wiki_propose(request: ProposalInput) -> dict:
        return current.propose(request.model_copy(update={'origin': 'agent'}))
    @server.tool()
    def wiki_report(request: IssueInput) -> dict:
        return current.report(request.model_copy(update={'discovered_by': 'agent'}))
    server.run()
