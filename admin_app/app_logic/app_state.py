from datetime import datetime

class AppState:
    def __init__(self):
        self._previewed_commands: list[tuple[str, str | None, str | None, list[str]]] = []
        self._selected_target_ip_display: str | None = None
        self._selected_target_actual_ip: str | None = None
        self.devices_status: dict[str, dict] = {} # ip: {'status': str, 'last_seen': datetime}
        self.is_backend_running: bool = False # New: to track backend status more directly

    @property
    def previewed_commands(self):
        return self._previewed_commands

    @previewed_commands.setter
    def previewed_commands(self, value):
        self._previewed_commands = value

    @property
    def selected_target_ip_display(self):
        return self._selected_target_ip_display

    @selected_target_ip_display.setter
    def selected_target_ip_display(self, value):
        self._selected_target_ip_display = value

    @property
    def selected_target_actual_ip(self):
        return self._selected_target_actual_ip

    @selected_target_actual_ip.setter
    def selected_target_actual_ip(self, value):
        self._selected_target_actual_ip = value

    def update_device_status_entry(self, ip: str, status: str, last_seen: datetime):
        self.devices_status[ip] = {'status': status, 'last_seen': last_seen}

    def get_device_status_entry(self, ip: str):
        return self.devices_status.get(ip)

    def remove_device_status_entry(self, ip: str):
        if ip in self.devices_status:
            del self.devices_status[ip]

    def clear_all_device_statuses(self):
        self.devices_status.clear()

    def clear_preview_data(self):
        self._previewed_commands = []

    def clear_selection_data(self):
        self._selected_target_ip_display = None
        self._selected_target_actual_ip = None