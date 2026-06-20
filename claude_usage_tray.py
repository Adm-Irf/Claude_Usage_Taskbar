"""
Claude Usage Tray
=================
A tiny Windows (and macOS/Linux) system-tray app. Click the tray icon and a
small panel appears just above the taskbar showing your Claude usage:

  - Session  (5-hour rolling window)
  - Weekly   (7-day, all models)
  - Weekly Opus (only shown if your account reports it)

Each metric is shown as a bar + percentage, with a "resets in ..." countdown.
Click anywhere outside the panel and it closes itself.

Data source
-----------
There is no official public API for the consumer session/weekly limits. This app
reads the SAME read-only endpoint the settings page uses:

    GET https://claude.ai/api/organizations/{org_id}/usage

authenticated with your own `sessionKey` cookie. Nothing is sent anywhere except
to claude.ai, and every request is a GET (it can never change your account).

Getting your session key (two ways):
  1. Automatic: install `browser-cookie3` and stay logged in to claude.ai in a
     browser. The app will read the cookie for you.
  2. Manual: open claude.ai > DevTools (F12) > Application > Cookies >
     https://claude.ai > copy the value of `sessionKey` into the config file
     printed on first run.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import winreg as _winreg
except ImportError:
    _winreg = None



# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
APP_NAME = "ClaudeUsageTray"
BASE = "https://claude.ai/api"
REFRESH_SECONDS = 300          # auto-refresh interval
STALE_SECONDS = 60             # re-fetch on open if data older than this
REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Colour thresholds (percent used -> colour)
COLOR_OK = "#3fb950"
COLOR_WARN = "#d29922"
COLOR_HIGH = "#f85149"
COLOR_TRACK = "#2a2d34"
COLOR_BG = "#1c1f24"
COLOR_CARD = "#23272e"
COLOR_TEXT = "#e6edf3"
COLOR_MUTED = "#8b949e"


def config_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def load_config() -> dict:
    path = config_path()
    if not os.path.exists(path):
        cfg = {"session_key": "", "org_id": ""}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"session_key": "", "org_id": ""}


def save_config(cfg: dict) -> None:
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# --------------------------------------------------------------------------- #
# Data fetching
# --------------------------------------------------------------------------- #
def get_session_key(cfg: dict):
    """Prefer the configured key, otherwise try reading it from a browser."""
    key = (cfg.get("session_key") or "").strip()
    if key:
        return key
    try:
        import browser_cookie3 as bc
    except ImportError:
        return None
    loaders = []
    for name in ("firefox", "chrome", "edge", "brave", "chromium", "opera"):
        loaders.append(getattr(bc, name, None))
    for loader in loaders:
        if loader is None:
            continue
        try:
            cj = loader(domain_name="claude.ai")
            for c in cj:
                if c.name == "sessionKey" and c.value:
                    return c.value
        except Exception:
            continue
    return None


def _first(d: dict, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d.get(k)
    return None


def _extract(metric):
    """Normalise one usage block into {pct, reset}."""
    if not isinstance(metric, dict):
        return None
    pct = _first(metric, ["utilization_pct", "utilization", "percentage", "pct"])
    reset = _first(metric, ["resets_at", "reset_at", "resetsAt", "reset"])
    if pct is None:
        return None
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return None
    # API returns 0-100. Guard against a fractional encoding just in case.
    if 0 < pct <= 1.0 and isinstance(pct, float):
        pct = pct * 100.0
    pct = max(0.0, min(100.0, pct))
    return {"pct": pct, "reset": reset}


def _pick_org(orgs):
    if not isinstance(orgs, list) or not orgs:
        raise RuntimeError("No organizations returned for this account.")
    for o in orgs:
        caps = o.get("capabilities") or []
        if "chat" in caps:
            return o.get("uuid")
    return orgs[0].get("uuid")


def fetch_usage(session_key: str, org_id: str = ""):
    """Return (normalised_usage_dict, org_id). Raises on failure."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    cookies = {"sessionKey": session_key}

    if not org_id:
        r = s.get(f"{BASE}/organizations", cookies=cookies, timeout=REQUEST_TIMEOUT)
        if r.status_code in (401, 403):
            raise RuntimeError("Not authorised — your session key is missing or expired.")
        r.raise_for_status()
        org_id = _pick_org(r.json())

    r = s.get(f"{BASE}/organizations/{org_id}/usage",
              cookies=cookies, timeout=REQUEST_TIMEOUT)
    if r.status_code in (401, 403):
        raise RuntimeError("Not authorised — your session key is missing or expired.")
    r.raise_for_status()
    data = r.json()

    usage = {
        "session": _extract(data.get("five_hour")),
        "weekly": _extract(data.get("seven_day")),
        "weekly_opus": _extract(data.get("seven_day_opus")),
    }
    return usage, org_id


