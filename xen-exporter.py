import base64
import logging
import shlex
import signal
import socket
import sys
import urllib.request
import time
import ssl
import os
import re
import threading
from typing import Optional

import pyjson5
import XenAPI
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import REGISTRY, Histogram, Counter, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client.core import GaugeMetricFamily

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


# Configuration constants
DEFAULT_METRICS_WINDOW_SECONDS = 10  # Time window for RRD updates
DEFAULT_PORT = 9100
DEFAULT_BIND_ADDRESS = "0.0.0.0"
SHORT_SR_UUID_LENGTH = 8  # Expected length of abbreviated SR UUIDs
HTTP_TIMEOUT_SECONDS = 30  # Timeout for HTTP requests to Xen hosts
XENAPI_TIMEOUT_SECONDS = 60  # Timeout for XenAPI operations
CACHE_MAX_SIZE = 10000  # Maximum entries per cache before cleanup

# We aggressively cache the SRs, VMs, and hosts to avoid calling XAPI which can double the runtime (~0.8s to ~1.5s)
# Mapping from UUID to human readable name
# Thread lock to protect cache access from concurrent HTTP requests
_cache_lock = threading.Lock()
srs = dict()
vms = dict()
hosts = dict()
all_srs = set()


# =============================================================================
# Persistent Metrics (outside of Collector pattern)
# =============================================================================

# Histogram for scrape duration - this is a persistent metric that accumulates
# across scrapes, unlike the GaugeMetricFamily metrics yielded by the collector.
# Buckets are chosen to cover typical scrape times from fast (0.1s) to slow (30s)
_SCRAPE_DURATION_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 30.0, float('inf'))


def _create_scrape_histogram():
    """Create the scrape duration histogram, handling re-registration gracefully."""
    try:
        return Histogram(
            'xen_scrape_duration_seconds',
            'Histogram of scrape durations in seconds',
            buckets=_SCRAPE_DURATION_BUCKETS
        )
    except ValueError:
        # Already registered (happens during testing when module is reloaded)
        # Return the existing metric from the registry
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == 'xen_scrape_duration_seconds':
                return collector
        raise


SCRAPE_DURATION_HISTOGRAM = _create_scrape_histogram()


# Error types for categorizing scrape failures
ERROR_TYPE_CONNECTION = 'connection'  # Network connectivity issues
ERROR_TYPE_AUTH = 'authentication'     # Authentication failures
ERROR_TYPE_TIMEOUT = 'timeout'         # Request timeouts
ERROR_TYPE_PARSE = 'parse'             # Response parsing errors
ERROR_TYPE_API = 'api'                 # XenAPI errors
ERROR_TYPE_UNKNOWN = 'unknown'         # Uncategorized errors


def _create_error_counter():
    """Create the scrape error counter, handling re-registration gracefully."""
    try:
        return Counter(
            'xen_scrape_errors_total',
            'Total number of scrape errors by type',
            ['error_type']
        )
    except ValueError:
        # Already registered (happens during testing when module is reloaded)
        # For Counter, the _name is without the _total suffix
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == 'xen_scrape_errors':
                return collector
        raise


SCRAPE_ERROR_COUNTER = _create_error_counter()


def classify_error(exception: Exception) -> str:
    """Classify an exception into an error type category."""
    error_str = str(exception).lower()
    error_type = type(exception).__name__

    # Connection errors
    if any(x in error_type.lower() for x in ['connection', 'socket', 'urlopen']):
        return ERROR_TYPE_CONNECTION
    if any(x in error_str for x in ['connection refused', 'network unreachable',
                                     'no route to host', 'name or service not known']):
        return ERROR_TYPE_CONNECTION

    # Timeout errors
    if 'timeout' in error_type.lower() or 'timeout' in error_str:
        return ERROR_TYPE_TIMEOUT

    # Authentication errors
    if any(x in error_str for x in ['401', 'unauthorized', 'authentication',
                                     'permission denied', 'access denied', 'login']):
        return ERROR_TYPE_AUTH
    if 'XenAPI.Failure' in error_type and 'session' in error_str.lower():
        return ERROR_TYPE_AUTH

    # Parse errors
    if any(x in error_type.lower() for x in ['json', 'decode', 'parse', 'value']):
        return ERROR_TYPE_PARSE

    # XenAPI errors
    if 'xenapi' in error_type.lower() or 'xenapi' in error_str:
        return ERROR_TYPE_API

    return ERROR_TYPE_UNKNOWN


# =============================================================================
# Metric Definitions
# =============================================================================

# Metric definitions: (metric_key, prometheus_name, help_text, label_names)
# These define all known metrics that the collector can emit

