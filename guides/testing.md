- Unit test code is placed in the tests/ directory.
- Naming convention for test files: test + the name of the tested module. For example, to test config.py, the test file name should be test_config.py.

## Manual Test Case: Owner Monitoring

1. Copy example config:

```bash
cp config.example.toml config.toml
```

2. In `config.toml`, add an `[[owners]]` entry and ensure `github.gh_token` is valid.

```toml
[[owners]]
type = "organization"
name = "bytedance"
enabled = true
```

3. Run a first check:

```bash
uv run progress -c config.toml
```

Expected behavior:
- A notification is sent for the most recent repository only.

4. Run a second check (without new repos created):

```bash
uv run progress -c config.toml
```

Expected behavior:
- No owner monitoring notification is sent.