class Fetcher(QtCore.QThread):
    """Runs the network call off the UI thread."""
    finished_result = QtCore.Signal(dict)

    def __init__(self, session_key, org_id):
        super().__init__()
        self.session_key = session_key
        self.org_id = org_id

    def run(self):
        if not self.session_key:
            self.finished_result.emit(
                {"ok": False, "error": "No session key. See config file."}
            )
            return
        try:
            usage, org_id = fetch_usage(self.session_key, self.org_id)
            self.finished_result.emit({"ok": True, "usage": usage, "org_id": org_id})
        except Exception as e:  # noqa: BLE001
            self.finished_result.emit({"ok": False, "error": str(e)})


# --------------------------------------------------------------------------- #
# Startup helpers (Windows only)
# --------------------------------------------------------------------------- #
_REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_NAME = "ClaudeUsageTray"


def _startup_is_set() -> bool:
    if _winreg is None or not sys.platform.startswith("win"):
        return True
    try:
        k = _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, _REG_RUN)
        _winreg.QueryValueEx(k, _REG_NAME)
        _winreg.CloseKey(k)
        return True
    except OSError:
        return False


def _startup_set() -> bool:
    if _winreg is None or not sys.platform.startswith("win"):
        return False
    if not getattr(sys, "frozen", False):
        return False
    try:
        k = _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, _REG_RUN, 0, _winreg.KEY_SET_VALUE)
        _winreg.SetValueEx(k, _REG_NAME, 0, _winreg.REG_SZ, f'"{sys.executable}"')
        _winreg.CloseKey(k)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def color_for(pct: float) -> str:
    if pct >= 85:
        return COLOR_HIGH
    if pct >= 60:
        return COLOR_WARN
    return COLOR_OK


def humanize_reset(reset_iso) -> str:
    if not reset_iso:
        return ""
    try:
        txt = str(reset_iso).replace("Z", "+00:00")
        when = datetime.fromisoformat(txt)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except Exception:
        return ""
    delta = when - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "resetting…"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"resets in {days}d {hours}h"
    if hours:
        return f"resets in {hours}h {mins}m"
    return f"resets in {mins}m"


# --------------------------------------------------------------------------- #
# UI widgets
# --------------------------------------------------------------------------- #
class Bar(QtWidgets.QWidget):
    """A rounded progress bar."""
    def __init__(self):
        super().__init__()
        self._pct = 0.0
        self.setFixedHeight(8)

    def set_pct(self, pct):
        self._pct = max(0.0, min(100.0, float(pct or 0)))
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        radius = r.height() / 2
        # track
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(COLOR_TRACK))
        p.drawRoundedRect(r, radius, radius)
        # fill
        w = int(r.width() * self._pct / 100.0)
        if w > 0:
            fill = QtCore.QRect(r.left(), r.top(), max(w, int(r.height())), r.height())
            p.setBrush(QtGui.QColor(color_for(self._pct)))
            p.drawRoundedRect(fill, radius, radius)
        p.end()


class MetricRow(QtWidgets.QWidget):
    def __init__(self, title):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.title = QtWidgets.QLabel(title)
        self.title.setStyleSheet(f"color:{COLOR_TEXT}; font-size:12px; font-weight:600;")
        self.pct = QtWidgets.QLabel("—")
        self.pct.setStyleSheet(f"color:{COLOR_TEXT}; font-size:12px; font-weight:700;")
        self.pct.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.pct)

        self.bar = Bar()

        self.reset = QtWidgets.QLabel("")
        self.reset.setStyleSheet(f"color:{COLOR_MUTED}; font-size:10px;")

        lay.addLayout(top)
        lay.addWidget(self.bar)
        lay.addWidget(self.reset)

    def update_metric(self, metric):
        if not metric:
            self.pct.setText("—")
            self.bar.set_pct(0)
            self.reset.setText("")
            return
        pct = metric["pct"]
        self.pct.setText(f"{pct:.0f}%")
        self.pct.setStyleSheet(
            f"color:{color_for(pct)}; font-size:12px; font-weight:700;"
        )
        self.bar.set_pct(pct)
        self.reset.setText(humanize_reset(metric.get("reset")))


