"""
Claude Usage Tray
=================
A tiny Windows system-tray app showing your Claude usage at a glance.

Authentication (automatic, no setup needed):
  1. Claude Code  — reads ~/.claude/.credentials.json
  2. Browser      — reads sessionKey cookie from Chrome/Firefox/Edge
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import ssl
import urllib.error
import urllib.request

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import winreg as _winreg
except ImportError:
    _winreg = None


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
APP_NAME = "ClaudeUsageTray"
BASE = "https://claude.ai/api"
REFRESH_SECONDS = 300
STALE_SECONDS = 60
REQUEST_TIMEOUT = 15
MIN_MANUAL_INTERVAL = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

COLOR_OK    = "#3fb950"
COLOR_WARN  = "#d29922"
COLOR_HIGH  = "#f85149"
COLOR_TRACK = "#2a2d34"
COLOR_BG    = "#1c1f24"
COLOR_CARD  = "#23272e"
COLOR_TEXT  = "#e6edf3"
COLOR_MUTED = "#8b949e"


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def _read_claude_code_credentials():
    """Return (token, org_id) from Claude Code's credentials file, or (None, None)."""
    creds_path = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    try:
        with open(creds_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        token = (data.get("claudeAiOauth") or {}).get("accessToken", "").strip()
        org_id = data.get("organizationUuid", "").strip()
        if token:
            return token, org_id
    except Exception:
        pass
    return None, None


def _refresh_claude_code_token() -> bool:
    """Run 'claude --version' silently so Claude Code auto-refreshes its OAuth token."""
    claude_path = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude_path:
        return False
    try:
        flags = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW
        subprocess.run(
            [claude_path, "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=flags,
        )
        return True
    except Exception:
        return False


def _read_browser_cookie():
    """Return sessionKey cookie value from the first browser that has one."""
    try:
        import browser_cookie3 as bc
    except ImportError:
        return None
    for name in ("firefox", "chrome", "edge", "brave", "chromium", "opera"):
        loader = getattr(bc, name, None)
        if loader is None:
            continue
        try:
            for c in loader(domain_name="claude.ai"):
                if c.name == "sessionKey" and c.value:
                    return c.value
        except Exception:
            continue
    return None


def get_credentials():
    """Return (token, org_id). Claude Code first, then browser cookie."""
    token, org_id = _read_claude_code_credentials()
    if token:
        return token, org_id
    cookie = _read_browser_cookie()
    if cookie:
        return cookie, ""
    return None, ""


# --------------------------------------------------------------------------- #
# HTTP + usage fetching
# --------------------------------------------------------------------------- #
class RateLimitedError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        wait = f" Retry in {retry_after}s." if retry_after else ""
        super().__init__(f"Rate limited by Claude — too many requests.{wait} Will retry automatically.")


def _http_get(url: str, headers: dict, timeout: int) -> dict:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("Not authorised — session expired. Log in to claude.ai again.")
        if e.code == 429:
            raw = e.headers.get("Retry-After") or e.headers.get("retry-after") or "0"
            try:
                secs = int(raw)
            except ValueError:
                secs = 0
            raise RateLimitedError(secs)
        raise RuntimeError(f"HTTP {e.code}: {e.reason}")


def _first(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d.get(k)
    return None


def _extract(metric):
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
    if 0 < pct <= 1.0 and isinstance(pct, float):
        pct *= 100.0
    return {"pct": max(0.0, min(100.0, pct)), "reset": reset}


def _pick_org(orgs):
    if not isinstance(orgs, list) or not orgs:
        raise RuntimeError("No organizations returned for this account.")
    for o in orgs:
        if "chat" in (o.get("capabilities") or []):
            return o.get("uuid"), o.get("name", "")
    return orgs[0].get("uuid"), orgs[0].get("name", "")


def fetch_usage(token: str, org_id: str = ""):
    """Return (usage_dict, org_id, account_label). Raises on failure."""
    if token.startswith("sk-ant-oat"):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-code/1.0.0",
        }
        data = _http_get("https://api.anthropic.com/api/oauth/usage", headers, REQUEST_TIMEOUT)
        account_label = "Claude Code"
    else:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Cookie": f"sessionKey={token}",
        }
        org_name = ""
        if not org_id:
            orgs = _http_get(f"{BASE}/organizations", headers, REQUEST_TIMEOUT)
            org_id, org_name = _pick_org(orgs)
        data = _http_get(f"{BASE}/organizations/{org_id}/usage", headers, REQUEST_TIMEOUT)
        account_label = org_name or org_id[:8] + "…"

    usage = {
        "session":     _extract(data.get("five_hour")),
        "weekly":      _extract(data.get("seven_day")),
        "weekly_opus": _extract(data.get("seven_day_opus")),
    }
    return usage, org_id, account_label


class Fetcher(QtCore.QThread):
    finished_result = QtCore.Signal(dict)

    def __init__(self, token, org_id):
        super().__init__()
        self.token = token
        self.org_id = org_id

    def run(self):
        if not self.token:
            self.finished_result.emit({
                "ok": False,
                "error": "Not connected.\nLog in to claude.ai in Chrome or Firefox,\nor install Claude Code.",
            })
            return
        try:
            usage, org_id, account_label = fetch_usage(self.token, self.org_id)
            self.finished_result.emit({"ok": True, "usage": usage, "org_id": org_id, "account_label": account_label})
        except RateLimitedError as e:
            self.finished_result.emit({"ok": False, "error": str(e), "retry_after": e.retry_after})
        except Exception as e:
            # Claude Code token expired (401) — try to refresh it, then fall back to browser cookie
            if self.token.startswith("sk-ant-oat") and "Not authorised" in str(e):
                # Step 1: ask claude CLI to refresh the OAuth token automatically
                if _refresh_claude_code_token():
                    time.sleep(2)  # wait for credentials file to be rewritten
                    new_token, new_org = _read_claude_code_credentials()
                    if new_token and new_token != self.token:
                        try:
                            usage, org_id, account_label = fetch_usage(new_token, self.org_id or new_org)
                            self.finished_result.emit({"ok": True, "usage": usage, "org_id": org_id, "account_label": account_label})
                            return
                        except Exception:
                            pass
                # Step 2: fall back to browser cookie
                cookie = _read_browser_cookie()
                if cookie:
                    try:
                        usage, org_id, account_label = fetch_usage(cookie, "")
                        self.finished_result.emit({"ok": True, "usage": usage, "org_id": org_id, "account_label": account_label})
                        return
                    except RateLimitedError as e2:
                        self.finished_result.emit({"ok": False, "error": str(e2), "retry_after": e2.retry_after})
                        return
                    except Exception as e2:
                        self.finished_result.emit({"ok": False, "error": str(e2)})
                        return
            self.finished_result.emit({"ok": False, "error": str(e)})


# --------------------------------------------------------------------------- #
# Startup helpers (Windows only)
# --------------------------------------------------------------------------- #
_REG_RUN  = r"Software\Microsoft\Windows\CurrentVersion\Run"
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
    secs = int((when - datetime.now(timezone.utc)).total_seconds())
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
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(COLOR_TRACK))
        p.drawRoundedRect(r, radius, radius)
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
        self.pct.setStyleSheet(f"color:{color_for(pct)}; font-size:12px; font-weight:700;")
        self.bar.set_pct(pct)
        self.reset.setText(humanize_reset(metric.get("reset")))


