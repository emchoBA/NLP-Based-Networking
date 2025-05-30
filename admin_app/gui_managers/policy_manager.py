import logging
import time  # For time.sleep in send_policy
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QCoreApplication  # For processEvents

# Assuming these are in parent directory or Python path
from backend import admin_connect, alias_manager
from backend.policy_engine import parse_and_generate_commands_for_gui

log = logging.getLogger(__name__)


class PolicyManager:
    def __init__(self, ui, app_state, append_log_slot, parent_window):
        self.ui = ui  # Instance of Ui_AdminMainWindow
        self.app_state = app_state  # Instance of AppState
        self.append_log = append_log_slot
        self.parent_window = parent_window  # For QMessageBox parent

        self.ui.nl_input.textChanged.connect(self.clear_preview_on_input_change)
        self.ui.preview_btn.clicked.connect(self.preview_policy)
        self.ui.send_btn.clicked.connect(self.send_policy)

    def clear_preview_on_input_change(self):
        # This method is connected to textChanged, so it directly calls clear_preview
        self.clear_preview()

    def clear_preview(self):
        self.app_state.clear_preview_data()
        self.ui.preview_area.clear()
        self.ui.preview_area.setPlaceholderText("Generated iptables commands will appear here after preview...")
        self.ui.send_btn.setEnabled(False)

    def preview_policy(self):
        """if not parse_and_generate_commands_for_gui:
            QMessageBox.critical(self.parent_window, "Module Error", "policy_engine not loaded.")
            return
        """

        nl_command = self.ui.nl_input.text().strip()
        if not nl_command:
            QMessageBox.warning(self.parent_window, "Input Error", "Please enter policy command.")
            return

        preferred_target_for_engine = self.app_state.selected_target_actual_ip
        self.append_log(
            f"[GUI] Preview requested for: '{nl_command}'. GUI Selected Actual IP: {preferred_target_for_engine}")

        self.clear_preview()  # Clear previous state
        self.ui.preview_area.setPlaceholderText("Generating preview...")
        QCoreApplication.processEvents()

        try:
            generated_tuples = parse_and_generate_commands_for_gui(
                nl_command,
                preferred_target_ip=preferred_target_for_engine
            )

            if not generated_tuples:
                self.ui.preview_area.setPlaceholderText("No valid commands generated or rule structure not understood.")
                QMessageBox.information(self.parent_window, "Preview", "Could not generate commands from the input.")
                return

            self.app_state.previewed_commands = generated_tuples
            preview_text = ""
            for i, (target_ip, source_ip, dest_ip, cmd_list) in enumerate(generated_tuples):
                context = []
                alias_fn = alias_manager.get_alias_for_ip if alias_manager else lambda x: None

                if source_ip: context.append(f"Src: {alias_fn(source_ip) or source_ip}")
                if dest_ip: context.append(f"Dest: {alias_fn(dest_ip) or dest_ip}")
                target_display = alias_fn(target_ip) or target_ip
                context_str = ", ".join(context) if context else "General Rule"
                preview_text += f"--- Rule {i + 1} ({context_str} -> Target: {target_display} [{target_ip}]) ---\n"

                if not cmd_list:
                    preview_text += "  (No specific commands generated for this rule)\n"
                for cmd in cmd_list:
                    preview_text += f"  {cmd}\n"
                preview_text += "\n"

            self.ui.preview_area.setPlainText(preview_text.strip())
            self.ui.send_btn.setEnabled(True)

        except Exception as e:
            self.append_log(f"[GUI ERROR] Policy preview failed: {e}")
            log.exception("Policy preview failed")
            self.ui.preview_area.setPlaceholderText("Error during preview. Check logs.")
            QMessageBox.critical(self.parent_window, "Preview Error", f"Failed to parse or generate commands:\n{e}")
            self.clear_preview()  # Ensure state is clean after error

    def send_policy(self):
        if not admin_connect:
            QMessageBox.critical(self.parent_window, "Module Error", "admin_connect not loaded.")
            return
        if not self.app_state.previewed_commands:
            QMessageBox.warning(self.parent_window, "Send Error", "No commands to send. Please preview first.")
            return
        if not self.app_state.is_backend_running:  # Check global backend status
            QMessageBox.critical(self.parent_window, "Send Error", "Backend not running. Cannot send commands.")
            self.clear_preview()
            return

        self.append_log("[GUI] Initiating send of previewed commands...")
        self.ui.send_btn.setEnabled(False)  # Disable while sending
        QCoreApplication.processEvents()

        sent_count = 0
        errors_occurred = False
        total_cmds_to_attempt = sum(len(cl) for _, _, _, cl in self.app_state.previewed_commands)

        for target_ip, _, _, cmd_list in self.app_state.previewed_commands:
            is_connected = False
            try:
                # Check connection status directly from admin_connect's state
                if hasattr(admin_connect, 'clients_lock') and hasattr(admin_connect, 'clients'):
                    if admin_connect.clients_lock.acquire(timeout=0.05):  # Short timeout
                        try:
                            is_connected = target_ip in admin_connect.clients
                        finally:
                            admin_connect.clients_lock.release()

                if not is_connected:
                    self.append_log(f"[GUI WARN] Target {target_ip} not connected. Skipping {len(cmd_list)} cmds.")
                    errors_occurred = True
                    continue
            except Exception as e:
                self.append_log(f"[GUI ERROR] Checking connection to {target_ip}: {e}")
                errors_occurred = True
                continue  # Skip this target if connection check fails

            for cmd in cmd_list:
                self.append_log(f"[GUI] Sending to {target_ip}: {cmd}")
                QCoreApplication.processEvents()
                try:
                    admin_connect.send_command(target_ip, cmd)
                    sent_count += 1
                    time.sleep(0.05)  # Small delay between commands
                except ConnectionError as e:  # Specific error from send_command
                    self.append_log(f"[GUI ERROR] ConnectionError sending to {target_ip}: {e}")
                    errors_occurred = True
                    break  # Stop sending to this IP if a connection error occurs
                except Exception as e:
                    self.append_log(f"[GUI ERROR] Unexpected error sending command to {target_ip}: {e}")
                    log.exception("Send command failed")
                    errors_occurred = True
                    # Optionally break here too, depending on desired behavior for other errors

            if errors_occurred and target_ip in [t[0] for t in self.app_state.previewed_commands]:
                # if an error occurred for this target_ip, maybe don't try other commands for it?
                pass  # Current logic continues to next target_ip if error is within cmd_list loop

        # Re-enable send button only if there are still previewed commands (it might be cleared by now)
        self.ui.send_btn.setEnabled(bool(self.app_state.previewed_commands))

        msg = f"Attempted to send: {total_cmds_to_attempt} command(s). Successfully sent: {sent_count}."
        if errors_occurred:
            QMessageBox.warning(self.parent_window, "Send Complete (with errors)",
                                f"{msg}\nSome commands may not have been sent. Check logs.")
        else:
            QMessageBox.information(self.parent_window, "Send Complete", msg)

        self.clear_preview()  # Clear after sending, regardless of outcome