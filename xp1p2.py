#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Ai assisted Code by RBolisay
"""
A Python 2.7 Tkinter GUI for performing the QC process.
It allows you to select directories, specify a sequence range,
displays results in a table with clear borders, and shows a status area.
Error values are displayed in red.
The output CSV filename is modified to include the sequence range.
"""

import os
import json
import re
import threading
import Queue

import Tkinter as tk
import tkFileDialog
import tkMessageBox
import ttk
import ScrolledText

# Default paths
default_P111_DIR = "/usr/local/trinop/dbase/links/currentjob/P111/P111_SSREG"
default_P211_DIR = "/usr/local/trinop/dbase/links/currentjob/P211"
default_BACKUP_DIR = "/usr/local/trinop/dbase/links/backup_processed"
default_FESB_DIR = "/usr/local/trinop/dbase/links/fes_backup"
default_OUTPUT_CSV = "/usr/local/trinop/qcfiles/Misc/xp1p2.csv"
DEFAULT_DATA_DIR = "/usr/local/trinop/dbase/links/qcfiles/Misc/xp1p2"
SESSION_FILE = os.path.join(DEFAULT_DATA_DIR, "session.json")
CONFIG_EXT = ".xcfg"
CONFIG_VERSION = 1
CACHE_VERSION = 1

# Define error strings that should be shown in red.
error_strings = {"Missing!", "SP range BAD", "Missing Backup!", "Missing FESB!", "mismatch", "Backup subline BAD"}
COMPRESSED_EXTENSIONS = (".gz", ".bz2")

# Define GUI colors
GUI_BACKGROUND_COLOR = "#B4C8E1"  # Blue Aura
BUTTON_BACKGROUND_COLOR = "#8DA9CC" # Distinct, slightly darker blue
BUTTON_TEXT_COLOR = "black"

def ensure_data_dir():
    """Creates the xp1p2 data directory if it does not exist."""
    if not os.path.isdir(DEFAULT_DATA_DIR):
        try:
            os.makedirs(DEFAULT_DATA_DIR)
        except Exception as e:
            print("Error creating data directory {}: {}".format(DEFAULT_DATA_DIR, e))

def safe_config_basename(name):
    """Returns a filesystem-safe configuration basename."""
    raw = (name or "").strip() or "default"
    safe = re.sub(r'[/\\:*?"<>|]+', "_", raw).strip("._ ") or "default"
    for ext in (".json", CONFIG_EXT):
        if safe.lower().endswith(ext):
            safe = safe[: -len(ext)].strip("._ ") or "default"
    return safe[:120]

def config_path_for_name(name, save_dir=None):
    """Builds the config path for a configuration name."""
    directory = save_dir or DEFAULT_DATA_DIR
    return os.path.join(directory, safe_config_basename(name) + CONFIG_EXT)

def is_config_file_path(path):
    """True when path is a loadable configuration file (not cache/session)."""
    base = os.path.basename(path).lower()
    if base == "session.json":
        return False
    if base.endswith("_qc_cache.json"):
        return False
    return base.endswith(CONFIG_EXT) or base.endswith(".json")

def cache_path_for_name(name):
    """Builds the QC cache JSON path for a configuration name."""
    ensure_data_dir()
    return os.path.join(DEFAULT_DATA_DIR, safe_config_basename(name) + "_qc_cache.json")

def expected_line_subline_pairs(line_p111, sub_p111, line_p211, sub_p211):
    """Collects unique (line name, subline) pairs from parsed P111/P211 values."""
    invalid = {"Missing!", "Multiple Files!"}
    pairs = []
    seen = set()
    for line_name, subline in ((line_p111, sub_p111), (line_p211, sub_p211)):
        if line_name in invalid or subline in invalid:
            continue
        key = (line_name.lower(), subline.lower())
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"line": line_name, "subline": subline})
    return pairs

def get_backup_match_signature(backup_dir, expected_pairs):
    """Signature of backup files matching expected line.subline pairs (name + mtime + size)."""
    if not expected_pairs:
        return {"status": "no_pairs"}
    matches = []
    try:
        for filename in os.listdir(backup_dir):
            path = os.path.join(backup_dir, filename)
            if not os.path.isfile(path):
                continue
            for pair in expected_pairs:
                if backup_filename_matches_line_subline(filename, pair["line"], pair["subline"]):
                    stat = os.stat(path)
                    matches.append({
                        "name": filename,
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                    })
                    break
    except Exception:
        return {"status": "error"}
    matches.sort(key=lambda item: item["name"])
    if not matches:
        return {"status": "none"}
    return {"status": "matched", "files": matches}

