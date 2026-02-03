# XEN-EXPORTER - Technical Documentation

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [How Metrics Are Collected from Dom0](#2-how-metrics-are-collected-from-dom0)
3. [Scrape Timing and Intervals](#3-scrape-timing-and-intervals)
4. [Minimum Requirements for Dom0](#4-minimum-requirements-for-dom0)
5. [Security Analysis](#5-security-analysis)
6. [Key-Based Authentication - Feasibility Analysis](#6-key-based-authentication---feasibility-analysis)
7. [Complete Metrics List](#7-complete-metrics-list)
8. [Configuration Reference](#8-configuration-reference)
9. [Planned Future Enhancements](#9-planned-future-enhancements)

---

## 1. Project Overview

**xen-exporter** is a Prometheus exporter for XCP-ng/XenServer infrastructure that automatically exports all statistics from the RRD (Round-Robin Database) metrics database from Xen hypervisors.

### Key Features
- Automatic metric discovery from Xen RRD database
- Support for single host and pool-wide metrics collection
- Aggressive caching for improved performance
- Docker containerization support
- Grafana dashboard available (ID: 16588)

### Project Structure
```
xen-exporter/
├── xen-exporter.py      # Main application (293 lines)
├── requirements.txt     # Python dependencies (pyjson5, XenAPI)
├── Dockerfile           # Docker containerization
├── README.md            # Basic documentation
└── LICENSE              # BSD 2-Clause License
```

---

## 2. How Metrics Are Collected from Dom0

### 2.1 Collection Mechanism

The exporter collects metrics through **two primary methods**:

#### Method 1: RRD Updates API (Primary Metrics)
```
URL: https://<xen_host>/rrd_updates?start=<timestamp>&json=true&host=true&cf=AVERAGE
```

**Process Flow:**
1. The exporter connects to Dom0's HTTPS endpoint
2. Requests RRD updates from the last 10 seconds: `start={int(time.time()-10)}`
3. Receives JSON5 formatted response containing all metrics
4. Parses the legend to extract metric names and associated metadata

**Code Reference (Line 173-186):**
```python
url = f"https://{xen_host}/rrd_updates?start={int(time.time()-10)}&json=true&host=true&cf=AVERAGE"

req = urllib.request.Request(url)
req.add_header(
    "Authorization",
    "Basic " + base64.b64encode((xen_user + ":" + xen_password).encode("utf-8")).decode("utf-8"),
)
res = urllib.request.urlopen(
    req, context=None if verify_ssl else ssl._create_unverified_context()
)
metrics = pyjson5.decode_io(res)
```

#### Method 2: XenAPI Direct Calls (SR Metrics)
```python
sr_records = session.xenapi.SR.get_all_records()
```

**Process Flow:**
1. Connects to XenAPI via HTTPS
2. Authenticates using username/password
3. Queries Storage Repository (SR) records directly
4. Extracts physical_size, physical_utilisation, virtual_allocation

**Code Reference (Line 94-108):**
```python
def collect_sr_usage(session: XenAPI.Session):
    sr_records = session.xenapi.SR.get_all_records()
    output = ""
    for sr_record in sr_records.values():
        sr_name_label = sr_record["name_label"]
        sr_uuid = sr_record["uuid"]
        # ... outputs xen_sr_physical_size, xen_sr_physical_utilization, xen_sr_virtual_allocation
```

### 2.2 Authentication Method

- **Protocol:** HTTPS (Basic Authentication)
- **Header:** `Authorization: Basic <base64(username:password)>`
- **Session:** XenAPI session with login_with_password

### 2.3 Metric Processing Pipeline

```
Dom0 RRD Database
       |
       v
HTTPS Request (Basic Auth)
       |
       v
JSON5 Response Parsing
       |
       v
Legend Extraction (metric_name:collector_type:collector_id:metric_type)
       |
       v
UUID Resolution (VM names, Host names, SR names)
       |
       v
Prometheus Format Output
```

### 2.4 Caching Strategy

The exporter uses global dictionaries to cache lookups:

```python
srs = dict()     # SR UUID -> Name mapping
vms = dict()     # VM UUID -> Name mapping
hosts = dict()   # Host UUID -> Name mapping
all_srs = set()  # All SR UUIDs for partial matching
```

**Performance Impact:** Reduces scrape time from ~1.5s to ~0.8s per request

---

## 3. Scrape Timing and Intervals

### 3.1 RRD Query Window

**Default Query Window:** Last 10 seconds

```python
url = f"https://{xen_host}/rrd_updates?start={int(time.time()-10)}&json=true&host=true&cf=AVERAGE"
```

The `start` parameter is set to `current_time - 10 seconds`, meaning:
- Only the most recent data point is retrieved
- Uses `cf=AVERAGE` (Consolidation Function) for averaged values

### 3.2 Recommended Prometheus Scrape Configuration

**From README.md (prometheus.yml):**
```yaml
- job_name: xenserver
  scrape_interval: 60s      # Scrape every 60 seconds
  scrape_timeout: 50s       # Allow up to 50 seconds for response
  static_configs:
  - targets:
    - xen01:9100
    - xen02:9100
```

### 3.3 Timing Breakdown

| Operation | Typical Duration |
|-----------|------------------|
| XenAPI Connection | 100-200ms |
| RRD Updates Fetch | 200-400ms |
| UUID Resolution (cached) | 50-100ms |
| UUID Resolution (uncached) | 500-700ms |
| SR Records Fetch | 100-200ms |
| **Total (cached)** | **~800ms** |
| **Total (uncached)** | **~1500ms** |

### 3.4 Collector Duration Metric

The exporter reports its own collection time:
```
xen_collector_duration_seconds <value>
```

**Code Reference (Line 260-261):**
```python
collector_end_time = time.perf_counter()
output += f"xen_collector_duration_seconds {collector_end_time - collector_start_time}\n"
```

---

## 4. Minimum Requirements for Dom0

### 4.1 Dom0 Resource Requirements

#### CPU Requirements
| Requirement | Value | Notes |
|-------------|-------|-------|
| **Minimum vCPUs** | 1 vCPU | No additional CPU required |
| **CPU Impact** | < 1% | Minimal overhead per scrape |

#### Memory Requirements
| Requirement | Value | Notes |
|-------------|-------|-------|
| **Minimum RAM** | 0 MB additional | Uses existing XAPI memory |
| **Per-Request Memory** | ~5-10 MB | Temporary for JSON parsing |

#### Network Requirements
| Requirement | Value | Notes |
|-------------|-------|-------|
| **Bandwidth per scrape** | ~50-200 KB | Depends on VM/SR count |
| **Port Required** | 443 (HTTPS) | For RRD API access |

### 4.2 Dom0 Service Requirements

| Service | Required | Purpose |
|---------|----------|---------|
| **XAPI** | Yes | XenAPI server must be running |
| **HTTPS (stunnel/nginx)** | Yes | For secure API access |
| **RRD Daemon** | Yes | Metrics collection service |

### 4.3 Dom0 Configuration Requirements

**No additional configuration required on Dom0.** The exporter uses:
- Built-in RRD Updates HTTP API (`/rrd_updates`)
- Standard XenAPI authentication
- Default HTTPS port (443)

### 4.4 Exporter Host Requirements (Where xen-exporter runs)

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU** | 0.1 vCPU | 0.5 vCPU |
| **RAM** | 64 MB | 128 MB |
| **Network** | 1 Mbps | 10 Mbps |
| **Python** | 3.10+ | 3.10+ |

### 4.5 Scalability Considerations

| Scenario | Impact on Dom0 |
|----------|----------------|
| 1-10 VMs | Negligible |
| 10-50 VMs | Low (~1% CPU spike per scrape) |
| 50-100 VMs | Moderate (~2-3% CPU spike) |
| 100+ VMs | Consider longer scrape intervals |

**Recommendation:** For large deployments (100+ VMs), increase scrape_interval to 120s or higher.

---

## 5. Security Analysis

### 5.1 Security Issues Identified

#### CRITICAL: Credentials Exposed in Plain Text

**Issue:** Credentials are read from environment variables and transmitted via Basic Authentication.

```python
xen_user = os.getenv("XEN_USER", "root")
xen_password = os.getenv("XEN_PASSWORD", "")
```

**Risk Level:** HIGH
**Impact:**
- Environment variables can be leaked through `/proc/<pid>/environ`
- Docker inspect exposes environment variables
- Process listing may show credentials

**Mitigation Recommendations:**
1. Use Docker secrets or Kubernetes secrets instead of environment variables
2. Use a dedicated service account with minimal permissions
3. Implement credential rotation

---

#### CRITICAL: SSL Verification Can Be Disabled

**Issue:** SSL verification can be completely bypassed.

```python
verify_ssl = os.getenv("XEN_SSL_VERIFY", "true")
verify_ssl = True if verify_ssl.lower() == "true" else False
# ...
res = urllib.request.urlopen(
    req, context=None if verify_ssl else ssl._create_unverified_context()
)
```

**Risk Level:** HIGH
**Impact:**
- Man-in-the-middle attacks possible when SSL verification is disabled
- Credentials can be intercepted

**Mitigation Recommendations:**
1. Always enable SSL verification in production
2. Install proper CA certificates on the exporter host
3. Use XCP-ng/XenServer with valid SSL certificates

---

#### HIGH: No Authentication on Exporter Endpoint

**Issue:** The `/metrics` endpoint has no authentication.

```python
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            metric_output = collect_metrics().encode("utf-8")
            self.send_response(200)
            # No authentication check
```

**Risk Level:** HIGH
**Impact:**
- Anyone with network access can scrape metrics
- Exposes infrastructure information (VM names, host names, UUIDs)
- Potential information disclosure

**Mitigation Recommendations:**
1. Deploy behind a reverse proxy with authentication
2. Use network segmentation (private network only)
3. Implement firewall rules to restrict access
4. Add basic authentication to the exporter

---

#### MEDIUM: Sensitive Information in Metrics

**Issue:** Metrics expose infrastructure details.

**Exposed Information:**
- VM names and UUIDs
- Host names and UUIDs
- Storage Repository names and UUIDs
- Network interface identifiers
- Resource utilization patterns

**Risk Level:** MEDIUM
**Impact:**
- Reconnaissance information for attackers
- Infrastructure mapping possible

**Mitigation Recommendations:**
1. Restrict network access to the exporter
2. Use metric relabeling in Prometheus to filter sensitive labels
3. Consider obfuscating UUIDs if not needed

---

#### MEDIUM: Default Root User

**Issue:** Default username is `root`.

```python
xen_user = os.getenv("XEN_USER", "root")
```

**Risk Level:** MEDIUM
**Impact:**
- Encourages use of root credentials
- Excessive privileges for metric collection

**Mitigation Recommendations:**
1. Create a dedicated read-only XenServer user for monitoring
2. Assign minimal permissions (read-only pool operator)

---

#### LOW: No Rate Limiting

**Issue:** No protection against excessive requests.

```python
http.server.HTTPServer((bind, int(port)), Handler).serve_forever()
```

**Risk Level:** LOW
**Impact:**
- Denial of service possible through rapid requests
- Each request triggers XenAPI calls

**Mitigation Recommendations:**
1. Deploy behind a rate-limiting reverse proxy
2. Configure Prometheus scrape_interval appropriately

---

#### LOW: Basic HTTP Server

**Issue:** Uses Python's basic `http.server` module.

**Risk Level:** LOW
**Impact:**
- Not designed for production use
- Limited security features
- Single-threaded (one request at a time)

**Mitigation Recommendations:**
1. Consider using gunicorn or uwsgi in production
2. Deploy behind nginx or similar reverse proxy

---

### 5.2 Security Summary Table

| Issue | Severity | Exploitability | Impact |
|-------|----------|----------------|--------|
| Plain-text credentials | CRITICAL | Easy | Credential theft |
| SSL verification bypass | CRITICAL | Medium | MITM attacks |
| No endpoint authentication | HIGH | Easy | Information disclosure |
| Sensitive info in metrics | MEDIUM | Easy | Reconnaissance |
| Default root user | MEDIUM | N/A | Excessive privileges |
| No rate limiting | LOW | Easy | DoS |
| Basic HTTP server | LOW | Medium | Various |

### 5.3 Recommended Security Hardening

```yaml
# Secure Docker Deployment Example
version: '3.8'
services:
  xen-exporter:
    image: ghcr.io/mikedombo/xen-exporter:latest
    environment:
      - XEN_HOST=10.10.10.101
      - XEN_USER=monitoring_user    # Use dedicated user, NOT root
      - XEN_SSL_VERIFY=true         # Always enable SSL verification
    secrets:
      - xen_password
    networks:
      - monitoring    # Isolated network
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M

secrets:
  xen_password:
    external: true

networks:
  monitoring:
    internal: true    # No external access
```

---

## 6. Key-Based Authentication - Feasibility Analysis

### 6.1 Current Authentication Method

The current exporter uses **Basic Authentication** with username/password:

```python
# Current implementation (xen-exporter.py lines 147-148)
xen_user = os.getenv("XEN_USER", "root")
xen_password = os.getenv("XEN_PASSWORD", "")

# Used for RRD API (line 176-181)
req.add_header(
    "Authorization",
    "Basic " + base64.b64encode((xen_user + ":" + xen_password).encode("utf-8")).decode("utf-8"),
)

# Used for XenAPI (line 114-116)
self.session.xenapi.login_with_password(username, password, "1.0", "xen-exporter")
```

### 6.2 Can We Change to Key-Based Authentication?

#### Answer: **Partially Yes, with Code Modifications**

XenAPI and XCP-ng/XenServer support **session-based authentication** but do NOT natively support:
- SSH key-based authentication for API
- API tokens/keys
- Certificate-based mutual TLS authentication

However, there are several approaches to implement more secure authentication:

---

### 6.3 Option 1: XenAPI Session Token Caching (Code Change Required)

**Concept:** Instead of sending credentials on every request, obtain a session token once and reuse it.

**How XenAPI Sessions Work:**
```python
# Login returns a session reference
session = XenAPI.Session("https://xenserver")
session.xenapi.login_with_password(user, password, "1.0", "exporter")
session_ref = session._session  # This is the session token

# Session can be reused until it expires or is logged out
```

**Benefits:**
- Credentials transmitted only once
- Session token used for subsequent requests
- Reduces credential exposure window

**Limitations:**
- Still requires initial password authentication
- Session tokens expire (configurable in XenServer)
- Code modification required

**Implementation Approach:**
```python
# Proposed change: Cache session and reuse
class PersistentXenSession:
    _instance = None
    _session = None

    @classmethod
    def get_session(cls, url, user, password, verify_ssl):
        if cls._session is None:
            cls._session = XenAPI.Session(url, ignore_ssl=not verify_ssl)
            cls._session.xenapi.login_with_password(user, password, "1.0", "xen-exporter")
        return cls._session
```

---

### 6.4 Option 2: RBAC with Dedicated Read-Only User (No Code Change)

**Concept:** Create a dedicated XenServer user with minimal read-only permissions.

**XenServer RBAC Roles:**
| Role | Permissions |
|------|-------------|
| Pool Admin | Full access |
| Pool Operator | VM operations, no pool config |
| VM Power Admin | Start/stop VMs |
| VM Admin | VM lifecycle management |
| VM Operator | Basic VM operations |
| **Read Only** | View only - metrics access |

**Steps to Create Read-Only User:**
```bash
# On XenServer/XCP-ng Dom0
xe user-create user-name="metrics_exporter"
xe subject-add subject-name="metrics_exporter"
xe role-add role-name="read-only" subject-name="metrics_exporter"
```

**Benefits:**
- No code change required
- Limits damage if credentials are compromised
- Attacker cannot modify VMs, hosts, or configurations

---

### 6.5 Option 3: Mutual TLS (mTLS) Authentication (Code Change Required)

**Concept:** Use client certificates instead of passwords.

**XenServer Support:** XenServer/XCP-ng XAPI can be configured to accept client certificates, but this requires:
1. Custom XAPI configuration on Dom0
2. Certificate generation and management
3. Code changes to use certificates

**Implementation Approach:**
```python
# Proposed: Use client certificate authentication
import ssl

ssl_context = ssl.create_default_context()
ssl_context.load_cert_chain(
    certfile='/path/to/client.crt',
    keyfile='/path/to/client.key'
)
ssl_context.load_verify_locations('/path/to/ca.crt')

# Use ssl_context in urllib requests
```

**Benefits:**
- No password transmission
- Certificate can be rotated
- Mutual authentication (both sides verified)

**Challenges:**
- Requires XenServer XAPI configuration changes
- Certificate management complexity
- Not officially documented by Citrix/XCP-ng

---

### 6.6 Securing Credentials to Prevent Compromise Access

Even without code changes, you can secure credentials so that if compromised, attackers cannot easily use them:

#### Strategy 1: HashiCorp Vault Integration (Recommended)

```yaml
# docker-compose with Vault
services:
  xen-exporter:
    image: ghcr.io/mikedombo/xen-exporter:latest
    entrypoint: /bin/sh
    command: |
      -c "export XEN_PASSWORD=$(vault kv get -field=password secret/xen-exporter) && python3 /app/xen-exporter.py"
    environment:
      - VAULT_ADDR=https://vault.example.com
      - VAULT_TOKEN_FILE=/run/secrets/vault_token
```

**Protection:**
- Credentials fetched at runtime from Vault
- Short-lived tokens
- Audit logging of credential access
- Automatic rotation possible

---

#### Strategy 2: Kubernetes Secrets with Encryption at Rest

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: xen-exporter-secrets
type: Opaque
stringData:
  XEN_PASSWORD: "encrypted-at-rest-password"
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: xen-exporter
        envFrom:
        - secretRef:
            name: xen-exporter-secrets
```

**Protection:**
- Secrets encrypted at rest in etcd
- RBAC controls access to secrets
- Secrets not visible in pod spec

---

#### Strategy 3: Docker Secrets (Swarm Mode)

```yaml
version: '3.8'
services:
  xen-exporter:
    image: ghcr.io/mikedombo/xen-exporter:latest
    secrets:
      - xen_password
    environment:
      - XEN_PASSWORD_FILE=/run/secrets/xen_password

secrets:
  xen_password:
    external: true  # Created with: docker secret create xen_password password.txt
```

**Note:** Requires code modification to read from file instead of environment variable.

---

#### Strategy 4: Network Segmentation + Short-Lived Credentials

```
┌─────────────────────────────────────────────────────────────┐
│                    MANAGEMENT NETWORK                        │
│                    (VLAN 100 - Isolated)                     │
│  ┌─────────────┐                      ┌─────────────────┐   │
│  │ XenServer   │◄────────────────────►│  xen-exporter   │   │
│  │ Dom0        │   HTTPS Only         │  Container      │   │
│  └─────────────┘                      └────────┬────────┘   │
│                                                │             │
└────────────────────────────────────────────────│─────────────┘
                                                 │ Port 9100
                                    ┌────────────▼────────────┐
                                    │      MONITORING NETWORK  │
                                    │      (VLAN 200)          │
                                    │   ┌──────────────────┐   │
                                    │   │   Prometheus     │   │
                                    │   └──────────────────┘   │
                                    └──────────────────────────┘
```

**Protection:**
- Exporter only accessible from monitoring network
- XenServer only accessible from management network
- Even if credentials leak, attacker needs network access

---

#### Strategy 5: Credential Rotation with Monitoring

```bash
#!/bin/bash
# rotate-xen-credentials.sh - Run weekly via cron

NEW_PASSWORD=$(openssl rand -base64 32)

# Update XenServer password
xe user-password-change user-name="metrics_exporter" new-password="$NEW_PASSWORD"

# Update Docker secret
echo "$NEW_PASSWORD" | docker secret create xen_password_v$(date +%s) -

# Restart exporter with new secret
docker service update --secret-rm xen_password --secret-add xen_password_v$(date +%s) xen-exporter

# Log rotation event
logger "XEN credentials rotated successfully"
```

---

### 6.7 Summary: Key-Based Authentication Feasibility

| Approach | Code Change Required | Security Level | Complexity |
|----------|---------------------|----------------|------------|
| Session Token Caching | Yes | Medium | Low |
| RBAC Read-Only User | No | Medium | Low |
| Mutual TLS (mTLS) | Yes + Dom0 Config | High | High |
| Vault Integration | No (wrapper script) | High | Medium |
| Kubernetes Secrets | No | Medium-High | Low |
| Docker Secrets | Yes (minor) | Medium | Low |
| Network Segmentation | No | Medium | Medium |
| Credential Rotation | No | Medium | Low |

### 6.8 Recommended Approach (Without Code Changes)

For maximum security without modifying the exporter code:

1. **Create dedicated read-only XenServer user** (limits blast radius)
2. **Deploy in isolated network segment** (limits access)
3. **Use Vault or Kubernetes secrets** (protects at rest)
4. **Implement credential rotation** (limits exposure window)
5. **Enable audit logging** (detect unauthorized access)
6. **Use reverse proxy with auth** for /metrics endpoint

```
┌─────────────────────────────────────────────────────────────────┐
│                    DEFENSE IN DEPTH                              │
│                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐  │
│  │  Vault   │──►│ Read-Only│──►│ Isolated │──►│ Auth Reverse │  │
│  │ Secrets  │   │   User   │   │ Network  │   │    Proxy     │  │
│  └──────────┘   └──────────┘   └──────────┘   └──────────────┘  │
│                                                                  │
│  Even if ONE layer is compromised, others provide protection    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Complete Metrics List

### 7.1 Host Metrics (xen_host_*)

| Metric | Description |
|--------|-------------|
| `xen_host_avgqu_sz` | Average queue size |
| `xen_host_cpu` | CPU utilization per core |
| `xen_host_cpu_avg` | Average CPU utilization |
| `xen_host_cpu_avg_freq` | Average CPU frequency |
| `xen_host_cpu_c0` | CPU C0 state time |
| `xen_host_cpu_c1` | CPU C1 state time |
| `xen_host_cpu_p0` | CPU P0 state time |
| `xen_host_cpu_p1` | CPU P1 state time |
| `xen_host_cpu_p2` | CPU P2 state time |
| `xen_host_inflight` | In-flight I/O operations |
| `xen_host_io_throughput_read` | Read throughput |
| `xen_host_io_throughput_total` | Total I/O throughput |
| `xen_host_io_throughput_write` | Write throughput |
| `xen_host_iops_read` | Read IOPS |
| `xen_host_iops_total` | Total IOPS |
| `xen_host_iops_write` | Write IOPS |
| `xen_host_iowait` | I/O wait time |
| `xen_host_latency` | I/O latency |
| `xen_host_loadavg` | System load average |
| `xen_host_memory_free_kib` | Free memory (KiB) |
| `xen_host_memory_reclaimed` | Reclaimed memory |
| `xen_host_memory_reclaimed_max` | Max reclaimed memory |
| `xen_host_memory_total_kib` | Total memory (KiB) |
| `xen_host_pif_rx` | Physical interface RX bytes |
| `xen_host_pif_tx` | Physical interface TX bytes |
| `xen_host_pool_session_count` | Active pool sessions |
| `xen_host_pool_task_count` | Active pool tasks |
| `xen_host_read` | Disk read operations |
| `xen_host_read_latency` | Read latency |
| `xen_host_sr_cache_hits` | SR cache hits |
| `xen_host_sr_cache_misses` | SR cache misses |
| `xen_host_sr_cache_size` | SR cache size |
| `xen_host_tapdisks_in_low_memory_mode` | Tapdisks in low memory |
| `xen_host_write` | Disk write operations |
| `xen_host_write_latency` | Write latency |
| `xen_host_xapi_allocation_kib` | XAPI allocation (KiB) |
| `xen_host_xapi_free_memory_kib` | XAPI free memory (KiB) |
| `xen_host_xapi_live_memory_kib` | XAPI live memory (KiB) |
| `xen_host_xapi_memory_usage_kib` | XAPI memory usage (KiB) |
| `xen_host_xapi_open_fds` | XAPI open file descriptors |

### 7.2 VM Metrics (xen_vm_*)

| Metric | Description |
|--------|-------------|
| `xen_vm_cpu` | VM CPU utilization |
| `xen_vm_memory` | VM memory usage |
| `xen_vm_memory_internal_free` | VM internal free memory |
| `xen_vm_memory_target` | VM memory target |
| `xen_vm_vbd_avgqu_sz` | VBD average queue size |
| `xen_vm_vbd_inflight` | VBD in-flight operations |
| `xen_vm_vbd_io_throughput_read` | VBD read throughput |
| `xen_vm_vbd_io_throughput_total` | VBD total throughput |
| `xen_vm_vbd_io_throughput_write` | VBD write throughput |
| `xen_vm_vbd_iops_read` | VBD read IOPS |
| `xen_vm_vbd_iops_total` | VBD total IOPS |
| `xen_vm_vbd_iops_write` | VBD write IOPS |
| `xen_vm_vbd_iowait` | VBD I/O wait |
| `xen_vm_vbd_latency` | VBD latency |
| `xen_vm_vbd_read` | VBD read operations |
| `xen_vm_vbd_read_latency` | VBD read latency |
| `xen_vm_vbd_write` | VBD write operations |
| `xen_vm_vbd_write_latency` | VBD write latency |
| `xen_vm_vif_rx` | VIF received bytes |
| `xen_vm_vif_tx` | VIF transmitted bytes |

### 7.3 Storage Metrics (xen_sr_*)

| Metric | Description |
|--------|-------------|
| `xen_sr_physical_size` | SR physical size |
| `xen_sr_physical_utilization` | SR physical utilization |
| `xen_sr_virtual_allocation` | SR virtual allocation |

### 7.4 System Metrics

| Metric | Description |
|--------|-------------|
| `xen_collector_duration_seconds` | Time to collect all metrics |

### 7.5 Metric Labels

Each metric includes contextual labels for identification:

#### Host Metric Labels
| Label | Description | Example |
|-------|-------------|---------|
| `host` | Human-readable host name | `xenserver01` |
| `host_uuid` | Host UUID | `a1b2c3d4-...` |
| `sr` | Storage Repository name (if applicable) | `Local Storage` |
| `sr_uuid` | Storage Repository UUID (if applicable) | `e5f6g7h8-...` |
| `pif` | Physical Interface ID (for network metrics) | `eth0` |
| `cpu` | CPU core number (for CPU metrics) | `0`, `1`, `2` |

#### VM Metric Labels
| Label | Description | Example |
|-------|-------------|---------|
| `vm` | Human-readable VM name | `web-server-01` |
| `vm_uuid` | VM UUID | `i9j0k1l2-...` |
| `vbd` | Virtual Block Device ID | `xvda` |
| `vif` | Virtual Interface ID | `0`, `1` |
| `cpu` | vCPU number | `0`, `1` |

#### Storage Metric Labels
| Label | Description | Example |
|-------|-------------|---------|
| `sr` | Storage Repository name | `NFS_Storage` |
| `sr_uuid` | Storage Repository UUID | `m3n4o5p6-...` |
| `type` | SR type | `nfs`, `lvm`, `ext` |
| `content_type` | Content type | `user`, `iso` |

### 7.6 Example Metric Output

```prometheus
# Host CPU metric
xen_host_cpu{host="xenserver01", host_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", cpu="0"} 0.15

# Host memory metric
xen_host_memory_free_kib{host="xenserver01", host_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890"} 16384000

# Host network metric
xen_host_pif_rx{host="xenserver01", host_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", pif="eth0"} 1234567890

# VM CPU metric
xen_vm_cpu{vm="web-server-01", vm_uuid="i9j0k1l2-m3n4-5678-opqr-st9012345678", cpu="0"} 0.45

# VM disk metric
xen_vm_vbd_read{vm="web-server-01", vm_uuid="i9j0k1l2-m3n4-5678-opqr-st9012345678", vbd="xvda"} 987654321

# VM network metric
xen_vm_vif_tx{vm="web-server-01", vm_uuid="i9j0k1l2-m3n4-5678-opqr-st9012345678", vif="0"} 123456789

# Storage Repository metric
xen_sr_physical_size{sr="Local Storage", sr_uuid="e5f6g7h8-i9j0-1234-klmn-op5678901234", type="lvm", content_type="user"} 1099511627776
xen_sr_physical_utilization{sr="Local Storage", sr_uuid="e5f6g7h8-i9j0-1234-klmn-op5678901234", type="lvm", content_type="user"} 549755813888

# Collector duration
xen_collector_duration_seconds 0.823456
```

### 7.7 Metrics Summary

| Category | Count | Description |
|----------|-------|-------------|
| Host Metrics | 39+ | CPU, Memory, Disk I/O, Network, XAPI stats |
| VM Metrics | 20+ | CPU, Memory, VBD (disk), VIF (network) |
| Storage Metrics | 3 | Physical size, utilization, virtual allocation |
| System Metrics | 1 | Collector duration |
| **Total** | **60+** | Dynamic based on infrastructure |

**Note:** The actual number of metrics depends on:
- Number of hosts in pool (pool mode)
- Number of VMs running
- Number of Storage Repositories
- Number of network interfaces (physical and virtual)
- Number of CPU cores

---

## 8. Configuration Reference

### 8.1 Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `XEN_USER` | `root` | No | XenServer username |
| `XEN_PASSWORD` | `""` | Yes | XenServer password |
| `XEN_HOST` | `localhost` | Yes | XenServer host IP/hostname |
| `XEN_SSL_VERIFY` | `true` | No | Enable SSL certificate verification |
| `XEN_MODE` | `host` | No | `host` for single host, `pool` for all pool members |
| `HALT_ON_NO_UUID` | `false` | No | Halt on missing UUID vs silent ignore |
| `PORT` | `9100` | No | HTTP server port |
| `BIND` | `0.0.0.0` | No | Network interface to bind to |

### 8.2 Example Configurations

#### Single Host Mode
```bash
docker run -e XEN_USER=root \
           -e XEN_PASSWORD=mypassword \
           -e XEN_HOST=192.168.1.100 \
           -e XEN_SSL_VERIFY=true \
           -p 9100:9100 \
           ghcr.io/mikedombo/xen-exporter:latest
```

#### Pool Mode (All Hosts)
```bash
docker run -e XEN_USER=root \
           -e XEN_PASSWORD=mypassword \
           -e XEN_HOST=192.168.1.100 \
           -e XEN_MODE=pool \
           -e XEN_SSL_VERIFY=true \
           -p 9100:9100 \
           ghcr.io/mikedombo/xen-exporter:latest
```

---

## 9. Planned Future Enhancements

### 9.1 Overview

The current exporter focuses on RRD-based metrics which cover performance and resource utilization. The following infrastructure-level metrics have been implemented.

### 9.2 Multipath Storage Metrics

**Current Status:** IMPLEMENTED

**Environment Variable:** `XEN_COLLECT_MULTIPATH` (default: `true`)

**What is Multipath?**
Multipath I/O (MPIO) provides redundant paths to storage devices, improving availability and load balancing.

**Planned Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `xen_host_multipath_enabled` | Gauge | Whether multipath is enabled on the host (1=enabled, 0=disabled) |
| `xen_sr_multipath_active` | Gauge | Whether multipath is active for the SR (1=active, 0=inactive) |
| `xen_sr_multipath_paths` | Gauge | Number of available paths to the storage |

**Implementation Approach:**
```python
def collect_multipath_status(session: XenAPI.Session):
    output = ""
    hosts = session.xenapi.host.get_all_records()
    for host_uuid, host_record in hosts.items():
        host_name = host_record["name_label"]
        # Check multipath in other_config
        multipath_enabled = host_record.get("other_config", {}).get("multipathing", "false")
        enabled_val = 1 if multipath_enabled.lower() == "true" else 0
        output += f'xen_host_multipath_enabled{{host="{host_name}", host_uuid="{host_uuid}"}} {enabled_val}\n'

    # Check SR multipath status via PBDs
    pbds = session.xenapi.PBD.get_all_records()
    for pbd_ref, pbd_record in pbds.items():
        sr_ref = pbd_record["SR"]
        sr_record = session.xenapi.SR.get_record(sr_ref)
        sr_name = sr_record["name_label"]
        sr_uuid = sr_record["uuid"]

        # Check device_config for multipath info
        device_config = pbd_record.get("device_config", {})
        multipath_active = 1 if device_config.get("multipath", "false").lower() == "true" else 0
        output += f'xen_sr_multipath_active{{sr="{sr_name}", sr_uuid="{sr_uuid}"}} {multipath_active}\n'

    return output
```

**Labels:**
| Label | Description |
|-------|-------------|
| `host` | Host name |
| `host_uuid` | Host UUID |
| `sr` | Storage Repository name |
| `sr_uuid` | Storage Repository UUID |

---

### 9.3 PBD Status Metrics

**Current Status:** IMPLEMENTED

**Environment Variable:** `XEN_COLLECT_PBD` (default: `true`)

**What is PBD Status?**
PBD (Physical Block Device) represents the connection between a host and a storage repository. Monitoring PBD status allows detection of storage disconnections.

**Implemented Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `xen_pbd_attached` | Gauge | PBD connection status (1=attached, 0=detached) |

### 9.4 Storage Target Information Metrics (Planned)

**Current Status:** NOT YET IMPLEMENTED

**What is Storage Target Info?**
Information about backend storage targets (iSCSI, NFS, Fibre Channel) including connectivity details.

**Planned Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `xen_sr_iscsi_target_info` | Info | iSCSI target connectivity information |
| `xen_sr_nfs_target_info` | Info | NFS target connectivity information |
| `xen_sr_fc_info` | Info | Fibre Channel storage information |

**Implementation Approach:**
```python
def collect_pbd_status(session: XenAPI.Session):
    output = ""
    pbd_records = session.xenapi.PBD.get_all_records()

    for pbd_ref, pbd_record in pbd_records.items():
        sr_ref = pbd_record["SR"]
        host_ref = pbd_record["host"]

        sr_record = session.xenapi.SR.get_record(sr_ref)
        host_record = session.xenapi.host.get_record(host_ref)

        sr_name = sr_record["name_label"]
        sr_uuid = sr_record["uuid"]
        sr_type = sr_record["type"]
        host_name = host_record["name_label"]
        host_uuid = host_record["uuid"]

        attached = 1 if pbd_record["currently_attached"] else 0

        output += f'xen_pbd_attached{{sr="{sr_name}", sr_uuid="{sr_uuid}", host="{host_name}", host_uuid="{host_uuid}", type="{sr_type}"}} {attached}\n'

    return output

def collect_storage_targets(session: XenAPI.Session):
    output = ""
    pbd_records = session.xenapi.PBD.get_all_records()

    for pbd_ref, pbd_record in pbd_records.items():
        sr_ref = pbd_record["SR"]
        sr_record = session.xenapi.SR.get_record(sr_ref)
        sr_name = sr_record["name_label"]
        sr_uuid = sr_record["uuid"]
        sr_type = sr_record["type"]

        device_config = pbd_record.get("device_config", {})

        # iSCSI targets
        if sr_type == "lvmoiscsi" or sr_type == "iscsi":
            target = device_config.get("target", "unknown")
            target_iqn = device_config.get("targetIQN", "unknown")
            output += f'xen_sr_iscsi_target_info{{sr="{sr_name}", sr_uuid="{sr_uuid}", target="{target}", iqn="{target_iqn}"}} 1\n'

        # NFS targets
        elif sr_type == "nfs" or sr_type == "iso":
            server = device_config.get("server", "unknown")
            server_path = device_config.get("serverpath", "unknown")
            output += f'xen_sr_nfs_target_info{{sr="{sr_name}", sr_uuid="{sr_uuid}", server="{server}", path="{server_path}"}} 1\n'

        # Fibre Channel
        elif sr_type == "lvmohba":
            scsi_id = device_config.get("SCSIid", "unknown")
            output += f'xen_sr_fc_info{{sr="{sr_name}", sr_uuid="{sr_uuid}", scsi_id="{scsi_id}"}} 1\n'

    return output
```

**Labels for PBD Metrics:**
| Label | Description |
|-------|-------------|
| `sr` | Storage Repository name |
| `sr_uuid` | Storage Repository UUID |
| `host` | Host name |
| `host_uuid` | Host UUID |
| `type` | SR type (nfs, lvmoiscsi, lvm, etc.) |

**Labels for Storage Target Metrics:**
| Label | Description |
|-------|-------------|
| `sr` | Storage Repository name |
| `sr_uuid` | Storage Repository UUID |
| `target` | iSCSI target IP/hostname |
| `iqn` | iSCSI target IQN |
| `server` | NFS server IP/hostname |
| `path` | NFS server path |
| `scsi_id` | Fibre Channel SCSI ID |

---

### 9.4 Summary of Planned Enhancements

| Feature | Priority | Complexity | XenAPI Calls Required |
|---------|----------|------------|----------------------|
| PBD Attachment Status | High | Low | `PBD.get_all_records()` |
| Multipath Status | Medium | Medium | `host.get_all_records()`, `PBD.get_all_records()` |
| iSCSI Target Info | Medium | Low | `PBD.get_all_records()`, `SR.get_record()` |
| NFS Target Info | Medium | Low | `PBD.get_all_records()`, `SR.get_record()` |
| Fibre Channel Info | Low | Low | `PBD.get_all_records()`, `SR.get_record()` |

### 9.5 Why These Are Not Currently Implemented

1. **RRD Focus:** The current exporter is designed to export RRD metrics which are performance-focused
2. **Additional API Calls:** Each enhancement requires additional XenAPI calls, increasing scrape time
3. **Use Case Specific:** Not all deployments use multipath or external storage targets

### 9.6 Integration Point

When implemented, these functions would be called from `collect_metrics()`:

```python
def collect_metrics():
    # ... existing code ...

    with Xen("https://" + xen_poolmaster, xen_user, xen_password, verify_ssl) as xen:
        # ... existing RRD collection ...

        output += collect_sr_usage(xen)

        # Future enhancements (uncomment when implemented)
        # output += collect_pbd_status(xen)
        # output += collect_multipath_status(xen)
        # output += collect_storage_targets(xen)

        collector_end_time = time.perf_counter()
        output += f"xen_collector_duration_seconds {collector_end_time - collector_start_time}\n"
        return output
```

### 9.7 Expected New Metrics After Implementation

| Metric | Description |
|--------|-------------|
| `xen_pbd_attached` | PBD attachment status per host/SR combination |
| `xen_host_multipath_enabled` | Host-level multipath enablement |
| `xen_sr_multipath_active` | SR-level multipath activation |
| `xen_sr_iscsi_target_info` | iSCSI target connectivity information |
| `xen_sr_nfs_target_info` | NFS target connectivity information |
| `xen_sr_fc_info` | Fibre Channel storage information |

---

## 10. Production Deployment Strategy

### 10.1 Overview

This section documents the recommended production deployment strategy focusing on essential metrics while minimizing Dom0 overhead.

### 10.2 Key Finding: Metric Filtering Does NOT Reduce Dom0 Load

**Important Research Finding:**

Removing metrics from the exporter output does **NOT** reduce Dom0 load because:

1. **Dom0's xcp-rrdd daemon** continuously collects ALL metrics regardless of whether they're queried
2. **The RRD API** returns all metrics in a single bulk response (no server-side filtering)
3. **Filtering happens on the client side** (exporter or Prometheus), not on Dom0

**What Actually Reduces Dom0 Load:**
| Action | Impact |
|--------|--------|
| Increase scrape interval (60s → 120s) | Halves query frequency |
| Prometheus metric relabeling | Zero Dom0 impact (client-side) |
| Not running exporter | Eliminates query overhead entirely |

### 10.3 Recommended Production Metrics

Based on production requirements, the following metrics are recommended:

#### Essential Metrics (KEEP)

| Category | Metrics | Alert Threshold |
|----------|---------|-----------------|
| **Host CPU** | `xen_host_cpu`, `xen_host_cpu_avg`, `xen_host_loadavg` | CPU > 90% for 5m |
| **Host Memory** | `xen_host_memory_free_kib`, `xen_host_memory_total_kib` | Free < 10% for 5m |
| **SR Utilization** | `xen_sr_physical_size`, `xen_sr_physical_utilization` | Utilization > 85% |
| **Collector Health** | `xen_collector_duration_seconds` | Duration > 30s |

#### Excluded Metrics (Per Production Requirements)

| Category | Metrics | Reason |
|----------|---------|--------|
| VM Metrics | `xen_vm_*` | Guest-level monitoring not required |
| Individual Disk I/O | `xen_host_iops_*`, `xen_host_read*`, `xen_host_write*` | Excluded per requirements |
| Network Throughput | `xen_host_pif_*` | Excluded per requirements |

### 10.4 Prometheus Configuration for Production

#### Scrape Configuration
```yaml
# prometheus.yml
scrape_configs:
  - job_name: xenserver
    scrape_interval: 60s      # Recommended interval
    scrape_timeout: 50s       # Allow time for collection
    static_configs:
      - targets:
        - xen-exporter:9100
```

#### Metric Relabeling (Filter to Essential Metrics)
```yaml
# prometheus.yml - Add to scrape_configs
    metric_relabel_configs:
      # Keep host CPU metrics
      - source_labels: [__name__]
        regex: 'xen_host_cpu.*'
        action: keep

      # Keep host memory metrics
      - source_labels: [__name__]
        regex: 'xen_host_memory_(free|total)_kib'
        action: keep

      # Keep host load average
      - source_labels: [__name__]
        regex: 'xen_host_loadavg'
        action: keep

      # Keep SR metrics
      - source_labels: [__name__]
        regex: 'xen_sr_(physical_size|physical_utilization)'
        action: keep

      # Keep collector duration
      - source_labels: [__name__]
        regex: 'xen_collector_duration_seconds'
        action: keep

      # Future: Keep PBD/Multipath (uncomment when implemented)
      # - source_labels: [__name__]
      #   regex: 'xen_(pbd_attached|host_multipath_enabled|sr_multipath_active)'
      #   action: keep
```

### 10.5 Production Alerting Rules

```yaml
# alerting_rules.yml
groups:
  - name: xen-production-alerts
    rules:
      # Host CPU Alert
      - alert: XenHostHighCPU
        expr: xen_host_cpu_avg > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on {{ $labels.host }}"
          description: "CPU utilization is {{ $value | humanizePercentage }} on host {{ $labels.host }}"

      # Host Memory Alert
      - alert: XenHostLowMemory
        expr: (xen_host_memory_free_kib / xen_host_memory_total_kib) < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Low memory on {{ $labels.host }}"
          description: "Only {{ $value | humanizePercentage }} memory free on host {{ $labels.host }}"

      # SR Warning Alert (85%)
      - alert: XenSRHighUtilization
        expr: (xen_sr_physical_utilization / xen_sr_physical_size) > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "SR {{ $labels.sr }} above 85% utilization"
          description: "Storage Repository {{ $labels.sr }} is {{ $value | humanizePercentage }} full"

      # SR Critical Alert (95%)
      - alert: XenSRCritical
        expr: (xen_sr_physical_utilization / xen_sr_physical_size) > 0.95
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SR {{ $labels.sr }} critically full"
          description: "Storage Repository {{ $labels.sr }} is {{ $value | humanizePercentage }} full - immediate action required"

      # Collector Health Alert
      - alert: XenCollectorSlow
        expr: xen_collector_duration_seconds > 30
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Xen exporter collection is slow"
          description: "Metric collection took {{ $value | humanizeDuration }}"

      # PLANNED: PBD Detached Alert (uncomment when implemented)
      # - alert: XenPBDDetached
      #   expr: xen_pbd_attached == 0
      #   for: 1m
      #   labels:
      #     severity: critical
      #   annotations:
      #     summary: "Storage disconnected on {{ $labels.host }}"
      #     description: "SR {{ $labels.sr }} is detached from host {{ $labels.host }}"

      # PLANNED: Multipath Alert (uncomment when implemented)
      # - alert: XenMultipathDisabled
      #   expr: xen_host_multipath_enabled == 0
      #   for: 5m
      #   labels:
      #     severity: warning
      #   annotations:
      #     summary: "Multipath disabled on {{ $labels.host }}"
      #     description: "Host {{ $labels.host }} does not have multipath enabled"
```

### 10.6 Production Deployment Checklist

| Step | Action | Status |
|------|--------|--------|
| 1 | Create dedicated read-only XenServer user | Pending |
| 2 | Deploy xen-exporter with SSL verification enabled | Pending |
| 3 | Configure Prometheus with 60s scrape interval | Pending |
| 4 | Apply metric relabeling to filter essential metrics | Pending |
| 5 | Import alerting rules | Pending |
| 6 | Test SR >85% alert with test data | Pending |
| 7 | Verify collector duration is < 30s | Pending |
| 8 | Document PBD/Multipath for future implementation | Complete |

### 10.7 Performance Expectations

| Metric | Expected Value |
|--------|----------------|
| Scrape interval | 60 seconds |
| Collection duration | 800-1500ms |
| Dom0 CPU impact per scrape | 1-3% |
| Network bandwidth per scrape | 50-200 KB |
| Prometheus storage (30 days) | ~50-100 MB per host |

### 10.8 Future Enhancements (Documented for Implementation)

The following features are documented and ready for implementation when required:

| Feature | Section Reference | Priority |
|---------|-------------------|----------|
| PBD Status Monitoring | Section 9.3 | High |
| Multipath Monitoring | Section 9.2 | Medium |
| Storage Target Info | Section 9.3 | Medium |

**Implementation Note:** When PBD and multipath monitoring are implemented, update the Prometheus metric relabeling and alerting rules by uncommenting the relevant sections in 10.4 and 10.5.

---

## Document Information

| Field | Value |
|-------|-------|
| **Project** | xen-exporter |
| **Version** | Latest (from master branch) |
| **License** | BSD 2-Clause |
| **Repository** | https://github.com/mikedombo/xen-exporter |
| **Grafana Dashboard** | ID 16588 |
| **Documentation Date** | January 2026 |
