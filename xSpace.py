#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
"""
xSpace Visual Analyzer  -  WinDirStat-style folder treemap for NAVSL servers.
Python 2.7 + Tkinter. Embeddable in xNAVSL via xnavsl_embed(master).

Every scan uses the same SSH commands on the selected server, regardless of
which machine xSpace is launched from:
  ssh -x navoff1 'df -h'
  ssh -x navoff1 'cd /path && du -sh *'
Ai assisted code by RBolisay
"""
from __future__ import print_function, unicode_literals

import os
import sys
import stat
import socket
import hashlib
import threading
import subprocess
import tempfile
import platform

import Tkinter as tk
import ttk
import tkMessageBox as messagebox

# ---------------------------------------------------------------------------
# NAVSL Blue Aura theme
# ---------------------------------------------------------------------------
GUI_BG = "#B4C8E1"
BTN_BG = "#8DA9CC"
BTN_ACTIVE = "#7C9BCD"
HEADER_FG = "#000033"
TEXT_FG = "#000000"
CANVAS_BG = "#E0EBF5"
ENTRY_BG = "#FFFFFF"
STATUS_FG = "#404040"
TOOLTIP_BG = "#FFFFE0"
TOOLTIP_FG = "#000000"

FONT_MAIN = ("TkDefaultFont", 10)
FONT_BOLD = ("TkDefaultFont", 10, "bold")
FONT_TITLE = ("TkDefaultFont", 12, "bold")
FONT_SMALL = ("TkDefaultFont", 9)

SERVERS = {
    "navoff1":   {"mount": "/aw-navoff1",   "host": "navoff1"},
    "navcon1":   {"mount": "/aw-navcon1",   "host": "navcon1"},
    "navsolve1": {"mount": "/aw-navsolve1", "host": "navsolve1"},
    "navsolve2": {"mount": "/aw-navsolve2", "host": "navsolve2"},
    "storage1":  {"mount": "/aw-storage1",  "host": "storage1"},
}

# SSH login for all NAVSL server commands (ssh -x user@host '...').
SSH_USER = "trinop"
SSH_PASSWORD = "operator"
SSH_TIMEOUT = 20

