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
        QHeaderView, QLineEdit, QTextEdit, QLabel, QSplitter, QMessageBox,
        QMenu, QDialog, QDialogButtonBox, QFormLayout # Added QMenu, QDialog etc.
    )
    from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, QDateTime
    from PyQt6.QtGui import QColor, QFont, QAction # Added QAction

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
         logging.getLogger("admin_connect").addHandler(log_handler)
         logging.getLogger("policy_engine").addHandler(log_handler)
         logging.getLogger("service_mapper").addHandler(log_handler)
         logging.getLogger("nlp").addHandler(log_handler)
         logging.getLogger("alias_manager").addHandler(log_handler) # Add alias_manager logger
         # Set minimum level for logs captured by this handler
         logging.getLogger("admin_connect").setLevel(logging.INFO)
         logging.getLogger("policy_engine").setLevel(logging.INFO)
         logging.getLogger("service_mapper").setLevel(logging.INFO)
         logging.getLogger("nlp").setLevel(logging.INFO)
         logging.getLogger("alias_manager").setLevel(logging.INFO)


except ImportError:
     print("ERROR: PyQt6 is not installed. Please run 'pip install PyQt6'", file=sys.stderr)

     #THIS PART IS FOR THE SOLE PURPOSE OF IGNORING THE WARNINGS IN IDE
     QApplication=None; QMainWindow=None; QWidget=None; QVBoxLayout=None; QHBoxLayout=None;
     QPushButton=None; QTableWidget=None; QTableWidgetItem=None; QAbstractItemView=None;
     QHeaderView=None; QLineEdit=None; QTextEdit=None; QLabel=None; QSplitter=None;
     QMessageBox=None; QMenu=None; QDialog=None; QDialogButtonBox=None; QFormLayout=None;
     QTimer=None; QObject=None; pyqtSignal=object; Qt=None; QColor=None; QFont=None; QAction=None;
     sys.exit(1)
except Exception as e:
     print(f"ERROR: Failed to initialize logging or Qt: {e}", file=sys.stderr)
     sys.exit(1)


# --- Import backend modules AFTER logging might be set up ---
try:
    import admin_connect
    import policy_engine
    import service_mapper
    import nlp
    import alias_manager # Import the new alias manager
except ImportError as e:
     print(f"ERROR: Failed to import backend module: {e}", file=sys.stderr)
     print("Ensure all .py files are in the same directory or Python path.", file=sys.stderr)
     admin_connect = None; policy_engine = None; service_mapper = None; nlp = None; alias_manager = None;
     # sys.exit(1) # Keep commented to allow GUI to show error if possible

# Redirect stdout/stderr
class StreamRedirector(QObject):
    write_signal = pyqtSignal(str)
    def __init__(self, stream_name):
        super().__init__()
        self.stream_name = stream_name
    def write(self, text):
        if text.strip():
            # noinspection PyUnresolvedReferences
            self.write_signal.emit(f"[{self.stream_name}] {text.strip()}")
    def flush(self): pass

original_stdout = sys.stdout
original_stderr = sys.stderr
stdout_redirector = StreamRedirector('stdout')
stderr_redirector = StreamRedirector('stderr')


# --- Alias Dialog ---
class AliasDialog(QDialog):
    def __init__(self, ip_address, current_alias="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Set Alias for {ip_address}")
        self.ip_address = ip_address

        layout = QFormLayout(self)
        self.alias_input = QLineEdit(current_alias)
        self.alias_input.setPlaceholderText("Enter alias name (e.g., Gateway)")
        layout.addRow("Alias Name:", self.alias_input)

        # Standard buttons with OK/Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_alias(self) -> str:
        """Returns the entered alias, stripped of whitespace."""
        return self.alias_input.text().strip()


