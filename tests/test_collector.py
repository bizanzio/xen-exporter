"""
Tests for the XenCollector class and metric collection logic.
"""
import pytest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the module with hyphen in name
import importlib.util
spec = importlib.util.spec_from_file_location("xen_exporter", "xen-exporter.py")
xen_exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xen_exporter)

XenCollector = xen_exporter.XenCollector
METRIC_DEFINITIONS = xen_exporter.METRIC_DEFINITIONS
SCRAPE_DURATION_HISTOGRAM = xen_exporter.SCRAPE_DURATION_HISTOGRAM


class TestXenCollectorInit:
    """Test XenCollector initialization."""

    def test_default_configuration(self, monkeypatch):
        """Test collector initializes with default configuration."""
        # Clear environment
        for var in ['XEN_HOST', 'XEN_USER', 'XEN_PASSWORD', 'XEN_MODE',
                    'XEN_SSL_VERIFY', 'XEN_CREDENTIALS']:
            monkeypatch.delenv(var, raising=False)

        collector = XenCollector()

        assert collector.xen_host == 'localhost'
        assert collector.xen_user == 'root'
        assert collector.xen_password == ''
        assert collector.xen_mode == 'host'
        assert collector.verify_ssl is True
        assert collector.collect_pbd is True
        assert collector.collect_multipath is True

    def test_custom_configuration(self, monkeypatch):
        """Test collector initializes with custom configuration."""
        monkeypatch.setenv('XEN_HOST', '192.168.1.100')
        monkeypatch.setenv('XEN_USER', 'admin')
        monkeypatch.setenv('XEN_PASSWORD', 'secret')
        monkeypatch.setenv('XEN_MODE', 'pool')
        monkeypatch.setenv('XEN_SSL_VERIFY', 'false')
        monkeypatch.setenv('XEN_COLLECT_PBD', 'false')
        monkeypatch.setenv('XEN_COLLECT_MULTIPATH', 'false')

        collector = XenCollector()

        assert collector.xen_host == '192.168.1.100'
        assert collector.xen_user == 'admin'
        assert collector.xen_password == 'secret'
        assert collector.xen_mode == 'pool'
        assert collector.verify_ssl is False
        assert collector.collect_pbd is False
        assert collector.collect_multipath is False

    def test_credentials_parsing(self, monkeypatch):
        """Test per-host credentials are parsed correctly."""
        monkeypatch.setenv('XEN_CREDENTIALS', '''
            192.168.1.100 admin1 pass1
            192.168.1.101 admin2 'pass with spaces'
        ''')
        monkeypatch.setenv('XEN_USER', 'default')
        monkeypatch.setenv('XEN_PASSWORD', 'defaultpass')

        collector = XenCollector()

        assert '192.168.1.100' in collector.host_credentials
        assert collector.host_credentials['192.168.1.100'] == ('admin1', 'pass1')
        assert '192.168.1.101' in collector.host_credentials
        assert collector.host_credentials['192.168.1.101'] == ('admin2', 'pass with spaces')


