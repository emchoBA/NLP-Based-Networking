#!/usr/bin/env python3
"""
admin_connect.py

Discovers Raspberry Pi devices via UDP broadcast requests,
accepts TCP connections from them, and periodically
reports the list of connected device IPs.

Also tracks each connection socket so we can push “policy”
commands to specific IPs via send_command().

Modified for increased robustness and logging.
"""

import socket
import threading
import select
import time
import logging # Import logging

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

# --- Get Logger specific to this module ---
# This allows the GUI logger to capture messages from here if configured
log = logging.getLogger(__name__)
# Basic config if run standalone (won't interfere with GUI handler)
if not log.hasHandlers():
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def udp_discovery_sender():
    """Broadcast discovery + print connected IPs on the same interval."""
    sock = None # Initialize sock to None
    log.info("[UDP] Discovery sender thread started.")
    try:
        log.info("[UDP] Creating UDP socket...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        log.info("[UDP] Setting SO_BROADCAST...")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # log.info("[UDP] Setting SO_REUSEADDR...") # Removed for UDP socket
        # sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Removed for UDP socket
        log.info("[UDP] Socket configured.")

        while not stop_event.is_set():
            try:
                # Broadcast discovery message
                sock.sendto(DISCOVERY_MSG, ('<broadcast>', DISCOVERY_PORT))
                log.debug(f"[UDP] Broadcasted discovery to port {DISCOVERY_PORT}") # Changed to debug level

                # Log connected devices (maybe less frequently or at different level?)
                with devices_lock:
                    ips = list(connected_devices)
                log.info(f"[NET] {len(ips)} device(s) connected: {ips}") # Changed prefix

            except socket.error as e:
                log.error(f"[UDP] Socket error during broadcast/send: {e}")
                # Potentially break or pause if socket error persists?
                stop_event.wait(BROADCAST_INTERVAL) # Wait even if error occurs
            except Exception as e:
                log.error(f"[UDP] Unexpected error in broadcast loop: {e}")
                stop_event.wait(BROADCAST_INTERVAL) # Wait even if error occurs
            else:
                # Wait up to BROADCAST_INTERVAL, but wake early if stopped
                stop_event.wait(BROADCAST_INTERVAL)

    except socket.error as e:
        log.error(f"[UDP] Failed to create or configure UDP socket: {e}")
    except Exception as e:
        log.error(f"[UDP] Unexpected error setting up UDP sender: {e}")
    finally:
        if sock:
            log.info("[UDP] Closing UDP socket.")
            sock.close()
        log.info("[UDP] Discovery sender thread stopped.")


def handle_client(conn: socket.socket, addr):
    """
    Each Pi connection runs here: registers IP/socket, monitors, unregisters.
    """
    ip = addr[0]
    log.info(f"[TCP] New connection attempt from {ip}:{addr[1]}")
    registered = False
    try:
        # Register
        with devices_lock:
            connected_devices.add(ip)
        with clients_lock:
            clients[ip] = conn
        registered = True
        log.info(f"[TCP] Device connected and registered: {ip}")

        # Monitor for disconnect or data (ignoring data for now)
        conn.setblocking(False) # Use non-blocking with select
        while not stop_event.is_set():
            # Wait for readability (data or disconnect) or timeout
            rlist, _, _ = select.select([conn], [], [], 1.0) # 1 second timeout
            if not rlist: # Timeout, loop continues checking stop_event
                continue

            # Socket is readable, check for data or close
            try:
                data = conn.recv(1024)
                if not data:
                    log.info(f"[TCP] Device {ip} disconnected (recv returned empty).")
                    break # Exit loop on clean disconnect
                else:
                    log.debug(f"[TCP] Received {len(data)} bytes from {ip} (ignored).")
                    # Handle incoming data if needed in the future
                    pass
            except (ConnectionResetError, ConnectionAbortedError):
                log.warning(f"[TCP] Device {ip} connection reset/aborted.")
                break # Exit loop on forceful disconnect
            except socket.error as e:
                log.error(f"[TCP] Socket error reading from {ip}: {e}")
                break # Exit loop on other socket errors

    except Exception as e:
        log.error(f"[TCP] Unexpected error in handler for {ip}: {e}")
    finally:
        log.debug(f"[TCP] Cleaning up connection for {ip}")
        # Ensure unregistration only if registration happened
        if registered:
            with devices_lock:
                connected_devices.discard(ip)
            with clients_lock:
                clients.pop(ip, None)
            log.info(f"[TCP] Device unregistered: {ip}")
        # Ensure socket is closed
        conn.close()
        log.info(f"[TCP] Handler thread for {ip} stopped.")


def tcp_server():
    """Listens for Pi connections and spawns a handler thread each time."""
    srv = None # Initialize srv to None
    log.info("[TCP] Server thread started.")
    try:
        log.info("[TCP] Creating TCP socket...")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        log.info("[TCP] Setting SO_REUSEADDR...")
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        log.info(f"[TCP] Binding to port {TCP_PORT}...")
        srv.bind(('', TCP_PORT))
        log.info("[TCP] Listening for connections...")
        srv.listen()
        # Use timeout to allow checking stop_event periodically
        srv.settimeout(1.0)
        log.info(f"[TCP] Server listening on port {TCP_PORT}")

        while not stop_event.is_set():
            try:
                # Accept connections
                conn, addr = srv.accept()
                # Start a handler thread for the new client
                threading.Thread(
                    target=handle_client,
                    args=(conn, addr),
                    daemon=True # Ensure threads exit if main program exits
                ).start()
            except socket.timeout:
                # Timeout occurred, loop back to check stop_event
                continue
            except socket.error as e:
                # Handle specific socket errors if needed, e.g., connection abort
                log.error(f"[TCP] Socket error during accept: {e}")
                # Consider a small delay before retrying accept on error
                time.sleep(0.1)
            except Exception as e:
                log.error(f"[TCP] Unexpected error during accept loop: {e}")
                # Consider breaking the loop on unexpected errors?
                time.sleep(0.1)

    except socket.error as e:
        log.error(f"[TCP] Failed to create, bind, or listen on TCP socket: {e}")
    except Exception as e:
        log.error(f"[TCP] Unexpected error setting up TCP server: {e}")
    finally:
        if srv:
            log.info("[TCP] Closing server socket.")
            srv.close()
        log.info("[TCP] Server thread stopped.")


def send_command(ip: str, cmd_str: str):
    """
    Send a command string to the Pi at `ip` via its TCP socket.
    """
    sock = None
    with clients_lock:
        sock = clients.get(ip) # Get the socket safely

    if not sock:
        log.warning(f"[CMD] No active connection found for IP {ip}. Cannot send command.")
        raise ConnectionError(f"No active connection to {ip}") # Raise error for GUI

    try:
        payload = cmd_str.encode('utf-8') + b'\n' # Ensure UTF-8 and newline
        log.info(f"[CMD] Sending to {ip}: {cmd_str}")
        sock.sendall(payload)
        log.debug(f"[CMD] Successfully sent {len(payload)} bytes to {ip}.")
    except socket.error as e:
        log.error(f"[CMD] Socket error sending command to {ip}: {e}")
        # Optionally, trigger removal of the client connection here if send fails?
        # (Requires careful handling to avoid deadlocks if handle_client also removes)
        raise ConnectionError(f"Socket error sending to {ip}: {e}") from e
    except Exception as e:
        log.error(f"[CMD] Unexpected error sending command to {ip}: {e}")
        raise ConnectionError(f"Unexpected error sending to {ip}: {e}") from e


def main():
    """Starts UDP broadcaster and TCP server threads."""
    log.info("--- admin_connect starting ---")
    stop_event.clear() # Ensure stop_event is clear

    log.info("Starting UDP discovery sender thread...")
    udp_thread = threading.Thread(target=udp_discovery_sender, daemon=True)
    udp_thread.start()

    log.info("Starting TCP server thread...")
    tcp_thread = threading.Thread(target=tcp_server, daemon=True)
    tcp_thread.start()

    log.info("admin_connect backend threads started. Waiting for stop signal...")
    # Keep main thread alive waiting for stop_event
    try:
        # Instead of just waiting, maybe periodically check thread health?
        while not stop_event.is_set():
            # Check if threads are alive (optional)
            if not udp_thread.is_alive():
                 log.warning("UDP discovery thread unexpectedly terminated.")
                 # Decide if we should restart it or stop everything?
                 # break # Or handle restart
            if not tcp_thread.is_alive():
                 log.warning("TCP server thread unexpectedly terminated.")
                 # break # Or handle restart
            time.sleep(1) # Check stop event every second
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received, signalling threads to stop.")
        stop_event.set()

    # Wait briefly for threads to potentially finish cleanup after stop_event is set
    log.info("Waiting for threads to stop...")
    udp_thread.join(timeout=2.0)
    tcp_thread.join(timeout=2.0)
    log.info(f"UDP thread alive: {udp_thread.is_alive()}")
    log.info(f"TCP thread alive: {tcp_thread.is_alive()}")

    log.info("--- admin_connect finished ---")

if __name__ == "__main__":
    main() # Run the main function if script is executed directly