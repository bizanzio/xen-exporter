# XEN-EXPORTER - Metrics Reference Guide

## Table of Contents
1. [Overview](#1-overview)
2. [Currently Available Metrics](#2-currently-available-metrics)
3. [Planned Future Metrics](#3-planned-future-metrics)
4. [Metric Labels Reference](#4-metric-labels-reference)
5. [Example Queries](#5-example-queries)

---

## 1. Overview

This document provides a complete reference of all metrics exported by xen-exporter, including both currently implemented metrics and planned future enhancements.

### Metrics Summary

| Category | Current Count | Planned Count | Total After Implementation |
|----------|---------------|---------------|---------------------------|
| Host Metrics | 39+ | 1 | 40+ |
| VM Metrics | 20+ | 0 | 20+ |
| Storage Metrics | 3 | 6 | 9 |
| System Metrics | 1 | 0 | 1 |
| **Total** | **60+** | **7** | **70+** |

---

## 2. Currently Available Metrics

### 2.1 Host Metrics (xen_host_*)

#### CPU Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_cpu` | Gauge | Ratio (0-1) | CPU utilization per core |
| `xen_host_cpu_avg` | Gauge | Ratio (0-1) | Average CPU utilization across all cores |
| `xen_host_cpu_avg_freq` | Gauge | Hz | Average CPU frequency |
| `xen_host_cpu_c0` | Gauge | Ratio | CPU C0 (active) state time |
| `xen_host_cpu_c1` | Gauge | Ratio | CPU C1 (halt) state time |
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

#### Pool Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_pool_session_count` | Gauge | Count | Active pool sessions |
| `xen_host_pool_task_count` | Gauge | Count | Active pool tasks |

#### Other Host Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_loadavg` | Gauge | Load | System load average |
| `xen_host_tapdisks_in_low_memory_mode` | Gauge | Count | Tapdisks in low memory mode |

---

### 2.2 VM Metrics (xen_vm_*)

#### CPU Metrics
| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_vm_cpu` | Gauge | Ratio (0-1) | VM CPU utilization per vCPU |

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

---

### 2.4 System Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_collector_duration_seconds` | Gauge | Seconds | Time taken to collect all metrics |

---

## 3. PBD and Multipath Metrics (Implemented)

The following metrics have been implemented to provide enhanced storage monitoring capabilities.

### 3.1 Multipath Metrics

**Status:** IMPLEMENTED

**Environment Variable:** `XEN_COLLECT_MULTIPATH` (default: `true`)

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_host_multipath_enabled` | Gauge | Boolean (0/1) | Whether multipath is enabled on the host |
| `xen_sr_multipath_active` | Gauge | Boolean (0/1) | Whether multipath is active for the SR |

**Labels:**
| Label | Description |
|-------|-------------|
| `host` | Host name (for host metrics) |
| `host_uuid` | Host UUID (for host metrics) |
| `sr` | Storage Repository name (for SR metrics) |
| `sr_uuid` | Storage Repository UUID (for SR metrics) |

**Use Cases:**
- Monitor multipath failover status
- Alert when multipath is disabled
- Track multipath configuration across pool

**Example Alert:**
```promql
xen_host_multipath_enabled == 0  # Alert when multipath disabled
xen_sr_multipath_active == 0     # Alert when SR multipath inactive
```

---

### 3.2 PBD (Physical Block Device) Metrics

**Status:** IMPLEMENTED

**Environment Variable:** `XEN_COLLECT_PBD` (default: `true`)

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `xen_pbd_attached` | Gauge | Boolean (0/1) | PBD connection status (1=attached, 0=detached) |

**Labels:**
| Label | Description |
|-------|-------------|
| `sr` | Storage Repository name |
| `sr_uuid` | Storage Repository UUID |
| `host` | Host name |
| `host_uuid` | Host UUID |
| `type` | SR type (nfs, lvmoiscsi, lvm, etc.) |

**Use Cases:**
- Detect storage disconnections immediately
- Monitor SR availability per host
- Alert on PBD detachment events

**Example Alert:**
```promql
xen_pbd_attached == 0  # Alert when PBD detached (critical)
```

**Implementation Priority:** High - DONE

---

### 3.3 Storage Target Information Metrics (Planned)

**Status:** NOT YET IMPLEMENTED

#### iSCSI Target Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `xen_sr_iscsi_target_info` | Info | iSCSI target connectivity information |

**Labels:** `sr`, `sr_uuid`, `target` (IP/hostname), `iqn` (iSCSI Qualified Name)

#### NFS Target Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `xen_sr_nfs_target_info` | Info | NFS server connectivity information |

**Labels:** `sr`, `sr_uuid`, `server` (IP/hostname), `path` (export path)

#### Fibre Channel Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `xen_sr_fc_info` | Info | Fibre Channel storage information |

**Labels:** `sr`, `sr_uuid`, `scsi_id`

**Use Cases:**
- Inventory storage targets in Prometheus
- Correlate storage issues with specific targets
- Document infrastructure in metrics

**Implementation Priority:** Medium

---

### 3.4 Summary: Implementation Status

| Category | Metric | Status | Env Variable |
|----------|--------|--------|--------------|
| **Multipath** | `xen_host_multipath_enabled` | IMPLEMENTED | `XEN_COLLECT_MULTIPATH` |
| **Multipath** | `xen_sr_multipath_active` | IMPLEMENTED | `XEN_COLLECT_MULTIPATH` |
| **PBD** | `xen_pbd_attached` | IMPLEMENTED | `XEN_COLLECT_PBD` |
| **iSCSI** | `xen_sr_iscsi_target_info` | Planned | - |
| **NFS** | `xen_sr_nfs_target_info` | Planned | - |
| **FC** | `xen_sr_fc_info` | Planned | - |

---

## 4. Metric Labels Reference

### 4.1 Host Metric Labels

| Label | Description | Example |
|-------|-------------|---------|
| `host` | Human-readable host name | `xenserver01` |
| `host_uuid` | Host UUID | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `sr` | Storage Repository name (for SR-related host metrics) | `Local Storage` |
| `sr_uuid` | Storage Repository UUID | `e5f6g7h8-i9j0-1234-klmn-op5678901234` |
| `pif` | Physical Interface identifier | `eth0`, `bond0` |
| `cpu` | CPU core number | `0`, `1`, `2`, `3` |

### 4.2 VM Metric Labels

| Label | Description | Example |
|-------|-------------|---------|
| `vm` | Human-readable VM name | `web-server-01` |
| `vm_uuid` | VM UUID | `i9j0k1l2-m3n4-5678-opqr-st9012345678` |
| `vbd` | Virtual Block Device identifier | `xvda`, `xvdb` |
| `vif` | Virtual Interface number | `0`, `1`, `2` |
| `cpu` | vCPU number | `0`, `1` |

### 4.3 Storage Metric Labels

| Label | Description | Example |
|-------|-------------|---------|
| `sr` | Storage Repository name | `NFS_Storage`, `iSCSI_LUN1` |
| `sr_uuid` | Storage Repository UUID | `m3n4o5p6-q7r8-9012-stuv-wx3456789012` |
| `type` | SR type | `nfs`, `lvmoiscsi`, `lvm`, `ext`, `iso` |
| `content_type` | Content type | `user`, `iso` |

### 4.4 Planned Labels (Future)

| Label | Description | Applicable Metrics |
|-------|-------------|-------------------|
| `target` | iSCSI target IP/hostname | `xen_sr_iscsi_target_info` |
| `iqn` | iSCSI Qualified Name | `xen_sr_iscsi_target_info` |
| `server` | NFS server IP/hostname | `xen_sr_nfs_target_info` |
| `path` | NFS export path | `xen_sr_nfs_target_info` |
| `scsi_id` | Fibre Channel SCSI ID | `xen_sr_fc_info` |

---

## 5. Example Queries

### 5.1 Host Monitoring Queries

```promql
# CPU utilization per host (average across all cores)
xen_host_cpu_avg

# Memory utilization percentage
(1 - (xen_host_memory_free_kib / xen_host_memory_total_kib)) * 100

# Host load average
xen_host_loadavg

# Network throughput per host (combined RX + TX)
sum by (host) (xen_host_pif_rx + xen_host_pif_tx)

# Disk IOPS per host
xen_host_iops_total

# Disk latency per host
xen_host_latency
```

### 5.2 VM Monitoring Queries

```promql
# CPU utilization per VM (average across all vCPUs)
avg by (vm) (xen_vm_cpu)

# Top 10 VMs by CPU usage
topk(10, avg by (vm) (xen_vm_cpu))

# VM memory usage
xen_vm_memory

# VM disk IOPS (combined read + write)
sum by (vm) (xen_vm_vbd_iops_total)

# VM network throughput
sum by (vm) (xen_vm_vif_rx + xen_vm_vif_tx)

# VMs with high disk latency (> 10ms)
xen_vm_vbd_latency > 0.01
```

### 5.3 Storage Monitoring Queries

```promql
# SR utilization percentage
(xen_sr_physical_utilization / xen_sr_physical_size) * 100

# SRs with > 80% utilization
(xen_sr_physical_utilization / xen_sr_physical_size) * 100 > 80

# Over-provisioned SRs (virtual > physical)
xen_sr_virtual_allocation > xen_sr_physical_size

# Free space per SR
xen_sr_physical_size - xen_sr_physical_utilization
```

### 5.4 Planned Queries (After Future Implementation)

```promql
# Hosts with multipath disabled (PLANNED)
xen_host_multipath_enabled == 0

# Detached PBDs - storage connectivity issues (PLANNED)
xen_pbd_attached == 0

# SRs without active multipath (PLANNED)
xen_sr_multipath_active == 0

# Count of storage paths per SR (PLANNED)
xen_sr_multipath_paths
```

### 5.5 Alerting Rule Examples

```yaml
groups:
  - name: xen-alerts
    rules:
      # High CPU usage alert
      - alert: XenHostHighCPU
        expr: xen_host_cpu_avg > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on {{ $labels.host }}"
          description: "CPU usage is {{ $value | humanizePercentage }}"

      # Low memory alert
      - alert: XenHostLowMemory
        expr: (xen_host_memory_free_kib / xen_host_memory_total_kib) < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Low memory on {{ $labels.host }}"
          description: "Only {{ $value | humanizePercentage }} memory free"

      # SR almost full alert
      - alert: XenSRAlmostFull
        expr: (xen_sr_physical_utilization / xen_sr_physical_size) > 0.9
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "SR {{ $labels.sr }} is almost full"
          description: "SR utilization is {{ $value | humanizePercentage }}"

      # High disk latency alert
      - alert: XenHostHighDiskLatency
        expr: xen_host_latency > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High disk latency on {{ $labels.host }}"
          description: "Disk latency is {{ $value | humanizeDuration }}"

      # Collector slow alert
      - alert: XenCollectorSlow
        expr: xen_collector_duration_seconds > 30
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Xen exporter collection is slow"
          description: "Collection took {{ $value | humanizeDuration }}"

      # PLANNED: PBD detached alert
      # - alert: XenPBDDetached
      #   expr: xen_pbd_attached == 0
      #   for: 1m
      #   labels:
      #     severity: critical
      #   annotations:
      #     summary: "Storage disconnected on {{ $labels.host }}"
      #     description: "SR {{ $labels.sr }} is detached from {{ $labels.host }}"
```

---

## Document Information

| Field | Value |
|-------|-------|
| **Document** | Metrics Reference Guide |
| **Project** | xen-exporter |
| **Version** | 1.0 |
| **Last Updated** | January 2026 |
| **Repository** | https://github.com/mikedombo/xen-exporter |