METRIC_DEFINITIONS = {
    # Host CPU Metrics
    'host_cpu': ('xen_host_cpu', 'CPU utilization per core (0-1 ratio)', ['host', 'host_uuid', 'cpu']),
    'host_cpu_avg': ('xen_host_cpu_avg', 'Average CPU utilization across all cores (0-1 ratio)', ['host', 'host_uuid']),
    'host_cpu_avg_freq': ('xen_host_cpu_avg_freq', 'Average CPU frequency in Hz', ['host', 'host_uuid', 'cpu']),
    'host_cpu_c0': ('xen_host_cpu_c0', 'CPU C0 (active) state time ratio', ['host', 'host_uuid', 'cpu']),
    'host_cpu_c1': ('xen_host_cpu_c1', 'CPU C1 (halt) state time ratio', ['host', 'host_uuid', 'cpu']),
    'host_cpu_c2': ('xen_host_cpu_c2', 'CPU C2 state time ratio', ['host', 'host_uuid', 'cpu']),
    'host_cpu_c3': ('xen_host_cpu_c3', 'CPU C3 state time ratio', ['host', 'host_uuid', 'cpu']),
    'host_cpu_c4': ('xen_host_cpu_c4', 'CPU C4 state time ratio', ['host', 'host_uuid', 'cpu']),
    'host_cpu_p0': ('xen_host_cpu_p0', 'CPU P0 power state time ratio', ['host', 'host_uuid', 'cpu']),
    'host_cpu_p1': ('xen_host_cpu_p1', 'CPU P1 power state time ratio', ['host', 'host_uuid', 'cpu']),
    'host_cpu_p2': ('xen_host_cpu_p2', 'CPU P2 power state time ratio', ['host', 'host_uuid', 'cpu']),

    # Host Memory Metrics
    'host_memory_free_kib': ('xen_host_memory_free_kib', 'Free memory on host in KiB', ['host', 'host_uuid']),
    'host_memory_total_kib': ('xen_host_memory_total_kib', 'Total memory on host in KiB', ['host', 'host_uuid']),
    'host_memory_reclaimed': ('xen_host_memory_reclaimed', 'Memory reclaimed from VMs in bytes', ['host', 'host_uuid']),
    'host_memory_reclaimed_max': ('xen_host_memory_reclaimed_max', 'Maximum reclaimable memory in bytes', ['host', 'host_uuid']),

    # Host Disk I/O Metrics
    'host_read': ('xen_host_read', 'Disk read operations per second', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_write': ('xen_host_write', 'Disk write operations per second', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_read_latency': ('xen_host_read_latency', 'Disk read latency in seconds', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_write_latency': ('xen_host_write_latency', 'Disk write latency in seconds', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_latency': ('xen_host_latency', 'Overall disk latency in seconds', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_iops_read': ('xen_host_iops_read', 'Disk read IOPS', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_iops_write': ('xen_host_iops_write', 'Disk write IOPS', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_iops_total': ('xen_host_iops_total', 'Total disk IOPS', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_io_throughput_read': ('xen_host_io_throughput_read', 'Disk read throughput in bytes/sec', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_io_throughput_write': ('xen_host_io_throughput_write', 'Disk write throughput in bytes/sec', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_io_throughput_total': ('xen_host_io_throughput_total', 'Total disk I/O throughput in bytes/sec', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_avgqu_sz': ('xen_host_avgqu_sz', 'Average I/O queue size', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_inflight': ('xen_host_inflight', 'Number of in-flight I/O operations', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_iowait': ('xen_host_iowait', 'I/O wait time ratio', ['host', 'host_uuid', 'sr', 'sr_uuid']),

    # Host Network Metrics
    'host_pif_rx': ('xen_host_pif_rx', 'Physical interface received bytes per second', ['host', 'host_uuid', 'pif']),
    'host_pif_tx': ('xen_host_pif_tx', 'Physical interface transmitted bytes per second', ['host', 'host_uuid', 'pif']),

    # Host SR Cache Metrics
    'host_sr_cache_hits': ('xen_host_sr_cache_hits', 'Storage repository cache hits (cumulative)', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_sr_cache_misses': ('xen_host_sr_cache_misses', 'Storage repository cache misses', ['host', 'host_uuid', 'sr', 'sr_uuid']),
    'host_sr_cache_size': ('xen_host_sr_cache_size', 'Storage repository cache size in bytes', ['host', 'host_uuid', 'sr', 'sr_uuid']),

    # Host XAPI Metrics
    'host_xapi_allocation_kib': ('xen_host_xapi_allocation_kib', 'XAPI memory allocation in KiB', ['host', 'host_uuid']),
    'host_xapi_free_memory_kib': ('xen_host_xapi_free_memory_kib', 'XAPI free memory in KiB', ['host', 'host_uuid']),
    'host_xapi_live_memory_kib': ('xen_host_xapi_live_memory_kib', 'XAPI live memory in KiB', ['host', 'host_uuid']),
    'host_xapi_memory_usage_kib': ('xen_host_xapi_memory_usage_kib', 'XAPI memory usage in KiB', ['host', 'host_uuid']),
    'host_xapi_open_fds': ('xen_host_xapi_open_fds', 'Number of open file descriptors in XAPI', ['host', 'host_uuid']),

    # Host Pool Metrics
    'host_pool_session_count': ('xen_host_pool_session_count', 'Number of active pool sessions', ['host', 'host_uuid']),
    'host_pool_task_count': ('xen_host_pool_task_count', 'Number of active pool tasks', ['host', 'host_uuid']),
    'host_pool_session_creation_rate': ('xen_host_pool_session_creation_rate', 'Rate of pool session creation', ['host', 'host_uuid']),

    # Other Host Metrics
    'host_loadavg': ('xen_host_loadavg', 'System load average', ['host', 'host_uuid']),
    'host_hostload': ('xen_host_hostload', 'Host load', ['host', 'host_uuid']),
    'host_running_domains': ('xen_host_running_domains', 'Number of running domains (VMs)', ['host', 'host_uuid']),
    'host_running_vcpus': ('xen_host_running_vcpus', 'Number of running vCPUs', ['host', 'host_uuid']),
    'host_dcmi_power_reading': ('xen_host_dcmi_power_reading', 'DCMI power reading in watts', ['host', 'host_uuid']),
    'host_tapdisks_in_low_memory_mode': ('xen_host_tapdisks_in_low_memory_mode', 'Number of tapdisks in low memory mode', ['host', 'host_uuid']),
    'host_multipath_enabled': ('xen_host_multipath_enabled', 'Whether multipath is enabled on the host (1=enabled, 0=disabled)', ['host', 'host_uuid']),

    # Host Xenopsd Metrics
    'host_xenopsd_xc_fdsize': ('xen_host_xenopsd_xc_fdsize', 'Xenopsd XC file descriptor size', ['host', 'host_uuid']),
    'host_xenopsd_xc_mem_extra': ('xen_host_xenopsd_xc_mem_extra', 'Xenopsd XC extra memory', ['host', 'host_uuid']),
    'host_xenopsd_xc_ocaml_allocation_rate': ('xen_host_xenopsd_xc_ocaml_allocation_rate', 'Xenopsd XC OCaml allocation rate', ['host', 'host_uuid']),
    'host_xenopsd_xc_ocaml_free': ('xen_host_xenopsd_xc_ocaml_free', 'Xenopsd XC OCaml free memory', ['host', 'host_uuid']),
    'host_xenopsd_xc_ocaml_maybe_live': ('xen_host_xenopsd_xc_ocaml_maybe_live', 'Xenopsd XC OCaml maybe live memory', ['host', 'host_uuid']),
    'host_xenopsd_xc_ocaml_total': ('xen_host_xenopsd_xc_ocaml_total', 'Xenopsd XC OCaml total memory', ['host', 'host_uuid']),
    'host_xenopsd_xc_rss': ('xen_host_xenopsd_xc_rss', 'Xenopsd XC resident set size', ['host', 'host_uuid']),
    'host_xenopsd_xc_threads': ('xen_host_xenopsd_xc_threads', 'Xenopsd XC number of threads', ['host', 'host_uuid']),
    'host_xenopsd_xc_vmdata': ('xen_host_xenopsd_xc_vmdata', 'Xenopsd XC VM data size', ['host', 'host_uuid']),
    'host_xenopsd_xc_vmlck': ('xen_host_xenopsd_xc_vmlck', 'Xenopsd XC VM locked memory', ['host', 'host_uuid']),
    'host_xenopsd_xc_vmpin': ('xen_host_xenopsd_xc_vmpin', 'Xenopsd XC VM pinned memory', ['host', 'host_uuid']),
    'host_xenopsd_xc_vmpte': ('xen_host_xenopsd_xc_vmpte', 'Xenopsd XC VM page table entries', ['host', 'host_uuid']),
    'host_xenopsd_xc_vmsize': ('xen_host_xenopsd_xc_vmsize', 'Xenopsd XC VM size', ['host', 'host_uuid']),
    'host_xenopsd_xc_vmstk': ('xen_host_xenopsd_xc_vmstk', 'Xenopsd XC VM stack size', ['host', 'host_uuid']),

    # VM CPU Metrics
    'vm_cpu': ('xen_vm_cpu', 'VM CPU utilization per vCPU (0-1 ratio)', ['vm', 'vm_uuid', 'host', 'host_uuid', 'cpu']),
    'vm_cpu_usage': ('xen_vm_cpu_usage', 'VM total CPU usage', ['vm', 'vm_uuid', 'host', 'host_uuid']),

    # VM Memory Metrics
    'vm_memory': ('xen_vm_memory', 'VM memory usage in bytes', ['vm', 'vm_uuid', 'host', 'host_uuid']),
    'vm_memory_internal_free': ('xen_vm_memory_internal_free', 'VM internal free memory (guest-reported) in bytes', ['vm', 'vm_uuid', 'host', 'host_uuid']),
    'vm_memory_target': ('xen_vm_memory_target', 'VM memory target in bytes', ['vm', 'vm_uuid', 'host', 'host_uuid']),

    # VM VBD Metrics
    'vm_vbd_read': ('xen_vm_vbd_read', 'VBD read operations per second', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_write': ('xen_vm_vbd_write', 'VBD write operations per second', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_read_latency': ('xen_vm_vbd_read_latency', 'VBD read latency in seconds', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_write_latency': ('xen_vm_vbd_write_latency', 'VBD write latency in seconds', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_latency': ('xen_vm_vbd_latency', 'VBD overall latency in seconds', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_iops_read': ('xen_vm_vbd_iops_read', 'VBD read IOPS', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_iops_write': ('xen_vm_vbd_iops_write', 'VBD write IOPS', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_iops_total': ('xen_vm_vbd_iops_total', 'VBD total IOPS', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_io_throughput_read': ('xen_vm_vbd_io_throughput_read', 'VBD read throughput in bytes/sec', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_io_throughput_write': ('xen_vm_vbd_io_throughput_write', 'VBD write throughput in bytes/sec', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_io_throughput_total': ('xen_vm_vbd_io_throughput_total', 'VBD total I/O throughput in bytes/sec', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_avgqu_sz': ('xen_vm_vbd_avgqu_sz', 'VBD average I/O queue size', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_inflight': ('xen_vm_vbd_inflight', 'VBD number of in-flight operations', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),
    'vm_vbd_iowait': ('xen_vm_vbd_iowait', 'VBD I/O wait time ratio', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd']),

    # VM VIF Metrics
    'vm_vif_rx': ('xen_vm_vif_rx', 'VIF received bytes per second', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vif']),
    'vm_vif_tx': ('xen_vm_vif_tx', 'VIF transmitted bytes per second', ['vm', 'vm_uuid', 'host', 'host_uuid', 'vif']),

    # Storage Repository Metrics
    'sr_physical_size': ('xen_sr_physical_size', 'Total physical size of storage repository in bytes', ['sr', 'sr_uuid', 'type', 'content_type']),
    'sr_physical_utilization': ('xen_sr_physical_utilization', 'Used physical space on storage repository in bytes', ['sr', 'sr_uuid', 'type', 'content_type']),
    'sr_virtual_allocation': ('xen_sr_virtual_allocation', 'Virtual allocation on storage repository in bytes', ['sr', 'sr_uuid', 'type', 'content_type']),
    'sr_multipath_active': ('xen_sr_multipath_active', 'Whether multipath is active for the storage repository (1=active, 0=inactive)', ['sr', 'sr_uuid']),

    # PBD Metrics
    'pbd_attached': ('xen_pbd_attached', 'PBD connection status (1=attached, 0=detached)', ['sr', 'sr_uuid', 'host', 'host_uuid', 'type']),

    # Collector Metrics
    'collector_duration_seconds': ('xen_collector_duration_seconds', 'Time taken to collect all metrics in seconds', []),
    'up': ('xen_up', 'Whether the last scrape was successful (1 = success, 0 = failure)', []),
}


class XenCollector:
    """
    Prometheus Collector for XenServer/XCP-ng metrics.

    This collector implements the official prometheus_client Collector pattern,
    which is the recommended way to build exporters that fetch metrics from
    external sources on each scrape.
    """

    def __init__(self):
        """Initialize the collector with configuration from environment variables."""
        self.xen_user = os.getenv("XEN_USER", "root")
        self.xen_password = os.getenv("XEN_PASSWORD", "")
        self.xen_host = os.getenv("XEN_HOST", "localhost")
        self.xen_mode = os.getenv("XEN_MODE", "host")
        self.xen_credentials = os.getenv("XEN_CREDENTIALS")
        self.verify_ssl = parse_bool_env("XEN_SSL_VERIFY", default=True)
        self.halt_on_no_uuid = parse_bool_env("HALT_ON_NO_UUID", default=False)
        self.collect_pbd = parse_bool_env("XEN_COLLECT_PBD", default=True)
        self.collect_multipath = parse_bool_env("XEN_COLLECT_MULTIPATH", default=True)

        # Parse per-host credentials
        self.host_credentials = parse_credentials(
            self.xen_credentials, self.xen_user, self.xen_password
        )

    def collect(self):
        """
        Collect metrics from XenServer/XCP-ng.

        This method is called by prometheus_client on each scrape request.
        It yields GaugeMetricFamily objects for each metric.
        """
        # Cleanup caches if they've grown too large
        _cleanup_cache_if_needed()

        # Track collected metrics: metric_key -> {labels_tuple: value}
        collected_metrics = {}
        # Track dynamic metrics discovered during collection
        dynamic_metrics = {}
        # Track scrape success status
        scrape_success = True

        collector_start_time = time.perf_counter()

        try:
            # Get credentials for poolmaster
            poolmaster_user, poolmaster_pass = get_host_credentials(
                self.xen_host, self.host_credentials, self.xen_user, self.xen_password
            )

            xen_poolmaster = collect_poolmaster(
                xen_user=poolmaster_user,
                xen_password=poolmaster_pass,
                xen_host=self.xen_host,
                verify_ssl=self.verify_ssl,
            )

            # Get credentials for the actual poolmaster address
            poolmaster_user, poolmaster_pass = get_host_credentials(
                xen_poolmaster, self.host_credentials, self.xen_user, self.xen_password
            )

            with Xen("https://" + xen_poolmaster, poolmaster_user, poolmaster_pass, self.verify_ssl) as xen:
                if self.xen_mode == "host":
                    xen_hosts = [self.xen_host]
                else:
                    xen_hosts = get_all_hosts_in_pool(xen)

                for current_host in xen_hosts:
                    self._collect_host_metrics(
                        xen, current_host, collected_metrics, dynamic_metrics
                    )

                # Collect SR usage metrics
                self._collect_sr_usage(xen, collected_metrics)

                # Collect PBD status metrics if enabled
                if self.collect_pbd:
                    self._collect_pbd_status(xen, collected_metrics)

                # Collect multipath status metrics if enabled
                if self.collect_multipath:
                    self._collect_multipath_status(xen, collected_metrics)

        except Exception as e:
            logging.error("Error during metric collection: %s", e)
            scrape_success = False
            # Classify and count the error
            error_type = classify_error(e)
            SCRAPE_ERROR_COUNTER.labels(error_type=error_type).inc()
            logging.debug("Error classified as: %s", error_type)
            # Continue to yield whatever metrics we collected

        # Record collection duration
        collector_end_time = time.perf_counter()
        duration = collector_end_time - collector_start_time
        collected_metrics['collector_duration_seconds'] = {(): duration}

        # Record scrape duration in histogram (persistent metric)
        SCRAPE_DURATION_HISTOGRAM.observe(duration)

        # Record scrape success status (1 = success, 0 = failure)
        collected_metrics['up'] = {(): 1 if scrape_success else 0}

        # Yield all collected metrics as GaugeMetricFamily objects
        yield from self._yield_metrics(collected_metrics, dynamic_metrics)

    def _collect_host_metrics(self, xen, current_host, collected_metrics, dynamic_metrics):
        """Collect RRD metrics from a single host."""
        host_name = None
        host_uuid = None

        url = f"https://{current_host}/rrd_updates?start={int(time.time()-DEFAULT_METRICS_WINDOW_SECONDS)}&json=true&host=true&cf=AVERAGE"

        # Get credentials for this specific host
        current_user, current_pass = get_host_credentials(
            current_host, self.host_credentials, self.xen_user, self.xen_password
        )

        req = urllib.request.Request(url)
        req.add_header(
            "Authorization",
            "Basic " + base64.b64encode(
                (current_user + ":" + current_pass).encode("utf-8")
            ).decode("utf-8"),
        )
        res = urllib.request.urlopen(
            req,
            context=None if self.verify_ssl else ssl._create_unverified_context(),
            timeout=HTTP_TIMEOUT_SECONDS
        )
        rrd_metrics = pyjson5.decode_io(res)

        # First pass: find host name and UUID
        for metric_name in rrd_metrics["meta"]["legend"]:
            metric_legend = metric_name.split(":")[1:]
            if len(metric_legend) < 3:
                logging.warning("Invalid metric legend format (expected 3+ parts): %s", metric_name)
                continue
            collector_type = metric_legend[0]
            collector = metric_legend[1]

            if collector_type == 'host':
                host_name = get_or_set(hosts, collector, lookup_host_name, xen)
                host_uuid = collector
                break

        if host_name is None or host_uuid is None:
            raise RuntimeError("Hostname or UUID not found in any retrieved data")

        # Second pass: collect all metrics
        for metric_idx, metric_name in enumerate(rrd_metrics["meta"]["legend"]):
            metric_legend = metric_name.split(":")[1:]
            if len(metric_legend) < 3:
                continue
            collector_type = metric_legend[0]
            collector = metric_legend[1]
            metric_type = metric_legend[2]
            extra_tags = {}

            if collector_type == "vm":
                vm = get_or_set(vms, collector, lookup_vm_name, xen)
                extra_tags["vm"] = vm
                extra_tags["vm_uuid"] = collector
                extra_tags['host'] = host_name
                extra_tags['host_uuid'] = host_uuid
            elif collector_type == 'host':
                extra_tags['host'] = host_name
                extra_tags['host_uuid'] = host_uuid

            if collector_type == "host" and "sr_" in metric_type:
                sr_parts = metric_type.split("sr_", 1)
                if len(sr_parts) > 1 and sr_parts[1]:
                    x = sr_parts[1]
                    x_parts = x.split("_")
                    sr = get_or_set(srs, x_parts[0], lookup_sr_name_by_uuid, xen)
                    extra_tags["sr"] = sr
                    extra_tags["sr_uuid"] = x_parts[0]
                    metric_type = "sr_" + "_".join(x_parts[1:])

            # Handle SR metrics which don't have a full UUID
            if (
                collector_type == "host"
                and len(metric_type.split("_")[-1]) == SHORT_SR_UUID_LENGTH
                and "_".join(metric_type.split("_")[0:-1]) in sr_metrics
            ):
                short_sr = metric_type.split("_")[-1]
                long_sr = find_full_sr_uuid(short_sr, xen, self.halt_on_no_uuid)
                if long_sr is not None:
                    sr = get_or_set(srs, long_sr, lookup_sr_name_by_uuid, xen)
                    extra_tags["sr"] = sr
                    extra_tags["sr_uuid"] = long_sr
                metric_type = "_".join(metric_type.split("_")[0:-1])

            if collector_type == "vm" and "vbd_" in metric_type:
                vbd_parts = metric_type.split("vbd_", 1)
                if len(vbd_parts) > 1 and vbd_parts[1]:
                    x_parts = vbd_parts[1].split("_")
                    extra_tags["vbd"] = x_parts[0]
                    metric_type = "vbd_" + "_".join(x_parts[1:])

            if collector_type == "vm" and "vif_" in metric_type:
                vif_parts = metric_type.split("vif_", 1)
                if len(vif_parts) > 1 and vif_parts[1]:
                    x_parts = vif_parts[1].split("_")
                    extra_tags["vif"] = x_parts[0]
                    metric_type = "vif_" + "_".join(x_parts[1:])

            if collector_type == "host" and "pif_" in metric_type:
                pif_parts = metric_type.split("pif_", 1)
                if len(pif_parts) > 1 and pif_parts[1]:
                    x_parts = pif_parts[1].split("_")
                    extra_tags["pif"] = x_parts[0]
                    metric_type = "pif_" + "_".join(x_parts[1:])

            if "cpu" in metric_type:
                cpu_parts = metric_type.split("cpu", 1)
                if len(cpu_parts) > 1 and cpu_parts[1]:
                    x = cpu_parts[1]
                    if x.isnumeric():
                        extra_tags["cpu"] = x
                        metric_type = "cpu"
                    elif "-" in x:
                        x_parts = x.split("-", 1)
                        extra_tags["cpu"] = x_parts[0]
                        metric_type = "cpu_" + x_parts[1] if len(x_parts) > 1 else "cpu"
            if "CPU" in metric_type:
                cpu_parts = metric_type.split("CPU", 1)
                if len(cpu_parts) > 1 and cpu_parts[1]:
                    x = cpu_parts[1]
                    x_parts = x.split("-")
                    extra_tags["cpu"] = x_parts[0]
                    metric_type = "cpu_" + "_".join(x_parts[1:]) if len(x_parts) > 1 else "cpu"

            # Normalize metric names
            metric_type = metric_type.lower().replace("-", "_")
            metric_key = f"{collector_type}_{metric_type}"
            value = rrd_metrics['data'][0]['values'][metric_idx]

            # Store metric value
            self._store_metric(
                collected_metrics, dynamic_metrics, metric_key, extra_tags, float(value)
            )

    def _store_metric(self, collected_metrics, dynamic_metrics, metric_key, labels, value):
        """Store a metric value for later yielding."""
        # Determine label names for this metric
        if metric_key in METRIC_DEFINITIONS:
            label_names = METRIC_DEFINITIONS[metric_key][2]
        else:
            # Dynamic metric - record its label names
            label_names = list(labels.keys())
            if metric_key not in dynamic_metrics:
                dynamic_metrics[metric_key] = label_names
                logging.debug("Discovered dynamic metric: %s with labels %s", metric_key, label_names)

        # Create labels tuple in correct order
        labels_tuple = tuple(labels.get(ln, '') for ln in label_names)

        # Initialize metric dict if needed
        if metric_key not in collected_metrics:
            collected_metrics[metric_key] = {}

        collected_metrics[metric_key][labels_tuple] = value

    def _collect_sr_usage(self, session, collected_metrics):
        """Collect storage repository usage metrics."""
        sr_records = session.xenapi.SR.get_all_records()
        for sr_record in sr_records.values():
            sr_name_label = sr_record["name_label"]
            sr_uuid = sr_record["uuid"]
            sr_type = sr_record["type"]
            content_type = sr_record["content_type"]

            labels = {
                'sr': sr_name_label,
                'sr_uuid': sr_uuid,
                'type': sr_type,
                'content_type': content_type
            }

            if "physical_size" in sr_record:
                self._store_metric(
                    collected_metrics, {}, 'sr_physical_size',
                    labels, float(sr_record["physical_size"])
                )

            if "physical_utilisation" in sr_record:
                self._store_metric(
                    collected_metrics, {}, 'sr_physical_utilization',
                    labels, float(sr_record["physical_utilisation"])
                )

            if "virtual_allocation" in sr_record:
                self._store_metric(
                    collected_metrics, {}, 'sr_virtual_allocation',
                    labels, float(sr_record["virtual_allocation"])
                )

    def _collect_pbd_status(self, session, collected_metrics):
        """Collect PBD attachment status metrics."""
        try:
            pbd_records = session.xenapi.PBD.get_all_records()
            sr_cache = {}
            host_cache = {}

            for pbd_ref, pbd_record in pbd_records.items():
                try:
                    sr_ref = pbd_record.get("SR")
                    host_ref = pbd_record.get("host")

                    if not sr_ref or not host_ref:
                        continue

                    if sr_ref not in sr_cache:
                        sr_cache[sr_ref] = session.xenapi.SR.get_record(sr_ref)
                    sr_record = sr_cache[sr_ref]

                    if host_ref not in host_cache:
                        host_cache[host_ref] = session.xenapi.host.get_record(host_ref)
                    host_record = host_cache[host_ref]

                    sr_name = sr_record.get("name_label", "unknown")
                    sr_uuid = sr_record.get("uuid", "unknown")
                    sr_type = sr_record.get("type", "unknown")
                    host_name = host_record.get("name_label", "unknown")
                    host_uuid = host_record.get("uuid", "unknown")

                    attached = 1 if pbd_record.get("currently_attached", False) else 0

                    labels = {
                        'sr': sr_name,
                        'sr_uuid': sr_uuid,
                        'host': host_name,
                        'host_uuid': host_uuid,
                        'type': sr_type
                    }
                    self._store_metric(collected_metrics, {}, 'pbd_attached', labels, attached)

                except Exception as e:
                    logging.warning("Error processing PBD record: %s", e)
                    continue

        except Exception as e:
            logging.error("Failed to collect PBD status: %s", e)

    def _collect_multipath_status(self, session, collected_metrics):
        """Collect multipath status metrics for hosts and SRs."""
        try:
            # Host-level multipath status
            host_records = session.xenapi.host.get_all_records()
            for host_ref, host_record in host_records.items():
                try:
                    host_name = host_record.get("name_label", "unknown")
                    host_uuid = host_record.get("uuid", "unknown")

                    other_config = host_record.get("other_config", {})
                    multipath_enabled = other_config.get("multipathing", "false")
                    enabled_val = 1 if str(multipath_enabled).lower() == "true" else 0

                    labels = {'host': host_name, 'host_uuid': host_uuid}
                    self._store_metric(
                        collected_metrics, {}, 'host_multipath_enabled', labels, enabled_val
                    )

                except Exception as e:
                    logging.warning("Error processing host multipath record: %s", e)
                    continue

            # SR-level multipath status via PBDs
            pbd_records = session.xenapi.PBD.get_all_records()
            sr_cache = {}
            sr_multipath_seen = set()

            for pbd_ref, pbd_record in pbd_records.items():
                try:
                    sr_ref = pbd_record.get("SR")
                    if not sr_ref:
                        continue

                    if sr_ref not in sr_cache:
                        sr_cache[sr_ref] = session.xenapi.SR.get_record(sr_ref)
                    sr_record = sr_cache[sr_ref]

                    sr_name = sr_record.get("name_label", "unknown")
                    sr_uuid = sr_record.get("uuid", "unknown")

                    if sr_uuid in sr_multipath_seen:
                        continue
                    sr_multipath_seen.add(sr_uuid)

                    device_config = pbd_record.get("device_config", {})
                    multipath_val = device_config.get("multipath", "false")
                    multipath_active = 1 if str(multipath_val).lower() == "true" else 0

                    labels = {'sr': sr_name, 'sr_uuid': sr_uuid}
                    self._store_metric(
                        collected_metrics, {}, 'sr_multipath_active', labels, multipath_active
                    )

                except Exception as e:
                    logging.warning("Error processing SR multipath record: %s", e)
                    continue

        except Exception as e:
            logging.error("Failed to collect multipath status: %s", e)

    def _yield_metrics(self, collected_metrics, dynamic_metrics):
        """Yield GaugeMetricFamily objects for all collected metrics."""
        for metric_key, values in collected_metrics.items():
            if metric_key in METRIC_DEFINITIONS:
                prom_name, help_text, label_names = METRIC_DEFINITIONS[metric_key]
            elif metric_key in dynamic_metrics:
                prom_name = f"xen_{metric_key}"
                help_text = f"Dynamic metric: {metric_key}"
                label_names = dynamic_metrics[metric_key]
            else:
                continue

            gauge = GaugeMetricFamily(prom_name, help_text, labels=label_names)

            for labels_tuple, value in values.items():
                gauge.add_metric(list(labels_tuple), value)

            yield gauge


def _cleanup_cache_if_needed():
    """Clear caches if they exceed the maximum size to prevent unbounded memory growth."""
    global srs, vms, hosts, all_srs
    with _cache_lock:
        if len(srs) > CACHE_MAX_SIZE:
            logging.info("Clearing SR cache (size: %d)", len(srs))
            srs = dict()
        if len(vms) > CACHE_MAX_SIZE:
            logging.info("Clearing VM cache (size: %d)", len(vms))
            vms = dict()
        if len(hosts) > CACHE_MAX_SIZE:
            logging.info("Clearing host cache (size: %d)", len(hosts))
            hosts = dict()
        if len(all_srs) > CACHE_MAX_SIZE:
            logging.info("Clearing all_srs cache (size: %d)", len(all_srs))
            all_srs = set()

def get_all_hosts_in_pool(session):
    host_addresses = []
    xen_hosts = session.xenapi.host.get_all()
    for host in xen_hosts:
        host_addresses.append(session.xenapi.host.get_address(host))
    return host_addresses

def lookup_vm_name(vm_uuid, session):
    try:
        return session.xenapi.VM.get_name_label(session.xenapi.VM.get_by_uuid(vm_uuid))
    except XenAPI.XenAPI.Failure as e:
        logging.debug("Failed to lookup VM name for %s: %s", vm_uuid, e)
        return vm_uuid


def lookup_sr_name_by_uuid(sr_uuid, session):
    try:
        return session.xenapi.SR.get_name_label(session.xenapi.SR.get_by_uuid(sr_uuid))
    except XenAPI.XenAPI.Failure as e:
        logging.debug("Failed to lookup SR name for %s: %s", sr_uuid, e)
        return sr_uuid


def lookup_host_name(host_uuid, session):
    try:
        return session.xenapi.host.get_name_label(
            session.xenapi.host.get_by_uuid(host_uuid)
        )
    except XenAPI.XenAPI.Failure as e:
        logging.debug("Failed to lookup host name for %s: %s", host_uuid, e)
        return host_uuid


def lookup_sr_uuid_by_ref(sr_ref, session):
    try:
        return session.xenapi.SR.get_uuid(sr_ref)
    except XenAPI.XenAPI.Failure as e:
        logging.debug("Failed to lookup SR UUID for ref %s: %s", sr_ref, e)
        return sr_ref


def find_full_sr_uuid(beginning_uuid, xen, halt_on_no_uuid):
    for _ in range(2):
        with _cache_lock:
            uuid = list(filter(lambda x: x.startswith(beginning_uuid), all_srs))
        if len(uuid) == 0:
            new_srs = set(
                map(
                    lambda x: lookup_sr_uuid_by_ref(x, xen),
                    xen.xenapi.SR.get_all(),
                )
            )
            with _cache_lock:
                all_srs.update(new_srs)
            continue  # skip the rest of the loop and try the search again
        elif len(uuid) > 1:
            raise Exception(f"Found multiple SRs starting with UUID {beginning_uuid}")
        uuid = uuid[0]
        return uuid
    if halt_on_no_uuid:
        raise Exception(f"Found no SRs starting with UUID {beginning_uuid}")
    return None


def get_or_set(d, key, func, *args):
    with _cache_lock:
        if key not in d:
            d[key] = func(key, *args)
        return d[key]


def collect_poolmaster(
    xen_user: str, xen_password: str, xen_host: str, verify_ssl: bool
):
    try:
        with Xen("https://" + xen_host, xen_user, xen_password, verify_ssl):
            poolmaster = xen_host
    except XenAPI.XenAPI.Failure as e:
        ipPattern = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
        ma = re.findall(ipPattern, str(e))
        if ma is not None and len(ma)>1 :
            poolmaster = ma[0]
        else:
            poolmaster = xen_host
    return poolmaster




class Xen:
    """Context manager for XenAPI sessions with timeout support.

    Sets a socket timeout during session operations to prevent indefinite
    blocking when XenServer is unresponsive.
    """

    def __init__(self, url, username, password, verify_ssl, timeout=XENAPI_TIMEOUT_SECONDS):
        self.timeout = timeout
        self._previous_timeout = None

        # Set timeout before creating session
        self._previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self.timeout)

        try:
            self.session = XenAPI.Session(url, ignore_ssl=not verify_ssl)
            self.session.xenapi.login_with_password(
                username, password, "1.0", "xen-exporter"
            )
        except Exception:
            # Restore timeout on error
            socket.setdefaulttimeout(self._previous_timeout)
            raise

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.session.xenapi.session.logout()
        except Exception as e:
            logging.debug("Error during session logout: %s", e)
        finally:
            # Always restore the previous timeout
            socket.setdefaulttimeout(self._previous_timeout)
        return False


# Known SR metrics whose legends include the beginning of the UUID, rather than the full UUID
sr_metrics = {
    "io_throughput_total",
    "avgqu_sz",
    "inflight",
    "iops_write",
    "iops_total",
    "io_throughput_read",
    "read",
    "latency",
    "write_latency",
    "write",
    "io_throughput_write",
    "iowait",
    "read_latency",
    "iops_read",
}


def parse_bool_env(env_var: str, default: bool = False) -> bool:
    """Parse a boolean environment variable safely.

    Accepts 'true', '1', 'yes' (case-insensitive) as True, anything else as False.
    """
    value = os.getenv(env_var)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def parse_credentials(xen_credentials: Optional[str], default_user: str, default_password: str) -> dict:
    """Parse XEN_CREDENTIALS environment variable into a dict of host -> (user, password).

    Format: one entry per line, each line has: host user password
    Passwords with spaces can be quoted with single or double quotes.

    Example:
        10.10.10.1 admin1 password1
        10.10.10.2 admin2 'password with spaces'

    Returns:
        dict mapping host address to (username, password) tuple
    """
    credentials = {}

    if not xen_credentials:
        return credentials

    for line in xen_credentials.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        try:
            # Use shlex to handle quoted passwords
            parts = shlex.split(line)
            if len(parts) < 3:
                logging.warning("Invalid credential line (need host user password): %s", line)
                continue

            host, user, password = parts[0], parts[1], parts[2]
            credentials[host] = (user, password)
            logging.debug("Loaded credentials for host: %s", host)

        except ValueError as e:
            logging.warning("Failed to parse credential line '%s': %s", line, e)
            continue

    return credentials


def get_host_credentials(
    host: str,
    host_credentials: dict,
    default_user: str,
    default_password: str
) -> tuple:
    """Get credentials for a specific host, falling back to defaults."""
    if host in host_credentials:
        return host_credentials[host]
    return (default_user, default_password)




def check_xen_connectivity():
    """
    Check if we can connect to XenServer.

    Returns:
        tuple: (success: bool, message: str)
    """
    xen_user = os.getenv("XEN_USER", "root")
    xen_password = os.getenv("XEN_PASSWORD", "")
    xen_host = os.getenv("XEN_HOST", "localhost")
    xen_credentials = os.getenv("XEN_CREDENTIALS")
    verify_ssl = parse_bool_env("XEN_SSL_VERIFY", default=True)

    host_credentials = parse_credentials(xen_credentials, xen_user, xen_password)

    try:
        poolmaster_user, poolmaster_pass = get_host_credentials(
            xen_host, host_credentials, xen_user, xen_password
        )

        xen_poolmaster = collect_poolmaster(
            xen_user=poolmaster_user,
            xen_password=poolmaster_pass,
            xen_host=xen_host,
            verify_ssl=verify_ssl,
        )

        poolmaster_user, poolmaster_pass = get_host_credentials(
            xen_poolmaster, host_credentials, xen_user, xen_password
        )

        # Quick connectivity check - just login and logout
        with Xen("https://" + xen_poolmaster, poolmaster_user, poolmaster_pass, verify_ssl, timeout=10):
            pass

        return True, "Connected to XenServer"

    except Exception as e:
        error_type = classify_error(e)
        return False, f"Cannot connect to XenServer: {error_type} - {str(e)}"


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for metrics, health, and readiness endpoints."""

    # Class-level collector reference (set during server setup)
    collector = None

    def log_message(self, format: str, *args) -> None:
        """Override to use our configured logger instead of stderr."""
        logging.info("%s - %s", self.address_string(), format % args)

    def do_GET(self):
        """Handle GET requests for all endpoints."""
        if self.path == '/health':
            self._handle_health()
        elif self.path == '/ready':
            self._handle_ready()
        elif self.path in ('/', '/metrics'):
            self._handle_metrics()
        else:
            self._send_response(404, 'text/plain', b'Not Found\n')

    def _handle_health(self):
        """Handle /health endpoint - basic liveness check."""
        self._send_response(200, 'text/plain', b'OK\n')

    def _handle_ready(self):
        """Handle /ready endpoint - check XenServer connectivity."""
        success, message = check_xen_connectivity()
        status = 200 if success else 503
        self._send_response(status, 'text/plain', (message + '\n').encode('utf-8'))

    def _handle_metrics(self):
        """Handle /metrics endpoint - Prometheus metrics."""
        try:
            output = generate_latest(REGISTRY)
            self._send_response(200, CONTENT_TYPE_LATEST, output)
        except Exception as e:
            logging.error("Error generating metrics: %s", e)
            self._send_response(500, 'text/plain', b'Internal Server Error\n')

    def _send_response(self, status: int, content_type: str, body: bytes):
        """Send an HTTP response."""
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(HTTPServer):
    """HTTP server that handles each request in a separate thread."""

    def process_request(self, request, client_address):
        """Start a new thread for each request."""
        thread = threading.Thread(target=self._handle_request_thread,
                                  args=(request, client_address))
        thread.daemon = True
        thread.start()

    def _handle_request_thread(self, request, client_address):
        """Handle a request in a separate thread."""
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def validate_config():
    """Validate environment variables at startup."""
    errors = []

    # Validate XEN_HOST is set (required for operation)
    xen_host = os.getenv("XEN_HOST")
    if not xen_host:
        logging.warning("XEN_HOST not set, using default 'localhost'")

    # Warn if XEN_PASSWORD is empty
    xen_password = os.getenv("XEN_PASSWORD")
    if not xen_password:
        logging.warning("XEN_PASSWORD not set or empty - authentication may fail")

    # Validate XEN_MODE
    xen_mode = os.getenv("XEN_MODE")
    if xen_mode and xen_mode not in ("host", "pool"):
        errors.append(f"XEN_MODE must be 'host' or 'pool', got: {xen_mode}")

    # Validate PORT is numeric
    port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        port_int = int(port)
        if port_int < 1 or port_int > 65535:
            errors.append(f"PORT must be between 1 and 65535, got: {port}")
    except ValueError:
        errors.append(f"PORT must be a number, got: {port}")

    if errors:
        for error in errors:
            logging.error("Configuration error: %s", error)
        raise ValueError("Invalid configuration: " + "; ".join(errors))


def main():
    """Main entry point for the exporter."""
    validate_config()

    port = int(os.getenv("PORT", str(DEFAULT_PORT)))
    bind = os.getenv("BIND", DEFAULT_BIND_ADDRESS)

    # Register the XenCollector with the global registry
    REGISTRY.register(XenCollector())

    # Create and start the threaded HTTP server
    logging.info("Starting xen-exporter on %s:%s", bind, port)
    logging.info("Endpoints: /metrics, /health, /ready")
    server = ThreadedHTTPServer((bind, port), MetricsHandler)

    # Set up signal handlers for graceful shutdown
    shutdown_event = threading.Event()

    def signal_handler(signum, frame):
        signame = signal.Signals(signum).name
        logging.info("Received %s, shutting down...", signame)
        shutdown_event.set()
        server.shutdown()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Start server in a separate thread
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    # Wait for shutdown signal
    logging.info("Exporter is ready. Press Ctrl+C to stop.")
    shutdown_event.wait()

    logging.info("Exporter stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
