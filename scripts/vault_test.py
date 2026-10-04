#!/usr/bin/env python3
"""Unit tests for scripts/vault.py (stdlib unittest).

Hermetic by default: ansible-vault integration cases self-skip when the
binary is absent, run against a temp password file via PROGRESS_VAULT_CLIENT,
and isolate the vault directory with PROGRESS_VAULT_DIR - the real avpm
client and the repo's group_vars are never touched.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
from typing import override
import unittest

SCRIPT = Path(__file__).with_name("vault.py")
sys.path.insert(0, str(Path(__file__).parent))

import vault  # noqa: E402  (imports SCRIPT's module for pure-logic cases)

ANSIBLE_VAULT = shutil.which("ansible-vault")

ENV = "staging"
OTHER = "prod"


def run_tool(*args: str, env: dict[str, str], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=120,
    )


class ParseBlocksTest(unittest.TestCase):
    def test_parses_blocks_with_comments_and_blank_separators(self):
        text = textwrap.dedent(
            """\
            # header comment stays put
            alpha: !vault |
                $ANSIBLE_VAULT;1.2;AES256;progress-test
                30303030
            # beta comment
            beta: !vault |
                    $ANSIBLE_VAULT;1.2;AES256;progress-prod
                    31313131

            gamma_plain: plain-value
            """
        )
        blocks = vault.parse_blocks(text)
        self.assertEqual([b.name for b in blocks], ["alpha", "beta"])
        self.assertEqual(blocks[0].label, "progress-test")
        self.assertEqual(blocks[1].label, "progress-prod")
        self.assertEqual(blocks[0].indent, 4)
        self.assertEqual(blocks[1].indent, 8)
        self.assertTrue(blocks[0].envelope.startswith("$ANSIBLE_VAULT;"))
        self.assertFalse(blocks[0].envelope.endswith("\n\n"))

    def test_blank_lines_inside_block_body_are_rejected_as_corrupt(self):
        text = "alpha: !vault |\n    $ANSIBLE_VAULT;1.2;AES256;progress-test\n\n    30303030\n"
        with self.assertRaises(vault.IntegrityError):
            vault.parse_blocks(text)
        # a trailing blank line is file spacing, not content
        ok = "alpha: !vault |\n    $ANSIBLE_VAULT;1.2;AES256;progress-test\n    30303030\n\n"
        self.assertEqual(vault.parse_blocks(ok)[0].name, "alpha")

    def test_header_without_body_raises(self):
        with self.assertRaises(vault.IntegrityError):
            vault.parse_blocks("alpha: !vault |\nbeta: 1\n")

    def test_upsert_replaces_in_place_and_keeps_comments(self):
        text = "# keep me\nalpha: !vault |\n    $ANSIBLE_VAULT;1.2;AES256;progress-test\n    30303030\nplain: 1\n"
        result = vault.upsert(text, "alpha", "$ANSIBLE_VAULT;1.2;AES256;progress-test\n99999999\n")
        self.assertIn("# keep me", result)
        self.assertIn("99999999", result)
        self.assertNotIn("30303030", result)
        self.assertIn("plain: 1", result)
        self.assertEqual([b.name for b in vault.parse_blocks(result)], ["alpha"])

    def test_upsert_appends_with_existing_indent_and_separator(self):
        text = "alpha: !vault |\n    $ANSIBLE_VAULT;1.2;AES256;progress-test\n    30303030\n"
        result = vault.upsert(text, "beta", "$ANSIBLE_VAULT;1.2;AES256;progress-test\n31313131\n")
        blocks = vault.parse_blocks(result)
        self.assertEqual([b.name for b in blocks], ["alpha", "beta"])
        self.assertEqual(blocks[1].indent, 4)

    def test_upsert_refuses_duplicate_names(self):
        text = (
            "alpha: !vault |\n"
            "    $ANSIBLE_VAULT;1.2;AES256;progress-test\n    AAAA\n"
            "alpha: !vault |\n"
            "    $ANSIBLE_VAULT;1.2;AES256;progress-test\n    BBBB\n"
        )
        blocks = vault.parse_blocks(text)
        with self.assertRaises(vault.IntegrityError):
            vault.find_blocks(blocks, "alpha")


@unittest.skipUnless(ANSIBLE_VAULT, "ansible-vault binary not on PATH")
class CliIntegrationTest(unittest.TestCase):
    """End-to-end cases against the real ansible-vault binary, hermetic vault dir."""

    @override
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault_dir = Path(self.tmp.name) / "group_vars"
        self.password_file = Path(self.tmp.name) / "pw"
        self.password_file.write_text("test-password-123\n")
        for env in vault.ENVIRONMENTS:
            (self.vault_dir / env).mkdir(parents=True)
        self.tool_env = dict(
            os.environ,
            PROGRESS_VAULT_DIR=str(self.vault_dir),
            PROGRESS_VAULT_CLIENT=str(self.password_file),
        )

    def write_vault(self, env: str, text: str) -> None:
        (self.vault_dir / env / "vault.yml").write_text(text)

    def read_vault(self, env: str) -> str:
        return (self.vault_dir / env / "vault.yml").read_text()

    def test_set_get_roundtrip_and_byte_fidelity(self):
        value = b"kuma-url?status=up&msg=OK&ping="
        proc = run_tool("set", ENV, "probe_var", "--stdin", env=self.tool_env, stdin=value)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stored = self.read_vault(ENV)
        self.assertIn("probe_var: !vault |", stored)
        proc = run_tool("get", ENV, "probe_var", "--quiet", env=self.tool_env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, value)

    def test_set_stdin_strips_one_trailing_newline_unless_exact(self):
        run_tool("set", ENV, "a_var", "--stdin", env=self.tool_env, stdin=b"v1\n")
        proc = run_tool("get", ENV, "a_var", "--quiet", env=self.tool_env)
        self.assertEqual(proc.stdout, b"v1")
        run_tool("set", ENV, "b_var", "--stdin", "--exact", env=self.tool_env, stdin=b"v2\n")
        proc = run_tool("get", ENV, "b_var", "--quiet", env=self.tool_env)
        self.assertEqual(proc.stdout, b"v2\n")

    def test_get_warns_on_stderr_unless_quiet(self):
        run_tool("set", ENV, "w_var", "--stdin", env=self.tool_env, stdin=b"x")
        loud = run_tool("get", ENV, "w_var", env=self.tool_env)
        self.assertIn(b"plaintext on stdout", loud.stderr)
        quiet = run_tool("get", ENV, "w_var", "--quiet", env=self.tool_env)
        self.assertEqual(quiet.stderr, b"")

    def test_set_replaces_existing_block_without_duplicates(self):
        run_tool("set", ENV, "r_var", "--stdin", env=self.tool_env, stdin=b"one")
        run_tool("set", ENV, "r_var", "--stdin", env=self.tool_env, stdin=b"two")
        stored = self.read_vault(ENV)
        self.assertEqual(stored.count("r_var: !vault |"), 1)
        proc = run_tool("get", ENV, "r_var", "--quiet", env=self.tool_env)
        self.assertEqual(proc.stdout, b"two")

    def test_set_multiple_names_prompts_are_rejected_with_stdin(self):
        proc = run_tool("set", ENV, "a", "b", "--stdin", env=self.tool_env, stdin=b"x")
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"one value", proc.stderr)

    def test_list_shows_names_and_labels(self):
        run_tool("set", ENV, "l_var", "--stdin", env=self.tool_env, stdin=b"v")
        proc = run_tool("list", ENV, env=self.tool_env)
        self.assertIn(b"l_var", proc.stdout)
        self.assertIn(b"progress-test", proc.stdout)

    def test_list_without_env_fails_friendly(self):
        proc = run_tool("list", env=self.tool_env)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn(b"Traceback", proc.stderr)
        self.assertIn(b"provide an environment", proc.stderr)

    def test_list_rejects_env_and_all_together(self):
        proc = run_tool("list", ENV, "--all", env=self.tool_env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"not both", proc.stderr)

    def test_set_interactive_requires_a_tty(self):
        proc = run_tool("set", ENV, "i_var", env=self.tool_env, stdin=b"piped\n")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn(b"Traceback", proc.stderr)
        self.assertIn(b"--stdin", proc.stderr)

    def test_check_rejects_unknown_environment_friendly(self):
        proc = run_tool("check", "bogus", env=self.tool_env)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn(b"Traceback", proc.stderr)
        self.assertIn(b"invalid choice", proc.stderr)

    def test_check_reports_ok_and_missing_env_is_skipped(self):
        run_tool("set", ENV, "c_var", "--stdin", env=self.tool_env, stdin=b"v")
        proc = run_tool("check", env=self.tool_env)
        self.assertIn(f"{ENV}: 1/1 ok".encode(), proc.stdout)
        self.assertIn(b"no vault file, skipped", proc.stdout)
        self.assertEqual(proc.returncode, 0)

    def test_check_fails_on_tampered_block(self):
        run_tool("set", ENV, "t_var", "--stdin", env=self.tool_env, stdin=b"secret-value")
        stored = self.read_vault(ENV)
        idx = stored.rindex("\n") - 2
        tampered = stored[:idx] + ("0" if stored[idx] != "0" else "1") + stored[idx + 1 :]
        self.write_vault(ENV, tampered)
        proc = run_tool("check", ENV, env=self.tool_env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(b"t_var", proc.stdout)

    def test_get_fails_loudly_on_missing_variable(self):
        run_tool("set", ENV, "seed_var", "--stdin", env=self.tool_env, stdin=b"v")
        proc = run_tool("get", ENV, "nope", env=self.tool_env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"nope", proc.stderr)

    def test_remove_deletes_block_and_needs_confirmation(self):
        run_tool("set", ENV, "d_var", "--stdin", env=self.tool_env, stdin=b"v")
        proc = run_tool("remove", ENV, "d_var", env=self.tool_env, stdin=b"n\n")
        self.assertIn(b"aborted", proc.stdout)
        self.assertIn("d_var", self.read_vault(ENV))
        proc = run_tool("remove", ENV, "d_var", "--yes", env=self.tool_env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("d_var", self.read_vault(ENV))

    def test_from_copies_between_environments_without_stdout_leak(self):
        run_tool("set", OTHER, "cp_var", "--stdin", env=self.tool_env, stdin=b"shared")
        proc = run_tool("set", ENV, "cp_var", "--from", OTHER, env=self.tool_env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(b"shared", proc.stdout)
        proc = run_tool("get", ENV, "cp_var", "--quiet", env=self.tool_env)
        self.assertEqual(proc.stdout, b"shared")


if __name__ == "__main__":
    unittest.main()
