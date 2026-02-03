"""
Tests for metric definitions and naming conventions.
"""
import pytest
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the module with hyphen in name
import importlib.util
spec = importlib.util.spec_from_file_location("xen_exporter", "xen-exporter.py")
xen_exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xen_exporter)

METRIC_DEFINITIONS = xen_exporter.METRIC_DEFINITIONS


class TestMetricNaming:
    """Test that metric names follow Prometheus naming conventions."""

    def test_all_metrics_have_xen_prefix(self):
        """All metrics should start with 'xen_' prefix."""
        for metric_key, (prom_name, help_text, labels) in METRIC_DEFINITIONS.items():
            assert prom_name.startswith('xen_'), \
                f"Metric {prom_name} should start with 'xen_' prefix"

    def test_metric_names_are_lowercase(self):
        """All metric names should be lowercase."""
        for metric_key, (prom_name, help_text, labels) in METRIC_DEFINITIONS.items():
            assert prom_name == prom_name.lower(), \
                f"Metric {prom_name} should be lowercase"

    def test_metric_names_use_underscores(self):
        """Metric names should use underscores, not hyphens or other separators."""
        for metric_key, (prom_name, help_text, labels) in METRIC_DEFINITIONS.items():
            assert '-' not in prom_name, \
                f"Metric {prom_name} should use underscores, not hyphens"
            assert ' ' not in prom_name, \
                f"Metric {prom_name} should not contain spaces"

    def test_metric_names_match_pattern(self):
        """Metric names should match Prometheus naming pattern."""
        pattern = re.compile(r'^[a-z_:][a-z0-9_:]*$')
        for metric_key, (prom_name, help_text, labels) in METRIC_DEFINITIONS.items():
            assert pattern.match(prom_name), \
                f"Metric {prom_name} doesn't match Prometheus naming pattern"


class TestMetricLabels:
    """Test that metric labels are properly defined."""

    def test_labels_are_lowercase(self):
        """All label names should be lowercase."""
        for metric_key, (prom_name, help_text, labels) in METRIC_DEFINITIONS.items():
            for label in labels:
                assert label == label.lower(), \
                    f"Label {label} in metric {prom_name} should be lowercase"

    def test_labels_use_underscores(self):
        """Label names should use underscores."""
        for metric_key, (prom_name, help_text, labels) in METRIC_DEFINITIONS.items():
            for label in labels:
                assert '-' not in label, \
                    f"Label {label} in metric {prom_name} should use underscores"

    def test_host_metrics_have_host_labels(self):
        """Host metrics should have host and host_uuid labels."""
        host_metrics = [k for k in METRIC_DEFINITIONS.keys() if k.startswith('host_')]
        for metric_key in host_metrics:
            prom_name, help_text, labels = METRIC_DEFINITIONS[metric_key]
            assert 'host' in labels, \
                f"Host metric {prom_name} should have 'host' label"
            assert 'host_uuid' in labels, \
                f"Host metric {prom_name} should have 'host_uuid' label"

    def test_vm_metrics_have_vm_labels(self):
        """VM metrics should have vm, vm_uuid, host, and host_uuid labels."""
        vm_metrics = [k for k in METRIC_DEFINITIONS.keys() if k.startswith('vm_')]
        for metric_key in vm_metrics:
            prom_name, help_text, labels = METRIC_DEFINITIONS[metric_key]
            assert 'vm' in labels, \
                f"VM metric {prom_name} should have 'vm' label"
            assert 'vm_uuid' in labels, \
                f"VM metric {prom_name} should have 'vm_uuid' label"
            assert 'host' in labels, \
                f"VM metric {prom_name} should have 'host' label"
            assert 'host_uuid' in labels, \
                f"VM metric {prom_name} should have 'host_uuid' label"

    def test_sr_metrics_have_sr_labels(self):
        """SR metrics should have sr and sr_uuid labels."""
        sr_metrics = [k for k in METRIC_DEFINITIONS.keys() if k.startswith('sr_')]
        for metric_key in sr_metrics:
            prom_name, help_text, labels = METRIC_DEFINITIONS[metric_key]
            assert 'sr' in labels, \
                f"SR metric {prom_name} should have 'sr' label"
            assert 'sr_uuid' in labels, \
                f"SR metric {prom_name} should have 'sr_uuid' label"


class TestMetricHelp:
    """Test that metric help text is properly defined."""

    def test_all_metrics_have_help_text(self):
        """All metrics should have non-empty help text."""
        for metric_key, (prom_name, help_text, labels) in METRIC_DEFINITIONS.items():
            assert help_text, \
                f"Metric {prom_name} should have help text"
            assert len(help_text) > 5, \
                f"Metric {prom_name} help text is too short"

    def test_help_text_not_just_metric_name(self):
        """Help text should be more descriptive than just the metric name."""
        for metric_key, (prom_name, help_text, labels) in METRIC_DEFINITIONS.items():
            # Remove prefix and underscores to compare
            simple_name = prom_name.replace('xen_', '').replace('_', ' ')
            assert help_text.lower() != simple_name.lower(), \
                f"Metric {prom_name} help text should be more descriptive"


class TestMetricCoverage:
    """Test that expected metrics are defined."""

    def test_cpu_metrics_exist(self):
        """CPU metrics should be defined for hosts and VMs."""
        assert 'host_cpu' in METRIC_DEFINITIONS
        assert 'host_cpu_avg' in METRIC_DEFINITIONS
        assert 'vm_cpu' in METRIC_DEFINITIONS

    def test_memory_metrics_exist(self):
        """Memory metrics should be defined for hosts and VMs."""
        assert 'host_memory_free_kib' in METRIC_DEFINITIONS
        assert 'host_memory_total_kib' in METRIC_DEFINITIONS
        assert 'vm_memory' in METRIC_DEFINITIONS

    def test_disk_metrics_exist(self):
        """Disk I/O metrics should be defined."""
        assert 'host_read' in METRIC_DEFINITIONS
        assert 'host_write' in METRIC_DEFINITIONS
        assert 'host_iops_read' in METRIC_DEFINITIONS
        assert 'host_iops_write' in METRIC_DEFINITIONS
        assert 'vm_vbd_read' in METRIC_DEFINITIONS
        assert 'vm_vbd_write' in METRIC_DEFINITIONS

    def test_network_metrics_exist(self):
        """Network metrics should be defined."""
        assert 'host_pif_rx' in METRIC_DEFINITIONS
        assert 'host_pif_tx' in METRIC_DEFINITIONS
        assert 'vm_vif_rx' in METRIC_DEFINITIONS
        assert 'vm_vif_tx' in METRIC_DEFINITIONS

    def test_sr_metrics_exist(self):
        """Storage repository metrics should be defined."""
        assert 'sr_physical_size' in METRIC_DEFINITIONS
        assert 'sr_physical_utilization' in METRIC_DEFINITIONS
        assert 'sr_virtual_allocation' in METRIC_DEFINITIONS

    def test_pbd_metrics_exist(self):
        """PBD metrics should be defined."""
        assert 'pbd_attached' in METRIC_DEFINITIONS

    def test_collector_metrics_exist(self):
        """Collector self-metrics should be defined."""
        assert 'collector_duration_seconds' in METRIC_DEFINITIONS
        assert 'up' in METRIC_DEFINITIONS

    def test_up_metric_has_no_labels(self):
        """The xen_up metric should have no labels."""
        prom_name, help_text, labels = METRIC_DEFINITIONS['up']
        assert prom_name == 'xen_up'
        assert labels == []