class TestMetricStorage:
    """Test the _store_metric method."""

    def test_store_known_metric(self, monkeypatch):
        """Test storing a known metric."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {}
        dynamic = {}

        collector._store_metric(
            collected, dynamic, 'host_cpu',
            {'host': 'test-host', 'host_uuid': 'uuid-123', 'cpu': '0'},
            0.75
        )

        assert 'host_cpu' in collected
        assert ('test-host', 'uuid-123', '0') in collected['host_cpu']
        assert collected['host_cpu'][('test-host', 'uuid-123', '0')] == 0.75

    def test_store_dynamic_metric(self, monkeypatch):
        """Test storing a dynamic (unknown) metric."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {}
        dynamic = {}

        collector._store_metric(
            collected, dynamic, 'unknown_metric',
            {'host': 'test-host', 'host_uuid': 'uuid-123'},
            42.0
        )

        assert 'unknown_metric' in collected
        assert 'unknown_metric' in dynamic
        assert dynamic['unknown_metric'] == ['host', 'host_uuid']

    def test_store_multiple_values_same_metric(self, monkeypatch):
        """Test storing multiple values for the same metric with different labels."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {}
        dynamic = {}

        collector._store_metric(
            collected, dynamic, 'host_cpu',
            {'host': 'host1', 'host_uuid': 'uuid-1', 'cpu': '0'},
            0.25
        )
        collector._store_metric(
            collected, dynamic, 'host_cpu',
            {'host': 'host1', 'host_uuid': 'uuid-1', 'cpu': '1'},
            0.50
        )

        assert len(collected['host_cpu']) == 2
        assert collected['host_cpu'][('host1', 'uuid-1', '0')] == 0.25
        assert collected['host_cpu'][('host1', 'uuid-1', '1')] == 0.50


class TestScrapeHistogram:
    """Test the scrape duration histogram."""

    def test_histogram_exists(self):
        """Test that the scrape duration histogram is defined."""
        assert SCRAPE_DURATION_HISTOGRAM is not None
        assert SCRAPE_DURATION_HISTOGRAM._name == 'xen_scrape_duration_seconds'

    def test_histogram_buckets(self):
        """Test that histogram has appropriate buckets."""
        # Buckets should cover typical scrape times
        buckets = SCRAPE_DURATION_HISTOGRAM._upper_bounds
        assert 0.1 in buckets
        assert 1.0 in buckets
        assert 10.0 in buckets
        assert 30.0 in buckets
        assert float('inf') in buckets


class TestUpMetric:
    """Test the xen_up metric for scrape success/failure tracking."""

    def test_up_metric_on_success(self, monkeypatch):
        """Test that xen_up is 1 when collection succeeds."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {
            'up': {(): 1},
            'collector_duration_seconds': {(): 0.5}
        }
        dynamic = {}

        metrics = list(collector._yield_metrics(collected, dynamic))
        up_metric = next((m for m in metrics if m.name == 'xen_up'), None)

        assert up_metric is not None
        assert up_metric.samples[0].value == 1

    def test_up_metric_on_failure(self, monkeypatch):
        """Test that xen_up is 0 when collection fails."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {
            'up': {(): 0},
            'collector_duration_seconds': {(): 0.1}
        }
        dynamic = {}

        metrics = list(collector._yield_metrics(collected, dynamic))
        up_metric = next((m for m in metrics if m.name == 'xen_up'), None)

        assert up_metric is not None
        assert up_metric.samples[0].value == 0


class TestYieldMetrics:
    """Test the _yield_metrics method."""

    def test_yield_known_metrics(self, monkeypatch):
        """Test yielding known metrics as GaugeMetricFamily."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {
            'host_cpu': {
                ('host1', 'uuid-1', '0'): 0.25,
                ('host1', 'uuid-1', '1'): 0.50,
            }
        }
        dynamic = {}

        metrics = list(collector._yield_metrics(collected, dynamic))

        assert len(metrics) == 1
        assert metrics[0].name == 'xen_host_cpu'
        assert len(metrics[0].samples) == 2

    def test_yield_dynamic_metrics(self, monkeypatch):
        """Test yielding dynamic metrics."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {
            'custom_metric': {
                ('host1', 'uuid-1'): 100.0,
            }
        }
        dynamic = {
            'custom_metric': ['host', 'host_uuid']
        }

        metrics = list(collector._yield_metrics(collected, dynamic))

        assert len(metrics) == 1
        assert metrics[0].name == 'xen_custom_metric'

    def test_yield_collector_duration(self, monkeypatch):
        """Test yielding collector duration metric."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {
            'collector_duration_seconds': {
                (): 1.234
            }
        }
        dynamic = {}

        metrics = list(collector._yield_metrics(collected, dynamic))

        assert len(metrics) == 1
        assert metrics[0].name == 'xen_collector_duration_seconds'
        assert metrics[0].samples[0].value == 1.234


class TestSRUsageCollection:
    """Test SR usage metric collection."""

    def test_collect_sr_usage(self, mock_xenapi_session, monkeypatch):
        """Test collecting SR usage metrics."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {}

        collector._collect_sr_usage(mock_xenapi_session, collected)

        assert 'sr_physical_size' in collected
        assert 'sr_physical_utilization' in collected
        assert 'sr_virtual_allocation' in collected

    def test_sr_usage_labels(self, mock_xenapi_session, monkeypatch):
        """Test that SR metrics have correct labels."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {}

        collector._collect_sr_usage(mock_xenapi_session, collected)

        # Check that labels are in correct order based on METRIC_DEFINITIONS
        label_tuple = list(collected['sr_physical_size'].keys())[0]
        assert len(label_tuple) == 4  # sr, sr_uuid, type, content_type


class TestPBDStatusCollection:
    """Test PBD status metric collection."""

    def test_collect_pbd_status(self, mock_xenapi_session, monkeypatch):
        """Test collecting PBD attachment status."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {}

        collector._collect_pbd_status(mock_xenapi_session, collected)

        assert 'pbd_attached' in collected
        # Value should be 1 (attached)
        values = list(collected['pbd_attached'].values())
        assert 1 in values

    def test_pbd_error_handling(self, monkeypatch):
        """Test that PBD collection handles errors gracefully."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        session = MagicMock()
        session.xenapi.PBD.get_all_records.side_effect = Exception("API Error")

        collector = XenCollector()
        collected = {}

        # Should not raise, just log error
        collector._collect_pbd_status(session, collected)

        assert 'pbd_attached' not in collected


class TestMultipathCollection:
    """Test multipath status metric collection."""

    def test_collect_host_multipath(self, mock_xenapi_session, monkeypatch):
        """Test collecting host multipath status."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {}

        collector._collect_multipath_status(mock_xenapi_session, collected)

        assert 'host_multipath_enabled' in collected
        # Value should be 1 (enabled based on mock)
        values = list(collected['host_multipath_enabled'].values())
        assert 1 in values

    def test_collect_sr_multipath(self, mock_xenapi_session, monkeypatch):
        """Test collecting SR multipath status."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        collector = XenCollector()
        collected = {}

        collector._collect_multipath_status(mock_xenapi_session, collected)

        assert 'sr_multipath_active' in collected

    def test_multipath_error_handling(self, monkeypatch):
        """Test that multipath collection handles errors gracefully."""
        monkeypatch.delenv('XEN_CREDENTIALS', raising=False)
        session = MagicMock()
        session.xenapi.host.get_all_records.side_effect = Exception("API Error")

        collector = XenCollector()
        collected = {}

        # Should not raise, just log error
        collector._collect_multipath_status(session, collected)
