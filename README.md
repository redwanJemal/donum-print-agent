# Donum QMS Print Agent

A small standalone program that prints Donum QMS token receipts on a local
thermal printer.

The Donum QMS backend runs in the cloud and cannot reach a printer sitting on
a store's LAN. This agent solves that: it runs on a PC **at the store**, dials
*out* to the backend over a WebSocket, and holds the connection open. Whenever
a token is issued, the backend pushes the receipt down that socket and the
agent spools it to the printer.

It is fully self-contained — no dependency on the backend codebase. Its only
contract is the WebSocket protocol.

```
  cloud backend  ──push ESC/POS──▶  print agent  ──RAW──▶  thermal printer
                   (WebSocket)        (this app)            (at the store)
```

## Requirements

- A Windows PC at the store, with the thermal printer installed (any 80mm
  ESC/POS printer with a Windows driver).
- **Python 3.10 or newer** — <https://www.python.org/downloads/>
  (during install, tick *"Add Python to PATH"*).

## Setup

```sh
# 1. Get the code
git clone <this-repo-url> donum-print-agent
cd donum-print-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
copy .env.example .env        # then edit .env (see below)
```

Edit `.env`:

| Setting          | What to put                                                        |
| ---------------- | ------------------------------------------------------------------ |
| `CLOUD_WS_URL`   | The backend WebSocket URL, e.g. `wss://api.donum.ae/ws/print`.      |
| `AGENT_API_KEY`  | A tenant API key — create one in the Donum tenant app → API Keys.  |
| `PRINTER_NAME`   | The printer's exact name from *Printers & scanners* (blank = default). |

## Run

**Test the printer first** (no network needed) — this prints a small slip:

```sh
python agent.py --selftest
```

If a slip comes out, the printer and `PRINTER_NAME` are correct. Then start
the agent for real:

```sh
python agent.py
```

Leave this window open — the agent must keep running to receive print jobs.
To print a token, issue one in the Donum QMS app; the receipt prints here.

## Reading the log

The agent logs to the console **and** to `print-agent.log` (rotating). A
healthy run looks like this:

```
2026-05-19 15:00:01  INFO    === Donum QMS print agent ===
2026-05-19 15:00:01  INFO    Server  : wss://api.donum.ae/ws/print
2026-05-19 15:00:01  INFO    Printer : E-PoS printer driver
2026-05-19 15:00:01  INFO    API key : dk_l...9f2a
2026-05-19 15:00:01  INFO    Connecting to wss://api.donum.ae/ws/print ...
2026-05-19 15:00:02  INFO    Connected and authenticated -- waiting for print jobs.
2026-05-19 15:01:02  INFO    link alive -- 0 job(s) printed since start
2026-05-19 15:01:48  INFO    Print job received: order A042.
2026-05-19 15:01:48  INFO    Printed order A042 on 'E-PoS printer driver'.
```

- **`Connected and authenticated`** — the agent is online and ready.
- **`link alive`** — printed every minute; proof the agent is still connected
  and not hung. The count is jobs printed since the agent started.
- **`Print job received` / `Printed order ...`** — a token was printed.

## Troubleshooting

| Log line                              | Meaning / fix                                            |
| -------------------------------------- | -------------------------------------------------------- |
| `AUTHENTICATION FAILED (HTTP 403)`     | `AGENT_API_KEY` is wrong or revoked. Fix `.env`, restart. |
| `Cannot reach the server`              | Wrong `CLOUD_WS_URL`, or no internet / firewall blocking. |
| `DRY RUN (no Windows printer)`         | Running off Windows (or `pywin32` missing). The job is saved as a `.bin` file instead of printed — useful for testing the connection. |
| `Print FAILED for order ...`           | The printer name is wrong, or the printer is offline.     |
| Connection drops, then reconnects      | Normal — the agent reconnects automatically every 5s.     |

## Run it automatically (recommended)

So the agent starts with Windows and restarts if it crashes, use the included
installer script:

```powershell
# Run PowerShell as Administrator, then:
cd C:\Development\ai-builder\donum-print-agent
.\install-service.ps1
```

 Option 1: Bypass for this script only (run in Admin PowerShell):                                                                                                  
  powershell -ExecutionPolicy Bypass -File ".\install-service.ps1"                                                                                                  
                                                                                                                                                                    
  Option 2: Change policy permanently (run in Admin PowerShell):                                                                                                    
  Set-ExecutionPolicy RemoteSigned -Scope CurrentUser                                                                                                               
                                                                                                                                                                    
  Then run the script normally:                                                                                                                                     
  .\install-service.ps1            
  
This creates a Windows Scheduled Task that:
- Starts the agent at system boot (before any user logs in)
- Runs in the background with no console window
- Auto-restarts if the agent crashes

**Commands after installation:**

```powershell
# Start/stop manually
Start-ScheduledTask -TaskName "DonumPrintAgent"
Stop-ScheduledTask -TaskName "DonumPrintAgent"

# Check status
Get-ScheduledTask -TaskName "DonumPrintAgent" | Select-Object State

# View recent logs
Get-Content print-agent.log -Tail 50

# Uninstall
.\install-service.ps1 -Uninstall
```

### Alternative: NSSM

You can also use [NSSM](https://nssm.cc/) to run the agent as a Windows service:

```sh
nssm install DonumPrintAgent "C:\Python\python.exe" "C:\donum-print-agent\agent.py"
nssm set DonumPrintAgent AppDirectory "C:\donum-print-agent"
nssm start DonumPrintAgent
```
