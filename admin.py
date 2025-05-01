# --- START OF FILE admin.py ---

#!/usr/bin/env python3
"""
admin.py

PyQt6 GUI wrapper around:
 - admin_connect (start/stop discovery & server)
 - policy_engine (preview and dispatch NLP rules to Pis)
"""

import sys
import threading
import time
from datetime import datetime
import logging # Import logging first

# --- Logging Setup (Do this EARLY) ---
log_handler = None # Placeholder

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView,
        QHeaderView, QLineEdit, QTextEdit, QLabel, QSplitter, QMessageBox
    )
    from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, QDateTime
    from PyQt6.QtGui import QColor, QFont

    # 1. Create a QObject based handler that emits a signal
    class QtLogHandler(logging.Handler, QObject):
        log_signal = pyqtSignal(str)

        def __init__(self):
            logging.Handler.__init__(self)
            QObject.__init__(self) # Initialize QObject

        def emit(self, record):
            try: # Protect against errors during logging itself
                 msg = self.format(record)
                 # noinspection PyUnresolvedReferences
                 self.log_signal.emit(msg)
            except Exception:
                 self.handleError(record)

    log_handler = QtLogHandler()
    # Optional: Set a specific format for the logs displayed in the GUI
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] %(message)s', datefmt='%H:%M:%S')
    log_handler.setFormatter(formatter)

    # 2. Apply handler ONLY AFTER checking if it exists
    if log_handler:
         # Add handler to the loggers we want to capture
         # Use placeholders for backend modules initially
         logging.getLogger("admin_connect").addHandler(log_handler)
         logging.getLogger("policy_engine").addHandler(log_handler)
         logging.getLogger("service_mapper").addHandler(log_handler) # Add mapper logger
         logging.getLogger("nlp").addHandler(log_handler) # Add nlp logger
         # Set minimum level for logs captured by this handler
         logging.getLogger("admin_connect").setLevel(logging.INFO)
         logging.getLogger("policy_engine").setLevel(logging.INFO)
         logging.getLogger("service_mapper").setLevel(logging.INFO)
         logging.getLogger("nlp").setLevel(logging.INFO) # Set level for nlp

except ImportError:
     print("ERROR: PyQt6 is not installed. Please run 'pip install PyQt6'", file=sys.stderr)

     #THIS PART IS FOR THE SOLE PURPOSE OF IGNORING THE WARNINGS
     QApplication = None
     QMainWindow = None
     QWidget = None
     QVBoxLayout = None
     QHBoxLayout = None
     QPushButton = None
     QTableWidget = None
     QTableWidgetItem = None
     QAbstractItemView = None
     QHeaderView = None
     QLineEdit = None
     QTextEdit = None
     QSplitter = None
     QLabel = None
     QMessageBox = None
     QTimer = None
     QObject = None
     pyqtSignal = None
     Qt = None
     QColor = None
     QFont = None

     sys.exit(1)
except Exception as e:
     print(f"ERROR: Failed to initialize logging or Qt: {e}", file=sys.stderr)
     sys.exit(1)


# --- Import backend modules AFTER logging might be set up ---
try:
    import admin_connect
    import policy_engine # Import the updated policy engine
    import service_mapper # Import service mapper
    import nlp # Import nlp
except ImportError as e:
     print(f"ERROR: Failed to import backend module: {e}", file=sys.stderr)
     print("Make sure admin_connect.py, policy_engine.py, service_mapper.py, nlp.py are in the same directory or Python path.", file=sys.stderr)
     admin_connect = None
     policy_engine = None
     service_mapper = None
     sys.exit(1)

# Redirect stdout/stderr (optional, captures 'print' statements)
class StreamRedirector(QObject):
    write_signal = pyqtSignal(str)

    def __init__(self, stream_name):
        super().__init__()
        self.stream_name = stream_name # 'stdout' or 'stderr'

    def write(self, text):
        if text.strip(): # Avoid sending empty lines
            # noinspection PyUnresolvedReferences
            self.write_signal.emit(f"[{self.stream_name}] {text}")

    def flush(self):
        pass # No-op needed for stream interface

