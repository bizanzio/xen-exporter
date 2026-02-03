"""
Pytest fixtures and configuration for xen-exporter tests.
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_xenapi_session():
    """Create a mock XenAPI session with common methods."""
    session = MagicMock()

    # Mock host methods
    session.xenapi.host.get_all.return_value = ['OpaqueRef:host-1']
    session.xenapi.host.get_address.return_value = '192.168.1.100'
    session.xenapi.host.get_name_label.return_value = 'xen-host-1'
    session.xenapi.host.get_by_uuid.return_value = 'OpaqueRef:host-1'
    session.xenapi.host.get_all_records.return_value = {
        'OpaqueRef:host-1': {
            'name_label': 'xen-host-1',
            'uuid': 'host-uuid-1234',
            'other_config': {'multipathing': 'true'}
        }
    }

    # Mock VM methods
    session.xenapi.VM.get_name_label.return_value = 'test-vm'
    session.xenapi.VM.get_by_uuid.return_value = 'OpaqueRef:vm-1'

    # Mock SR methods
    session.xenapi.SR.get_all.return_value = ['OpaqueRef:sr-1']
    session.xenapi.SR.get_name_label.return_value = 'Local Storage'
    session.xenapi.SR.get_by_uuid.return_value = 'OpaqueRef:sr-1'
    session.xenapi.SR.get_uuid.return_value = 'sr-uuid-12345678'
    session.xenapi.SR.get_all_records.return_value = {
        'OpaqueRef:sr-1': {
            'name_label': 'Local Storage',
            'uuid': 'sr-uuid-12345678',
            'type': 'ext',
            'content_type': 'user',
            'physical_size': '1000000000000',
            'physical_utilisation': '500000000000',
            'virtual_allocation': '600000000000'
        }
    }
    session.xenapi.SR.get_record.return_value = {
        'name_label': 'Local Storage',
        'uuid': 'sr-uuid-12345678',
        'type': 'ext'
    }

    # Mock PBD methods
    session.xenapi.PBD.get_all_records.return_value = {
        'OpaqueRef:pbd-1': {
            'SR': 'OpaqueRef:sr-1',
            'host': 'OpaqueRef:host-1',
            'currently_attached': True,
            'device_config': {'multipath': 'true'}
        }
    }

    return session


@pytest.fixture
def mock_rrd_response():
    """Create a mock RRD JSON response."""
    return {
        'meta': {
            'legend': [
                'AVERAGE:host:host-uuid-1234:cpu0',
                'AVERAGE:host:host-uuid-1234:cpu1',
                'AVERAGE:host:host-uuid-1234:memory_free_kib',
                'AVERAGE:host:host-uuid-1234:memory_total_kib',
                'AVERAGE:host:host-uuid-1234:loadavg',
                'AVERAGE:vm:vm-uuid-5678:cpu0',
                'AVERAGE:vm:vm-uuid-5678:memory',
                'AVERAGE:vm:vm-uuid-5678:vbd_xvda_read',
                'AVERAGE:vm:vm-uuid-5678:vif_0_rx',
            ]
        },
        'data': [
            {
                'values': [0.25, 0.30, 8000000, 16000000, 1.5, 0.50, 2000000000, 1000, 5000000]
            }
        ]
    }


@pytest.fixture
def sample_env_config(monkeypatch):
    """Set up sample environment configuration."""
    monkeypatch.setenv('XEN_HOST', '192.168.1.100')
    monkeypatch.setenv('XEN_USER', 'root')
    monkeypatch.setenv('XEN_PASSWORD', 'testpass')
    monkeypatch.setenv('XEN_MODE', 'host')
    monkeypatch.setenv('XEN_SSL_VERIFY', 'false')
    monkeypatch.setenv('PORT', '9100')
    monkeypatch.setenv('BIND', '0.0.0.0')


@pytest.fixture
def clear_caches():
    """Clear global caches before each test."""
    import importlib
    # Import and clear caches
    try:
        from importlib import import_module
        xen_exporter = import_module('xen-exporter')
        xen_exporter.srs.clear()
        xen_exporter.vms.clear()
        xen_exporter.hosts.clear()
        xen_exporter.all_srs.clear()
    except ImportError:
        pass
    yield
