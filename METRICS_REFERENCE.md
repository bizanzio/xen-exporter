# xen-exporter Metrics Reference

## Table of Contents
1. [Overview](#1-overview)
2. [Metrics Reference](#2-metrics-reference)
3. [Labels Reference](#3-labels-reference)
4. [Example Queries](#4-example-queries)
5. [Alerting Rules](#5-alerting-rules)
6. [Architecture](#6-architecture)
7. [Security Considerations](#7-security-considerations)
8. [Production Deployment](#8-production-deployment)

---

## 1. Overview

### Metrics Summary

| Category | Count | Description |
|----------|-------|-------------|
| Host Metrics | 60+ | CPU, Memory, Disk I/O, Network, XAPI, Xenopsd |
| VM Metrics | 20+ | CPU, Memory, VBD, VIF |
| Storage Metrics | 4 | Physical size, utilization, allocation, multipath |
| PBD Metrics | 1 | Attachment status |
| System Metrics | 1 | Collector duration |
| **Total** | **85+** | Dynamic based on infrastructure |

---

## 2. Metrics Reference

### 2.1 Host Metrics (xen_host_*)

#### CPU Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_cpu` | Gauge | Ratio (0-1) | CPU utilization per core |
| `xen_host_cpu_avg` | Gauge | Ratio (0-1) | Average CPU utilization across all cores |
| `xen_host_cpu_avg_freq` | Gauge | Hz | Average CPU frequency |
| `xen_host_cpu_c0` | Gauge | Ratio | CPU C0 (active) state time |
| `xen_host_cpu_c1` | Gauge | Ratio | CPU C1 (halt) state time |
| `xen_host_cpu_c2` | Gauge | Ratio | CPU C2 state time |
| `xen_host_cpu_c3` | Gauge | Ratio | CPU C3 state time |
| `xen_host_cpu_c4` | Gauge | Ratio | CPU C4 state time |
| `xen_host_cpu_p0` | Gauge | Ratio | CPU P0 power state time |
| `xen_host_cpu_p1` | Gauge | Ratio | CPU P1 power state time |
| `xen_host_cpu_p2` | Gauge | Ratio | CPU P2 power state time |

#### Memory Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_memory_free_kib` | Gauge | KiB | Free memory on host |
| `xen_host_memory_total_kib` | Gauge | KiB | Total memory on host |
| `xen_host_memory_reclaimed` | Gauge | Bytes | Memory reclaimed from VMs |
| `xen_host_memory_reclaimed_max` | Gauge | Bytes | Maximum reclaimable memory |

#### Disk I/O Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_read` | Gauge | Ops/sec | Disk read operations |
| `xen_host_write` | Gauge | Ops/sec | Disk write operations |
| `xen_host_read_latency` | Gauge | Seconds | Disk read latency |
| `xen_host_write_latency` | Gauge | Seconds | Disk write latency |
| `xen_host_latency` | Gauge | Seconds | Overall disk latency |
| `xen_host_iops_read` | Gauge | IOPS | Read IOPS |
| `xen_host_iops_write` | Gauge | IOPS | Write IOPS |
| `xen_host_iops_total` | Gauge | IOPS | Total IOPS |
| `xen_host_io_throughput_read` | Gauge | Bytes/sec | Read throughput |
| `xen_host_io_throughput_write` | Gauge | Bytes/sec | Write throughput |
| `xen_host_io_throughput_total` | Gauge | Bytes/sec | Total I/O throughput |
| `xen_host_avgqu_sz` | Gauge | Count | Average I/O queue size |
| `xen_host_inflight` | Gauge | Count | In-flight I/O operations |
| `xen_host_iowait` | Gauge | Ratio | I/O wait time ratio |

#### Network Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_pif_rx` | Gauge | Bytes/sec | Physical interface received bytes |
| `xen_host_pif_tx` | Gauge | Bytes/sec | Physical interface transmitted bytes |

#### Storage Repository Cache Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_sr_cache_hits` | Counter | Count | SR cache hits |
| `xen_host_sr_cache_misses` | Counter | Count | SR cache misses |
| `xen_host_sr_cache_size` | Gauge | Bytes | SR cache size |

#### XAPI Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_xapi_allocation_kib` | Gauge | KiB | XAPI memory allocation |
| `xen_host_xapi_free_memory_kib` | Gauge | KiB | XAPI free memory |
| `xen_host_xapi_live_memory_kib` | Gauge | KiB | XAPI live memory |
| `xen_host_xapi_memory_usage_kib` | Gauge | KiB | XAPI memory usage |
| `xen_host_xapi_open_fds` | Gauge | Count | XAPI open file descriptors |

#### Xenopsd Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_xenopsd_xc_fdsize` | Gauge | Count | Xenopsd XC file descriptor table size |
| `xen_host_xenopsd_xc_mem_extra` | Gauge | KiB | Xenopsd XC extra memory |
| `xen_host_xenopsd_xc_ocaml_allocation_rate` | Gauge | Rate | Xenopsd XC OCaml heap allocation rate |
| `xen_host_xenopsd_xc_ocaml_free` | Gauge | KiB | Xenopsd XC OCaml free heap memory |
| `xen_host_xenopsd_xc_ocaml_maybe_live` | Gauge | KiB | Xenopsd XC OCaml maybe live memory |
| `xen_host_xenopsd_xc_ocaml_total` | Gauge | KiB | Xenopsd XC OCaml total heap size |
| `xen_host_xenopsd_xc_rss` | Gauge | KiB | Xenopsd XC resident set size |
| `xen_host_xenopsd_xc_threads` | Gauge | Count | Xenopsd XC number of threads |
| `xen_host_xenopsd_xc_vmdata` | Gauge | KiB | Xenopsd XC virtual memory data segment |
| `xen_host_xenopsd_xc_vmlck` | Gauge | KiB | Xenopsd XC locked virtual memory |
| `xen_host_xenopsd_xc_vmpin` | Gauge | KiB | Xenopsd XC pinned virtual memory |
| `xen_host_xenopsd_xc_vmpte` | Gauge | Count | Xenopsd XC page table entries |
| `xen_host_xenopsd_xc_vmsize` | Gauge | KiB | Xenopsd XC total virtual memory size |
| `xen_host_xenopsd_xc_vmstk` | Gauge | KiB | Xenopsd XC stack size |

#### Pool Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_pool_session_count` | Gauge | Count | Active pool sessions |
| `xen_host_pool_task_count` | Gauge | Count | Active pool tasks |
| `xen_host_pool_session_creation_rate` | Gauge | Rate | Rate of pool session creation |

#### Other Host Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_loadavg` | Gauge | Load | System load average |
| `xen_host_hostload` | Gauge | Load | Host load |
| `xen_host_running_domains` | Gauge | Count | Number of running domains (VMs) |
| `xen_host_running_vcpus` | Gauge | Count | Number of running vCPUs |
| `xen_host_dcmi_power_reading` | Gauge | Watts | DCMI power reading (if available) |
| `xen_host_tapdisks_in_low_memory_mode` | Gauge | Count | Tapdisks in low memory mode |
| `xen_host_multipath_enabled` | Gauge | Boolean (0/1) | Whether multipath is enabled on the host |

---

### 2.2 VM Metrics (xen_vm_*)

#### CPU Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_vm_cpu` | Gauge | Ratio (0-1) | VM CPU utilization per vCPU |
| `xen_vm_cpu_usage` | Gauge | Ratio | VM total CPU usage |

#### Memory Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_vm_memory` | Gauge | Bytes | VM memory usage |
| `xen_vm_memory_internal_free` | Gauge | Bytes | VM internal free memory (guest-reported) |
| `xen_vm_memory_target` | Gauge | Bytes | VM memory target |

#### Virtual Block Device (VBD) Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_vm_vbd_read` | Gauge | Ops/sec | VBD read operations |
| `xen_vm_vbd_write` | Gauge | Ops/sec | VBD write operations |
| `xen_vm_vbd_read_latency` | Gauge | Seconds | VBD read latency |
| `xen_vm_vbd_write_latency` | Gauge | Seconds | VBD write latency |
| `xen_vm_vbd_latency` | Gauge | Seconds | VBD overall latency |
| `xen_vm_vbd_iops_read` | Gauge | IOPS | VBD read IOPS |
| `xen_vm_vbd_iops_write` | Gauge | IOPS | VBD write IOPS |
| `xen_vm_vbd_iops_total` | Gauge | IOPS | VBD total IOPS |
| `xen_vm_vbd_io_throughput_read` | Gauge | Bytes/sec | VBD read throughput |
| `xen_vm_vbd_io_throughput_write` | Gauge | Bytes/sec | VBD write throughput |
| `xen_vm_vbd_io_throughput_total` | Gauge | Bytes/sec | VBD total throughput |
| `xen_vm_vbd_avgqu_sz` | Gauge | Count | VBD average queue size |
| `xen_vm_vbd_inflight` | Gauge | Count | VBD in-flight operations |
| `xen_vm_vbd_iowait` | Gauge | Ratio | VBD I/O wait time |

#### Virtual Interface (VIF) Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_vm_vif_rx` | Gauge | Bytes/sec | VIF received bytes |
| `xen_vm_vif_tx` | Gauge | Bytes/sec | VIF transmitted bytes |

---

### 2.3 Storage Repository Metrics (xen_sr_*)

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_sr_physical_size` | Gauge | Bytes | Total physical size of SR |
| `xen_sr_physical_utilization` | Gauge | Bytes | Used physical space on SR |
| `xen_sr_virtual_allocation` | Gauge | Bytes | Virtual allocation on SR |
| `xen_sr_multipath_active` | Gauge | Boolean (0/1) | Whether multipath is active for the SR |

### 2.4 PBD Metrics (xen_pbd_*)

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_pbd_attached` | Gauge | Boolean (0/1) | PBD connection status (1=attached, 0=detached) |

### 2.5 System Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_collector_duration_seconds` | Gauge | Seconds | Time taken to collect all metrics |

---

## 3. Labels Reference

### Host Metric Labels
| Label | Description | Example |
|-------|-------------|---------|
| `host` | Human-readable host name | `xenserver01` |
| `host_uuid` | Host UUID | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `sr` | Storage Repository name | `Local Storage` |
| `sr_uuid` | Storage Repository UUID | `e5f6g7h8-i9j0-1234-klmn-op5678901234` |
| `pif` | Physical Interface identifier | `eth0`, `bond0` |
| `cpu` | CPU core number | `0`, `1`, `2` |

### VM Metric Labels
| Label | Description | Example |
|-------|-------------|---------|
| `vm` | Human-readable VM name | `web-server-01` |
| `vm_uuid` | VM UUID | `i9j0k1l2-m3n4-5678-opqr-st9012345678` |
| `host` | Host running the VM | `xenserver01` |
| `host_uuid` | Host UUID | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `vbd` | Virtual Block Device identifier | `xvda`, `xvdb` |
| `vif` | Virtual Interface number | `0`, `1` |
| `cpu` | vCPU number | `0`, `1` |

### Storage Metric Labels
| Label | Description | Example |
|-------|-------------|---------|
| `sr` | Storage Repository name | `NFS_Storage` |
| `sr_uuid` | Storage Repository UUID | `m3n4o5p6-q7r8-9012-stuv-wx3456789012` |
| `type` | SR type | `nfs`, `lvmoiscsi`, `lvm`, `ext` |
| `content_type` | Content type | `user`, `iso` |

### PBD Metric Labels
| Label | Description |
|-------|-------------|
| `sr` | Storage Repository name |
| `sr_uuid` | Storage Repository UUID |
| `host` | Host name |
| `host_uuid` | Host UUID |
| `type` | SR type (nfs, lvmoiscsi, lvm, etc.) |

---

## 4. Example Queries

### Host Monitoring
```promql
# CPU utilization per host (average across all cores)
xen_host_cpu_avg

# Memory utilization percentage
(1 - (xen_host_memory_free_kib / xen_host_memory_total_kib)) * 100

# Host load average
xen_host_loadavg

# Network throughput per host
sum by (host) (xen_host_pif_rx + xen_host_pif_tx)

# Disk latency
xen_host_latency
```

### VM Monitoring
```promql
# CPU utilization per VM (average across vCPUs)
avg by (vm) (xen_vm_cpu)

# Top 10 VMs by CPU usage
topk(10, avg by (vm) (xen_vm_cpu))

# VMs with high disk latency (> 10ms)
xen_vm_vbd_latency > 0.01
```

### Storage Monitoring
```promql
# SR utilization percentage
(xen_sr_physical_utilization / xen_sr_physical_size) * 100

# SRs with > 80% utilization
(xen_sr_physical_utilization / xen_sr_physical_size) * 100 > 80

# Detached PBDs
xen_pbd_attached == 0

# Hosts with multipath disabled
xen_host_multipath_enabled == 0
```

---

## 5. Alerting Rules

```yaml
groups:
  - name: xen-alerts
    rules:
      - alert: XenHostHighCPU
        expr: xen_host_cpu_avg > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.host }}"

      - alert: XenHostLowMemory
        expr: (xen_host_memory_free_kib / xen_host_memory_total_kib) < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Low memory on {{ $labels.host }}"

      - alert: XenSRAlmostFull
        expr: (xen_sr_physical_utilization / xen_sr_physical_size) > 0.9
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "SR {{ $labels.sr }} is almost full"

      - alert: XenPBDDetached
        expr: xen_pbd_attached == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Storage disconnected: {{ $labels.sr }} on {{ $labels.host }}"

      - alert: XenMultipathDisabled
        expr: xen_host_multipath_enabled == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Multipath disabled on {{ $labels.host }}"

      - alert: XenCollectorSlow
        expr: xen_collector_duration_seconds > 30
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Metric collection slow"
```

---

## 6. Architecture

### Collection Methods

**1. RRD Updates API (Primary)**
```
GET https://<host>/rrd_updates?start=<timestamp>&json=true&host=true&cf=AVERAGE
```
- Retrieves all RRD metrics in a single request
- Returns JSON5 formatted response
- Uses Basic Authentication

**2. XenAPI Direct Calls (Storage/PBD/Multipath)**
```python
session.xenapi.SR.get_all_records()
session.xenapi.PBD.get_all_records()
session.xenapi.host.get_all_records()
```

### Processing Pipeline
```
Dom0 RRD Database
       ↓
HTTPS Request (Basic Auth)
       ↓
JSON5 Response Parsing
       ↓
UUID Resolution (cached)
       ↓
Prometheus Format Output
```

### Performance
| Operation | Typical Duration |
|-----------|------------------|
| Total (cached) | ~800ms |
| Total (uncached) | ~1500ms |

---

## 7. Security Considerations

### Issues and Mitigations

| Issue | Severity | Mitigation |
|-------|----------|------------|
| Plain-text credentials | High | Use secrets management (Vault, K8s secrets) |
| SSL verification bypass | High | Always enable `XEN_SSL_VERIFY=true` in production |
| No endpoint authentication | High | Deploy behind authenticated reverse proxy |
| Sensitive info in metrics | Medium | Network segmentation, metric relabeling |
| Default root user | Medium | Create dedicated read-only XenServer user |

### Recommended Secure Deployment
```yaml
services:
  xen-exporter:
    image: ghcr.io/mikedombo/xen-exporter:latest
    environment:
      - XEN_HOST=10.10.10.101
      - XEN_USER=monitoring_user  # NOT root
      - XEN_SSL_VERIFY=true
    secrets:
      - xen_password
    networks:
      - monitoring  # Isolated network

secrets:
  xen_password:
    external: true

networks:
  monitoring:
    internal: true
```

---

## 8. Production Deployment

### Prometheus Configuration
```yaml
scrape_configs:
  - job_name: xenserver
    scrape_interval: 60s
    scrape_timeout: 50s
    static_configs:
      - targets: ["xen-exporter:9100"]
```

### Resource Requirements

**Exporter Host:**
| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 0.1 vCPU | 0.5 vCPU |
| RAM | 64 MB | 128 MB |
| Python | 3.12+ | 3.14+ |

**Dom0 Impact:**
| Scenario | CPU Impact |
|----------|------------|
| 1-10 VMs | Negligible |
| 10-50 VMs | ~1% per scrape |
| 50-100 VMs | ~2-3% per scrape |
| 100+ VMs | Consider 120s interval |

### Scalability Note
Filtering metrics on the client side does NOT reduce Dom0 load. The RRD API returns all metrics regardless. To reduce load, increase `scrape_interval`.

---

## Document Information

| Field | Value |
|-------|-------|
| **Project** | xen-exporter |
| **Repository** | https://github.com/bizanzio/xen-exporter |
| **Upstream** | https://github.com/mikedombo/xen-exporter |
| **Grafana Dashboard** | ID 16588 |
| **Last Updated** | February 2026 |
