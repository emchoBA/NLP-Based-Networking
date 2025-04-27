#!/usr/bin/env python3
"""
admin.py

GUI wrapper around admin_connect.
Provides Start/Stop controls and an Info menu.
"""

import threading
import tkinter as tk
from tkinter import messagebox

import admin_connect


class AdminGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Admin Controller")
        self.geometry("300x150")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # ── Menu Bar ─────────────────────────────────────────────
        menubar = tk.Menu(self)
        info_menu = tk.Menu(menubar, tearoff=0)
        info_menu.add_command(label="My Name", command=self.show_name)
        menubar.add_cascade(label="Info", menu=info_menu)
        self.config(menu=menubar)

        # ── Start/Stop Buttons ───────────────────────────────────
        self.start_btn = tk.Button(self, text="Start", width=10, command=self.start)
        self.start_btn.pack(pady=(30, 5))

        self.stop_btn = tk.Button(self, text="Stop", width=10, command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(pady=5)

        self.worker_thread = None

    def show_name(self):
        messagebox.showinfo("Info", "Emir Emri")

    def start(self):
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        # clear any previous stop flag
        admin_connect.stop_event.clear()

        # run admin_connect.main() in background
        self.worker_thread = threading.Thread(
            target=admin_connect.main,
            daemon=True
        )
        self.worker_thread.start()

    def stop(self):
        admin_connect.stop_event.set()
        self.stop_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.NORMAL)

    def on_close(self):
        # ensure threads are told to stop
        self.stop()
        self.destroy()


if __name__ == "__main__":
    app = AdminGUI()
    app.mainloop()
