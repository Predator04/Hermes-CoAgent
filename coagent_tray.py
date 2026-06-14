# Hermes CoAgent Tray v2 - Full Feature System Tray App
# Icon by the clock with start/stop/dashboard/emergency/settings/pairing/notifications/clipboard/logs/quick-actions/auto-update

import sys, os, json, subprocess, threading, time, webbrowser, queue, urllib.request
from copy import deepcopy
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox, QDialog, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QCheckBox, QGroupBox,
    QTabWidget, QWidget, QSpinBox, QTextEdit, QListWidget, QListWidgetItem,
    QInputDialog, QDialogButtonBox, QScrollArea, QDoubleSpinBox, QComboBox,
    QFormLayout
)
from PySide6.QtGui import QIcon, QAction, QFont, QPixmap, QPainter, QColor, QPen, QBrush, QClipboard
from PySide6.QtCore import QTimer, Signal, QObject, Qt

COAGENT_DIR = Path(__file__).parent.resolve()
python_exe = Path(r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe")
if not python_exe.exists():
    python_exe = Path(r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe")
PYTHON = str(python_exe if python_exe.exists() else Path(sys.executable))
CONFIG_FILE = COAGENT_DIR / "tray_config.json"
SERVER_SCRIPT = COAGENT_DIR / "hermes_coagent.py"
VERSION = "v3.2"
BUILD_DATE = "2026-06-14"
GITHUB_URL = "https://github.com/Predator04/Hermes-CoAgent"

DEFAULT_CONFIG = {
    "port": 9123,
    "autostart_server": True,
    "minimize_to_tray": True,
    "start_minimized": True,
    "quick_actions": [],
    "show_notifications": True,
    "clipboard_history": True,
    "screenshot_interval": 1.0,
    "action_cooldown": 0.12,
    "max_action_history": 1000,
    "emergency_hotkey_combo": "Ctrl+Alt+Shift",
    "theme": "Dark",
    "notify_all_actions": True,
    "notify_errors_only": False,
    "notification_duration": 3,
    "notify_clipboard_changes": False,
    "notify_server_status_changes": True,
    "notification_position": "Bottom-right",
    "macro_name_prefix": "macro_",
    "record_mouse_moves": True,
    "record_clicks_only": False,
    "max_recording_duration": 120,
    "stop_recording_hotkey": "F9",
    "auto_start_tunnel_on_server_start": False,
    "tunnel_log_lines": 2000,
    "show_qr_on_tunnel_start": True,
    "restart_tunnel_on_disconnect": False,
    "show_keepalive_actions": True,
    "home_assistant_auto_reconnect": True,
    "max_tts_message_length": 500,
}

class Config:
    def __init__(self):
        self.data = deepcopy(DEFAULT_CONFIG)
        self.load()
    def load(self):
        if CONFIG_FILE.exists():
            try:
                loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except: pass
    def save(self):
        tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_FILE)
    def __getitem__(self, key): return self.data.get(key, DEFAULT_CONFIG.get(key))
    def __setitem__(self, key, value):
        self.data[key] = value; self.save()

config = Config()

class ServerManager(QObject):
    status_changed = Signal(str)
    def __init__(self):
        super().__init__()
        self.process = None
        self._timer = QTimer()
        self._timer.timeout.connect(self._check)
        self._timer.start(3000)
    def start(self):
        if self.process and self.process.poll() is None: return
        try:
            self.process = subprocess.Popen(
                [PYTHON, str(SERVER_SCRIPT), str(config["port"])],
                cwd=str(COAGENT_DIR),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self.status_changed.emit("running")
        except Exception as e:
            self.status_changed.emit(f"error: {e}")
    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except: self.process.kill()
            self.process = None
            self.status_changed.emit("stopped")
    def restart(self):
        self.stop(); time.sleep(0.5); self.start()
    def is_running(self):
        return self.process is not None and self.process.poll() is None
    def _check(self):
        if self.process and self.process.poll() is not None:
            self.process = None
            self.status_changed.emit("stopped")

def _api(method, path, body=None, timeout=5):
    """Make HTTP request to CoAgent server."""
    url = f"http://localhost:{config['port']}{path}"
    try:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data,
            headers={'Content-Type': 'application/json'} if body else {})
        if method == "POST" and not body:
            req = urllib.request.Request(url, data=b'{}',
                headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}

class ApiResultBridge(QObject):
    result = Signal(str, object)

# === SETTINGS ===
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hermes CoAgent Settings")
        self.setMinimumSize(640, 560)
        layout = QVBoxLayout()
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._notifications_tab(), "Notifications")
        tabs.addTab(self._quick_actions_tab(), "Quick Actions")
        tabs.addTab(self._macros_tab(), "Macros & Recording")
        tabs.addTab(self._tunnel_tab(), "Tunnel & Remote")
        tabs.addTab(self._home_ai_tab(), "Home Automation / AI")
        tabs.addTab(self._about_tab(), "About")
        layout.addWidget(tabs)

        self.notif_cb.toggled.connect(self.enable_notifications_cb.setChecked)
        self.enable_notifications_cb.toggled.connect(self.notif_cb.setChecked)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        self.setLayout(layout)

    def _scroll_tab(self, layout):
        layout.addStretch()
        inner = QWidget()
        inner.setLayout(layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        return scroll

    def _combo(self, key, options):
        box = QComboBox()
        box.addItems(options)
        value = config[key] or DEFAULT_CONFIG[key]
        box.setCurrentText(value if value in options else DEFAULT_CONFIG[key])
        return box

    def _general_tab(self):
        layout = QVBoxLayout()
        pg = QGroupBox("Server Port")
        pl = QHBoxLayout()
        pl.addWidget(QLabel("Port:"))
        self.port_input = QSpinBox(); self.port_input.setRange(1024, 65535); self.port_input.setValue(config["port"])
        pl.addWidget(self.port_input); pg.setLayout(pl); layout.addWidget(pg)

        self.autostart_cb = QCheckBox("Auto-start server on launch")
        self.autostart_cb.setChecked(config["autostart_server"]); layout.addWidget(self.autostart_cb)
        self.notif_cb = QCheckBox("Show desktop notifications")
        self.notif_cb.setChecked(config["show_notifications"]); layout.addWidget(self.notif_cb)
        self.clip_cb = QCheckBox("Track clipboard history")
        self.clip_cb.setChecked(config["clipboard_history"]); layout.addWidget(self.clip_cb)
        self.min_cb = QCheckBox("Start minimized to tray")
        self.min_cb.setChecked(config["start_minimized"]); layout.addWidget(self.min_cb)

        form = QFormLayout()
        self.screenshot_interval_input = QDoubleSpinBox()
        self.screenshot_interval_input.setRange(0.5, 10.0)
        self.screenshot_interval_input.setSingleStep(0.5)
        self.screenshot_interval_input.setDecimals(2)
        self.screenshot_interval_input.setSuffix(" sec")
        self.screenshot_interval_input.setValue(float(config["screenshot_interval"]))
        form.addRow("Screenshot interval:", self.screenshot_interval_input)

        self.action_cooldown_input = QDoubleSpinBox()
        self.action_cooldown_input.setRange(0.05, 1.0)
        self.action_cooldown_input.setSingleStep(0.01)
        self.action_cooldown_input.setDecimals(2)
        self.action_cooldown_input.setSuffix(" sec")
        self.action_cooldown_input.setValue(float(config["action_cooldown"]))
        form.addRow("Action cooldown:", self.action_cooldown_input)

        self.max_action_history_input = QSpinBox()
        self.max_action_history_input.setRange(100, 10000)
        self.max_action_history_input.setSingleStep(100)
        self.max_action_history_input.setValue(int(config["max_action_history"]))
        form.addRow("Max action history:", self.max_action_history_input)

        self.emergency_hotkey_input = QLineEdit(str(config["emergency_hotkey_combo"]))
        form.addRow("Emergency hotkey combo:", self.emergency_hotkey_input)

        self.theme_combo = self._combo("theme", ["Dark", "Light", "System"])
        form.addRow("Theme:", self.theme_combo)

        layout.addLayout(form)
        return self._scroll_tab(layout)

    def _notifications_tab(self):
        layout = QVBoxLayout()
        self.enable_notifications_cb = QCheckBox("Enable notifications")
        self.enable_notifications_cb.setChecked(config["show_notifications"]); layout.addWidget(self.enable_notifications_cb)
        self.notify_all_actions_cb = QCheckBox("Notify on all actions")
        self.notify_all_actions_cb.setChecked(config["notify_all_actions"]); layout.addWidget(self.notify_all_actions_cb)
        self.notify_errors_only_cb = QCheckBox("Notify on errors only")
        self.notify_errors_only_cb.setChecked(config["notify_errors_only"]); layout.addWidget(self.notify_errors_only_cb)

        form = QFormLayout()
        self.notification_duration_input = QSpinBox()
        self.notification_duration_input.setRange(1, 10)
        self.notification_duration_input.setSuffix(" sec")
        self.notification_duration_input.setValue(int(config["notification_duration"]))
        form.addRow("Notification duration:", self.notification_duration_input)

        self.notify_clipboard_changes_cb = QCheckBox("Show clipboard change notifications")
        self.notify_clipboard_changes_cb.setChecked(config["notify_clipboard_changes"])
        form.addRow("", self.notify_clipboard_changes_cb)

        self.notify_server_status_changes_cb = QCheckBox("Show server status changes")
        self.notify_server_status_changes_cb.setChecked(config["notify_server_status_changes"])
        form.addRow("", self.notify_server_status_changes_cb)

        self.notification_position_combo = self._combo(
            "notification_position",
            ["Bottom-right", "Bottom-left", "Top-right", "Top-left"]
        )
        form.addRow("Notification position:", self.notification_position_combo)
        layout.addLayout(form)
        return self._scroll_tab(layout)

    def _macros_tab(self):
        layout = QVBoxLayout()
        form = QFormLayout()
        self.macro_name_prefix_input = QLineEdit(str(config["macro_name_prefix"]))
        form.addRow("Default macro name prefix:", self.macro_name_prefix_input)

        self.record_mouse_moves_cb = QCheckBox("Record mouse moves")
        self.record_mouse_moves_cb.setChecked(config["record_mouse_moves"])
        form.addRow("", self.record_mouse_moves_cb)

        self.record_clicks_only_cb = QCheckBox("Record clicks only")
        self.record_clicks_only_cb.setChecked(config["record_clicks_only"])
        form.addRow("", self.record_clicks_only_cb)

        self.max_recording_duration_input = QSpinBox()
        self.max_recording_duration_input.setRange(10, 600)
        self.max_recording_duration_input.setSuffix(" sec")
        self.max_recording_duration_input.setValue(int(config["max_recording_duration"]))
        form.addRow("Max recording duration:", self.max_recording_duration_input)

        self.stop_recording_hotkey_input = QLineEdit(str(config["stop_recording_hotkey"]))
        form.addRow("Stop recording hotkey:", self.stop_recording_hotkey_input)
        layout.addLayout(form)
        return self._scroll_tab(layout)

    def _tunnel_tab(self):
        layout = QVBoxLayout()
        form = QFormLayout()
        self.auto_start_tunnel_cb = QCheckBox("Auto-start tunnel on server start")
        self.auto_start_tunnel_cb.setChecked(config["auto_start_tunnel_on_server_start"])
        form.addRow("", self.auto_start_tunnel_cb)

        self.tunnel_log_lines_input = QSpinBox()
        self.tunnel_log_lines_input.setRange(100, 5000)
        self.tunnel_log_lines_input.setSingleStep(100)
        self.tunnel_log_lines_input.setValue(int(config["tunnel_log_lines"]))
        form.addRow("Tunnel log lines:", self.tunnel_log_lines_input)

        self.show_qr_on_tunnel_start_cb = QCheckBox("Show QR on tunnel start")
        self.show_qr_on_tunnel_start_cb.setChecked(config["show_qr_on_tunnel_start"])
        form.addRow("", self.show_qr_on_tunnel_start_cb)

        self.restart_tunnel_on_disconnect_cb = QCheckBox("Restart tunnel on disconnect")
        self.restart_tunnel_on_disconnect_cb.setChecked(config["restart_tunnel_on_disconnect"])
        form.addRow("", self.restart_tunnel_on_disconnect_cb)
        layout.addLayout(form)
        return self._scroll_tab(layout)

    def _home_ai_tab(self):
        layout = QVBoxLayout()
        form = QFormLayout()
        self.show_keepalive_actions_cb = QCheckBox("Show keepalive actions in log")
        self.show_keepalive_actions_cb.setChecked(config["show_keepalive_actions"])
        form.addRow("", self.show_keepalive_actions_cb)

        self.home_assistant_auto_reconnect_cb = QCheckBox("Auto-reconnect to Home Assistant")
        self.home_assistant_auto_reconnect_cb.setChecked(config["home_assistant_auto_reconnect"])
        form.addRow("", self.home_assistant_auto_reconnect_cb)

        self.max_tts_message_length_input = QSpinBox()
        self.max_tts_message_length_input.setRange(100, 5000)
        self.max_tts_message_length_input.setSuffix(" chars")
        self.max_tts_message_length_input.setValue(int(config["max_tts_message_length"]))
        form.addRow("Max TTS message length:", self.max_tts_message_length_input)
        layout.addLayout(form)
        return self._scroll_tab(layout)

    def _save_all(self):
        old_port = config["port"]
        config.data.update({
            "port": self.port_input.value(),
            "autostart_server": self.autostart_cb.isChecked(),
            "show_notifications": self.enable_notifications_cb.isChecked(),
            "clipboard_history": self.clip_cb.isChecked(),
            "start_minimized": self.min_cb.isChecked(),
            "screenshot_interval": self.screenshot_interval_input.value(),
            "action_cooldown": self.action_cooldown_input.value(),
            "max_action_history": self.max_action_history_input.value(),
            "emergency_hotkey_combo": self.emergency_hotkey_input.text().strip() or DEFAULT_CONFIG["emergency_hotkey_combo"],
            "theme": self.theme_combo.currentText(),
            "notify_all_actions": self.notify_all_actions_cb.isChecked(),
            "notify_errors_only": self.notify_errors_only_cb.isChecked(),
            "notification_duration": self.notification_duration_input.value(),
            "notify_clipboard_changes": self.notify_clipboard_changes_cb.isChecked(),
            "notify_server_status_changes": self.notify_server_status_changes_cb.isChecked(),
            "notification_position": self.notification_position_combo.currentText(),
            "macro_name_prefix": self.macro_name_prefix_input.text().strip() or DEFAULT_CONFIG["macro_name_prefix"],
            "record_mouse_moves": self.record_mouse_moves_cb.isChecked(),
            "record_clicks_only": self.record_clicks_only_cb.isChecked(),
            "max_recording_duration": self.max_recording_duration_input.value(),
            "stop_recording_hotkey": self.stop_recording_hotkey_input.text().strip() or DEFAULT_CONFIG["stop_recording_hotkey"],
            "auto_start_tunnel_on_server_start": self.auto_start_tunnel_cb.isChecked(),
            "tunnel_log_lines": self.tunnel_log_lines_input.value(),
            "show_qr_on_tunnel_start": self.show_qr_on_tunnel_start_cb.isChecked(),
            "restart_tunnel_on_disconnect": self.restart_tunnel_on_disconnect_cb.isChecked(),
            "show_keepalive_actions": self.show_keepalive_actions_cb.isChecked(),
            "home_assistant_auto_reconnect": self.home_assistant_auto_reconnect_cb.isChecked(),
            "max_tts_message_length": self.max_tts_message_length_input.value(),
        })
        config.save()
        QMessageBox.information(self, "Settings", "Settings saved!")
        if config["port"] != old_port:
            QMessageBox.warning(self, "Port Changed", "Port changed. Restart the server for it to take effect.")

    def _quick_actions_tab(self):
        tab = QWidget(); layout = QVBoxLayout()
        layout.addWidget(QLabel("Quick Actions (right-click menu shortcuts):"))
        self.qa_list = QListWidget()
        self._refresh_qa_list()
        layout.addWidget(self.qa_list)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add"); add_btn.clicked.connect(self._add_qa)
        remove_btn = QPushButton("Remove"); remove_btn.clicked.connect(self._remove_qa)
        btn_row.addWidget(add_btn); btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row); tab.setLayout(layout); return tab

    def _refresh_qa_list(self):
        self.qa_list.clear()
        for i, qa in enumerate(config["quick_actions"]):
            item = QListWidgetItem(f"{qa.get('name','?')} -> {qa.get('command','?')}")
            item.setData(Qt.UserRole, i)
            self.qa_list.addItem(item)

    def _add_qa(self):
        name, ok1 = QInputDialog.getText(self, "Quick Action", "Name (e.g. Chrome):")
        if not ok1 or not name: return
        cmd, ok2 = QInputDialog.getText(self, "Quick Action", f"Command for '{name}' (e.g. start chrome):")
        if not ok2 or not cmd: return
        qa = config["quick_actions"]
        qa.append({"name": name, "command": cmd})
        config["quick_actions"] = qa
        self._refresh_qa_list()

    def _remove_qa(self):
        item = self.qa_list.currentItem()
        if not item: return
        idx = item.data(Qt.UserRole)
        qa = config["quick_actions"]
        if 0 <= idx < len(qa):
            qa.pop(idx)
            config["quick_actions"] = qa
            self._refresh_qa_list()

    def _about_tab(self):
        tab = QWidget(); layout = QVBoxLayout()
        dashboard_url = f"http://localhost:{config['port']}/"
        about = QLabel(
            f"<h2>Hermes CoAgent {VERSION}</h2>"
            "<p><b>Ultimate Desktop Co-Pilot</b></p>"
            "<p>Control your PC from any browser, chat app, or AI agent.</p>"
            "<p>Runs alongside you with 150ms burst-mode input.</p><hr>"
            f"<p>Build date: {BUILD_DATE}</p>"
            f"<p>GitHub: <a href='{GITHUB_URL}'>{GITHUB_URL}</a></p>"
            f"<p>Dashboard: <a href='{dashboard_url}'>{dashboard_url}</a></p>"
            f"<p>Emergency: {config['emergency_hotkey_combo']}</p><hr>"
            "<p>Edge Foundry</p>"
        )
        about.setWordWrap(True); about.setOpenExternalLinks(True)
        layout.addWidget(about); layout.addStretch()
        tab.setLayout(layout); return tab

