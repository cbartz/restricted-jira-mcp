import os
import tempfile
import unittest
from unittest.mock import patch

from restricted_jira_mcp.config import JiraConfig


class TestConfig(unittest.TestCase):
    def setUp(self):
        # Set minimal required environment variables for most tests
        self.base_env = {
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_EMAIL": "test@example.com",
            "JIRA_ALLOWED_PROJECTS": "PROJ1,PROJ2",
        }

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_required_environment_variables(self):
        """Neither JIRA_API_TOKEN nor JIRA_API_TOKEN_FILE set - should raise ValueError mentioning JIRA_API_TOKEN"""
        with self.assertRaises(ValueError) as cm:
            JiraConfig.from_env()
        self.assertIn("Missing required environment variables: JIRA_BASE_URL, JIRA_EMAIL, JIRA_ALLOWED_PROJECTS, JIRA_API_TOKEN", str(cm.exception))

    @patch.dict(os.environ, {"JIRA_API_TOKEN": "secret"})
    def test_api_token_from_environment_variable(self):
        """API token from JIRA_API_TOKEN environment variable (existing behavior)"""
        with patch.dict(os.environ, {
            **self.base_env,
            "JIRA_API_TOKEN": "secret"
        }):
            config = JiraConfig.from_env()
            self.assertEqual(config.api_token, "secret")

    @patch.dict(os.environ, {}, clear=True)
    def test_api_token_from_file(self):
        """API token from JIRA_API_TOKEN_FILE environment variable"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("secret\n")
            temp_file_path = f.name
        
        try:
            with patch.dict(os.environ, {
                **self.base_env,
                "JIRA_API_TOKEN_FILE": temp_file_path
            }):
                config = JiraConfig.from_env()
                self.assertEqual(config.api_token, "secret")
        finally:
            os.unlink(temp_file_path)

    @patch.dict(os.environ, {}, clear=True)
    def test_api_token_from_file_with_whitespace(self):
        """API token from file with surrounding whitespace should be stripped"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("  secret  \n")
            temp_file_path = f.name
        
        try:
            with patch.dict(os.environ, {
                **self.base_env,
                "JIRA_API_TOKEN_FILE": temp_file_path
            }):
                config = JiraConfig.from_env()
                self.assertEqual(config.api_token, "secret")
        finally:
            os.unlink(temp_file_path)

    @patch.dict(os.environ, {}, clear=True)
    def test_both_token_variables_set(self):
        """Both JIRA_API_TOKEN and JIRA_API_TOKEN_FILE set - should raise ValueError"""
        with patch.dict(os.environ, {
            **self.base_env,
            "JIRA_API_TOKEN": "secret1",
            "JIRA_API_TOKEN_FILE": "/path/to/file"
        }):
            with self.assertRaises(ValueError) as cm:
                JiraConfig.from_env()
            self.assertEqual(str(cm.exception), "Set only one of JIRA_API_TOKEN and JIRA_API_TOKEN_FILE")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_token_file(self):
        """JIRA_API_TOKEN_FILE points to non-existent file - should raise ValueError naming the path"""
        with patch.dict(os.environ, {
            **self.base_env,
            "JIRA_API_TOKEN_FILE": "/non/existent/path"
        }):
            with self.assertRaises(ValueError) as cm:
                JiraConfig.from_env()
            self.assertIn("/non/existent/path", str(cm.exception))

    @patch.dict(os.environ, {}, clear=True)
    def test_empty_token_file(self):
        """JIRA_API_TOKEN_FILE points to empty file - should raise ValueError naming the path"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("")
            temp_file_path = f.name
        
        try:
            with patch.dict(os.environ, {
                **self.base_env,
                "JIRA_API_TOKEN_FILE": temp_file_path
            }):
                with self.assertRaises(ValueError) as cm:
                    JiraConfig.from_env()
                self.assertIn(temp_file_path, str(cm.exception))
        finally:
            os.unlink(temp_file_path)