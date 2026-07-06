"""Subprocess execution wrapper."""

import asyncio
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
    """Run subprocess command and return stdout (sync).

    Retained for code paths that run inside ``asyncio.to_thread`` (e.g. the
    GitPython/PyGithub bridges). Prefer :func:`arun_command` from async code.
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


async def arun_command(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: float | None = None,
    check: bool = True,
    input: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Async counterpart of :func:`run_command`.

    Uses ``asyncio.create_subprocess_exec`` so the event loop stays free while
    the subprocess runs. Byte-oriented stdio is decoded explicitly (asyncio
    subprocesses are not text-mode). The error contract (``CommandException``
    for failure/timeout, same message shape) is preserved.
    """
    logger.debug(f"Executing: {cwd}$ {' '.join(cmd)}")

    input_bytes = input.encode("utf-8") if input else None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as e:
        from progress.errors import CommandException

        raise CommandException(f"command not found: {cmd[0] if cmd else ''}") from e
    except OSError as e:
        from progress.errors import CommandException

        raise CommandException(f"Failed to run command: {e}") from e

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=input_bytes),
            timeout=timeout,
        )
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        from progress.errors import CommandException

        raise CommandException("Command timeout") from None

    stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
    stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
    returncode = int(proc.returncode or 0)

    if stderr:
        logger.warning(f"Command stderr: {stderr}")

    if check and returncode != 0:
        err = f"command failed: exit code {returncode}\n"
        err += f"command: {' '.join(cmd)}\n"
        if stdout:
            err += f"Stdout:\n{stdout.strip()}\n"
        if stderr:
            err += f"Stderr:\n{stderr.strip()}\n"

        from progress.errors import CommandException

        raise CommandException(err)

    return stdout
