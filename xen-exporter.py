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

def collect_sr_usage(session: XenAPI.Session):
    sr_records = session.xenapi.SR.get_all_records()
    output = ""
    for sr_record in sr_records.values():
        sr_name_label = sr_record["name_label"]
        sr_uuid = sr_record["uuid"]
        if "physical_size" in sr_record:
            output += f'xen_sr_physical_size{{sr_uuid="{sr_uuid}", sr="{sr_name_label}", type="{sr_record["type"]}", content_type="{sr_record["content_type"]}"}} {str(sr_record["physical_size"])}\n'

        if "physical_utilisation" in sr_record:
            output += f'xen_sr_physical_utilization{{sr_uuid="{sr_uuid}", sr="{sr_name_label}", type="{sr_record["type"]}", content_type="{sr_record["content_type"]}"}} {str(sr_record["physical_utilisation"])}\n'

        if "virtual_allocation" in sr_record:
            output += f'xen_sr_virtual_allocation{{sr_uuid="{sr_uuid}", sr="{sr_name_label}", type="{sr_record["type"]}", content_type="{sr_record["content_type"]}"}} {str(sr_record["virtual_allocation"])}\n'
    return output


def collect_pbd_status(session: XenAPI.Session):
    """
    Collect PBD (Physical Block Device) attachment status metrics.
    Returns metrics indicating whether each PBD is currently attached (1) or detached (0).
    """
    output = ""
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

                output += f'xen_pbd_attached{{sr="{sr_name}", sr_uuid="{sr_uuid}", host="{host_name}", host_uuid="{host_uuid}", type="{sr_type}"}} {attached}\n'

            except Exception as e:
                # Skip this PBD if there's an error, continue with others
                logging.warning("Error processing PBD record: %s", e)
                continue

    except Exception as e:
        # If we can't get PBD records at all, return empty string
        # This ensures the exporter continues working even if PBD API fails
        logging.error("Failed to collect PBD status: %s", e)

    return output


def collect_multipath_status(session: XenAPI.Session):
    """
    Collect multipath status metrics for hosts and SRs.
    Returns metrics indicating multipath enablement on hosts and activation on SRs.
    """
    output = ""
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

                output += f'xen_host_multipath_enabled{{host="{host_name}", host_uuid="{host_uuid}"}} {enabled_val}\n'

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

                output += f'xen_sr_multipath_active{{sr="{sr_name}", sr_uuid="{sr_uuid}"}} {multipath_active}\n'

            except Exception as e:
                logging.warning("Error processing SR multipath record: %s", e)
                continue

    except Exception as e:
        # If we can't get records, return empty string
        # This ensures the exporter continues working even if API fails
        logging.error("Failed to collect multipath status: %s", e)

    return output


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


def collect_metrics():
    # Cleanup caches if they've grown too large
    _cleanup_cache_if_needed()

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

        output = ""
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
            metrics = pyjson5.decode_io(res)

            for metric_name in metrics["meta"]["legend"]:
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

            for metric_idx, metric_name in enumerate(metrics["meta"]["legend"]):
                metric_legend = metric_name.split(":")[1:]
                if len(metric_legend) < 3:
                    continue  # Already logged in the first loop
                collector_type = metric_legend[0]
                collector = metric_legend[1]
                metric_type = metric_legend[2]
                extra_tags = {collector_type: collector}

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

                tags = {f'{k}="{v}"' for k, v in extra_tags.items()}
                output += f"xen_{collector_type}_{metric_type}{{{', '.join(tags)}}} {metrics['data'][0]['values'][metric_idx]}\n"

        output += collect_sr_usage(xen)

        # Collect PBD status metrics if enabled
        if collect_pbd:
            output += collect_pbd_status(xen)

        # Collect multipath status metrics if enabled
        if collect_multipath:
            output += collect_multipath_status(xen)

        collector_end_time = time.perf_counter()
        output += f"xen_collector_duration_seconds {collector_end_time - collector_start_time}\n"
        return output
    
class Handler(http.server.BaseHTTPRequestHandler):
    def __init__(self, request: socket.socket, client_address: tuple[str, int], server: Any) -> None:
        super().__init__(request, client_address, server)

    def do_GET(self):
        try:
            metric_output = collect_metrics().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(metric_output)
        except BaseException:
            error_msg = traceback.format_exc()
            logging.error("Error collecting metrics: %s", error_msg)
            self.send_response(500)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Internal Server Error\n")


def validate_config():
    """Validate environment variables at startup."""
    errors = []

    # Validate XEN_HOST is set (required for operation)
    xen_host = os.getenv("XEN_HOST")
    if not xen_host:
        logging.warning("XEN_HOST not set, using default 'localhost'")

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
