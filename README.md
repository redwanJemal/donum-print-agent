# Donum QMS Print Agent

A small standalone program that prints Donum QMS token receipts on a local
thermal printer.

The Donum QMS backend runs in the cloud and **cannot reach a printer sitting on
a store's LAN** (private IP, behind NAT). This agent solves that: it runs on a
PC **at the store**, dials *out* to the backend over a WebSocket, and holds the
connection open. Whenever a token is issued, the backend pushes the receipt
down that socket and the agent spools it to the printer.

It is fully self-contained — no dependency on the backend codebase. Its only
contract is the WebSocket protocol.

```
  cloud backend  ──push ESC/POS──▶  print agent  ──RAW over USB──▶  thermal printer
                   (WebSocket)        (this app)                    (at the store)
```

> **Why an agent at all?** A browser tab on the SaaS site cannot print to a LAN
> printer directly — browsers can't open raw sockets, block HTTPS→HTTP "mixed
> content", and block public sites from reaching private IPs. And the cloud
> can't reach into your LAN. So a small program that dials *out* from the store
> is required. That program is this agent.

---

## 1. Requirements

- A Windows PC **at the store**, kept powered on while the store is open.
- The thermal printer installed in Windows (any 80mm ESC/POS printer with a
  Windows driver), connected by **USB**.
- **Python 3.10 or newer** — <https://www.python.org/downloads/>
  (during install, tick **"Add Python to PATH"**).

---

## 2. Install

```powershell
# 1. Get the code
git clone <this-repo-url> donum-print-agent
cd donum-print-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
copy .env.example .env        # then edit .env (see below)
```

Edit `.env`:

| Setting          | What to put                                                            |
| ---------------- | ---------------------------------------------------------------------- |
| `CLOUD_WS_URL`   | The backend WebSocket URL — `wss://qms.endlessmaker.com/ws/print`.      |
| `AGENT_API_KEY`  | A tenant API key — create one in the Donum tenant app → **API Keys**.   |
| `PRINTER_NAME`   | The printer's **exact** name from *Printers & scanners* (blank = system default). |

> The `AGENT_API_KEY` both authenticates the agent and tells the backend which
> tenant's jobs to send it. Keep it secret; never commit a real `.env`.

---

## 3. Test the printer (no network needed)

This prints a small slip straight to the printer:

```powershell
python agent.py --selftest
```

If a slip comes out, the printer and `PRINTER_NAME` are correct.

---

## 4. Lock down the printer (important — do this once)

On a shared store/office network, **anything on the LAN can print to an exposed
printer with no password**, so other people's documents end up on your receipt
roll. Close every door so **only this agent** can print to it:

