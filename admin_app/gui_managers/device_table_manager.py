import logging
from datetime import datetime
from PyQt6.QtWidgets import QTableWidgetItem, QMenu, QMessageBox
from PyQt6.QtGui import QColor, QAction

# Assuming these are in parent directory or Python path
from backend import admin_connect, alias_manager
from admin_app.gui_setup.dialogs import AliasDialog  # Relative import for AliasDialog

log = logging.getLogger(__name__)


class DeviceTableManager:
    def __init__(self, ui, app_state, append_log_slot, parent_window):
        self.ui = ui  # Instance of Ui_AdminMainWindow
        self.app_state = app_state  # Instance of AppState
        self.append_log = append_log_slot
        self.parent_window = parent_window  # The AdminGUI instance for dialog parent

        self.ui.device_table.customContextMenuRequested.connect(self.show_device_context_menu)
        self.ui.device_table.itemSelectionChanged.connect(self.update_selected_target_from_table)

    def update_device_status(self):
        if not admin_connect or not hasattr(admin_connect, 'devices_lock'):
            return

        if not self.app_state.is_backend_running:  # Check global backend status
            # If backend is not running, mark all connected devices as disconnected
            changed_to_disconnected = False
            for ip in list(self.app_state.devices_status.keys()):
                if self.app_state.devices_status[ip]['status'] == 'Connected':
                    self.app_state.devices_status[ip]['status'] = 'Disconnected (Server Down)'
                    changed_to_disconnected = True
            if changed_to_disconnected:
                self.refresh_device_table()
            return

        now = datetime.now()
        current_connected_ips = set()
        try:
            # Use a short timeout to avoid blocking GUI if lock is contended
            if admin_connect.devices_lock.acquire(timeout=0.05):
                try:
                    if hasattr(admin_connect, 'connected_devices'):
                        current_connected_ips = admin_connect.connected_devices.copy()
                finally:
                    admin_connect.devices_lock.release()
            else:
                self.append_log("[GUI WARN] DeviceTable: Failed to acquire device lock for status update.")
                # Don't return; proceed to mark devices as disconnected if they were previously connected
                # This handles cases where the lock is stuck but devices might have dropped.
        except Exception as e:
            self.append_log(f"[GUI ERROR] DeviceTable: Error getting device list: {e}")
            return

        changed = False
        # Update connected devices
        for ip in current_connected_ips:
            if ip not in self.app_state.devices_status or self.app_state.devices_status[ip]['status'] != 'Connected':
                changed = True
            self.app_state.update_device_status_entry(ip, 'Connected', now)

        # Mark devices no longer in current_connected_ips as Disconnected
        for ip in list(self.app_state.devices_status.keys()):
            if ip not in current_connected_ips and self.app_state.devices_status[ip]['status'] == 'Connected':
                self.app_state.update_device_status_entry(ip, 'Disconnected', self.app_state.devices_status[ip][
                    'last_seen'])  # Keep last seen time
                changed = True

        if changed:
            self.refresh_device_table()

    def refresh_device_table(self):
        if not alias_manager: return
        try:
            self.ui.device_table.setSortingEnabled(False)
            # Restore selection based on actual IP, not display name, for robustness
            selected_actual_ip_to_restore = self.app_state.selected_target_actual_ip
            row_to_reselect = -1

            self.ui.device_table.setRowCount(len(self.app_state.devices_status))
            row_idx = 0
            # Sort by IP for consistent display, or by last_seen if preferred
            sorted_devices = sorted(self.app_state.devices_status.items(), key=lambda item: item[0])

            for ip, data in sorted_devices:
                ip_item = QTableWidgetItem(ip)
                alias_name = alias_manager.get_alias_for_ip(ip)
                alias_item = QTableWidgetItem(alias_name if alias_name else "")
                status_item = QTableWidgetItem(data['status'])
                last_seen_str = data['last_seen'].strftime('%Y-%m-%d %H:%M:%S')
                last_seen_item = QTableWidgetItem(last_seen_str)

                status_color = QColor('darkGreen') if data['status'] == 'Connected' else \
                    (QColor('orange') if 'Server Down' in data['status'] else QColor('red'))
                status_item.setForeground(status_color)

                self.ui.device_table.setItem(row_idx, 0, ip_item)
                self.ui.device_table.setItem(row_idx, 1, alias_item)
                self.ui.device_table.setItem(row_idx, 2, status_item)
                self.ui.device_table.setItem(row_idx, 3, last_seen_item)

                if ip == selected_actual_ip_to_restore:
                    row_to_reselect = row_idx
                row_idx += 1

            self.ui.device_table.setSortingEnabled(True)  # Re-enable sorting

            if row_to_reselect != -1:
                self.ui.device_table.blockSignals(True)
                self.ui.device_table.selectRow(row_to_reselect)
                self.ui.device_table.blockSignals(False)
            elif selected_actual_ip_to_restore is not None:  # If previous selection is gone
                self.app_state.clear_selection_data()
                self.ui.target_label.setText("Selected Target: None")


        except Exception as e:
            self.append_log(f"[GUI ERROR] DeviceTable: Failed to refresh: {e}")
            log.exception("Device table refresh error")

    def update_selected_target_from_table(self):
        selected_items = self.ui.device_table.selectedItems()
        if selected_items:
            selected_row = self.ui.device_table.row(selected_items[0])
            ip_item = self.ui.device_table.item(selected_row, 0)
            alias_item = self.ui.device_table.item(selected_row, 1)

            if ip_item:
                actual_ip = ip_item.text()
                display_name = alias_item.text() if alias_item and alias_item.text() else actual_ip

                if actual_ip != self.app_state.selected_target_actual_ip:  # Check actual IP for change
                    self.app_state.selected_target_ip_display = display_name
                    self.app_state.selected_target_actual_ip = actual_ip
                    self.ui.target_label.setText(f"Selected Target: {display_name} ({actual_ip})")
                    # Policy manager should observe app_state or be notified to clear preview
                    # For now, assume policy manager handles this when preview is clicked.
            else:
                if self.app_state.selected_target_actual_ip is not None:
                    self.app_state.clear_selection_data()
                    self.ui.target_label.setText("Selected Target: None")
        else:
            if self.app_state.selected_target_actual_ip is not None:
                self.app_state.clear_selection_data()
                self.ui.target_label.setText("Selected Target: None")

    def show_device_context_menu(self, position):
        if not alias_manager: return
        selected_items = self.ui.device_table.selectedItems()
        if not selected_items: return

        selected_row = self.ui.device_table.row(selected_items[0])
        ip_item = self.ui.device_table.item(selected_row, 0)
        if not ip_item: return
        ip_address = ip_item.text()

        menu = QMenu(self.parent_window)  # Parent the menu to the main window
        alias_action = QAction("Assign/Edit Alias...", self.parent_window)
        # noinspection PyUnresolvedReferences
        alias_action.triggered.connect(lambda: self.edit_alias_for_ip(ip_address))
        menu.addAction(alias_action)

        remove_alias_action = QAction("Remove Alias", self.parent_window)
        # noinspection PyUnresolvedReferences
        remove_alias_action.triggered.connect(lambda: self.remove_alias_for_ip_action(ip_address))
        current_alias = alias_manager.get_alias_for_ip(ip_address)
        remove_alias_action.setEnabled(bool(current_alias))
        menu.addAction(remove_alias_action)

        menu.exec(self.ui.device_table.viewport().mapToGlobal(position))

    def edit_alias_for_ip(self, ip_address):
        if not alias_manager: return
        current_alias = alias_manager.get_alias_for_ip(ip_address) or ""
        dialog = AliasDialog(ip_address, current_alias, self.parent_window)
        if dialog.exec():
            new_alias = dialog.get_alias()
            if new_alias:
                if alias_manager.add_alias(ip_address, new_alias):
                    self.append_log(f"[GUI] Alias '{new_alias}' set for {ip_address}")
                    self.refresh_device_table()  # Refresh to show new alias
                else:
                    QMessageBox.warning(self.parent_window, "Alias Error", "Failed to set alias. Check logs.")
            elif current_alias:
                if alias_manager.remove_alias_for_ip(ip_address):
                    self.append_log(f"[GUI] Alias removed for {ip_address}")
                    self.refresh_device_table()
                else:
                    QMessageBox.warning(self.parent_window, "Alias Error", "Failed to remove alias. Check logs.")

    def remove_alias_for_ip_action(self, ip_address):
        if not alias_manager: return
        if alias_manager.remove_alias_for_ip(ip_address):
            self.append_log(f"[GUI] Alias removed for {ip_address}")
            self.refresh_device_table()
        else:
            QMessageBox.information(self.parent_window, "Alias Info",
                                    f"No alias was set for {ip_address} or failed to remove.")