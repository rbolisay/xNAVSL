#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
"""
xSpace Visual Analyzer  -  WinDirStat-style folder treemap for NAVSL servers.
Python 2.7 + Tkinter. Embeddable in xNAVSL via xnavsl_embed(master).
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
import tkFileDialog

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
}

SSH_USER = "shearwater"
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
        if h == socket.gethostname().lower():
            return True
    except Exception:
        pass
    return False


def sshpass_available():
    try:
        p = subprocess.Popen(
            ["sshpass", "--version"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.communicate()
        return True
    except OSError:
        return False


def _make_askpass_script(password):
    safe = password.replace("\\", "\\\\").replace("'", "'\\''")
    script = "#!/bin/sh\nprintf '%s' '{}'\n".format(safe)
    fd, path = tempfile.mkstemp(suffix=".sh", prefix="xspace_")
    try:
        os.write(fd, script.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRWXU)
    return path


def run_remote_command(host, command, user=SSH_USER, password="", key_file=""):
    """Run shell command on remote host via SSH, or locally if host is local."""
    if is_local_host(host):
        try:
            proc = subprocess.Popen(
                command, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = proc.communicate()
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            return out, err, proc.returncode
        except Exception as e:
            return "", str(e), 1

    target = "%s@%s" % (user, host)
    common = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=%d" % SSH_TIMEOUT,
        "-o", "LogLevel=ERROR",
        "-o", "NumberOfPasswordPrompts=1",
    ]
    askpass_path = None
    env = None
    try:
        if key_file and os.path.isfile(key_file):
            cmd = (["ssh"] + common +
                   ["-o", "BatchMode=yes", "-i", key_file,
                    target, command])
        elif password and sshpass_available():
            cmd = (["sshpass", "-p", password, "ssh"] + common +
                   ["-o", "BatchMode=no", target, command])
        elif password:
            askpass_path = _make_askpass_script(password)
            env = os.environ.copy()
            env["SSH_ASKPASS"] = askpass_path
            env["SSH_ASKPASS_REQUIRE"] = "force"
            if "DISPLAY" not in env:
                env["DISPLAY"] = ":0"
            cmd = (["ssh"] + common +
                   ["-o", "BatchMode=no", target, command])
        else:
            cmd = (["ssh"] + common +
                   ["-o", "BatchMode=yes", target, command])

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, stdin=subprocess.PIPE)
        out, err = proc.communicate()
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        return out, err, proc.returncode
    except Exception as e:
        return "", str(e), 1
    finally:
        if askpass_path and os.path.exists(askpass_path):
            try:
                os.unlink(askpass_path)
            except Exception:
                pass


def parse_du_output(raw, parent_path):
    """Parse `du -sk path/*` output into entry dicts."""
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            size_kb = int(parts[0])
        except ValueError:
            continue
        child_path = parts[1].strip()
        name = os.path.basename(child_path.rstrip("/"))
        if not name:
            name = child_path
        entries.append({
            "name": name,
            "path": child_path,
            "size": size_kb * 1024,
            "is_dir": True,
        })
    entries.sort(key=lambda e: e["size"], reverse=True)
    return entries


def scan_local_du(directory):
    """Scan immediate children sizes using du (fast on Linux)."""
    if not os.path.isdir(directory):
        return []
    quoted = directory.replace("'", "'\\''")
    cmd = "du -sk '%s'/* 2>/dev/null" % quoted
    try:
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if out.strip():
            return parse_du_output(out, directory)
    except Exception:
        pass
    return scan_local_python(directory)


def scan_local_python(directory):
    """Fallback: walk each immediate child to compute size."""
    entries = []
    try:
        names = os.listdir(directory)
    except OSError:
        return entries
    for name in names:
        full = os.path.join(directory, name)
        try:
            if os.path.isdir(full):
                size = dir_size_walk(full)
                entries.append({
                    "name": name, "path": full,
                    "size": size, "is_dir": True,
                })
            elif os.path.isfile(full):
                entries.append({
                    "name": name, "path": full,
                    "size": os.path.getsize(full), "is_dir": False,
                })
        except OSError:
            continue
    entries.sort(key=lambda e: e["size"], reverse=True)
    return entries


def dir_size_walk(path):
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def scan_remote_du(host, directory):
    """Scan remote directory via SSH du."""
    quoted = directory.replace("'", "'\\''")
    cmd = "du -sk '%s'/* 2>/dev/null" % quoted
    out, err, rc = run_remote_command(host, cmd)
    if out.strip():
        return parse_du_output(out, directory)
    return []


def scan_directory(server_key, directory):
    """Scan one directory level; prefer local mount, else SSH."""
    cfg = SERVERS.get(server_key, {})
    mount = cfg.get("mount", "")
    host = cfg.get("host", server_key)
    directory = os.path.normpath(directory)

    if mount and directory.startswith(mount) and os.path.isdir(directory):
        return scan_local_du(directory)
    if os.path.isdir(directory):
        return scan_local_du(directory)
    return scan_remote_du(host, directory)


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
        self.bind("<Double-Button-1>", self._on_double)
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
            rect = self.create_rectangle(
                x1, y1, x2, y2,
                fill=color, outline="#FFFFFF", width=1, tags=(tag, "tile"))
            label = item.get("name", "")
            if tw > 40 and th > 20:
                self.create_text(
                    (x1 + x2) / 2, (y1 + y2) / 2,
                    text=label, fill="#000000" if _is_light(color) else "#FFFFFF",
                    font=FONT_SMALL, width=max(int(tw - 4), 1),
                    tags=(tag, "tile"))
            self._tiles.append({
                "item": item,
                "bbox": (x1, y1, x2, y2),
                "tag": tag,
                "rect_id": rect,
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
        text = "%s\n%s" % (item.get("path", item.get("name", "")),
                           human_size(item.get("size", 0)))
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

    def _on_double(self, event):
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
            ctrl, text="Pick Folder...", bg=BTN_BG, activebackground=BTN_ACTIVE,
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
        status_row.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Label(
            status_row, textvariable=self.status_var,
            bg=GUI_BG, fg=STATUS_FG, font=FONT_SMALL, anchor="w",
        ).pack(fill=tk.X)

    def _server_root(self):
        key = self.server_var.get()
        cfg = SERVERS.get(key, {})
        return cfg.get("mount", "/aw-%s" % key)

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
        cur = self.path_var.get()
        parent = os.path.dirname(cur.rstrip("/\\"))
        if not parent or parent == cur:
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

    def _pick_folder(self):
        initial = self.path_var.get() or self._server_root()
        if not os.path.isdir(initial):
            initial = self._server_root()
        picked = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=initial)
        if picked:
            self.path_var.set(picked)
            self._nav_stack.append(picked)
            self._start_scan(picked)

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
        self.status_var.set("Scanning %s ..." % path)
        self.canvas.set_entries([])
        self.canvas.create_text(
            self.canvas.winfo_width() // 2 or 200,
            self.canvas.winfo_height() // 2 or 200,
            text="Scanning...", fill=STATUS_FG, font=FONT_BOLD, tags="scanning")

        server = self.server_var.get()

        def worker():
            entries = scan_directory(server, path)
            total = sum(e.get("size", 0) for e in entries)
            self.after(0, lambda: self._apply_scan(token, path, entries, total))

        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        self._scan_thread = t

    def _apply_scan(self, token, path, entries, total):
        if token != self._scan_token:
            return
        self.canvas.delete("scanning")
        if not entries:
            self.canvas.set_entries([])
            self.status_var.set(
                "No data for %s (mount missing or empty). "
                "Check server mount /aw-%s" % (path, self.server_var.get()))
            return
        self.canvas.set_entries(entries)
        self.status_var.set(
            "%d items  |  Total: %s  |  %s" % (
                len(entries), human_size(total), path))

    def _show_context_menu(self, event, item):
        menu = tk.Menu(self, tearoff=0, bg=GUI_BG, fg=TEXT_FG)
        path = item.get("path", "")

        menu.add_command(
            label="Rescan",
            command=lambda: self._rescan_item(item))
        menu.add_command(
            label="Browse Directory",
            command=lambda: self._browse_item(item))
        menu.add_separator()
        menu.add_command(
            label="Delete",
            command=lambda: self._delete_item(item))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _rescan_item(self, item):
        path = item.get("path", "")
        if not path:
            return
        if os.path.isdir(path):
            self.path_var.set(path)
            self._start_scan(path)
        else:
            parent = os.path.dirname(path)
            self.path_var.set(parent)
            self._start_scan(parent)

    def _browse_item(self, item):
        path = item.get("path", "")
        if path:
            FileExplorerPopup.show(
                self.winfo_toplevel(), path,
                title="Browse: %s" % os.path.basename(path.rstrip("/\\")))

    def _delete_item(self, item):
        path = item.get("path", "")
        name = item.get("name", path)
        if not path:
            return
        if not messagebox.askyesno(
                "Confirm Delete",
                "Delete permanently?\n\n%s\n\nThis cannot be undone." % path,
                parent=self.winfo_toplevel(), icon="warning"):
            return
        try:
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
            elif os.path.isfile(path):
                os.remove(path)
            else:
                messagebox.showerror(
                    "Delete", "Path not found locally:\n%s" % path,
                    parent=self.winfo_toplevel())
                return
        except Exception as e:
            messagebox.showerror("Delete Failed", str(e), parent=self.winfo_toplevel())
            return
        self._rescan_current()

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
