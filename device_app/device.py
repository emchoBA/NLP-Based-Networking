#!/usr/bin/env python3
"""
device.py

Main application runner for the device-side agent.
Initializes and manages the network handler for discovery and command reception.
"""
import threading
import time
import logging

# Import from sibling modules within the 'device_app' package
from . import network_handler # Use . for explicit relative import

# --- Global Configuration (kept here since we skipped config.py) ---
# These constants are passed to network_handler functions
APP_DISCOVERY_PORT = 9999
APP_ADMIN_TCP_PORT = 10000 # The port on the admin server the device connects to
APP_DISCOVERY_MSG = b'DISCOVER_PI'

# --- Global Stop Event ---
# This event is used to signal all threads to terminate.
STOP_EVENT = threading.Event()


def main():
    """
    Initializes logging, starts the discovery listener thread,
    and handles graceful shutdown.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    log = logging.getLogger(__name__) # Logger for this main module

    STOP_EVENT.clear()
    log.info("Device agent starting...")

    discovery_thread = threading.Thread(
        target=network_handler.listen_for_discovery,
        args=(APP_DISCOVERY_PORT, APP_DISCOVERY_MSG, APP_ADMIN_TCP_PORT, STOP_EVENT),
        name="DiscoveryThread",
        daemon=True # Daemon threads exit when the main program exits
    )
    discovery_thread.start()

    log.info("Device agent running. Press Ctrl+C to exit.")
    try:
        while not STOP_EVENT.is_set():
            if not discovery_thread.is_alive():
                log.warning("Discovery thread has terminated. Attempting to restart...")
                # Ensure previous thread object is not reused if joinable
                if discovery_thread.is_alive(): # Should not happen if it already terminated
                    discovery_thread.join(timeout=0.1)

                discovery_thread = threading.Thread(
                    target=network_handler.listen_for_discovery,
                    args=(APP_DISCOVERY_PORT, APP_DISCOVERY_MSG, APP_ADMIN_TCP_PORT, STOP_EVENT),
                    name="DiscoveryThread",
                    daemon=True
                )
                discovery_thread.start()
                if not discovery_thread.is_alive():
                    log.error("Failed to restart discovery thread. Exiting loop.")
                    break # Critical failure
            time.sleep(2) # Check every 2 seconds
    except KeyboardInterrupt:
        log.info("\nKeyboardInterrupt received. Shutting down device agent...")
    except Exception as e:
        log.exception("An unexpected error occurred in the main loop.")
    finally:
        log.info("Signaling threads to stop...")
        STOP_EVENT.set()
        if discovery_thread.is_alive():
            log.info("Waiting for discovery thread to stop...")
            discovery_thread.join(timeout=5.0)
            if discovery_thread.is_alive():
                log.warning("Discovery thread did not stop in time.")
        log.info("Device agent shutdown complete.")


if __name__ == "__main__":
    main()