def get_fesb_match_signature(fesb_dir, sequence):
    """Signature of FESB file(s) matching rt_XXXX (name + mtime + size)."""
    token = "rt_{:04d}".format(sequence).lower()
    matches = []
    try:
        for filename in os.listdir(fesb_dir):
            path = os.path.join(fesb_dir, filename)
            if not os.path.isfile(path):
                continue
            normalized = strip_compression_extension(filename).lower()
            if token in filename.lower() or token in normalized:
                stat = os.stat(path)
                matches.append({
                    "name": filename,
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                })
    except Exception:
        return {"status": "error"}
    matches.sort(key=lambda item: item["name"])
    if not matches:
        return {"status": "none"}
    return {"status": "matched", "files": matches}

def get_sequence_file_signature(directory, extension, seq_num, file_value):
    """Builds a cache signature for one sequence file selection."""
    if file_value == "Missing!":
        return {"status": "missing"}
    if file_value == "Multiple Files!":
        candidates = []
        try:
            for filename in os.listdir(directory):
                if filename.endswith(extension) and filename[:4].isdigit():
                    try:
                        if int(filename[:4]) != seq_num:
                            continue
                    except ValueError:
                        continue
                    path = os.path.join(directory, filename)
                    stat = os.stat(path)
                    candidates.append({"path": path, "mtime": stat.st_mtime, "size": stat.st_size})
        except Exception:
            pass
        candidates.sort(key=lambda item: item["path"])
        return {"status": "multiple", "candidates": candidates}
    try:
        stat = os.stat(file_value)
        return {"status": "ok", "path": file_value, "mtime": stat.st_mtime, "size": stat.st_size}
    except Exception:
        return {"status": "missing"}

def build_sequence_inputs(p111_sig, p211_sig, line_p111, sub_p111, line_p211, sub_p211, backup_dir, fesb_dir, seq):
    """Builds the input signature stored with each cached QC row."""
    expected_pairs = expected_line_subline_pairs(line_p111, sub_p111, line_p211, sub_p211)
    return {
        "p111": p111_sig,
        "p211": p211_sig,
        "expected_line_subline_pairs": expected_pairs,
        "backup_match": get_backup_match_signature(backup_dir, expected_pairs),
        "fesb_match": get_fesb_match_signature(fesb_dir, seq),
    }

def run_config_browse_dialog(parent):
    """Load file vs save-folder choice."""
    result = [None]
    dlg = tk.Toplevel(parent)
    dlg.title("Configuration")
    dlg.configure(bg=GUI_BACKGROUND_COLOR)
    dlg.transient(parent)
    dlg.grab_set()

    def finish(value):
        result[0] = value
        dlg.destroy()

    tk.Label(
        dlg,
        text="Choose an action:",
        bg=GUI_BACKGROUND_COLOR,
        foreground="black",
    ).pack(padx=22, pady=(14, 10))
    for text, value in (
        ("Load configuration file...", "load"),
        ("Choose save folder...", "folder"),
        ("Cancel", None),
    ):
        tk.Button(
            dlg,
            text=text,
            command=lambda v=value: finish(v),
            background=BUTTON_BACKGROUND_COLOR,
            foreground=BUTTON_TEXT_COLOR,
            padx=12,
            pady=4,
        ).pack(fill=tk.X, padx=20, pady=3)
    parent.wait_window(dlg)
    return result[0]

class QCCache(object):
    """Per-configuration QC result cache stored under DEFAULT_DATA_DIR."""

    def __init__(self, cache_path):
        self.cache_path = cache_path
        self.data = self._load()

    def _load(self):
        if not os.path.isfile(self.cache_path):
            return {"version": CACHE_VERSION, "paths": {}, "sequences": {}}
        try:
            f = open(self.cache_path, "r")
            data = json.load(f)
            f.close()
        except Exception as e:
            print("Error loading QC cache {}: {}".format(self.cache_path, e))
            return {"version": CACHE_VERSION, "paths": {}, "sequences": {}}
        if not isinstance(data, dict):
            return {"version": CACHE_VERSION, "paths": {}, "sequences": {}}
        data.setdefault("paths", {})
        data.setdefault("sequences", {})
        return data

    def ensure_paths(self, p111_dir, p211_dir, backup_dir, fesb_dir):
        """Clears cached sequences when configured directories change."""
        current_paths = {
            "p111_dir": p111_dir,
            "p211_dir": p211_dir,
            "backup_dir": backup_dir,
            "fesb_dir": fesb_dir,
        }
        if self.data.get("paths") != current_paths:
            self.data["paths"] = current_paths
            self.data["sequences"] = {}

    def get_cached_row(self, seq_key, p111_sig, p211_sig, backup_dir, fesb_dir, seq):
        entry = self.data.get("sequences", {}).get(seq_key)
        if not entry:
            return None
        cached = entry.get("inputs")
        if not isinstance(cached, dict):
            return None
        if cached.get("p111") != p111_sig or cached.get("p211") != p211_sig:
            return None
        expected_pairs = cached.get("expected_line_subline_pairs")
        if not expected_pairs:
            return None
        current_backup = get_backup_match_signature(backup_dir, expected_pairs)
        current_fesb = get_fesb_match_signature(fesb_dir, seq)
        if cached.get("backup_match") != current_backup:
            return None
        if cached.get("fesb_match") != current_fesb:
            return None
        return entry.get("result_row")

    def put_row(self, seq_key, inputs, result_row):
        self.data.setdefault("sequences", {})[seq_key] = {
            "inputs": inputs,
            "result_row": result_row,
        }

    def save(self):
        ensure_data_dir()
        try:
            f = open(self.cache_path, "w")
            json.dump(self.data, f, indent=2, sort_keys=True)
            f.close()
        except Exception as e:
            print("Error saving QC cache {}: {}".format(self.cache_path, e))

