# Hermes CoAgent Tray v2 - Full Feature System Tray App
# Icon by the clock with start/stop/dashboard/emergency/settings/pairing/notifications/clipboard/logs/quick-actions/auto-update

import sys, os, json, subprocess, threading, time, webbrowser, urllib.request, traceback, ctypes
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox, QDialog, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QCheckBox, QGroupBox,
    QTabWidget, QWidget, QSpinBox, QTextEdit, QListWidget, QListWidgetItem,
    QInputDialog, QDialogButtonBox, QScrollArea, QDoubleSpinBox, QComboBox,
    QFormLayout, QStyle
)
from PySide6.QtGui import QIcon, QAction, QFont, QPixmap, QPainter, QColor, QPen, QBrush
from PySide6.QtCore import QTimer, Signal, QObject, Qt

COAGENT_DIR = Path(__file__).parent.resolve()
python_exe = Path(r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe")
if not python_exe.exists():
    python_exe = Path(r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe")
PYTHON = str(python_exe if python_exe.exists() else Path(sys.executable))
CONFIG_FILE = COAGENT_DIR / "tray_config.json"
DEBUG_LOG = COAGENT_DIR / "tray_debug.log"
RELAUNCH_MARKER = COAGENT_DIR / ".tray_relaunch_attempt"
SERVER_SCRIPT = COAGENT_DIR / "hermes_coagent.py"
VERSION = "v3.2"
BUILD_DATE = "2026-06-14"
GITHUB_URL = "https://github.com/Predator04/Hermes-CoAgent"
_LOG_LOCK = threading.RLock()

def debug_log(message, exc_info=False):
    """Append a timestamped line to the tray startup/debug log."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] [pid={os.getpid()}] {message}\n"
        if exc_info:
            if exc_info is True:
                line += traceback.format_exc()
            else:
                line += "".join(traceback.format_exception(*exc_info))
        with _LOG_LOCK:
            with DEBUG_LOG.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass

def install_exception_hook():
    def _hook(exc_type, exc, tb):
        debug_log("Unhandled exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = _hook

def _current_session_id():
    if os.name != "nt":
        return None
    try:
        session_id = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id))
        if not ok:
            raise ctypes.WinError()
        return int(session_id.value)
    except Exception:
        debug_log("Unable to read current Windows session id", exc_info=True)
        return None

def _active_console_session_id():
    if os.name != "nt":
        return None
    try:
        active = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
        if active == 0xFFFFFFFF:
            return None
        return int(active)
    except Exception:
        debug_log("Unable to read active console session id", exc_info=True)
        return None

def _windows_startupinfo():
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo

def _hidden_creationflags():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)

def _run_hidden(args, timeout=10):
    return subprocess.run(
        args,
        cwd=str(COAGENT_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        startupinfo=_windows_startupinfo(),
        creationflags=_hidden_creationflags(),
    )

def _recent_relaunch_attempt(max_age_seconds=45):
    try:
        if not RELAUNCH_MARKER.exists():
            return False
        raw = RELAUNCH_MARKER.read_text(encoding="utf-8").strip()
        attempted_at = datetime.fromisoformat(raw)
        return (datetime.now() - attempted_at).total_seconds() < max_age_seconds
    except Exception:
        return False

def _mark_relaunch_attempt():
    try:
        RELAUNCH_MARKER.write_text(datetime.now().isoformat(), encoding="utf-8")
    except Exception:
        debug_log("Unable to write relaunch marker", exc_info=True)

def _try_pywin32_interactive_relaunch(start_bat, active_session):
    if os.name != "nt" or active_session is None:
        return False
    try:
        import win32con
        import win32process
        import win32security
        import win32ts
    except Exception as e:
        debug_log(f"pywin32 interactive relaunch unavailable: {e}")
        return False

    token = None
    primary_token = None
    try:
        token = win32ts.WTSQueryUserToken(active_session)
        primary_token = win32security.DuplicateTokenEx(
            token,
            win32con.MAXIMUM_ALLOWED,
            None,
            win32security.SecurityImpersonation,
            win32security.TokenPrimary,
        )
        cmd_exe = os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
        command_line = f'"{cmd_exe}" /c ""{start_bat}""'
        startup = win32process.STARTUPINFO()
        startup.lpDesktop = r"winsta0\default"
        startup.dwFlags |= win32con.STARTF_USESHOWWINDOW
        startup.wShowWindow = win32con.SW_HIDE
        creation_flags = win32con.CREATE_NEW_CONSOLE | win32con.CREATE_NEW_PROCESS_GROUP
        proc_info = win32process.CreateProcessAsUser(
            primary_token,
            None,
            command_line,
            None,
            None,
            False,
            creation_flags,
            None,
            str(COAGENT_DIR),
            startup,
        )
        for handle in proc_info[:2]:
            try:
                handle.Close()
            except Exception:
                pass
        debug_log(f"Relaunched tray in active session {active_session} via pywin32 CreateProcessAsUser")
        return True
    except Exception:
        debug_log("pywin32 interactive relaunch failed", exc_info=True)
        return False
    finally:
        for handle in (primary_token, token):
            if handle is not None:
                try:
                    handle.Close()
                except Exception:
                    pass

def _try_schtasks_interactive_relaunch(start_bat):
    if os.name != "nt":
        return False
    task_name = "HermesCoAgentTrayInteractiveRelaunch"
    run_at = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
    task_command = f'cmd.exe /c ""{start_bat}""'
    try:
        create = _run_hidden([
            "schtasks.exe", "/Create",
            "/TN", task_name,
            "/SC", "ONCE",
            "/ST", run_at,
            "/TR", task_command,
            "/F",
            "/RL", "LIMITED",
            "/IT",
        ])
        debug_log(
            "schtasks create rc="
            f"{create.returncode} stdout={create.stdout.strip()} stderr={create.stderr.strip()}"
        )
        if create.returncode != 0:
            return False
        run = _run_hidden(["schtasks.exe", "/Run", "/TN", task_name])
        debug_log(
            "schtasks run rc="
            f"{run.returncode} stdout={run.stdout.strip()} stderr={run.stderr.strip()}"
        )
        return run.returncode == 0
    except Exception:
        debug_log("schtasks interactive relaunch failed", exc_info=True)
        return False

def _try_explorer_relaunch(start_bat):
    if os.name != "nt":
        return False
    try:
        subprocess.Popen(
            ["explorer.exe", str(start_bat)],
            cwd=str(COAGENT_DIR),
            startupinfo=_windows_startupinfo(),
            creationflags=_hidden_creationflags(),
        )
        debug_log("Requested tray relaunch through explorer.exe")
        return True
    except Exception:
        debug_log("explorer.exe relaunch failed", exc_info=True)
        return False

def maybe_relaunch_in_interactive_session():
    if os.name != "nt":
        debug_log("Session check skipped: non-Windows platform")
        return False

    current_session = _current_session_id()
    active_session = _active_console_session_id()
    debug_log(f"Session check: current_session={current_session} active_console_session={active_session}")

    wrong_session = current_session in (None, 0)
    if current_session in (None, 0):
        debug_log("WARNING: Running in session 0 — tray icon will not appear!")
    elif active_session is not None and current_session != active_session:
        wrong_session = True
        debug_log(
            f"WARNING: Running in session {current_session}; active console session is "
            f"{active_session}. Tray icon may not appear."
        )

    if not wrong_session:
        return False
    if _recent_relaunch_attempt():
        debug_log("Skipping interactive relaunch: a recent relaunch attempt marker already exists")
        return False

    start_bat = COAGENT_DIR / "start_tray.bat"
    if not start_bat.exists():
        debug_log(f"Cannot relaunch tray: missing {start_bat}")
        return False

    _mark_relaunch_attempt()
    debug_log(f"Attempting interactive relaunch through {start_bat}")
    if _try_pywin32_interactive_relaunch(start_bat, active_session):
        return True
    if _try_schtasks_interactive_relaunch(start_bat):
        return True
    if _try_explorer_relaunch(start_bat):
        return True

    debug_log("All interactive relaunch attempts failed; continuing in current session for diagnostics")
    return False

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
            except Exception:
                debug_log("Failed to load tray_config.json", exc_info=True)
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
        debug_log("Initializing ServerManager")
        # Kill any old stray server processes (not other pythonw like the tray itself)
        try:
            import subprocess, time
            # Use WMI-like approach: find pythonw processes running hermes_coagent
            script_path = str(SERVER_SCRIPT)
            result = subprocess.run(
                ['wmic', 'process', 'where', f"name='pythonw.exe' and commandline like '%{SERVER_SCRIPT.name}%'",
                 'get', 'processid', '/format:csv'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n')[1:]:
                parts = line.strip().split(',')
                if len(parts) >= 2 and parts[-1].strip().isdigit():
                    try:
                        subprocess.run(['taskkill', '/f', '/pid', parts[-1].strip()], capture_output=True, timeout=3)
                    except Exception:
                        pass
        except Exception:
            pass
        self.process = None
        self._external_running = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._check)
        self._timer.start(3000)
    def _server_responding(self, timeout=0.5):
        r = _api("GET", "/ping", timeout=timeout)
        return "_error" not in r and r.get("status") == "ok"
    def start(self):
        if self.process and self.process.poll() is None: return
        try:
            if self._server_responding():
                self._external_running = True
                debug_log("Server already responding on /ping; not spawning duplicate tray-managed process")
                self.status_changed.emit("running")
                return
            self._external_running = False
            debug_log(f"Starting server: {PYTHON} {SERVER_SCRIPT} {config['port']}")
            self.process = subprocess.Popen(
                [PYTHON, str(SERVER_SCRIPT), str(config["port"])],
                cwd=str(COAGENT_DIR),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            debug_log(f"Server process started pid={self.process.pid}")
            self.status_changed.emit("running")
        except Exception as e:
            debug_log("Server start failed", exc_info=True)
            self.status_changed.emit(f"error: {e}")
    def stop(self):
        if self.process and self.process.poll() is None:
            debug_log(f"Stopping server pid={self.process.pid}")
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except: self.process.kill()
            self.process = None
            self.status_changed.emit("stopped")
        elif self._external_running:
            debug_log("Stop requested, but server is externally managed; leaving existing server running")
            self.status_changed.emit("running")
    def restart(self):
        self.stop(); time.sleep(0.5); self.start()
    def is_running(self):
        return (self.process is not None and self.process.poll() is None) or self._external_running
    def _check(self):
        if self.process and self.process.poll() is not None:
            self.process = None
            if self._server_responding(timeout=0.4):
                self._external_running = True
                self.status_changed.emit("running")
            else:
                self._external_running = False
                self.status_changed.emit("stopped")
        elif not self.process:
            responding = self._server_responding(timeout=0.4)
            if responding and not self._external_running:
                self._external_running = True
                self.status_changed.emit("running")
            elif not responding and self._external_running:
                self._external_running = False
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

class TrayEventBridge(QObject):
    action = Signal(object)

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
        try:
            debug_log("CoAgentTray.__init__ starting")
            self._initialize()
            debug_log("CoAgentTray.__init__ completed")
        except Exception:
            debug_log("CoAgentTray.__init__ failed", exc_info=True)
            try:
                QMessageBox.critical(None, "Hermes CoAgent Tray", f"Tray startup failed. See:\n{DEBUG_LOG}")
            except Exception:
                pass
            raise

    def _initialize(self):
        app = QApplication.instance()
        if app is None:
            debug_log("Creating QApplication")
            app = QApplication(sys.argv)
        else:
            debug_log("Using existing QApplication instance")
        self.app = app
        if QApplication.instance() is None:
            raise RuntimeError("QApplication.instance() is None after QApplication initialization")

        self.app.setApplicationName("Hermes CoAgent")
        self.app.setOrganizationName("Edge Foundry")
        self.app.setQuitOnLastWindowClosed(False)
        try:
            self.app.setStyle("Fusion")
            debug_log("QApplication style set to Fusion")
        except Exception:
            debug_log("Unable to set QApplication style to Fusion", exc_info=True)

        screens = self.app.screens()
        primary = self.app.primaryScreen()
        debug_log(
            "QApplication ready: "
            f"platform={self.app.platformName()} screens={len(screens)} "
            f"primary_screen={primary.name() if primary else None}"
        )
        if not screens:
            debug_log("WARNING: QApplication has no screens; tray icon cannot be displayed")

        self._status = "stopped"
        self._api_bridge = ApiResultBridge()
        self._api_bridge.result.connect(self._handle_api_result)
        self._event_bridge = TrayEventBridge()
        self._event_bridge.action.connect(self._handle_server_action_event)
        self._api_inflight = set()
        self._menu_built = False
        self._qa_menu = None
        self._clip_menu = None
        self._flash_generation = 0

        self.server = ServerManager()
        self.server.status_changed.connect(self._on_status)

        self.tray = QSystemTrayIcon(self.app)
        tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        supports_messages = QSystemTrayIcon.supportsMessages()
        debug_log(
            "QSystemTrayIcon created: "
            f"isSystemTrayAvailable={tray_available} supportsMessages={supports_messages}"
        )
        if not tray_available:
            debug_log("WARNING: QSystemTrayIcon.isSystemTrayAvailable() returned False")
        self.tray.setToolTip("Hermes CoAgent - Starting...")
        self._update_icon("stopped")
        self.tray.activated.connect(self._on_click)

        debug_log("Initializing clipboard history")
        self._clip_history = []
        self._last_clip = ""

        debug_log("Building tray context menu")
        self.menu = QMenu("Hermes CoAgent")
        self._build_menu()
        self.menu.aboutToShow.connect(self._refresh_menu_dynamic)
        self.tray.setContextMenu(self.menu)

        self._clipboard = QApplication.clipboard()
        if self._clipboard is not None:
            self._clipboard.dataChanged.connect(self._on_clipboard_changed)
            debug_log("Clipboard dataChanged signal connected")
        else:
            debug_log("WARNING: QApplication.clipboard() returned None")

        self._stats_timer = QTimer(self.app)
        self._stats_timer.timeout.connect(self._refresh_stats)

        self._sse_thread = None
        self._sse_stop = threading.Event()
        self._sse_connected = False
        self._notif_timer = QTimer(self.app)
        self._notif_timer.timeout.connect(self._poll_notifications)
        self._last_notif_count = None

        debug_log("Showing tray icon")
        self.tray.show()
        debug_log(
            "Tray show called: "
            f"isVisible={self.tray.isVisible()} supportsMessages={QSystemTrayIcon.supportsMessages()}"
        )

        debug_log("Starting stats and notification timers")
        self._stats_timer.start(5000)
        self._notif_timer.start(3000)

        if config["autostart_server"]:
            debug_log("Scheduling server autostart")
            QTimer.singleShot(1000, self.server.start)

    def _fallback_icon(self):
        for theme_name in ("computer", "applications-system", "dialog-information"):
            icon = QIcon.fromTheme(theme_name)
            if not icon.isNull():
                debug_log(f"Using theme fallback tray icon: {theme_name}")
                return icon
        try:
            icon = self.app.style().standardIcon(QStyle.SP_ComputerIcon)
            if not icon.isNull():
                debug_log("Using QStyle.SP_ComputerIcon fallback tray icon")
                return icon
        except Exception:
            debug_log("Unable to load standard fallback tray icon", exc_info=True)
        return QIcon()

    def _set_tray_icon(self, icon, source):
        if icon.isNull():
            debug_log(f"Tray icon from {source} is null; trying fallback icon")
            icon = self._fallback_icon()
        self.tray.setIcon(icon)
        debug_log(f"Tray icon set from {source}; final_is_null={icon.isNull()}")

    def _update_icon(self, status, pixmap_data=None):
        painter = None
        try:
            pm = QPixmap(32, 32)
            if pm.isNull():
                debug_log("QPixmap(32, 32) returned null while rendering tray icon")
                self._set_tray_icon(QIcon(), "null generated pixmap")
                return
            pm.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pm)
            if not painter.isActive():
                debug_log("QPainter is inactive while rendering tray icon")
                self._set_tray_icon(QIcon(), "inactive painter")
                return
            painter.setRenderHint(QPainter.Antialiasing)
            if pixmap_data:
                thumb = QPixmap()
                if thumb.loadFromData(pixmap_data) and not thumb.isNull():
                    painter.drawPixmap(0, 0, thumb.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    painter.end()
                    painter = None
                    self._set_tray_icon(QIcon(pm), "pixmap data")
                    return
                debug_log("Provided tray pixmap_data could not be loaded; using generated status icon")
            if status == "flash":
                color = QColor(255, 255, 255)
            elif status == "running":
                color = QColor(0, 200, 83)
            elif "error" in status:
                color = QColor(255, 50, 50)
            else:
                color = QColor(120, 120, 120)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(30, 30, 30), 1))
            painter.drawEllipse(2, 2, 28, 28)
            painter.setPen(QPen(QColor(255, 255, 255) if status != "stopped" else QColor(180, 180, 180), 1))
            font = QFont("Segoe UI", 14, QFont.Bold); painter.setFont(font)
            text = "C" if status != "error" else "!"
            painter.drawText(pm.rect(), Qt.AlignCenter, text)
            painter.end()
            painter = None
            self._set_tray_icon(QIcon(pm), f"generated status={status}")
        except Exception:
            debug_log("Failed to render tray icon", exc_info=True)
            self._set_tray_icon(QIcon(), "icon render exception")
        finally:
            if painter is not None and painter.isActive():
                painter.end()

    def _build_menu(self):
        if getattr(self, "_menu_built", False):
            return
        self._menu_built = True
        self.status_action = QAction("Status: Connecting...", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)

        self.stats_action = QAction("", self.menu)
        self.stats_action.setEnabled(False)
        self.menu.addAction(self.stats_action)

        self.menu.addSeparator()
        self.start_stop_action = QAction("Start Server", self.menu)
        self.start_stop_action.triggered.connect(self._toggle)
        self.menu.addAction(self.start_stop_action)

        restart_action = QAction("Restart Server", self.menu)
        restart_action.triggered.connect(self.server.restart)
        self.menu.addAction(restart_action)

        dash_action = QAction("Open Dashboard", self.menu)
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
        pair_action = QAction("Share Desktop (Remote Access)", self.menu)
        pair_action.triggered.connect(self._show_pairing)
        self.menu.addAction(pair_action)

        # Logs
        log_action = QAction("View Logs", self.menu)
        log_action.triggered.connect(self._show_logs)
        self.menu.addAction(log_action)

        self.menu.addSeparator()

        et = QAction("Emergency Stop", self.menu)
        et.triggered.connect(lambda: self._emergency("stop"))
        self.menu.addAction(et)

        er = QAction("Emergency Resume", self.menu)
        er.triggered.connect(lambda: self._emergency("resume"))
        self.menu.addAction(er)

        self.menu.addSeparator()

        settings_action = QAction("Settings", self.menu)
        settings_action.triggered.connect(self._open_settings)
        self.menu.addAction(settings_action)

        # Auto-update
        update_action = QAction("Check for Updates", self.menu)
        update_action.triggered.connect(self._check_updates)
        self.menu.addAction(update_action)

        self.menu.addSeparator()

        exit_action = QAction("Exit", self.menu)
        exit_action.triggered.connect(self._exit)
        self.menu.addAction(exit_action)

    def _build_qa_menu(self):
        if self._qa_menu is None:
            debug_log("Skipping quick actions menu rebuild because _qa_menu is not initialized")
            return
        self._qa_menu.clear()
        for qa in config["quick_actions"]:
            a = QAction(qa.get("name", "?"), self._qa_menu)
            cmd = qa.get("command", "")
            a.triggered.connect(lambda checked, c=cmd: self._run_quick_action(c))
            self._qa_menu.addAction(a)
        if not config["quick_actions"]:
            a = QAction("(No quick actions - add in Settings)", self._qa_menu)
            a.setEnabled(False)
            self._qa_menu.addAction(a)

    def _build_clip_menu(self):
        if self._clip_menu is None:
            debug_log("Skipping clipboard menu rebuild because _clip_menu is not initialized")
            return
        self._clip_menu.clear()
        for entry in self._clip_history[-20:]:
            text = entry[:50] + ("..." if len(entry) > 50 else "")
            a = QAction(text, self._clip_menu)
            a.triggered.connect(lambda checked, t=entry: QApplication.clipboard().setText(t))
            self._clip_menu.addAction(a)
        if not self._clip_history:
            a = QAction("(Empty)", self._clip_menu)
            a.setEnabled(False)
            self._clip_menu.addAction(a)

    def _refresh_menu_dynamic(self):
        try:
            t = self._status.title() if "error" not in self._status else self._status
            self.status_action.setText(f"Status: {t}")
            self.start_stop_action.setText("Stop Server" if self.server.is_running() else "Start Server")
            self._refresh_stats()
        except Exception:
            debug_log("Tray menu dynamic refresh failed", exc_info=True)

    def _on_status(self, status):
        try:
            previous = self._status
            self._status = status
            debug_log(f"Server status changed: {previous} -> {status}")
            t = status.title() if "error" not in status else status
            self.tray.setToolTip(f"Hermes CoAgent - {t}")
            self.status_action.setText(f"Status: {t}")
            self.start_stop_action.setText("Stop Server" if status == "running" else "Start Server")
            self._update_icon(status)
            if previous != status and config["notify_server_status_changes"]:
                icon = QSystemTrayIcon.Warning if "error" in status else QSystemTrayIcon.Information
                self._show_message("Hermes CoAgent", f"Server {t}", icon)
            if status == "running":
                self._ensure_sse_listener()
            elif "error" in status or status == "stopped":
                self._sse_connected = False
            if previous != status and status == "running" and config["auto_start_tunnel_on_server_start"]:
                QTimer.singleShot(1500, self._auto_start_tunnel)
        except Exception:
            debug_log("Status update handler failed", exc_info=True)

    def _toggle(self):
        if self.server.is_running(): self.server.stop()
        else: self.server.start()

    def _refresh_stats(self):
        try:
            if not self.server.is_running():
                self.stats_action.setText("")
                return
            self._api_async("stats", "GET", "/stats", timeout=2)
        except Exception:
            debug_log("Stats refresh failed", exc_info=True)

    def _poll_notifications(self):
        """Fallback notification polling for history count changes."""
        try:
            if not self.server.is_running():
                return
            self._api_async("notifications", "GET", "/history?limit=1", timeout=2)
        except Exception:
            debug_log("Notification poll failed", exc_info=True)

    def _ensure_sse_listener(self):
        try:
            if self._sse_thread is not None and self._sse_thread.is_alive():
                return
            self._sse_stop.clear()
            self._sse_thread = threading.Thread(
                target=self._sse_loop,
                name="CoAgentTraySSE",
                daemon=True,
            )
            self._sse_thread.start()
            debug_log("SSE listener thread started")
        except Exception:
            debug_log("Failed to start SSE listener thread", exc_info=True)

    def _sse_loop(self):
        debug_log("SSE listener loop entering")
        while not self._sse_stop.is_set():
            if not self.server.is_running():
                self._sse_connected = False
                if self._sse_stop.wait(1.0):
                    break
                continue
            url = f"http://localhost:{config['port']}/events"
            try:
                req = urllib.request.Request(
                    url,
                    headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
                )
                with urllib.request.urlopen(req, timeout=35) as response:
                    self._sse_connected = True
                    debug_log(f"SSE connected to {url}")
                    event_name = "message"
                    data_lines = []
                    while not self._sse_stop.is_set():
                        raw = response.readline()
                        if not raw:
                            break
                        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                        if line == "":
                            if data_lines:
                                self._dispatch_sse_event(event_name, "\n".join(data_lines))
                            event_name = "message"
                            data_lines = []
                        elif line.startswith(":"):
                            continue
                        elif line.startswith("event:"):
                            event_name = line[6:].strip() or "message"
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                self._sse_connected = False
            except Exception as e:
                self._sse_connected = False
                if not self._sse_stop.is_set():
                    debug_log(f"SSE listener disconnected: {e}")
                    self._sse_stop.wait(2.0)
        self._sse_connected = False
        debug_log("SSE listener loop exiting")

    def _dispatch_sse_event(self, event_name, payload):
        try:
            if event_name != "action":
                return
            data = json.loads(payload)
            self._event_bridge.action.emit(data)
        except Exception:
            debug_log(f"Failed to dispatch SSE event {event_name!r}", exc_info=True)

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
            except Exception:
                debug_log("Clipboard change handler failed", exc_info=True)

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
            try:
                result = _api(method, path, body, timeout)
            except Exception as e:
                debug_log(f"API worker failed for {key}", exc_info=True)
                result = {"_error": str(e)}
            try:
                self._api_bridge.result.emit(key, result)
            except Exception:
                debug_log(f"API worker could not emit result for {key}", exc_info=True)

        threading.Thread(target=worker, name=f"CoAgentAPI-{key}", daemon=True).start()

    def _handle_api_result(self, key, result):
        try:
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
        except Exception:
            debug_log(f"API result handler failed for {key}", exc_info=True)

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
            if not self._sse_connected:
                self._flash_action_icon("history-poll")
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

    def _handle_server_action_event(self, action):
        try:
            self._flash_action_icon("sse")
            debug_log(
                "Action event received: "
                f"type={action.get('type')} data={json.dumps(action.get('data', {}))[:100]}"
            )
        except Exception:
            debug_log("Action event handler failed", exc_info=True)

    def _flash_action_icon(self, source):
        try:
            self._flash_generation += 1
            generation = self._flash_generation
            debug_log(f"Flashing tray icon source={source} generation={generation}")
            self._update_icon("flash")
            QTimer.singleShot(200, lambda g=generation: self._restore_icon_after_flash(g))
        except Exception:
            debug_log("Failed to flash tray icon", exc_info=True)

    def _restore_icon_after_flash(self, generation):
        try:
            if generation == self._flash_generation:
                self._update_icon(self._status)
        except Exception:
            debug_log("Failed to restore tray icon after flash", exc_info=True)

    def _show_message(self, title, message, icon=QSystemTrayIcon.Information):
        if not config["show_notifications"]:
            return
        if not QSystemTrayIcon.supportsMessages():
            debug_log(f"Tray messages unsupported; skipped notification title={title!r}")
            return
        duration_ms = int(config["notification_duration"]) * 1000
        try:
            self.tray.showMessage(title, message, icon, duration_ms)
        except Exception:
            debug_log(f"Tray showMessage failed title={title!r}", exc_info=True)

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
        self._show_message(
            "Update Check",
            f"Network update checks are disabled. Current version: {VERSION}",
            QSystemTrayIcon.Information,
        )

    def _on_click(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            webbrowser.open(f"http://localhost:{config['port']}/")

    def _exit(self):
        debug_log("Tray exit requested")
        self._sse_stop.set()
        self.server.stop()
        self._stats_timer.stop()
        self._notif_timer.stop()
        self.tray.hide()
        self.app.quit()

    def run(self):
        debug_log("Entering Qt event loop")
        code = self.app.exec()
        debug_log(f"Qt event loop exited code={code}")
        return code

if __name__ == "__main__":
    try:
        install_exception_hook()
        debug_log("=" * 72)
        debug_log(f"Hermes CoAgent Tray starting: argv={sys.argv!r}")
        debug_log(f"COAGENT_DIR={COAGENT_DIR}")
        debug_log(f"PYTHON={PYTHON}")
        if maybe_relaunch_in_interactive_session():
            debug_log("Interactive relaunch requested successfully; exiting current process")
            sys.exit(0)
        tray = CoAgentTray()
        sys.exit(tray.run())
    except SystemExit:
        raise
    except Exception:
        debug_log("Fatal tray process crash", exc_info=True)
        sys.exit(1)
