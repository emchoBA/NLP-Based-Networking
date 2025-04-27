# device_connect.py

#!/usr/bin/env python3
"""
device_connect.py

Listens for admin’s UDP discovery broadcasts, then
establishes a TCP connection back to the admin.
Now also prints any 'policy' commands received.
"""

import socket
import threading
import select
import time

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
DISCOVERY_PORT = 9999
TCP_PORT       = 10000
DISCOVERY_MSG  = b'DISCOVER_PI'

stop_event = threading.Event()

def listen_for_discovery():
    """Waits for the admin’s UDP broadcast and (once) connects back."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', DISCOVERY_PORT))
    print(f"[UDP] Listening on port {DISCOVERY_PORT} for discovery")

    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(1024)
            if data == DISCOVERY_MSG:
                admin_ip = addr[0]
                print(f"[UDP] Discovery from admin at {admin_ip}")
                threading.Thread(
                    target=connect_to_admin,
                    args=(admin_ip,),
                    daemon=True
                ).start()
                break  # only need one discovery
        except Exception as e:
            print(f"[UDP] Listener error: {e}")

    sock.close()

def connect_to_admin(admin_ip: str):
    """Establishes and monitors a TCP connection to the admin."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((admin_ip, TCP_PORT))
        print(f"[TCP] Connected to admin at {admin_ip}:{TCP_PORT}")
        monitor_connection(sock)
    except Exception as e:
        print(f"[TCP] Connection failed: {e}")

def monitor_connection(sock: socket.socket):
    """Prints any data received as 'policy' commands, or detects disconnect."""
    try:
        while not stop_event.is_set():
            rlist, _, _ = select.select([sock], [], [], 1)
            if rlist:
                data = sock.recv(1024)
                if not data:
                    print("[TCP] disconnected by admin")
                    break
                # Decode and print the command
                try:
                    text = data.decode().strip()
                except UnicodeDecodeError:
                    text = repr(data)
                print(f"[POLICY] Received command: {text}")
    except Exception as e:
        print(f"[TCP] Monitor error: {e}")
    finally:
        sock.close()
        print("[TCP] Connection closed")

def main():
    stop_event.clear()
    threading.Thread(target=listen_for_discovery, daemon=True).start()
    print("device_connect running. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
        print("Shutting down device_connect")

if __name__ == "__main__":
    main()