class Popup(QtWidgets.QWidget):
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
        outer.setContentsMargins(14, 14, 14, 14)

        card = QtWidgets.QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            f"#card {{ background:{COLOR_CARD}; border-radius:14px; border:1px solid #2f343c; }}"
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
        title.setStyleSheet(f"color:{COLOR_TEXT}; font-size:14px; font-weight:700;")
        self.account_label = QtWidgets.QLabel("")
        self.account_label.setStyleSheet(f"color:{COLOR_MUTED}; font-size:10px;")
        self.account_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.account_label.hide()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.account_label)
        cl.addLayout(header)

        self.session_row = MetricRow("Session · 5-hour")
        self.weekly_row  = MetricRow("Weekly · all models")
        self.opus_row    = MetricRow("Weekly · Opus")
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
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(
            "QPushButton{color:%s; background:transparent; border:none; font-size:11px; font-weight:600;}"
            "QPushButton:hover{color:%s;}" % (COLOR_MUTED, COLOR_TEXT)
        )
        refresh_btn.clicked.connect(self._on_refresh)
        footer.addWidget(self.updated)
        footer.addStretch(1)
        footer.addWidget(refresh_btn)
        cl.addLayout(footer)

        self.setFixedWidth(300)
        self._last_ts = 0

    def hideEvent(self, e):
        self.hidden.emit()
        super().hideEvent(e)

    def set_account(self, label: str):
        if label:
            self.account_label.setText(label)
            self.account_label.show()
        else:
            self.account_label.hide()

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
        self.updated.setText(f"Updated {ago}s ago" if ago < 60 else f"Updated {ago // 60}m ago")


