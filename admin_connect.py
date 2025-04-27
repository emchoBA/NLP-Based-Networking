#!/usr/bin/env python3
"""
admin_connect.py

Discovers Raspberry Pi devices via UDP broadcast requests,
accepts TCP connections from them, and periodically
reports the list of connected device IPs.
"""

import socket
import threading

import select

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
DISCOVERY_PORT     = 9999
TCP_PORT           = 10000
DISCOVERY_MSG      = b'DISCOVER_PI'
BROADCAST_INTERVAL = 5

# -------------------------------------------------------------------
# Control and state
# -------------------------------------------------------------------
stop_event = threading.Event()
connected_devices = set()        # set of IP strings
devices_lock = threading.Lock()


def udp_discovery_sender():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    while not stop_event.is_set():
        try:
            sock.sendto(DISCOVERY_MSG, ('<broadcast>', DISCOVERY_PORT))
            print(f"[UDP] Broadcast discovery to port {DISCOVERY_PORT}")
        except Exception as e:
            print(f"[UDP] Broadcast error: {e}")

        with devices_lock:
            ips = list(connected_devices)
        print(f"[INFO] {len(ips)} device(s) connected: {ips}")

        # wait up to BROADCAST_INTERVAL, but wake early if stopped
        stop_event.wait(BROADCAST_INTERVAL)

    sock.close()
    print("[UDP] Discovery sender stopped")


def handle_client(conn: socket.socket, addr):
    ip = addr[0]
    with devices_lock:
        connected_devices.add(ip)
    print(f"[TCP] New device connected from {ip}")

    try:
        while not stop_event.is_set():
            rlist, _, _ = select.select([conn], [], [], 1)
            if rlist:
                data = conn.recv(1024)
                if not data:
                    print(f"[TCP] Device {ip} disconnected")
                    break
                # (optional) handle data…
    except Exception as e:
        print(f"[TCP] Error with {ip}: {e}")
    finally:
        conn.close()
        with devices_lock:
            connected_devices.discard(ip)
        print(f"[TCP] Handler for {ip} exited")


def tcp_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('', TCP_PORT))
    srv.listen()
    srv.settimeout(1)
    print(f"[TCP] Server listening on port {TCP_PORT}")

    while not stop_event.is_set():
        try:
            conn, addr = srv.accept()
            threading.Thread(
                target=handle_client,
                args=(conn, addr),
                daemon=True
            ).start()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[TCP] Accept error: {e}")

    srv.close()
    print("[TCP] Server stopped")


def main():
    # ensure any previous stop flag is cleared
    stop_event.clear()

    threading.Thread(target=udp_discovery_sender, daemon=True).start()
    threading.Thread(target=tcp_server, daemon=True).start()

    print("admin_connect running. Waiting for stop_event...")
    # block here until stop_event is set
    stop_event.wait()
    print("admin_connect exiting")
