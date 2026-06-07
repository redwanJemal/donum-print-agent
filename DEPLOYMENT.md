# Deploying the Print Agent on a new store PC

This is the step-by-step runbook for setting up the agent on a **new till /
store computer** so it **starts automatically at boot — with no one logged in**.

It uses a **SYSTEM scheduled task** (`DonumPrintAgent`, created by
`install-service.ps1`). This is the method validated in production: it survives
an unattended reboot (the original failure mode was a login-only launcher that
never fired when the PC rebooted to the lock screen).

> **One caveat, and step 5 exists to catch it:** a SYSTEM task can only reach the
> printer if the printer's **driver is installed machine-wide** (the usual case
> for a USB ESC/POS driver — e.g. `E-PoS printer driver`). On the rare machine
> where the driver is per-user only, SYSTEM will *connect but not print*. Step 5
> verifies real printing as SYSTEM **before** you rely on it; if it fails, use
> the **login-session fallback** in `README.md` section 5 instead.

Each store is one PC + one printer + its **own** `AGENT_API_KEY`.

---

## 0. Prerequisites (on the new PC)

- Windows, kept powered on during opening hours.
- The thermal printer installed and working over **USB** (print a Windows test
  page first). Note its **exact** name from *Settings → Bluetooth & devices →
  Printers & scanners*.
- **Python 3.10+** — <https://www.python.org/downloads/>, ticking
  **"Add Python to PATH"** during install.
- This repo cloned to a stable path, e.g. `C:\donum-print-agent`.

Do steps 1–5 **as the store's normal user account** (the one that will be logged
in day to day). Where a step needs Administrator it says so.

---

## 1. Install dependencies

```powershell
cd C:\donum-print-agent
pip install -r requirements.txt
```

## 2. Configure `.env`

```powershell
copy .env.example .env      # then edit .env
```

| Setting         | Value for this store                                                   |
| --------------- | --------------------------------------------------------------------- |
| `CLOUD_WS_URL`  | `wss://qms.endlessmaker.com/ws/print`                                  |
| `AGENT_API_KEY` | **This store's own** tenant API key (Donum tenant app → **API Keys**). |
| `PRINTER_NAME`  | The printer's **exact** name (e.g. `E-PoS printer driver`).            |

> Use a **separate API key per store**. The key both authenticates and selects
> which tenant's jobs are pushed here. Never commit a real `.env`.

## 3. Test the printer as yourself (no network)

```powershell
python agent.py --selftest
```

A slip should print. If it does, the printer and `PRINTER_NAME` are correct. If
not, fix `PRINTER_NAME` before continuing.

## 4. Install the boot task (Administrator)

Open PowerShell **as Administrator**, then:

```powershell
cd C:\donum-print-agent
powershell -ExecutionPolicy Bypass -File .\install-service.ps1
```

This registers the `DonumPrintAgent` task: **runs at system startup as SYSTEM**,
single-instance only, auto-restarts on crash, no execution time limit. Answer
**Y** when it offers to start now.

## 5. Verify SYSTEM can actually print  ← do not skip

The agent must print **while running as SYSTEM**, not just as you. Run this in
the **Administrator** PowerShell — a slip should come out:

```powershell
$dir   = (Get-Location).Path
$pyw   = (Get-ScheduledTask DonumPrintAgent).Actions.Execute   # the pythonw path baked into the task
$agent = Join-Path $dir 'agent.py'
Register-ScheduledTask -TaskName DonumSelftest -Force `
  -Action (New-ScheduledTaskAction -Execute $pyw -Argument "`"$agent`" --selftest" -WorkingDirectory $dir) `
  -Principal (New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest) | Out-Null
Start-ScheduledTask DonumSelftest
Start-Sleep 8
"Result code (0 = ok): " + (Get-ScheduledTaskInfo DonumSelftest).LastTaskResult
Unregister-ScheduledTask DonumSelftest -Confirm:$false
Get-Content .\print-agent.log -Tail 3
```

- **Slip prints + result code `0` + log shows `Printed order selftest`** → SYSTEM
  printing works. Continue.
- **No slip** (and/or a `job-selftest.bin` file appears) → this machine's driver
  isn't reachable by SYSTEM. **Uninstall the task** (`.\install-service.ps1
  -Uninstall`) and use the **login-session launcher** in `README.md` section 5
  instead.

## 6. Reboot test

Restart the PC. Without logging in, wait ~30 s, then (after logging in to check):

```powershell
# Exactly ONE agent, started seconds after boot:
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Select ProcessId
Get-Content .\print-agent.log -Tail 6
```

You should see a fresh `=== Donum QMS print agent ===` / `Connected and
authenticated` block timestamped just after boot. Then issue a real token in the
Donum QMS app — it should print **once**.

## 7. Lock down the printer

Do `README.md` **section 4** (USB-only, unshare, don't make it the default) so no
other device on the LAN can print to the receipt roll.

## 8. Make sure only ONE launcher is active

Two agents on the same API key = **every receipt prints twice**. The boot task is
the only launcher you should use. On a fresh PC there's nothing else; if this PC
was previously set up the login way, remove the old launcher:

```powershell
Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'Donum Print Agent.lnk') -ErrorAction SilentlyContinue
```

---

## Day-to-day operations

```powershell
# Health: a new "link alive" line every ~60s means it's connected.
Get-Content C:\donum-print-agent\print-agent.log -Tail 20 -Wait

# Status (Administrator):
Get-ScheduledTask DonumPrintAgent | Select State
Start-ScheduledTask DonumPrintAgent     # start
Stop-ScheduledTask  DonumPrintAgent     # stop
.\install-service.ps1 -Uninstall        # remove the boot task entirely
```

For symptoms (double prints, "permission denied", connects-but-no-print, HTTP
403, etc.) see the **Troubleshooting** table in `README.md` section 7.
