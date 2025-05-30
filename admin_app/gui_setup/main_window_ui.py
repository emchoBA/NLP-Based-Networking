from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QAbstractItemView, QHeaderView, QLineEdit, QTextEdit, QLabel, QSplitter
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class Ui_AdminMainWindow:
    def setup_ui(self, main_window):
        main_window.setWindowTitle("Admin Controller")
        main_window.setGeometry(100, 100, 850, 650)

        self.central_widget = QWidget()
        main_window.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # --- Top Control Bar ---
        control_bar_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Server")
        self.stop_btn = QPushButton("Stop Server")
        self.stop_btn.setEnabled(False)
        control_bar_layout.addWidget(self.start_btn)
        control_bar_layout.addWidget(self.stop_btn)
        control_bar_layout.addStretch(1)
        self.main_layout.addLayout(control_bar_layout)

        # --- Main Splitter (Devices and Logs) ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Device Widget
        device_widget = QWidget()
        device_layout = QVBoxLayout(device_widget)
        device_layout.addWidget(QLabel("Connected Devices"))
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(4)
        self.device_table.setHorizontalHeaderLabels(["IP Address", "Alias", "Status", "Last Seen"])
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.device_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        device_layout.addWidget(self.device_table)
        splitter.addWidget(device_widget)

        # Log Widget
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.addWidget(QLabel("System Logs"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 9))
        log_layout.addWidget(self.log_view)
        splitter.addWidget(log_widget)
        splitter.setSizes([380, 470])
        self.main_layout.addWidget(splitter, 1)

        # --- Policy Widget ---
        policy_widget = QWidget()
        policy_layout = QVBoxLayout(policy_widget)
        self.target_label = QLabel("Selected Target: None")
        policy_layout.addWidget(self.target_label)

        nl_layout = QHBoxLayout()
        nl_layout.addWidget(QLabel("Policy Command(s):"))
        self.nl_input = QLineEdit()
        self.nl_input.setPlaceholderText("e.g., on MyDevice deny ssh from 1.2.3.4")
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
        self.send_btn = QPushButton("Send Policy")
        self.send_btn.setEnabled(False)
        preview_buttons_layout.addWidget(self.preview_btn)
        preview_buttons_layout.addWidget(self.send_btn)
        preview_layout.addLayout(preview_buttons_layout)
        policy_layout.addLayout(preview_layout)
        self.main_layout.addWidget(policy_widget)