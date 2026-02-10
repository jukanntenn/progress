# GitPython and PyGithub Migration Notes

## Overview

Progress now uses native Python libraries for Git and GitHub operations instead of CLI tools.

## Changes

### Removed Dependencies

- **Git binary** - No longer required (GitPython provides native Python bindings)
- **GitHub CLI (gh)** - Only required for initial repository clone (auth handling)

### Added Dependencies

- **GitPython>=3.1.46** - Local Git operations
- **PyGithub>=2.8.1** - GitHub API operations
- **urllib3>=2.6.3** - Required for security (CVE-2026-21441 fix)

## Breaking Changes

None. All configuration and APIs remain the same.

## For Users

If you were previously required to install `git` and `gh`, you now only need:
- `gh` CLI (for initial clone only)
- All Git operations are done via GitPython

## For Developers

See `src/progress/github_client.py` for the new GitHub API client.
See `src/progress/github.py` for the updated GitClient (now using GitPython).
