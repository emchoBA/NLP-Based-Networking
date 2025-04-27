# admin_connect.py

#!/usr/bin/env python3
"""
admin_connect.py

Discovers Raspberry Pi devices via UDP broadcast requests,
accepts TCP connections from them, and periodically
reports the list of connected device IPs.

Also tracks each connection socket so we can push “policy”
commands to specific IPs via send_command().
"""

import socket
import threading
import select
import time

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
DISCOVERY_PORT     = 9999
TCP_PORT           = 10000
DISCOVERY_MSG      = b'DISCOVER_PI'
BROADCAST_INTERVAL = 5  # seconds

# -------------------------------------------------------------------
# State & Locks
# -------------------------------------------------------------------
connected_devices = set()        # set of IP strings
clients           = {}           # ip_str -> socket
devices_lock      = threading.Lock()
clients_lock      = threading.Lock()
stop_event        = threading.Event()


def udp_discovery_sender():
    """Broadcast discovery + print connected IPs on the same interval."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    while not stop_event.is_set():
        try:
            sock.sendto(DISCOVERY_MSG, ('<broadcast>', DISCOVERY_PORT))
            print(f"[UDP] Broadcasted discovery to port {DISCOVERY_PORT}")
        except Exception as e:
            print(f"[UDP] Broadcast error: {e}")

        # Print which IPs are connected right now
        with devices_lock:
            ips = list(connected_devices)
        print(f"[INFO] {len(ips)} device(s) connected: {ips}")

        # wait up to BROADCAST_INTERVAL, but wake early if stopped
        stop_event.wait(BROADCAST_INTERVAL)

    sock.close()
    print("[UDP] Discovery sender stopped")


def handle_client(conn: socket.socket, addr):
    """
    Each Pi connection runs here:
     - registers the IP/socket
     - monitors for disconnect
     - unregisters on exit
    """
    ip = addr[0]
    # Register
    with devices_lock:
        connected_devices.add(ip)
    with clients_lock:
        clients[ip] = conn
    print(f"[TCP] New device connected from {ip}")

    try:
        # monitor for clean close
        while not stop_event.is_set():
            rlist, _, _ = select.select([conn], [], [], 1)
            if rlist:
                data = conn.recv(1024)
                if not data:
                    print(f"[TCP] Device {ip} disconnected")
                    break
                # ignoring incoming data for now…
    except Exception as e:
        print(f"[TCP] Error with {ip}: {e}")
    finally:
        conn.close()
        # Unregister
        with devices_lock:
            connected_devices.discard(ip)
        with clients_lock:
            clients.pop(ip, None)
        print(f"[TCP] Handler for {ip} exited")


def tcp_server():
    """Listens for Pi connections and spawns a handler thread each time."""
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


def send_command(ip: str, cmd_str: str):
    """
    Send a command string to the Pi at `ip` via its TCP socket.
    """
    with clients_lock:
        sock = clients.get(ip)
    if not sock:
        print(f"[ADMIN] No active connection to {ip}")
        return

    try:
        payload = cmd_str.encode() + b'\n'
        sock.sendall(payload)
        print(f"[ADMIN] Sent to {ip}: {cmd_str}")
    except Exception as e:
        print(f"[ADMIN] Error sending to {ip}: {e}")


def main():
    """Starts UDP broadcaster and TCP server threads."""
    stop_event.clear()
    threading.Thread(target=udp_discovery_sender, daemon=True).start()
    threading.Thread(target=tcp_server, daemon=True).start()
    print("admin_connect running. Waiting for stop_event...")
    stop_event.wait()
    print("admin_connect exiting")
