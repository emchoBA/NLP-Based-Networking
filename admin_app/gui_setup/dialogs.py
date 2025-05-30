from PyQt6.QtWidgets import QDialog, QLineEdit, QFormLayout, QDialogButtonBox

class AliasDialog(QDialog):
    def __init__(self, ip_address, current_alias="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Set Alias for {ip_address}")
        self.ip_address = ip_address

        layout = QFormLayout(self)
        self.alias_input = QLineEdit(current_alias)
        self.alias_input.setPlaceholderText("Enter alias name (e.g., Gateway)")
        layout.addRow("Alias Name:", self.alias_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_alias(self) -> str:
        return self.alias_input.text().strip()