def get_files_in_range(directory, extension, seq_start, seq_end):
    """Retrieves files in the directory matching the sequence range."""
    file_map = {}
    try:
        files = [f for f in os.listdir(directory) if f.endswith(extension) and f[:4].isdigit()]
        files.sort(key=lambda x: os.path.getmtime(os.path.join(directory, x)), reverse=True)
        for f in files:
            try:
                seq_num = int(f[:4])
            except:
                continue
            if seq_start <= seq_num <= seq_end:
                if seq_num in file_map:
                    file_map[seq_num] = "Multiple Files!"
                else:
                    file_map[seq_num] = os.path.join(directory, f)
    except Exception as e:
        print("Error accessing {}: {}".format(directory, e))
    return file_map

def extract_shotpoints(file_path, record_type, shotpoint_index):
    """
    Extracts shotpoint numbers, preserving the file order, and also computes
    the numeric minimum and maximum.
    
    Returns a tuple:
      (display_FSP, display_LSP, numeric_min, numeric_max, line_name, subline)
      
    - display_FSP and display_LSP are the first and last shotpoints as encountered in the file.
    - numeric_min and numeric_max are the minimum and maximum shotpoint values (for QC checks).
    """
    if not file_path or file_path in ["Missing!", "Multiple Files!"]:
        return "Missing!", "Missing!", "Missing!", "Missing!", "Missing!", "Missing!"
    shotpoints = []
    display_list = []  # to preserve the order of appearance
    line_name, subline = "Missing!", "Missing!"
    try:
        f = open(file_path, "r")
    except Exception:
        return "Missing!", "Missing!", "Missing!", "Missing!", "Missing!", "Missing!"
    for line in f:
        parts = line.strip().split(",")
        if line.startswith(record_type) and len(parts) > shotpoint_index:
            try:
                val = int(parts[shotpoint_index])
                shotpoints.append(val)
                display_list.append(val)
            except ValueError:
                pass
        if "LINENAME/SUBLINE" in line:
            name_parts = line.split("=")[-1].strip().split("/")
            if len(name_parts) > 2:
                line_name = name_parts[1]
                subline = name_parts[2]
    f.close()
    if not shotpoints:
        return "Missing!", "Missing!", "Missing!", "Missing!", line_name, subline
    # Preserve display order exactly as in the file.
    display_FSP = display_list[0]
    display_LSP = display_list[-1]
    # For QC check, use the numeric min and max.
    numeric_min = min(shotpoints)
    numeric_max = max(shotpoints)
    return display_FSP, display_LSP, numeric_min, numeric_max, line_name, subline

def strip_compression_extension(filename):
    """Removes supported compression extensions from a filename."""
    lower_name = filename.lower()
    for extension in COMPRESSED_EXTENSIONS:
        if lower_name.endswith(extension):
            return filename[:-len(extension)]
    return filename

def directory_contains_token(directory, token):
    """Checks filenames, including .gz/.bz2 stems, for the requested token."""
    token = token.lower()
    try:
        for filename in os.listdir(directory):
            normalized_name = strip_compression_extension(filename).lower()
            if token in filename.lower() or token in normalized_name:
                return True
    except Exception as e:
        print("Error accessing {}: {}".format(directory, e))
    return False

def parse_backup_line_subline(filename):
    """Parse line name and subline from line.subline.suffix.BACKUP[.gz|.bz2]."""
    normalized = strip_compression_extension(filename)
    if normalized.upper().endswith(".BACKUP"):
        normalized = normalized[:-len(".BACKUP")]
    parts = normalized.split(".")
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]

def backup_filename_matches_line_subline(filename, line_name, subline):
    """True when backup name field 1 = line name and field 2 = subline."""
    invalid = {"Missing!", "Multiple Files!"}
    if line_name in invalid or subline in invalid:
        return False
    parsed_line, parsed_subline = parse_backup_line_subline(filename)
    if parsed_line is None or parsed_subline is None:
        return False
    return (
        parsed_line.lower() == line_name.lower()
        and parsed_subline.lower() == subline.lower()
    )

