import threading
import time
import logging
from PyQt6.QtWidgets import QMessageBox

# Assuming admin_connect is in the parent directory or Python path
from backend import admin_connect

# For simplicity, assuming it's discoverable.

log = logging.getLogger(__name__)

class BackendManager:
    def __init__(self, ui, app_state, append_log_slot):
        self.ui = ui # Instance of Ui_AdminMainWindow
        self.app_state = app_state # Instance of AppState
        self.append_log = append_log_slot # Method to append to log_view
        self.worker_thread = None

        self.ui.start_btn.clicked.connect(self.start_backend)
        self.ui.stop_btn.clicked.connect(self.stop_backend)

    def start_backend(self):
        if not admin_connect:
            QMessageBox.critical(self.ui.central_widget, "Module Error", "admin_connect not loaded.")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            self.append_log("[GUI] Backend is already running.")
            return

        self.append_log("[GUI] Attempting to start backend...")
        self.ui.start_btn.setEnabled(False)
        try:
            admin_connect.stop_event.clear()
            self.worker_thread = threading.Thread(target=admin_connect.main, name="AdminConnectBackend", daemon=True)
            self.worker_thread.start()
            time.sleep(0.2) # Give thread a moment to start

            if self.worker_thread.is_alive():
                self.append_log("[GUI] Backend thread started successfully.")
                self.ui.stop_btn.setEnabled(True)
                self.app_state.is_backend_running = True
            else:
                self.append_log("[GUI ERROR] Backend thread failed to start. Check logs.")
                self.ui.start_btn.setEnabled(True)
                self.ui.stop_btn.setEnabled(False)
                self.app_state.is_backend_running = False
                QMessageBox.critical(self.ui.central_widget, "Backend Error", "Failed to start backend. Check logs.")
        except Exception as e:
            self.append_log(f"[GUI CRITICAL] Failed to start backend: {e}")
            log.exception("GUI start backend failed")
            self.ui.start_btn.setEnabled(True)
            self.app_state.is_backend_running = False
            QMessageBox.critical(self.ui.central_widget, "Backend Error", f"Error starting backend:\n{e}")

    def stop_backend(self):
        if not admin_connect:
            return
        if not self.worker_thread or not self.worker_thread.is_alive():
            self.append_log("[GUI] Backend not running.")
            if not self.ui.start_btn.isEnabled():
                self.ui.start_btn.setEnabled(True)
            self.ui.stop_btn.setEnabled(False)
            self.app_state.is_backend_running = False
            return

        self.append_log("[GUI] Sending stop signal to backend...")
        self.ui.stop_btn.setEnabled(False)
        try:
            admin_connect.stop_event.set()
            # Wait a bit for the thread to potentially join (optional, but good practice)
            # self.worker_thread.join(timeout=2.0) # If join is desired here.
            # if self.worker_thread.is_alive():
            #     self.append_log("[GUI WARN] Backend thread did not stop quickly.")
            self.append_log("[GUI] Backend stop signal sent.")
        except Exception as e:
            self.append_log(f"[GUI ERROR] Error signaling backend stop: {e}")
            log.exception("GUI stop backend failed")
        finally:
            self.worker_thread = None # Clear the thread reference
            self.ui.start_btn.setEnabled(True)
            self.app_state.is_backend_running = False
            # The device table manager will handle updating device statuses based on app_state.is_backend_running

    def get_worker_thread_status(self):
        return self.worker_thread and self.worker_thread.is_alive()

    def cleanup_on_close(self):
        if self.app_state.is_backend_running and admin_connect:
            self.append_log("[GUI Close] Signaling backend to stop from BackendManager...")
            admin_connect.stop_event.set()
            if self.worker_thread:
                self.worker_thread.join(timeout=2.0) # Attempt to join
                if self.worker_thread.is_alive():
                    self.append_log("[GUI Close WARN] Backend thread still alive after join attempt.")