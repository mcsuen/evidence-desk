"""Human CLI for the current research desk and Wiki."""
import typer
from pitr.cli.api_cmds import api_app
from pitr.wiki.cli import app as wiki_app

app=typer.Typer(name='research',help='PITR 研究与 LLM Wiki',no_args_is_help=True)
app.add_typer(api_app,name='api')
app.add_typer(wiki_app,name='wiki')

def main():app()

if __name__=='__main__':main()