# WinDirStat-inspired tile palette
TILE_PALETTE = [
    "#4A90D9", "#50C878", "#F5A623", "#D0021B", "#9013FE",
    "#BD10E0", "#7ED321", "#417505", "#F8E71C", "#8B572A",
    "#4A4A4A", "#50E3C2", "#B8E986", "#F5A623", "#D0011B",
    "#6B5B95", "#88B04B", "#FF6F61", "#92A8D1", "#955251",
    "#B565A7", "#009B77", "#DD4124", "#45B8AC", "#EFC050",
    "#5B5EA6", "#9B2335", "#DFCFBE", "#55B4B0", "#E15D44",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def human_size(num_bytes):
    """Format byte count as human-readable string."""
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return "0 B"
    if n < 0:
        n = 0
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while n >= 1024.0 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return "%d %s" % (int(n), units[i])
    return "%.2f %s" % (n, units[i])


def parse_human_size(size_str):
    """Parse human size strings from df -h / du -sh (e.g. 1.2G, 500M, 12K)."""
    if not size_str or size_str.strip() in ("-", "0", "0B"):
        return 0
    s = size_str.strip().upper().rstrip("B").strip()
    units = [
        ("PI", 1024 ** 5), ("P", 1024 ** 5),
        ("TI", 1024 ** 4), ("T", 1024 ** 4),
        ("GI", 1024 ** 3), ("G", 1024 ** 3),
        ("MI", 1024 ** 2), ("M", 1024 ** 2),
        ("KI", 1024), ("K", 1024),
    ]
    for suffix, mult in units:
        if s.endswith(suffix):
            try:
                return int(float(s[:-len(suffix)].strip()) * mult)
            except ValueError:
                return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def tile_color(name, index):
    """Deterministic color from folder name and position."""
    if name.startswith("."):
        return "#A0A0A0"
    h = int(hashlib.md5(name.encode("utf-8", errors="replace")).hexdigest()[:6], 16)
    return TILE_PALETTE[(index + h) % len(TILE_PALETTE)]


def is_local_host(host):
    h = (host or "").strip().lower()
    if h in ("localhost", "127.0.0.1", "::1", "lo"):
        return True
    try:
        hn = socket.gethostname().lower()
        fqdn = socket.getfqdn().lower()
        short = hn.split(".")[0]
        for name in (hn, fqdn, short):
            if not name:
                continue
            if h == name:
                return True
            # navoff1 config vs aw-navoff1 hostname (and reverse).
            if name == "aw-%s" % h or h == "aw-%s" % name:
                return True
    except Exception:
        pass
    return False


def _find_sshpass_bin():
    """Locate sshpass binary (GUI apps often have a minimal PATH)."""
    seen = set()
    candidates = ["sshpass"]
    path_env = os.environ.get("PATH", "")
    for d in path_env.split(os.pathsep) + ["/usr/bin", "/bin", "/usr/local/bin"]:
        if d:
            candidates.append(os.path.join(d, "sshpass"))
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _make_askpass_script(password):
    safe = password.replace("\\", "\\\\").replace("'", "'\\''")
    script = "#!/bin/sh\nexec printf '%s' '{}'\n".format(safe)
    fd, path = tempfile.mkstemp(suffix=".sh", prefix="xspace_")
    try:
        os.write(fd, script.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRWXU)
    return path


def _password_ssh_opts():
    """Force password auth without an interactive terminal prompt."""
    return [
        "-o", "PubkeyAuthentication=no",
        "-o", "PreferredAuthentications=keyboard-interactive,password",
        "-o", "PasswordAuthentication=yes",
        "-o", "BatchMode=no",
        "-o", "NumberOfPasswordPrompts=1",
        "-n",
    ]


def _ssh_target(host, user=None):
    """Build ssh destination: navoff1 or user@navoff1."""
    host = (host or "").strip()
    u = SSH_USER if user is None else user
    if u:
        return "%s@%s" % (u, host)
    return host


def ssh_command_display(host, command):
    """Human-readable equivalent of the remote command."""
    target = _ssh_target(host)
    return "ssh -x %s '%s'" % (target, command.replace("'", "'\\''"))


def run_remote_command(host, command, user=None, password=None, key_file="", force_ssh=False):
    """Run command on host. Production scans always pass force_ssh=True."""
    if user is None:
        user = SSH_USER
    if password is None:
        password = SSH_PASSWORD
    if is_local_host(host) and not force_ssh:
        # Already logged in on this server (ssh -X navoff1); run directly — no self-ssh auth.
        try:
            proc = subprocess.Popen(
                command, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = proc.communicate()
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            if isinstance(err, bytes):
                err = err.decode("utf-8", errors="replace")
            return out, err, proc.returncode
        except Exception as e:
            return "", str(e), 1

    target = _ssh_target(host, user)
    common = [
        "-x",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=%d" % SSH_TIMEOUT,
        "-o", "LogLevel=ERROR",
    ]
    askpass_path = None
    env = os.environ.copy()
    devnull = None
    try:
        if key_file and os.path.isfile(key_file):
            cmd = (["ssh"] + common +
                   ["-o", "BatchMode=yes", "-i", key_file,
                    target, command])
        elif password:
            pwd_opts = _password_ssh_opts()
            sshpass_bin = _find_sshpass_bin()
            if sshpass_bin:
                cmd = ([sshpass_bin, "-p", password, "ssh"] + common +
                       pwd_opts + [target, command])
            else:
                askpass_path = _make_askpass_script(password)
                env["SSH_ASKPASS"] = askpass_path
                env["SSH_ASKPASS_REQUIRE"] = "force"
                env["DISPLAY"] = env.get("DISPLAY") or ":0"
                cmd = (["ssh"] + common + pwd_opts + [target, command])
        else:
            cmd = (["ssh"] + common + [target, command])

        pop_kw = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
        }
        devnull = open(os.devnull, "r")
        pop_kw["stdin"] = devnull
        if hasattr(os, "setsid"):
            pop_kw["preexec_fn"] = os.setsid

        proc = subprocess.Popen(cmd, **pop_kw)
        out, err = proc.communicate()
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        if password and proc.returncode != 0 and not out.strip():
            if not _find_sshpass_bin():
                hint = (
                    "SSH password auth failed (sshpass not found). "
                    "Install: yum install sshpass")
                err = (err.strip() + "\n" + hint).strip()
        return out, err, proc.returncode
    except Exception as e:
        return "", str(e), 1
    finally:
        if devnull is not None:
            try:
                devnull.close()
            except Exception:
                pass
        if askpass_path and os.path.exists(askpass_path):
            try:
                os.unlink(askpass_path)
            except Exception:
                pass


def parse_du_sh_output(raw, parent_path):
    """Parse du -sh * output lines into entry dicts."""
    entries = []
    parent_path = os.path.normpath(parent_path or "/")
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        size_bytes = parse_human_size(parts[0])
        name = parts[1].strip()
        if not name or name in (".", ".."):
            continue
        child_path = os.path.normpath(os.path.join(parent_path, name))
        entries.append({
            "name": name,
            "path": child_path,
            "size": max(size_bytes, 1),
            "is_dir": True,
        })
    entries.sort(key=lambda e: e["size"], reverse=True)
    return entries


def _du_sh_shell_cmd(directory):
    """cd into directory and run du -sh * (one-level folder sizes)."""
    quoted = directory.replace("'", "'\\''")
    return "cd '%s' && du -sh *" % quoted


def _df_h_shell_cmd():
    """Root view: df -h on the selected server."""
    return "df -h"


# Skip ephemeral filesystems in df -h root tiles.
_DF_SKIP_FS_PREFIXES = ("tmpfs", "devtmpfs", "overlay", "squashfs", "efivarfs")


def scan_df_h_overview(host):
    """Scan root via df -h; tile size = Used space on each mount."""
    cmd = _df_h_shell_cmd()
    out, err, rc = run_remote_command(host, cmd, force_ssh=True)
    merged = _merge_df_lines(out)
    entries = []
    for line in merged:
        stats = _parse_df_line(line)
        if not stats:
            continue
        fs = stats.get("filesystem", "")
        if any(fs.startswith(p) for p in _DF_SKIP_FS_PREFIXES):
            continue
        mounted = stats.get("mounted", "")
        if not mounted:
            continue
        used_bytes = parse_human_size(stats.get("used", "0"))
        if used_bytes <= 0:
            used_bytes = 1
        name = os.path.basename(mounted.rstrip("/")) or mounted
        entries.append({
            "name": name,
            "path": mounted,
            "size": used_bytes,
            "is_dir": True,
        })
    entries.sort(key=lambda e: e["size"], reverse=True)
    if entries:
        return entries, ""
    err_msg = (err or "").strip()
    if err_msg:
        if "permission denied" in err_msg.lower() and "publickey" in err_msg.lower():
            err_msg = (
                "%s — try: ssh %s true  (load key: ssh-add -l)"
                % (err_msg, host))
        return [], err_msg
    return [], "df -h returned no data (check: %s)" % ssh_command_display(host, _df_h_shell_cmd())


def scan_remote_du(host, directory):
    """Scan remote directory via SSH — cd && du -sh *."""
    cmd = _du_sh_shell_cmd(directory)
    out, err, rc = run_remote_command(host, cmd, force_ssh=True)
    if out.strip():
        entries = parse_du_sh_output(out, directory)
        if entries:
            return entries, ""
    err_msg = (err or "").strip()
    if err_msg:
        if "permission denied" in err_msg.lower() and "publickey" in err_msg.lower():
            err_msg = (
                "%s — try: ssh %s true  (load key: ssh-add -l)"
                % (err_msg, host))
        return [], err_msg
    return [], "Remote scan returned no data (check: %s)" % (
        ssh_command_display(host, _du_sh_shell_cmd(directory)))


def scan_directory(server_key, directory):
    """Always scan via SSH on the selected server (same on every machine)."""
    cfg = SERVERS.get(server_key, {})
    host = cfg.get("host", server_key)
    directory = os.path.normpath((directory or "/").strip())
    if directory == "/":
        return scan_df_h_overview(host)
    return scan_remote_du(host, directory)


def remote_list_directory(host, directory):
    """List one directory level on the selected server via SSH ls -1F."""
    directory = os.path.normpath(directory or "/")
    quoted = directory.replace("'", "'\\''")
    if directory == "/":
        cmd = "ls -1F /"
    else:
        cmd = "ls -1F '%s'" % quoted
    out, err, rc = run_remote_command(host, cmd, force_ssh=True)
    entries = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line in (".", ".."):
            continue
        if line.endswith("/"):
            name = line[:-1].rstrip()
            is_dir = True
        elif line.endswith("@"):
            name = line[:-1]
            is_dir = True
        elif line.endswith("*"):
            name = line[:-1]
            is_dir = False
        else:
            name = line
            is_dir = False
        if not name:
            continue
        if directory == "/":
            full = "/" + name
        else:
            full = os.path.normpath(os.path.join(directory, name))
        entries.append({"name": name, "path": full, "is_dir": is_dir})
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return entries, (err or "").strip()


def _parse_df_line(line):
    """Parse one df -h data line into a stats dict."""
    parts = line.split()
    if len(parts) < 6:
        return None
    use_pct_str = parts[4].rstrip("%")
    try:
        use_pct = float(use_pct_str)
    except ValueError:
        use_pct = 0.0
    mounted = parts[5] if len(parts) == 6 else " ".join(parts[5:])
    return {
        "filesystem": parts[0],
        "size": parts[1],
        "used": parts[2],
        "avail": parts[3],
        "use_pct": use_pct,
        "remain_pct": max(0.0, 100.0 - use_pct),
        "mounted": mounted,
    }


def _merge_df_lines(raw):
    """Merge wrapped df -h lines (long mount paths)."""
    lines = [l for l in raw.strip().splitlines() if l.strip()]
    if not lines:
        return []
    data_lines = [l for l in lines if not l.startswith("Filesystem")]
    merged = []
    buf = ""
    for line in data_lines:
        parts = line.split()
        if not parts:
            continue
        if len(parts) == 1:
            buf = line
        elif buf:
            merged.append(buf + " " + line)
            buf = ""
        else:
            merged.append(line)
    if buf:
        merged.append(buf)
    return merged


def fetch_filesystem_stats(server_key, path):
    """
    df -h for the filesystem holding path on the selected server (always SSH).
    Returns stats dict or None.
    """
    cfg = SERVERS.get(server_key, {})
    host = cfg.get("host", server_key)
    path = os.path.normpath((path or "/").strip())

    quoted = path.replace("'", "'\\''")
    cmd = "df -h '%s'" % quoted

    out, err, rc = run_remote_command(host, cmd, force_ssh=True)

    merged = _merge_df_lines(out)
    if not merged:
        return None
    return _parse_df_line(merged[-1])


def format_fs_stats_line(stats):
    """One-line summary of filesystem used / remaining."""
    if not stats:
        return "Disk: stats unavailable for this path"
    return (
        "Disk on %s  |  Used: %.0f%% (%s)  |  Remaining: %.0f%% (%s)  |  Total: %s"
        % (
            stats.get("mounted", "?"),
            stats.get("use_pct", 0),
            stats.get("used", "?"),
            stats.get("remain_pct", 0),
            stats.get("avail", "?"),
            stats.get("size", "?"),
        )
    )


def open_system_explorer(path):
    """Open path in OS file manager."""
    if not path or not os.path.exists(path):
        messagebox.showwarning(
            "Browse Directory",
            "Path not accessible locally:\n%s\n\n"
            "Mount the server share or browse from a machine with access."
            % path,
            parent=None)
        return
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)  # noqa: F821 — Windows only
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Browse Directory", str(e))


