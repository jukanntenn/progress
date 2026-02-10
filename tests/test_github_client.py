"""GitHub API client unit tests"""

import pytest
from unittest.mock import Mock, patch
from progress.github_client import GitHubClient
from progress.errors import GitException


def test_github_client_initialization():
    """Test: GitHubClient initializes with token and proxy"""
    mock_github = Mock()
    with patch('progress.github_client.Github', return_value=mock_github) as mock_ctor:
        client = GitHubClient(token="test_token", proxy="http://proxy")
        mock_ctor.assert_called_once_with("test_token")
        mock_github.set_proxy.assert_called_once_with("http://proxy")


def test_github_client_initialization_without_proxy():
    """Test: GitHubClient initializes without proxy"""
    mock_github = Mock()
    with patch('progress.github_client.Github', return_value=mock_github) as mock_ctor:
        client = GitHubClient(token="test_token")
        mock_ctor.assert_called_once_with("test_token")
        mock_github.set_proxy.assert_not_called()