class Popup(QtWidgets.QWidget):
    """Frameless panel that auto-closes when you click outside it."""
    hidden = QtCore.Signal()

    def __init__(self, on_refresh):
        super().__init__(None)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Popup
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self._on_refresh = on_refresh

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)  # room for shadow

        card = QtWidgets.QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            f"#card {{ background:{COLOR_CARD}; border-radius:14px;"
            f" border:1px solid #2f343c; }}"
        )
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QtGui.QColor(0, 0, 0, 170))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 12)
        cl.setSpacing(14)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Claude Usage")
        title.setStyleSheet(
            f"color:{COLOR_TEXT}; font-size:14px; font-weight:700;"
        )
        header.addWidget(title)
        header.addStretch(1)
        cl.addLayout(header)

        self.session_row = MetricRow("Session · 5-hour")
        self.weekly_row = MetricRow("Weekly · all models")
        self.opus_row = MetricRow("Weekly · Opus")
        cl.addWidget(self.session_row)
        cl.addWidget(self.weekly_row)
        cl.addWidget(self.opus_row)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color:{COLOR_HIGH}; font-size:11px;")
        self.error_label.hide()
        cl.addWidget(self.error_label)

        footer = QtWidgets.QHBoxLayout()
        self.updated = QtWidgets.QLabel("")
        self.updated.setStyleSheet(f"color:{COLOR_MUTED}; font-size:10px;")
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        refresh.setStyleSheet(
            "QPushButton{color:%s; background:transparent; border:none;"
            " font-size:11px; font-weight:600;}"
            "QPushButton:hover{color:%s;}" % (COLOR_MUTED, COLOR_TEXT)
        )
        refresh.clicked.connect(self._on_refresh)
        footer.addWidget(self.updated)
        footer.addStretch(1)
        footer.addWidget(refresh)
        cl.addLayout(footer)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2f343c;")
        cl.addWidget(sep)
        self.startup_btn = QtWidgets.QPushButton("Start automatically on Windows login")
        self.startup_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.startup_btn.setStyleSheet(
            "QPushButton{color:%s; background:#2a2d34; border:none; border-radius:6px;"
            " font-size:11px; font-weight:600; padding:6px 10px;}"
            "QPushButton:hover{background:#31363f; color:%s;}" % (COLOR_MUTED, COLOR_OK)
        )
        self.startup_btn.clicked.connect(self._on_startup_clicked)
        self._startup_sep = sep
        cl.addWidget(self.startup_btn)

        self.setFixedWidth(300)
        self._last_ts = 0

    def _on_startup_clicked(self):
        if _startup_set():
            self.startup_btn.hide()
            self._startup_sep.hide()
            self.adjustSize()

    def hideEvent(self, e):
        self.hidden.emit()
        super().hideEvent(e)

    def show_loading(self):
        self.error_label.hide()
        self.updated.setText("Loading…")

    def show_error(self, msg):
        self.error_label.setText(msg)
        self.error_label.show()
        self.updated.setText("Failed to update")
        self.adjustSize()

    def show_usage(self, usage, ts):
        self.error_label.hide()
        self.session_row.update_metric(usage.get("session"))
        self.weekly_row.update_metric(usage.get("weekly"))
        opus = usage.get("weekly_opus")
        self.opus_row.setVisible(bool(opus))
        if opus:
            self.opus_row.update_metric(opus)
        self._last_ts = ts
        self.refresh_updated_label()
        self.adjustSize()

    def refresh_updated_label(self):
        if not self._last_ts:
            return
        ago = int(time.time() - self._last_ts)
        if ago < 60:
            self.updated.setText(f"Updated {ago}s ago")
        else:
            self.updated.setText(f"Updated {ago // 60}m ago")


# --------------------------------------------------------------------------- #
# Tray controller
# --------------------------------------------------------------------------- #
def make_ring_icon(pct, loaded=True) -> QtGui.QIcon:
    size = 64
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    margin = 8
    rect = QtCore.QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    thickness = 9
    pen_track = QtGui.QPen(QtGui.QColor("#3a3f47"), thickness)
    pen_track.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    p.setPen(pen_track)
    p.drawArc(rect, 0, 360 * 16)
    if loaded:
        col = QtGui.QColor(color_for(pct))
        pen = QtGui.QPen(col, thickness)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        span = int(-360 * 16 * (pct / 100.0))
        p.drawArc(rect, 90 * 16, span)
    p.end()
    return QtGui.QIcon(pm)


