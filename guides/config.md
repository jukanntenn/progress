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

## Changelog Tracking

You can track software release changelogs from arbitrary URLs using the `[[changelog_trackers]]` section.

### Fields

- `name` (required): a human-readable tracker name
- `url` (required): changelog URL (HTTP/HTTPS)
- `parser_type` (required): one of `"markdown_heading"`, `"html_chinese_version"`
- `enabled` (optional): `true` or `false` (default: `true`)

### Parser Types

- `markdown_heading`: Markdown changelog with headings like `## 1.2.3`; description is the text until the next version heading.
- `html_chinese_version`: HTML changelog with patterns like `uTools v7.5.1`; description is the text until the next version pattern.

### Notification Behavior

- The program checks enabled changelog trackers sequentially on startup.
- The first check always sends a notification (when `last_seen_version` is empty in the database) to help validate configuration.
- New version detection uses string comparison (`latest_version != last_seen_version`).
- If multiple new versions are found since `last_seen_version`, all new versions are included in the generated report.
- When updates exist across trackers, the program generates one merged Markpost report and sends a single notification pointing to it.

### Example

```toml
[[changelog_trackers]]
name = "Vite"
url = "https://raw.githubusercontent.com/vitejs/vite/main/packages/vite/CHANGELOG.md"
parser_type = "markdown_heading"
enabled = true

[[changelog_trackers]]
name = "uTools"
url = "https://www.u-tools.cn/docs/guide/changelog.html"
parser_type = "html_chinese_version"
enabled = false
```

### Troubleshooting

- HTTP failures: confirm the URL is reachable from the runtime environment and does not require authentication.
- Parse errors: verify `parser_type` matches the actual changelog format and that the changelog still contains recognizable version markers.
- Repeated notifications: if notifications fail, `last_seen_version` will not be updated, so the same version may be retried on next run.
