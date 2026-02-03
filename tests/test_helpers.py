"""
Tests for helper functions.
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the module with hyphen in name
import importlib.util
spec = importlib.util.spec_from_file_location("xen_exporter", "xen-exporter.py")
xen_exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xen_exporter)

get_or_set = xen_exporter.get_or_set
lookup_vm_name = xen_exporter.lookup_vm_name
lookup_sr_name_by_uuid = xen_exporter.lookup_sr_name_by_uuid
lookup_host_name = xen_exporter.lookup_host_name
find_full_sr_uuid = xen_exporter.find_full_sr_uuid
_cleanup_cache_if_needed = xen_exporter._cleanup_cache_if_needed
Xen = xen_exporter.Xen
XENAPI_TIMEOUT_SECONDS = xen_exporter.XENAPI_TIMEOUT_SECONDS


class TestGetOrSet:
    """Test the get_or_set cache helper function."""

    def test_sets_new_value(self):
        """Test that new values are set in the dictionary."""
        d = {}
        result = get_or_set(d, 'key1', lambda k, s: f'value_for_{k}', None)

        assert result == 'value_for_key1'
        assert d['key1'] == 'value_for_key1'

    def test_returns_existing_value(self):
        """Test that existing values are returned without calling function."""
        d = {'key1': 'existing_value'}
        call_count = [0]

        def counter(k, s):
            call_count[0] += 1
            return 'new_value'

        result = get_or_set(d, 'key1', counter, None)

        assert result == 'existing_value'
        assert call_count[0] == 0  # Function should not be called

    def test_thread_safety(self):
        """Test that get_or_set is thread-safe."""
        d = {}
        results = []
        call_count = [0]

        def slow_lookup(k, s):
            call_count[0] += 1
            import time
            time.sleep(0.01)  # Simulate slow operation
            return f'value_{call_count[0]}'

        def worker():
            result = get_or_set(d, 'shared_key', slow_lookup, None)
            results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All results should be the same (first computed value)
        assert len(set(results)) == 1
        # Function should only be called once
        assert call_count[0] == 1


class TestLookupFunctions:
    """Test the various lookup helper functions."""

    def test_lookup_vm_name_success(self, mock_xenapi_session):
        """Test successful VM name lookup."""
        result = lookup_vm_name('vm-uuid-123', mock_xenapi_session)
        assert result == 'test-vm'

    def test_lookup_vm_name_failure(self):
        """Test VM name lookup returns UUID on failure."""
        session = MagicMock()
        session.xenapi.VM.get_by_uuid.side_effect = xen_exporter.XenAPI.XenAPI.Failure('Error')

        result = lookup_vm_name('vm-uuid-123', session)
        assert result == 'vm-uuid-123'

    def test_lookup_sr_name_success(self, mock_xenapi_session):
        """Test successful SR name lookup."""
        result = lookup_sr_name_by_uuid('sr-uuid-123', mock_xenapi_session)
        assert result == 'Local Storage'

    def test_lookup_sr_name_failure(self):
        """Test SR name lookup returns UUID on failure."""
        session = MagicMock()
        session.xenapi.SR.get_by_uuid.side_effect = xen_exporter.XenAPI.XenAPI.Failure('Error')

        result = lookup_sr_name_by_uuid('sr-uuid-123', session)
        assert result == 'sr-uuid-123'

    def test_lookup_host_name_success(self, mock_xenapi_session):
        """Test successful host name lookup."""
        result = lookup_host_name('host-uuid-123', mock_xenapi_session)
        assert result == 'xen-host-1'

    def test_lookup_host_name_failure(self):
        """Test host name lookup returns UUID on failure."""
        session = MagicMock()
        session.xenapi.host.get_by_uuid.side_effect = xen_exporter.XenAPI.XenAPI.Failure('Error')

        result = lookup_host_name('host-uuid-123', session)
        assert result == 'host-uuid-123'


class TestFindFullSRUUID:
    """Test the find_full_sr_uuid function."""

    def test_find_existing_uuid(self):
        """Test finding a full UUID from a short prefix."""
        # Populate the all_srs cache
        xen_exporter.all_srs.clear()
        xen_exporter.all_srs.add('12345678-abcd-efgh-ijkl-mnopqrstuvwx')

        session = MagicMock()
        result = find_full_sr_uuid('12345678', session, halt_on_no_uuid=False)

        assert result == '12345678-abcd-efgh-ijkl-mnopqrstuvwx'

    def test_find_uuid_after_refresh(self):
        """Test finding UUID after refreshing the cache."""
        xen_exporter.all_srs.clear()

        session = MagicMock()
        session.xenapi.SR.get_all.return_value = ['OpaqueRef:sr-1']
        session.xenapi.SR.get_uuid.return_value = 'abcd1234-efgh-ijkl-mnop-qrstuvwxyz12'

        # Patch lookup_sr_uuid_by_ref to return the UUID
        with patch.object(xen_exporter, 'lookup_sr_uuid_by_ref',
                         return_value='abcd1234-efgh-ijkl-mnop-qrstuvwxyz12'):
            result = find_full_sr_uuid('abcd1234', session, halt_on_no_uuid=False)

        assert result == 'abcd1234-efgh-ijkl-mnop-qrstuvwxyz12'

    def test_not_found_without_halt(self):
        """Test that None is returned when UUID not found and halt is False."""
        xen_exporter.all_srs.clear()

        session = MagicMock()
        session.xenapi.SR.get_all.return_value = []

        result = find_full_sr_uuid('nonexist', session, halt_on_no_uuid=False)

        assert result is None

    def test_not_found_with_halt(self):
        """Test that exception is raised when UUID not found and halt is True."""
        xen_exporter.all_srs.clear()

        session = MagicMock()
        session.xenapi.SR.get_all.return_value = []

        with pytest.raises(Exception, match='Found no SRs'):
            find_full_sr_uuid('nonexist', session, halt_on_no_uuid=True)

    def test_multiple_matches_raises(self):
        """Test that exception is raised when multiple UUIDs match."""
        xen_exporter.all_srs.clear()
        xen_exporter.all_srs.add('12345678-aaaa-bbbb-cccc-dddddddddddd')
        xen_exporter.all_srs.add('12345678-eeee-ffff-gggg-hhhhhhhhhhhh')

        session = MagicMock()

        with pytest.raises(Exception, match='Found multiple SRs'):
            find_full_sr_uuid('12345678', session, halt_on_no_uuid=False)


class TestXenSessionTimeout:
    """Test the Xen session timeout functionality."""

    def test_default_timeout_constant(self):
        """Test that the default timeout constant is defined."""
        assert XENAPI_TIMEOUT_SECONDS == 60

    def test_timeout_restored_on_error(self):
        """Test that socket timeout is restored after session creation failure."""
        import socket as sock

        original_timeout = sock.getdefaulttimeout()

        # Attempt to create session with invalid URL (will fail)
        try:
            with Xen("https://invalid.host.local", "user", "pass", False):
                pass
        except Exception:
            pass  # Expected to fail

        # Timeout should be restored
        assert sock.getdefaulttimeout() == original_timeout


class TestCacheCleanup:
    """Test cache cleanup functionality."""

    def test_cleanup_when_over_limit(self):
        """Test that caches are cleared when over the limit."""
        # Set caches to be over the limit
        original_max = xen_exporter.CACHE_MAX_SIZE

        # Temporarily reduce max size for testing
        xen_exporter.CACHE_MAX_SIZE = 5

        try:
            xen_exporter.srs.clear()
            xen_exporter.vms.clear()
            xen_exporter.hosts.clear()
            xen_exporter.all_srs.clear()

            # Add more than max entries
            for i in range(10):
                xen_exporter.srs[f'sr-{i}'] = f'name-{i}'
                xen_exporter.vms[f'vm-{i}'] = f'name-{i}'

            _cleanup_cache_if_needed()

            # Caches should be cleared
            assert len(xen_exporter.srs) == 0
            assert len(xen_exporter.vms) == 0
        finally:
            xen_exporter.CACHE_MAX_SIZE = original_max

    def test_no_cleanup_when_under_limit(self):
        """Test that caches are not cleared when under the limit."""
        xen_exporter.srs.clear()
        xen_exporter.vms.clear()
        xen_exporter.hosts.clear()
        xen_exporter.all_srs.clear()

        # Add a few entries (well under the limit)
        xen_exporter.srs['sr-1'] = 'name-1'
        xen_exporter.vms['vm-1'] = 'name-1'

        _cleanup_cache_if_needed()

        # Caches should not be cleared
        assert len(xen_exporter.srs) == 1
        assert len(xen_exporter.vms) == 1
