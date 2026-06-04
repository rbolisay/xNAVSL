#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Ai assisted Code by RBolisay

"""
Job Completion Estimate - Python 2.7 Tkinter GUI

This application provides a fast, responsive GUI to estimate job completion
time based on preplot lines and acquisition parameters. It follows a
modularized structure with a mediator-style controller coordinating
independent view components.

Python: 2.7
GUI: Tkinter + ttk
"""

from __future__ import division

import os
import sys
import csv
import json
import math
import re
from datetime import datetime, timedelta
import calendar as pycalendar

try:
    import Tkinter as tk
    import ttk
    import tkFileDialog as filedialog
    import tkMessageBox as messagebox
    import tkSimpleDialog as simpledialog
    import tkFont as tkfont
except ImportError:
    # Fallback for environments where Python 3 may be used accidentally
    import tkinter as tk
    from tkinter import ttk
    from tkinter import filedialog, messagebox, simpledialog
    from tkinter import font as tkfont


# Colors and UI constants
BG_COLOR = "#B4C8E1"  # Blue Aura background
BUTTON_BG = "#8DA9CC"  # Slightly darker blue for buttons
BUTTON_FG = "black"
ENTRY_BG = "white"
TEXT_FG = "black"
APP_TITLE = "Job Completion Estimate"
LAST_CONFIG_POINTER = os.path.join(os.path.expanduser("~"), ".xjbcalc_last_config.json")
AUTOSAVE_DIR = os.path.join(os.path.expanduser("~"), ".xjbcalc")


def is_string_numeric(value):
    try:
        int(value)
        return True
    except Exception:
        return False


def try_parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def haversine_distance_km(lat1_deg, lon1_deg, lat2_deg, lon2_deg):
    """Approximate great-circle distance in kilometers between two lat/lon points."""
    # Earth radius in kilometers
    R = 6371.0088
    lat1 = math.radians(lat1_deg)
    lon1 = math.radians(lon1_deg)
    lat2 = math.radians(lat2_deg)
    lon2 = math.radians(lon2_deg)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def euclidean_distance_km(x1, y1, x2, y2):
    """Euclidean distance in kilometers assuming input units are meters if large, or km if small.

    If the magnitude suggests meters (values > 1000), convert to km.
    """
    try:
        dx = float(x2) - float(x1)
        dy = float(y2) - float(y1)
        dist = math.sqrt(dx * dx + dy * dy)
        # Heuristic: if distance is large, assume meters and convert to km
        if dist > 1000.0:
            return dist / 1000.0
        return dist
    except Exception:
        return 0.0


def _dms_compact_to_deg(num_str, is_lat):
    """Convert compact DMS numeric string to decimal degrees.

    num_str examples:
      - lat: 082057.01  -> 08°20'57.01"
      - lon: 0565319.96 -> 056°53'19.96"
    """
    s = str(num_str)
    # Strip any non-digit/dot just in case
    s = re.sub(r"[^0-9\.]", "", s)
    if not s or "." not in s:
        return None
    head, tail = s.split(".", 1)
    # Ensure head has at least 6 (lat) or 7 (lon) digits by left-padding with zeros
    if is_lat and len(head) < 6:
        head = head.zfill(6)
    if not is_lat and len(head) < 7:
        head = head.zfill(7)
    deg_digits = 2 if is_lat else 3
    deg_part = head[:deg_digits]
    min_part = head[deg_digits:deg_digits + 2]
    sec_part_int = head[deg_digits + 2:]
    sec_part = sec_part_int + "." + tail if sec_part_int else "0." + tail
    try:
        deg = int(deg_part)
        minutes = int(min_part)
        seconds = float(sec_part)
        return float(deg) + (minutes / 60.0) + (seconds / 3600.0)
    except Exception:
        return None


def parse_compact_latlon(latlon_str):
    """Parse compact lat/lon string like '082057.01N0565319.96W' to (lat_deg, lon_deg)."""
    m = re.search(r"(?P<lat>\d+\.?\d*)(?P<lat_h>[NS])(?P<lon>\d+\.?\d*)(?P<lon_h>[EW])", str(latlon_str))
    if not m:
        return None, None
    lat_num = m.group('lat')
    lat_h = m.group('lat_h')
    lon_num = m.group('lon')
    lon_h = m.group('lon_h')
    lat = _dms_compact_to_deg(lat_num, is_lat=True)
    lon = _dms_compact_to_deg(lon_num, is_lat=False)
    if lat is None or lon is None:
        return None, None
    if lat_h.upper() == 'S':
        lat = -lat
    if lon_h.upper() == 'W':
        lon = -lon
    return lat, lon


def compress_numeric_ranges(values):
    """Compress sorted iterable of ints into range expression '1-3, 5, 7-9'."""
    if not values:
        return ""
    values = sorted(set(values))
    ranges = []
    start = values[0]
    prev = values[0]
    for v in values[1:]:
        if v == prev + 1:
            prev = v
            continue
        if start == prev:
            ranges.append(str(start))
        else:
            ranges.append("%d-%d" % (start, prev))
        start = v
        prev = v
    if start == prev:
        ranges.append(str(start))
    else:
        ranges.append("%d-%d" % (start, prev))
    return ", ".join(ranges)


def parse_inclusion_expression(expr_text, available_names):
    """Parse inclusion expression like 'ALL' or '1001-1010, 1012, 1020-1030'.

    Returns a set of names (as strings) to include, intersected with available_names.
    If names are non-numeric, falls back to direct matching by exact tokens.
    """
    expr = str(expr_text or "").strip()
    if not expr:
        return set()
    if expr.upper() == "ALL":
        return set(available_names)

    # Try numeric parsing
    tokens = [t.strip() for t in re.split(r",", expr) if t.strip()]
    selected = set()
    all_numeric_names = all(is_string_numeric(n) for n in available_names)
    if all_numeric_names:
        numeric_names = set(int(n) for n in available_names)
        for token in tokens:
            if re.match(r"^\d+\s*-\s*\d+$", token):
                parts = re.split(r"-", token)
                a = try_parse_int(parts[0], None)
                b = try_parse_int(parts[1], None)
                if a is None or b is None:
                    continue
                if a > b:
                    a, b = b, a
                for v in range(a, b + 1):
                    if v in numeric_names:
                        selected.add(str(v))
            elif re.match(r"^\d+$", token):
                v = try_parse_int(token, None)
                if v is not None and v in numeric_names:
                    selected.add(str(v))
        return selected
    else:
        # Fallback to exact token matching for non-numeric names
        name_set = set(available_names)
        for token in tokens:
            if token in name_set:
                selected.add(token)
        return selected


