"""Subprocess execution wrapper."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def run_command(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: float | None = None,
    check: bool = True,
    input: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Run subprocess command and return stdout.

    Args:
        cmd: Command and arguments to execute
        cwd: Working directory (optional)
        timeout: Command timeout in seconds (optional)
        check: If True, raise CalledProcessError for non-zero exit codes
        input: Input string to pass to stdin (optional)
        env: Environment variables (optional)

    Returns:
        Command stdout output

    Raises:
        CommandException: If command fails (CalledProcessError, TimeoutExpired)
        FileNotFoundError: If command executable not found
    """
    logger.debug(f"Executing: {cwd}$ {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            input=input,
            env=env,
        )

        if result.stderr:
            logger.warning(f"Command stderr: {result.stderr}")

        return result.stdout

    except subprocess.CalledProcessError as e:
        err = f"command failed: {e}\n"
        err += f"command: {' '.join(cmd)}\n"
        if e.stdout:
            err += f"Stdout:\n{e.stdout.strip()}\n"
        if e.stderr:
            err += f"Stderr:\n{e.stderr.strip()}\n"

        from progress.errors import CommandException

        raise CommandException(err) from e

    except subprocess.TimeoutExpired:
        from progress.errors import CommandException

        raise CommandException("Command timeout") from None

    except subprocess.SubprocessError as e:
        from progress.errors import CommandException

        raise CommandException("Failed to run command") from e