1. **Use USB only — take the printer off the network.** The agent prints over
   USB, so the printer's network side is pure liability. **Unplug its Ethernet
   cable** (or disable Wi-Fi in the printer's menu). This is the single most
   important step — it makes the printer unreachable from any other device.
2. **Don't share it.** *Printer Properties → Sharing →* untick **Share this
   printer**.
3. **Don't make it the default**, and stop Windows auto-switching the default:
   *Settings → Bluetooth & devices → Printers & scanners →* turn **off**
   "Let Windows manage my default printer", then set the default to something
   harmless (e.g. *Microsoft Print to PDF*). The agent prints **by name**, so
   this does not affect it.

PowerShell equivalent for steps 2–3:

```powershell
Set-Printer -Name 'E-PoS printer driver' -Shared $false
Set-ItemProperty 'HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows' -Name LegacyDefaultPrinterMode -Value 1
(Get-CimInstance Win32_Printer -Filter "Name='Microsoft Print to PDF'").SetDefaultPrinter()
```

---

## 5. Run automatically at login (recommended)

> **Do NOT use a SYSTEM service / boot task for a USB receipt printer.** A task
> that runs as `SYSTEM` (session 0) starts *before* you log in and **cannot
> reliably reach a USB printer that lives in your desktop session** — it
> connects but silently fails to print. Run the agent in **your own login
> session** instead, as below. (The old `install-service.ps1` SYSTEM task is
> kept only for reference; see the appendix.)

The repo includes **`run-hidden-forever.vbs`** — it launches the agent with **no
console window** and **auto-restarts** it if it ever exits. Make it start when
you log in by dropping a shortcut into the Startup folder:

```powershell
# Run as your normal user (NOT admin)
$agentDir = (Get-Location).Path                       # run this from the agent folder
$vbs      = Join-Path $agentDir 'run-hidden-forever.vbs'
$lnk      = Join-Path ([Environment]::GetFolderPath('Startup')) 'Donum Print Agent.lnk'

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath       = "$env:WINDIR\System32\wscript.exe"
$sc.Arguments        = "`"$vbs`""
$sc.WorkingDirectory = $agentDir
$sc.WindowStyle      = 7
$sc.Description       = 'Donum QMS Print Agent - hidden, auto-restart, runs at login'
$sc.Save()
"Created: $lnk"
```

To test it immediately without rebooting:

```powershell
Start-Process wscript.exe -ArgumentList '"run-hidden-forever.vbs"'
```

Then **reboot, log in, and verify** (see next section). The agent starts hidden
after you log in — for a store PC that someone logs into each morning, this is
the right trade-off and it actually reaches the printer.

> **Run only ONE launcher.** Don't combine this with the SYSTEM task, the
> `run-forever.bat` console, or `run-hidden.vbs` — two agents on the same API
> key means **every token prints twice**. Pick one (this one).

---

## 6. Verify it's healthy

```powershell
# Exactly ONE agent should be running:
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Select-Object ProcessId, Name

# Watch the live log:
Get-Content print-agent.log -Tail 20 -Wait
```

A healthy run looks like:

```
2026-06-02 20:27:00  INFO    === Donum QMS print agent ===
2026-06-02 20:27:00  INFO    Server  : wss://qms.endlessmaker.com/ws/print
2026-06-02 20:27:00  INFO    Printer : E-PoS printer driver
2026-06-02 20:27:00  INFO    API key : dk_l...wKo7
2026-06-02 20:27:00  INFO    Connecting to wss://qms.endlessmaker.com/ws/print ...
2026-06-02 20:27:02  INFO    Connected and authenticated -- waiting for print jobs.
2026-06-02 20:28:02  INFO    link alive -- 0 job(s) printed since start
2026-06-02 20:28:48  INFO    Print job received: order A042.
2026-06-02 20:28:48  INFO    Printed order A042 on 'E-PoS printer driver'.
```

- **`Connected and authenticated`** — online and ready.
- **`link alive`** — printed every minute; proof it's still connected. The count
  is jobs printed since this agent started.
- **`Print job received` / `Printed order ...`** — a token was printed.

Now issue a token in the Donum QMS app — it should print **once**.

---

## 7. Troubleshooting

| Symptom                                          | Cause / fix                                                                                                                                                  |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **"Permission denied" when printing a token** (in the QMS app; agent log shows *no* "Print job received") | This is an app **permission**, not the printer. Printing needs the `qms.tokens.print` permission. **Owner / Admin / Manager** have it; **Member / Viewer** do not. Give the user a Manager/Admin role, or — if printing via an **API key** (kiosk) — add the `qms.tokens.print` **scope** to that key. |
| **A token prints two or more times**             | More than one agent is running (same API key → each prints). Keep only one launcher. Check: `Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'"` and stop the extras (a reboot clears manual ones). |
| **Other people's documents print on the printer**| The printer is reachable on the LAN and/or shared. Do **section 4** — unplug its network cable, unshare it, remove it as default.                              |
| **Agent connects but nothing prints**            | If it's running as a SYSTEM boot task, it can't reach the USB printer — switch to the **login** method (section 5). Otherwise the printer is offline / wrong `PRINTER_NAME` / out of paper. |
| `AUTHENTICATION FAILED (HTTP 403)`               | `AGENT_API_KEY` is wrong or revoked. Fix `.env`, restart the agent.                                                                                           |
| Can't reach the server                           | Wrong `CLOUD_WS_URL`, or no internet / firewall blocking outbound WSS.                                                                                        |
| `DRY RUN (no Windows printer)`                   | Running off Windows, or `pywin32` missing. The job is saved as a `.bin` file instead of printed — useful for testing the connection only.                     |
| `Print FAILED for order ...`                     | Printer name wrong, printer offline, or (rarely) `pywin32` DLLs not registered — run `python -m pywin32_postinstall -install` once.                            |
| Connection drops, then reconnects                | Normal — the agent reconnects automatically every 5s.                                                                                                         |

---

## Files in this folder

| File                      | Purpose                                                                 |
| ------------------------- | ----------------------------------------------------------------------- |
| `agent.py`                | The agent itself.                                                       |
| `.env` / `.env.example`   | Configuration (URL, API key, printer name).                            |
| `run-hidden-forever.vbs`  | **Recommended** launcher — hidden, auto-restart, runs as you at login.  |
| `run-forever.bat`         | Visible-console launcher with restart loop (manual / debugging).        |
| `run-hidden.vbs`          | Hidden launcher, single-shot (no restart loop).                        |
| `install-service.ps1`     | Appendix only — installs a SYSTEM boot task (**not** advised for USB printers; see section 5). |
| `print-agent.log`         | Rotating log file.                                                      |

---

## Appendix: SYSTEM boot task (not recommended for USB printers)

`install-service.ps1` registers a Scheduled Task that runs as **SYSTEM at boot**.
It is kept for environments where the agent talks to a **networked** printer and
must run with no one logged in. For a **USB** receipt printer it does **not work
reliably** — SYSTEM runs in session 0 and can't reach the printer in your desktop
session (it connects but prints nothing). Prefer the login method in section 5.

```powershell
# Run PowerShell as Administrator:
cd C:\path\to\donum-print-agent
.\install-service.ps1            # or: powershell -ExecutionPolicy Bypass -File .\install-service.ps1
.\install-service.ps1 -Uninstall # remove it
```

If you ever need true "before login" autostart, configure the task to run as the
**store user account** with *"Run whether user is logged on or not"* (stored
password) rather than as `SYSTEM`, so it inherits that user's printer access.