def check_backup_exists(line_p111, sub_p111, line_p211, sub_p211, backup_dir):
    """Checks whether any backup filename matches P111/P211 line name and subline."""
    expected_pairs = expected_line_subline_pairs(line_p111, sub_p111, line_p211, sub_p211)
    if not expected_pairs:
        return "Missing Backup!"
    try:
        backup_files = os.listdir(backup_dir)
    except Exception as e:
        print("Error accessing {}: {}".format(backup_dir, e))
        return "Missing Backup!"
    if not backup_files:
        return "Missing Backup!"
    for filename in backup_files:
        for pair in expected_pairs:
            if backup_filename_matches_line_subline(filename, pair["line"], pair["subline"]):
                return "Backup GOOD"
    return "Backup subline BAD"

def check_fesb_exists(sequence, fesb_dir):
    """Checks if a FESB file, zipped or plain, exists in the FESB directory."""
    seq_str = "{:04d}".format(sequence)
    return "FESB GOOD" if directory_contains_token(fesb_dir, "rt_{}".format(seq_str)) else "Missing FESB!"

def check_subline_xcheck(sub_p111, sub_p211):
    """Compares P111 and P211 sublines."""
    invalid = {"Missing!", "Multiple Files!"}
    if sub_p111 in invalid or sub_p211 in invalid:
        return "Missing!"
    if sub_p111.lower() == sub_p211.lower():
        return "Match"
    return "mismatch"

def save_csv(file_path, data, output_queue):
    """Saves the processed data to a CSV file."""
    try:
        directory = os.path.dirname(file_path)
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(file_path, "w") as f:
            f.write("Sequence No.,Filename P111,Line Name P111,Subline P111,FSP P111,LSP P111,"
                    "Filename P211,Line Name P211,Subline P211,FSP P211,LSP P211,Subline XCheck,SP Range XCheck,Backup XCheck,FESB XCheck\n")
            for row in data:
                f.write(",".join(map(str, row)) + "\n")
        output_queue.put(("status", "CSV saved to {}\n".format(file_path)))
    except Exception as e:
        output_queue.put(("status", "Error writing CSV file: {}\n".format(e)))

class QCWorker(threading.Thread):
    """Worker thread that performs the QC process."""
    def __init__(self, p111_dir, p211_dir, backup_dir, fesb_dir, output_csv, seq_range, cache_path, output_queue):
        threading.Thread.__init__(self)
        self.p111_dir = p111_dir
        self.p211_dir = p211_dir
        self.backup_dir = backup_dir
        self.fesb_dir = fesb_dir
        self.output_csv = output_csv
        self.seq_range = seq_range
        self.cache_path = cache_path
        self.output_queue = output_queue

    def run(self):
        try:
            seq_start, seq_end = map(int, self.seq_range.split("-"))
        except Exception:
            self.output_queue.put(("status", "Invalid sequence range! Please use format '1-5'\n"))
            return
        self.output_queue.put(("status", "Starting QC process for sequence range {} to {}\n".format(seq_start, seq_end)))
        qc_cache = QCCache(self.cache_path)
        qc_cache.ensure_paths(self.p111_dir, self.p211_dir, self.backup_dir, self.fesb_dir)
        p111_files = get_files_in_range(self.p111_dir, ".p111", seq_start, seq_end)
        p211_files = get_files_in_range(self.p211_dir, ".p211", seq_start, seq_end)
        extracted_data = []
        reused_count = 0
        recomputed_count = 0
        for seq in range(seq_start, seq_end + 1):
            seq_key = "{:04d}".format(seq)
            p111_file = p111_files.get(seq, "Missing!")
            p211_file = p211_files.get(seq, "Missing!")
            p111_sig = get_sequence_file_signature(self.p111_dir, ".p111", seq, p111_file)
            p211_sig = get_sequence_file_signature(self.p211_dir, ".p211", seq, p211_file)
            cached_row = qc_cache.get_cached_row(
                seq_key, p111_sig, p211_sig, self.backup_dir, self.fesb_dir, seq
            )
            if cached_row is not None:
                result_line = cached_row
                reused_count += 1
            else:
                fsp_p111_disp, lsp_p111_disp, fsp_p111_num, lsp_p111_num, line_p111, sub_p111 = \
                    extract_shotpoints(p111_file, "S1", 4)
                fsp_p211_disp, lsp_p211_disp, fsp_p211_num, lsp_p211_num, line_p211, sub_p211 = \
                    extract_shotpoints(p211_file, "E2", 6)
                backup_xcheck = check_backup_exists(
                    line_p111, sub_p111, line_p211, sub_p211, self.backup_dir
                )
                fesb_xcheck = check_fesb_exists(seq, self.fesb_dir)
                subline_xcheck = check_subline_xcheck(sub_p111, sub_p211)
                try:
                    if int(fsp_p111_num) >= int(fsp_p211_num) and int(lsp_p111_num) <= int(lsp_p211_num):
                        sp_range_xcheck = "SP range GOOD"
                    else:
                        sp_range_xcheck = "SP range BAD"
                except Exception:
                    sp_range_xcheck = "SP range BAD"
                result_line = [
                    seq_key,
                    os.path.basename(p111_file),
                    line_p111,
                    sub_p111,
                    fsp_p111_disp,
                    lsp_p111_disp,
                    os.path.basename(p211_file),
                    line_p211,
                    sub_p211,
                    fsp_p211_disp,
                    lsp_p211_disp,
                    subline_xcheck,
                    sp_range_xcheck,
                    backup_xcheck,
                    fesb_xcheck
                ]
                inputs = build_sequence_inputs(
                    p111_sig, p211_sig, line_p111, sub_p111, line_p211, sub_p211,
                    self.backup_dir, self.fesb_dir, seq
                )
                qc_cache.put_row(seq_key, inputs, result_line)
                recomputed_count += 1
            extracted_data.append(result_line)
            self.output_queue.put(("row", result_line))

        qc_cache.save()
        self.output_queue.put(("status", "Reused cache: {} sequence(s), recomputed: {} sequence(s).\n".format(
            reused_count, recomputed_count
        )))
        base, ext = os.path.splitext(self.output_csv)
        output_csv_modified = base + "_" + self.seq_range + ext
        save_csv(output_csv_modified, extracted_data, self.output_queue)
        self.output_queue.put(("status", "QC process completed.\n"))

