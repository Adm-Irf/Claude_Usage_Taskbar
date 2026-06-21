# Claude Usage Tray

A tiny Windows system-tray app that shows your Claude **Session (5-hour)** and **Weekly** usage at a glance — no browser tab needed.

Click the tray icon → a panel pops up with usage bars, percentages, and reset countdowns. Click anywhere outside → it closes. The tray icon itself is a ring that fills and changes colour (green → amber → red) with your session usage.

![Claude Usage Tray](Pic/Screenshot%202026-06-20%20143944.png)

---

## Download & Install

1. Go to the [**Releases**](../../releases/latest) page and download `ClaudeUsageTray.exe`.
2. Double-click it — a setup window appears.
3. It installs itself to `%LOCALAPPDATA%\Programs\ClaudeUsageTray\`, tests your Claude connection, then launches automatically.
4. Click **Done** and delete the downloaded file.
5. The ring icon appears in your system tray (bottom-right, expand `^` if hidden).

> **Windows SmartScreen warning?** Click **More info → Run anyway**. This is a one-time prompt because the exe is unsigned. Once installed, the app runs without warnings.

> **Antivirus blocking the exe?** If Kaspersky, Defender, or any AV quarantines the file, skip this section and follow the [**Run from source**](#antivirus-blocking-the-exe-run-from-source-instead) guide at the bottom instead.

---

## Authentication

Fully automatic — no setup needed:

1. **Claude Code** — if you have Claude Code installed, the app reads your credentials from `~/.claude/.credentials.json` automatically.
2. **Browser cookie** — otherwise it reads your `sessionKey` cookie from Chrome, Firefox, or Edge. Just be logged in to claude.ai in your browser.

If neither is found, the popup shows an error telling you to log in to claude.ai in your browser, then click **Refresh**.

---

## Storage

| What | Size | Notes |
|---|---|---|
| Installed exe | ~30 MB | `%LOCALAPPDATA%\Programs\ClaudeUsageTray\` |
| Temp files | ~73 MB | While running only — auto-deleted on exit |

No config file. No account data stored on disk.

---

## Start on login

Automatic. On first successful connection the app registers itself to start on Windows login.

---

## Right-click menu

| Option | Description |
|---|---|
| **Refresh** | Fetch usage now (max once per 30s) |
| **Open usage page** | Opens claude.ai/settings/usage |
| **Quit** | Exit the app |

---

## Uninstall

1. Right-click the tray icon → **Quit**
2. Delete `%LOCALAPPDATA%\Programs\ClaudeUsageTray\`
3. Remove the startup entry: Task Manager → **Startup apps** → disable **ClaudeUsageTray**

---

## Notes

- No official API exists for consumer usage limits. This reads the same undocumented endpoint the claude.ai settings page uses. Every request is read-only.
- "Weekly · Opus" only appears if your account reports a separate Opus cap.
- Rate limited? The app backs off automatically and retries when the cooldown expires.

---

## Build from source

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python claude_usage_tray.py
```

To repackage as an exe:

```bash
pip install pyinstaller
pyinstaller ClaudeUsageTray.spec
```

---

## Antivirus blocking the exe? Run from source instead

If your antivirus quarantines or blocks the exe, you can run the app directly from Python. Nothing gets extracted to `%TEMP%`, so AV heuristics don't trigger.

### What you need

- [Python 3.10+](https://www.python.org/downloads/) — tick **"Add Python to PATH"** during install
- [Git](https://git-scm.com/download/win) (or you can download a ZIP instead)
- [VS Code](https://code.visualstudio.com/) (optional, makes it easier)

### Steps

**1. Get the code**

Open **PowerShell** (Win + R → type `powershell` → Enter) and run:

```
git clone https://github.com/Adm-Irf/Claude_Usage_Taskbar.git
cd Claude_Usage_Taskbar
```

Or click the green **Code** button on GitHub → **Download ZIP**, extract it, then `cd` into the folder.

**2. Install dependencies**

In the same PowerShell window (inside the `Claude_Usage_Taskbar` folder):

```
pip install -r requirements.txt
```

**3. Run the app**

```
Start-Process pythonw claude_usage_tray.py
```

The tray icon appears and PowerShell can be closed — the app keeps running independently. (`pythonw` runs without a console window; `Start-Process` detaches it from the terminal.)

**4. Make it start on login**

Paste this into the same PowerShell window (must be inside the `Claude_Usage_Taskbar` folder):

```powershell
$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\ClaudeUsageTray.lnk"); $sc.TargetPath = (Get-Command pythonw).Source; $sc.Arguments = "`"$((Resolve-Path 'claude_usage_tray.py').Path)`""; $sc.WorkingDirectory = $PWD.Path; $sc.Save(); Write-Host "Done — ClaudeUsageTray will start on next login."
```

To undo, delete `ClaudeUsageTray.lnk` from `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.
