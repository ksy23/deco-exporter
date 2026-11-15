import os
import time
from prometheus_client import Gauge, start_http_server
from tplink_deco_api import DecoClient

DECO_HOST = os.getenv("DECO_HOST", "192.168.1.1")
DECO_USERNAME = os.getenv("DECO_USERNAME", "admin")
DECO_PASSWORD = os.getenv("DECO_PASSWORD", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "7550"))
# Deco BE11000 firmware reports speeds in Kbps; 125 converts Kbps -> Bytes/sec
SPEED_MULTIPLIER = float(os.getenv("SPEED_MULTIPLIER", "125"))

# Router & Internet Metrics
g_internet_online = Gauge("deco_internet_online", "Internet connectivity status (1=online, 0=offline)")
g_cpu_usage = Gauge("deco_cpu_usage", "Router CPU usage ratio (0.0 - 1.0)")
g_memory_usage = Gauge("deco_memory_usage", "Router memory usage ratio (0.0 - 1.0)")
g_total_rx = Gauge("deco_total_rx_bytes_per_second", "Total mesh download speed (bytes/s)")
g_total_tx = Gauge("deco_total_tx_bytes_per_second", "Total mesh upload speed (bytes/s)")
g_clients_total = Gauge("deco_clients_total", "Total connected clients")
g_nodes_total = Gauge("deco_nodes_total", "Total mesh nodes")
g_nodes_online = Gauge("deco_nodes_online", "Online mesh nodes")
g_fw_update = Gauge("deco_firmware_update_available", "Firmware update available (1=yes, 0=no)")

# Node Metrics
g_device_info = Gauge(
    "deco_device_info",
    "Deco mesh node metadata",
    ["name", "mac", "ip", "model", "firmware", "hardware", "master", "connection_type"],
)
g_node_online = Gauge("deco_node_online", "Mesh node online status", ["name", "mac"])
g_node_clients = Gauge("deco_node_clients_total", "Connected clients per node", ["name", "mac"])
g_node_sig_2g = Gauge("deco_node_signal_2g", "Node 2.4GHz signal strength", ["name", "mac"])
g_node_sig_5g = Gauge("deco_node_signal_5g", "Node 5GHz signal strength", ["name", "mac"])

# Client Metrics
g_client_info = Gauge(
    "deco_client_info",
    "Connected client metadata",
    ["name", "mac", "ip", "connection_type", "interface", "online"],
)
g_client_rx = Gauge("deco_client_rx_bytes_per_second", "Client download speed (bytes/s)", ["name", "mac"])
g_client_tx = Gauge("deco_client_tx_bytes_per_second", "Client upload speed (bytes/s)", ["name", "mac"])


def to_ratio(val):
    v = float(val or 0)
    return v / 100.0 if v > 1.0 else v


