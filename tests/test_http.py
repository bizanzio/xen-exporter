"""
Tests for HTTP server and endpoints.
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the module with hyphen in name
import importlib.util
spec = importlib.util.spec_from_file_location("xen_exporter", "xen-exporter.py")
xen_exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xen_exporter)

check_xen_connectivity = xen_exporter.check_xen_connectivity
MetricsHandler = xen_exporter.MetricsHandler
ThreadedHTTPServer = xen_exporter.ThreadedHTTPServer


class TestCheckXenConnectivity:
    """Test the check_xen_connectivity function."""

    def test_connectivity_check_returns_tuple(self, monkeypatch):
        """Test that connectivity check returns (bool, str) tuple."""
        monkeypatch.setenv('XEN_HOST', 'invalid.host.local')
        monkeypatch.setenv('XEN_PASSWORD', 'test')
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)

        success, message = check_xen_connectivity()

        assert isinstance(success, bool)
        assert isinstance(message, str)

    def test_connectivity_failure_returns_false(self, monkeypatch):
        """Test that connection failure returns False."""
        monkeypatch.setenv('XEN_HOST', 'invalid.host.local')
        monkeypatch.setenv('XEN_PASSWORD', 'test')
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)

        success, message = check_xen_connectivity()

        assert success is False
        assert 'Cannot connect' in message

    @patch.object(xen_exporter, 'Xen')
    @patch.object(xen_exporter, 'collect_poolmaster')
    def test_connectivity_success(self, mock_poolmaster, mock_xen, monkeypatch):
        """Test that successful connection returns True."""
        monkeypatch.setenv('XEN_HOST', '192.168.1.100')
        monkeypatch.setenv('XEN_PASSWORD', 'test')
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)

        mock_poolmaster.return_value = '192.168.1.100'
        mock_xen.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_xen.return_value.__exit__ = MagicMock(return_value=False)

        success, message = check_xen_connectivity()

        assert success is True
        assert 'Connected' in message


class TestMetricsHandler:
    """Test the MetricsHandler class."""

    def test_handler_class_exists(self):
        """Test that MetricsHandler is defined."""
        assert MetricsHandler is not None

    def test_handler_has_required_methods(self):
        """Test that handler has all required methods."""
        assert hasattr(MetricsHandler, 'do_GET')
        assert hasattr(MetricsHandler, '_handle_health')
        assert hasattr(MetricsHandler, '_handle_ready')
        assert hasattr(MetricsHandler, '_handle_metrics')


class TestThreadedHTTPServer:
    """Test the ThreadedHTTPServer class."""

    def test_server_class_exists(self):
        """Test that ThreadedHTTPServer is defined."""
        assert ThreadedHTTPServer is not None

    def test_server_has_process_request(self):
        """Test that server has threaded request processing."""
        assert hasattr(ThreadedHTTPServer, 'process_request')
