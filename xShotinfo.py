#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
xShotinfo — 24h CSV files builder (Python 2.7)

Creates one CSV per day (24h) from ShotInfo files, preserving all
original columns and value formatting from the source ShotInfo files.
"""

import csv
import glob
import importlib
import json
import os
from datetime import datetime

try:
    tk = importlib.import_module("Tkinter")
    filedialog = importlib.import_module("tkFileDialog")
    messagebox = importlib.import_module("tkMessageBox")
    tkfont = importlib.import_module("tkFont")
except ImportError:
    raise SystemExit("Tkinter is required. Install it with: sudo dnf install -y python2-tkinter")


DEFAULT_SHOTINFO_DIR = "/aw-navoff1/data/JOB/3190/qcfiles/Navigation_Info/ShotInfo"
DEFAULT_OUTPUT_DIR = "/aw-navoff1/data/JOB/3190/qcfiles/Water_Depth"
DEFAULT_STATE_DIR = "/aw-navoff1/data/JOB/3190/qcfiles/Misc/xShotinfo"
LAST_SETTINGS_FILE = os.path.join(DEFAULT_STATE_DIR, "xShotinfo_last_settings.json")

COLOR_BG = "#aec6dd"
COLOR_BTN = "#9cb6cf"
COLOR_BTN_ACTIVE = "#8cabc2"
COLOR_TEXT = "#000000"
COLOR_HEADER = "#000033"
COLOR_NOTE = "#404040"


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def parse_time(value):
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S.%f")


def normalize_fieldnames(fieldnames):
    mapped = {}
    for name in fieldnames:
        if name is None:
            continue
        clean_name = name.strip().lower()
        if clean_name.startswith("\xef\xbb\xbf"):
            clean_name = clean_name[3:]
        mapped[clean_name] = name
    return mapped


def parse_shotinfo_file(file_path):
    rows = []
    output_fieldnames = None
    with open(file_path, "rb") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        if not reader.fieldnames:
            return rows, output_fieldnames

        source_fieldnames = list(reader.fieldnames)
        output_fieldnames = list(source_fieldnames)
        if output_fieldnames and output_fieldnames[0].startswith("\xef\xbb\xbf"):
            output_fieldnames[0] = output_fieldnames[0][3:]

        name_map = normalize_fieldnames(source_fieldnames)
        time_col = name_map.get("#time") or name_map.get("time")
        if not time_col:
            raise ValueError("Missing required column: Time")

        line_number = 1
        for row in reader:
            line_number += 1
            try:
                timestamp = parse_time(row.get(time_col, ""))
                row_values = []
                for field_name in source_fieldnames:
                    raw_value = row.get(field_name, "")
                    if raw_value is None:
                        raw_value = ""
                    row_values.append(raw_value)
                rows.append({
                    "timestamp": timestamp,
                    "values": row_values,
                })
            except Exception as exc:
                raise ValueError("%s: invalid data at line %d: %s" % (os.path.basename(file_path), line_number, exc))

    return rows, output_fieldnames


def collect_points(shotinfo_dir):
    all_points = []
    skipped_files = []
    output_fieldnames = None
    csv_files = sorted(glob.glob(os.path.join(shotinfo_dir, "*.csv")), key=lambda p: os.path.basename(p).lower())
    for csv_file in csv_files:
        try:
            rows, file_fieldnames = parse_shotinfo_file(csv_file)
            if file_fieldnames is None:
                continue
            if output_fieldnames is None:
                output_fieldnames = file_fieldnames
            elif file_fieldnames != output_fieldnames:
                raise ValueError("Header mismatch. Expected same ShotInfo columns/order as first valid file.")
            all_points.extend(rows)
        except Exception as exc:
            skipped_files.append((os.path.basename(csv_file), str(exc)))
    return all_points, skipped_files, output_fieldnames


def group_by_day(points):
    grouped = {}
    for point in points:
        day_key = point["timestamp"].strftime("%Y-%m-%d")
        grouped.setdefault(day_key, []).append(point)
    for day_key in grouped:
        grouped[day_key].sort(key=lambda p: p["timestamp"])
    return grouped


def write_daily_files(grouped, output_dir, output_fieldnames):
    ensure_dir(output_dir)
    files_created = 0
    files_skipped = 0
    today_key = datetime.now().strftime("%Y-%m-%d")

    for day_key in sorted(grouped.keys()):
        out_file = os.path.join(output_dir, "%s_WaterDepth_24h.csv" % day_key)

        if day_key < today_key and os.path.isfile(out_file):
            existing_rows = 0
            try:
                with open(out_file, "rb") as existing_handle:
                    existing_rows = sum(1 for _ in existing_handle)
                existing_rows = max(0, existing_rows - 1)
            except Exception:
                existing_rows = 0

            if existing_rows >= len(grouped[day_key]):
                files_skipped += 1
                continue

        with open(out_file, "wb") as handle:
            writer = csv.writer(handle)
            writer.writerow(output_fieldnames)
            for point in grouped[day_key]:
                writer.writerow(point["values"])
        files_created += 1

    return files_created, files_skipped


class XShotinfoPanel(tk.Frame):
    """Tkinter UI as a Frame for embedding in xNAVSL or packing into a standalone root."""

    def __init__(self, master, geometry_save_widget=None):
        tk.Frame.__init__(self, master, bg=COLOR_BG)
        self._geometry_save_widget = geometry_save_widget

        default_font = tkfont.nametofont("TkDefaultFont")
        self.header_font = tkfont.Font(family="Helvetica", size=16, weight="bold")
        self.button_font = tkfont.Font(
            family=default_font.actual("family"),
            size=default_font.actual("size"),
            weight="bold",
        )

        self.shotinfo_var = tk.StringVar(value=DEFAULT_SHOTINFO_DIR)
        self.output_var = tk.StringVar(value=DEFAULT_OUTPUT_DIR)
        self.status_var = tk.StringVar(value="Ready.")

        self._load_last_settings()

        tk.Label(
            self,
            text="xShotinfo 24h CSV files",
            bg=COLOR_BG,
            fg=COLOR_HEADER,
            font=self.header_font,
        ).pack(padx=12, pady=(12, 6), anchor="w")

        tk.Label(
            self,
            text="Select ShotInfo and output folders, then click one button to generate daily files.",
            bg=COLOR_BG,
            fg=COLOR_NOTE,
        ).pack(padx=12, pady=(0, 10), anchor="w")

        paths = tk.Frame(self, bg=COLOR_BG)
        paths.pack(fill=tk.X, padx=12)

        tk.Label(paths, text="ShotInfo folder:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, sticky="w", pady=4)
        tk.Entry(paths, textvariable=self.shotinfo_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        tk.Button(
            paths,
            text="Browse",
            font=self.button_font,
            bg=COLOR_BTN,
            fg=COLOR_TEXT,
            activebackground=COLOR_BTN_ACTIVE,
            command=self.pick_shotinfo_dir,
        ).grid(row=0, column=2, sticky="ew", pady=4)

        tk.Label(paths, text="Output folder:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, sticky="w", pady=4)
        tk.Entry(paths, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        tk.Button(
            paths,
            text="Browse",
            font=self.button_font,
            bg=COLOR_BTN,
            fg=COLOR_TEXT,
            activebackground=COLOR_BTN_ACTIVE,
            command=self.pick_output_dir,
        ).grid(row=1, column=2, sticky="ew", pady=4)

        paths.columnconfigure(1, weight=1)

        self.run_button = tk.Button(
            self,
            text="Create 24h CSV Files",
            font=self.button_font,
            bg=COLOR_BTN,
            fg=COLOR_TEXT,
            activebackground=COLOR_BTN_ACTIVE,
            command=self.process,
            height=2,
        )
        self.run_button.pack(fill=tk.X, padx=12, pady=(12, 8))

        tk.Label(self, text="Log:", bg=COLOR_BG, fg=COLOR_HEADER).pack(padx=12, anchor="w")
        self.log_box = tk.Text(self, height=10, bg="white", state=tk.DISABLED)
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        tk.Label(self, textvariable=self.status_var, bg=COLOR_BG, fg=COLOR_NOTE).pack(padx=12, pady=(0, 10), anchor="w")

        if self._geometry_save_widget is None:
            self.bind("<Destroy>", self._on_embed_destroy)

    def _load_last_settings(self):
        try:
            if not os.path.isfile(LAST_SETTINGS_FILE):
                return
            with open(LAST_SETTINGS_FILE, "rb") as handle:
                data = json.load(handle)
            saved_shotinfo = data.get("shotinfo_dir", "")
            saved_output = data.get("output_dir", "")
            if saved_shotinfo:
                self.shotinfo_var.set(saved_shotinfo)
            if saved_output:
                self.output_var.set(saved_output)
        except Exception:
            pass

    def _save_last_settings(self):
        try:
            ensure_dir(DEFAULT_STATE_DIR)
            payload = {
                "shotinfo_dir": self.shotinfo_var.get().strip(),
                "output_dir": self.output_var.get().strip(),
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(LAST_SETTINGS_FILE, "wb") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
        except Exception:
            pass

    def set_status(self, message):
        self.status_var.set(message)

    def append_log(self, message):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.insert(tk.END, message + "\n")
        self.log_box.see(tk.END)
        self.log_box.config(state=tk.DISABLED)

    def pick_shotinfo_dir(self):
        selected = filedialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.shotinfo_var.get() or "/"
        )
        if selected:
            self.shotinfo_var.set(selected)
            self._save_last_settings()

    def pick_output_dir(self):
        selected = filedialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.output_var.get() or "/"
        )
        if selected:
            self.output_var.set(selected)
            self._save_last_settings()

    def process(self):
        shotinfo_dir = self.shotinfo_var.get().strip()
        output_dir = self.output_var.get().strip()

        top = self.winfo_toplevel()
        if not os.path.isdir(shotinfo_dir):
            messagebox.showerror("xShotinfo", "Invalid ShotInfo folder:\n%s" % shotinfo_dir, parent=top)
            return

        csv_files = sorted(glob.glob(os.path.join(shotinfo_dir, "*.csv")))
        if not csv_files:
            messagebox.showwarning("xShotinfo", "No CSV files found in:\n%s" % shotinfo_dir, parent=top)
            return

        self.run_button.config(state=tk.DISABLED)
        self._save_last_settings()
        self.set_status("Processing ShotInfo files...")
        self.append_log("Input: %s" % shotinfo_dir)
        self.append_log("Output: %s" % output_dir)
        self.append_log("Found %d ShotInfo file(s)" % len(csv_files))

        try:
            points, skipped_files, output_fieldnames = collect_points(shotinfo_dir)

            if skipped_files:
                self.append_log("Skipped files: %d" % len(skipped_files))
                for item in skipped_files:
                    self.append_log("  - %s" % item[0])

            if not points or not output_fieldnames:
                messagebox.showwarning(
                    "xShotinfo", "No valid rows found in files matching the latest format.", parent=top
                )
                self.set_status("No valid rows found.")
                return

            grouped = group_by_day(points)
            files_created, files_skipped = write_daily_files(grouped, output_dir, output_fieldnames)

            self.append_log("Rows exported: %d" % len(points))
            self.append_log("24h files created: %d" % files_created)
            self.append_log("24h files skipped (already fulfilled): %d" % files_skipped)
            for day in sorted(grouped.keys()):
                self.append_log("  - %s: %d row(s)" % (day, len(grouped[day])))

            self.set_status("Done. Created %d file(s), skipped %d fulfilled file(s)." % (files_created, files_skipped))
            messagebox.showinfo(
                "xShotinfo",
                "Completed. Created %d file(s), skipped %d fulfilled file(s) in:\n%s"
                % (files_created, files_skipped, output_dir),
                parent=top,
            )
        except Exception as exc:
            self.set_status("Failed.")
            self.append_log("ERROR: %s" % exc)
            messagebox.showerror("xShotinfo", "Processing failed:\n%s" % exc, parent=top)
        finally:
            self.run_button.config(state=tk.NORMAL)

    def on_root_close(self):
        self._save_last_settings()
        try:
            self.winfo_toplevel().destroy()
        except Exception:
            pass

    def _on_embed_destroy(self, event):
        try:
            if str(event.widget) != str(self):
                return
        except Exception:
            return
        try:
            self._save_last_settings()
        except Exception:
            pass


class XShotinfo24hApp(object):
    """Standalone window: same behavior as before the xNAVSL embed refactor."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("xShotinfo 24h CSV files")
        self.root.configure(bg=COLOR_BG)
        self.root.geometry("920x440")
        self.panel = XShotinfoPanel(self.root, geometry_save_widget=self.root)
        self.panel.pack(fill=tk.BOTH, expand=True)
        self.root.protocol("WM_DELETE_WINDOW", self.panel.on_root_close)

    def run(self):
        self.root.mainloop()


def xnavsl_embed(master):
    """Host inside xNAVSL (or any parent Frame); does not create a new Tk."""
    panel = XShotinfoPanel(master, geometry_save_widget=None)
    panel.pack(fill=tk.BOTH, expand=True)


if __name__ == "__main__":
    try:
        XShotinfo24hApp().run()
    except Exception as exc:
        try:
            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror("xShotinfo Error", "Application error:\n%s" % exc)
            fallback.destroy()
        except Exception:
            raise

