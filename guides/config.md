- Manage configurations with pydantic-settings
- Configuration items are divided into required and optional types:

  - Required configuration items must be specified in configuration files or environment variables; otherwise, an error will be thrown during validation.
  - Optional configuration items must have reasonable default values.

- Configuration item priority: environment variables > configuration files > default values
