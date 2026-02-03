# xen-exporter

XCP-ng / XenServer Prometheus Exporter

Automatically exports all statistics from the [RRD metrics database](https://xapi-project.github.io/xen-api/metrics.html) plus PBD and multipath status via XenAPI.

> **Fork of [mikedombo/xen-exporter](https://github.com/mikedombo/xen-exporter)** with additional features and improvements. See [Changes from Upstream](#changes-from-upstream).

## Quick Start

```bash
docker run -e XEN_USER=root -e XEN_PASSWORD=<password> -e XEN_HOST=<host> \
  -p 9100:9100 ghcr.io/mikedombo/xen-exporter:latest
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `XEN_HOST` | `localhost` | XenServer host IP/hostname |
| `XEN_USER` | `root` | XenServer username (default for all hosts) |
| `XEN_PASSWORD` | `""` | XenServer password (default for all hosts) |
| `XEN_CREDENTIALS` | `""` | Per-host credentials (see below) |
| `XEN_SSL_VERIFY` | `true` | Enable SSL certificate verification |
| `XEN_MODE` | `host` | `host` for single host, `pool` for all pool members |
| `XEN_COLLECT_PBD` | `true` | Collect PBD attachment status metrics |
| `XEN_COLLECT_MULTIPATH` | `true` | Collect multipath status metrics |
| `HALT_ON_NO_UUID` | `false` | Halt on missing UUID vs silent ignore |
| `PORT` | `9100` | HTTP server port |
| `BIND` | `0.0.0.0` | Network interface to bind |

### Per-Host Credentials

When hosts in a pool have different credentials, use `XEN_CREDENTIALS` to specify them individually. Hosts not listed will use `XEN_USER`/`XEN_PASSWORD` as fallback.

**Format:** One host per line: `host user password`

```bash
# Add hosts one by one
XEN_CREDENTIALS=""
XEN_CREDENTIALS+="10.10.10.1 admin1 password1"$'\n'
XEN_CREDENTIALS+="10.10.10.2 admin2 password2"$'\n'
XEN_CREDENTIALS+="10.10.10.3 admin3 'password with spaces'"$'\n'
export XEN_CREDENTIALS
```

**docker-compose.yml with per-host credentials:**
```yaml
services:
  xen-exporter:
    image: ghcr.io/mikedombo/xen-exporter:latest
    environment:
      - XEN_HOST=10.10.10.1
      - XEN_USER=root
      - XEN_PASSWORD=fallback_password
      - XEN_SSL_VERIFY=false
      - |
        XEN_CREDENTIALS=
        10.10.10.1 admin1 password1
        10.10.10.2 admin2 password2
        10.10.10.3 admin3 'password with spaces'
    ports:
      - "9100:9100"
```

## Example Setup

**docker-compose.yml**
```yaml
services:
  xen-exporter:
    image: ghcr.io/mikedombo/xen-exporter:latest
    environment:
      - XEN_HOST=10.10.10.101
      - XEN_USER=root
      - XEN_PASSWORD=mypassword
      - XEN_SSL_VERIFY=false
    ports:
      - "9100:9100"
```

**prometheus.yml**
```yaml
scrape_configs:
  - job_name: xenserver
    scrape_interval: 60s
    scrape_timeout: 50s
    static_configs:
      - targets: ["xen-exporter:9100"]
```

## Grafana Dashboard

A dashboard is [available here](https://grafana.com/grafana/dashboards/16588) (ID: 16588).

![Dashboard](https://grafana.com/api/dashboards/16588/images/12479/image)

## Changes from Upstream

This fork includes significant improvements over the original [mikedombo/xen-exporter](https://github.com/mikedombo/xen-exporter):

### New Features
- **PBD monitoring** (`xen_pbd_attached`) - Detect storage disconnections
- **Multipath monitoring** (`xen_host_multipath_enabled`, `xen_sr_multipath_active`)
- **prometheus_client library** - Proper metric types, HELP/TYPE headers
- **Xenopsd metrics** - 14 metrics for domain manager process monitoring
- **Configurable PORT/BIND** - Customize HTTP server binding
- **Environment validation** - Startup checks for required variables

### Code Quality
- Thread-safe global caches
- HTTP request timeouts
- Bounded cache sizes
- Proper error handling and logging
- Type annotations
- Fixed variable shadowing issues

### Documentation
- Complete metrics reference with units and descriptions
- PromQL query examples
- Alerting rule examples
- Security analysis and hardening recommendations

## Documentation

See [METRICS_REFERENCE.md](METRICS_REFERENCE.md) for:
- Complete metrics list with descriptions
- Label reference
- PromQL query examples
- Alerting rules
- Architecture and security considerations

## License

BSD 2-Clause License