# Keep references to original streams
original_stdout = sys.stdout
original_stderr = sys.stderr

stdout_redirector = StreamRedirector('stdout')
stderr_redirector = StreamRedirector('stderr') # Redirect stderr if desired


# --- Main GUI Class ---
class AdminGUI(QMainWindow):
    # Store generated commands between preview and send
    _previewed_commands: list[tuple[str, str, list[str]]] = []
    _selected_target_ip: str | None = None

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Admin Controller")
        self.setGeometry(100, 100, 800, 600) # Adjusted size

        self.worker_thread = None
        self.devices_status = {} # ip: {'status': 'Connected/Disconnected', 'last_seen': datetime}
        self._is_closing = False # Flag to prevent actions during close

        # --- Central Widget and Layouts ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Top Control Bar
        control_bar_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Server")
        # noinspection PyUnresolvedReferences
        self.start_btn.clicked.connect(self.start_backend)
        self.stop_btn = QPushButton("Stop Server")
        # noinspection PyUnresolvedReferences
        self.stop_btn.clicked.connect(self.stop_backend)
        self.stop_btn.setEnabled(False)
        control_bar_layout.addWidget(self.start_btn)
        control_bar_layout.addWidget(self.stop_btn)
        control_bar_layout.addStretch(1)
        main_layout.addLayout(control_bar_layout)

        # Splitter for Device List and Log
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left Panel: Device List ---
        device_widget = QWidget()
        device_layout = QVBoxLayout(device_widget)
        device_layout.addWidget(QLabel("Connected Devices"))
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(3)
        self.device_table.setHorizontalHeaderLabels(["IP Address", "Status", "Last Seen"])
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # Read-only
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Status column
        # noinspection PyUnresolvedReferences
        self.device_table.itemSelectionChanged.connect(self.update_selected_target_from_table)
        device_layout.addWidget(self.device_table)
        splitter.addWidget(device_widget)

        # --- Right Panel: Log View ---
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.addWidget(QLabel("System Logs"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 9))
        log_layout.addWidget(self.log_view)
        splitter.addWidget(log_widget)

        splitter.setSizes([250, 550]) # Initial size ratio
        main_layout.addWidget(splitter, 1) # Give splitter resizing priority

        # --- Bottom Panel: Policy Control ---
        policy_widget = QWidget()
        policy_layout = QVBoxLayout(policy_widget)

        # Target Info
        self.target_label = QLabel("Selected Target: None")
        policy_layout.addWidget(self.target_label)

        # NL Input
        nl_layout = QHBoxLayout()
        nl_layout.addWidget(QLabel("Policy Command(s):"))
        self.nl_input = QLineEdit()
        self.nl_input.setPlaceholderText("e.g., deny ssh from 192.168.1.100 or on 10.0.0.1 block http from 10.0.0.5")
        # noinspection PyUnresolvedReferences
        self.nl_input.textChanged.connect(self.clear_preview) # Clear preview if text changes
        nl_layout.addWidget(self.nl_input)
        policy_layout.addLayout(nl_layout)

        # Preview Area and Buttons
        preview_layout = QHBoxLayout()
        self.preview_area = QTextEdit()
        self.preview_area.setReadOnly(True)
        self.preview_area.setPlaceholderText("Generated iptables commands will appear here after preview...")
        self.preview_area.setMaximumHeight(100) # Limit height
        preview_layout.addWidget(self.preview_area, 1)

        preview_buttons_layout = QVBoxLayout()
        self.preview_btn = QPushButton("Parse & Preview")
        # noinspection PyUnresolvedReferences
        self.preview_btn.clicked.connect(self.preview_policy)
        self.send_btn = QPushButton("Send Policy")
        # noinspection PyUnresolvedReferences
        self.send_btn.clicked.connect(self.send_policy)
        self.send_btn.setEnabled(False) # Disabled until previewed
        preview_buttons_layout.addWidget(self.preview_btn)
        preview_buttons_layout.addWidget(self.send_btn)
        preview_layout.addLayout(preview_buttons_layout)
        policy_layout.addLayout(preview_layout)

        main_layout.addWidget(policy_widget)

        # --- Status Update Timer ---
        self.status_timer = QTimer(self)
        # noinspection PyUnresolvedReferences
        self.status_timer.timeout.connect(self.update_device_status)
        # Check status every 5 seconds (adjust as needed)
        self.status_timer.setInterval(5000)

        # --- Connect Log Handler Signal ---
        if log_handler: # Check if handler was created
            # noinspection PyUnresolvedReferences
            log_handler.log_signal.connect(self.append_log)
        # noinspection PyUnresolvedReferences
        stdout_redirector.write_signal.connect(self.append_log)
        # noinspection PyUnresolvedReferences
        stderr_redirector.write_signal.connect(self.append_log) # Connect stderr too

        # Redirect stdout/stderr after GUI setup
        sys.stdout = stdout_redirector
        sys.stderr = stderr_redirector # Redirect stderr

        # Initial load of service mapper to catch errors early
        self._init_service_mapper()

    def _init_service_mapper(self):
        """Triggers initial load of service mapper and logs status."""
        self.append_log("[GUI] Initializing service mappings...")
        # Use a common service to trigger load
        _ = service_mapper.get_service_params("ssh")
        if service_mapper._service_mappings is None: # Check internal flag if possible
             self.append_log("[GUI ERROR] Service mapper failed initial load. Check console/logs.")
             QMessageBox.critical(self, "Config Error", "Failed to load services.json. Policy commands may not work correctly.")
        elif not service_mapper._service_mappings: # Empty map after load attempt
             self.append_log("[GUI WARN] Service mappings loaded but are empty. Check services.json.")
             QMessageBox.warning(self, "Config Warning", "Service mapping file loaded but is empty. Check services.json.")
        else:
             self.append_log("[GUI] Service mappings initialized.")


    def append_log(self, message):
        """Safely appends a message to the log view."""
        if self._is_closing: return # Don't log during shutdown
        try:
             # Ensure log messages are appended on the main GUI thread if coming from signals
             self.log_view.append(message.strip())
             # Optional: Auto-scroll to the bottom
             self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
        except Exception as e:
             # Fallback if GUI logging fails during critical moments
             print(f"LOGGING ERROR: {e}\nOriginal message: {message}", file=original_stderr)


    def update_device_status(self):
        """Periodically checks backend status and updates the table."""
        if self._is_closing: return
        if not self.worker_thread or not self.worker_thread.is_alive():
            if any(d['status'] == 'Connected' for d in self.devices_status.values()):
                 # Mark all as disconnected if thread died unexpectedly
                 for ip in list(self.devices_status.keys()):
                     self.devices_status[ip]['status'] = 'Disconnected'
                 self.refresh_device_table()
            return

        now = datetime.now()
        current_connected_ips = set()

        # Safely get connected IPs from admin_connect
        try:
            if admin_connect.devices_lock.acquire(timeout=0.1): # Use timeout
                try:
                    current_connected_ips = admin_connect.connected_devices.copy()
                finally:
                    admin_connect.devices_lock.release()
            else:
                 self.append_log("[GUI WARN] Failed to acquire device lock for status update.")
                 return # Skip update if lock contended
        except Exception as e:
            self.append_log(f"[GUI ERROR] Error getting device list: {e}")
            return

        # Update status for currently connected devices
        changed = False
        for ip in current_connected_ips:
            if ip not in self.devices_status or self.devices_status[ip]['status'] != 'Connected':
                changed = True
            self.devices_status[ip] = {'status': 'Connected', 'last_seen': now}

        # Mark devices no longer in the set as Disconnected
        for ip in list(self.devices_status.keys()): # Iterate over copy
            if ip not in current_connected_ips and self.devices_status[ip]['status'] == 'Connected':
                self.devices_status[ip]['status'] = 'Disconnected'
                changed = True
                # Keep last_seen timestamp for disconnected devices

        if changed: # Only refresh table if data changed
             self.refresh_device_table()

    def refresh_device_table(self):
        """Updates the QTableWidget based on self.devices_status."""
        if self._is_closing: return
        try:
            self.device_table.setSortingEnabled(False) # Disable sorting during update
            # Store current selection
            selected_ip = self._selected_target_ip

            self.device_table.setRowCount(len(self.devices_status))

            row = 0
            new_selection_row = -1
            for ip, data in sorted(self.devices_status.items()): # Sort by IP
                ip_item = QTableWidgetItem(ip)
                status_item = QTableWidgetItem(data['status'])
                last_seen_str = data['last_seen'].strftime('%Y-%m-%d %H:%M:%S')
                last_seen_item = QTableWidgetItem(last_seen_str)

                # Set colors based on status
                if data['status'] == 'Connected':
                    status_item.setForeground(QColor('darkGreen')) # Darker green
                else:
                    status_item.setForeground(QColor('red'))

                self.device_table.setItem(row, 0, ip_item)
                self.device_table.setItem(row, 1, status_item)
                self.device_table.setItem(row, 2, last_seen_item)

                # Check if this row corresponds to the previously selected IP
                if ip == selected_ip:
                    new_selection_row = row

                row += 1

            # Restore selection if the IP is still present
            if new_selection_row != -1:
                 self.device_table.selectRow(new_selection_row)
            elif selected_ip is not None: # Selection disappeared
                 self._selected_target_ip = None
                 self.target_label.setText("Selected Target: None")


            self.device_table.setSortingEnabled(True) # Re-enable sorting
        except Exception as e:
            self.append_log(f"[GUI ERROR] Failed to refresh device table: {e}")


    def update_selected_target_from_table(self):
        """Updates the target IP when a row is selected in the table."""
        if self._is_closing: return
        selected_items = self.device_table.selectedItems()
        if selected_items:
            selected_row = self.device_table.row(selected_items[0])
            ip_item = self.device_table.item(selected_row, 0)
            if ip_item:
                new_ip = ip_item.text()
                if new_ip != self._selected_target_ip:
                     self._selected_target_ip = new_ip
                     self.target_label.setText(f"Selected Target: {self._selected_target_ip}")
                     self.clear_preview() # Clear preview when target changes via table
            else:
                 self._selected_target_ip = None
                 self.target_label.setText("Selected Target: None")
        else:
             # Only clear if selection truly disappears
             if self._selected_target_ip is not None:
                  self._selected_target_ip = None
                  self.target_label.setText("Selected Target: None")
                  self.clear_preview()


    def start_backend(self):
        """Starts the admin_connect backend thread."""
        if self._is_closing: return
        if self.worker_thread and self.worker_thread.is_alive():
            self.append_log("[GUI] Backend is already running.")
            return

        self.append_log("[GUI] Attempting to start backend server and discovery...")
        self.start_btn.setEnabled(False) # Disable immediately

        try:
            # Clear previous stop event
            admin_connect.stop_event.clear()

            # Start backend in a separate thread
            self.worker_thread = threading.Thread(
                target=admin_connect.main,
                name="AdminConnectBackend", # Give thread a name
                daemon=True
            )
            self.worker_thread.start()
            time.sleep(0.2) # Give thread a moment to initialize before checking status

            # Check if thread started successfully (basic check)
            if self.worker_thread.is_alive():
                 self.append_log("[GUI] Backend thread started successfully.")
                 self.stop_btn.setEnabled(True)
                 self.status_timer.start() # Start the status update timer
            else:
                 self.append_log("[GUI ERROR] Backend thread failed to start or exited immediately. Check logs.")
                 self.start_btn.setEnabled(True) # Re-enable start button
                 self.stop_btn.setEnabled(False)
                 QMessageBox.critical(self, "Backend Error", "Failed to start the backend server thread. Check logs for details.")

        except Exception as e:
             self.append_log(f"[GUI CRITICAL] Failed to create/start backend thread: {e}")
             logging.exception("GUI failed to start backend thread") # Log full traceback
             self.start_btn.setEnabled(True)
             self.stop_btn.setEnabled(False)
             QMessageBox.critical(self, "Backend Error", f"An unexpected error occurred while starting the backend:\n{e}")


    def stop_backend(self):
        """Signals the admin_connect backend thread to stop."""
        if self._is_closing: return
        if not self.worker_thread or not self.worker_thread.is_alive():
            self.append_log("[GUI] Backend is not running.")
            if self.start_btn.isEnabled() == False: # Ensure buttons are correct state
                 self.start_btn.setEnabled(True)
                 self.stop_btn.setEnabled(False)
            self.status_timer.stop()
            return

        self.append_log("[GUI] Sending stop signal to backend...")
        self.stop_btn.setEnabled(False) # Disable immediately
        self.status_timer.stop() # Stop status updates

        try:
            admin_connect.stop_event.set() # Signal backend to stop

            # Give the thread some time to stop gracefully
            # Don't block the GUI thread for too long with join()
            # Instead, we can periodically check is_alive() or rely on daemon=True
            # For now, just log the signal sent.
            self.append_log("[GUI] Backend stop signal sent. Thread will exit.")

        except Exception as e:
             self.append_log(f"[GUI ERROR] Error signaling backend thread to stop: {e}")
             logging.exception("GUI failed to signal backend stop")

        finally:
             # Reset state even if signaling failed
             self.worker_thread = None # Clear the thread reference
             self.start_btn.setEnabled(True)
             # Update status one last time after stopping attempt
             self.update_device_status()


    def clear_preview(self):
        """Clears the preview area and disables the send button."""
        if self._is_closing: return
        self._previewed_commands = []
        self.preview_area.clear()
        self.send_btn.setEnabled(False)

    def preview_policy(self):
        """Parses the NL command and shows generated commands in the preview area."""
        if self._is_closing: return
        nl_command = self.nl_input.text().strip()
        if not nl_command:
            QMessageBox.warning(self, "Input Error", "Please enter a policy command.")
            return

        self.append_log(f"[GUI] Preview requested for: '{nl_command}'")
        self.clear_preview() # Clear previous preview first
        self.preview_area.setPlaceholderText("Generating preview...") # Indicate activity
        QApplication.processEvents() # Allow GUI to update

        try:
            # Use the new function from policy_engine
            generated_tuples = policy_engine.parse_and_generate_commands(nl_command)

            if not generated_tuples:
                self.preview_area.setPlaceholderText("No valid commands generated or rule structure not understood.")
                self.preview_area.clear() # Explicitly clear if no commands
                QMessageBox.information(self, "Preview", "Could not generate commands from the input.")
                return

            self._previewed_commands = generated_tuples # Store for sending
            preview_text = ""
            for i, (target_ip, subject_ip, cmd_list) in enumerate(generated_tuples):
                 preview_text += f"--- Rule {i+1} (Subject: {subject_ip}, Target Device: {target_ip}) ---\n"
                 if not cmd_list:
                     preview_text += "  (No specific commands generated for this rule)\n"
                 for cmd in cmd_list:
                     preview_text += f"  {cmd}\n"
                 preview_text += "\n"

            self.preview_area.setPlainText(preview_text.strip())
            self.send_btn.setEnabled(True) # Enable sending only if preview succeeded

        except Exception as e:
            self.append_log(f"[GUI ERROR] Failed during policy preview: {e}")
            logging.exception("Policy preview failed") # Log traceback
            self.preview_area.setPlaceholderText("Error during preview. Check logs.")
            self.preview_area.clear()
            QMessageBox.critical(self, "Preview Error", f"Failed to parse or generate commands:\n{e}")
            self.clear_preview()


    def send_policy(self):
        """Sends the commands stored from the preview step."""
        if self._is_closing: return
        if not self._previewed_commands:
            QMessageBox.warning(self, "Send Error", "No commands previewed to send. Please Preview first.")
            return

        # Double check if backend is running
        if not self.worker_thread or not self.worker_thread.is_alive():
             QMessageBox.critical(self, "Send Error", "Backend server is not running. Cannot send commands.")
             self.clear_preview()
             return

        self.append_log("[GUI] Initiating send of previewed policy commands...")
        self.send_btn.setEnabled(False) # Disable while sending
        QApplication.processEvents()

        commands_sent_count = 0
        errors_occurred = False
        total_expected_commands = sum(len(cl) for _, _, cl in self._previewed_commands)

        for target_ip, _, cmd_list in self._previewed_commands:
            # Check if target device is actually connected (optional but good)
            is_connected = False
            try:
                 if admin_connect.clients_lock.acquire(timeout=0.1):
                     try:
                         is_connected = target_ip in admin_connect.clients
                     finally:
                         admin_connect.clients_lock.release()
                 else:
                      self.append_log(f"[GUI WARN] Failed to acquire client lock for send check to {target_ip}. Assuming disconnected.")
                      is_connected = False

            except Exception as e:
                 self.append_log(f"[GUI ERROR] Error checking connection status for {target_ip}: {e}")
                 is_connected = False # Assume disconnected on error

            if not is_connected:
                 warning_msg = f"Target device {target_ip} is not currently connected. Skipping {len(cmd_list)} command(s) for this target."
                 self.append_log(f"[GUI WARN] {warning_msg}")
                 # Don't show popup for every disconnected device if many rules
                 # QMessageBox.warning(self, "Send Warning", warning_msg)
                 errors_occurred = True # Treat as an error for feedback
                 continue # Skip commands for this disconnected target

            # Send commands for this rule/target
            for cmd in cmd_list:
                self.append_log(f"[GUI] Sending to {target_ip}: {cmd}")
                QApplication.processEvents() # Keep GUI responsive
                try:
                    # Use the existing send_command from admin_connect
                    admin_connect.send_command(target_ip, cmd)
                    commands_sent_count += 1
                    time.sleep(0.05) # Small delay between commands
                except ConnectionError as e: # Catch specific error from send_command
                    self.append_log(f"[GUI ERROR] ConnectionError sending command to {target_ip}: {e}")
                    errors_occurred = True
                    # Maybe break sending to this target?
                    break # Stop sending further commands to this disconnected target
                except Exception as e:
                    self.append_log(f"[GUI ERROR] Unexpected error sending command to {target_ip}: {e}")
                    logging.exception(f"Send command failed to {target_ip}")
                    errors_occurred = True
                    # Decide whether to stop or continue on error

        # Re-enable button after loop finishes
        self.send_btn.setEnabled(True if self._previewed_commands else False)

        # Final status message
        if errors_occurred:
            QMessageBox.warning(self, "Send Complete (with errors)", f"Attempted to send {total_expected_commands} command(s). \nSuccessfully sent: {commands_sent_count}.\nSome errors occurred or targets disconnected. Check logs.")
        else:
            QMessageBox.information(self, "Send Complete", f"Successfully sent {commands_sent_count} command(s).")

        self.clear_preview() # Clear after sending


    def closeEvent(self, event):
        """Ensure backend stops when GUI is closed."""
        if self._is_closing: # Prevent recursion
             event.accept()
             return

        self._is_closing = True # Set closing flag
        self.append_log("[GUI] Close event triggered. Shutting down...")

        # Stop the timer first
        self.status_timer.stop()
        self.append_log("[GUI] Status timer stopped.")

        # Stop the backend thread if running
        if self.worker_thread and self.worker_thread.is_alive():
             self.append_log("[GUI] Signaling backend thread to stop...")
             admin_connect.stop_event.set()
             # Don't wait indefinitely, GUI needs to close
             # self.worker_thread.join(timeout=1.5)
             # if self.worker_thread.is_alive():
             #      self.append_log("[GUI WARN] Backend thread did not exit after 1.5s.")
             # else:
             #      self.append_log("[GUI] Backend thread stopped.")
        else:
             self.append_log("[GUI] Backend thread was not running.")

        # Restore stdout/stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        self.append_log("[GUI] Restored stdout/stderr.") # This will go to original console

        self.append_log("[GUI] Shutdown complete. Accepting close event.")
        print("GUI Shutdown complete.", file=original_stderr) # Final message to console
        event.accept() # Accept the close event


if __name__ == "__main__":
    # Basic console logging setup for issues BEFORE GUI/Qt handler takes over
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s', datefmt='%H:%M:%S')

    app = QApplication(sys.argv)
    main_window = AdminGUI()
    main_window.show()
    sys.exit(app.exec())

# --- END OF FILE admin.py ---