# --------------------------------------------------------------------------- #
# Tray icon
# --------------------------------------------------------------------------- #
def make_ring_icon(pct, loaded=True) -> QtGui.QIcon:
    size = 64
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    margin, thickness = 8, 9
    rect = QtCore.QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    pen_track = QtGui.QPen(QtGui.QColor("#3a3f47"), thickness)
    pen_track.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    p.setPen(pen_track)
    p.drawArc(rect, 0, 360 * 16)
    if loaded:
        pen = QtGui.QPen(QtGui.QColor(color_for(pct)), thickness)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 90 * 16, int(-360 * 16 * pct / 100.0))
    p.end()
    return QtGui.QIcon(pm)


# --------------------------------------------------------------------------- #
# Controller
# --------------------------------------------------------------------------- #
class Controller(QtCore.QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.token, self.org_id = get_credentials()
        self.usage = None
        self.last_ts = 0
        self.fetcher = None
        self._rate_limited_until = 0
        self._last_manual_refresh = 0

        self.popup = Popup(self.manual_refresh)
        self.popup.hidden.connect(self._on_popup_hidden)
        self._last_hide = 0

        self.tray = QtWidgets.QSystemTrayIcon(make_ring_icon(0, loaded=False))
        self.tray.setToolTip("Claude Usage — loading…")
        menu = QtWidgets.QMenu()
        menu.addAction("Refresh").triggered.connect(self.manual_refresh)
        menu.addAction("Open usage page").triggered.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://claude.ai/settings/usage"))
        )
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(self.app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(REFRESH_SECONDS * 1000)

        self.tick_timer = QtCore.QTimer(self)
        self.tick_timer.timeout.connect(self._tick)
        self.tick_timer.start(30 * 1000)

        if not self.token:
            self.tray.setToolTip("Claude Usage — not connected. Log in to claude.ai in your browser.")
        QtCore.QTimer.singleShot(200, self.refresh)

    def _on_tray_activated(self, reason):
        if reason in (
            QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
            QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if time.time() - self._last_hide < 0.25:
                return
            self.open_popup()

    def _on_popup_hidden(self):
        self._last_hide = time.time()

    def open_popup(self):
        if self.usage:
            self.popup.show_usage(self.usage, self.last_ts)
        elif self.token:
            self.popup.show_loading()
        else:
            self.popup.show_error(
                "Not connected.\nLog in to claude.ai in Chrome or Firefox,\nor install Claude Code."
            )
        self.popup.adjustSize()

        cursor = QtGui.QCursor.pos()
        screen = QtWidgets.QApplication.screenAt(cursor) or QtWidgets.QApplication.primaryScreen()
        avail = screen.availableGeometry()
        w, h = self.popup.width(), self.popup.height()
        x = max(avail.left() + 4, min(cursor.x() - w // 2, avail.right() - w - 4))
        self.popup.move(x, avail.bottom() - h - 50)
        self.popup.show()
        self.popup.raise_()
        self.popup.activateWindow()

        if self.token and (time.time() - self.last_ts > STALE_SECONDS):
            self.refresh()

    def manual_refresh(self):
        remaining = int(self._rate_limited_until - time.time())
        if remaining > 0:
            if self.popup.isVisible():
                mins, secs = divmod(remaining, 60)
                wait = f"{mins}m {secs}s" if mins else f"{secs}s"
                self.popup.show_error(f"Rate limited — retry in {wait}.")
            return
        since_last = time.time() - self._last_manual_refresh
        if since_last < MIN_MANUAL_INTERVAL:
            if self.popup.isVisible():
                self.popup.show_error(f"Please wait {int(MIN_MANUAL_INTERVAL - since_last)}s before refreshing again.")
            return
        # Re-read credentials in case user just logged in to browser
        self.token, _org = get_credentials()
        if not self.org_id:
            self.org_id = _org or ""
        self._last_manual_refresh = time.time()
        if self.popup.isVisible():
            self.popup.show_loading()
        self.refresh()

    def refresh(self):
        if self.fetcher and self.fetcher.isRunning():
            return
        if time.time() < self._rate_limited_until:
            return
        self.fetcher = Fetcher(self.token, self.org_id)
        self.fetcher.finished_result.connect(self._on_fetched)
        self.fetcher.start()

    def _on_fetched(self, result):
        if result.get("ok"):
            self._rate_limited_until = 0
            self.usage = result["usage"]
            self.last_ts = time.time()
            new_org = result.get("org_id")
            if new_org:
                self.org_id = new_org
            self.popup.set_account(result.get("account_label", ""))
            sess = self.usage.get("session")
            sess_pct = sess["pct"] if sess else 0
            self.tray.setIcon(make_ring_icon(sess_pct, loaded=True))
            wk = self.usage.get("weekly")
            wk_pct = wk["pct"] if wk else 0
            self.tray.setToolTip(f"Claude — Session {sess_pct:.0f}% · Weekly {wk_pct:.0f}%")
            self.refresh_timer.setInterval(REFRESH_SECONDS * 1000)
            if not _startup_is_set():
                _startup_set()
            if self.popup.isVisible():
                self.popup.show_usage(self.usage, self.last_ts)
        else:
            err = result.get("error", "Unknown error")
            self.tray.setToolTip(f"Claude Usage — {err}")
            if self.popup.isVisible():
                self.popup.show_error(err)
            if "rate limited" in err.lower():
                retry_after = result.get("retry_after", 0)
                if retry_after > 0:
                    self._rate_limited_until = time.time() + retry_after
                    QtCore.QTimer.singleShot(retry_after * 1000, self.refresh)
                    self.refresh_timer.setInterval(max(retry_after + 30, 10 * 60) * 1000)
                else:
                    self.refresh_timer.setInterval(10 * 60 * 1000)
            else:
                self.refresh_timer.setInterval(REFRESH_SECONDS * 1000)

    def _tick(self):
        if self.popup.isVisible():
            self.popup.refresh_updated_label()
            if self.usage:
                self.popup.show_usage(self.usage, self.last_ts)


# --------------------------------------------------------------------------- #
# First-run setup dialog
# --------------------------------------------------------------------------- #
class SetupDialog(QtWidgets.QDialog):
    """Copies the exe to AppData on first run (strips Zone.Identifier),
    then tests the Claude connection."""

    def __init__(self, original_exe, install_exe):
        super().__init__()
        self.original_exe = original_exe
        self.install_exe = install_exe
        self._fetcher = None

        self.setWindowTitle("Claude Usage Tray — Setup")
        self.setWindowFlag(QtCore.Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedWidth(460)
        self.setStyleSheet(f"background:{COLOR_BG}; color:{COLOR_TEXT};")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(28, 28, 28, 24)

        title = QtWidgets.QLabel("Claude Usage Tray")
        title.setStyleSheet(f"color:{COLOR_TEXT}; font-size:16px; font-weight:700;")
        lay.addWidget(title)

        self.step_install = QtWidgets.QLabel("Installing…")
        self.step_install.setStyleSheet(f"color:{COLOR_MUTED}; font-size:12px;")
        lay.addWidget(self.step_install)

        self.path_label = QtWidgets.QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet(f"color:{COLOR_MUTED}; font-size:10px;")
        self.path_label.hide()
        lay.addWidget(self.path_label)

        self.cleanup_label = QtWidgets.QLabel("")
        self.cleanup_label.setWordWrap(True)
        self.cleanup_label.setStyleSheet(f"color:{COLOR_MUTED}; font-size:10px;")
        self.cleanup_label.hide()
        lay.addWidget(self.cleanup_label)

        self.step_connect = QtWidgets.QLabel("")
        self.step_connect.setWordWrap(True)
        self.step_connect.setStyleSheet(f"color:{COLOR_MUTED}; font-size:12px;")
        self.step_connect.hide()
        lay.addWidget(self.step_connect)

        bottom = QtWidgets.QHBoxLayout()
        self.retry_btn = QtWidgets.QPushButton("Retry")
        self.retry_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.retry_btn.setStyleSheet(
            f"QPushButton{{color:{COLOR_TEXT}; background:#2a2d34; border:1px solid #3a3f47;"
            f" border-radius:6px; font-size:12px; font-weight:600; padding:8px 14px;}}"
            f"QPushButton:hover{{background:#3a3f47;}}"
        )
        self.retry_btn.clicked.connect(self._try_connect)
        self.retry_btn.hide()
        bottom.addWidget(self.retry_btn)
        bottom.addStretch(1)

        self.done_btn = QtWidgets.QPushButton("Done")
        self.done_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.done_btn.setStyleSheet(
            f"QPushButton{{color:#fff; background:#2563eb; border:none; border-radius:6px;"
            f" font-size:12px; font-weight:600; padding:8px 14px;}}"
            f"QPushButton:hover{{background:#1d4ed8;}}"
        )
        self.done_btn.clicked.connect(self.accept)
        self.done_btn.hide()
        bottom.addWidget(self.done_btn)
        lay.addLayout(bottom)

    def showEvent(self, e):
        super().showEvent(e)
        QtCore.QTimer.singleShot(80, self._do_install)

    def _do_install(self):
        install_dir = os.path.dirname(self.install_exe)
        os.makedirs(install_dir, exist_ok=True)
        shutil.copyfile(self.original_exe, self.install_exe)
        # Remove Zone.Identifier ADS — strips the "downloaded from internet" mark
        # so the installed copy is treated as a local trusted file.
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.kernel32.DeleteFileW(self.install_exe + ":Zone.Identifier")
            except Exception:
                pass
        self.step_install.setText("✓  Installed")
        self.step_install.setStyleSheet(f"color:{COLOR_OK}; font-size:12px; font-weight:600;")
        self.path_label.setText(f"Stored at:  {install_dir}")
        self.path_label.show()
        self.cleanup_label.setText(f"You can now delete the downloaded file:\n{self.original_exe}")
        self.cleanup_label.show()
        self.step_connect.setText("Connecting to Claude…")
        self.step_connect.show()
        self.adjustSize()
        self._try_connect()

    def _try_connect(self):
        self.retry_btn.hide()
        self.done_btn.hide()
        self.step_connect.setText("Connecting to Claude…")
        self.step_connect.setStyleSheet(f"color:{COLOR_MUTED}; font-size:12px;")
        token, org_id = get_credentials()
        self._fetcher = Fetcher(token, org_id)
        self._fetcher.finished_result.connect(self._on_connect_result)
        self._fetcher.start()

    def _on_connect_result(self, result):
        if result.get("ok"):
            label = result.get("account_label", "Claude")
            self.step_connect.setText(f"✓  Connected — {label}")
            self.step_connect.setStyleSheet(f"color:{COLOR_OK}; font-size:12px; font-weight:600;")
        else:
            err = result.get("error", "Failed to connect")
            self.step_connect.setText(f"✗  {err}")
            self.step_connect.setStyleSheet(f"color:{COLOR_HIGH}; font-size:11px;")
            self.retry_btn.show()
        self.done_btn.show()
        self.adjustSize()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
        install_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ClaudeUsageTray")
        install_exe = os.path.join(install_dir, "ClaudeUsageTray.exe")
        current_exe = sys.executable
        if os.path.normcase(os.path.abspath(current_exe)) != os.path.normcase(os.path.abspath(install_exe)):
            app = QtWidgets.QApplication(sys.argv)
            dlg = SetupDialog(current_exe, install_exe)
            dlg.exec()
            if os.path.exists(install_exe):
                os.startfile(install_exe)
            return 0

    if sys.platform.startswith("win") and _winreg is not None:
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "ClaudeUsageTray_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:
            return 0

    QtWidgets.QApplication.setQuitOnLastWindowClosed(False)
    app = QtWidgets.QApplication(sys.argv)
    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        QtWidgets.QMessageBox.critical(None, APP_NAME, "No system tray available on this system.")
        return 1
    _ = Controller(app)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
