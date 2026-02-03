"""
Tests for configuration parsing and validation.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the module with hyphen in name
import importlib.util
spec = importlib.util.spec_from_file_location("xen_exporter", "xen-exporter.py")
xen_exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xen_exporter)

parse_bool_env = xen_exporter.parse_bool_env
parse_credentials = xen_exporter.parse_credentials
get_host_credentials = xen_exporter.get_host_credentials
validate_config = xen_exporter.validate_config


class TestParseBoolEnv:
    """Test boolean environment variable parsing."""

    def test_true_values(self, monkeypatch):
        """Test that 'true', '1', 'yes' are parsed as True."""
        for value in ['true', 'True', 'TRUE', '1', 'yes', 'Yes', 'YES']:
            monkeypatch.setenv('TEST_VAR', value)
            assert parse_bool_env('TEST_VAR') is True

    def test_false_values(self, monkeypatch):
        """Test that other values are parsed as False."""
        for value in ['false', 'False', '0', 'no', 'No', '', 'anything']:
            monkeypatch.setenv('TEST_VAR', value)
            assert parse_bool_env('TEST_VAR') is False

    def test_default_when_not_set(self, monkeypatch):
        """Test default value when environment variable is not set."""
        monkeypatch.delenv('TEST_VAR', raising=False)

        assert parse_bool_env('TEST_VAR', default=False) is False
        assert parse_bool_env('TEST_VAR', default=True) is True


class TestParseCredentials:
    """Test credential parsing."""

    def test_empty_credentials(self):
        """Test empty credentials returns empty dict."""
        result = parse_credentials(None, 'default', 'pass')
        assert result == {}

        result = parse_credentials('', 'default', 'pass')
        assert result == {}

    def test_single_credential(self):
        """Test parsing a single credential line."""
        creds = '192.168.1.100 admin password123'
        result = parse_credentials(creds, 'default', 'pass')

        assert '192.168.1.100' in result
        assert result['192.168.1.100'] == ('admin', 'password123')

    def test_multiple_credentials(self):
        """Test parsing multiple credential lines."""
        creds = '''
            192.168.1.100 admin1 pass1
            192.168.1.101 admin2 pass2
            192.168.1.102 admin3 pass3
        '''
        result = parse_credentials(creds, 'default', 'pass')

        assert len(result) == 3
        assert result['192.168.1.100'] == ('admin1', 'pass1')
        assert result['192.168.1.101'] == ('admin2', 'pass2')
        assert result['192.168.1.102'] == ('admin3', 'pass3')

    def test_quoted_password(self):
        """Test parsing credentials with quoted passwords."""
        creds = "192.168.1.100 admin 'password with spaces'"
        result = parse_credentials(creds, 'default', 'pass')

        assert result['192.168.1.100'] == ('admin', 'password with spaces')

    def test_double_quoted_password(self):
        """Test parsing credentials with double-quoted passwords."""
        creds = '192.168.1.100 admin "password with spaces"'
        result = parse_credentials(creds, 'default', 'pass')

        assert result['192.168.1.100'] == ('admin', 'password with spaces')

    def test_comment_lines_ignored(self):
        """Test that comment lines are ignored."""
        creds = '''
            # This is a comment
            192.168.1.100 admin pass
            # Another comment
        '''
        result = parse_credentials(creds, 'default', 'pass')

        assert len(result) == 1
        assert '192.168.1.100' in result

    def test_empty_lines_ignored(self):
        """Test that empty lines are ignored."""
        creds = '''
            192.168.1.100 admin pass

            192.168.1.101 admin2 pass2

        '''
        result = parse_credentials(creds, 'default', 'pass')

        assert len(result) == 2

    def test_invalid_line_skipped(self):
        """Test that invalid lines are skipped with warning."""
        creds = '''
            192.168.1.100 admin pass
            invalid_line
            192.168.1.101 admin2
        '''
        result = parse_credentials(creds, 'default', 'pass')

        # Only the valid line should be parsed
        assert len(result) == 1
        assert '192.168.1.100' in result


class TestGetHostCredentials:
    """Test host credential lookup."""

    def test_specific_credentials(self):
        """Test that specific credentials are returned for known host."""
        host_creds = {
            '192.168.1.100': ('admin1', 'pass1'),
            '192.168.1.101': ('admin2', 'pass2'),
        }

        result = get_host_credentials('192.168.1.100', host_creds, 'default', 'defaultpass')
        assert result == ('admin1', 'pass1')

    def test_default_credentials(self):
        """Test that default credentials are returned for unknown host."""
        host_creds = {
            '192.168.1.100': ('admin1', 'pass1'),
        }

        result = get_host_credentials('192.168.1.200', host_creds, 'default', 'defaultpass')
        assert result == ('default', 'defaultpass')

    def test_empty_credentials_dict(self):
        """Test with empty credentials dictionary."""
        result = get_host_credentials('192.168.1.100', {}, 'default', 'defaultpass')
        assert result == ('default', 'defaultpass')


class TestValidateConfig:
    """Test configuration validation."""

    def test_valid_config(self, monkeypatch):
        """Test that valid configuration passes validation."""
        monkeypatch.setenv('XEN_HOST', '192.168.1.100')
        monkeypatch.setenv('XEN_PASSWORD', 'secret')
        monkeypatch.setenv('XEN_MODE', 'host')
        monkeypatch.setenv('PORT', '9100')

        # Should not raise
        validate_config()

    def test_invalid_mode(self, monkeypatch):
        """Test that invalid XEN_MODE raises error."""
        monkeypatch.setenv('XEN_MODE', 'invalid')
        monkeypatch.setenv('PORT', '9100')

        with pytest.raises(ValueError, match='XEN_MODE'):
            validate_config()

    def test_invalid_port_non_numeric(self, monkeypatch):
        """Test that non-numeric PORT raises error."""
        monkeypatch.setenv('PORT', 'abc')
        monkeypatch.delenv('XEN_MODE', raising=False)

        with pytest.raises(ValueError, match='PORT'):
            validate_config()

    def test_invalid_port_out_of_range(self, monkeypatch):
        """Test that out-of-range PORT raises error."""
        monkeypatch.setenv('PORT', '70000')
        monkeypatch.delenv('XEN_MODE', raising=False)

        with pytest.raises(ValueError, match='PORT'):
            validate_config()

    def test_port_zero(self, monkeypatch):
        """Test that PORT 0 raises error."""
        monkeypatch.setenv('PORT', '0')
        monkeypatch.delenv('XEN_MODE', raising=False)

        with pytest.raises(ValueError, match='PORT'):
            validate_config()

    def test_missing_host_warning(self, monkeypatch, caplog):
        """Test that missing XEN_HOST logs warning but doesn't fail."""
        monkeypatch.delenv('XEN_HOST', raising=False)
        monkeypatch.setenv('PORT', '9100')
        monkeypatch.delenv('XEN_MODE', raising=False)

        import logging
        with caplog.at_level(logging.WARNING):
            validate_config()

        assert 'XEN_HOST' in caplog.text

    def test_missing_password_warning(self, monkeypatch, caplog):
        """Test that missing XEN_PASSWORD logs warning but doesn't fail."""
        monkeypatch.setenv('XEN_HOST', '192.168.1.100')
        monkeypatch.delenv('XEN_PASSWORD', raising=False)
        monkeypatch.setenv('PORT', '9100')
        monkeypatch.delenv('XEN_MODE', raising=False)

        import logging
        with caplog.at_level(logging.WARNING):
            validate_config()

        assert 'XEN_PASSWORD' in caplog.text
