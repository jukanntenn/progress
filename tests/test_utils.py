"""Tests for utils module"""

import time
from unittest.mock import Mock

import pytest

from progress.utils import sanitize, retry


class TestSanitize:
    """Tests for sanitize function"""

    def test_sanitize_long_string(self):
        """Test sanitization of long string"""
        assert sanitize("ghp_abc123def456xyz789") == "gh***89"

    def test_sanitize_custom_keep_chars(self):
        """Test sanitization with custom keep_chars"""
        assert sanitize("my_secret_password", keep_chars=3) == "my_***ord"

    def test_sanitize_none(self):
        """Test sanitization of None"""
        assert sanitize(None) == "***"

    def test_sanitize_empty_string(self):
        """Test sanitization of empty string"""
        assert sanitize("") == "***"

    def test_sanitize_short_string(self):
        """Test sanitization of short string (length <= keep_chars * 2)"""
        assert sanitize("abc") == "***"
        assert sanitize("abcdef", keep_chars=3) == "***"

    def test_sanitize_exact_length(self):
        """Test sanitization with exact length (keep_chars * 2 + 1)"""
        assert sanitize("abcde", keep_chars=2) == "ab***de"


class TestRetry:
    """Tests for retry decorator"""

    def test_retry_success_first_attempt(self):
        """Test function succeeds on first attempt"""

        @retry(times=3, initial_delay=1)
        def func():
            return "success"

        assert func() == "success"

    def test_retry_success_after_retries(self):
        """Test function succeeds after some retries"""
        attempt_count = 0

        @retry(times=3, initial_delay=0.01)
        def func():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise ValueError("fail")
            return "success"

        assert func() == "success"
        assert attempt_count == 2

    def test_retry_max_retries_exceeded(self):
        """Test function fails after max retries exceeded"""

        @retry(times=2, initial_delay=0.01)
        def func():
            raise ValueError("fail")

        with pytest.raises(ValueError, match="fail"):
            func()

    def test_retry_exponential_backoff(self):
        """Test exponential backoff delay strategy"""
        call_times = []

        @retry(times=3, initial_delay=0.1, backoff="exponential")
        def func():
            call_times.append(time.time())
            if len(call_times) < 2:
                raise ValueError("fail")
            return "success"

        func()

        delay = call_times[1] - call_times[0]
        assert 0.08 < delay < 0.15

    def test_retry_fixed_backoff(self):
        """Test fixed delay strategy"""
        call_times = []

        @retry(times=4, initial_delay=0.05, backoff="fixed")
        def func():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ValueError("fail")
            return "success"

        func()

        for i in range(len(call_times) - 1):
            delay = call_times[i + 1] - call_times[i]
            assert 0.04 < delay < 0.07

    def test_retry_on_retry_callback(self):
        """Test on_retry callback is called"""
        callback_mock = Mock()

        @retry(times=3, initial_delay=0.01, on_retry=callback_mock)
        def func():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            func()

        assert callback_mock.call_count == 2

    def test_retry_callback_receives_args(self):
        """Test on_retry callback receives correct arguments"""
        callback_mock = Mock()

        @retry(times=3, initial_delay=0.01, on_retry=callback_mock)
        def func(a, b, c=None):
            raise ValueError("fail")

        with pytest.raises(ValueError):
            func(1, 2, c=3)

        assert callback_mock.call_count == 2
        call_args = callback_mock.call_args[0]
        assert call_args[0] == (1, 2)
        assert call_args[1] == {"c": 3}
        assert isinstance(call_args[2], ValueError)
        assert isinstance(call_args[3], int)

    def test_retry_specific_exception_type(self):
        """Test retry only catches specified exception types"""

        @retry(times=3, initial_delay=0.01, exceptions=(ValueError,))
        def func():
            raise TypeError("type error")

        with pytest.raises(TypeError, match="type error"):
            func()

    def test_retry_custom_exception_not_caught(self):
        """Test non-specified exceptions are not caught"""

        @retry(times=3, initial_delay=0.01, exceptions=(ValueError,))
        def func():
            raise RuntimeError("runtime error")

        with pytest.raises(RuntimeError, match="runtime error"):
            func()


class TestStripGitSuffix:
    """Test strip_git_suffix function."""

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            # Basic .git suffix removal
            ("owner/repo.git", "owner/repo"),
            ("repo.git", "repo"),
            ("owner/repo", "owner/repo"),
            # Names ending with characters from .git set (regression tests)
            ("OpenList", "OpenList"),  # Ends with 't'
            ("vue.js", "vue.js"),  # Contains '.' and ends with 's'
            ("mygit", "mygit"),  # Ends with 'git'
            ("test.g", "test.g"),  # Ends with 'g'
            ("test.i", "test.i"),  # Ends with 'i'
            ("test.t", "test.t"),  # Ends with 't'
            # Edge cases
            ("", ""),
            ("git", "git"),
            (".git", ""),
            ("a.git", "a"),
            # Multiple .git suffixes (only last one removed)
            ("repo.git.git", "repo.git"),
            # Case sensitivity
            ("repo.GIT", "repo.GIT"),  # Not removed (case-sensitive)
            ("repo.Git", "repo.Git"),  # Not removed (case-sensitive)
        ],
    )
    def test_strip_git_suffix(self, input_name, expected):
        """Test strip_git_suffix removes only .git suffix."""
        from progress.utils import strip_git_suffix

        result = strip_git_suffix(input_name)
        assert result == expected, (
            f"Failed for {input_name!r}: got {result!r}, expected {expected!r}"
        )
