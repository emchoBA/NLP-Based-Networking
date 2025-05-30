#!/usr/bin/env python3
import sys
import logging

# --- PyQt6 Imports ---
try:
    from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox
    from PyQt6.QtCore import QTimer, Qt
    # QtGui elements like QColor, QFont, QAction are used by managers/ui_setup
except ImportError:
    print("ERROR: PyQt6 is not installed. Please run 'pip install PyQt6'", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"ERROR: Failed to initialize Qt: {e}", file=sys.stderr)
    sys.exit(1)

# --- Local Module Imports ---
# Assuming the script is run from the 'admin_app' directory, or 'admin_app' is in PYTHONPATH
from admin_app.gui_setup.main_window_ui import Ui_AdminMainWindow
# from gui_setup.dialogs import AliasDialog # Dialog is used by DeviceTableManager

from admin_app.gui_managers.device_table_manager import DeviceTableManager
from admin_app.gui_managers.policy_manager import PolicyManager
from admin_app.gui_managers.backend_manager import BackendManager

from admin_app.app_logic.app_state import AppState
from admin_app.utils.gui_logging import setup_gui_logging  # Import specific items

# --- Backend Module Imports ---
try:
    from backend import admin_connect, policy_engine, service_mapper, alias_manager, nlp
except ImportError as e:
    print(f"ERROR: Failed to import backend module: {e}", file=sys.stderr)
    # In a real app, might show a QMessageBox if QApplication is available
    sys.exit(1)


# Store original stdout/stderr for restoration
original_stdout = sys.stdout
original_stderr = sys.stderr


class AdminGUI(QMainWindow):
    def __init__(self):
        super().__init__()

        if not all([admin_connect, policy_engine, service_mapper, nlp, alias_manager]):
            QMessageBox.critical(None, "Import Error", "One or more backend modules failed to load. Cannot start GUI.")
            sys.exit("Backend module import failed")

        self._is_closing = False

        # 1. Setup UI Structure
        self.ui = Ui_AdminMainWindow()
        self.ui.setup_ui(self) # Pass self (the QMainWindow) to the UI setup

        # 2. Initialize Application State
        self.app_state = AppState()

        # 3. Setup Logging (needs log_view from ui)
        # The setup_gui_logging function now also redirects stdout/stderr
        self.stdout_redirector, self.stderr_redirector, self.qt_log_handler = \
            setup_gui_logging(self.append_log_message)

        self.append_log_message("[GUI] Admin Controller starting...") # Initial log

        # 4. Initialize Managers (pass ui, app_state, and necessary callbacks/modules)
        self.backend_manager = BackendManager(self.ui, self.app_state, self.append_log_message)
        self.device_table_manager = DeviceTableManager(self.ui, self.app_state, self.append_log_message, self) # self for parent window
        self.policy_manager = PolicyManager(self.ui, self.app_state, self.append_log_message, self) # self for parent window


        # 5. Initialize Status Timer
        self.status_timer = QTimer(self)
        # noinspection PyUnresolvedReferences
        self.status_timer.timeout.connect(self.device_table_manager.update_device_status)
        self.status_timer.setInterval(5000) # 5 seconds
        # Start timer only if backend starts successfully (handled by backend_manager, or here)
        # For now, let backend_manager control this if needed, or we can start it after successful backend start.
        # Let's start it if backend is running (which is initially false).
        # It will be more robust if the timer start/stop is tied to backend_manager's success/failure.
        # Let's assume for now the device_table_manager.update_device_status will check app_state.is_backend_running.
        self.status_timer.start() # Start it, it will check backend status internally.


        # 6. Initialize Service Mapper (early check)
        self._init_service_mapper()

        self.append_log_message("[GUI] Initialization complete.")


    def _init_service_mapper(self):
        if not service_mapper: return
        self.append_log_message("[GUI] Initializing service mappings...")
        try:
            # Call a function that might log success/failure internally
            _ = service_mapper.get_service_params("ssh") # Example call
            # The service_mapper itself logs success/failure.
            self.append_log_message("[GUI] Service mappings initialization attempt complete (check logs for details).")
        except Exception as e:
            self.append_log_message(f"[GUI CRITICAL] Failed during service mapper init call: {e}")
            logging.exception("Service mapper init failed in GUI") # Log full traceback
            QMessageBox.critical(self, "Config Error", f"Failed to initialize service mapper:\n{e}")


    def append_log_message(self, message: str):
        if self._is_closing or not hasattr(self.ui, 'log_view'): # Check if log_view exists
            return
        try:
            self.ui.log_view.append(message.strip())
            self.ui.log_view.verticalScrollBar().setValue(self.ui.log_view.verticalScrollBar().maximum())
        except RuntimeError: # Window might be closing
            pass
        except Exception as e:
            # Use original stderr if logging fails during critical shutdown
            print(f"LOGGING ERROR: {e}\nOriginal message: {message}", file=original_stderr)


    def closeEvent(self, event):
        if self._is_closing:
            if event: event.accept()
            return

        self._is_closing = True
        print("GUI Close event. Shutting down...", file=original_stderr) # Use original for critical logs
        self.append_log_message("[GUI] Close event. Shutting down...")

        self.status_timer.stop()
        self.append_log_message("[GUI] Status timer stopped.")

        # Signal backend to stop via its manager
        if self.backend_manager:
            self.backend_manager.cleanup_on_close() # Manager handles thread join

        # Restore stdout/stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        print("[GUI] Restored stdout/stderr.", file=original_stderr)
        print("GUI Shutdown complete.", file=original_stderr)

        if event:
            event.accept()


if __name__ == "__main__":
    # Basic logging setup for the main application itself, if not captured by Qt handler
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s',
                        datefmt='%H:%M:%S')

    if not QApplication.instance():
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()

    if not all([admin_connect, policy_engine, service_mapper, nlp, alias_manager]):
        # This check is also in AdminGUI.__init__, but good for early exit if modules are missing
        # before even trying to create the window.
        logging.critical("Essential backend modules failed to load. Exiting application.")
        if 'QMessageBox' in globals(): # Check if QMessageBox was imported
             QMessageBox.critical(None, "Fatal Import Error", "Core backend modules failed to load. The application cannot start.")
        sys.exit(1)

    main_window = AdminGUI()
    main_window.show()
    sys.exit(app.exec())