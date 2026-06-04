#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
xWD — ShotInfo day stitcher

- Reads ShotInfo CSV files from an input folder (top-level only)
- Stitches rows by day based on #Time/Time
- Writes one file per day into output folder:
  YYYY-MM-DD_WaterDepth_24h.csv
- Preserves full ShotInfo column format (same header/columns as source)
"""

from __future__ import print_function

import csv
import glob
import json
import os
from datetime import datetime

try:
    import Tkinter as tk
    import tkFileDialog as filedialog
    import tkMessageBox as messagebox
except ImportError:
    import tkinter as tk
    from tkinter import filedialog, messagebox


APP_TITLE = "xWD — Daily ShotInfo Stitcher"
CONFIG_NAME = "xWD_last_dirs.json"


def ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path)


def normalize_name(name):
    clean = (name or "").strip()
    if clean.startswith(u"\ufeff"):
        clean = clean[1:]
    clean = clean.lower()
    if clean.startswith("\xef\xbb\xbf"):
        clean = clean[3:]
    return clean


def parse_time(value):
    return datetime.strptime((value or "").strip(), "%Y-%m-%d %H:%M:%S.%f")


def get_config_path():
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, CONFIG_NAME)


def load_config(default_input):
    default_output = os.path.join(default_input, "24H")
    config = {
        "input_dir": default_input,
        "output_dir": default_output,
    }
    cfg_path = get_config_path()
    if not os.path.isfile(cfg_path):
        return config
    try:
        with open(cfg_path, "r") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            input_dir = (loaded.get("input_dir") or "").strip()
            output_dir = (loaded.get("output_dir") or "").strip()
            if input_dir:
                config["input_dir"] = input_dir
            if output_dir:
                config["output_dir"] = output_dir
    except Exception:
        pass
    return config


def save_config(input_dir, output_dir):
    payload = {
        "input_dir": (input_dir or "").strip(),
        "output_dir": (output_dir or "").strip(),
    }
    with open(get_config_path(), "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def list_csv_files(input_dir):
    pattern = os.path.join(input_dir, "*.csv")
    return sorted(glob.glob(pattern), key=lambda p: os.path.basename(p).lower())


def read_rows_from_file(file_path, expected_fields=None):
    rows = []
    with open(file_path, "rb") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        if not reader.fieldnames:
            return rows, expected_fields

        source_fields = [(name or "").strip() for name in reader.fieldnames if name is not None]
        source_map = {}
        for name in source_fields:
            source_map[normalize_name(name)] = name

        if expected_fields is None:
            expected_fields = source_fields[:]

        expected_norms = [normalize_name(name) for name in expected_fields]
        for need in expected_norms:
            if need not in source_map:
                raise ValueError("missing column: %s" % need)

        time_col = source_map.get("#time") or source_map.get("time")
        if not time_col:
            raise ValueError("missing #Time/Time column")

        line_number = 1
        for row in reader:
            line_number += 1
            try:
                timestamp = parse_time(row.get(time_col, ""))
            except Exception as exc:
                raise ValueError("invalid time at line %d: %s" % (line_number, exc))

            out_values = []
            for norm_name in expected_norms:
                src_col = source_map[norm_name]
                out_values.append((row.get(src_col) or "").strip())
            rows.append((timestamp, out_values))

    return rows, expected_fields


def stitch_by_day(input_dir):
    csv_files = list_csv_files(input_dir)
    grouped = {}
    skipped = []
    expected_fields = None
    total_rows = 0
    used_files = 0

    for file_path in csv_files:
        try:
            file_rows, expected_fields = read_rows_from_file(file_path, expected_fields)
            if file_rows:
                used_files += 1
            for timestamp, values in file_rows:
                day_key = timestamp.strftime("%Y-%m-%d")
                grouped.setdefault(day_key, []).append((timestamp, values))
                total_rows += 1
        except Exception as exc:
            skipped.append((os.path.basename(file_path), str(exc)))

    for day_key in grouped:
        grouped[day_key].sort(key=lambda item: item[0])

    return {
        "csv_files": csv_files,
        "grouped": grouped,
        "fields": expected_fields,
        "skipped": skipped,
        "total_rows": total_rows,
        "used_files": used_files,
    }


def write_daily_files(grouped, fields, output_dir):
    ensure_dir(output_dir)
    created = 0
    details = []

    for day_key in sorted(grouped.keys()):
        out_path = os.path.join(output_dir, "%s_WaterDepth_24h.csv" % day_key)
        with open(out_path, "wb") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            for _, values in grouped[day_key]:
                writer.writerow(values)
        created += 1
        details.append((day_key, len(grouped[day_key]), out_path))

    return created, details


class App(object):
    def __init__(self):
        cwd = os.path.dirname(os.path.abspath(__file__))
        cfg = load_config(cwd)

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("900x520")

        self.input_var = tk.StringVar(value=cfg["input_dir"])
        self.output_var = tk.StringVar(value=cfg["output_dir"])
        self.status_var = tk.StringVar(value="Ready")

        self.build_ui()

    def build_ui(self):
        top = tk.Frame(self.root)
        top.pack(fill=tk.X, padx=12, pady=12)

        tk.Label(top, text="Input folder").grid(row=0, column=0, sticky="w", pady=4)
        tk.Entry(top, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        tk.Button(top, text="Browse", command=self.pick_input).grid(row=0, column=2, sticky="ew", pady=4)

        tk.Label(top, text="Output folder").grid(row=1, column=0, sticky="w", pady=4)
        tk.Entry(top, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        tk.Button(top, text="Browse", command=self.pick_output).grid(row=1, column=2, sticky="ew", pady=4)

        top.columnconfigure(1, weight=1)

        self.run_btn = tk.Button(self.root, text="Process", height=2, command=self.process)
        self.run_btn.pack(fill=tk.X, padx=12, pady=(0, 8))

        tk.Label(self.root, text="Processing log").pack(anchor="w", padx=12)
        log_frame = tk.Frame(self.root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        self.log_box = tk.Text(log_frame, state=tk.DISABLED)
        self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll = tk.Scrollbar(log_frame, command=self.log_box.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_box.configure(yscrollcommand=scroll.set)

        tk.Label(self.root, textvariable=self.status_var).pack(anchor="w", padx=12, pady=(0, 10))

    def set_status(self, text):
        self.status_var.set(text)

    def log(self, text):
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, text + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def pick_input(self):
        selected = filedialog.askdirectory(initialdir=self.input_var.get() or os.getcwd())
        if selected:
            self.input_var.set(selected)
            if not self.output_var.get().strip():
                self.output_var.set(os.path.join(selected, "24H"))
            save_config(self.input_var.get(), self.output_var.get())

    def pick_output(self):
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or os.getcwd())
        if selected:
            self.output_var.set(selected)
            save_config(self.input_var.get(), self.output_var.get())

    def process(self):
        input_dir = self.input_var.get().strip()
        output_dir = self.output_var.get().strip()

        if not os.path.isdir(input_dir):
            messagebox.showerror(APP_TITLE, "Invalid input folder:\n%s" % input_dir)
            return
        if not output_dir:
            messagebox.showerror(APP_TITLE, "Output folder is empty")
            return

        csv_files = list_csv_files(input_dir)
        if not csv_files:
            messagebox.showwarning(APP_TITLE, "No CSV files found in:\n%s" % input_dir)
            return

        self.run_btn.configure(state=tk.DISABLED)
        self.set_status("Processing...")
        self.log("Input: %s" % input_dir)
        self.log("Output: %s" % output_dir)
        self.log("CSV files found: %d" % len(csv_files))

        try:
            save_config(input_dir, output_dir)
            result = stitch_by_day(input_dir)

            if not result["fields"]:
                raise ValueError("No readable header found in input files")
            if not result["grouped"]:
                raise ValueError("No valid rows found")

            created, details = write_daily_files(result["grouped"], result["fields"], output_dir)

            self.log("Files used: %d" % result["used_files"])
            self.log("Rows stitched: %d" % result["total_rows"])
            self.log("Daily files written: %d" % created)
            for day_key, count, out_path in details:
                self.log("  %s -> %d rows" % (day_key, count))
                self.log("    %s" % out_path)

            if result["skipped"]:
                self.log("Skipped files: %d" % len(result["skipped"]))
                for name, reason in result["skipped"]:
                    self.log("  %s: %s" % (name, reason))

            self.set_status("Done")
            messagebox.showinfo(APP_TITLE, "Completed. Wrote %d daily file(s)." % created)
        except Exception as exc:
            self.set_status("Failed")
            self.log("ERROR: %s" % exc)
            messagebox.showerror(APP_TITLE, "Processing failed:\n%s" % exc)
        finally:
            self.run_btn.configure(state=tk.NORMAL)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()

