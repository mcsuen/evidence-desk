from __future__ import annotations

from pathlib import Path
from typing import Optional  # noqa: UP035

import typer

from pitr.config import settings

api_app = typer.Typer(help="Independent financial research desk server.", no_args_is_help=True)


@api_app.command("serve")
def api_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    desk_dir: Path = typer.Option(settings.data_dir / "desk_control", "--desk-dir"),
    web_dist: Optional[Path] = typer.Option(None, "--web-dist", help="built UI directory (default web/dist)"),  # noqa: UP007
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    from pitr.agent_runtime.daemon import serve

    if reload:
        raise typer.BadParameter("新工作台请使用前端 Vite 热更新；后端修改后重启服务")
    if host!='127.0.0.1':raise typer.BadParameter('本机 Agent 工作台仅绑定 127.0.0.1')
    serve(desk_dir,port,web_dist=web_dist)