class QCAppPanel(tk.Frame):
    """
    Main QC UI as a Frame so it can be packed into xNAVSL or into a standalone Tk window.
    geometry_save_widget: when set (standalone root Tk), window geometry is saved/restored; when None (embedded), not.
    """
    def __init__(self, master, geometry_save_widget=None):
        tk.Frame.__init__(self, master, background=GUI_BACKGROUND_COLOR)
        self._geometry_save_widget = geometry_save_widget

        # Configure panel grid: two rows (controls and results)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Create a frame for controls at the top left.
        self.controls_frame = tk.Frame(self, background=GUI_BACKGROUND_COLOR)
        self.controls_frame.grid(row=0, column=0, sticky="nw", padx=5, pady=5)

        # Define StringVars for paths and sequence range.
        self.config_name = tk.StringVar(value="default")
        self.p111_dir = tk.StringVar(value=default_P111_DIR)
        self.p211_dir = tk.StringVar(value=default_P211_DIR)
        self.backup_dir = tk.StringVar(value=default_BACKUP_DIR)
        self.fesb_dir = tk.StringVar(value=default_FESB_DIR)
        self.output_csv = tk.StringVar(value=default_OUTPUT_CSV)
        self.seq_range = tk.StringVar(value="1-5")
        self._saved_geometry = None
        self.current_config_path = None
        self.default_save_dir = DEFAULT_DATA_DIR
        ensure_data_dir()
        self.load_session_on_startup()

        # Populate the controls frame.
        row = 0
        # Configuration Name
        tk.Label(self.controls_frame, text="Configuration Name:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.config_name, width=50).grid(row=row, column=1)
        browse_load_button = tk.Button(self.controls_frame, text="Browse/Load", command=self.browse_load_config, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        browse_load_button.grid(row=row, column=2, padx=(0, 2))
        save_config_button = tk.Button(self.controls_frame, text="Save", command=self.save_config, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        save_config_button.grid(row=row, column=3, padx=(2, 0))

        row += 1
        # P111 Directory
        tk.Label(self.controls_frame, text="P111 Directory:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.p111_dir, width=50).grid(row=row, column=1)
        p111_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_p111, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        p111_browse_button.grid(row=row, column=2)

        row += 1
        # P211 Directory
        tk.Label(self.controls_frame, text="P211 Directory:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.p211_dir, width=50).grid(row=row, column=1)
        p211_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_p211, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        p211_browse_button.grid(row=row, column=2)

        row += 1
        # Backup Directory
        tk.Label(self.controls_frame, text="Backup Directory:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.backup_dir, width=50).grid(row=row, column=1)
        backup_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_backup, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        backup_browse_button.grid(row=row, column=2)

        row += 1
        # FESB Directory
        tk.Label(self.controls_frame, text="FESB Directory:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.fesb_dir, width=50).grid(row=row, column=1)
        fesb_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_fesb, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        fesb_browse_button.grid(row=row, column=2)

        row += 1
        # Output CSV File
        tk.Label(self.controls_frame, text="Output CSV File:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.output_csv, width=50).grid(row=row, column=1)
        output_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_output, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        output_browse_button.grid(row=row, column=2)
        
        row += 1
        # Sequence Range
        tk.Label(self.controls_frame, text="Sequence Range (e.g., 1-5):", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.seq_range, width=20).grid(row=row, column=1, sticky="w")

        row += 1
        # Start QC Button
        self.start_button = tk.Button(self.controls_frame, text="Start QC", command=self.start_qc, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        self.start_button.grid(row=row, column=0, columnspan=3, pady=10)

        # Create a frame for the results.
        self.results_frame = tk.Frame(self, background=GUI_BACKGROUND_COLOR)
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.results_frame.grid_rowconfigure(0, weight=1)
        self.results_frame.grid_columnconfigure(0, weight=1)

        # Setup custom style for the Treeview and other ttk widgets.
        style = ttk.Style()
        # Configure Treeview style
        style.configure("mystyle.Treeview", borderwidth=1, relief="solid", rowheight=25, background="white", fieldbackground="white") # Treeview data area
        style.map("mystyle.Treeview", background=[('selected', BUTTON_BACKGROUND_COLOR)]) # Selected item color
        style.configure("mystyle.Treeview.Heading", borderwidth=1, relief="solid", background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR) # Treeview headings
        
        # Configure Scrollbar style for consistency, though direct background might not apply easily to all parts
        style.configure("TScrollbar", background=BUTTON_BACKGROUND_COLOR, troughcolor=GUI_BACKGROUND_COLOR)


        # Define the columns.
        self.columns = ["Sequence No.", "Filename P111", "Line Name P111", "Subline P111",
                        "FSP P111", "LSP P111", "Filename P211", "Line Name P211", "Subline P211",
                        "FSP P211", "LSP P211", "Subline XCheck", "SP Range XCheck", "Backup XCheck", "FESB XCheck"]

        # Create the Treeview widget.
        self.tree = ttk.Treeview(self.results_frame, columns=self.columns, show="headings", style="mystyle.Treeview")
        # Set up headings and column widths.
        col_widths = [120, 150, 120, 120, 100, 100, 150, 120, 120, 100, 100, 120, 120, 120, 120]
        for col, width in zip(self.columns, col_widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="center")
        
        # Configure a tag for error rows to have red text.
        self.tree.tag_configure("error", foreground="red")
        
        # Attach vertical and horizontal scrollbars.
        vsb = ttk.Scrollbar(self.results_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.results_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        # Create a status area below the Treeview for miscellaneous messages.
        self.status_text = ScrolledText.ScrolledText(self.results_frame, height=5, wrap=tk.WORD, background="white", foreground="black")
        self.status_text.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5,0))
        self.status_text.configure(state="disabled")

        # Setup a thread-safe queue for communication from the worker thread.
        self.output_queue = Queue.Queue()
        self.after(100, self.process_queue)
        if self._geometry_save_widget is not None and self._saved_geometry:
            try:
                self._geometry_save_widget.geometry(self._saved_geometry)
            except Exception:
                pass
        if self._geometry_save_widget is None:
            self.bind("<Destroy>", self._on_embed_destroy)

    def build_config_dict(self):
        """Builds the JSON payload for the current configuration."""
        geometry = None
        if self._geometry_save_widget is not None:
            try:
                geometry = self._geometry_save_widget.geometry()
            except Exception:
                geometry = None
        return {
            "version": CONFIG_VERSION,
            "configuration_name": self.config_name.get().strip(),
            "p111_dir": self.p111_dir.get(),
            "p211_dir": self.p211_dir.get(),
            "backup_dir": self.backup_dir.get(),
            "fesb_dir": self.fesb_dir.get(),
            "output_csv": self.output_csv.get(),
            "seq_range": self.seq_range.get(),
            "window_geometry": geometry,
            "default_save_dir": self.default_save_dir,
            "last_config_path": self.current_config_path,
        }

    def apply_config_dict(self, data, apply_window_layout=True):
        """Applies a loaded configuration dictionary to the UI."""
        if not isinstance(data, dict):
            return
        name = (data.get("configuration_name") or "").strip()
        if name:
            self.config_name.set(name)
        self.p111_dir.set(data.get("p111_dir", default_P111_DIR))
        self.p211_dir.set(data.get("p211_dir", default_P211_DIR))
        self.backup_dir.set(data.get("backup_dir", default_BACKUP_DIR))
        self.fesb_dir.set(data.get("fesb_dir", default_FESB_DIR))
        self.output_csv.set(data.get("output_csv", default_OUTPUT_CSV))
        self.seq_range.set(data.get("seq_range", "1-5"))
        save_dir = data.get("default_save_dir")
        if save_dir and os.path.isdir(save_dir):
            self.default_save_dir = save_dir
        last_path = data.get("last_config_path")
        if last_path:
            self.current_config_path = last_path
        if apply_window_layout:
            geometry = data.get("window_geometry")
            if geometry and self._geometry_save_widget is not None:
                self._saved_geometry = geometry
                try:
                    self._geometry_save_widget.geometry(geometry)
                except Exception:
                    pass

    def get_cache_path(self):
        """Returns the QC cache file path for the active configuration name."""
        return cache_path_for_name(self.config_name.get())

    def load_config_file(self, path):
        """Loads a configuration file (.xcfg or legacy .json)."""
        path = os.path.abspath(path)
        if not is_config_file_path(path):
            raise ValueError(
                "Not a configuration file: {}. Use a .xcfg file (not cache or session).".format(path)
            )
        f = open(path, "r")
        data = json.load(f)
        f.close()
        self.current_config_path = path
        self.default_save_dir = os.path.dirname(path)
        self.apply_config_dict(data, apply_window_layout=True)
        if not (data.get("configuration_name") or "").strip():
            self.config_name.set(safe_config_basename(os.path.basename(path)))
        self.save_session()

    def load_session_on_startup(self):
        """Loads the last session or configuration on startup."""
        if not os.path.isfile(SESSION_FILE):
            return
        try:
            f = open(SESSION_FILE, "r")
            session = json.load(f)
            f.close()
        except Exception as e:
            print("Error loading session from {}: {}".format(SESSION_FILE, e))
            return
        save_dir = session.get("default_save_dir")
        if save_dir and os.path.isdir(save_dir):
            self.default_save_dir = save_dir
        path = session.get("last_config_path")
        if path and os.path.isfile(path):
            try:
                self.load_config_file(path)
                return
            except Exception as e:
                print("Error loading last config {}: {}".format(path, e))
        self._saved_geometry = session.get("window_geometry")
        if session.get("p111_dir"):
            self.p111_dir.set(session.get("p111_dir", default_P111_DIR))
            self.p211_dir.set(session.get("p211_dir", default_P211_DIR))
            self.backup_dir.set(session.get("backup_dir", default_BACKUP_DIR))
            self.fesb_dir.set(session.get("fesb_dir", default_FESB_DIR))
            self.output_csv.set(session.get("output_csv", default_OUTPUT_CSV))
            self.seq_range.set(session.get("seq_range", "1-5"))
            name = session.get("configuration_name")
            if name:
                self.config_name.set(name)

    def save_session(self):
        """Persists session data including last loaded configuration."""
        ensure_data_dir()
        geometry = None
        if self._geometry_save_widget is not None:
            try:
                geometry = self._geometry_save_widget.geometry()
            except Exception:
                geometry = None
        session = {
            "last_config_path": self.current_config_path,
            "default_save_dir": self.default_save_dir,
            "window_geometry": geometry,
            "configuration_name": self.config_name.get().strip(),
            "p111_dir": self.p111_dir.get(),
            "p211_dir": self.p211_dir.get(),
            "backup_dir": self.backup_dir.get(),
            "fesb_dir": self.fesb_dir.get(),
            "output_csv": self.output_csv.get(),
            "seq_range": self.seq_range.get(),
        }
        try:
            f = open(SESSION_FILE, "w")
            json.dump(session, f, indent=2, sort_keys=True)
            f.close()
        except Exception as e:
            print("Error saving session to {}: {}".format(SESSION_FILE, e))

    def browse_load_config(self):
        """Browse/load dialog: load a config file or choose a save folder."""
        choice = run_config_browse_dialog(self.winfo_toplevel())
        if choice == "load":
            initialdir = self.default_save_dir if os.path.isdir(self.default_save_dir) else DEFAULT_DATA_DIR
            path = tkFileDialog.askopenfilename(
                parent=self.winfo_toplevel(),
                title="Load configuration",
                initialdir=initialdir,
                filetypes=[
                    ("xP1P2 config", "*.xcfg"),
                    ("Legacy JSON config", "*.json"),
                    ("All files", "*.*"),
                ],
            )
            if path:
                try:
                    if not is_config_file_path(path):
                        tkMessageBox.showerror(
                            "Load error",
                            "Not a configuration file:\n{}\n\nChoose a .xcfg file.".format(path),
                        )
                        return
                    self.load_config_file(path)
                    tkMessageBox.showinfo("Loaded", "Configuration loaded:\n{}".format(path))
                except Exception as ex:
                    tkMessageBox.showerror("Load error", str(ex))
        elif choice == "folder":
            initialdir = self.default_save_dir if os.path.isdir(self.default_save_dir) else DEFAULT_DATA_DIR
            directory = tkFileDialog.askdirectory(
                parent=self.winfo_toplevel(),
                title="Choose folder for saving configurations",
                initialdir=initialdir,
            )
            if directory:
                self.default_save_dir = os.path.abspath(directory)
                self.save_session()
                tkMessageBox.showinfo("Save folder", "Configurations will save to:\n{}".format(self.default_save_dir))

    def save_config(self):
        """Saves the current configuration to a .xcfg file."""
        name = safe_config_basename(self.config_name.get())
        self.config_name.set(name)
        if not os.path.isdir(self.default_save_dir):
            try:
                os.makedirs(self.default_save_dir)
            except Exception:
                self.default_save_dir = DEFAULT_DATA_DIR
                ensure_data_dir()
        path = config_path_for_name(name, self.default_save_dir)
        payload = self.build_config_dict()
        payload["last_config_path"] = path
        try:
            f = open(path, "w")
            json.dump(payload, f, indent=2, sort_keys=True)
            f.close()
            self.current_config_path = path
            self.save_session()
            tkMessageBox.showinfo("Saved", "Configuration saved:\n{}".format(path))
        except Exception as ex:
            tkMessageBox.showerror("Save error", str(ex))

    def load_settings(self):
        """Deprecated: retained for compatibility; session loader is used instead."""
        self.load_session_on_startup()

    def save_settings(self):
        """Saves session state and current configuration when a path is known."""
        self.save_session()
        if self.current_config_path:
            try:
                payload = self.build_config_dict()
                payload["last_config_path"] = self.current_config_path
                f = open(self.current_config_path, "w")
                json.dump(payload, f, indent=2, sort_keys=True)
                f.close()
            except Exception as e:
                print("Error auto-saving config {}: {}".format(self.current_config_path, e))

    def on_root_close(self):
        """Standalone window: save and destroy the Tk root."""
        self.save_settings()
        try:
            self.winfo_toplevel().destroy()
        except Exception:
            pass

    def _on_embed_destroy(self, event):
        # Tk may deliver a distinct wrapper; compare paths.
        try:
            if str(event.widget) != str(self):
                return
        except Exception:
            return
        try:
            self.save_settings()
        except Exception:
            pass

    def browse_p111(self):
        directory = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.p111_dir.get()
        )
        if directory:
            self.p111_dir.set(directory)

    def browse_p211(self):
        directory = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.p211_dir.get()
        )
        if directory:
            self.p211_dir.set(directory)

    def browse_backup(self):
        directory = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.backup_dir.get()
        )
        if directory:
            self.backup_dir.set(directory)

    def browse_fesb(self):
        directory = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.fesb_dir.get()
        )
        if directory:
            self.fesb_dir.set(directory)

    def browse_output(self):
        file_path = tkFileDialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            initialfile=self.output_csv.get(),
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if file_path:
            self.output_csv.set(file_path)

    def start_qc(self):
        # Disable the Start button to avoid multiple runs.
        self.start_button.config(state="disabled")
        # Clear previous results in the tree and status area.
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", tk.END)
        self.status_text.configure(state="disabled")
        # Start the QC process in a new thread.
        worker = QCWorker(self.p111_dir.get(), self.p211_dir.get(), self.backup_dir.get(),
                          self.fesb_dir.get(), self.output_csv.get(), self.seq_range.get(),
                          self.get_cache_path(), self.output_queue)
        worker.start()

    def process_queue(self):
        """Polls the output queue and updates the Treeview and status area."""
        while True:
            try:
                item = self.output_queue.get_nowait()
            except Queue.Empty:
                break
            else:
                msg_type, content = item
                if msg_type == "row":
                    # Check if any cell contains an error value.
                    if any(str(cell) in error_strings for cell in content): # Ensure cell is compared as string
                        self.tree.insert("", "end", values=content, tags=("error",))
                    else:
                        self.tree.insert("", "end", values=content)
                elif msg_type == "status":
                    self.status_text.configure(state="normal")
                    self.status_text.insert(tk.END, content)
                    self.status_text.see(tk.END)
                    self.status_text.configure(state="disabled")
                    # Re-enable the Start button when QC process is completed.
                    if "QC process completed" in content or "Invalid sequence range!" in content: # Also re-enable on error
                        self.start_button.config(state="normal")
        self.after(100, self.process_queue)


class QCApp(tk.Tk):
    """Standalone top-level window (same behavior as before refactor)."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.title("xP1P2 Final QC")
        self.geometry("1800x700")
        self.minsize(1800, 700)
        self.configure(background=GUI_BACKGROUND_COLOR)
        self.panel = QCAppPanel(self, geometry_save_widget=self)
        self.panel.pack(fill=tk.BOTH, expand=True)
        self.protocol("WM_DELETE_WINDOW", self.panel.on_root_close)


def xnavsl_embed(master):
    """Called by xNAVSL to show this tool inside a tab (no second Tk)."""
    panel = QCAppPanel(master, geometry_save_widget=None)
    panel.pack(fill=tk.BOTH, expand=True)


if __name__ == "__main__":
    app = QCApp()
    app.mainloop()
