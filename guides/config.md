- Manage configurations with pydantic-settings
- Configuration items are divided into required and optional types:

  - Required configuration items must be specified in configuration files or environment variables; otherwise, an error will be thrown during validation.
  - Optional configuration items must have reasonable default values.

- Configuration item priority: environment variables > configuration files > default values

## Owner Monitoring

You can monitor GitHub users and organizations for newly created repositories using the `[[owners]]` section.

### Fields

- `type` (required): `"user"` or `"organization"`
- `name` (required): GitHub username or organization name (cannot be empty)
- `enabled` (optional): `true` or `false` (default: `true`)

### Example

```toml
[[owners]]
type = "organization"
name = "bytedance"
enabled = true

[[owners]]
type = "user"
name = "torvalds"
enabled = true
```

## Proposal Tracking

You can track proposal repositories (EIPs, Rust RFCs, PEPs, Django DEPs) using the `[[proposal_trackers]]` section.

### Fields

- `type` (required): one of `"eip"`, `"rust_rfc"`, `"pep"`, `"django_dep"`
- `repo_url` (required): GitHub repository URL in the form `https://github.com/<owner>/<repo>(.git)`
- `branch` (optional): branch to track (default: `main`)
- `enabled` (optional): `true` or `false` (default: `true`)
- `proposal_dir` (optional): subdirectory to scan within the repo (default: empty)
- `file_pattern` (optional): filename glob pattern (default: empty)

### Example

```toml
[[proposal_trackers]]
type = "eip"
repo_url = "https://github.com/ethereum/EIPs.git"
branch = "master"
enabled = true
proposal_dir = "EIPS"
file_pattern = "eip-*.md"
```