class CalendarDialog(tk.Toplevel):
    """Simple calendar + time dialog that returns a datetime when confirmed."""

    def __init__(self, master, initial_dt=None):
        tk.Toplevel.__init__(self, master)
        self.title("Select Start Date/Time")
        self.configure(bg=BG_COLOR)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        now = initial_dt or datetime.now()
        self.selected_date = now.date()
        self.hour_var = tk.StringVar()
        self.min_var = tk.StringVar()
        self.hour_var.set("%02d" % now.hour)
        self.min_var.set("%02d" % now.minute)

        self.year = now.year
        self.month = now.month

        outer = tk.Frame(self, bg=BG_COLOR)
        outer.pack(padx=10, pady=10)

        nav = tk.Frame(outer, bg=BG_COLOR)
        nav.pack(fill="x")
        prev_btn = tk.Button(nav, text="<", command=self._prev_month, bg=BUTTON_BG, fg=BUTTON_FG)
        prev_btn.pack(side="left")
        self.month_label = tk.Label(nav, text="", bg=BG_COLOR)
        self.month_label.pack(side="left", expand=True)
        next_btn = tk.Button(nav, text=">", command=self._next_month, bg=BUTTON_BG, fg=BUTTON_FG)
        next_btn.pack(side="right")

        self.days_frame = tk.Frame(outer, bg=BG_COLOR)
        self.days_frame.pack(pady=(6, 6))

        time_frame = tk.Frame(outer, bg=BG_COLOR)
        time_frame.pack(fill="x", pady=(4, 8))
        tk.Label(time_frame, text="Time (HH:MM):", bg=BG_COLOR).pack(side="left")
        hour_entry = tk.Entry(time_frame, width=3, textvariable=self.hour_var)
        hour_entry.pack(side="left", padx=(6, 2))
        tk.Label(time_frame, text=":", bg=BG_COLOR).pack(side="left")
        min_entry = tk.Entry(time_frame, width=3, textvariable=self.min_var)
        min_entry.pack(side="left", padx=(2, 6))

        btns = tk.Frame(outer, bg=BG_COLOR)
        btns.pack(fill="x")
        tk.Button(btns, text="OK", width=10, command=self._on_ok, bg=BUTTON_BG, fg=BUTTON_FG).pack(side="left")
        tk.Button(btns, text="Cancel", width=10, command=self._on_cancel, bg=BUTTON_BG, fg=BUTTON_FG).pack(side="right")

        self.result = None
        self._rebuild_days()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _prev_month(self):
        if self.month == 1:
            self.month = 12
            self.year -= 1
        else:
            self.month -= 1
        self._rebuild_days()

    def _next_month(self):
        if self.month == 12:
            self.month = 1
            self.year += 1
        else:
            self.month += 1
        self._rebuild_days()

    def _pick_day(self, day):
        try:
            self.selected_date = datetime(self.year, self.month, day).date()
            # Highlight selection by rebuilding (simple approach)
            self._rebuild_days(selected_day=day)
        except Exception:
            pass

    def _on_ok(self):
        try:
            hour = max(0, min(23, int(self.hour_var.get())))
            minute = max(0, min(59, int(self.min_var.get())))
            self.result = datetime(self.selected_date.year, self.selected_date.month, self.selected_date.day, hour, minute)
        except Exception:
            messagebox.showerror("Invalid Time", "Please enter a valid time (HH:MM).", parent=self)
            return
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()

    def _rebuild_days(self, selected_day=None):
        for child in self.days_frame.winfo_children():
            child.destroy()
        month_name = pycalendar.month_name[self.month]
        self.month_label.config(text="%s %d" % (month_name, self.year))
        # Weekday headers
        header = tk.Frame(self.days_frame, bg=BG_COLOR)
        header.pack()
        for wd in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]:
            tk.Label(header, width=3, text=wd, bg=BG_COLOR).pack(side="left", padx=2)

        cal = pycalendar.Calendar(firstweekday=0)  # Monday
        for week in cal.monthdayscalendar(self.year, self.month):
            row = tk.Frame(self.days_frame, bg=BG_COLOR)
            row.pack()
            for day in week:
                if day == 0:
                    tk.Label(row, width=3, text="", bg=BG_COLOR).pack(side="left", padx=2)
                else:
                    style = {}
                    if selected_day == day:
                        style = {"relief": "sunken"}
                    b = tk.Button(row, width=3, text=str(day), command=lambda d=day: self._pick_day(d), bg=BUTTON_BG, fg=BUTTON_FG)
                    b.pack(side="left", padx=2)


