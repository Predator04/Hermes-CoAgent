import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tray_icon


class FakeIcon:
    instances = []

    def __init__(self, name, icon, title, menu=None):
        self.name = name
        self.icon = icon
        self.title = title
        self.menu = menu
        self.notifications = []
        self.stopped = False
        FakeIcon.instances.append(self)

    def run(self):
        return None

    def stop(self):
        self.stopped = True

    def notify(self, message, title=None):
        self.notifications.append((title, message))

    def update_menu(self):
        return None


class FakeMenu:
    def __init__(self, *items):
        self.items = items


class FakeMenuItem:
    def __init__(self, text, action, default=False):
        self.text = text
        self.action = action
        self.default = default


class FakePystray:
    Icon = FakeIcon
    Menu = FakeMenu
    MenuItem = FakeMenuItem


def test_tray_icon_main_starts_without_errors_and_builds_menu(tmp_path, monkeypatch):
    FakeIcon.instances.clear()
    monkeypatch.setattr(tray_icon, "_config_from_args", lambda: (9123, "", tmp_path, False))
    monkeypatch.setattr(tray_icon, "_other_tray_process_running", lambda: False)
    monkeypatch.setattr(tray_icon, "_acquire_tray_mutex", lambda: True)
    monkeypatch.setattr(tray_icon, "_release_tray_mutex", lambda: None)
    monkeypatch.setattr(tray_icon.atexit, "register", lambda _fn: None)
    monkeypatch.setattr(tray_icon, "_ensure_tray_dependencies", lambda: None)
    monkeypatch.setattr(tray_icon, "_health_loop", lambda _icon, _state: None)
    monkeypatch.setattr(tray_icon, "_create_icon_image", lambda _healthy: object())
    monkeypatch.setattr(tray_icon, "pystray", FakePystray)

    assert tray_icon.main() == 0
    icon = FakeIcon.instances[-1]
    labels = [item.text for item in icon.menu.items]
    assert labels == [
        "Open Dashboard",
        "Settings",
        "Check Health",
        "Start/Open Server",
        "Restart Server",
        "Exit",
    ]


def test_tray_health_loop_updates_state_once(monkeypatch, tmp_path):
    state = tray_icon.TrayState(port=9123, token="", coagent_dir=tmp_path, auto_restart=False)
    icon = FakeIcon("test", object(), "title")

    monkeypatch.setattr(tray_icon, "_ping", lambda _state: (True, 42, "pong"))

    def stop_after_refresh(_icon, _state):
        with _state.lock:
            _state.shutting_down = True

    monkeypatch.setattr(tray_icon, "_refresh_icon", stop_after_refresh)
    monkeypatch.setattr(tray_icon.time, "sleep", lambda _seconds: None)

    tray_icon._health_loop(icon, state)

    assert state.healthy is True
    assert state.server_uptime == 42
    assert state.consecutive_failures == 0


def test_tray_menu_handlers(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(tray_icon.webbrowser, "open", lambda url: opened.append(url))
    state = tray_icon.TrayState(port=9123, token="tok", coagent_dir=tmp_path, auto_restart=False)
    icon = FakeIcon("test", object(), "title")

    tray_icon._open_dashboard(icon, None, state)
    tray_icon._open_url("http://example.test/settings")
    assert opened[0].startswith("http://localhost:9123/")
    assert opened[1] == "http://example.test/settings"

    monkeypatch.setattr(tray_icon, "_ping", lambda _state: (False, 0, "down"))
    monkeypatch.setattr(tray_icon, "_refresh_icon", lambda _icon, _state: None)
    tray_icon._check_health(icon, None, state)
    assert state.healthy is False
    assert icon.notifications[-1][1] == "down"
