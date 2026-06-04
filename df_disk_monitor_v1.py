#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
================================================================
  disc_monitor  -  Disk Space Monitor  (SSH df -h)
  Python 2.7  -  Standard library only
  SSH via subprocess  (sshpass  or  SSH_ASKPASS fallback)
  AI assisted code by RBolisay
================================================================
"""
from __future__ import print_function, unicode_literals

import os
import sys
import json
import stat
import time
import socket
import tempfile
import threading
import subprocess

import Tkinter as tk
import ttk
import tkMessageBox   as messagebox
import tkSimpleDialog as simpledialog

# ================================================================
#  THEMES
# ================================================================
THEMES = {
    "Dark": {
        "WIN_BG":    "#1a1a2e",
        "FRAME_BG":  "#16213e",
        "HEADER_BG": "#2c3e50",
        "HEADER_FG": "#ecf0f1",
        "TEXT_FG":   "#ecf0f1",
        "ACCENT":    "#0f3460",
        "BTN_BG":    "#0f3460",
        "BTN_ACT":   "#1a4a7a",
        "ENTRY_BG":  "#0d1b2a",
        "ENTRY_FG":  "#ecf0f1",
        "ROW_A":     "#1e2a38",
        "ROW_B":     "#243040",
        "LOG_BG":    "#1a1a2e",
        "SEP_BG":    "#0f3460",
        "FONT_MAIN": ("Consolas",  10),
        "FONT_BOLD": ("Consolas",  10, "bold"),
        "FONT_HEAD": ("Consolas",  11, "bold"),
        "FONT_TITL": ("Consolas",  12, "bold"),
        "FONT_SMAL": ("Consolas",   9),
        "FONT_MONO": ("Consolas",  10),
        "TAB_SEL_FG": "#2ecc71",
        "STATUS_OK":  "#2ecc71",
        "STATUS_RUN": "#f1c40f",
        "STATUS_ERR": "#e74c3c",
        "HINT_FG":    "#7f8c8d",
    },
    "df_disk": {
        "WIN_BG":    "#B4C8E1",
        "FRAME_BG":  "#B4C8E1",
        "HEADER_BG": "#8DA9CC",
        "HEADER_FG": "#000000",
        "TEXT_FG":   "#000000",
        "ACCENT":    "#8DA9CC",
        "BTN_BG":    "#8DA9CC",
        "BTN_ACT":   "#7a96b8",
        "ENTRY_BG":  "#ffffff",
        "ENTRY_FG":  "#000000",
        "ROW_A":     "#d4e0ef",
        "ROW_B":     "#c8d8eb",
        "LOG_BG":    "#B4C8E1",
        "SEP_BG":    "#8DA9CC",
        "FONT_MAIN": ("TkDefaultFont", 10),
        "FONT_BOLD": ("TkDefaultFont", 10, "bold"),
        "FONT_HEAD": ("TkDefaultFont", 11, "bold"),
        "FONT_TITL": ("TkDefaultFont", 12, "bold"),
        "FONT_SMAL": ("TkDefaultFont",  9),
        "FONT_MONO": ("Courier",        10),
        "TAB_SEL_FG": "#00008b",
        "STATUS_OK":  "#006400",
        "STATUS_RUN": "#8B6914",
        "STATUS_ERR": "#8b0000",
        "HINT_FG":    "#4a4a4a",
    },
}

# Active theme dict  (starts as Dark, changed by _apply_theme)
T = dict(THEMES["Dark"])

# Usage % color bands  (same regardless of theme)
THRESHOLDS = [
    (60,  "#2ecc71", "#000000"),   # < 60%  green
    (80,  "#f1c40f", "#000000"),   # 60-80% yellow
    (90,  "#e67e22", "#ffffff"),   # 80-90% orange
    (101, "#e74c3c", "#ffffff"),   # > 90%  red
]

CONFIG_FILE = "df_servers.json"
SSH_TIMEOUT = 15

# ================================================================
#  Helpers
# ================================================================
def usage_color(pct_str):
    try:
        val = int(pct_str.rstrip("%"))
    except (ValueError, AttributeError):
        return ("#888888", T["TEXT_FG"])
    for limit, bg, fg in THRESHOLDS:
        if val < limit:
            return (bg, fg)
    return ("#e74c3c", "#ffffff")


def parse_df_output(raw):
    rows  = []
    lines = raw.strip().splitlines()
    if not lines:
        return rows
    data_lines = [l for l in lines if not l.startswith("Filesystem")]
    merged = []
    buf    = ""
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
    cols = ["filesystem", "size", "used", "avail", "use_pct", "mounted"]
    for line in merged:
        parts = line.split()
        if len(parts) < 6:
            continue
        rows.append(dict(zip(cols, parts[:6])))
    return rows


def sshpass_available():
    try:
        p = subprocess.Popen(["sshpass", "--version"],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        p.communicate()
        return True
    except OSError:
        return False


def _make_askpass_script(password):
    safe   = password.replace("\\", "\\\\").replace("'", "'\\''")
    script = "#!/bin/sh\nprintf '%s' '{}'\n".format(safe)
    fd, path = tempfile.mkstemp(suffix=".sh", prefix="df_disk_")
    try:
        os.write(fd, script.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRWXU)
    return path


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "lo"}

def is_local(host):
    h = host.strip().lower()
    if h in LOCAL_HOSTS:
        return True
    try:
        if h == socket.gethostname().lower():
            return True
        if h == socket.getfqdn().lower():
            return True
    except Exception:
        pass
    return False


def run_local_command(command):
    try:
        proc = subprocess.Popen(command, shell=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0 and not stdout.strip():
            return None, "Error rc={}: {}".format(proc.returncode, stderr.strip())
        return stdout, stderr
    except Exception as e:
        return None, str(e)


def run_ssh_command(server):
    """
    Execute command on server.
    If host is local  -> direct execution (no SSH).
    If remote, auth priority:
      1. SSH private key   (-i key_file)
      2. sshpass + password
      3. SSH_ASKPASS + password  (stdlib-only fallback)
      4. ssh-agent / authorized_keys
    """
    host     = server["host"]
    port     = str(server.get("port", 22))
    user     = server["user"]
    password = server.get("password", "")
    key_file = server.get("key_file", "").strip()
    command  = server.get("command", "df -h")
    target   = "{}@{}".format(user, host)

    if is_local(host):
        return run_local_command(command)

    common = [
        "-p", port,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout={}".format(SSH_TIMEOUT),
        "-o", "LogLevel=ERROR",
        "-o", "NumberOfPasswordPrompts=1",
    ]

    askpass_path = None
    env          = None

    try:
        if key_file and os.path.isfile(key_file):
            cmd = (["ssh"] + common +
                   ["-o", "BatchMode=yes", "-i", key_file, target, command])

        elif password and sshpass_available():
            cmd = (["sshpass", "-p", password, "ssh"] + common +
                   ["-o", "BatchMode=no", target, command])

        elif password:
            askpass_path = _make_askpass_script(password)
            env = os.environ.copy()
            env["SSH_ASKPASS"]         = askpass_path
            env["SSH_ASKPASS_REQUIRE"] = "force"
            if "DISPLAY" not in env:
                env["DISPLAY"] = ":0"
            cmd = (["ssh"] + common +
                   ["-o", "BatchMode=no", target, command])

        else:
            cmd = (["ssh"] + common +
                   ["-o", "BatchMode=yes", target, command])

        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                env=env,
                                stdin=subprocess.PIPE)
        stdout, stderr = proc.communicate()

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0 and not stdout.strip():
            return None, "SSH rc={}: {}".format(proc.returncode, stderr.strip())

        return stdout, stderr

    except OSError as e:
        return None, "Cannot run ssh: {}".format(e)
    except Exception as e:
        return None, str(e)
    finally:
        if askpass_path and os.path.exists(askpass_path):
            try:
                os.unlink(askpass_path)
            except Exception:
                pass


def auth_method_label(server):
    if is_local(server.get("host", "")):
        return "LOCAL (no SSH)"
    kf = server.get("key_file", "").strip()
    pw = server.get("password", "")
    if kf and os.path.isfile(kf):
        return "SSH key"
    elif pw:
        return "sshpass+pwd" if sshpass_available() else "SSH_ASKPASS+pwd"
    else:
        return "agent/authorized_keys"


# ================================================================
#  Server Dialog  -  Add / Edit
# ================================================================
class ServerDialog(tk.Toplevel):

    def __init__(self, parent, title="Server", server=None):
        tk.Toplevel.__init__(self, parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(bg=T["WIN_BG"])
        self.result = None
        pad = dict(padx=8, pady=4)

        fields = [
            ("Name / Tag:",         0),
            ("Host / IP:",          1),
            ("Port:",               2),
            ("Username:",           3),
            ("Password:",           4),
            ("SSH Key (path):",     5),
            ("Command:",            6),
        ]
        for text, row in fields:
            tk.Label(self, text=text, bg=T["WIN_BG"], fg=T["TEXT_FG"],
                     font=T["FONT_MAIN"]
                     ).grid(row=row, column=0, sticky="e", **pad)

        def ent(row, show=""):
            e = tk.Entry(self, width=36,
                         bg=T["ENTRY_BG"], fg=T["ENTRY_FG"],
                         insertbackground=T["TEXT_FG"],
                         relief="groove", font=T["FONT_MONO"], show=show)
            e.grid(row=row, column=1, **pad)
            return e

        self.e_name = ent(0)
        self.e_host = ent(1)
        self.e_port = ent(2)
        self.e_user = ent(3)
        self.e_pass = ent(4, show="*")
        self.e_key  = ent(5)
        self.e_cmd  = ent(6)

        self.e_port.insert(0, "22")
        self.e_cmd.insert(0, "df -h")

        if server:
            self.e_name.insert(0, server.get("name",     ""))
            self.e_host.insert(0, server.get("host",     ""))
            self.e_port.delete(0, "end")
            self.e_port.insert(0, str(server.get("port", 22)))
            self.e_user.insert(0, server.get("user",     ""))
            self.e_pass.insert(0, server.get("password", ""))
            self.e_key.insert(0,  server.get("key_file", ""))
            self.e_cmd.delete(0, "end")
            self.e_cmd.insert(0,  server.get("command",  "df -h"))

        tk.Label(self,
                 text="Auth priority: SSH key  >  sshpass+pwd  >  SSH_ASKPASS+pwd\n"
                      "For local hosts (same machine) no SSH is used.",
                 bg=T["WIN_BG"], fg=T["HINT_FG"],
                 font=T["FONT_SMAL"], justify="left"
                 ).grid(row=7, column=0, columnspan=2,
                        padx=8, pady=4, sticky="w")

        bf = tk.Frame(self, bg=T["WIN_BG"])
        bf.grid(row=8, column=0, columnspan=2, pady=8)
        tk.Button(bf, text="  Save  ", command=self._save,
                  bg=T["BTN_BG"], fg=T["HEADER_FG"],
                  activebackground=T["BTN_ACT"],
                  relief="groove", font=T["FONT_BOLD"],
                  cursor="hand2").pack(side="left", padx=6)
        tk.Button(bf, text="  Cancel  ", command=self.destroy,
                  bg=T["BTN_BG"], fg=T["HEADER_FG"],
                  activebackground=T["BTN_ACT"],
                  relief="groove", font=T["FONT_MAIN"],
                  cursor="hand2").pack(side="left", padx=6)

        self.grab_set()
        self.wait_window(self)

    def _save(self):
        host = self.e_host.get().strip()
        user = self.e_user.get().strip()
        if not host or not user:
            messagebox.showerror("Error",
                "Host and username are required.", parent=self)
            return
        try:
            port = int(self.e_port.get().strip())
        except ValueError:
            port = 22
        self.result = {
            "name":     self.e_name.get().strip() or host,
            "host":     host,
            "port":     port,
            "user":     user,
            "password": self.e_pass.get(),
            "key_file": self.e_key.get().strip(),
            "command":  self.e_cmd.get().strip() or "df -h",
        }
        self.destroy()


# ================================================================
#  ServerTab  -  one tab per server
# ================================================================
class ServerTab(tk.Frame):

    COL_W = [32, 8, 8, 8, 8, 24]
    COL_N = ["Filesystem", "Size", "Used", "Avail", "Use%", "Mounted on"]

    def __init__(self, parent, app, server):
        tk.Frame.__init__(self, parent, bg=T["FRAME_BG"])
        self.app    = app
        self.server = server
        self._stop  = threading.Event()
        self._widgets = []   # (widget, attr)  for re-theming
        self._build_ui()

    # ── build ─────────────────────────────────────────────
    def _build_ui(self):
        # top bar
        top = tk.Frame(self, bg=T["HEADER_BG"])
        top.pack(fill="x")
        self._tw("top_bar", top)

        self._lbl_info = tk.Label(
            top,
            text="  {}  @  {}:{}".format(
                self.server["user"],
                self.server["host"],
                self.server["port"]),
            bg=T["HEADER_BG"], fg=T["HEADER_FG"],
            font=T["FONT_HEAD"])
        self._lbl_info.pack(side="left", padx=10, pady=6)

        self._sv = tk.StringVar(value="* idle")
        self._sl = tk.Label(top, textvariable=self._sv,
                            bg=T["HEADER_BG"], fg=T["STATUS_ERR"],
                            font=T["FONT_MAIN"])
        self._sl.pack(side="left", padx=10)

        self._tv = tk.StringVar(value="")
        self._lbl_time = tk.Label(top, textvariable=self._tv,
                                  bg=T["HEADER_BG"], fg=T["HINT_FG"],
                                  font=T["FONT_SMAL"])
        self._lbl_time.pack(side="left", padx=10)

        self._btn_ref = tk.Button(
            top, text=" Refresh ",
            command=self._manual_refresh,
            bg=T["BTN_BG"], fg=T["HEADER_FG"],
            activebackground=T["BTN_ACT"],
            relief="groove", font=T["FONT_SMAL"], cursor="hand2")
        self._btn_ref.pack(side="right", padx=4, pady=4)

        self._btn_edit = tk.Button(
            top, text=" Edit ",
            command=self._edit_server,
            bg=T["BTN_BG"], fg=T["HEADER_FG"],
            activebackground=T["BTN_ACT"],
            relief="groove", font=T["FONT_SMAL"], cursor="hand2")
        self._btn_edit.pack(side="right", padx=4, pady=4)

        # command / auth bar
        cb = tk.Frame(self, bg=T["ACCENT"])
        cb.pack(fill="x")
        self._tw("cmd_bar", cb)

        self._cmdlbl = tk.Label(
            cb,
            text=" cmd: {}".format(self.server.get("command", "df -h")),
            bg=T["ACCENT"], fg=T["TEXT_FG"],
            font=T["FONT_SMAL"])
        self._cmdlbl.pack(side="left", padx=8, pady=2)

        self._authv = tk.StringVar(value="")
        self._lbl_auth = tk.Label(
            cb, textvariable=self._authv,
            bg=T["ACCENT"], fg=T["STATUS_OK"],
            font=T["FONT_SMAL"])
        self._lbl_auth.pack(side="right", padx=8)
        self._refresh_auth_label()

        # table header
        outer = tk.Frame(self, bg=T["FRAME_BG"])
        outer.pack(fill="both", expand=True, padx=4, pady=4)
        self._tw("outer", outer)

        self._hdr_frame = tk.Frame(outer, bg=T["HEADER_BG"])
        self._hdr_frame.pack(fill="x")

        self._hdr_labels = []
        for i, (n, w) in enumerate(zip(self.COL_N, self.COL_W)):
            a = "w" if i in (0, 5) else "center"
            lbl = tk.Label(self._hdr_frame, text=n, width=w,
                           bg=T["HEADER_BG"], fg=T["HEADER_FG"],
                           font=T["FONT_BOLD"], anchor=a)
            lbl.pack(side="left", padx=2, pady=4)
            self._hdr_labels.append(lbl)

        # scrollable body
        cont = tk.Frame(outer, bg=T["FRAME_BG"])
        cont.pack(fill="both", expand=True)
        self._tw("cont", cont)

        self._cv = tk.Canvas(cont, bg=T["FRAME_BG"], highlightthickness=0)
        vsb = tk.Scrollbar(cont, orient="vertical", command=self._cv.yview)
        self._cv.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._cv.pack(side="left", fill="both", expand=True)

        self._body = tk.Frame(self._cv, bg=T["FRAME_BG"])
        self._bid  = self._cv.create_window((0, 0), window=self._body,
                                            anchor="nw")

        self._body.bind("<Configure>",
            lambda e: self._cv.configure(
                scrollregion=self._cv.bbox("all")))
        self._cv.bind("<Configure>",
            lambda e: self._cv.itemconfig(self._bid, width=e.width))
        self._cv.bind("<Button-4>",
            lambda e: self._cv.yview_scroll(-1, "units"))
        self._cv.bind("<Button-5>",
            lambda e: self._cv.yview_scroll(1, "units"))

        # error log bar
        lf = tk.Frame(self, bg=T["LOG_BG"])
        lf.pack(fill="x", padx=4, pady=(0, 2))
        self._tw("log_frame", lf)
        self._logv = tk.StringVar(value="")
        self._lbl_log = tk.Label(lf, textvariable=self._logv,
                                 bg=T["LOG_BG"], fg=T["STATUS_ERR"],
                                 font=T["FONT_SMAL"],
                                 wraplength=900, justify="left")
        self._lbl_log.pack(side="left", padx=4)

        # legend
        self._leg_frame = tk.Frame(self, bg=T["LOG_BG"])
        self._leg_frame.pack(fill="x", padx=4, pady=2)
        self._build_legend()

        self.start()

    def _tw(self, tag, widget):
        """Track a themed frame/widget for later re-theming."""
        self._widgets.append((tag, widget))

    def _build_legend(self):
        for w in self._leg_frame.winfo_children():
            w.destroy()
        tk.Label(self._leg_frame, text="Disk usage: ",
                 bg=T["LOG_BG"], fg=T["TEXT_FG"],
                 font=T["FONT_BOLD"]).pack(side="left", padx=(4, 6))
        for txt, bg, fg in [
                ("  < 60%  ", "#2ecc71", "#000"),
                (" 60-80%  ", "#f1c40f", "#000"),
                (" 80-90%  ", "#e67e22", "#fff"),
                ("  > 90%  ", "#e74c3c", "#fff")]:
            tk.Label(self._leg_frame, text=txt, bg=bg, fg=fg,
                     font=T["FONT_SMAL"]).pack(side="left", padx=2)

    def _refresh_auth_label(self):
        self._authv.set("auth: {} ".format(auth_method_label(self.server)))

    # ── re-theme ──────────────────────────────────────────
    def apply_theme(self):
        """Re-apply the active global theme T to all widgets."""
        self.configure(bg=T["FRAME_BG"])

        self._lbl_info.configure(bg=T["HEADER_BG"], fg=T["HEADER_FG"],
                                 font=T["FONT_HEAD"])
        self._sl.configure(bg=T["HEADER_BG"], font=T["FONT_MAIN"])
        self._lbl_time.configure(bg=T["HEADER_BG"], fg=T["HINT_FG"],
                                 font=T["FONT_SMAL"])
        self._btn_ref.configure(bg=T["BTN_BG"], fg=T["HEADER_FG"],
                                activebackground=T["BTN_ACT"],
                                font=T["FONT_SMAL"])
        self._btn_edit.configure(bg=T["BTN_BG"], fg=T["HEADER_FG"],
                                 activebackground=T["BTN_ACT"],
                                 font=T["FONT_SMAL"])
        self._cmdlbl.configure(bg=T["ACCENT"], fg=T["TEXT_FG"],
                               font=T["FONT_SMAL"])
        self._lbl_auth.configure(bg=T["ACCENT"], fg=T["STATUS_OK"],
                                 font=T["FONT_SMAL"])
        self._lbl_log.configure(bg=T["LOG_BG"], fg=T["STATUS_ERR"],
                                font=T["FONT_SMAL"])

        for tag, w in self._widgets:
            if tag == "top_bar":
                w.configure(bg=T["HEADER_BG"])
            elif tag == "cmd_bar":
                w.configure(bg=T["ACCENT"])
            elif tag in ("outer", "cont"):
                w.configure(bg=T["FRAME_BG"])
            elif tag in ("log_frame",):
                w.configure(bg=T["LOG_BG"])

        self._hdr_frame.configure(bg=T["HEADER_BG"])
        for lbl in self._hdr_labels:
            lbl.configure(bg=T["HEADER_BG"], fg=T["HEADER_FG"],
                          font=T["FONT_BOLD"])

        self._cv.configure(bg=T["FRAME_BG"])
        self._body.configure(bg=T["FRAME_BG"])
        self._leg_frame.configure(bg=T["LOG_BG"])
        self._build_legend()

        # re-render table rows with new colors
        if self._body.winfo_children():
            # trigger a visual refresh keeping existing data
            for rf in self._body.winfo_children():
                rf.configure(bg=T["ROW_A"])   # approximate; full re-render on next refresh

    # ── rendering ─────────────────────────────────────────
    def _render_rows(self, rows):
        for w in self._body.winfo_children():
            w.destroy()
        for idx, row in enumerate(rows):
            rbg = T["ROW_A"] if idx % 2 == 0 else T["ROW_B"]
            pct = row.get("use_pct", "0%")
            cbg, cfg = usage_color(pct)

            rf = tk.Frame(self._body, bg=rbg)
            rf.pack(fill="x")

            vals = [row.get("filesystem", ""), row.get("size",   ""),
                    row.get("used",        ""), row.get("avail",  ""),
                    pct,                        row.get("mounted", "")]

            for i, (v, w) in enumerate(zip(vals, self.COL_W)):
                is_pct = (i == 4)
                a      = "w" if i in (0, 5) else "center"
                wt     = "bold" if is_pct else "normal"
                cell_bg = cbg         if is_pct else rbg
                cell_fg = cfg         if is_pct else T["TEXT_FG"]
                font    = (T["FONT_MONO"][0], T["FONT_MONO"][1], wt)
                tk.Label(rf, text=v, width=w,
                         bg=cell_bg, fg=cell_fg,
                         font=font, anchor=a
                         ).pack(side="left", padx=2, pady=3)
        self._cv.yview_moveto(0)

    # ── refresh loop ──────────────────────────────────────
    def start(self):
        self._stop.clear()
        t = threading.Thread(target=self._loop)
        t.daemon = True
        t.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            self._do_refresh()
            self._stop.wait(self.app.interval)

    def _do_refresh(self):
        self._setstatus("running")
        out, err = run_ssh_command(self.server)
        if out is None:
            self._setstatus("error", err)
        else:
            rows = parse_df_output(out)
            ts   = time.strftime("%H:%M:%S")
            self.after(0, lambda r=rows, t=ts: self._update_ui(r, t))
            if err and err.strip():
                self.after(0, lambda e=err:
                    self._logv.set("stderr: " + e.strip()))

    def _update_ui(self, rows, ts):
        self._render_rows(rows)
        self._tv.set("Updated: {}".format(ts))
        self._logv.set("")
        self._setstatus("ok")

    def _setstatus(self, state, msg=""):
        MAP = {
            "running": (T["STATUS_RUN"], "* running..."),
            "ok":      (T["STATUS_OK"],  "* ok"),
            "error":   (T["STATUS_ERR"], "* error"),
        }
        fg, txt = MAP.get(state, (T["STATUS_ERR"], "* ?"))
        def _do():
            self._sv.set(txt)
            self._sl.config(fg=fg)
            if state == "error":
                self._logv.set(msg)
        self.after(0, _do)

    def _manual_refresh(self):
        t = threading.Thread(target=self._do_refresh)
        t.daemon = True
        t.start()

    def _edit_server(self):
        dlg = ServerDialog(self.app, title="Edit Server", server=self.server)
        if dlg.result:
            self.stop()
            self.server.update(dlg.result)
            idx = self.app.notebook.index(self)
            self.app.notebook.tab(idx, text=" {} ".format(self.server["name"]))
            self._lbl_info.config(
                text="  {}  @  {}:{}".format(
                    self.server["user"],
                    self.server["host"],
                    self.server["port"]))
            self._cmdlbl.config(
                text=" cmd: {}".format(self.server.get("command", "df -h")))
            self._refresh_auth_label()
            self.app.save_servers()
            self.start()


# ================================================================
#  Main Application
# ================================================================
class DF_App(tk.Tk):

    DEFAULT_INTERVAL = 30
    VERSION          = "1.0"

    def __init__(self):
        tk.Tk.__init__(self)
        self.title("DISK  -  Disk Space Monitor  v{}  [Python 2.7]".format(
            self.VERSION))
        self.geometry("1200x660")
        self.configure(bg=T["WIN_BG"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.interval     = self.DEFAULT_INTERVAL
        self._tabs        = {}
        self._theme_name  = tk.StringVar(value="Dark")

        self._build_toolbar()
        self._build_notebook()
        self._load_servers()

    # ── toolbar ───────────────────────────────────────────
    def _build_toolbar(self):
        self._bar = tk.Frame(self, bg=T["HEADER_BG"], height=48)
        self._bar.pack(fill="x")
        self._bar.pack_propagate(False)

        # Title
        self._lbl_title = tk.Label(
            self._bar,
            text="  DISK  |  SSH Disk Space Monitor",
            bg=T["HEADER_BG"], fg=T["HEADER_FG"],
            font=T["FONT_TITL"])
        self._lbl_title.pack(side="left", padx=10)

        # Add server
        self._btn_add = tk.Button(
            self._bar, text="  + Add Server  ",
            command=self._add_server,
            bg=T["BTN_BG"], fg=T["HEADER_FG"],
            activebackground=T["BTN_ACT"],
            relief="groove", font=T["FONT_MAIN"], cursor="hand2")
        self._btn_add.pack(side="left", padx=4, pady=7)

        # Remove server
        self._btn_rem = tk.Button(
            self._bar, text="  - Remove  ",
            command=self._remove_current,
            bg="#6c1f1f", fg="#ffffff",
            activebackground="#8b2828",
            relief="groove", font=T["FONT_MAIN"], cursor="hand2")
        self._btn_rem.pack(side="left", padx=4, pady=7)

        # sshpass indicator
        sp = sshpass_available()
        sp_fg  = T["STATUS_OK"] if sp else "#f39c12"
        sp_txt = "sshpass: OK" if sp else "sshpass: N/A"
        self._lbl_sp = tk.Label(
            self._bar, text="  " + sp_txt,
            bg=T["HEADER_BG"], fg=sp_fg,
            font=T["FONT_SMAL"])
        self._lbl_sp.pack(side="left", padx=8)

        # ── RIGHT side ────────────────────────────────────
        # Interval button
        self._btn_int = tk.Button(
            self._bar, text=" Interval ",
            command=self._set_interval,
            bg=T["HEADER_BG"], fg=T["HEADER_FG"],
            activebackground=T["ACCENT"],
            relief="flat", font=T["FONT_SMAL"], cursor="hand2")
        self._btn_int.pack(side="right", padx=6)

        self._iv = tk.StringVar(value="{} s".format(self.DEFAULT_INTERVAL))
        self._lbl_iv = tk.Label(
            self._bar, textvariable=self._iv,
            bg=T["HEADER_BG"], fg=T["STATUS_OK"],
            font=T["FONT_BOLD"])
        self._lbl_iv.pack(side="right")

        self._lbl_ref = tk.Label(
            self._bar, text="Refresh: ",
            bg=T["HEADER_BG"], fg=T["HEADER_FG"],
            font=T["FONT_SMAL"])
        self._lbl_ref.pack(side="right")

        # separator
        tk.Frame(self._bar, bg=T["ACCENT"], width=2
                 ).pack(side="right", fill="y", padx=6, pady=6)

        # Theme selector
        self._lbl_thm = tk.Label(
            self._bar, text="Theme:",
            bg=T["HEADER_BG"], fg=T["HEADER_FG"],
            font=T["FONT_SMAL"])
        self._lbl_thm.pack(side="right", padx=(0, 2))

        self._theme_menu = ttk.Combobox(
            self._bar,
            textvariable=self._theme_name,
            values=sorted(THEMES.keys()),
            state="readonly", width=9,
            font=T["FONT_SMAL"])
        self._theme_menu.pack(side="right", padx=4)
        self._theme_menu.bind("<<ComboboxSelected>>", self._on_theme_change)

    # ── notebook ──────────────────────────────────────────
    def _build_notebook(self):
        self._apply_notebook_style()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)

        self._ph = tk.Frame(self.notebook, bg=T["FRAME_BG"])
        tk.Label(self._ph,
                 text="\n\n\n  No servers configured.\n"
                      "  Click '+ Add Server' to begin.\n",
                 bg=T["FRAME_BG"], fg=T["HINT_FG"],
                 font=T["FONT_HEAD"]).pack(expand=True)
        self.notebook.add(self._ph, text="  -  ")

    def _apply_notebook_style(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook",
                        background=T["WIN_BG"], borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=T["ACCENT"], foreground=T["HEADER_FG"],
                        padding=[12, 4], font=T["FONT_MAIN"])
        style.map("TNotebook.Tab",
                  background=[("selected", T["HEADER_BG"])],
                  foreground=[("selected", T["TAB_SEL_FG"])])
        style.configure("TCombobox",
                        fieldbackground=T["ENTRY_BG"],
                        foreground=T["ENTRY_FG"],
                        background=T["BTN_BG"])

    # ── theme change ──────────────────────────────────────
    def _on_theme_change(self, event=None):
        name = self._theme_name.get()
        if name not in THEMES:
            return
        T.update(THEMES[name])
        self._apply_theme_to_app()

    def _apply_theme_to_app(self):
        # root window
        self.configure(bg=T["WIN_BG"])

        # toolbar
        self._bar.configure(bg=T["HEADER_BG"])
        self._lbl_title.configure(bg=T["HEADER_BG"], fg=T["HEADER_FG"],
                                  font=T["FONT_TITL"])
        self._btn_add.configure(bg=T["BTN_BG"], fg=T["HEADER_FG"],
                                activebackground=T["BTN_ACT"],
                                font=T["FONT_MAIN"])
        self._lbl_iv.configure(bg=T["HEADER_BG"], fg=T["STATUS_OK"],
                               font=T["FONT_BOLD"])
        self._lbl_ref.configure(bg=T["HEADER_BG"], fg=T["HEADER_FG"],
                                font=T["FONT_SMAL"])
        self._btn_int.configure(bg=T["HEADER_BG"], fg=T["HEADER_FG"],
                                activebackground=T["ACCENT"],
                                font=T["FONT_SMAL"])
        self._lbl_thm.configure(bg=T["HEADER_BG"], fg=T["HEADER_FG"],
                                font=T["FONT_SMAL"])
        self._lbl_sp.configure(bg=T["HEADER_BG"], font=T["FONT_SMAL"])

        # placeholder
        self._ph.configure(bg=T["FRAME_BG"])
        for w in self._ph.winfo_children():
            w.configure(bg=T["FRAME_BG"], fg=T["HINT_FG"],
                        font=T["FONT_HEAD"])

        # notebook style
        self._apply_notebook_style()

        # all server tabs
        for tab in self._tabs.values():
            tab.apply_theme()

    # ── server management ─────────────────────────────────
    def _add_server(self, server=None):
        if server is None:
            dlg    = ServerDialog(self, title="Add Server")
            server = dlg.result
        if not server:
            return
        name = server["name"]
        base = name; n = 1
        while name in self._tabs:
            name = "{} ({})".format(base, n); n += 1
        server["name"] = name

        if len(self._tabs) == 0:
            try:
                self.notebook.forget(self._ph)
            except Exception:
                pass

        tab = ServerTab(self.notebook, self, server)
        self.notebook.add(tab, text=" {} ".format(name))
        self.notebook.select(tab)
        self._tabs[name] = tab
        self.save_servers()

    def _remove_current(self):
        sel = self.notebook.select()
        if not sel:
            return
        widget = self.nametowidget(sel)
        if widget is self._ph:
            return
        name = None
        for n, t in self._tabs.items():
            if t is widget:
                name = n; break
        if name and messagebox.askyesno(
                "Remove Server",
                "Remove server '{}'?".format(name)):
            widget.stop()
            self.notebook.forget(widget)
            del self._tabs[name]
            self.save_servers()
            if not self._tabs:
                self.notebook.add(self._ph, text="  -  ")

    # ── interval ──────────────────────────────────────────
    def _set_interval(self):
        val = simpledialog.askinteger(
            "Refresh Interval",
            "Seconds between updates (min 5):",
            initialvalue=self.interval,
            minvalue=5, maxvalue=3600,
            parent=self)
        if val:
            self.interval = val
            self._iv.set("{} s".format(val))

    # ── persistence ───────────────────────────────────────
    def save_servers(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump([t.server for t in self._tabs.values()],
                          f, indent=2)
        except Exception:
            pass

    def _load_servers(self):
        if not os.path.isfile(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r") as f:
                for srv in json.load(f):
                    self._add_server(server=srv)
        except Exception:
            pass

    # ── close ─────────────────────────────────────────────
    def _on_close(self):
        if messagebox.askokcancel("Quit", "Exit DISK?", parent=self):
            for tab in self._tabs.values():
                tab.stop()
            self.destroy()


# ================================================================
if __name__ == "__main__":
    app = DF_App()
    app.mainloop()