class ConfigBar(tk.Frame):
    """Top bar: job config name, browse/select (load or choose save dir), save config."""

    def __init__(self, master, mediator):
        tk.Frame.__init__(self, master, bg=BG_COLOR)
        self.mediator = mediator

        self.config_name_var = tk.StringVar()
        self.save_dir = None

        tk.Label(self, text="Job Config name:", bg=BG_COLOR).pack(side="left", padx=(6, 4))
        self.name_entry = tk.Entry(self, width=40, textvariable=self.config_name_var, bg=ENTRY_BG)
        self.name_entry.pack(side="left", padx=(0, 8))

        self.browse_btn = tk.Button(self, text="Browse/Select", command=self._on_browse_select, bg=BUTTON_BG, fg=BUTTON_FG)
        self.browse_btn.pack(side="left", padx=(0, 6))

        self.save_btn = tk.Button(self, text="Save Config", command=self._on_save_config, bg=BUTTON_BG, fg=BUTTON_FG)
        self.save_btn.pack(side="left")

    def _on_browse_select(self):
        # Popup to choose action: Load config or Select save folder
        menu = tk.Toplevel(self)
        menu.title("Choose Action")
        menu.configure(bg=BG_COLOR)
        menu.resizable(False, False)
        menu.transient(self)
        tk.Label(menu, text="Select an action:", bg=BG_COLOR).pack(padx=10, pady=(10, 6))
        tk.Button(menu, text="Load Config...", command=lambda: self._choose_load(menu), width=20, bg=BUTTON_BG, fg=BUTTON_FG).pack(padx=10, pady=3)
        tk.Button(menu, text="Select Save Folder...", command=lambda: self._choose_save_dir(menu), width=20, bg=BUTTON_BG, fg=BUTTON_FG).pack(padx=10, pady=(3, 10))

    def _choose_load(self, dialog):
        dialog.destroy()
        path = filedialog.askopenfilename(title="Select Config JSON", filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            # Set config name from loaded data
            config_name = data.get("config_name", "")
            self.config_name_var.set(config_name)
            self.save_dir = data.get("save_dir") or os.path.dirname(path)
            self.mediator.load_config_data(data)
            # Remember last used config pointer
            try:
                with open(LAST_CONFIG_POINTER, "w") as pf:
                    json.dump({"last_config_path": path}, pf)
            except Exception:
                pass
            messagebox.showinfo("Config Loaded", "Configuration '%s' loaded successfully." % (config_name or "Unnamed"))
        except Exception as ex:
            messagebox.showerror("Load Failed", "Failed to load config: %s" % ex)

    def _choose_save_dir(self, dialog):
        dialog.destroy()
        directory = filedialog.askdirectory(title="Select Save Directory")
        if directory:
            self.save_dir = directory
            messagebox.showinfo("Save Directory", "Selected save directory:\n%s" % directory)

    def _on_save_config(self):
        name = self.config_name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a Job Config name before saving.")
            return
        # Ask for directory if not set
        save_dir = self.save_dir or filedialog.askdirectory(title="Select Save Directory")
        if not save_dir:
            return
        # Ensure directory exists
        try:
            if not os.path.isdir(save_dir):
                os.makedirs(save_dir)
        except Exception:
            pass
        data = self.mediator.build_config_data()
        data["config_name"] = name
        data["save_dir"] = save_dir
        filename = os.path.join(save_dir, "%s.json" % name)
        try:
            with open(filename, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            # Remember last used config pointer
            try:
                with open(LAST_CONFIG_POINTER, "w") as pf:
                    json.dump({"last_config_path": filename}, pf)
            except Exception:
                pass
            messagebox.showinfo("Saved", "Configuration saved to:\n%s" % filename)
        except Exception as ex:
            messagebox.showerror("Save Failed", "Failed to save config: %s" % ex)


class PreplotSelector(tk.Frame):
    """Row: preplot path entry + Browse/Select button to choose the preplot file."""

    def __init__(self, master, mediator):
        tk.Frame.__init__(self, master, bg=BG_COLOR)
        self.mediator = mediator
        self.path_var = tk.StringVar()

        tk.Label(self, text="Select Preplot:", bg=BG_COLOR).pack(side="left", padx=(6, 4))
        self.path_entry = tk.Entry(self, width=60, textvariable=self.path_var, bg=ENTRY_BG)
        self.path_entry.pack(side="left", padx=(0, 8))
        tk.Button(self, text="Browse/Select", command=self._choose_preplot_file, bg=BUTTON_BG, fg=BUTTON_FG).pack(side="left")

    def _choose_preplot_file(self):
        path = filedialog.askopenfilename(title="Select Preplot File", filetypes=[
            ("P1/90 Preplot (*.p190)", "*.p190"),
            ("CSV or Text", "*.csv *.txt"),
            ("All Files", "*.*"),
        ])
        if not path:
            return
        self.path_var.set(path)
        self.mediator.load_preplots_from_file(path)


class ParametersPanel(tk.Frame):
    """Acquisition parameters: Average line speed (knots), linechange minutes, Start Date/Time."""

    def __init__(self, master, mediator):
        tk.Frame.__init__(self, master, bg=BG_COLOR, bd=1, relief="groove")
        self.mediator = mediator

        left = tk.Frame(self, bg=BG_COLOR)
        left.pack(side="left", fill="x", expand=True, padx=6, pady=6)

        # Row 0: Average line speed in knots
        tk.Label(left, text="Average Line Speed (knots):", bg=BG_COLOR).grid(row=0, column=0, sticky="w")
        self.speed_knots_var = tk.StringVar()
        speed_entry = tk.Entry(left, width=12, textvariable=self.speed_knots_var, bg=ENTRY_BG)
        speed_entry.grid(row=0, column=1, padx=(6, 16), sticky="w")
        speed_entry.bind("<FocusOut>", self._on_speed_change)
        speed_entry.bind("<Return>", self._on_speed_change)

        # Average Linechange time (minutes)
        tk.Label(left, text="Average Linechange (min):", bg=BG_COLOR).grid(row=0, column=2, sticky="w")
        self.linechange_var = tk.StringVar()
        tk.Entry(left, width=12, textvariable=self.linechange_var, bg=ENTRY_BG).grid(row=0, column=3, padx=(6, 16), sticky="w")

        # Percentage Allowance (+/-)
        tk.Label(left, text="Percentage Allowance (+/-):", bg=BG_COLOR).grid(row=0, column=4, sticky="w")
        self.pct_allowance_var = tk.StringVar()
        tk.Entry(left, width=12, textvariable=self.pct_allowance_var, bg=ENTRY_BG).grid(row=0, column=5, padx=(6, 16), sticky="w")

        # Shot Interval (meters)
        tk.Label(left, text="Shot Interval (m):", bg=BG_COLOR).grid(row=0, column=6, sticky="w")
        self.shot_interval_var = tk.StringVar()
        interval_entry = tk.Entry(left, width=12, textvariable=self.shot_interval_var, bg=ENTRY_BG)
        interval_entry.grid(row=0, column=7, padx=(6, 16), sticky="w")
        interval_entry.bind("<FocusOut>", self._on_params_change)
        interval_entry.bind("<Return>", self._on_params_change)

        # Shot Increment
        tk.Label(left, text="Shot Increment:", bg=BG_COLOR).grid(row=0, column=8, sticky="w")
        self.shot_increment_var = tk.StringVar()
        increment_entry = tk.Entry(left, width=12, textvariable=self.shot_increment_var, bg=ENTRY_BG)
        increment_entry.grid(row=0, column=9, padx=(6, 16), sticky="w")
        increment_entry.bind("<FocusOut>", self._on_params_change)
        increment_entry.bind("<Return>", self._on_params_change)

        # Row 1: Start Date/Time button and Use Current Time toggle (moved below average line speed)
        self.start_dt_label = tk.Label(left, text="Start: not set", bg=BG_COLOR)
        self.start_dt_label.grid(row=1, column=0, columnspan=1, padx=(6, 8), pady=(6, 0), sticky="w")
        self.start_btn = tk.Button(left, text="Start Date/Time...", command=self._pick_start_dt, bg=BUTTON_BG, fg=BUTTON_FG)
        self.start_btn.grid(row=1, column=1, pady=(6, 0), sticky="w")
        self.use_current_var = tk.IntVar(value=0)
        self.use_current_chk = tk.Checkbutton(left, text="Use Current Time", variable=self.use_current_var, command=self._on_toggle_use_current, bg=BG_COLOR)
        self.use_current_chk.grid(row=1, column=2, columnspan=2, padx=(6, 0), pady=(6, 0), sticky="w")

        # Grid config
        for c in range(10):
            left.grid_columnconfigure(c, weight=0)
        left.grid_columnconfigure(1, weight=0)

    def _pick_start_dt(self):
        dlg = CalendarDialog(self, initial_dt=self.mediator.state.get("start_dt") or datetime.now())
        self.wait_window(dlg)
        if dlg.result is not None:
            self.mediator.state["start_dt"] = dlg.result
            self.start_dt_label.config(text="Start: %s" % dlg.result.strftime("%Y-%m-%d %H:%M"))

    def _on_toggle_use_current(self):
        use_now = bool(self.use_current_var.get())
        if use_now:
            try:
                self.start_btn.config(state=tk.DISABLED)
            except Exception:
                self.start_btn.config(state="disabled")
            now = datetime.now()
            self.mediator.state["start_dt"] = now
            self.start_dt_label.config(text="Start: current system time (%s)" % now.strftime("%Y-%m-%d %H:%M"))
        else:
            try:
                self.start_btn.config(state=tk.NORMAL)
            except Exception:
                self.start_btn.config(state="normal")

    def _on_speed_change(self, event=None):
        """Recalculate durations when speed changes."""
        if hasattr(self.mediator, 'state') and self.mediator.state.get("preplot_items"):
            self.mediator._calculate_durations(self.mediator.state["preplot_items"])
            self.mediator.list_panel.populate(self.mediator.state["preplot_items"])

    def _on_params_change(self, event=None):
        """Recalculate line lengths and durations when shot interval or increment changes."""
        if hasattr(self.mediator, 'state') and self.mediator.state.get("preplot_items"):
            # Recalculate line lengths with new parameters
            self.mediator._recalculate_line_lengths_and_durations()


class PreplotListPanel(tk.Frame):
    """Scrollable preplot list (Treeview) with columns: Name, FSP, LSP, Line Length."""

    def __init__(self, master, mediator):
        tk.Frame.__init__(self, master, bg=BG_COLOR)
        self.mediator = mediator

        # Style Treeview for background
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure("Custom.Treeview", background=BG_COLOR, fieldbackground=BG_COLOR)
        style.configure("Custom.Treeview.Heading", background=BUTTON_BG)
        # Ensure selected rows are visibly highlighted in green and bold
        try:
            bold_font = tkfont.nametofont("TkDefaultFont").copy()
            bold_font.configure(weight="bold")
            style.configure("Custom.Treeview", font=bold_font)
            style.map("Custom.Treeview",
                      background=[('selected', '#7CFC00')],  # LawnGreen
                      foreground=[('selected', 'black')],
                      font=[('selected', bold_font)])
        except Exception:
            try:
                style.map("Custom.Treeview",
                          background=[('selected', '#7CFC00')],
                          foreground=[('selected', 'black')])
            except Exception:
                pass

        columns = ("name", "fsp", "lsp", "length_m", "duration_hrs")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended", style="Custom.Treeview")
        self.tree.heading("name", text="Preplot Name")
        self.tree.heading("fsp", text="FSP")
        self.tree.heading("lsp", text="LSP")
        self.tree.heading("length_m", text="Line Length (m)")
        self.tree.heading("duration_hrs", text="Line Duration (Hrs.)")
        self.tree.column("name", width=140, anchor="w")
        self.tree.column("fsp", width=70, anchor="center")
        self.tree.column("lsp", width=70, anchor="center")
        self.tree.column("length_m", width=120, anchor="e")
        self.tree.column("duration_hrs", width=130, anchor="e")

        vsb = tk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=(4, 6))
        vsb.pack(side="left", fill="y", padx=(0, 6), pady=(4, 6))

        self.tree.bind("<<TreeviewSelect>>", self._on_selection_change)

    def populate(self, items):
        # items: list of dicts with keys: name, fsp, lsp, length_m, duration_hrs
        for i in self.tree.get_children():
            self.tree.delete(i)
        for item in items:
            length_m = item.get("length_m", 0.0) or 0.0
            duration_hrs = item.get("duration_hrs", 0.0) or 0.0
            self.tree.insert("", "end", iid=str(item["name"]), values=(
                item["name"], 
                item["fsp"], 
                item["lsp"], 
                "%.0f" % float(length_m),
                "%.2f" % float(duration_hrs)
            ))

    def select_names(self, names):
        # Clear then select
        try:
            if not names:
                self.tree.selection_set(())
                return
            name_set = [str(n) for n in names]
            # Only select items that exist in the tree
            valid_iids = []
            for iid in self.tree.get_children():
                if iid in name_set:
                    valid_iids.append(iid)
            self.tree.selection_set(valid_iids)
            # Ensure view moves to first selected if any
            sel = self.tree.selection()
            if sel:
                self.tree.see(sel[0])
        except Exception:
            # Fallback to previous behavior
            self.tree.selection_remove(self.tree.selection())
            name_set = set(str(n) for n in names)
            for iid in self.tree.get_children():
                if iid in name_set:
                    self.tree.selection_add(iid)
            sel = self.tree.selection()
            if sel:
                self.tree.see(sel[0])

    def _on_selection_change(self, event):
        names = [self.tree.set(iid, "name") for iid in self.tree.selection()]
        self.mediator.on_tree_selection(names)


class InclusionPanel(tk.Frame):
    """Entry for inclusion expression and instruction label."""

    def __init__(self, master, mediator):
        tk.Frame.__init__(self, master, bg=BG_COLOR)
        self.mediator = mediator
        self.expr_var = tk.StringVar()

        tk.Label(self, text="Preplots to include in Estimate:", bg=BG_COLOR).pack(side="left", padx=(6, 6))
        self.entry = tk.Entry(self, width=60, textvariable=self.expr_var, bg=ENTRY_BG)
        self.entry.pack(side="left", padx=(0, 8))
        self.entry.bind("<Return>", self._apply_expr)
        self.entry.bind("<FocusOut>", self._apply_expr)

        hint = "Use ALL or ranges like 1001-1010, 1012, 1020-1030 or Select Preplot lines from the Preplot List"
        tk.Label(self, text=hint, bg=BG_COLOR).pack(side="left", padx=(0, 6))

    def set_expression_from_names(self, names):
        if not names:
            self.expr_var.set("")
            return
        if all(is_string_numeric(n) for n in names):
            nums = [int(n) for n in names]
            self.expr_var.set(compress_numeric_ranges(nums))
        else:
            self.expr_var.set(", ".join(sorted(names)))

    def _apply_expr(self, event=None):
        expr = self.expr_var.get()
        self.mediator.on_expr_entered(expr)


class ResultsPanel(tk.Frame):
    """Results window and Estimate button."""

    def __init__(self, master, mediator):
        tk.Frame.__init__(self, master, bg=BG_COLOR)
        self.mediator = mediator

        self.text = tk.Text(self, height=8, bg="white", fg=TEXT_FG, state="disabled")
        self.text.pack(fill="both", expand=True, padx=6, pady=(4, 6))

        btn = tk.Button(self, text="Estimate", command=self.mediator.on_estimate, bg=BUTTON_BG, fg=BUTTON_FG)
        btn.pack(pady=(0, 8))

    def show_text(self, content):
        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, content)
        self.text.config(state="disabled")


