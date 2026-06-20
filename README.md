# Claude Usage Tray

A tiny Windows system-tray app that shows your Claude **Session (5-hour)** and **Weekly** usage at a glance — no browser tab needed.

Click the tray icon → a panel pops up with usage bars, percentages, and reset countdowns. Click anywhere outside → it closes. The tray icon itself is a ring that fills and changes colour (green → amber → red) with your session usage.

![Claude Usage Tray](Pic/Screenshot%202026-06-20%20143944.png)

---

## Download & Install

1. Go to the [**Releases**](../../releases/latest) page and download `ClaudeUsageTray.exe`.
2. Double-click it from anywhere (Downloads, Desktop, wherever).
3. A setup window appears — it installs itself to `%LOCALAPPDATA%\Programs\ClaudeUsageTray\`, connects to your Claude account, and shows you the path of the downloaded file.
4. Click **Done**, then manually delete the downloaded file.
5. The ring icon appears in your system tray (bottom-right, expand `^` if hidden).

---

## Storage

| What | Size | When |
|---|---|---|
| Installed exe | ~30 MB | Permanent — lives in `%LOCALAPPDATA%\Programs\ClaudeUsageTray\` |
| Temp files | ~73 MB | While running only — PyInstaller unpacks to `%TEMP%`, auto-deleted on exit |
| Config | < 1 KB | Permanent — lives in `%APPDATA%\ClaudeUsageTray\` |

**After you delete the downloaded file:** only the ~30 MB installed exe remains on disk. Temp files appear when the app starts and are automatically cleaned up when it exits (or on next Windows startup if it was force-killed).

The ~30 MB is the irreducible minimum for a Python app with a Qt UI — it bundles the Qt6 rendering library (~26 MB) and the Python runtime (~7 MB) so no separate install is needed.

To fully uninstall: delete `%LOCALAPPDATA%\Programs\ClaudeUsageTray\` and `%APPDATA%\ClaudeUsageTray\`, and remove the startup entry in Task Manager → Startup apps.

---

## Authentication

The app connects automatically with **zero setup** if you have **Claude Code** installed — it reads your existing credentials from `~/.claude/.credentials.json`.

If you don't use Claude Code, it falls back to reading your browser session cookie. If that also fails, a **"Connect Claude Account"** button appears in the panel:

1. Click it — claude.ai opens in your browser (log in if prompted).
2. The app tries to read the session automatically for ~15 seconds.
3. If Chrome's encryption blocks it, a paste field appears:
   - Open claude.ai → **F12** → **Application** → **Cookies** → copy **`sessionKey`** → paste it in.

Session keys expire periodically — if usage stops updating, click **Refresh** or re-paste a fresh key.

---

## Start on login

Handled automatically. The first time the app successfully connects to your Claude account, it registers itself to start on Windows login — no action needed.

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

- There is **no official API** for consumer session/weekly limits. This uses the undocumented usage endpoint — the same one the settings page loads. Every request is read-only; nothing leaves your machine except the call to claude.ai / api.anthropic.com.
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
pyinstaller ClaudeUsageTray.spec
```
