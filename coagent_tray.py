# Hermes CoAgent Tray — System Tray App
# Runs in taskbar notification area. Start/stop/configure CoAgent.

import sys
import os
import json
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QGroupBox, QTabWidget, QWidget,
    QSpinBox, QComboBox, QTextEdit
)
from PySide6.QtGui import QIcon, QAction, QFont, QPixmap, QPainter, QColor, QPen, QBrush
from PySide6.QtCore import QTimer, Signal, QObject

# --- Config ---
COAGENT_DIR = Path(__file__).parent.resolve()
PYTHON = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
CONFIG_FILE = COAGENT_DIR / "tray_config.json"
SERVER_SCRIPT = COAGENT_DIR / "hermes_coagent.py"

DEFAULT_CONFIG = {
    "port": 9123,
    "autostart_server": True,
    "minimize_to_tray": True,
    "start_minimized": True
}

class Config:
    def __init__(self):
        self.data = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                self.data.update(json.loads(CONFIG_FILE.read_text()))
            except: pass

    def save(self):
        CONFIG_FILE.write_text(json.dumps(self.data, indent=2))

    def __getitem__(self, key):
        return self.data.get(key, DEFAULT_CONFIG.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

config = Config()

# --- Server Manager ---
class ServerManager(QObject):
    status_changed = Signal(str)  # "running", "stopped", "error"

    def __init__(self):
        super().__init__()
        self.process = None
        self._monitor_timer = QTimer()
        self._monitor_timer.timeout.connect(self._check_status)
        self._monitor_timer.start(3000)  # check every 3s

    def start(self):
        if self.process and self.process.poll() is None:
            return  # already running
        try:
            self.process = subprocess.Popen(
                [PYTHON, str(SERVER_SCRIPT), str(config["port"])],
                cwd=str(COAGENT_DIR),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.status_changed.emit("running")
        except Exception as e:
            self.status_changed.emit(f"error: {e}")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            self.process = None
            self.status_changed.emit("stopped")

    def restart(self):
        self.stop()
        time.sleep(0.5)
        self.start()

    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def _check_status(self):
        if self.process and self.process.poll() is not None:
            self.process = None
            self.status_changed.emit("stopped")

# --- Settings Dialog ---
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hermes CoAgent Settings")
        self.setMinimumWidth(450)
        self.setMinimumHeight(350)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._about_tab(), "About")
        layout.addWidget(tabs)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        self.setLayout(layout)

    def _general_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        # Port
        port_group = QGroupBox("Server Port")
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1024, 65535)
        self.port_input.setValue(config["port"])
        port_layout.addWidget(self.port_input)
        port_group.setLayout(port_layout)
        layout.addWidget(port_group)

        # Autostart server
        self.autostart_cb = QCheckBox("Auto-start server on launch")
        self.autostart_cb.setChecked(config["autostart_server"])
        layout.addWidget(self.autostart_cb)

        # Start minimized
        self.minimized_cb = QCheckBox("Start minimized to tray")
        self.minimized_cb.setChecked(config["start_minimized"])
        layout.addWidget(self.minimized_cb)

        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def _about_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        about = QLabel(
            "<h2>Hermes CoAgent v3</h2>"
            "<p><b>Ultimate Desktop Co-Pilot</b></p>"
            "<p>Control your PC from any browser, chat app, or AI agent.</p>"
            "<p>Runs alongside you with 150ms burst-mode input.</p>"
            "<hr>"
            "<p>Dashboard: <a href='http://localhost:9123/'>http://localhost:9123/</a></p>"
            "<p>Emergency: Ctrl+Alt+Shift</p>"
            "<hr>"
            "<p>Edge Foundry</p>"
        )
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)
        layout.addWidget(about)
        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def save_settings(self):
        old_port = config["port"]
        config["port"] = self.port_input.value()
        config["autostart_server"] = self.autostart_cb.isChecked()
        config["start_minimized"] = self.minimized_cb.isChecked()
        config.save()
        QMessageBox.information(self, "Settings", "Settings saved!")
        if config["port"] != old_port:
            QMessageBox.warning(self, "Port Changed",
                "Port changed. Restart the server for it to take effect.")

