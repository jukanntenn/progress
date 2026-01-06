"""Configuration module unit tests"""

import os
import tempfile
from pathlib import Path
import pytest

from progress.config import Config
from progress.enums import Protocol
from progress.errors import ConfigException


@pytest.fixture
def temp_config_file():
    """Create a temporary config file"""
    fd, path = tempfile.mkstemp(suffix=".toml")
    os.close(fd)
    yield path
    # Cleanup
    os.unlink(path)


# ========== Test Cases ==========


def test_load_from_file_with_only_required_fields(temp_config_file):
    """Test: Load config with only required fields from file"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test-key"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test_token_12345"
"""
    Path(temp_config_file).write_text(content)

    config = Config.load_from_file(temp_config_file)

    # Verify required config items
    assert str(config.markpost.url) == "https://markpost.example.com/p/test-key"
    assert (
        str(config.notification.feishu.webhook_url)
        == "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    )
    assert config.github.gh_token == "ghp_test_token_12345"

    # Verify optional config item defaults
    assert config.timezone == "UTC"
    assert config.analysis.max_diff_length == 100000
    assert config.analysis.concurrency == 1
    assert config.github.protocol == Protocol.HTTPS
    assert config.github.proxy == ""
    assert config.repos == []


def test_load_from_env_with_only_required_fields(temp_config_file, monkeypatch):
    """Test: Load config with only required fields from environment variables"""
    # Create an empty TOML file
    Path(temp_config_file).write_text("")

    # Set environment variables
    monkeypatch.setenv(
        "PROGRESS_MARKPOST__URL", "https://markpost.example.com/p/env-key"
    )
    monkeypatch.setenv(
        "PROGRESS_NOTIFICATION__FEISHU__WEBHOOK_URL",
        "https://open.feishu.cn/open-apis/bot/v2/hook/env",
    )
    monkeypatch.setenv("PROGRESS_GITHUB__GH_TOKEN", "ghp_env_token_67890")

    config = Config.load_from_file(temp_config_file)

    # Verify config loaded from environment variables
    assert str(config.markpost.url) == "https://markpost.example.com/p/env-key"
    assert (
        str(config.notification.feishu.webhook_url)
        == "https://open.feishu.cn/open-apis/bot/v2/hook/env"
    )
    assert config.github.gh_token == "ghp_env_token_67890"

    # Verify defaults
    assert config.timezone == "UTC"
    assert config.analysis.max_diff_length == 100000
    assert config.analysis.concurrency == 1


def test_env_overrides_file_config(temp_config_file, monkeypatch):
    """Test: Environment variables properly override file config values"""
    content = """
timezone = "UTC"

[analysis]
max_diff_length = 100000

[markpost]
url = "https://markpost.example.com/p/file-key"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/file"

[github]
gh_token = "ghp_file_token"
protocol = "https"
"""
    Path(temp_config_file).write_text(content)

    # Set environment variables to override partial config
    monkeypatch.setenv("PROGRESS_TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("PROGRESS_ANALYSIS__MAX_DIFF_LENGTH", "200000")
    monkeypatch.setenv("PROGRESS_ANALYSIS__CONCURRENCY", "4")
    monkeypatch.setenv("PROGRESS_GITHUB__GH_TOKEN", "ghp_env_override")
    monkeypatch.setenv("PROGRESS_GITHUB__PROTOCOL", "ssh")

    config = Config.load_from_file(temp_config_file)

    # Verify environment variables override file config
    assert config.timezone == "Asia/Shanghai"
    assert config.analysis.max_diff_length == 200000
    assert config.analysis.concurrency == 4
    assert config.github.gh_token == "ghp_env_override"
    assert config.github.protocol == Protocol.SSH

    # Verify non-overridden config keeps file values
    assert str(config.markpost.url) == "https://markpost.example.com/p/file-key"
    assert (
        str(config.notification.feishu.webhook_url)
        == "https://open.feishu.cn/open-apis/bot/v2/hook/file"
    )


def test_config_file_not_found():
    """Test: Configuration file not found"""
    from progress.errors import ConfigException

    with pytest.raises(ConfigException, match="Configuration file not found"):
        Config.load_from_file("/nonexistent/config.toml")


def test_invalid_timezone(temp_config_file):
    """Test: Invalid timezone"""
    content = """
timezone = "Invalid/Timezone"

[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_invalid_port_range(temp_config_file):
    """Test: Port out of range"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"

[notification.email]
host = "smtp.gmail.com"
port = 99999
from_addr = "test@example.com"
recipient = ["recipient@example.com"]
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_invalid_protocol(temp_config_file):
    """Test: Invalid protocol"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"
protocol = "ftp"
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_invalid_repo_url_format(temp_config_file):
    """Test: Invalid repository URL format"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"

[[repos]]
url = "invalid-url-format"
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_email_partial_config_missing_required_fields(temp_config_file):
    """Test: Email partial config missing required fields"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"

[notification.email]
host = "smtp.gmail.com"
port = 587
# Missing recipient
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException, match="Missing required fields"):
        Config.load_from_file(temp_config_file)


def test_max_diff_length_must_be_positive(temp_config_file):
    """Test: max_diff_length must be > 0"""
    content = """
[analysis]
max_diff_length = 0

[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_concurrency_must_be_at_least_1(temp_config_file):
    """Test: concurrency must be >= 1"""
    content = """
[analysis]
concurrency = 0

[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_missing_required_markpost_url(temp_config_file):
    """Test: Missing required markpost url"""
    content = """
[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_missing_required_webhook_url(temp_config_file):
    """Test: Missing required webhook_url"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[github]
gh_token = "ghp_test"
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_missing_required_gh_token(temp_config_file):
    """Test: Missing required gh_token"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
"""
    Path(temp_config_file).write_text(content)

    with pytest.raises(ConfigException):
        Config.load_from_file(temp_config_file)


def test_empty_repos_list(temp_config_file):
    """Test: Empty repository list"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"
"""
    Path(temp_config_file).write_text(content)

    config = Config.load_from_file(temp_config_file)
    assert config.repos == []


def test_repo_enabled_filtering(temp_config_file):
    """Test: Repository enabled field"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"

[[repos]]
url = "vitejs/vite"
enabled = true

[[repos]]
url = "facebook/react"
enabled = false

[[repos]]
url = "vue/core"
enabled = true
"""
    Path(temp_config_file).write_text(content)

    config = Config.load_from_file(temp_config_file)

    # Verify all repos are loaded
    assert len(config.repos) == 3

    # Verify enabled field
    assert config.repos[0].enabled is True
    assert config.repos[1].enabled is False
    assert config.repos[2].enabled is True

    # Verify filtering logic
    enabled_repos = [r for r in config.repos if r.enabled]
    assert len(enabled_repos) == 2
    assert enabled_repos[0].url == "vitejs/vite"
    assert enabled_repos[1].url == "vue/core"


def test_get_timezone_method(temp_config_file):
    """Test: get_timezone method"""
    content = """
timezone = "Asia/Shanghai"

[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"
"""
    Path(temp_config_file).write_text(content)

    config = Config.load_from_file(temp_config_file)
    tz = config.get_timezone()

    assert str(tz) == "Asia/Shanghai"


def test_email_config_with_ssl(temp_config_file):
    """Test: Email configuration with SSL"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"

[notification.email]
host = "smtp.gmail.com"
port = 465
user = "test@gmail.com"
password = "password"
from_addr = "test@gmail.com"
recipient = ["recipient@example.com"]
starttls = false
ssl = true
"""
    Path(temp_config_file).write_text(content)

    config = Config.load_from_file(temp_config_file)

    assert config.notification.email is not None
    assert config.notification.email.ssl is True
    assert config.notification.email.starttls is False


def test_repo_with_protocol_override(temp_config_file):
    """Test: Repository-level protocol config overrides global config"""
    content = """
[markpost]
url = "https://markpost.example.com/p/test"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

[github]
gh_token = "ghp_test"
protocol = "https"

[[repos]]
url = "vitejs/vite"
protocol = "ssh"

[[repos]]
url = "facebook/react"
# Protocol not specified, should use global config https
"""
    Path(temp_config_file).write_text(content)

    config = Config.load_from_file(temp_config_file)

    assert config.repos[0].protocol == Protocol.SSH
    assert config.repos[1].protocol is None