def poll_deco():
    with DecoClient(DECO_HOST, password=DECO_PASSWORD, username=DECO_USERNAME) as deco:
        # 1. CPU & Memory Performance
        perf = deco.get_performance()
        g_cpu_usage.set(to_ratio(getattr(perf, "cpu_usage", 0)))
        g_memory_usage.set(to_ratio(getattr(perf, "mem_usage", getattr(perf, "memory_usage", 0))))

        # 2. Internet Status
        inet = deco.get_internet_status()
        inet_data = inet if isinstance(inet, dict) else vars(inet)
        ipv4 = inet_data.get("ipv4") or {}
        ipv6 = inet_data.get("ipv6") or {}
        v4_status = str(ipv4.get("inet_status") if isinstance(ipv4, dict) else getattr(ipv4, "inet_status", "")).lower()
        v6_status = str(ipv6.get("inet_status") if isinstance(ipv6, dict) else getattr(ipv6, "inet_status", "")).lower()
        g_internet_online.set(1.0 if (v4_status == "online" or v6_status == "online") else 0.0)

        # 3. Mesh Nodes
        devices = deco.get_device_list()
        g_device_info.clear()
        g_node_online.clear()
        g_node_clients.clear()
        g_node_sig_2g.clear()
        g_node_sig_5g.clear()

        online_nodes = 0
        fw_avail = 0
        for d in devices:
            name = str(getattr(d, "custom_nickname", None) or getattr(d, "nickname", None) or getattr(d, "name", "Deco"))
            mac = str(getattr(d, "mac", ""))
            ip = str(getattr(d, "device_ip", getattr(d, "ip", "")))
            model = str(getattr(d, "device_model", getattr(d, "model", "")))
            fw = str(getattr(d, "software_ver", getattr(d, "firmware_ver", "")))
            hw = str(getattr(d, "hardware_ver", ""))
            role = str(getattr(d, "role", "")).lower()
            is_master = "true" if (role == "master" or getattr(d, "master", False)) else "false"
            conn_type = ",".join(d.connection_type) if isinstance(getattr(d, "connection_type", None), list) else str(getattr(d, "connection_type", ""))
            status_str = str(getattr(d, "inet_status", getattr(d, "status", "online"))).lower()
            is_online = 1.0 if status_str in ("online", "connected", "true", "1") else 0.0
            online_nodes += int(is_online)

            if getattr(d, "need_update", False):
                fw_avail = 1

            g_device_info.labels(name, mac, ip, model, fw, hw, is_master, conn_type).set(1.0)
            g_node_online.labels(name, mac).set(is_online)

            sig = getattr(d, "signal_level", None)
            if sig is not None:
                g_node_sig_2g.labels(name, mac).set(float(getattr(sig, "band2_4", 0) or 0))
                g_node_sig_5g.labels(name, mac).set(float(getattr(sig, "band5", 0) or 0))

        g_nodes_total.set(float(len(devices)))
        g_nodes_online.set(float(online_nodes))
        g_fw_update.set(float(fw_avail))

        # 4. Connected Clients
        clients = deco.get_client_list()
        g_client_info.clear()
        g_client_rx.clear()
        g_client_tx.clear()

        node_counts = {}
        sum_rx = 0.0
        sum_tx = 0.0
        for c in clients:
            cname = str(getattr(c, "name", None) or getattr(c, "mac", "Unknown"))
            cmac = str(getattr(c, "mac", ""))
            cip = str(getattr(c, "ip", ""))
            ctype = str(getattr(c, "connection_type", ""))
            ciface = str(getattr(c, "interface", "main"))
            conline = "true" if getattr(c, "online", True) else "false"

            rx_bps = float(getattr(c, "down_speed", 0) or 0) * SPEED_MULTIPLIER
            tx_bps = float(getattr(c, "up_speed", 0) or 0) * SPEED_MULTIPLIER
            sum_rx += rx_bps
            sum_tx += tx_bps

            g_client_info.labels(cname, cmac, cip, ctype, ciface, conline).set(1.0)
            g_client_rx.labels(cname, cmac).set(rx_bps)
            g_client_tx.labels(cname, cmac).set(tx_bps)

            owner_mac = str(getattr(c, "access_node_mac", getattr(c, "deco_mac", "")))
            if owner_mac:
                node_counts[owner_mac] = node_counts.get(owner_mac, 0) + 1

        for d in devices:
            name = str(getattr(d, "custom_nickname", None) or getattr(d, "nickname", None) or getattr(d, "name", "Deco"))
            mac = str(getattr(d, "mac", ""))
            g_node_clients.labels(name, mac).set(float(node_counts.get(mac, 0)))

        # 5. Client Totals (from get_client_totals with fallback to client sum)
        totals = deco.get_client_totals()
        tot_down_raw = getattr(totals, "down_speed", getattr(totals, "total_down_speed", None))
        tot_up_raw = getattr(totals, "up_speed", getattr(totals, "total_up_speed", None))

        g_total_rx.set(float(tot_down_raw) * SPEED_MULTIPLIER if tot_down_raw is not None else sum_rx)
        g_total_tx.set(float(tot_up_raw) * SPEED_MULTIPLIER if tot_up_raw is not None else sum_tx)
        g_clients_total.set(float(getattr(totals, "total", len(clients)) or len(clients)))


if __name__ == "__main__":
    start_http_server(METRICS_PORT)
    print(f"Deco Prometheus exporter listening on :{METRICS_PORT} (polling {DECO_HOST} every {POLL_INTERVAL}s)")
    while True:
        try:
            poll_deco()
        except Exception as exc:
            print(f"Poll error: {exc}")
        time.sleep(POLL_INTERVAL)
