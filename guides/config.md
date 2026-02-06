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
