# Claude Usage Tray

A tiny system-tray app. Click the tray icon → a small panel pops up just above
the taskbar showing your Claude **Session (5-hour)** and **Weekly** usage as
bars + percentages, with reset countdowns. Click anywhere outside → it closes.

The tray icon itself is a ring that fills/colours with your current session
usage (green → amber → red), so you get a glance value without even clicking.

---

## Setup

```bash
pip install -r requirements.txt
python claude_usage_tray.py
```

Leave it running; it lives in the tray, not the taskbar buttons. It auto-refreshes
every 5 minutes and whenever you open the panel.

---

## Authentication (one-time)

The app reads the same read-only endpoint the claude.ai settings page uses,
signed in as **you**. It needs your `sessionKey` cookie. Two options:

**Option A — automatic (easiest).** Just stay logged in to claude.ai in Firefox,
Chrome, or Edge. With `browser-cookie3` installed, the app reads the cookie for
you. (Note: recent Chrome versions on Windows encrypt cookies in a way
`browser-cookie3` sometimes can't read — Firefox is the most reliable, or use
Option B.)

**Option B — manual.** Right-click the tray icon → **Open config folder**, edit
`config.json`:

```json
{ "session_key": "sk-ant-sid01-....", "org_id": "" }
```

Get the value: open claude.ai → press **F12** → **Application** tab → **Cookies**
→ `https://claude.ai` → copy the **`sessionKey`** value. Leave `org_id` blank;
the app fills it in automatically. Then right-click → **Refresh**.

Session keys expire periodically — if it stops updating, re-paste a fresh one.

---

## Right-click menu

- **Refresh** – fetch now
- **Open usage page** – opens claude.ai/settings/usage
- **Open config folder** – where `config.json` lives
- **Quit**

---

## Start automatically on Windows login (optional)

Press `Win+R`, type `shell:startup`, Enter. Drop a shortcut in that folder
pointing at:

```
pythonw.exe  "C:\full\path\to\claude_usage_tray.py"
```

(`pythonw.exe` runs it without a console window.)

---

## Package as a single .exe (optional)

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name ClaudeUsageTray claude_usage_tray.py
```

The exe lands in `dist/`. (Bundling browser-cookie3's browser support can be
finicky in PyInstaller; if auto-read breaks in the packaged build, the manual
`config.json` route always works.)

---

## Notes / limitations

- There is **no official API** for consumer session/weekly limits. This uses the
  undocumented `GET /api/organizations/{org_id}/usage` endpoint — the same one
  the settings page loads. Every request is a read-only GET; nothing leaves your
  machine except the call to claude.ai. A future change on Anthropic's side could
  require updating the field names in `_extract()`.
- "Weekly · Opus" only appears if your account reports a separate Opus weekly cap.
- If you only ever use Claude Code (not the web app), the same endpoint still
  reflects your shared plan usage, so this works the same.