class JCEApp(tk.Tk):
    """Mediator-style controller and application window."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.wm_title(APP_TITLE)
        self.configure(bg=BG_COLOR)
        try:
            self.wm_iconname(APP_TITLE)
        except Exception:
            pass

        # Global state managed by mediator
        self.state = {
            "start_dt": None,
            "preplot_items": [],  # list of dicts: name, fsp, lsp, length_m, shots
            "shot_interval_m": None,
        }

        # Build UI layout
        self._build_ui()
        # Attempt to auto-load last config and restore window geometry
        self._geometry_restored = False
        self._autoload_last_config()
        # Set up auto-save on window close
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        # If no geometry was restored, set a sensible default
        try:
            if not self._geometry_restored:
                self.geometry("1800x840")
        except Exception:
            pass

    def _build_ui(self):
        # Top bar
        self.config_bar = ConfigBar(self, self)
        # Default save directory to script folder unless changed by user or loaded config
        try:
            self.config_bar.save_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            self.config_bar.save_dir = None
        self.config_bar.pack(fill="x", pady=(8, 4))

        # Preplot selector
        self.preplot_selector = PreplotSelector(self, self)
        self.preplot_selector.pack(fill="x", pady=(0, 8))

        # Acquisition parameters
        self.params_panel = ParametersPanel(self, self)
        self.params_panel.pack(fill="x", padx=6, pady=(0, 8))

        # Preplot list
        tk.Label(self, text="Preplot List:", bg=BG_COLOR).pack(anchor="w", padx=6)
        self.list_panel = PreplotListPanel(self, self)
        self.list_panel.pack(fill="both", expand=True, padx=0, pady=(0, 8))

        # Inclusion box
        self.inclusion_panel = InclusionPanel(self, self)
        self.inclusion_panel.pack(fill="x", pady=(0, 8))

        # Results
        tk.Label(self, text="Result Window:", bg=BG_COLOR).pack(anchor="w", padx=6)
        self.results_panel = ResultsPanel(self, self)
        self.results_panel.pack(fill="both", expand=False, padx=0, pady=(0, 8))

    def _autoload_last_config(self):
        # Load window geometry if present in last config; otherwise, use saved pointer to a config file
        try:
            loaded = False
            path = None
            if os.path.isfile(LAST_CONFIG_POINTER):
                with open(LAST_CONFIG_POINTER, 'r') as pf:
                    meta = json.load(pf)
                path = meta.get('last_config_path')
                if path and os.path.isfile(path):
                    loaded = True
            if not loaded:
                # Fallback: load most recent JSON in script directory
                script_dir = os.path.dirname(os.path.abspath(__file__))
                json_files = [os.path.join(script_dir, f) for f in os.listdir(script_dir) if f.lower().endswith('.json')]
                if json_files:
                    json_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                    path = json_files[0]
                    loaded = True
            if loaded and path:
                with open(path, 'r') as f:
                    data = json.load(f)
                # Set config name and save directory from loaded data
                config_name = data.get("config_name", "")
                if config_name:
                    self.config_bar.config_name_var.set(config_name)
                save_dir = data.get("save_dir") or os.path.dirname(path)
                self.config_bar.save_dir = save_dir
                # Apply config data
                self.load_config_data(data)
                # Restore geometry if present
                win = data.get('window', {})
                geom = win.get('geometry')
                if geom:
                    try:
                        self.geometry(geom)
                        self._geometry_restored = True
                    except Exception:
                        pass
        except Exception:
            # Ignore failures silently
            pass

    def _on_window_close(self):
        """Auto-save current state when window is closing."""
        try:
            # Capture current window geometry before anything is destroyed
            try:
                self.update_idletasks()
            except Exception:
                pass
            current_geometry = self.geometry()
            
            # Capture current selection before widgets are destroyed
            try:
                selected_items = [self.list_panel.tree.set(iid, "name") for iid in self.list_panel.tree.selection()]
                inclusion_expr = self.inclusion_panel.expr_var.get().strip()
            except Exception:
                selected_items = []
                inclusion_expr = ""
            
            # Build config data with captured values
            data = {
                "preplot_path": self.preplot_selector.path_var.get().strip(),
                "inclusion_expr": inclusion_expr,
                "parameters": {
                    "avg_speed_knots": self._get_float(self.params_panel.speed_knots_var.get()),
                    "linechange_min": self._get_float(self.params_panel.linechange_var.get()),
                    "pct_allowance": self._get_float(self.params_panel.pct_allowance_var.get()),
                    "start_dt_iso": self.state.get("start_dt").isoformat() if self.state.get("start_dt") else None,
                    "use_current_time": bool(getattr(self.params_panel, 'use_current_var', tk.IntVar(value=0)).get()),
                    "shot_interval_m": self._get_float(self.params_panel.shot_interval_var.get()),
                    "shot_increment": self._get_float(self.params_panel.shot_increment_var.get()),
                },
                "preplot_data": {
                    "items": self.state.get("preplot_items", []),
                    "shot_interval_detected": self.state.get("shot_interval_m"),
                    "selected_items": selected_items,
                    "inclusion_expression": inclusion_expr,
                },
                "window": {
                    "geometry": current_geometry,
                },
            }
            
            # Use current config name or default to "auto_save"
            config_name = self.config_bar.config_name_var.get().strip() or "auto_save"
            data["config_name"] = config_name
            
            # Resolve save directory preference order:
            # 1) User-selected save_dir from ConfigBar
            # 2) Directory of last loaded/saved config (from LAST_CONFIG_POINTER)
            # 3) Application directory
            save_dir = getattr(self.config_bar, 'save_dir', None)
            if not save_dir:
                try:
                    if os.path.isfile(LAST_CONFIG_POINTER):
                        with open(LAST_CONFIG_POINTER, 'r') as pf:
                            meta = json.load(pf)
                        last_path = meta.get('last_config_path')
                        if last_path:
                            save_dir = os.path.dirname(last_path)
                except Exception:
                    save_dir = None
            if not save_dir:
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Ensure directory exists
            try:
                if not os.path.isdir(save_dir):
                    os.makedirs(save_dir)
            except Exception:
                pass
            
            data["save_dir"] = save_dir
            filename = os.path.join(save_dir, "%s.json" % config_name)
            
            with open(filename, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            
            # Update last config pointer
            with open(LAST_CONFIG_POINTER, "w") as pf:
                json.dump({"last_config_path": filename}, pf)
        except Exception:
            # Ignore save errors on close
            pass
        
        # Close the application
        self.destroy()

    # Mediator callbacks and helpers
    def load_config_data(self, data):
        # Set preplot path
        preplot_path = data.get("preplot_path") or ""
        if preplot_path:
            self.preplot_selector.path_var.set(preplot_path)
            
        # Load saved preplot data if available, otherwise parse from file
        preplot_data = data.get("preplot_data", {})
        saved_items = preplot_data.get("items", [])
        # Capture saved selection/inclusion early so it can be reused after any repopulate
        saved_selection = preplot_data.get("selected_items", [])
        saved_inclusion = preplot_data.get("inclusion_expression", "")
        
        if saved_items:
            # Use saved preplot data (with calculated lengths and durations)
            self.state["preplot_items"] = saved_items
            saved_interval = preplot_data.get("shot_interval_detected")
            if saved_interval is not None:
                self.state["shot_interval_m"] = saved_interval
            self.list_panel.populate(saved_items)
            
            # Restore saved inclusion expression (if any)
            if saved_inclusion:
                self.inclusion_panel.expr_var.set(saved_inclusion)
            
            # Restore tree selection (if any)
            if saved_selection:
                try:
                    self.list_panel.select_names(saved_selection)
                except Exception:
                    pass
                # Schedule a deferred re-apply to survive any later repopulate/paint
                try:
                    self.after(0, lambda sel=list(saved_selection): self.list_panel.select_names(sel))
                except Exception:
                    pass
            applied_saved_selection = bool(saved_selection)
        elif preplot_path:
            # No saved data, parse from file
            try:
                self.load_preplots_from_file(preplot_path)
            except Exception:
                pass
        # Parameters
        params = data.get("parameters", {})
        self.params_panel.speed_knots_var.set(str(params.get("avg_speed_knots", "")))
        self.params_panel.linechange_var.set(str(params.get("linechange_min", "")))
        self.params_panel.pct_allowance_var.set(str(params.get("pct_allowance", "")))
        if params.get("shot_interval_m") is not None:
            self.params_panel.shot_interval_var.set(str(params.get("shot_interval_m")))
            self.state["shot_interval_m"] = params.get("shot_interval_m")
        if params.get("shot_increment") is not None:
            self.params_panel.shot_increment_var.set(str(params.get("shot_increment")))
        start_iso = params.get("start_dt_iso")
        if start_iso:
            try:
                dt = datetime.fromisoformat(start_iso)
            except Exception:
                try:
                    dt = datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%S")
                except Exception:
                    dt = None
            if dt is not None:
                self.state["start_dt"] = dt
                self.params_panel.start_dt_label.config(text="Start: %s" % dt.strftime("%Y-%m-%d %H:%M"))
        use_now = params.get("use_current_time", False)
        try:
            self.params_panel.use_current_var.set(1 if use_now else 0)
            self.params_panel._on_toggle_use_current()
        except Exception:
            pass
        # Inclusion
        inclusion_expr = data.get("inclusion_expr", "")
        # Only apply inclusion expression if we didn't already restore a saved selection
        if not locals().get('applied_saved_selection', False) and inclusion_expr:
            self.inclusion_panel.expr_var.set(inclusion_expr)
            # Apply to selection if items exist
            if self.state["preplot_items"]:
                self.on_expr_entered(inclusion_expr)
        
        # Recalculate durations with loaded speed parameters if preplot data exists
        if saved_items and params.get("avg_speed_knots"):
            self._calculate_durations(self.state["preplot_items"])
            self.list_panel.populate(self.state["preplot_items"])
            # Re-apply saved selection after repopulating
            if saved_selection:
                try:
                    self.list_panel.select_names(saved_selection)
                except Exception:
                    pass
                # And defer once more to ensure it sticks
                try:
                    self.after(0, lambda sel=list(saved_selection): self.list_panel.select_names(sel))
                except Exception:
                    pass

    def build_config_data(self):
        # Get current window geometry
        try:
            current_geometry = self.geometry()
        except Exception:
            current_geometry = "1800x840+100+100"  # fallback
            
        return {
            "preplot_path": self.preplot_selector.path_var.get().strip(),
            "inclusion_expr": self.inclusion_panel.expr_var.get().strip(),
            "parameters": {
                "avg_speed_knots": self._get_float(self.params_panel.speed_knots_var.get()),
                "linechange_min": self._get_float(self.params_panel.linechange_var.get()),
                "pct_allowance": self._get_float(self.params_panel.pct_allowance_var.get()),
                "start_dt_iso": self.state.get("start_dt").isoformat() if self.state.get("start_dt") else None,
                "use_current_time": bool(getattr(self.params_panel, 'use_current_var', tk.IntVar(value=0)).get()),
                "shot_interval_m": self._get_float(self.params_panel.shot_interval_var.get()),
                "shot_increment": self._get_float(self.params_panel.shot_increment_var.get()),
            },
            "preplot_data": {
                "items": self.state.get("preplot_items", []),
                "shot_interval_detected": self.state.get("shot_interval_m"),
                "selected_items": [self.list_panel.tree.set(iid, "name") for iid in self.list_panel.tree.selection()],
                "inclusion_expression": self.inclusion_panel.expr_var.get().strip(),
            },
            "window": {
                "geometry": current_geometry,
            },
        }

    def load_preplots_from_file(self, path):
        items = self._parse_preplot_file(path)
        # Calculate duration for each item based on current speed setting
        self._calculate_durations(items)
        self.state["preplot_items"] = items
        self.list_panel.populate(items)
        # Clear expression/selection on new load
        self.inclusion_panel.expr_var.set("")

    def _parse_preplot_file(self, path):
        """Parse preplot file.

        Supports:
        - CSV/TXT with header columns (auto-detected)
        - P1/90 style `.p190` text with lines like:
            V51892  14288  082057.01N0565319.96W
            V51900  14732  081913.29N0565051.35W
          or compact variants containing both FSP+LSP coords over two lines.
        """
        if not os.path.isfile(path):
            messagebox.showerror("File Not Found", "Preplot file does not exist: %s" % path)
            return []

        # Strategy: First attempt parse as P1/90. If fails, fallback to CSV DictReader.
        try:
            with open(path, 'rU') as f:
                content = f.read()
        except Exception as ex:
            messagebox.showerror("Read Failed", "Failed to read preplot file: %s" % ex)
            return []

        items = self._try_parse_p190(content)
        if items:
            return items

        # Fallback: CSV with headers
        rows = []
        try:
            from io import BytesIO
        except Exception:
            BytesIO = None
        try:
            # Re-open for csv reader
            with open(path, 'rU') as f:
                sample = f.read(2048)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except Exception:
                    dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)
                for r in reader:
                    rows.append(r)
        except Exception as ex:
            messagebox.showerror("Read Failed", "Failed to read preplot file: %s" % ex)
            return []

        if not rows:
            return []

        headers = [h.lower().strip() for h in rows[0].keys()]

        def get_val(row, *candidates):
            for c in candidates:
                for h in row:
                    if h.lower().strip() == c:
                        return row[h]
            return None

        items = []
        for row in rows:
            name = get_val(row, "name", "preplot", "line", "preplot_name")
            fsp = try_parse_int(get_val(row, "fsp", "first_sp", "f_sp", "start_sp"), None)
            lsp = try_parse_int(get_val(row, "lsp", "last_sp", "l_sp", "end_sp"), None)

            slat = get_val(row, "start_lat", "lat_start", "y1", "lat1")
            slon = get_val(row, "start_lon", "lon_start", "x1", "lon1")
            elat = get_val(row, "end_lat", "lat_end", "y2", "lat2")
            elon = get_val(row, "end_lon", "lon_end", "x2", "lon2")

            sx = get_val(row, "start_x", "x_start", "easting1", "x1")
            sy = get_val(row, "start_y", "y_start", "northing1", "y1")
            ex_ = get_val(row, "end_x", "x_end", "easting2", "x2")
            ey = get_val(row, "end_y", "y_end", "northing2", "y2")

            length_km = 0.0
            try:
                if slat is not None and slon is not None and elat is not None and elon is not None:
                    length_km = haversine_distance_km(float(slat), float(slon), float(elat), float(elon))
                elif sx is not None and sy is not None and ex_ is not None and ey is not None:
                    length_km = euclidean_distance_km(float(sx), float(sy), float(ex_), float(ey))
            except Exception:
                length_km = 0.0

            if name is None:
                continue
            name = str(name).strip()
            shots = None
            if fsp is not None and lsp is not None:
                shots = max(0, (lsp - fsp + 1))
            items.append({
                "name": name,
                "fsp": fsp if fsp is not None else "",
                "lsp": lsp if lsp is not None else "",
                "length_m": float(length_km) * 1000.0,
                "duration_hrs": 0.0,  # Will be calculated later
                "shots": shots,
            })

        return items

    def _try_parse_p190(self, content):
        """Parse P1/90 style text content where preplot lines are encoded with compact lat/lon.

        We look for two consecutive lines per preplot like:
          V51892 ... 082057.01N0565319.96W ...
          V51900 ... 081913.29N0565051.35W ...
        We infer name from the first line token (e.g., 51892).
        FSP from first line number, LSP from second line number, and compute length
        using the two lat/lon pairs.
        """
        lines = [ln.rstrip('\n') for ln in content.splitlines()]
        # Extract SHOT POINT INTERVAL from header if present (meters), be tolerant of spacing and prefixes like H2600
        sp_int_m = None
        spi_match = re.search(r"SHOT\s+POINT\s+INTERVAL\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*m", content, re.IGNORECASE)
        if spi_match:
            try:
                sp_int_m = float(spi_match.group(1))
            except Exception:
                sp_int_m = None
        # Persist into state and UI
        if sp_int_m is not None:
            self.state["shot_interval_m"] = sp_int_m
            try:
                self.params_panel.shot_interval_var.set(str(sp_int_m))
            except Exception:
                pass

        # Identify candidate lines with compact lat/lon. Extract SP from concatenated SP+lat/lon format.
        # Example: V51892  14288082057.01N0565319.96W -> SP=14288, lat/lon=082057.01N0565319.96W
        pattern = re.compile(r"V(?P<name>\d+)\s+(?P<sp_ll>\d+\.?\d*[NS]\d+\.?\d*[EW])")
        candidates = []
        for ln in lines:
            m = pattern.search(ln)
            if m:
                sp_ll = m.group('sp_ll')
                # Split SP from lat/lon: SP digits + lat/lon in DDMMSS.SSN format
                # Look for lat/lon pattern: DDMMSS.SSN where DD=degrees, MM=minutes, SS.SS=seconds, N/S=hemisphere
                # Example: 082057.01N0565319.96W -> lat starts at position where we find DDMMSS.SSN pattern
                lat_match = re.search(r"(\d{6}\.\d+[NS]\d{7}\.\d+[EW])$", sp_ll)
                if lat_match:
                    ll = lat_match.group(1)
                    sp = sp_ll[:lat_match.start()]
                else:
                    # Alternative pattern with leading zero: 0DDMMSS.SSN
                    lat_match2 = re.search(r"(0\d{5}\.\d+[NS]0?\d{6,7}\.\d+[EW])$", sp_ll)
                    if lat_match2:
                        ll = lat_match2.group(1)
                        sp = sp_ll[:lat_match2.start()]
                    else:
                        # No valid lat/lon found, skip this line
                        sp = None
                        ll = sp_ll
                candidates.append((m.group('name'), sp, ll))

        # Pair consecutive candidate lines as FSP (first) and LSP (second).
        # Both lines should have the same V-name but different SP values.
        items = []
        i = 0
        while i < len(candidates) - 1:
            name1, sp1, ll1 = candidates[i]
            name2, sp2, ll2 = candidates[i + 1]
            # Only pair if both lines have the same V-name (same preplot)
            if name1 != name2:
                i += 1
                continue
            # If an odd number of candidates ends list, break gracefully
            lat1, lon1 = parse_compact_latlon(ll1)
            lat2, lon2 = parse_compact_latlon(ll2)
            length_km = 0.0
            # Use interval from header or UI; header wins, otherwise read from state/UI
            if sp_int_m is None:
                sp_int_m = self.state.get("shot_interval_m") or self._get_float(getattr(self.params_panel, 'shot_interval_var', tk.StringVar()).get())
            # Get shot increment from UI (default to 1 if empty)
            shot_increment = self._get_float(getattr(self.params_panel, 'shot_increment_var', tk.StringVar()).get()) or 1.0
            
            if sp_int_m is not None and sp1 and sp2:
                a = try_parse_int(sp1, None)
                b = try_parse_int(sp2, None)
                if a is not None and b is not None:
                    # New formula: (abs(FSP-LSP)/Shot Increment) × Shot Interval
                    shot_diff = abs(b - a)
                    shots_count = shot_diff / shot_increment
                    length_km = (shots_count * sp_int_m) / 1000.0
            elif lat1 is not None and lat2 is not None:
                length_km = haversine_distance_km(lat1, lon1, lat2, lon2)
            fsp = try_parse_int(sp1, None)
            lsp = try_parse_int(sp2, None)
            shots = None
            if fsp is not None and lsp is not None:
                shots = max(0, (abs(lsp - fsp) + 1))
            items.append({
                "name": str(name1),
                "fsp": fsp if fsp is not None else "",
                "lsp": lsp if lsp is not None else "",
                "length_m": float(length_km) * 1000.0,
                "duration_hrs": 0.0,  # Will be calculated later
                "shots": shots,
            })
            i += 2

        return items

    def _calculate_durations(self, items):
        """Calculate duration in hours for each preplot line based on length and average speed."""
        try:
            speed_knots = self._get_float(self.params_panel.speed_knots_var.get())
            if speed_knots is None or speed_knots <= 0:
                speed_knots = 1.0  # Default to avoid division by zero
            
            # Convert knots to m/h: 1 knot = 1852 m/h
            speed_mh = speed_knots * 1852.0
            
            for item in items:
                length_m = float(item.get("length_m", 0.0) or 0.0)
                # Duration = distance / speed (both in same units: meters and m/h)
                duration_hrs = length_m / speed_mh if speed_mh > 0 else 0.0
                item["duration_hrs"] = duration_hrs
        except Exception:
            # If there's any error, set all durations to 0
            for item in items:
                item["duration_hrs"] = 0.0

    def _recalculate_line_lengths_and_durations(self):
        """Recalculate line lengths and durations for all preplot items when parameters change."""
        items = self.state.get("preplot_items", [])
        if not items:
            return
            
        # Get current parameters
        try:
            shot_interval = self._get_float(self.params_panel.shot_interval_var.get())
            shot_increment = self._get_float(self.params_panel.shot_increment_var.get()) or 1.0
            
            if shot_interval is not None and shot_interval > 0:
                # Recalculate line lengths for each item
                for item in items:
                    fsp = try_parse_int(item.get("fsp"), None)
                    lsp = try_parse_int(item.get("lsp"), None)
                    
                    if fsp is not None and lsp is not None:
                        # Use new formula: (abs(FSP-LSP)/Shot Increment) × Shot Interval
                        shot_diff = abs(lsp - fsp)
                        shots_count = shot_diff / shot_increment
                        length_m = shots_count * shot_interval
                        item["length_m"] = float(length_m)
                    else:
                        item["length_m"] = 0.0
            
            # Recalculate durations with updated lengths
            self._calculate_durations(items)
            
            # Update the display
            self.list_panel.populate(items)
            
        except Exception:
            # If there's an error, just skip the recalculation
            pass

    def on_tree_selection(self, names):
        # Update expression entry when selection made in tree
        self.inclusion_panel.set_expression_from_names(names)

    def on_expr_entered(self, expr):
        available = [str(it["name"]) for it in self.state["preplot_items"]]
        selected = parse_inclusion_expression(expr, available)
        # Update the selection in the list to mirror the inclusion expression
        try:
            self.list_panel.select_names(selected)
        except Exception:
            pass
        self.list_panel.select_names(selected)

    def on_estimate(self):
        # Determine selected names
        available = [str(it["name"]) for it in self.state["preplot_items"]]
        expr = self.inclusion_panel.expr_var.get().strip()
        names = parse_inclusion_expression(expr, available) if expr else set([self.list_panel.tree.set(iid, "name") for iid in self.list_panel.tree.selection()])
        if not names:
            messagebox.showwarning("No Selection", "Please select preplots or enter an inclusion expression.")
            return

        # Map selection to items preserving display order
        items_by_name = {str(it["name"]): it for it in self.state["preplot_items"]}
        ordered_names = []
        if all(is_string_numeric(n) for n in names):
            ordered_names = [str(n) for n in sorted([int(n) for n in names])]
        else:
            # Keep UI order
            for iid in self.list_panel.tree.get_children():
                n = self.list_panel.tree.set(iid, "name")
                if n in names:
                    ordered_names.append(n)

        # Parameters
        speed_knots = self._get_float(self.params_panel.speed_knots_var.get())
        if speed_knots is None or speed_knots <= 0:
            messagebox.showerror("Invalid Speed", "Please enter a positive value for Average Line Speed (knots).")
            return
        linechange_min = self._get_float(self.params_panel.linechange_var.get()) or 0.0
        # Resolve start datetime; if Use Current Time is ticked, refresh it now
        if hasattr(self.params_panel, 'use_current_var') and bool(self.params_panel.use_current_var.get()):
            self.state["start_dt"] = datetime.now()
            self.params_panel.start_dt_label.config(text="Start: current system time (%s)" % self.state["start_dt"].strftime("%Y-%m-%d %H:%M"))
        start_dt = self.state.get("start_dt")
        if start_dt is None:
            messagebox.showerror("Start Time Missing", "Please pick a Start Date/Time.")
            return

        total_hours = 0.0
        total_length_km = 0.0
        line_count = 0
        for idx, name in enumerate(ordered_names):
            item = items_by_name.get(name)
            if not item:
                continue
            line_count += 1
            # Time from length and speed: 1 knot = 1.852 km/h
            # We store length_m now; convert to km for time calc
            length_km = (float(item.get("length_m", 0.0)) or 0.0) / 1000.0
            if length_km > 0:
                total_hours += length_km / (float(speed_knots) * 1.852)
            # Add linechange except after last line
            if idx < len(ordered_names) - 1:
                total_hours += (linechange_min / 60.0)
            total_length_km += length_km

        # Apply percentage allowance (+/-)
        pct_allowance = self._get_float(self.params_panel.pct_allowance_var.get()) or 0.0
        hours_before_allowance = total_hours
        if pct_allowance != 0.0:
            total_hours = total_hours * (1.0 + pct_allowance / 100.0)

        completion_dt = start_dt + timedelta(hours=total_hours)
        days = total_hours / 24.0

        report = []
        report.append("Lines included: %d" % line_count)
        report.append("Total Length: %.0f m (%.3f km)" % (total_length_km * 1000.0, total_length_km))
        report.append("Average Speed: %.3f knots (%.3f km/h)" % (speed_knots, speed_knots * 1.852))
        report.append("Linechange: %.1f min" % linechange_min)
        if pct_allowance != 0.0:
            report.append("Percentage Allowance: %.1f%%" % pct_allowance)
            report.append("Hours before allowance: %.2f" % hours_before_allowance)
        report.append("")
        report.append("Start: %s" % start_dt.strftime("%Y-%m-%d %H:%M"))
        report.append("Completion: %s" % completion_dt.strftime("%Y-%m-%d %H:%M"))
        report.append("Total Hours: %.2f" % total_hours)
        report.append("Total Days: %.2f" % days)

        self.results_panel.show_text("\n".join(report))
        
        # Auto-save current state including selection when estimate is run
        self._auto_save_on_estimate()

    def _auto_save_on_estimate(self):
        """Auto-save current state including selection when estimate button is pressed."""
        try:
            # Build current config data including current selection
            data = self.build_config_data()
            # Use current config name or default to "last_estimate"
            config_name = self.config_bar.config_name_var.get().strip() or "last_estimate"
            data["config_name"] = config_name
            
            # Resolve save directory preference order:
            # 1) User-selected save_dir from ConfigBar
            # 2) Directory of last loaded/saved config (from LAST_CONFIG_POINTER)
            # 3) Application directory
            save_dir = getattr(self.config_bar, 'save_dir', None)
            if not save_dir:
                try:
                    if os.path.isfile(LAST_CONFIG_POINTER):
                        with open(LAST_CONFIG_POINTER, 'r') as pf:
                            meta = json.load(pf)
                        last_path = meta.get('last_config_path')
                        if last_path:
                            save_dir = os.path.dirname(last_path)
                except Exception:
                    save_dir = None
            if not save_dir:
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Ensure directory exists
            try:
                if not os.path.isdir(save_dir):
                    os.makedirs(save_dir)
            except Exception:
                pass
            
            data["save_dir"] = save_dir
            filename = os.path.join(save_dir, "%s.json" % config_name)
            
            with open(filename, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            
            # Update last config pointer
            with open(LAST_CONFIG_POINTER, "w") as pf:
                json.dump({"last_config_path": filename}, pf)
        except Exception:
            # Ignore save errors during estimate
            pass

    def _get_float(self, value):
        try:
            return float(str(value).strip())
        except Exception:
            return None


def main():
    app = JCEApp()
    # Make buttons have consistent colors
    app.option_add("*Button.background", BUTTON_BG)
    app.option_add("*Button.foreground", BUTTON_FG)
    app.option_add("*Label.background", BG_COLOR)
    app.option_add("*Frame.background", BG_COLOR)
    app.mainloop()


if __name__ == "__main__":
    main()
