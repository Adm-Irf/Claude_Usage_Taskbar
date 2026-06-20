# Claude Usage Tray

A tiny Windows system-tray app that shows your Claude **Session (5-hour)** and **Weekly** usage at a glance — no browser tab needed.

Click the tray icon → a panel pops up with usage bars, percentages, and reset countdowns. Click anywhere outside → it closes. The tray icon itself is a ring that fills and changes colour (green → amber → red) with your session usage.

![Claude Usage Tray](Pic/Screenshot%202026-06-20%20143944.png)

---

## Download & Run

1. Go to the [**Releases**](../../releases/latest) page and download `ClaudeUsageTray.exe`.
2. Double-click it from anywhere (Downloads, Desktop, wherever) — it installs itself automatically.
3. A ring icon appears in your system tray (bottom-right, expand the `^` if hidden).

You can delete the downloaded file after running it — the app copies itself to `%LOCALAPPDATA%\Programs\ClaudeUsageTray\` automatically.

---

## Authentication (one-time)

The app reads the same read-only endpoint the claude.ai settings page uses. It needs your `sessionKey` cookie to sign requests.

**Option A — automatic (easiest)**

Stay logged in to claude.ai in Firefox, Chrome, or Edge. The app tries to read the cookie automatically.
> Chrome on Windows sometimes encrypts cookies in a way the app can't read — Firefox is the most reliable. If auto-read fails, use Option B.

**Option B — manual**

1. Open [claude.ai](https://claude.ai) in your browser.
2. Press **F12** → go to the **Application** tab → **Cookies** → `https://claude.ai`.
3. Copy the value of **`sessionKey`**.
4. Right-click the tray icon → **Open config folder** → open `config.json` and paste it in:
   ```json
   { "session_key": "sk-ant-sid01-....", "org_id": "" }
   ```
5. Right-click the tray icon → **Refresh**.

Session keys expire periodically — if usage stops updating, re-paste a fresh one.

---

## Start on login (optional)

Once the app successfully loads your usage data, a **"Start automatically on Windows login"** button appears at the bottom of the panel. Click it once — done. The button disappears after that.

---

## Right-click menu

| Option | Description |
|---|---|
| **Refresh** | Fetch usage now |
| **Open usage page** | Opens claude.ai/settings/usage |
| **Open config folder** | Where `config.json` lives |
| **Quit** | Exit the app |

---

## Notes / limitations

- There is **no official API** for consumer session/weekly limits. This uses the undocumented `GET /api/organizations/{org_id}/usage` endpoint — the same one the settings page loads. Every request is a read-only GET; nothing leaves your machine except the call to claude.ai.
- "Weekly · Opus" only appears if your account reports a separate Opus weekly cap.
- Works whether you use Claude via the web app or Claude Code — the endpoint reflects shared plan usage either way.

---

## Build from source

Requires Python 3.8+.

```bash
pip install -r requirements.txt
python claude_usage_tray.py
```

To repackage as an exe:

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name ClaudeUsageTray claude_usage_tray.py
```

The exe lands in `dist/`. If auto browser-cookie reading breaks in the packaged build, the manual `config.json` route always works.