class Controller(QtCore.QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.cfg = load_config()
        self.session_key = get_session_key(self.cfg)
        self.org_id = (self.cfg.get("org_id") or "").strip()
        self.usage = None
        self.last_ts = 0
        self.fetcher = None

        self.popup = Popup(self.manual_refresh)
        self.popup.hidden.connect(self._on_popup_hidden)
        self._last_hide = 0

        self.tray = QtWidgets.QSystemTrayIcon(make_ring_icon(0, loaded=False))
        self.tray.setToolTip("Claude Usage — loading…")
        menu = QtWidgets.QMenu()
        act_refresh = menu.addAction("Refresh")
        act_refresh.triggered.connect(self.manual_refresh)
        act_open = menu.addAction("Open usage page")
        act_open.triggered.connect(
            lambda: QtGui.QDesktopServices.openUrl(
                QtCore.QUrl("https://claude.ai/settings/usage")
            )
        )
        act_cfg = menu.addAction("Open config folder")
        act_cfg.triggered.connect(
            lambda: QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(config_dir())
            )
        )
        menu.addSeparator()
        act_quit = menu.addAction("Quit")
        act_quit.triggered.connect(self.app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        # Periodic refresh + live "updated Xm ago" / countdown ticks
        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(REFRESH_SECONDS * 1000)

        self.tick_timer = QtCore.QTimer(self)
        self.tick_timer.timeout.connect(self._tick)
        self.tick_timer.start(30 * 1000)

        if not self.session_key:
            self.tray.setToolTip(
                "Claude Usage — no session key. Right-click > Open config folder."
            )
        QtCore.QTimer.singleShot(200, self.refresh)

    # --- tray interaction ---
    def _on_tray_activated(self, reason):
        if reason in (
            QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
            QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            # Debounce: a click that just dismissed the popup shouldn't reopen it.
            if time.time() - self._last_hide < 0.25:
                return
            self.open_popup()

    def _on_popup_hidden(self):
        self._last_hide = time.time()

    def open_popup(self):
        if self.usage:
            self.popup.show_usage(self.usage, self.last_ts)
        elif self.session_key:
            self.popup.show_loading()
        else:
            self.popup.show_error(
                "No session key found.\nRight-click the icon > Open config folder, "
                "paste your claude.ai sessionKey into config.json, then Refresh."
            )
        self.popup.adjustSize()

        cursor = QtGui.QCursor.pos()
        screen = QtWidgets.QApplication.screenAt(cursor) \
            or QtWidgets.QApplication.primaryScreen()
        avail = screen.availableGeometry()
        w, h = self.popup.width(), self.popup.height()
        x = cursor.x() - w // 2
        x = max(avail.left() + 4, min(x, avail.right() - w - 4))
        y = avail.bottom() - h - 50
        self.popup.move(x, y)
        self.popup.show()
        self.popup.raise_()
        self.popup.activateWindow()

        # Re-fetch if data is stale.
        if self.session_key and (time.time() - self.last_ts > STALE_SECONDS):
            self.refresh()

    # --- data ---
    def manual_refresh(self):
        # Re-read key in case the user just pasted it.
        self.cfg = load_config()
        self.session_key = get_session_key(self.cfg)
        self.org_id = (self.cfg.get("org_id") or "").strip()
        if self.popup.isVisible():
            self.popup.show_loading()
        self.refresh()

    def refresh(self):
        if self.fetcher and self.fetcher.isRunning():
            return
        self.fetcher = Fetcher(self.session_key, self.org_id)
        self.fetcher.finished_result.connect(self._on_fetched)
        self.fetcher.start()

    def _on_fetched(self, result):
        if result.get("ok"):
            self.usage = result["usage"]
            self.last_ts = time.time()
            new_org = result.get("org_id")
            if new_org and new_org != self.org_id:
                self.org_id = new_org
                self.cfg["org_id"] = new_org
                save_config(self.cfg)
            sess = self.usage.get("session")
            sess_pct = sess["pct"] if sess else 0
            self.tray.setIcon(make_ring_icon(sess_pct, loaded=True))
            wk = self.usage.get("weekly")
            wk_pct = wk["pct"] if wk else 0
            self.tray.setToolTip(
                f"Claude — Session {sess_pct:.0f}% · Weekly {wk_pct:.0f}%"
            )
            if self.popup.isVisible():
                self.popup.show_usage(self.usage, self.last_ts)
        else:
            err = result.get("error", "Unknown error")
            self.tray.setToolTip(f"Claude Usage — {err}")
            if self.popup.isVisible():
                self.popup.show_error(err)

    def _tick(self):
        if self.popup.isVisible():
            self.popup.refresh_updated_label()
            if self.usage:
                self.popup.show_usage(self.usage, self.last_ts)


def _self_install():
    """If running as a frozen exe outside the install dir, copy there and relaunch."""
    if not (getattr(sys, "frozen", False) and sys.platform.startswith("win")):
        return
    install_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ClaudeUsageTray")
    install_exe = os.path.join(install_dir, "ClaudeUsageTray.exe")
    current_exe = sys.executable
    if os.path.normcase(os.path.abspath(current_exe)) == os.path.normcase(os.path.abspath(install_exe)):
        return
    os.makedirs(install_dir, exist_ok=True)
    shutil.copyfile(current_exe, install_exe)
    subprocess.Popen([install_exe])
    sys.exit(0)


def main():
    _self_install()
    QtWidgets.QApplication.setQuitOnLastWindowClosed(False)
    app = QtWidgets.QApplication(sys.argv)
    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        QtWidgets.QMessageBox.critical(
            None, APP_NAME, "No system tray available on this system."
        )
        return 1
    _ = Controller(app)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
