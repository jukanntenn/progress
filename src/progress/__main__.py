"""``python -m progress`` entry point (delegates to the CLI typer app)."""

from progress.cli.main import app

if __name__ == "__main__":
    app()