# === LOG VIEWER ===
class LogViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CoAgent Logs")
        self.setMinimumSize(700, 400)
        layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text)
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh"); refresh_btn.clicked.connect(self._load)
        close_btn = QPushButton("Close"); close_btn.clicked.connect(self.accept)
        btn_row.addWidget(refresh_btn); btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        self.setLayout(layout)
        self._load()

    def _load(self):
        r = _api("GET", "/logs?limit=200")
        if "_error" in r:
            self.log_text.setText(f"Error connecting to server: {r['_error']}\n\nIs the server running?")
            return
        lines = []
        for entry in r.get("logs", []):
            t = entry.get("time","")[11:19]
            lines.append(f"[{t}] {entry.get('msg','')}")
        self.log_text.setText("\n".join(lines) if lines else "No logs yet.")

# === CHAINED QR PAIRING ===
class PairingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Share Desktop")
        self.setMinimumSize(400, 300)
        layout = QVBoxLayout()
        self.status_label = QLabel("Starting tunnel...")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        self.url_label = QLabel("")
        self.url_label.setAlignment(Qt.AlignCenter)
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.url_label.setFont(QFont("Consolas", 10))
        layout.addWidget(self.url_label)
        self.qr_label = QLabel("")
        self.qr_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.qr_label)
        copy_btn = QPushButton("Copy URL")
        copy_btn.clicked.connect(self._copy_url)
        layout.addWidget(copy_btn)
        close_btn = QPushButton("Close"); close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        self.setLayout(layout)
        self._url = ""
        QTimer.singleShot(500, self._start_tunnel)

    def _start_tunnel(self):
        r = _api("POST", "/tunnel/start", timeout=15)
        if "_error" in r:
            self.status_label.setText(f"Error: {r['_error']}\n\nInstall cloudflared from:\nhttps://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
            return
        if r.get("status") == "running" and r.get("url"):
            self._show_url(r["url"])
        elif r.get("status") == "already_running":
            sr = _api("GET", "/tunnel/status")
            if sr.get("url") and "connecting" not in sr["url"]:
                self._show_url(sr["url"])
            else:
                self.status_label.setText("Tunnel already running. Check /tunnel/status")
        else:
            self.status_label.setText(f"Starting... {r.get('message','')}")
            QTimer.singleShot(3000, self._check_url)

    def _check_url(self):
        r = _api("GET", "/tunnel/status")
        if r.get("url") and "connecting" not in r["url"]:
            self._show_url(r["url"])
        else:
            self.status_label.setText(f"Still connecting... {r.get('url','')}")

    def _show_url(self, url):
        self._url = url
        self.status_label.setText("Your desktop is now accessible from anywhere:")
        self.url_label.setText(url)
        if not config["show_qr_on_tunnel_start"]:
            self.qr_label.setText("")
            return
        try:
            import qrcode
            from io import BytesIO
            img = qrcode.make(url)
            buf = BytesIO()
            img.save(buf, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue())
            self.qr_label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except ImportError:
            self.qr_label.setText("Install 'qrcode' lib for QR generation:\npip install qrcode[pil]")

    def _copy_url(self):
        if self._url:
            QApplication.clipboard().setText(self._url)

# === MAIN TRAY ===
class CoAgentTray:
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setApplicationName("Hermes CoAgent")
        self.app.setQuitOnLastWindowClosed(False)

        self._status = "stopped"
        self._api_bridge = ApiResultBridge()
        self._api_bridge.result.connect(self._handle_api_result)
        self._api_inflight = set()

        self.server = ServerManager()
        self.server.status_changed.connect(self._on_status)

        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Hermes CoAgent - Starting...")
        self._update_icon("stopped")
        self.tray.activated.connect(self._on_click)

        # Clipboard history (initialize before building menu)
        self._clip_history = []
        self._last_clip = ""
        self._clipboard = QApplication.clipboard()
        self._clipboard.dataChanged.connect(self._on_clipboard_changed)

        self.menu = QMenu()
        self._build_menu()
        self.menu.aboutToShow.connect(self._refresh_menu_dynamic)
        self.tray.setContextMenu(self.menu)

        # Stats refresh
        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start(5000)

        # Notifications (SSE listener)
        self._sse_active = False
        self._notif_timer = QTimer()
        self._notif_timer.timeout.connect(self._poll_notifications)
        self._last_notif_count = None
        self._notif_timer.start(3000)

        self.tray.show()
        if config["autostart_server"]:
            QTimer.singleShot(1000, self.server.start)

    def _update_icon(self, status, pixmap_data=None):
        pm = QPixmap(32, 32)
        pm.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        if pixmap_data:
            thumb = QPixmap()
            if thumb.loadFromData(pixmap_data) and not thumb.isNull():
                painter.drawPixmap(0, 0, thumb.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                painter.end()
                self.tray.setIcon(QIcon(pm))
                return
        if status == "running": color = QColor(0, 200, 83)
        elif status == "error": color = QColor(255, 50, 50)
        else: color = QColor(120, 120, 120)
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor(30, 30, 30), 1))
        painter.drawEllipse(2, 2, 28, 28)
        painter.setPen(QPen(QColor(255, 255, 255) if status != "stopped" else QColor(180, 180, 180), 1))
        font = QFont("Segoe UI", 14, QFont.Bold); painter.setFont(font)
        text = "C" if status != "error" else "!"
        painter.drawText(pm.rect(), Qt.AlignCenter, text)
        painter.end()
        self.tray.setIcon(QIcon(pm))

    def _build_menu(self):
        if getattr(self, "_menu_built", False):
            return
        self._menu_built = True
        self.status_action = QAction(f"Status: Connecting...")
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)

        self.stats_action = QAction("")
        self.stats_action.setEnabled(False)
        self.menu.addAction(self.stats_action)

        self.menu.addSeparator()
        self.start_stop_action = QAction("Start Server")
        self.start_stop_action.triggered.connect(self._toggle)
        self.menu.addAction(self.start_stop_action)

        restart_action = QAction("Restart Server")
        restart_action.triggered.connect(self.server.restart)
        self.menu.addAction(restart_action)

        dash_action = QAction("Open Dashboard")
        dash_action.triggered.connect(lambda: webbrowser.open(f"http://localhost:{config['port']}/"))
        self.menu.addAction(dash_action)

        self.menu.addSeparator()

        # Quick Actions submenu
        qa_menu = self.menu.addMenu("Quick Actions")
        self._qa_menu = qa_menu
        self._build_qa_menu()

        # Clipboard submenu
        clip_menu = self.menu.addMenu("Clipboard History")
        self._clip_menu = clip_menu
        self._build_clip_menu()

        self.menu.addSeparator()

        # Pairing
        pair_action = QAction("Share Desktop (Remote Access)")
        pair_action.triggered.connect(self._show_pairing)
        self.menu.addAction(pair_action)

        # Logs
        log_action = QAction("View Logs")
        log_action.triggered.connect(self._show_logs)
        self.menu.addAction(log_action)

        self.menu.addSeparator()

        et = QAction("Emergency Stop")
        et.triggered.connect(lambda: self._emergency("stop"))
        self.menu.addAction(et)

        er = QAction("Emergency Resume")
        er.triggered.connect(lambda: self._emergency("resume"))
        self.menu.addAction(er)

        self.menu.addSeparator()

        settings_action = QAction("Settings")
        settings_action.triggered.connect(self._open_settings)
        self.menu.addAction(settings_action)

        # Auto-update
        update_action = QAction("Check for Updates")
        update_action.triggered.connect(self._check_updates)
        self.menu.addAction(update_action)

        self.menu.addSeparator()

        exit_action = QAction("Exit")
        exit_action.triggered.connect(self._exit)
        self.menu.addAction(exit_action)

    def _build_qa_menu(self):
        self._qa_menu.clear()
        for qa in config["quick_actions"]:
            a = QAction(qa.get("name", "?"))
            cmd = qa.get("command", "")
            a.triggered.connect(lambda checked, c=cmd: self._run_quick_action(c))
            self._qa_menu.addAction(a)
        if not config["quick_actions"]:
            a = QAction("(No quick actions - add in Settings)")
            a.setEnabled(False)
            self._qa_menu.addAction(a)

    def _build_clip_menu(self):
        self._clip_menu.clear()
        for entry in self._clip_history[-20:]:
            text = entry[:50] + ("..." if len(entry) > 50 else "")
            a = QAction(text)
            a.triggered.connect(lambda checked, t=entry: QApplication.clipboard().setText(t))
            self._clip_menu.addAction(a)
        if not self._clip_history:
            a = QAction("(Empty)")
            a.setEnabled(False)
            self._clip_menu.addAction(a)

    def _refresh_menu_dynamic(self):
        t = self._status.title() if "error" not in self._status else self._status
        self.status_action.setText(f"Status: {t}")
        self.start_stop_action.setText("Stop Server" if self.server.is_running() else "Start Server")
        self._refresh_stats()

    def _on_status(self, status):
        previous = self._status
        self._status = status
        t = status.title() if "error" not in status else status
        self.tray.setToolTip(f"Hermes CoAgent - {t}")
        self.status_action.setText(f"Status: {t}")
        self.start_stop_action.setText("Stop Server" if status == "running" else "Start Server")
        self._update_icon(status)
        if previous != status and config["notify_server_status_changes"]:
            icon = QSystemTrayIcon.Warning if "error" in status else QSystemTrayIcon.Information
            self._show_message("Hermes CoAgent", f"Server {t}", icon)
        if previous != status and status == "running" and config["auto_start_tunnel_on_server_start"]:
            QTimer.singleShot(1500, self._auto_start_tunnel)

    def _toggle(self):
        if self.server.is_running(): self.server.stop()
        else: self.server.start()

    def _refresh_stats(self):
        if not self.server.is_running():
            self.stats_action.setText("")
            return
        self._api_async("stats", "GET", "/stats", timeout=2)

    def _poll_notifications(self):
        """Poll /events style: check history count for new actions."""
        if not config["show_notifications"] or not self.server.is_running():
            return
        self._api_async("notifications", "GET", "/history?limit=1", timeout=2)

    def _on_clipboard_changed(self):
        if config["clipboard_history"]:
            try:
                current = QApplication.clipboard().text()
                if current and current != self._last_clip and len(current) < 500:
                    self._clip_history.append(current)
                    if len(self._clip_history) > 50:
                        self._clip_history = self._clip_history[-50:]
                    self._last_clip = current
                    self._build_clip_menu()
                    if config["notify_clipboard_changes"]:
                        preview = current[:60] + ("..." if len(current) > 60 else "")
                        self._show_message("Clipboard Updated", preview, QSystemTrayIcon.Information)
            except: pass

    def _emergency(self, action):
        self._api_async(f"emergency:{action}", "POST", f"/emergency/{action}")

    def _run_quick_action(self, cmd):
        key = f"quick-action:{time.monotonic_ns()}"
        self._api_async(key, "POST", "/app/run", {"cmd": cmd, "timeout": 10}, timeout=12)

    def _auto_start_tunnel(self):
        if self.server.is_running():
            self._api_async("tunnel-autostart", "POST", "/tunnel/start", timeout=15)

    def _api_async(self, key, method, path, body=None, timeout=5):
        if key in self._api_inflight:
            return
        self._api_inflight.add(key)

        def worker():
            result = _api(method, path, body, timeout)
            self._api_bridge.result.emit(key, result)

        threading.Thread(target=worker, name=f"CoAgentAPI-{key}", daemon=True).start()

    def _handle_api_result(self, key, result):
        self._api_inflight.discard(key)
        if key == "stats":
            self._handle_stats_result(result)
        elif key == "notifications":
            self._handle_notifications_result(result)
        elif key.startswith("emergency:"):
            action = key.split(":", 1)[1]
            if "_error" not in result:
                msg = "Emergency Stop activated!" if action == "stop" else "Input re-enabled"
                self._show_message("Hermes CoAgent", msg, QSystemTrayIcon.Information)
            else:
                self._show_message("Hermes CoAgent", f"Error: {result['_error']}", QSystemTrayIcon.Warning)
        elif key == "tunnel-autostart" and "_error" in result:
            self._show_message("Tunnel", f"Auto-start failed: {result['_error']}", QSystemTrayIcon.Warning)

    def _handle_stats_result(self, result):
        if "_error" in result:
            return
        mem = result.get("memory_mb", "?")
        acts = result.get("actions_today", 0)
        uptime = result.get("uptime_seconds", 0)
        h = uptime // 3600
        m = (uptime % 3600) // 60
        self.stats_action.setText(f"Actions: {acts}  |  Mem: {mem} MB  |  Up: {h}h {m}m")

    def _handle_notifications_result(self, result):
        if "_error" in result:
            return
        actions = result.get("actions", [])
        total = result.get("total")
        if not isinstance(total, int):
            total = len(actions)
        if self._last_notif_count is None:
            self._last_notif_count = total
            return
        if total < self._last_notif_count:
            self._last_notif_count = total
            return
        if total <= self._last_notif_count:
            return

        if actions:
            last = actions[-1]
            is_error = self._action_is_error(last)
            should_notify = config["notify_errors_only"] and is_error
            should_notify = should_notify or (config["notify_all_actions"] and not config["notify_errors_only"])
            if should_notify:
                msg = f"{last.get('type','?')}: {json.dumps(last.get('data',{}))[:60]}"
                icon = QSystemTrayIcon.Warning if is_error else QSystemTrayIcon.Information
                self._show_message("CoAgent Action", msg, icon)
        self._last_notif_count = total

    def _action_is_error(self, action):
        text = f"{action.get('type', '')} {json.dumps(action.get('data', {}))}".lower()
        return any(token in text for token in ("error", "failed", "exception", "traceback"))

    def _show_message(self, title, message, icon=QSystemTrayIcon.Information):
        if not config["show_notifications"]:
            return
        duration_ms = int(config["notification_duration"]) * 1000
        self.tray.showMessage(title, message, icon, duration_ms)

    def _show_pairing(self):
        dlg = PairingDialog()
        dlg.exec()

    def _show_logs(self):
        dlg = LogViewerDialog()
        dlg.exec()

    def _open_settings(self):
        dlg = SettingsDialog()
        dlg.exec()
        self._build_qa_menu()
        self._build_clip_menu()
        self._refresh_menu_dynamic()

    def _check_updates(self):
        self.tray.showMessage(
            "Update Check",
            f"Network update checks are disabled. Current version: {VERSION}",
            QSystemTrayIcon.Information,
            3000
        )

    def _on_click(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            webbrowser.open(f"http://localhost:{config['port']}/")

    def _exit(self):
        self.server.stop()
        self._stats_timer.stop()
        self._notif_timer.stop()
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())

if __name__ == "__main__":
    tray = CoAgentTray()
    tray.run()
