#!/usr/bin/env python3
"""Ergonomic CLI for the per-variable ansible-vault blocks in group_vars.

The vault files (devops/ansible/group_vars/<env>/vault.yml) hold per-variable
``name: !vault |`` blocks inside plain YAML - not whole-file vaults - so the
ansible-vault CLI cannot operate on them directly. This tool orchestrates the
two native primitives that make a temp-file-free workflow possible:

  ``ansible-vault view -``                      decrypt stdin -> stdout
  ``ansible-vault encrypt_string --stdin-name`` encrypt stdin -> block stdout

Everything else here is text surgery: extracting a block's envelope, upserting
it back with the file's own indentation, and structural validation. Passwords
come from the avpm client (or another vault client via PROGRESS_VAULT_CLIENT);
subprocesses run with ANSIBLE_VAULT_IDENTITY_LIST emptied so exactly the
requested environment's password is tried - the repo ansible.cfg otherwise
injects every configured identity and would let a misfiled secret decrypt
anyway.

Commands:
  set     upsert encrypted variable(s): interactive, --stdin, or --from <env>
  get     print one decrypted value to stdout (the only plaintext-emitting command)
  list    print variable names and their encryption labels (no decryption)
  check   decrypt every variable in the given env(s); no values printed
  remove  delete variable block(s)

Stdout of ``get`` is byte-exact (``decrypt --output=-``); pipe the value
straight into its consumer and never redirect it to files or logs.
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import re
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR = Path(os.environ.get("PROGRESS_VAULT_DIR", REPO_ROOT / "devops/ansible/group_vars"))
CLIENT = os.environ.get("PROGRESS_VAULT_CLIENT", str(Path.home() / ".local/bin/avpm-client"))

# env name -> ansible vault identity label. `staging` is guarded by the
# `progress-test` vault-id: the label predates the two-tier environment rename
# and the avpm keyring was kept as-is (see the 2026-10-03 environment PRFC);
# `prod` keeps `progress-prod`.
ENVIRONMENTS = {"staging": "progress-test", "prod": "progress-prod"}
ENVELOPE_HEADER = "$ANSIBLE_VAULT;"
HEADER_RE = re.compile(r"^(?P<indent>\s*)(?P<name>[A-Za-z_][A-Za-z0-9_]*): !vault \|\s*$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class VaultToolError(Exception):
    exit_code = 1


class UsageError(VaultToolError):
    exit_code = 2


class CryptoError(VaultToolError):
    exit_code = 2


class IntegrityError(VaultToolError):
    exit_code = 3


class Block:
    """One ``name: !vault |`` block: header line index range and its envelope."""

    def __init__(self, name: str, start: int, end: int, indent: int, envelope: str, label: str):
        self.name = name
        self.start = start  # first line index (the header)
        self.end = end  # one past the last body line
        self.indent = indent  # envelope indentation inside the file
        self.envelope = envelope  # dedented "$ANSIBLE_VAULT;..." text
        self.label = label  # vault identity the block was encrypted under


def vault_path(env: str) -> Path:
    return VAULT_DIR / env / "vault.yml"


def run_vault_cli(args: list[str], input_bytes: bytes | None = None) -> bytes:
    """Run ansible-vault with a single-identity environment and no pager."""
    env = dict(os.environ)
    # Strictness: the repo ansible.cfg injects all three identities; emptying
    # the list makes the CLI try exactly the --vault-id we pass, so a secret
    # encrypted under another environment's password fails here.
    env["ANSIBLE_VAULT_IDENTITY_LIST"] = ""
    env["PAGER"] = "cat"  # view - must not page when stdout is a pipe
    try:
        proc = subprocess.run(
            ["ansible-vault", *args],
            input=input_bytes,
            capture_output=True,
            timeout=120,
            env=env,
        )
    except FileNotFoundError as exc:
        raise CryptoError("ansible-vault not found on PATH; install ansible-core") from exc
    except subprocess.TimeoutExpired as exc:
        raise CryptoError("ansible-vault timed out; is the vault client interactive?") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip().splitlines()
        raise CryptoError(f"ansible-vault {' '.join(args[:2])} failed: {detail[-1] if detail else 'unknown error'}")
    return proc.stdout


def decrypt_envelope(env: str, envelope: str) -> bytes:
    """Decrypt one envelope byte-exactly.

    ``decrypt --output=-`` writes the plaintext to stdout through write_data,
    which adds no newline - unlike ``view``, whose display layer appends one
    to values that lack it, making its output ambiguous for values that
    genuinely end in a newline.
    """
    return run_vault_cli(
        ["decrypt", "-", "--output=-", f"--vault-id={ENVIRONMENTS[env]}@{CLIENT}"],
        envelope.encode(),
    )


def encrypt_block(env: str, name: str, value: bytes) -> str:
    """Encrypt value into the canonical ``name: !vault |`` block text."""
    out = run_vault_cli(
        [
            "encrypt_string",
            f"--vault-id={ENVIRONMENTS[env]}@{CLIENT}",
            f"--encrypt-vault-id={ENVIRONMENTS[env]}",
            f"--stdin-name={name}",
        ],
        value,
    )
    text = out.decode()
    blocks = parse_blocks(text)
    if len(blocks) != 1 or blocks[0].name != name:
        raise IntegrityError(f"encrypt_string produced an unexpected block for {name!r}")
    return text


def parse_blocks(text: str) -> list[Block]:
    """Parse every ``name: !vault |`` block; blank separators stay untouched."""
    lines = text.splitlines()
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        match = HEADER_RE.match(lines[i])
        if not match:
            i += 1
            continue
        base_indent = len(match.group("indent"))
        j = i + 1
        body: list[str] = []
        while j < len(lines):
            line = lines[j]
            if line.strip() == "":
                body.append(line)
                j += 1
                continue
            if len(line) - len(line.lstrip()) <= base_indent:
                break
            body.append(line)
            j += 1
        while body and body[-1].strip() == "":
            body.pop()
            j -= 1
        if not body:
            raise IntegrityError(f"variable {match.group('name')!r}: vault block has no content")
        if any(line.strip() == "" for line in body):
            # a blank line inside the block scalar is unhexlify-fatal for
            # ansible itself, so flag it here instead of failing at decrypt
            raise IntegrityError(f"variable {match.group('name')!r}: blank line inside vault block")
        unit = min(len(line) - len(line.lstrip()) for line in body)
        envelope = "\n".join(line[unit:] for line in body) + "\n"
        first = envelope.split("\n", 1)[0]
        if not first.startswith(ENVELOPE_HEADER):
            raise IntegrityError(f"variable {match.group('name')!r}: block does not start with {ENVELOPE_HEADER}")
        label = first.split(";")[3] if len(first.split(";")) > 3 else ""
        blocks.append(Block(match.group("name"), i, j, unit, envelope, label))
        i = j
    return blocks


def find_blocks(blocks: list[Block], name: str) -> list[Block]:
    if not NAME_RE.match(name):
        raise UsageError(f"invalid variable name {name!r}")
    found = [b for b in blocks if b.name == name]
    if len(found) > 1:
        raise IntegrityError(f"variable {name!r} occurs {len(found)} times; run 'remove' to clean up first")
    return found


def render_block(name: str, envelope: str, indent: int) -> list[str]:
    lines = [f"{name}: !vault |"]
    lines.extend(" " * indent + line for line in envelope.splitlines())
    return lines


def upsert(text: str, name: str, envelope: str) -> str:
    """Insert or replace one block; comments and other variables stay put."""
    lines = text.splitlines()
    blocks = parse_blocks(text)
    existing = find_blocks(blocks, name)
    if existing:
        block = existing[0]
        rendered = render_block(name, envelope, block.indent)
        lines[block.start : block.end] = rendered
    else:
        indent = blocks[-1].indent if blocks else 4
        rendered = render_block(name, envelope, indent)
        if text.strip():
            if not text.endswith("\n"):
                text += "\n"
            text += "\n"
            lines = text.splitlines()
        lines.extend(rendered)
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    # structural re-parse: the file must still yield exactly the expected blocks
    after = parse_blocks(result)
    find_blocks(after, name)
    return result


def read_vault_text(env: str) -> str:
    path = vault_path(env)
    if not path.is_file():
        raise UsageError(f"{path} does not exist")
    return path.read_text()


def load_value(args: argparse.Namespace, name: str) -> bytes:
    if args.from_env:
        return decrypt_envelope(args.from_env, envelope_of(args.from_env, name))
    if args.stdin:
        value = sys.stdin.buffer.read()
        if not args.exact and value.endswith(b"\n"):
            value = value[:-1]
            if value.endswith(b"\r"):
                value = value[:-1]
    else:
        if not sys.stdin.isatty():
            raise UsageError(
                "stdin is not a terminal, so a hidden prompt cannot read the value; pipe it in with --stdin instead"
            )
        value = getpass.getpass(f"value for {name} (input hidden): ").encode()
    if not value:
        raise UsageError(f"empty value for {name!r}")
    return value


def envelope_of(env: str, name: str) -> str:
    blocks = find_blocks(parse_blocks(read_vault_text(env)), name)
    if not blocks:
        raise UsageError(f"variable {name!r} not found in {vault_path(env)}")
    return blocks[0].envelope


def cmd_set(args: argparse.Namespace) -> None:
    if args.stdin and len(args.names) > 1:
        raise UsageError("--stdin reads one value; pass one variable name")
    if args.from_env and len(args.names) > 1:
        raise UsageError("--from copies one variable; pass one variable name")
    text = vault_path(args.env).read_text() if vault_path(args.env).is_file() else ""
    existing_names = {b.name for b in parse_blocks(text)} if text else set()
    for name in args.names:
        value = load_value(args, name)
        block_text = encrypt_block(args.env, name, value)
        envelope = parse_blocks(block_text)[0].envelope
        # cryptographic self-verify before touching the file
        if decrypt_envelope(args.env, envelope) != value:
            raise IntegrityError(f"post-encryption verification failed for {name!r}")
        text = upsert(text, name, envelope)
        action = "replaced" if name in existing_names else "added"
        print(f"✓ {name} -> {vault_path(args.env)} ({action})")
    vault_path(args.env).write_text(text)


def cmd_get(args: argparse.Namespace) -> None:
    value = decrypt_envelope(args.env, envelope_of(args.env, args.name))
    if not args.quiet:
        print("[vault] plaintext on stdout; pipe it into its consumer, do not redirect", file=sys.stderr)
    sys.stdout.buffer.write(value)
    sys.stdout.buffer.flush()


def cmd_list(args: argparse.Namespace) -> None:
    if args.all and args.env:
        raise UsageError("pass either an environment or --all, not both")
    if not args.all and not args.env:
        raise UsageError(f"provide an environment ({', '.join(ENVIRONMENTS)}) or --all")
    envs = list(ENVIRONMENTS) if args.all else [args.env]
    for env in envs:
        path = vault_path(env)
        if not path.is_file():
            print(f"{env}: no vault file")
            continue
        blocks = parse_blocks(path.read_text())
        print(f"{env}: {len(blocks)} variable(s)")
        for block in blocks:
            print(f"  {block.name}  [{block.label or '?'}]")


def cmd_check(args: argparse.Namespace) -> None:
    envs = args.environments or list(ENVIRONMENTS)
    failed = False
    for env in envs:
        if env not in ENVIRONMENTS:
            raise UsageError(f"unknown environment {env!r}; choose from {', '.join(ENVIRONMENTS)}")
        path = vault_path(env)
        if not path.is_file():
            print(f"{env}: no vault file, skipped")
            continue
        blocks = parse_blocks(path.read_text())
        failures = []
        for block in blocks:
            try:
                decrypt_envelope(env, block.envelope)
            except CryptoError:
                failures.append(block.name)
        status = "ok" if not failures else "FAILED"
        print(f"{env}: {len(blocks) - len(failures)}/{len(blocks)} {status}")
        for name in failures:
            print(f"  ✗ {name}")
            failed = True
    if failed:
        raise VaultToolError("vault check failed")


def cmd_remove(args: argparse.Namespace) -> None:
    text = read_vault_text(args.env)
    blocks = parse_blocks(text)
    targets: list[Block] = []
    for name in args.names:
        found = find_blocks(blocks, name)
        if not found:
            raise UsageError(f"variable {name!r} not found in {vault_path(args.env)}")
        targets.extend(found)
    if not args.yes:
        answer = input(f"remove {len(targets)} block(s) from {vault_path(args.env)}? [y/N] ")
        if answer.strip().lower() != "y":
            print("aborted")
            return
    doomed = {(b.start, b.end) for b in targets}
    lines = text.splitlines()
    keep = [line for idx, line in enumerate(lines) if not any(start <= idx < end for start, end in doomed)]
    result = "\n".join(keep)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    parse_blocks(result)  # structural gate before writing
    vault_path(args.env).write_text(result)
    print(f"✓ removed {len(targets)} block(s) from {vault_path(args.env)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vault.py",
        description="Ergonomic CLI for per-variable ansible-vault blocks in group_vars.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_env(sub_parser: argparse.ArgumentParser, required: bool = True) -> None:
        sub_parser.add_argument("env", choices=sorted(ENVIRONMENTS), help="target environment")

    p_set = sub.add_parser("set", help="upsert encrypted variable(s)")
    add_env(p_set)
    p_set.add_argument("names", nargs="+", metavar="name")
    p_set.add_argument("--stdin", action="store_true", help="read value from stdin instead of a hidden prompt")
    p_set.add_argument(
        "--exact", action="store_true", help="with --stdin: keep the value byte-exact (no trailing-newline strip)"
    )
    p_set.add_argument(
        "--from",
        dest="from_env",
        choices=sorted(ENVIRONMENTS),
        metavar="env",
        help="copy the same-named variable from another environment",
    )
    p_set.set_defaults(func=cmd_set)

    p_get = sub.add_parser("get", help="print one decrypted value to stdout")
    add_env(p_get)
    p_get.add_argument("name", metavar="name")
    p_get.add_argument("--quiet", action="store_true", help="suppress the plaintext warning on stderr")
    p_get.set_defaults(func=cmd_get)

    p_list = sub.add_parser("list", help="print variable names (no decryption)")
    p_list.add_argument("env", nargs="?", choices=sorted(ENVIRONMENTS))
    p_list.add_argument("--all", action="store_true", help="list every environment")
    p_list.set_defaults(func=cmd_list, env=None)

    p_check = sub.add_parser("check", help="decrypt-validate variables (no values printed)")
    p_check.add_argument("environments", nargs="*", choices=sorted(ENVIRONMENTS), metavar="env")
    p_check.set_defaults(func=cmd_check)

    p_remove = sub.add_parser("remove", help="delete variable block(s)")
    add_env(p_remove)
    p_remove.add_argument("names", nargs="+", metavar="name")
    p_remove.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_remove.set_defaults(func=cmd_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "from_env", None) and getattr(args, "stdin", False):
        print("error: --from and --stdin are mutually exclusive", file=sys.stderr)
        return 2
    try:
        args.func(args)
    except VaultToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
