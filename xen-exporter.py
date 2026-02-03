import base64
import http.server
import logging
import socket
import urllib.request
import time
import traceback
import ssl
import os
import re
import threading
from typing import Any

import pyjson5
import XenAPI
from prometheus_client import (
    CollectorRegistry,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

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
# Prometheus Metrics Registry
# =============================================================================

# Create a custom registry for all xen metrics
# Using a custom registry allows us to clear and rebuild metrics on each scrape
def create_metrics_registry():
    """Create a fresh CollectorRegistry with all metric definitions."""
    registry = CollectorRegistry()

    metrics = {}

    # -------------------------------------------------------------------------
    # Host CPU Metrics
    # -------------------------------------------------------------------------
    metrics['host_cpu'] = Gauge(
        'xen_host_cpu',
        'CPU utilization per core (0-1 ratio)',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_avg'] = Gauge(
        'xen_host_cpu_avg',
        'Average CPU utilization across all cores (0-1 ratio)',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_cpu_avg_freq'] = Gauge(
        'xen_host_cpu_avg_freq',
        'Average CPU frequency in Hz',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_c0'] = Gauge(
        'xen_host_cpu_c0',
        'CPU C0 (active) state time ratio',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_c1'] = Gauge(
        'xen_host_cpu_c1',
        'CPU C1 (halt) state time ratio',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_p0'] = Gauge(
        'xen_host_cpu_p0',
        'CPU P0 power state time ratio',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_p1'] = Gauge(
        'xen_host_cpu_p1',
        'CPU P1 power state time ratio',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_p2'] = Gauge(
        'xen_host_cpu_p2',
        'CPU P2 power state time ratio',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_c2'] = Gauge(
        'xen_host_cpu_c2',
        'CPU C2 state time ratio',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_c3'] = Gauge(
        'xen_host_cpu_c3',
        'CPU C3 state time ratio',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['host_cpu_c4'] = Gauge(
        'xen_host_cpu_c4',
        'CPU C4 state time ratio',
        ['host', 'host_uuid', 'cpu'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Host Memory Metrics
    # -------------------------------------------------------------------------
    metrics['host_memory_free_kib'] = Gauge(
        'xen_host_memory_free_kib',
        'Free memory on host in KiB',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_memory_total_kib'] = Gauge(
        'xen_host_memory_total_kib',
        'Total memory on host in KiB',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_memory_reclaimed'] = Gauge(
        'xen_host_memory_reclaimed',
        'Memory reclaimed from VMs in bytes',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_memory_reclaimed_max'] = Gauge(
        'xen_host_memory_reclaimed_max',
        'Maximum reclaimable memory in bytes',
        ['host', 'host_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Host Disk I/O Metrics
    # -------------------------------------------------------------------------
    metrics['host_read'] = Gauge(
        'xen_host_read',
        'Disk read operations per second',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_write'] = Gauge(
        'xen_host_write',
        'Disk write operations per second',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_read_latency'] = Gauge(
        'xen_host_read_latency',
        'Disk read latency in seconds',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_write_latency'] = Gauge(
        'xen_host_write_latency',
        'Disk write latency in seconds',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_latency'] = Gauge(
        'xen_host_latency',
        'Overall disk latency in seconds',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_iops_read'] = Gauge(
        'xen_host_iops_read',
        'Disk read IOPS',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_iops_write'] = Gauge(
        'xen_host_iops_write',
        'Disk write IOPS',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_iops_total'] = Gauge(
        'xen_host_iops_total',
        'Total disk IOPS',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_io_throughput_read'] = Gauge(
        'xen_host_io_throughput_read',
        'Disk read throughput in bytes/sec',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_io_throughput_write'] = Gauge(
        'xen_host_io_throughput_write',
        'Disk write throughput in bytes/sec',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_io_throughput_total'] = Gauge(
        'xen_host_io_throughput_total',
        'Total disk I/O throughput in bytes/sec',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_avgqu_sz'] = Gauge(
        'xen_host_avgqu_sz',
        'Average I/O queue size',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_inflight'] = Gauge(
        'xen_host_inflight',
        'Number of in-flight I/O operations',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_iowait'] = Gauge(
        'xen_host_iowait',
        'I/O wait time ratio',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Host Network Metrics
    # -------------------------------------------------------------------------
    metrics['host_pif_rx'] = Gauge(
        'xen_host_pif_rx',
        'Physical interface received bytes per second',
        ['host', 'host_uuid', 'pif'],
        registry=registry
    )
    metrics['host_pif_tx'] = Gauge(
        'xen_host_pif_tx',
        'Physical interface transmitted bytes per second',
        ['host', 'host_uuid', 'pif'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Host SR Cache Metrics
    # Note: Using Gauge instead of Counter because RRD provides absolute values
    # -------------------------------------------------------------------------
    metrics['host_sr_cache_hits'] = Gauge(
        'xen_host_sr_cache_hits',
        'Storage repository cache hits (cumulative)',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_sr_cache_misses'] = Gauge(
        'xen_host_sr_cache_misses',
        'Storage repository cache misses',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )
    metrics['host_sr_cache_size'] = Gauge(
        'xen_host_sr_cache_size',
        'Storage repository cache size in bytes',
        ['host', 'host_uuid', 'sr', 'sr_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Host XAPI Metrics
    # -------------------------------------------------------------------------
    metrics['host_xapi_allocation_kib'] = Gauge(
        'xen_host_xapi_allocation_kib',
        'XAPI memory allocation in KiB',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xapi_free_memory_kib'] = Gauge(
        'xen_host_xapi_free_memory_kib',
        'XAPI free memory in KiB',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xapi_live_memory_kib'] = Gauge(
        'xen_host_xapi_live_memory_kib',
        'XAPI live memory in KiB',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xapi_memory_usage_kib'] = Gauge(
        'xen_host_xapi_memory_usage_kib',
        'XAPI memory usage in KiB',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xapi_open_fds'] = Gauge(
        'xen_host_xapi_open_fds',
        'Number of open file descriptors in XAPI',
        ['host', 'host_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Host Pool Metrics
    # -------------------------------------------------------------------------
    metrics['host_pool_session_count'] = Gauge(
        'xen_host_pool_session_count',
        'Number of active pool sessions',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_pool_task_count'] = Gauge(
        'xen_host_pool_task_count',
        'Number of active pool tasks',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_pool_session_creation_rate'] = Gauge(
        'xen_host_pool_session_creation_rate',
        'Rate of pool session creation',
        ['host', 'host_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Other Host Metrics
    # -------------------------------------------------------------------------
    metrics['host_loadavg'] = Gauge(
        'xen_host_loadavg',
        'System load average',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_hostload'] = Gauge(
        'xen_host_hostload',
        'Host load',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_running_domains'] = Gauge(
        'xen_host_running_domains',
        'Number of running domains (VMs)',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_running_vcpus'] = Gauge(
        'xen_host_running_vcpus',
        'Number of running vCPUs',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_dcmi_power_reading'] = Gauge(
        'xen_host_dcmi_power_reading',
        'DCMI power reading in watts',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_tapdisks_in_low_memory_mode'] = Gauge(
        'xen_host_tapdisks_in_low_memory_mode',
        'Number of tapdisks in low memory mode',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_multipath_enabled'] = Gauge(
        'xen_host_multipath_enabled',
        'Whether multipath is enabled on the host (1=enabled, 0=disabled)',
        ['host', 'host_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Host Xenopsd Metrics
    # -------------------------------------------------------------------------
    metrics['host_xenopsd_xc_fdsize'] = Gauge(
        'xen_host_xenopsd_xc_fdsize',
        'Xenopsd XC file descriptor size',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_mem_extra'] = Gauge(
        'xen_host_xenopsd_xc_mem_extra',
        'Xenopsd XC extra memory',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_ocaml_allocation_rate'] = Gauge(
        'xen_host_xenopsd_xc_ocaml_allocation_rate',
        'Xenopsd XC OCaml allocation rate',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_ocaml_free'] = Gauge(
        'xen_host_xenopsd_xc_ocaml_free',
        'Xenopsd XC OCaml free memory',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_ocaml_maybe_live'] = Gauge(
        'xen_host_xenopsd_xc_ocaml_maybe_live',
        'Xenopsd XC OCaml maybe live memory',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_ocaml_total'] = Gauge(
        'xen_host_xenopsd_xc_ocaml_total',
        'Xenopsd XC OCaml total memory',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_rss'] = Gauge(
        'xen_host_xenopsd_xc_rss',
        'Xenopsd XC resident set size',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_threads'] = Gauge(
        'xen_host_xenopsd_xc_threads',
        'Xenopsd XC number of threads',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_vmdata'] = Gauge(
        'xen_host_xenopsd_xc_vmdata',
        'Xenopsd XC VM data size',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_vmlck'] = Gauge(
        'xen_host_xenopsd_xc_vmlck',
        'Xenopsd XC VM locked memory',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_vmpin'] = Gauge(
        'xen_host_xenopsd_xc_vmpin',
        'Xenopsd XC VM pinned memory',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_vmpte'] = Gauge(
        'xen_host_xenopsd_xc_vmpte',
        'Xenopsd XC VM page table entries',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_vmsize'] = Gauge(
        'xen_host_xenopsd_xc_vmsize',
        'Xenopsd XC VM size',
        ['host', 'host_uuid'],
        registry=registry
    )
    metrics['host_xenopsd_xc_vmstk'] = Gauge(
        'xen_host_xenopsd_xc_vmstk',
        'Xenopsd XC VM stack size',
        ['host', 'host_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # VM CPU Metrics
    # -------------------------------------------------------------------------
    metrics['vm_cpu'] = Gauge(
        'xen_vm_cpu',
        'VM CPU utilization per vCPU (0-1 ratio)',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'cpu'],
        registry=registry
    )
    metrics['vm_cpu_usage'] = Gauge(
        'xen_vm_cpu_usage',
        'VM total CPU usage',
        ['vm', 'vm_uuid', 'host', 'host_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # VM Memory Metrics
    # -------------------------------------------------------------------------
    metrics['vm_memory'] = Gauge(
        'xen_vm_memory',
        'VM memory usage in bytes',
        ['vm', 'vm_uuid', 'host', 'host_uuid'],
        registry=registry
    )
    metrics['vm_memory_internal_free'] = Gauge(
        'xen_vm_memory_internal_free',
        'VM internal free memory (guest-reported) in bytes',
        ['vm', 'vm_uuid', 'host', 'host_uuid'],
        registry=registry
    )
    metrics['vm_memory_target'] = Gauge(
        'xen_vm_memory_target',
        'VM memory target in bytes',
        ['vm', 'vm_uuid', 'host', 'host_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # VM VBD (Virtual Block Device) Metrics
    # -------------------------------------------------------------------------
    metrics['vm_vbd_read'] = Gauge(
        'xen_vm_vbd_read',
        'VBD read operations per second',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_write'] = Gauge(
        'xen_vm_vbd_write',
        'VBD write operations per second',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_read_latency'] = Gauge(
        'xen_vm_vbd_read_latency',
        'VBD read latency in seconds',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_write_latency'] = Gauge(
        'xen_vm_vbd_write_latency',
        'VBD write latency in seconds',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_latency'] = Gauge(
        'xen_vm_vbd_latency',
        'VBD overall latency in seconds',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_iops_read'] = Gauge(
        'xen_vm_vbd_iops_read',
        'VBD read IOPS',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_iops_write'] = Gauge(
        'xen_vm_vbd_iops_write',
        'VBD write IOPS',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_iops_total'] = Gauge(
        'xen_vm_vbd_iops_total',
        'VBD total IOPS',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_io_throughput_read'] = Gauge(
        'xen_vm_vbd_io_throughput_read',
        'VBD read throughput in bytes/sec',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_io_throughput_write'] = Gauge(
        'xen_vm_vbd_io_throughput_write',
        'VBD write throughput in bytes/sec',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_io_throughput_total'] = Gauge(
        'xen_vm_vbd_io_throughput_total',
        'VBD total I/O throughput in bytes/sec',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_avgqu_sz'] = Gauge(
        'xen_vm_vbd_avgqu_sz',
        'VBD average I/O queue size',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_inflight'] = Gauge(
        'xen_vm_vbd_inflight',
        'VBD number of in-flight operations',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )
    metrics['vm_vbd_iowait'] = Gauge(
        'xen_vm_vbd_iowait',
        'VBD I/O wait time ratio',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vbd'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # VM VIF (Virtual Interface) Metrics
    # -------------------------------------------------------------------------
    metrics['vm_vif_rx'] = Gauge(
        'xen_vm_vif_rx',
        'VIF received bytes per second',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vif'],
        registry=registry
    )
    metrics['vm_vif_tx'] = Gauge(
        'xen_vm_vif_tx',
        'VIF transmitted bytes per second',
        ['vm', 'vm_uuid', 'host', 'host_uuid', 'vif'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Storage Repository Metrics
    # -------------------------------------------------------------------------
    metrics['sr_physical_size'] = Gauge(
        'xen_sr_physical_size',
        'Total physical size of storage repository in bytes',
        ['sr', 'sr_uuid', 'type', 'content_type'],
        registry=registry
    )
    metrics['sr_physical_utilization'] = Gauge(
        'xen_sr_physical_utilization',
        'Used physical space on storage repository in bytes',
        ['sr', 'sr_uuid', 'type', 'content_type'],
        registry=registry
    )
    metrics['sr_virtual_allocation'] = Gauge(
        'xen_sr_virtual_allocation',
        'Virtual allocation on storage repository in bytes',
        ['sr', 'sr_uuid', 'type', 'content_type'],
        registry=registry
    )
    metrics['sr_multipath_active'] = Gauge(
        'xen_sr_multipath_active',
        'Whether multipath is active for the storage repository (1=active, 0=inactive)',
        ['sr', 'sr_uuid'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # PBD (Physical Block Device) Metrics
    # -------------------------------------------------------------------------
    metrics['pbd_attached'] = Gauge(
        'xen_pbd_attached',
        'PBD connection status (1=attached, 0=detached)',
        ['sr', 'sr_uuid', 'host', 'host_uuid', 'type'],
        registry=registry
    )

    # -------------------------------------------------------------------------
    # Collector Metrics
    # -------------------------------------------------------------------------
    metrics['collector_duration_seconds'] = Gauge(
        'xen_collector_duration_seconds',
        'Time taken to collect all metrics in seconds',
        [],
        registry=registry
    )

    return registry, metrics


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


def collect_sr_usage(session: XenAPI.Session, metrics: dict):
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
            metrics['sr_physical_size'].labels(**labels).set(float(sr_record["physical_size"]))

        if "physical_utilisation" in sr_record:
            metrics['sr_physical_utilization'].labels(**labels).set(float(sr_record["physical_utilisation"]))

        if "virtual_allocation" in sr_record:
            metrics['sr_virtual_allocation'].labels(**labels).set(float(sr_record["virtual_allocation"]))


def collect_pbd_status(session: XenAPI.Session, metrics: dict):
    """
    Collect PBD (Physical Block Device) attachment status metrics.
    Sets metrics indicating whether each PBD is currently attached (1) or detached (0).
    """
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

                # Cache SR record to avoid repeated API calls
                if sr_ref not in sr_cache:
                    sr_cache[sr_ref] = session.xenapi.SR.get_record(sr_ref)
                sr_record = sr_cache[sr_ref]

                # Cache host record to avoid repeated API calls
                if host_ref not in host_cache:
                    host_cache[host_ref] = session.xenapi.host.get_record(host_ref)
                host_record = host_cache[host_ref]

                sr_name = sr_record.get("name_label", "unknown")
                sr_uuid = sr_record.get("uuid", "unknown")
                sr_type = sr_record.get("type", "unknown")
                host_name = host_record.get("name_label", "unknown")
                host_uuid = host_record.get("uuid", "unknown")

                attached = 1 if pbd_record.get("currently_attached", False) else 0

                metrics['pbd_attached'].labels(
                    sr=sr_name,
                    sr_uuid=sr_uuid,
                    host=host_name,
                    host_uuid=host_uuid,
                    type=sr_type
                ).set(attached)

            except Exception as e:
                # Skip this PBD if there's an error, continue with others
                logging.warning("Error processing PBD record: %s", e)
                continue

    except Exception as e:
        # If we can't get PBD records at all, log the error
        # This ensures the exporter continues working even if PBD API fails
        logging.error("Failed to collect PBD status: %s", e)


def collect_multipath_status(session: XenAPI.Session, metrics: dict):
    """
    Collect multipath status metrics for hosts and SRs.
    Sets metrics indicating multipath enablement on hosts and activation on SRs.
    """
    try:
        # Collect host-level multipath status
        host_records = session.xenapi.host.get_all_records()
        for host_ref, host_record in host_records.items():
            try:
                host_name = host_record.get("name_label", "unknown")
                host_uuid = host_record.get("uuid", "unknown")

                # Check multipath in other_config
                other_config = host_record.get("other_config", {})
                multipath_enabled = other_config.get("multipathing", "false")
                enabled_val = 1 if str(multipath_enabled).lower() == "true" else 0

                metrics['host_multipath_enabled'].labels(
                    host=host_name,
                    host_uuid=host_uuid
                ).set(enabled_val)

            except Exception as e:
                logging.warning("Error processing host multipath record: %s", e)
                continue

        # Collect SR-level multipath status via PBDs
        pbd_records = session.xenapi.PBD.get_all_records()
        sr_cache = {}
        sr_multipath_seen = set()

        for pbd_ref, pbd_record in pbd_records.items():
            try:
                sr_ref = pbd_record.get("SR")
                if not sr_ref:
                    continue

                # Cache SR record
                if sr_ref not in sr_cache:
                    sr_cache[sr_ref] = session.xenapi.SR.get_record(sr_ref)
                sr_record = sr_cache[sr_ref]

                sr_name = sr_record.get("name_label", "unknown")
                sr_uuid = sr_record.get("uuid", "unknown")

                # Only emit one metric per SR (not per PBD)
                if sr_uuid in sr_multipath_seen:
                    continue
                sr_multipath_seen.add(sr_uuid)

                # Check device_config for multipath info
                device_config = pbd_record.get("device_config", {})
                multipath_val = device_config.get("multipath", "false")
                multipath_active = 1 if str(multipath_val).lower() == "true" else 0

                metrics['sr_multipath_active'].labels(
                    sr=sr_name,
                    sr_uuid=sr_uuid
                ).set(multipath_active)

            except Exception as e:
                logging.warning("Error processing SR multipath record: %s", e)
                continue

    except Exception as e:
        # If we can't get records, log the error
        # This ensures the exporter continues working even if API fails
        logging.error("Failed to collect multipath status: %s", e)


class Xen:
    def __init__(self, url, username, password, verify_ssl):
        self.session = XenAPI.Session(url, ignore_ssl=not verify_ssl)
        self.session.xenapi.login_with_password(
            username, password, "1.0", "xen-exporter"
        )

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, traceback):
        self.session.xenapi.session.logout()
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


def set_metric_value(metrics: dict, registry: CollectorRegistry, metric_key: str, labels: dict, value: float):
    """Safely set a metric value, creating dynamic metrics if needed."""
    if metric_key not in metrics:
        # Create a dynamic metric for unknown RRD metrics
        metric_name = f"xen_{metric_key}"
        label_names = list(labels.keys())
        try:
            metrics[metric_key] = Gauge(
                metric_name,
                f"Dynamic metric: {metric_key}",
                label_names,
                registry=registry
            )
            logging.debug("Created dynamic metric: %s with labels %s", metric_name, label_names)
        except Exception as e:
            logging.warning("Failed to create dynamic metric %s: %s", metric_key, e)
            return

    try:
        metrics[metric_key].labels(**labels).set(value)
    except Exception as e:
        logging.debug("Failed to set metric %s with labels %s: %s", metric_key, labels, e)


def collect_metrics():
    # Cleanup caches if they've grown too large
    _cleanup_cache_if_needed()

    # Create fresh registry for this scrape
    registry, metrics = create_metrics_registry()

    xen_user = os.getenv("XEN_USER", "root")
    xen_password = os.getenv("XEN_PASSWORD", "")
    xen_host = os.getenv("XEN_HOST", "localhost")
    xen_mode = os.getenv("XEN_MODE", "host")
    verify_ssl = parse_bool_env("XEN_SSL_VERIFY", default=True)
    halt_on_no_uuid = parse_bool_env("HALT_ON_NO_UUID", default=False)

    # Enable/disable PBD and multipath metrics collection (enabled by default)
    collect_pbd = parse_bool_env("XEN_COLLECT_PBD", default=True)
    collect_multipath = parse_bool_env("XEN_COLLECT_MULTIPATH", default=True)

    collector_start_time = time.perf_counter()
    xen_poolmaster = collect_poolmaster(
        xen_user=xen_user,
        xen_password=xen_password,
        xen_host=xen_host,
        verify_ssl=verify_ssl,
    )

    with Xen("https://" + xen_poolmaster, xen_user, xen_password, verify_ssl) as xen:
        if xen_mode == "host":
            xen_hosts = [xen_host]
        else:
            xen_hosts = get_all_hosts_in_pool(xen)

        for current_host in xen_hosts:
            host_name = None
            host_uuid = None
            url = f"https://{current_host}/rrd_updates?start={int(time.time()-DEFAULT_METRICS_WINDOW_SECONDS)}&json=true&host=true&cf=AVERAGE"

            req = urllib.request.Request(url)
            req.add_header(
                "Authorization",
                "Basic "
                + base64.b64encode((xen_user + ":" + xen_password).encode("utf-8")).decode(
                    "utf-8"
                ),
            )
            res = urllib.request.urlopen(
                req,
                context=None if verify_ssl else ssl._create_unverified_context(),
                timeout=HTTP_TIMEOUT_SECONDS
            )
            rrd_metrics = pyjson5.decode_io(res)

            for metric_name in rrd_metrics["meta"]["legend"]:
                metric_legend = metric_name.split(":")[1:]
                if len(metric_legend) < 3:
                    logging.warning("Invalid metric legend format (expected 3+ parts): %s", metric_name)
                    continue
                collector_type = metric_legend[0]
                collector = metric_legend[1]

                if collector_type == 'host':
                    host = get_or_set(hosts, collector, lookup_host_name, xen)
                    host_name = host
                    host_uuid = collector
                    break

            if host_name is None or host_uuid is None:
                raise RuntimeError("Hostname or UUID not found in any retrieved data")

            for metric_idx, metric_name in enumerate(rrd_metrics["meta"]["legend"]):
                metric_legend = metric_name.split(":")[1:]
                if len(metric_legend) < 3:
                    continue  # Already logged in the first loop
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

                # Handle SR metrics which don't have a full UUID (and don't have sr_)
                if (
                    collector_type == "host"
                    and len(metric_type.split("_")[-1]) == SHORT_SR_UUID_LENGTH
                    and "_".join(metric_type.split("_")[0:-1]) in sr_metrics
                ):
                    short_sr = metric_type.split("_")[-1]
                    long_sr = find_full_sr_uuid(short_sr, xen, halt_on_no_uuid)
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

                # Normalize metric names to lowercase and underscores
                metric_type = metric_type.lower().replace("-", "_")

                # Build metric key: {collector_type}_{metric_type}
                metric_key = f"{collector_type}_{metric_type}"
                value = rrd_metrics['data'][0]['values'][metric_idx]

                # Set the metric value using the helper function
                set_metric_value(metrics, registry, metric_key, extra_tags, float(value))

        collect_sr_usage(xen, metrics)

        # Collect PBD status metrics if enabled
        if collect_pbd:
            collect_pbd_status(xen, metrics)

        # Collect multipath status metrics if enabled
        if collect_multipath:
            collect_multipath_status(xen, metrics)

        collector_end_time = time.perf_counter()
        metrics['collector_duration_seconds'].set(collector_end_time - collector_start_time)

        return generate_latest(registry)


class Handler(http.server.BaseHTTPRequestHandler):
    def __init__(self, request: socket.socket, client_address: tuple[str, int], server: Any) -> None:
        super().__init__(request, client_address, server)

    def log_message(self, format: str, *args) -> None:
        """Override to use our configured logger instead of stderr."""
        logging.info("%s - %s", self.address_string(), format % args)

    def do_GET(self):
        # Health check endpoint
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.send_header("Content-Length", "3")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return

        # Metrics endpoint (/ or /metrics)
        if self.path not in ("/", "/metrics"):
            self.send_response(404)
            self.send_header("Content-type", "text/plain")
            error_msg = b"Not Found\n"
            self.send_header("Content-Length", str(len(error_msg)))
            self.end_headers()
            self.wfile.write(error_msg)
            return

        try:
            metric_output = collect_metrics()
            self.send_response(200)
            self.send_header("Content-type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(metric_output)))
            self.end_headers()
            self.wfile.write(metric_output)
        except BaseException:
            error_msg = traceback.format_exc()
            logging.error("Error collecting metrics: %s", error_msg)
            self.send_response(500)
            self.send_header("Content-type", "text/plain")
            error_response = b"Internal Server Error\n"
            self.send_header("Content-Length", str(len(error_response)))
            self.end_headers()
            self.wfile.write(error_response)


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


if __name__ == "__main__":
    validate_config()

    port = os.getenv("PORT", str(DEFAULT_PORT))
    bind = os.getenv("BIND", DEFAULT_BIND_ADDRESS)

    logging.info("Starting xen-exporter on %s:%s", bind, port)
    http.server.HTTPServer(
        (
            bind,
            int(port),
        ),
        Handler,
    ).serve_forever()
