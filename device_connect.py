#!/usr/bin/env python3
"""
device_connect.py

Listens for admin’s UDP discovery broadcasts, then
establishes and monitors a TCP connection back to the admin.
"""

import socket
import threading
import select
import time

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
DISCOVERY_PORT = 9999            # UDP port to listen for discovery
TCP_PORT       = 10000           # TCP port to connect back to admin
DISCOVERY_MSG  = b'DISCOVER_PI'  # Must match admin’s broadcast payload

# Globals for connection state
connected = False
conn_lock = threading.Lock()
tcp_sock   = None


def listen_for_discovery():
    """
    Waits for UDP discovery packets from admin.
    On receipt, spawns a thread to connect via TCP (once).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', DISCOVERY_PORT))
    print(f"[UDP] Listening on port {DISCOVERY_PORT} for discovery")

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            if data == DISCOVERY_MSG:
                admin_ip = addr[0]
                with conn_lock:
                    if not connected:
                        print(f"[UDP] Discovery from admin at {admin_ip}")
                        threading.Thread(
                            target=connect_to_admin,
                            args=(admin_ip,),
                            daemon=True
                        ).start()
        except Exception as e:
            print(f"[UDP] Listener error: {e}")


def connect_to_admin(admin_ip: str):
    """
    Attempts to establish a TCP connection to the admin.
    If successful, starts monitoring that socket.
    """
    global connected, tcp_sock
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((admin_ip, TCP_PORT))
        with conn_lock:
            tcp_sock = sock
            connected = True
        print(f"[TCP] Connected to admin at {admin_ip}:{TCP_PORT}")
        monitor_connection(sock)
    except Exception as e:
        print(f"[TCP] Connection to {admin_ip}:{TCP_PORT} failed: {e}")


def monitor_connection(sock: socket.socket):
    """
    Monitors the TCP socket until it’s closed by the admin or network error.
    Prints “disconnected” when it drops.
    """
    global connected
    try:
        while True:
            rlist, _, _ = select.select([sock], [], [], 1)
            if rlist:
                data = sock.recv(1024)
                if not data:
                    print("[TCP] disconnected")
                    break
                # (optional) process commands from admin here
    except Exception as e:
        print(f"[TCP] Monitor error: {e}")
    finally:
        sock.close()
        with conn_lock:
            connected = False
        print("[TCP] Connection closed, awaiting next discovery")


def main():
    # Start UDP listener thread
    threading.Thread(target=listen_for_discovery, daemon=True).start()

    print("Device discovery client running. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Main] Shutting down.")


if __name__ == '__main__':
    main()
