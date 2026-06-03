import typer

app = typer.Typer(help="Peptide Catalyst Watch CLI")

@app.command()
def hello() -> None:
    """Placeholder CLI command until Milestone 1 is implemented."""
    typer.echo("peptide-watch scaffold ready")