# --- Main Tray App ---
class CoAgentTray:
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setApplicationName("Hermes CoAgent")
        self.app.setQuitOnLastWindowClosed(False)

        self.server = ServerManager()
        self.server.status_changed.connect(self._on_status_change)

        # Create tray icon
        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Hermes CoAgent — Stopped")
        self._update_icon("stopped")
        self.tray.activated.connect(self._on_tray_click)

        # Build menu
        self.menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)

        # Status polling for status bar update
        self._status = "stopped"
        self.tray.show()

        # Auto-start if configured
        if config["autostart_server"]:
            QTimer.singleShot(1000, self.server.start)

    def _update_icon(self, status):
        """Generate a colored circle icon programmatically."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        if status == "running":
            color = QColor(0, 200, 83)  # green
            text = "C"
        elif status == "error":
            color = QColor(255, 50, 50)  # red
            text = "!"
        else:
            color = QColor(120, 120, 120)  # gray
            text = "C"

        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor(30, 30, 30), 1))
        painter.drawEllipse(2, 2, 28, 28)

        painter.setPen(QPen(QColor(255, 255, 255), 1))
        font = QFont("Segoe UI", 14, QFont.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), 0x0084, text)

        painter.end()
        self.tray.setIcon(QIcon(pixmap))

    def _build_menu(self):
        self.menu.clear()

        # Status header
        self.status_action = QAction(f"Status: {self._status.title()}")
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)

        self.menu.addSeparator()

        # Start/Stop
        self.start_stop_action = QAction("Start Server")
        self.start_stop_action.triggered.connect(self._toggle_server)
        self.menu.addAction(self.start_stop_action)

        # Restart
        restart_action = QAction("Restart Server")
        restart_action.triggered.connect(self.server.restart)
        self.menu.addAction(restart_action)

        # Open Dashboard
        dash_action = QAction("Open Dashboard")
        dash_action.triggered.connect(self._open_dashboard)
        self.menu.addAction(dash_action)

        self.menu.addSeparator()

        # Emergency Stop
        emergency_action = QAction("Emergency Stop")
        emergency_action.triggered.connect(self._emergency_stop)
        self.menu.addAction(emergency_action)

        # Emergency Resume
        resume_action = QAction("Emergency Resume")
        resume_action.triggered.connect(self._emergency_resume)
        self.menu.addAction(resume_action)

        self.menu.addSeparator()

        # Settings
        settings_action = QAction("Settings")
        settings_action.triggered.connect(self._open_settings)
        self.menu.addAction(settings_action)

        self.menu.addSeparator()

        # Exit
        exit_action = QAction("Exit")
        exit_action.triggered.connect(self._exit_app)
        self.menu.addAction(exit_action)

    def _on_status_change(self, status):
        self._status = status
        self._update_icon(status)
        status_text = status.title() if "error" not in status else status
        self.tray.setToolTip(f"Hermes CoAgent — {status_text}")
        if hasattr(self, 'status_action'):
            self.status_action.setText(f"Status: {status_text}")
        if hasattr(self, 'start_stop_action'):
            if status == "running":
                self.start_stop_action.setText("Stop Server")
            else:
                self.start_stop_action.setText("Start Server")

    def _toggle_server(self):
        if self.server.is_running():
            self.server.stop()
        else:
            self.server.start()

    def _open_dashboard(self):
        webbrowser.open(f"http://localhost:{config['port']}/")

    def _emergency_stop(self):
        try:
            import urllib.request
            req = urllib.request.Request(f"http://localhost:{config['port']}/emergency/stop",
                                       data=b'{}', headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=5)
            self.tray.showMessage("Hermes CoAgent", "Emergency Stop activated!", QSystemTrayIcon.Information, 3000)
        except Exception as e:
            self.tray.showMessage("Hermes CoAgent", f"Could not reach server: {e}", QSystemTrayIcon.Warning, 3000)

    def _emergency_resume(self):
        try:
            import urllib.request
            req = urllib.request.Request(f"http://localhost:{config['port']}/emergency/resume",
                                       data=b'{}', headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=5)
            self.tray.showMessage("Hermes CoAgent", "Emergency Resume — input re-enabled", QSystemTrayIcon.Information, 3000)
        except Exception as e:
            self.tray.showMessage("Hermes CoAgent", f"Could not reach server: {e}", QSystemTrayIcon.Warning, 3000)

    def _open_settings(self):
        dlg = SettingsDialog()
        dlg.exec()

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._open_dashboard()

    def _exit_app(self):
        self.server.stop()
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())

if __name__ == "__main__":
    tray = CoAgentTray()
    tray.run()
