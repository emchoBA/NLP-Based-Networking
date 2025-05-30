import socket
import threading # Only for type hinting if STOP_EVENT is passed as threading.Event
import select
import time
import logging

# Import from sibling modules within the 'device_app' package
from . import command_executor # Use . for explicit relative import

log = logging.getLogger(__name__)

# These would typically come from a config.py or be passed in
DISCOVERY_PORT = 9999
TCP_PORT = 10000 # Admin's TCP listening port
DISCOVERY_MSG = b'DISCOVER_PI'


def monitor_connection(sock: socket.socket, stop_event: threading.Event):
    """
    Monitors the TCP connection for incoming commands, prints them,
    and attempts to execute them using command_executor.
    """
    sock.setblocking(False)
    log.info("[NetHandler TCP] Monitoring connection for commands...")
    try:
        while not stop_event.is_set():
            rlist, _, _ = select.select([sock], [], [], 1.0)
            if not rlist:
                continue

            try:
                data = sock.recv(4096)
                if not data:
                    log.info("[NetHandler TCP] Disconnected by admin (recv returned empty).")
                    break

                command_string = data.decode().strip()
                log.info(f"[NetHandler TCP] Received raw command string: '{command_string}'")

                for single_cmd in command_string.splitlines():
                    single_cmd = single_cmd.strip()
                    if not single_cmd:
                        continue

                    log.info(f"[NetHandler TCP] Processing command: '{single_cmd}'")
                    # Call the executor from the command_executor module
                    success, output_msg = command_executor.execute_firewall_command(single_cmd)

                    if success:
                        log.info(f"[NetHandler EXEC] Successfully applied: '{single_cmd}'. Output: {output_msg if output_msg else 'None'}")
                    else:
                        log.error(f"[NetHandler EXEC] Failed to apply: '{single_cmd}'. Reason: {output_msg}")

            except ConnectionResetError:
                log.warning("[NetHandler TCP] Connection reset by admin.")
                break
            except ConnectionAbortedError:
                log.warning("[NetHandler TCP] Connection aborted by admin.")
                break
            except socket.error as e:
                log.error(f"[NetHandler TCP] Socket error during monitoring: {e}")
                break
            except Exception as e:
                log.exception("[NetHandler TCP] Unexpected error during command processing")
                break
    finally:
        log.info("[NetHandler TCP] Stopped monitoring connection.")


def connect_to_admin(admin_ip: str, admin_tcp_port: int, stop_event: threading.Event):
    """Establishes and monitors a TCP connection to the admin."""
    tcp_sock = None
    try:
        log.info(f"[NetHandler TCP] Attempting to connect to admin at {admin_ip}:{admin_tcp_port}...")
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.settimeout(10.0)
        tcp_sock.connect((admin_ip, admin_tcp_port))
        log.info(f"[NetHandler TCP] Successfully connected to admin at {admin_ip}:{admin_tcp_port}")
        monitor_connection(tcp_sock, stop_event) # Pass the socket and stop_event
    except socket.timeout:
        log.warning(f"[NetHandler TCP] Connection attempt to {admin_ip}:{admin_tcp_port} timed out.")
    except ConnectionRefusedError:
        log.warning(f"[NetHandler TCP] Connection to {admin_ip}:{admin_tcp_port} refused.")
    except Exception as e:
        log.error(f"[NetHandler TCP] TCP connection failed: {e}")
    finally:
        if tcp_sock:
            tcp_sock.close()
        log.info(f"[NetHandler TCP] Connection to {admin_ip} closed or failed to establish.")


def listen_for_discovery(discovery_port: int, discovery_msg: bytes, admin_tcp_port: int, stop_event: threading.Event):
    """Waits for the admin’s UDP broadcast and initiates connection."""
    udp_sock = None
    log.info(f"[NetHandler UDP] Starting discovery listener on port {discovery_port}.")
    try:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            udp_sock.bind(('', discovery_port))
        except OSError as e:
            log.critical(f"[NetHandler UDP] Failed to bind to port {discovery_port}: {e}. Another process might be using it.")
            return # Cannot proceed if bind fails

        log.info(f"[NetHandler UDP] Listening on port {discovery_port} for discovery broadcast.")
        udp_sock.settimeout(2.0)

        while not stop_event.is_set():
            try:
                data, addr = udp_sock.recvfrom(1024)
                if data == discovery_msg:
                    admin_ip = addr[0]
                    log.info(f"[NetHandler UDP] Discovery message received from admin at {admin_ip}")
                    connect_to_admin(admin_ip, admin_tcp_port, stop_event)
                    log.info(f"[NetHandler UDP] Resuming listening on port {discovery_port} after connection attempt.")
            except socket.timeout:
                continue
            except Exception as e:
                log.error(f"[NetHandler UDP] Listener error: {e}")
                time.sleep(5) # Wait before retrying on other errors
    finally:
        if udp_sock:
            udp_sock.close()
        log.info("[NetHandler UDP] Discovery listener stopped.")