# --- Main GUI Class ---
class AdminGUI(QMainWindow):
    _previewed_commands: list[tuple[str, str | None, str | None, list[str]]] = []
    _selected_target_ip_display: str | None = None # What's shown in the label (can be alias)
    _selected_target_actual_ip: str | None = None # The actual IP for logic

    def __init__(self):
        if not all([admin_connect, policy_engine, service_mapper, nlp, alias_manager]):
            if QApplication: # Only if Qt loaded enough to show a box
                QMessageBox.critical(None, "Import Error", "One or more backend modules failed to load. Cannot start GUI.")
            else: # Fallback to console if Qt itself failed early
                print("FATAL: Backend modules failed to load. Exiting.", file=original_stderr)
            sys.exit("Backend module import failed")

        super().__init__()
        self.setWindowTitle("Admin Controller")
        self.setGeometry(100, 100, 850, 650) # Slightly wider for alias column

        self.worker_thread = None
        self.devices_status = {}
        self._is_closing = False

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Top Control Bar
        control_bar_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Server")
        self.start_btn.clicked.connect(self.start_backend)
        self.stop_btn = QPushButton("Stop Server")
        self.stop_btn.clicked.connect(self.stop_backend)
        self.stop_btn.setEnabled(False)
        control_bar_layout.addWidget(self.start_btn)
        control_bar_layout.addWidget(self.stop_btn)
        control_bar_layout.addStretch(1)
        main_layout.addLayout(control_bar_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        device_widget = QWidget()
        device_layout = QVBoxLayout(device_widget)
        device_layout.addWidget(QLabel("Connected Devices"))
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(4) # IP, Alias, Status, Last Seen
        self.device_table.setHorizontalHeaderLabels(["IP Address", "Alias", "Status", "Last Seen"])
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) # IP
        self.device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch) # Alias
        self.device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Status
        self.device_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch) # Last Seen

        self.device_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self.show_device_context_menu)
        self.device_table.itemSelectionChanged.connect(self.update_selected_target_from_table)
        device_layout.addWidget(self.device_table)
        splitter.addWidget(device_widget)

        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.addWidget(QLabel("System Logs"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 9))
        log_layout.addWidget(self.log_view)
        splitter.addWidget(log_widget)
        splitter.setSizes([380, 470]) # Adjusted for new column
        main_layout.addWidget(splitter, 1)

        policy_widget = QWidget()
        policy_layout = QVBoxLayout(policy_widget)
        self.target_label = QLabel("Selected Target: None")
        policy_layout.addWidget(self.target_label)
        nl_layout = QHBoxLayout()
        nl_layout.addWidget(QLabel("Policy Command(s):"))
        self.nl_input = QLineEdit()
        self.nl_input.setPlaceholderText("e.g., on MyDevice deny ssh from 1.2.3.4")
        self.nl_input.textChanged.connect(self.clear_preview)
        nl_layout.addWidget(self.nl_input)
        policy_layout.addLayout(nl_layout)
        preview_layout = QHBoxLayout()
        self.preview_area = QTextEdit()
        self.preview_area.setReadOnly(True)
        self.preview_area.setPlaceholderText("Generated iptables commands will appear here after preview...")
        self.preview_area.setMaximumHeight(100)
        preview_layout.addWidget(self.preview_area, 1)
        preview_buttons_layout = QVBoxLayout()
        self.preview_btn = QPushButton("Parse & Preview")
        self.preview_btn.clicked.connect(self.preview_policy)
        self.send_btn = QPushButton("Send Policy")
        self.send_btn.clicked.connect(self.send_policy)
        self.send_btn.setEnabled(False)
        preview_buttons_layout.addWidget(self.preview_btn)
        preview_buttons_layout.addWidget(self.send_btn)
        preview_layout.addLayout(preview_buttons_layout)
        policy_layout.addLayout(preview_layout)
        main_layout.addWidget(policy_widget)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_device_status)
        self.status_timer.setInterval(5000)

        if log_handler:
            log_handler.log_signal.connect(self.append_log)
        stdout_redirector.write_signal.connect(self.append_log)
        stderr_redirector.write_signal.connect(self.append_log)

        sys.stdout = stdout_redirector
        sys.stderr = stderr_redirector

        self._init_service_mapper()

    def _init_service_mapper(self):
        if not service_mapper: return
        self.append_log("[GUI] Initializing service mappings...")
        try:
            _ = service_mapper.get_service_params("ssh")
            # The service_mapper itself logs success/failure, check GUI log
            self.append_log("[GUI] Service mappings initialization attempt complete.")
        except Exception as e:
            self.append_log(f"[GUI CRITICAL] Failed during service mapper init call: {e}")
            logging.exception("Service mapper init failed in GUI")
            QMessageBox.critical(self, "Config Error", f"Failed to initialize service mapper:\n{e}")

    def append_log(self, message):
        if self._is_closing: return
        try:
             self.log_view.append(message.strip())
             self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
        except Exception as e:
             print(f"LOGGING ERROR: {e}\nOriginal message: {message}", file=original_stderr)

    def show_device_context_menu(self, position):
        if not alias_manager: return
        selected_items = self.device_table.selectedItems()
        if not selected_items: return

        selected_row = self.device_table.row(selected_items[0])
        ip_item = self.device_table.item(selected_row, 0)
        if not ip_item: return
        ip_address = ip_item.text()

        menu = QMenu()
        alias_action = QAction("Assign/Edit Alias...", self)
        alias_action.triggered.connect(lambda: self.edit_alias_for_ip(ip_address))
        menu.addAction(alias_action)

        remove_alias_action = QAction("Remove Alias", self)
        remove_alias_action.triggered.connect(lambda: self.remove_alias_for_ip_action(ip_address))
        current_alias = alias_manager.get_alias_for_ip(ip_address)
        remove_alias_action.setEnabled(bool(current_alias))
        menu.addAction(remove_alias_action)

        menu.exec(self.device_table.viewport().mapToGlobal(position))

    def edit_alias_for_ip(self, ip_address):
        if not alias_manager: return
        current_alias = alias_manager.get_alias_for_ip(ip_address) or ""
        dialog = AliasDialog(ip_address, current_alias, self)
        if dialog.exec():
            new_alias = dialog.get_alias()
            if new_alias:
                if alias_manager.add_alias(ip_address, new_alias):
                    self.append_log(f"[GUI] Alias '{new_alias}' set for {ip_address}")
                    self.refresh_device_table()
                else:
                    QMessageBox.warning(self, "Alias Error", "Failed to set alias. Check logs.")
            elif current_alias: # User cleared the alias by submitting empty
                 if alias_manager.remove_alias_for_ip(ip_address):
                     self.append_log(f"[GUI] Alias removed for {ip_address}")
                     self.refresh_device_table()
                 else:
                      QMessageBox.warning(self, "Alias Error", "Failed to remove alias. Check logs.")

    def remove_alias_for_ip_action(self, ip_address):
        if not alias_manager: return
        if alias_manager.remove_alias_for_ip(ip_address):
            self.append_log(f"[GUI] Alias removed for {ip_address}")
            self.refresh_device_table()
        else: # Should not happen if remove_alias_action was enabled
            QMessageBox.information(self, "Alias Info", f"No alias was set for {ip_address} or failed to remove.")


    def update_device_status(self):
        if self._is_closing or not admin_connect or not hasattr(admin_connect, 'devices_lock'): return
        if not self.worker_thread or not self.worker_thread.is_alive():
            if any(d['status'] == 'Connected' for d in self.devices_status.values()):
                 for ip in list(self.devices_status.keys()):
                     self.devices_status[ip]['status'] = 'Disconnected'
                 self.refresh_device_table()
            return
        now = datetime.now()
        current_connected_ips = set()
        try:
            if admin_connect.devices_lock.acquire(timeout=0.1):
                try:
                    if hasattr(admin_connect, 'connected_devices'):
                         current_connected_ips = admin_connect.connected_devices.copy()
                finally: admin_connect.devices_lock.release()
            else:
                 self.append_log("[GUI WARN] Failed to acquire device lock for status update.")
                 return
        except Exception as e:
            self.append_log(f"[GUI ERROR] Error getting device list: {e}")
            return

        changed = False
        for ip in current_connected_ips:
            if ip not in self.devices_status or self.devices_status[ip]['status'] != 'Connected': changed = True
            self.devices_status[ip] = {'status': 'Connected', 'last_seen': now}
        for ip in list(self.devices_status.keys()):
            if ip not in current_connected_ips and self.devices_status[ip]['status'] == 'Connected':
                self.devices_status[ip]['status'] = 'Disconnected'; changed = True
        if changed: self.refresh_device_table()

    def refresh_device_table(self):
        if self._is_closing or not alias_manager: return
        try:
            self.device_table.setSortingEnabled(False)
            current_selection_text = self._selected_target_ip_display
            selected_row_to_restore = -1

            self.device_table.setRowCount(len(self.devices_status))
            row_idx = 0
            for ip, data in sorted(self.devices_status.items()):
                ip_item = QTableWidgetItem(ip)
                alias_name = alias_manager.get_alias_for_ip(ip)
                alias_item = QTableWidgetItem(alias_name if alias_name else "")
                status_item = QTableWidgetItem(data['status'])
                last_seen_str = data['last_seen'].strftime('%Y-%m-%d %H:%M:%S')
                last_seen_item = QTableWidgetItem(last_seen_str)

                status_item.setForeground(QColor('darkGreen') if data['status'] == 'Connected' else QColor('red'))

                self.device_table.setItem(row_idx, 0, ip_item)
                self.device_table.setItem(row_idx, 1, alias_item)
                self.device_table.setItem(row_idx, 2, status_item)
                self.device_table.setItem(row_idx, 3, last_seen_item)

                # Try to match selection (IP or alias)
                display_text_for_row = alias_name if alias_name else ip
                if display_text_for_row == current_selection_text:
                    selected_row_to_restore = row_idx
                row_idx += 1

            if selected_row_to_restore != -1:
                self.device_table.blockSignals(True)
                self.device_table.selectRow(selected_row_to_restore)
                self.device_table.blockSignals(False)
            elif current_selection_text is not None: # If previous selection is gone
                self._selected_target_ip_display = None
                self._selected_target_actual_ip = None
                self.target_label.setText("Selected Target: None")
                # self.clear_preview() # Optional: clear preview if selection is lost

            self.device_table.setSortingEnabled(True)
        except Exception as e:
            self.append_log(f"[GUI ERROR] Failed to refresh device table: {e}")
            logging.exception("Device table refresh error")

    def update_selected_target_from_table(self):
        if self._is_closing: return
        selected_items = self.device_table.selectedItems()
        if selected_items:
            selected_row = self.device_table.row(selected_items[0])
            ip_item = self.device_table.item(selected_row, 0)
            alias_item = self.device_table.item(selected_row, 1)

            if ip_item:
                actual_ip = ip_item.text()
                display_name = alias_item.text() if alias_item and alias_item.text() else actual_ip

                if display_name != self._selected_target_ip_display:
                     self._selected_target_ip_display = display_name
                     self._selected_target_actual_ip = actual_ip # Store actual IP
                     self.target_label.setText(f"Selected Target: {display_name} ({actual_ip})")
                     self.clear_preview()
            else: # Should not happen
                 if self._selected_target_ip_display is not None:
                      self._selected_target_ip_display = None; self._selected_target_actual_ip = None
                      self.target_label.setText("Selected Target: None"); self.clear_preview()
        else: # Selection cleared
             if self._selected_target_ip_display is not None:
                  self._selected_target_ip_display = None; self._selected_target_actual_ip = None
                  self.target_label.setText("Selected Target: None"); self.clear_preview()

    def start_backend(self):
        if not admin_connect: QMessageBox.critical(self, "Module Error", "admin_connect not loaded."); return
        if self._is_closing: return
        if self.worker_thread and self.worker_thread.is_alive():
            self.append_log("[GUI] Backend is already running."); return
        self.append_log("[GUI] Attempting to start backend...")
        self.start_btn.setEnabled(False)
        try:
            admin_connect.stop_event.clear()
            self.worker_thread = threading.Thread(target=admin_connect.main, name="AdminConnectBackend", daemon=True)
            self.worker_thread.start()
            time.sleep(0.2)
            if self.worker_thread.is_alive():
                 self.append_log("[GUI] Backend thread started successfully.")
                 self.stop_btn.setEnabled(True); self.status_timer.start()
            else:
                 self.append_log("[GUI ERROR] Backend thread failed to start. Check logs.")
                 self.start_btn.setEnabled(True); self.stop_btn.setEnabled(False)
                 QMessageBox.critical(self, "Backend Error", "Failed to start backend. Check logs.")
        except Exception as e:
             self.append_log(f"[GUI CRITICAL] Failed to start backend: {e}")
             logging.exception("GUI start backend failed"); self.start_btn.setEnabled(True)
             QMessageBox.critical(self, "Backend Error", f"Error starting backend:\n{e}")

    def stop_backend(self):
        if not admin_connect: return
        if self._is_closing: return
        if not self.worker_thread or not self.worker_thread.is_alive():
            self.append_log("[GUI] Backend not running.")
            if not self.start_btn.isEnabled(): self.start_btn.setEnabled(True); self.stop_btn.setEnabled(False)
            self.status_timer.stop(); return
        self.append_log("[GUI] Sending stop signal to backend...")
        self.stop_btn.setEnabled(False); self.status_timer.stop()
        try:
            admin_connect.stop_event.set()
            self.append_log("[GUI] Backend stop signal sent.")
        except Exception as e:
             self.append_log(f"[GUI ERROR] Error signaling backend stop: {e}")
             logging.exception("GUI stop backend failed")
        finally:
             self.worker_thread = None; self.start_btn.setEnabled(True)
             self.update_device_status()

    def clear_preview(self):
        if self._is_closing: return
        self._previewed_commands = []
        self.preview_area.clear()
        self.preview_area.setPlaceholderText("Generated iptables commands will appear here after preview...")
        self.send_btn.setEnabled(False)

    def preview_policy(self):
        if not policy_engine: QMessageBox.critical(self, "Module Error", "policy_engine not loaded."); return
        if self._is_closing: return
        nl_command = self.nl_input.text().strip()
        if not nl_command: QMessageBox.warning(self, "Input Error", "Please enter policy command."); return
        self.append_log(f"[GUI] Preview requested for: '{nl_command}'")
        self.clear_preview(); self.preview_area.setPlaceholderText("Generating preview...")
        QApplication.processEvents()
        try:
            generated_tuples = policy_engine.parse_and_generate_commands(nl_command)
            if not generated_tuples:
                self.preview_area.setPlaceholderText("No valid commands generated."); self.preview_area.clear()
                QMessageBox.information(self, "Preview", "Could not generate commands."); return
            self._previewed_commands = generated_tuples
            preview_text = ""
            for i, (target_ip, src_ip, dest_ip, cmd_list) in enumerate(generated_tuples):
                 context = []
                 if src_ip: context.append(f"Src: {alias_manager.get_alias_for_ip(src_ip) or src_ip}")
                 if dest_ip: context.append(f"Dest: {alias_manager.get_alias_for_ip(dest_ip) or dest_ip}")
                 target_display = alias_manager.get_alias_for_ip(target_ip) or target_ip
                 context_str = ", ".join(context) if context else "General Rule"
                 preview_text += f"--- Rule {i+1} ({context_str} -> Target: {target_display} [{target_ip}]) ---\n"
                 for cmd in cmd_list: preview_text += f"  {cmd}\n"
                 preview_text += "\n"
            self.preview_area.setPlainText(preview_text.strip())
            self.send_btn.setEnabled(True)
        except Exception as e:
            self.append_log(f"[GUI ERROR] Policy preview failed: {e}")
            logging.exception("Policy preview failed"); self.preview_area.setPlaceholderText("Error during preview.")
            QMessageBox.critical(self, "Preview Error", f"Failed to generate commands:\n{e}"); self.clear_preview()

    def send_policy(self):
        if not admin_connect: QMessageBox.critical(self, "Module Error", "admin_connect not loaded."); return
        if self._is_closing: return
        if not self._previewed_commands: QMessageBox.warning(self, "Send Error", "No commands to send."); return
        if not self.worker_thread or not self.worker_thread.is_alive():
             QMessageBox.critical(self, "Send Error", "Backend not running."); self.clear_preview(); return
        self.append_log("[GUI] Initiating send of previewed commands...")
        self.send_btn.setEnabled(False); QApplication.processEvents()
        sent_count = 0; errors = False
        total_cmds = sum(len(cl) for _,_,_,cl in self._previewed_commands)
        for target_ip, _, _, cmd_list in self._previewed_commands:
            is_connected = False
            try:
                 if hasattr(admin_connect, 'clients_lock') and hasattr(admin_connect, 'clients'):
                     if admin_connect.clients_lock.acquire(timeout=0.1):
                         try: is_connected = target_ip in admin_connect.clients
                         finally: admin_connect.clients_lock.release()
                 if not is_connected:
                      self.append_log(f"[GUI WARN] Target {target_ip} not connected. Skipping {len(cmd_list)} cmds.")
                      errors = True; continue
            except Exception as e:
                 self.append_log(f"[GUI ERROR] Checking connection to {target_ip}: {e}"); errors=True; continue
            for cmd in cmd_list:
                self.append_log(f"[GUI] Sending to {target_ip}: {cmd}"); QApplication.processEvents()
                try:
                    admin_connect.send_command(target_ip, cmd); sent_count += 1; time.sleep(0.05)
                except ConnectionError as e:
                    self.append_log(f"[GUI ERROR] ConnectionError to {target_ip}: {e}"); errors=True; break
                except Exception as e:
                    self.append_log(f"[GUI ERROR] Sending to {target_ip}: {e}"); logging.exception("Send cmd failed"); errors=True
        self.send_btn.setEnabled(bool(self._previewed_commands))
        msg = f"Attempted: {total_cmds}, Sent: {sent_count}."
        if errors: QMessageBox.warning(self, "Send Complete (with errors)", f"{msg}\nCheck logs.")
        else: QMessageBox.information(self, "Send Complete", msg)
        self.clear_preview()

    def closeEvent(self, event):
        if self._is_closing:
             if event: event.accept(); return
        self._is_closing = True
        print("GUI Close event. Shutting down...", file=original_stderr)
        try: self.append_log("[GUI] Close event. Shutting down...")
        except: pass
        self.status_timer.stop()
        try: self.append_log("[GUI] Status timer stopped.")
        except: pass
        if admin_connect and self.worker_thread and self.worker_thread.is_alive():
             try:
                 self.append_log("[GUI] Signaling backend to stop...")
                 admin_connect.stop_event.set()
             except Exception as e: print(f"ERROR signaling backend: {e}", file=original_stderr)
        else:
             try: self.append_log("[GUI] Backend not running or module not loaded.")
             except: pass
        sys.stdout = original_stdout; sys.stderr = original_stderr
        print("[GUI] Restored stdout/stderr.", file=original_stderr)
        print("GUI Shutdown complete.", file=original_stderr)
        if event: event.accept()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s', datefmt='%H:%M:%S')
    if not QApplication: sys.exit(1) # Check if Qt loaded
    if not all([admin_connect, policy_engine, service_mapper, nlp, alias_manager]):
         print("ERROR: Essential modules failed. Exiting.", file=sys.stderr)
         if QApplication: QMessageBox.critical(None, "Import Error", "Backend modules failed. Cannot start.")
         sys.exit(1)
    app = QApplication(sys.argv)
    main_window = AdminGUI()
    main_window.show()
    sys.exit(app.exec())

# --- END OF FILE admin.py ---