# ---------------------------------------------------------------------------
# Treemap layout (recursive proportional split)
# ---------------------------------------------------------------------------
def layout_treemap(items, rect):
    """Lay out items in rect; returns [(item, (x1,y1,x2,y2)), ...]."""
    x, y, x2, y2 = rect
    w = x2 - x
    h = y2 - y
    if not items or w <= 1 or h <= 1:
        return []
    if len(items) == 1:
        return [(items[0], rect)]

    total = sum(max(float(it.get("size", 1)), 1.0) for it in items)
    horizontal = w >= h
    mid = max(1, len(items) // 2)
    left = items[:mid]
    right = items[mid:]
    left_sum = sum(max(float(it.get("size", 1)), 1.0) for it in left)
    ratio = left_sum / total if total > 0 else 0.5

    if horizontal:
        split = w * ratio
        r1 = (x, y, x + split, y2)
        r2 = (x + split, y, x2, y2)
    else:
        split = h * ratio
        r1 = (x, y, x2, y + split)
        r2 = (x, y + split, x2, y2)

    return layout_treemap(left, r1) + layout_treemap(right, r2)


# ---------------------------------------------------------------------------
# File explorer popup (non-modal, single instance)
# ---------------------------------------------------------------------------
class FileExplorerPopup(object):
    _instance = None

    @classmethod
    def show(cls, master, path, title="Browse Directory"):
        if cls._instance is not None:
            try:
                if cls._instance.win.winfo_exists():
                    cls._instance.refresh(path, title)
                    cls._instance.win.deiconify()
                    cls._instance.win.lift()
                    cls._instance.win.focus_force()
                    return cls._instance
            except tk.TclError:
                cls._instance = None
        cls._instance = cls(master, path, title)
        return cls._instance

    def __init__(self, master, path, title):
        self.master = master
        self.path = path
        self.win = tk.Toplevel(master)
        self.win.title(title)
        self.win.configure(bg=GUI_BG)
        self.win.geometry("720x480")
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        hdr = tk.Frame(self.win, bg=GUI_BG)
        hdr.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(
            hdr, text=path, bg=GUI_BG, fg=HEADER_FG,
            font=FONT_SMALL, anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        btn_row = tk.Frame(self.win, bg=GUI_BG)
        btn_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Button(
            btn_row, text="Up", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=self._go_up,
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            btn_row, text="Refresh", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=lambda: self.refresh(self.path, self.win.title()),
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            btn_row, text="Open in OS", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=lambda: open_system_explorer(self.path),
        ).pack(side=tk.LEFT, padx=2)

        tree_frame = tk.Frame(self.win, bg=GUI_BG)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        cols = ("name", "type", "size")
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("size", text="Size")
        self.tree.column("name", width=360, stretch=True)
        self.tree.column("type", width=80, stretch=False)
        self.tree.column("size", width=120, stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_double)
        self.status = tk.Label(
            self.win, text="", bg=GUI_BG, fg=STATUS_FG, font=FONT_SMALL, anchor="w")
        self.status.pack(fill=tk.X, padx=8, pady=4)

        self._populate()

    def _on_close(self):
        FileExplorerPopup._instance = None
        self.win.destroy()

    def refresh(self, path, title):
        self.path = path
        self.win.title(title)
        self._populate()

    def _go_up(self):
        parent = os.path.dirname(self.path.rstrip("/\\"))
        if parent and parent != self.path:
            self.refresh(parent, "Browse: %s" % parent)

    def _populate(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if not os.path.isdir(self.path):
            self.status.config(text="Path not accessible locally.")
            return
        try:
            names = sorted(os.listdir(self.path))
        except OSError as e:
            self.status.config(text="Error: %s" % e)
            return
        dirs = []
        files = []
        for name in names:
            full = os.path.join(self.path, name)
            try:
                if os.path.isdir(full):
                    dirs.append((name, full, "Folder", ""))
                else:
                    sz = os.path.getsize(full)
                    files.append((name, full, "File", human_size(sz)))
            except OSError:
                continue
        count = 0
        for name, full, typ, sz in dirs + files:
            self.tree.insert("", tk.END, values=(name, typ, sz), tags=(full,))
            count += 1
        self.status.config(text="%d items in %s" % (count, self.path))

    def _on_double(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return
        name = vals[0]
        full = os.path.join(self.path, name)
        if os.path.isdir(full):
            self.refresh(full, "Browse: %s" % full)


# ---------------------------------------------------------------------------
# Visualize Folder picker (non-modal, single instance, themed)
# ---------------------------------------------------------------------------
class VisualizeFolderPopup(object):
    _instance = None

    @classmethod
    def show(cls, master, server_key, host, initial_path, on_select):
        if cls._instance is not None:
            try:
                if cls._instance.win.winfo_exists():
                    cls._instance.reopen(server_key, host, initial_path, on_select)
                    cls._instance.win.deiconify()
                    cls._instance.win.lift()
                    cls._instance.win.focus_force()
                    return cls._instance
            except tk.TclError:
                cls._instance = None
        cls._instance = cls(master, server_key, host, initial_path, on_select)
        return cls._instance

    def __init__(self, master, server_key, host, initial_path, on_select):
        self.master = master
        self.server_key = server_key
        self.host = host
        self.on_select = on_select
        self.path = os.path.normpath(initial_path or "/")
        self._list_token = 0

        self.win = tk.Toplevel(master)
        self.win.title("Visualize Folder — %s" % server_key)
        self.win.configure(bg=GUI_BG)
        self.win.geometry("760x520")
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        hdr = tk.Frame(self.win, bg=GUI_BG)
        hdr.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(
            hdr, text="Server:", bg=GUI_BG, fg=TEXT_FG, font=FONT_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            hdr, text=server_key, bg=GUI_BG, fg=HEADER_FG, font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=(4, 12))
        tk.Label(
            hdr, text="Path:", bg=GUI_BG, fg=TEXT_FG, font=FONT_MAIN,
        ).pack(side=tk.LEFT)
        self.path_label = tk.Label(
            hdr, text=self.path, bg=GUI_BG, fg=HEADER_FG,
            font=FONT_SMALL, anchor="w",
        )
        self.path_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        btn_row = tk.Frame(self.win, bg=GUI_BG)
        btn_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Button(
            btn_row, text="Up", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=self._go_up,
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            btn_row, text="Refresh", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=self._populate,
        ).pack(side=tk.LEFT, padx=2)

        tree_frame = tk.Frame(self.win, bg=GUI_BG)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        style = ttk.Style(self.win)
        try:
            style.configure(
                "XSpace.Treeview",
                background=ENTRY_BG,
                fieldbackground=ENTRY_BG,
                foreground=TEXT_FG,
                font=FONT_SMALL,
            )
            style.configure(
                "XSpace.Treeview.Heading",
                background=BTN_BG,
                foreground=HEADER_FG,
                font=FONT_BOLD,
            )
        except tk.TclError:
            pass

        cols = ("name", "type")
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            selectmode="browse", style="XSpace.Treeview")
        self.tree.heading("name", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.column("name", width=520, stretch=True)
        self.tree.column("type", width=100, stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Return>", self._on_enter_folder)

        foot = tk.Frame(self.win, bg=GUI_BG)
        foot.pack(fill=tk.X, padx=8, pady=(4, 8))
        self.status = tk.Label(
            foot, text="", bg=GUI_BG, fg=STATUS_FG, font=FONT_SMALL, anchor="w")
        self.status.pack(fill=tk.X, pady=(0, 6))

        btn_row2 = tk.Frame(foot, bg=GUI_BG)
        btn_row2.pack(fill=tk.X)
        tk.Button(
            btn_row2, text="Visualize This Folder", bg=BTN_BG,
            activebackground=BTN_ACTIVE, font=FONT_BOLD,
            command=self._visualize_current,
        ).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(
            btn_row2, text="Cancel", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=self._on_close,
        ).pack(side=tk.RIGHT)

        self._populate()

    def reopen(self, server_key, host, initial_path, on_select):
        self.server_key = server_key
        self.host = host
        self.on_select = on_select
        self.path = os.path.normpath(initial_path or "/")
        self.win.title("Visualize Folder — %s" % server_key)
        self.path_label.config(text=self.path)
        self._populate()

    def _on_close(self):
        VisualizeFolderPopup._instance = None
        self.win.destroy()

    def _go_up(self):
        if self.path == "/":
            return
        parent = os.path.dirname(self.path.rstrip("/"))
        if not parent:
            parent = "/"
        if parent == self.path:
            return
        self.path = parent
        self.path_label.config(text=self.path)
        self._populate()

    def _populate(self):
        self._list_token += 1
        token = self._list_token
        self.status.config(
            text="Loading %s ..." % ssh_command_display(
                self.host, "ls -1F '%s'" % self.path.replace("'", "'\\''")))
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        def worker():
            entries, err = remote_list_directory(self.host, self.path)
            self.win.after(0, lambda: self._apply_list(token, entries, err))

        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()

    def _apply_list(self, token, entries, err):
        if token != self._list_token:
            return
        if err and not entries:
            self.status.config(text="Error: %s" % err)
            return
        count = 0
        for ent in entries:
            typ = "Folder" if ent.get("is_dir") else "File"
            self.tree.insert(
                "", tk.END,
                values=(ent.get("name", ""), typ),
                tags=(ent.get("path", ""),),
            )
            count += 1
        self.status.config(
            text="%d items  |  double-click folder to open  |  %s"
            % (count, self.path))

    def _selected_path(self):
        sel = self.tree.selection()
        if not sel:
            return None
        tags = self.tree.item(sel[0], "tags")
        if tags:
            return tags[0]
        vals = self.tree.item(sel[0], "values")
        if vals:
            return os.path.normpath(os.path.join(self.path, vals[0]))
        return None

    def _on_double(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals or vals[1] != "Folder":
            return
        tags = self.tree.item(sel[0], "tags")
        if tags:
            self.path = tags[0]
        else:
            self.path = os.path.normpath(os.path.join(self.path, vals[0]))
        self.path_label.config(text=self.path)
        self._populate()

    def _on_enter_folder(self, event):
        self._on_double(event)

    def _visualize_current(self):
        if callable(self.on_select):
            self.on_select(self.path)
        self._on_close()


# ---------------------------------------------------------------------------
# Treemap canvas
# ---------------------------------------------------------------------------
class TreemapCanvas(tk.Canvas):
    MIN_TILE = 6

    def __init__(self, master, on_enter_dir=None, on_context=None, **kw):
        kw.setdefault("bg", CANVAS_BG)
        kw.setdefault("highlightthickness", 0)
        tk.Canvas.__init__(self, master, **kw)
        self.on_enter_dir = on_enter_dir
        self.on_context = on_context
        self._tiles = []
        self._tooltip = None
        self._tooltip_after = None

        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._hide_tooltip)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Button-3>", self._on_right)
        if sys.platform == "darwin":
            self.bind("<Button-2>", self._on_right)

    def set_entries(self, entries):
        self._entries = entries
        self._redraw()

    def _on_configure(self, event):
        self._redraw()

    def _redraw(self):
        self.delete("all")
        self._tiles = []
        entries = getattr(self, "_entries", [])
        if not entries:
            self.create_text(
                self.winfo_width() // 2, self.winfo_height() // 2,
                text="No folders to display", fill=STATUS_FG, font=FONT_MAIN)
            return

        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            return

        total = sum(max(e.get("size", 0), 1) for e in entries)
        if total <= 0:
            return

        pad = 2
        layout = layout_treemap(entries, (pad, pad, w - pad, h - pad))
        for i, (item, bbox) in enumerate(layout):
            x1, y1, x2, y2 = bbox
            tw = x2 - x1
            th = y2 - y1
            if tw < self.MIN_TILE or th < self.MIN_TILE:
                continue
            color = tile_color(item.get("name", ""), i)
            tag = "tile_%d" % i
            self.create_rectangle(
                x1, y1, x2, y2,
                fill=color, outline="#FFFFFF", width=1, tags=(tag, "tile"))
            name = item.get("name", "")
            sz = human_size(item.get("size", 0))
            fg = "#000000" if _is_light(color) else "#FFFFFF"
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            if tw > 45 and th > 32:
                label = "%s\n%s" % (name, sz)
            elif tw > 28 and th > 18:
                label = sz
            else:
                label = ""
            if label:
                self.create_text(
                    cx, cy, text=label, fill=fg,
                    font=FONT_SMALL, width=max(int(tw - 4), 1),
                    tags=(tag, "tile"))
            self._tiles.append({
                "item": item,
                "bbox": (x1, y1, x2, y2),
                "tag": tag,
            })

    def _hit_test(self, x, y):
        for t in self._tiles:
            x1, y1, x2, y2 = t["bbox"]
            if x1 <= x <= x2 and y1 <= y <= y2:
                return t
        return None

    def _on_motion(self, event):
        t = self._hit_test(event.x, event.y)
        if t is None:
            self._hide_tooltip()
            self.config(cursor="")
            return
        self.config(cursor="hand2")
        item = t["item"]
        text = "%s\n%s" % (
            item.get("path", item.get("name", "")),
            human_size(item.get("size", 0)),
        )
        self._show_tooltip(event.x_root, event.y_root, text)

    def _show_tooltip(self, x, y, text):
        if self._tooltip_after:
            self.after_cancel(self._tooltip_after)
        self._tooltip_after = self.after(120, lambda: self._do_tooltip(x, y, text))

    def _do_tooltip(self, x, y, text):
        self._hide_tooltip()
        self._tooltip = tk.Toplevel(self)
        self._tooltip.wm_overrideredirect(True)
        self._tooltip.configure(bg=TOOLTIP_BG)
        lbl = tk.Label(
            self._tooltip, text=text, bg=TOOLTIP_BG, fg=TOOLTIP_FG,
            font=FONT_SMALL, justify=tk.LEFT, padx=6, pady=4)
        lbl.pack()
        self._tooltip.geometry("+{}+{}".format(x + 12, y + 12))

    def _hide_tooltip(self, event=None):
        if self._tooltip_after:
            try:
                self.after_cancel(self._tooltip_after)
            except Exception:
                pass
            self._tooltip_after = None
        if self._tooltip is not None:
            try:
                self._tooltip.destroy()
            except Exception:
                pass
            self._tooltip = None

    def _on_click(self, event):
        t = self._hit_test(event.x, event.y)
        if t is None:
            return
        item = t["item"]
        if item.get("is_dir") and callable(self.on_enter_dir):
            self.on_enter_dir(item)

    def _on_right(self, event):
        t = self._hit_test(event.x, event.y)
        if t is None:
            return
        if callable(self.on_context):
            self.on_context(event, t["item"])


def _is_light(hex_color):
    try:
        c = hex_color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return lum > 140
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------
class XSpacePanel(tk.Frame):
    def __init__(self, master, geometry_save_widget=None):
        tk.Frame.__init__(self, master, bg=GUI_BG)
        self._geometry_save_widget = geometry_save_widget
        self._scan_thread = None
        self._scan_token = 0
        self._nav_stack = []

        self.server_var = tk.StringVar(value="navoff1")
        self.path_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready")
        self.fs_stats_var = tk.StringVar(value="")

        self._build_ui()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.after(200, self._initial_scan)

    def _build_ui(self):
        title_row = tk.Frame(self, bg=GUI_BG)
        title_row.pack(fill=tk.X, padx=10, pady=(8, 4))
        tk.Label(
            title_row, text="xSpace Visual Analyzer",
            bg=GUI_BG, fg=HEADER_FG, font=FONT_TITLE,
        ).pack(side=tk.LEFT)

        ctrl = tk.Frame(self, bg=GUI_BG)
        ctrl.pack(fill=tk.X, padx=10, pady=4)

        tk.Label(ctrl, text="Server:", bg=GUI_BG, fg=TEXT_FG, font=FONT_MAIN).pack(
            side=tk.LEFT, padx=(0, 4))
        self.server_combo = ttk.Combobox(
            ctrl, textvariable=self.server_var,
            values=sorted(SERVERS.keys()), state="readonly", width=12)
        self.server_combo.pack(side=tk.LEFT, padx=(0, 12))
        self.server_combo.bind("<<ComboboxSelected>>", lambda e: self._on_server_change())

        tk.Button(
            ctrl, text="Scan Root", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=self._scan_root,
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            ctrl, text="Up", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=self._go_up,
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            ctrl, text="Rescan", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=self._rescan_current,
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            ctrl, text="Visualize Folder", bg=BTN_BG, activebackground=BTN_ACTIVE,
            command=self._pick_folder,
        ).pack(side=tk.LEFT, padx=2)

        path_row = tk.Frame(self, bg=GUI_BG)
        path_row.pack(fill=tk.X, padx=10, pady=(0, 4))
        tk.Label(path_row, text="Path:", bg=GUI_BG, fg=TEXT_FG, font=FONT_MAIN).pack(
            side=tk.LEFT)
        self.path_entry = tk.Entry(
            path_row, textvariable=self.path_var, bg=ENTRY_BG, fg=TEXT_FG,
            font=FONT_SMALL)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        tk.Button(
            path_row, text="Go", bg=BTN_BG, activebackground=BTN_ACTIVE,
            width=4, command=self._go_path,
        ).pack(side=tk.LEFT)

        self.canvas = TreemapCanvas(
            self,
            on_enter_dir=self._enter_directory,
            on_context=self._show_context_menu,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        status_row = tk.Frame(self, bg=GUI_BG)
        status_row.pack(fill=tk.X, padx=10, pady=(0, 2))
        tk.Label(
            status_row, textvariable=self.status_var,
            bg=GUI_BG, fg=STATUS_FG, font=FONT_SMALL, anchor="w",
        ).pack(fill=tk.X)

        fs_row = tk.Frame(self, bg=GUI_BG)
        fs_row.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Label(
            fs_row, textvariable=self.fs_stats_var,
            bg=GUI_BG, fg=HEADER_FG, font=FONT_BOLD, anchor="w",
        ).pack(fill=tk.X)

    def _server_root(self):
        """Root view: df -h filesystem overview."""
        return "/"

    def _initial_scan(self):
        root = self._server_root()
        self.path_var.set(root)
        self._nav_stack = [root]
        self._start_scan(root)

    def _on_server_change(self):
        self._nav_stack = []
        self._scan_root()

    def _scan_root(self):
        root = self._server_root()
        self.path_var.set(root)
        self._nav_stack = [root]
        self._start_scan(root)

    def _go_up(self):
        cur = os.path.normpath(self.path_var.get().strip() or self._server_root())
        if cur == "/":
            return
        parent = os.path.dirname(cur.rstrip("/"))
        if not parent:
            parent = "/"
        if parent == cur:
            return
        self.path_var.set(parent)
        if self._nav_stack and self._nav_stack[-1] == cur:
            self._nav_stack.pop()
        if not self._nav_stack or self._nav_stack[-1] != parent:
            self._nav_stack.append(parent)
        self._start_scan(parent)

    def _go_path(self):
        path = self.path_var.get().strip()
        if path:
            self._nav_stack.append(path)
            self._start_scan(path)

    def _default_server_path(self):
        """Default directory path for the selected server (server-side)."""
        path = self.path_var.get().strip()
        if path and path != "/":
            return path
        key = self.server_var.get()
        cfg = SERVERS.get(key, {})
        return cfg.get("mount", "/")

    def _pick_folder(self):
        """Browse directories on the selected server, then visualize with du -sh *."""
        server = self.server_var.get()
        cfg = SERVERS.get(server, {})
        host = cfg.get("host", server)
        initial = self._default_server_path()

        def on_select(path):
            path = os.path.normpath(path.strip())
            if not path:
                return
            self.path_var.set(path)
            self._nav_stack.append(path)
            self._start_scan(path)

        VisualizeFolderPopup.show(
            self.winfo_toplevel(), server, host, initial, on_select)

    def _rescan_current(self):
        path = self.path_var.get().strip()
        if path:
            self._start_scan(path)

    def _enter_directory(self, item):
        path = item.get("path", "")
        if not path or not item.get("is_dir"):
            return
        self.path_var.set(path)
        self._nav_stack.append(path)
        self._start_scan(path)

    def _start_scan(self, path):
        self._scan_token += 1
        token = self._scan_token
        server = self.server_var.get()
        cfg = SERVERS.get(server, {})
        host = cfg.get("host", server)
        path = os.path.normpath((path or self._server_root()).strip())
        self.path_var.set(path)
        if path == "/":
            self.status_var.set(
                "Running %s ..." % ssh_command_display(host, _df_h_shell_cmd()))
        else:
            self.status_var.set(
                "Running %s ..."
                % ssh_command_display(host, _du_sh_shell_cmd(path)))
        self.fs_stats_var.set("")
        self.canvas.set_entries([])

        def worker():
            entries, scan_err = scan_directory(server, path)
            total = sum(e.get("size", 0) for e in entries)
            fs_stats = fetch_filesystem_stats(server, path)
            self.after(0, lambda: self._apply_scan(
                token, path, entries, total, fs_stats, scan_err, host))

        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        self._scan_thread = t

    def _apply_scan(self, token, path, entries, total, fs_stats, scan_err="", host=""):
        if token != self._scan_token:
            return
        self.canvas.delete("scanning")
        self.fs_stats_var.set(format_fs_stats_line(fs_stats))
        if not entries:
            self.canvas.set_entries([])
            if scan_err:
                self.status_var.set(scan_err)
            elif path == "/":
                self.status_var.set(
                    "No df -h data from %s"
                    % ssh_command_display(host, _df_h_shell_cmd()))
            else:
                self.status_var.set(
                    "No du output from %s"
                    % ssh_command_display(host, _du_sh_shell_cmd(path)))
            return
        self.canvas.set_entries(entries)
        self.status_var.set(
            "%d items  |  Folder total: %s  |  %s" % (
                len(entries), human_size(total), path))

    def _show_context_menu(self, event, item):
        menu = tk.Menu(self, tearoff=0, bg=GUI_BG, fg=TEXT_FG)

        menu.add_command(
            label="Rescan",
            command=lambda: self._rescan_item(item))
        menu.add_command(
            label="Browse Directory",
            command=lambda: self._browse_item(item))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _rescan_item(self, item):
        path = item.get("path", "")
        if not path:
            return
        if item.get("is_dir", True):
            self.path_var.set(path)
            self._start_scan(path)
        else:
            parent = os.path.dirname(path)
            if parent:
                self.path_var.set(parent)
                self._start_scan(parent)

    def _browse_item(self, item):
        path = item.get("path", "")
        if path:
            FileExplorerPopup.show(
                self.winfo_toplevel(), path,
                title="Browse: %s" % os.path.basename(path.rstrip("/\\")))

    def _on_destroy(self, event):
        try:
            if str(event.widget) != str(self):
                return
        except Exception:
            return
        self._scan_token += 1


class XSpaceApp(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("xSpace Visual Analyzer")
        self.configure(bg=GUI_BG)
        self.geometry("960x640")
        self.minsize(640, 480)
        panel = XSpacePanel(self, geometry_save_widget=self)
        panel.pack(fill=tk.BOTH, expand=True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)


def _ensure_display():
    """
    Tkinter needs $DISPLAY. SSH shells often unset it even when the host
    has a local X session at :0 (common on QC workstations / navoff1 console).
    """
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    if sys.platform.startswith("linux"):
        try:
            test_env = os.environ.copy()
            test_env["DISPLAY"] = ":0"
            subprocess.check_output(
                ["xdpyinfo"], env=test_env, stderr=subprocess.STDOUT)
            os.environ["DISPLAY"] = ":0"
            return True
        except Exception:
            pass
    return False


def xnavsl_embed(master):
    """Called by xNAVSL to show this tool inside a tab (no second Tk)."""
    panel = XSpacePanel(master, geometry_save_widget=None)
    panel.pack(fill=tk.BOTH, expand=True)
    return panel


if __name__ == "__main__":
    if not _ensure_display():
        sys.stderr.write(
            "\n--- xSpace Visual Analyzer ---\n"
            "Tkinter could not find a display (error at Tkinter.py line ~1825).\n"
            "\n"
            "This is NOT a bug in xSpace.py — the GUI has nowhere to draw.\n"
            "\n"
            "Fix:\n"
            "  • Run on your QC workstation (with monitor), or from xNAVSL there\n"
            "  • Or SSH with X forwarding:  ssh -X user@host\n"
            "  • Or on the server console:  export DISPLAY=:0\n"
            "\n")
        sys.exit(1)
    try:
        app = XSpaceApp()
        app.mainloop()
    except tk.TclError as e:
        sys.stderr.write(
            "\nTkinter display error: %s\n"
            "(Tkinter.py ~1825 — set DISPLAY or use ssh -X)\n" % e)
        sys.exit(1)
