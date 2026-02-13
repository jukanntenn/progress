# Testing Rules

## Module-Test Correspondence

Test directory structure MUST mirror `src/progress/`, example:

| Source | Test |
|--------|------|
| `src/progress/ai/` | `tests/ai/` |
| `src/progress/config.py` | `tests/test_config.py` |
| `src/progress/db/` | `tests/db/` |
| `src/progress/utils/` | `tests/utils/` |
| `src/progress/utils/text.py` | `tests/utils/test_text.py` |

## Naming

- Test files: `test_<module_name>.py`
- Example: `src/progress/utils/text.py` → `tests/utils/test_text.py`
- Integration tests: `tests/integration.py`
