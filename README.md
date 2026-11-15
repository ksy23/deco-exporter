# TP-Link Deco Prometheus Exporter (`tplink-deco-api`)

A lightweight Python Prometheus exporter for **TP-Link Deco** mesh routers (tested on **Deco BE11000** Wi-Fi 7) built on [`roquerodrigo/tplink-deco-api`](https://github.com). It exposes router CPU/memory usage, internet connectivity, mesh node health, connected client metadata, and accurately scaled Rx/Tx bandwidth metrics on port **`7550`**.

## Why This Exporter?

* **Accurate Bandwidth Calibration (`SPEED_MULTIPLIER=125`):** Newer TP-Link Deco firmware (such as Wi-Fi 7 BE11000) reports `down_speed` and `up_speed` in **Kbps** rather than `KB/s` or `Bytes/s`. Multiplying by `125` (`1000 bits / 8`) converts the raw API values into exact **Bytes/sec** so downstream dashboards (`MB/s` and `Mbps`) match real-world speed tests.
* **Aggregate & Per-Client Throughput:** Pulls total mesh download/upload speeds via `get_client_totals()` (with automatic fallback to summing client speeds) alongside individual per-client speeds.
* **Drop-In Compatibility:** Outputs standardized `deco_*` Prometheus metric names designed to feed directly into Prometheus and Homarr v2 custom widgets.

---

## Project Files

```text
deco-exporter/
├── Dockerfile
├── docker-compose.yml
├── exporter.py
├── requirements.txt
└── README.md
```

---

## Configuration (Environment Variables)

All settings can be overridden via environment variables in `docker-compose.yml`:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DECO_HOST` | Gateway IP address of your main Deco unit (do not include `http://`) | `192.168.1.1` |
| `DECO_USERNAME` | Deco web UI username (`admin` or your TP-Link ID email) | `admin` |
| `DECO_PASSWORD` | Your TP-Link ID / Deco owner password | *(empty)* |
| `POLL_INTERVAL` | Seconds between Deco API polls (recommended: `15`–`30`) | `30` |
| `METRICS_PORT` | HTTP port where `/metrics` is served | `7550` |
| `SPEED_MULTIPLIER` | Conversion factor to `Bytes/s` (`125` for `Kbps`, `1024` for `KB/s`, `1` for `B/s`) | `125` |

---

## Deployment (Docker Compose)

1. **Create your `docker-compose.yml`:**

```yaml
services:
  deco_exporter:
    build: .
    container_name: deco_exporter
    ports:
      - "7550:7550"
    environment:
      DECO_HOST: "192.168.1.1"
      DECO_USERNAME: "admin"
      DECO_PASSWORD: "your-tplink-password"
      POLL_INTERVAL: "30"
      METRICS_PORT: "7550"
      SPEED_MULTIPLIER: "125"
    restart: unless-stopped
```

2. **Build and start the container:**

```bash
docker compose up -d --build
```

3. **Verify logs and `/metrics` output:**

```bash
docker logs -f deco_exporter
curl -s http://localhost:7550/metrics | grep ^deco_
```

---

## Prometheus Scrape Configuration

Add the `deco` job to your `prometheus.yml` pointing to port **`7550`** (match `scrape_interval` to your `POLL_INTERVAL`):

```yaml
scrape_configs:
  - job_name: 'deco'
    scrape_interval: 30s
    static_configs:
      - targets: ['<docker-host-ip>:7550']
```

Reload or restart Prometheus to begin scraping.

---

## Exported Metrics

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `deco_internet_online` | Gauge | — | Internet connectivity (`1` = online, `0` = offline) |
| `deco_cpu_usage` | Gauge | — | Router CPU load ratio (`0.0` – `1.0`) |
| `deco_memory_usage` | Gauge | — | Router memory usage ratio (`0.0` – `1.0`) |
| `deco_total_rx_bytes_per_second` | Gauge | — | Total mesh download throughput (`Bytes/s`) |
| `deco_total_tx_bytes_per_second` | Gauge | — | Total mesh upload throughput (`Bytes/s`) |
| `deco_clients_total` | Gauge | — | Total number of connected clients |
| `deco_nodes_total` | Gauge | — | Total number of Deco mesh units |
| `deco_nodes_online` | Gauge | — | Number of online Deco mesh units |
| `deco_firmware_update_available` | Gauge | — | Firmware update status (`1` = available, `0` = up to date) |
| `deco_device_info` | Gauge | `name`, `mac`, `ip`, `model`, `firmware`, `hardware`, `master`, `connection_type` | Metadata for each Deco mesh unit |
| `deco_node_online` | Gauge | `name`, `mac` | Per-node online status (`1` / `0`) |
| `deco_node_clients_total` | Gauge | `name`, `mac` | Connected client count per Deco node |
| `deco_node_signal_2g` | Gauge | `name`, `mac` | Node 2.4 GHz signal metric |
| `deco_node_signal_5g` | Gauge | `name`, `mac` | Node 5 GHz signal metric |
| `deco_client_info` | Gauge | `name`, `mac`, `ip`, `connection_type`, `interface`, `online` | Connected client metadata |
| `deco_client_rx_bytes_per_second` | Gauge | `name`, `mac` | Per-client download speed (`Bytes/s`) |
| `deco_client_tx_bytes_per_second` | Gauge | `name`, `mac` | Per-client upload speed (`Bytes/s`) |

---

## Troubleshooting

* **`Failed to POST https://http://...`:** Ensure `DECO_HOST` contains **only the IP address** (e.g., `192.168.1.1`) without `http://` or `https://`.
* **Session / Login Conflicts:** TP-Link Deco firmware allows only one active web admin session at a time. Opening the Deco web UI in a browser while the exporter is running may briefly log one session out, though the exporter will automatically re-authenticate on its next poll cycle.
