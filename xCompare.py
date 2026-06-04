#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Ai assisted Code by RBolisay
import os
import json
import Tkinter as tk
import tkFileDialog  # Corrected import for Python 2.7 file dialogs
import ttk
import math # Needed for floor/log
import threading
import Queue

# --- Constants ---
DIR_MARKER = '<DIR>' # Marker for directories in our comparison dictionary
SCAN_THREADS = 2     # Source + copied scanned in parallel
PROGRESS_POLL_MS = 50

SETTINGS_DIR = "/usr/local/trinop/dbase/links/qcfiles/Misc/xCompare"
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "xCompare_settings.json")
DEFAULT_GEOMETRY = "750x650"

# --- Helper Functions ---

def format_size(size_bytes):
    """Converts a size in bytes to a human-readable string (KB, MB, GB, TB)."""
    if not isinstance(size_bytes, (int, long, float)) or size_bytes < 0:
        return str(size_bytes)
    if size_bytes == 0:
        return "0 bytes"
    size_names = ("bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    power = int(math.floor(math.log(size_bytes + 1e-9, 1024)))
    power = min(power, len(size_names) - 1)
    size_in_unit = float(size_bytes) / (1024**power)
    if power == 0:
        return "{:.0f} {}".format(size_in_unit, size_names[power])
    return "{:.2f} {}".format(size_in_unit, size_names[power])


def format_size_diff(source_size, copied_size):
    """Human-readable signed size difference between source and copied file sizes."""
    diff = long(copied_size) - long(source_size)
    sign = "+" if diff > 0 else ""
    return "{}{} ({})".format(sign, format_size(abs(diff)), sign + str(diff) if diff != 0 else "0")


class CompareProgress(object):
    """Thread-safe progress counters polled by the GUI (avoids queue flooding)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "Ready"
        self.scanned_source = 0
        self.scanned_copied = 0
        self.compared = 0
        self.total = 0
        self.good = 0
        self.bad = 0

    def set_phase(self, phase):
        with self.lock:
            self.phase = phase

    def set_scan_count(self, side, count):
        with self.lock:
            if side == "source":
                self.scanned_source = count
            else:
                self.scanned_copied = count

    def set_total(self, total):
        with self.lock:
            self.total = total

    def bump_compared(self, good_inc, bad_inc):
        with self.lock:
            self.compared += 1
            self.good += good_inc
            self.bad += bad_inc
            return self.compared, self.total, self.good, self.bad

    def reset(self):
        with self.lock:
            self.phase = "Ready"
            self.scanned_source = 0
            self.scanned_copied = 0
            self.compared = 0
            self.total = 0
            self.good = 0
            self.bad = 0

    def snapshot(self):
        with self.lock:
            return (
                self.phase,
                self.scanned_source,
                self.scanned_copied,
                self.compared,
                self.total,
                self.good,
                self.bad,
            )


def get_dir_contents_recursive(base_dir, progress=None, side=None, cancel_event=None):
    """
    Recursively walks through a directory and collects relative paths
    of files (with sizes) and directories.
    """
    contents = {}
    if not os.path.isdir(base_dir):
        return None, "Path is not a valid directory: {}".format(base_dir)

    item_count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(base_dir):
            if cancel_event and cancel_event.is_set():
                return None, "Comparison cancelled during directory scan."

            for filename in filenames:
                if cancel_event and cancel_event.is_set():
                    return None, "Comparison cancelled during directory scan."

                full_path = os.path.join(dirpath, filename)
                if not os.path.exists(full_path) and os.path.islink(full_path):
                    relative_path = os.path.relpath(full_path, base_dir)
                    contents[relative_path] = "Error accessing: Broken symbolic link"
                    item_count += 1
                    if progress and side:
                        progress.set_scan_count(side, item_count)
                    continue

                relative_path = os.path.relpath(full_path, base_dir)
                try:
                    if os.path.isfile(full_path):
                         contents[relative_path] = os.path.getsize(full_path)
                         item_count += 1
                         if progress and side:
                             progress.set_scan_count(side, item_count)
                    elif os.path.islink(full_path):
                         if not os.path.isdir(full_path):
                              contents[relative_path] = "Error accessing: Link to non-file/dir?"
                              item_count += 1
                              if progress and side:
                                  progress.set_scan_count(side, item_count)

                except OSError as e:
                    contents[relative_path] = "Error accessing: {}".format(e)
                    item_count += 1
                    if progress and side:
                        progress.set_scan_count(side, item_count)

            for dirname in dirnames:
                if cancel_event and cancel_event.is_set():
                    return None, "Comparison cancelled during directory scan."

                full_path = os.path.join(dirpath, dirname)
                relative_path = os.path.relpath(full_path, base_dir)
                contents[relative_path] = DIR_MARKER
                item_count += 1
                if progress and side:
                    progress.set_scan_count(side, item_count)

        return contents, None
    except OSError as e:
        return None, "Error walking directory {}: {}".format(base_dir, e)


def _evaluate_common_path(path, source_contents, copied_contents):
    """Compare one path present in both trees. Returns result dict."""
    s_val = source_contents[path]
    c_val = copied_contents[path]
    result = {
        "good_inc": 0,
        "bad_inc": 0,
        "match_inc": 0,
        "mismatch_inc": 0,
        "discrepancy_text": None,
        "discrepancy_tag": None,
    }

    if isinstance(s_val, basestring) and s_val.startswith("Error"):
        result["bad_inc"] = 1
        result["mismatch_inc"] = 1
        result["discrepancy_text"] = "ACCESS ERROR (Source): {}\n  {}\n".format(path, s_val)
        result["discrepancy_tag"] = "error"
    elif isinstance(c_val, basestring) and c_val.startswith("Error"):
        result["bad_inc"] = 1
        result["mismatch_inc"] = 1
        result["discrepancy_text"] = "ACCESS ERROR (Copied): {}\n  {}\n".format(path, c_val)
        result["discrepancy_tag"] = "error"
    elif s_val == DIR_MARKER and c_val == DIR_MARKER:
        result["good_inc"] = 1
        result["match_inc"] = 1
    elif s_val == DIR_MARKER or c_val == DIR_MARKER:
        result["bad_inc"] = 1
        result["mismatch_inc"] = 1
        s_type = "Dir" if s_val == DIR_MARKER else "File"
        c_type = "Dir" if c_val == DIR_MARKER else "File"
        result["discrepancy_text"] = "MISMATCH (Type): {} (Source: {}, Copied: {})\n".format(path, s_type, c_type)
        result["discrepancy_tag"] = "mismatch_type"
    else:
        try:
            s_size = long(s_val)
            c_size = long(c_val)
            if s_size == c_size:
                result["good_inc"] = 1
                result["match_inc"] = 1
            else:
                result["bad_inc"] = 1
                result["mismatch_inc"] = 1
                size_diff = format_size_diff(s_size, c_size)
                result["discrepancy_text"] = (
                    "MISMATCH (Size): {}\n  Source: {}  |  Copied: {}  |  Diff: {}\n".format(
                        path, format_size(s_size), format_size(c_size), size_diff)
                )
                result["discrepancy_tag"] = "mismatch_size"
        except (ValueError, TypeError):
            result["bad_inc"] = 1
            result["mismatch_inc"] = 1
            result["discrepancy_text"] = "MISMATCH (Data?): {} (Source: '{}', Copied: '{}')\n".format(path, s_val, c_val)
            result["discrepancy_tag"] = "error"

    return result


def _scan_directory(side, base_dir, cancel_event, progress, scan_state, scan_lock):
    contents, err = get_dir_contents_recursive(
        base_dir,
        progress=progress,
        side=side,
        cancel_event=cancel_event,
    )
    with scan_lock:
        scan_state[side] = (contents, err)


def _compare_worker(source_dir, copied_dir, cancel_event, progress, result_queue):
    """
    Scan both trees in parallel, then compare in one pass.
    Progress counters update in real time; result_queue carries text output only.
    """
    try:
        progress.set_phase("Scanning directories (parallel)...")

        scan_state = {}
        scan_lock = threading.Lock()
        scan_threads = [
            threading.Thread(
                target=_scan_directory,
                args=("source", source_dir, cancel_event, progress, scan_state, scan_lock),
            ),
            threading.Thread(
                target=_scan_directory,
                args=("copied", copied_dir, cancel_event, progress, scan_state, scan_lock),
            ),
        ]
        for t in scan_threads:
            t.daemon = True
            t.start()
        for t in scan_threads:
            t.join()

        source_contents, source_err = scan_state.get("source", (None, "Scan did not complete"))
        copied_contents, copied_err = scan_state.get("copied", (None, "Scan did not complete"))

        if source_err:
            result_queue.put(("error", "Error reading Source directory:\n{}\n".format(source_err)))
            return
        if copied_err:
            result_queue.put(("error", "Error reading Copied directory:\n{}\n".format(copied_err)))
            return
        if cancel_event.is_set():
            result_queue.put(("log", "\nComparison cancelled by user.\n", "warning"))
            return

        source_paths = set(source_contents.keys())
        copied_paths = set(copied_contents.keys())

        common_paths = sorted(source_paths.intersection(copied_paths))
        source_only_paths = sorted(source_paths - copied_paths)
        copied_only_paths = sorted(copied_paths - source_paths)

        total_items = len(common_paths) + len(source_only_paths) + len(copied_only_paths)
        progress.set_total(total_items)
        progress.set_phase("Comparing...")
        result_queue.put(("log", "\n--- Discrepancies ---\n", None))

        match_count = 0
        mismatch_count = 0
        source_only_count = 0
        copied_only_count = 0
        discrepancy_seen = False

        for path in common_paths:
            if cancel_event.is_set():
                result_queue.put(("log", "\nComparison cancelled by user.\n", "warning"))
                return

            ev = _evaluate_common_path(path, source_contents, copied_contents)
            progress.bump_compared(ev["good_inc"], ev["bad_inc"])
            match_count += ev["match_inc"]
            mismatch_count += ev["mismatch_inc"]
            if ev["discrepancy_text"]:
                discrepancy_seen = True
                result_queue.put(("discrepancy", ev["discrepancy_text"], ev["discrepancy_tag"]))

        if source_only_paths:
            result_queue.put(("log", "\n--- Items Only in Source Directory ---\n", None))
            for path in source_only_paths:
                if cancel_event.is_set():
                    result_queue.put(("log", "\nComparison cancelled by user.\n", "warning"))
                    return
                s_val = source_contents[path]
                item_type = "Directory" if s_val == DIR_MARKER else "File"
                if isinstance(s_val, basestring) and s_val.startswith("Error"):
                    item_type = "Access Error"
                progress.bump_compared(0, 1)
                source_only_count += 1
                discrepancy_seen = True
                result_queue.put(("discrepancy",
                    "SOURCE ONLY ({}): {}\n".format(item_type, path), "source_only"))

        if copied_only_paths:
            result_queue.put(("log", "\n--- Items Only in Copied Directory ---\n", None))
            for path in copied_only_paths:
                if cancel_event.is_set():
                    result_queue.put(("log", "\nComparison cancelled by user.\n", "warning"))
                    return
                c_val = copied_contents[path]
                item_type = "Directory" if c_val == DIR_MARKER else "File"
                if isinstance(c_val, basestring) and c_val.startswith("Error"):
                    item_type = "Access Error"
                progress.bump_compared(0, 1)
                copied_only_count += 1
                discrepancy_seen = True
                result_queue.put(("discrepancy",
                    "COPIED ONLY ({}): {}\n".format(item_type, path), "copied_only"))

        if not discrepancy_seen:
            result_queue.put(("log", "(None)\n", None))

        result_queue.put(("log", "\n--- Summary ---\n", None))
        result_queue.put(("log", "Matched items (GOOD): {}\n".format(match_count), "summary"))
        result_queue.put(("log", "Mismatched items (BAD): {}\n".format(mismatch_count), "summary"))
        result_queue.put(("log", "Items only in Source: {}\n".format(source_only_count), "summary"))
        result_queue.put(("log", "Items only in Copied: {}\n".format(copied_only_count), "summary"))
        result_queue.put(("log", "\nComparison finished.\n", None))
        progress.set_phase("Complete")

    except Exception as e:
        result_queue.put(("error", "Unexpected error during comparison:\n{}\n".format(e)))
    finally:
        result_queue.put(None)


class XComparePanel(ttk.Frame):
    """Main xCompare UI as a Frame for standalone or xNAVSL embed."""

    def __init__(self, master, geometry_save_widget=None):
        ttk.Frame.__init__(self, master, padding=0)
        self._geometry_save_widget = geometry_save_widget
        self._saved_geometry = None

        self.compare_thread = None
        self.compare_cancel = threading.Event()
        self.compare_progress = CompareProgress()
        self.result_queue = Queue.Queue()
        self._progress_poll_active = False

        self._build_styles()
        self._build_widgets()
        self.load_settings()
        self._apply_saved_geometry()

        if self._geometry_save_widget is None:
            self.bind("<Destroy>", self._on_embed_destroy)

    def _build_styles(self):
        self.gui_bg_color = "#B4C8E1"
        self.button_bg_color = "#8DA9CC"
        self.button_text_color = "black"
        self.default_font = ("Arial", 10)

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            print("Warning: 'clam' theme not available, using default.")

        style.configure('TButton', background=self.button_bg_color, foreground=self.button_text_color, font=self.default_font)
        style.configure('TLabel', background=self.gui_bg_color, foreground='black', font=self.default_font)
        style.configure('TFrame', background=self.gui_bg_color)
        style.configure('TLabelframe', background=self.gui_bg_color)
        style.configure('TLabelframe.Label', background=self.gui_bg_color, foreground='black')
        style.configure('Good.TLabel', background=self.gui_bg_color, foreground='darkgreen', font=(self.default_font[0], self.default_font[1], "bold"))
        style.configure('Bad.TLabel', background=self.gui_bg_color, foreground='red', font=(self.default_font[0], self.default_font[1], "bold"))
        style.configure('Count.TLabel', background=self.gui_bg_color, foreground='black', font=(self.default_font[0], self.default_font[1], "bold"))

        top = self.winfo_toplevel()
        try:
            top.configure(bg=self.gui_bg_color)
        except tk.TclError:
            pass

    def _build_widgets(self):
        description_text = (
            "This tool recursively compares files and folders between two directories based on their relative paths.\n"
            "It flags differences in file size, item type (file/directory), and items existing in only one location."
        )
        description_label = ttk.Label(self, text=description_text, justify=tk.CENTER, relief=tk.GROOVE, padding=(5, 5))
        description_label.pack(pady=10, padx=10, fill=tk.X)

        dir_frame = ttk.Frame(self, padding=(10, 5))
        dir_frame.pack(fill=tk.X)

        self.source_directory = tk.StringVar()
        self.copied_directory = tk.StringVar()

        ttk.Label(dir_frame, text="Source Directory:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.source_entry = ttk.Entry(dir_frame, textvariable=self.source_directory, width=60)
        self.source_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.source_button = ttk.Button(
            dir_frame, text="Browse...",
            command=lambda: self._browse_directory(self.source_directory, "Select Source Directory"),
        )
        self.source_button.grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(dir_frame, text="Copied Directory:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.copied_entry = ttk.Entry(dir_frame, textvariable=self.copied_directory, width=60)
        self.copied_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        self.copied_button = ttk.Button(
            dir_frame, text="Browse...",
            command=lambda: self._browse_directory(self.copied_directory, "Select Copied Directory"),
        )
        self.copied_button.grid(row=1, column=2, padx=5, pady=5)
        dir_frame.columnconfigure(1, weight=1)

        status_frame = ttk.LabelFrame(self, text="Progress", padding=(8, 6))
        status_frame.pack(pady=(0, 5), padx=10, fill=tk.X)

        self.status_phase_var = tk.StringVar(value="Ready")
        self.status_compared_var = tk.StringVar(value="Compared: 0 / 0")
        self.status_good_var = tk.StringVar(value="GOOD: 0")
        self.status_bad_var = tk.StringVar(value="BAD: 0")

        ttk.Label(status_frame, textvariable=self.status_phase_var).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 4))
        ttk.Label(status_frame, textvariable=self.status_compared_var, style="Count.TLabel").grid(row=1, column=0, padx=(0, 18), sticky=tk.W)
        ttk.Label(status_frame, textvariable=self.status_good_var, style="Good.TLabel").grid(row=1, column=1, padx=(0, 18), sticky=tk.W)
        ttk.Label(status_frame, textvariable=self.status_bad_var, style="Bad.TLabel").grid(row=1, column=2, sticky=tk.W)

        results_outer_frame = ttk.LabelFrame(self, text="Comparison Results", padding=(5, 5))
        results_outer_frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        result_box_bg_color = "#FFFFFF"
        self.result_box = tk.Text(
            results_outer_frame, wrap=tk.WORD, height=20, width=80,
            state=tk.DISABLED, background=result_box_bg_color, relief=tk.SUNKEN, borderwidth=1,
        )
        self.result_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        scrollbar = ttk.Scrollbar(results_outer_frame, orient="vertical", command=self.result_box.yview)
        scrollbar.pack(side=tk.RIGHT, fill="y")
        self.result_box.configure(yscrollcommand=scrollbar.set)

        bold_font = ("Arial", 10, "bold")
        self.result_box.tag_configure("matched_file", foreground="darkgreen")
        self.result_box.tag_configure("matched_dir", foreground="green")
        self.result_box.tag_configure("mismatch_size", foreground="red", font=bold_font)
        self.result_box.tag_configure("mismatch_type", foreground="magenta", font=bold_font)
        self.result_box.tag_configure("source_only", foreground="blue")
        self.result_box.tag_configure("copied_only", foreground="orange")
        self.result_box.tag_configure("warning", foreground="darkgoldenrod")
        self.result_box.tag_configure("error", foreground="white", background="red", font=bold_font)
        self.result_box.tag_configure("summary", foreground="purple")

        button_frame = ttk.Frame(self, padding=(0, 0))
        button_frame.pack(pady=10)

        self.compare_button = ttk.Button(button_frame, text="Compare Directories", command=self.compare_directories)
        self.compare_button.pack(side=tk.LEFT, padx=(0, 8))

        self.cancel_button = ttk.Button(button_frame, text="Cancel", command=self.cancel_compare, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT)

        self.pack(fill=tk.BOTH, expand=True)

    def _browse_directory(self, string_var, title):
        chosen = tkFileDialog.askdirectory(title=title)
        if chosen:
            string_var.set(chosen)
            self.save_settings()

    def _apply_saved_geometry(self):
        if self._geometry_save_widget is not None and self._saved_geometry:
            try:
                self._geometry_save_widget.geometry(self._saved_geometry)
            except Exception:
                pass

    def load_settings(self):
        if not os.path.isfile(SETTINGS_FILE):
            return
        try:
            f = open(SETTINGS_FILE, "r")
            settings = json.load(f)
            f.close()
        except Exception as e:
            print("Error loading settings from {}: {}".format(SETTINGS_FILE, e))
            return

        self.source_directory.set(settings.get("source_dir", ""))
        self.copied_directory.set(settings.get("copied_dir", ""))
        self._saved_geometry = settings.get("window_geometry")

    def save_settings(self):
        settings = {
            "source_dir": self.source_directory.get(),
            "copied_dir": self.copied_directory.get(),
        }
        if self._geometry_save_widget is not None:
            try:
                settings["window_geometry"] = self._geometry_save_widget.geometry()
            except Exception:
                settings["window_geometry"] = None
        try:
            if not os.path.isdir(SETTINGS_DIR):
                os.makedirs(SETTINGS_DIR)
            f = open(SETTINGS_FILE, "w")
            json.dump(settings, f, indent=2, sort_keys=True)
            f.close()
        except Exception as e:
            print("Error saving settings to {}: {}".format(SETTINGS_FILE, e))

    def _on_embed_destroy(self, event):
        if event.widget is self:
            self.save_settings()

    def on_root_close(self):
        self.save_settings()
        try:
            self.winfo_toplevel().destroy()
        except Exception:
            pass

    def _set_compare_controls(self, running):
        state = tk.DISABLED if running else tk.NORMAL
        self.compare_button.config(state=state)
        self.cancel_button.config(state=tk.NORMAL if running else tk.DISABLED)
        self.source_button.config(state=state)
        self.copied_button.config(state=state)

    def _reset_status_labels(self):
        self.compare_progress.reset()
        self._refresh_progress_labels()

    def _refresh_progress_labels(self):
        phase, scanned_source, scanned_copied, compared, total, good, bad = self.compare_progress.snapshot()
        self.status_phase_var.set(phase)
        if phase.startswith("Scanning"):
            self.status_compared_var.set(
                "Scanned: source {}  |  copied {}".format(scanned_source, scanned_copied)
            )
        elif total > 0:
            self.status_compared_var.set("Compared: {} / {}".format(compared, total))
        else:
            self.status_compared_var.set("Compared: {} / ...".format(compared))
        self.status_good_var.set("GOOD: {}".format(good))
        self.status_bad_var.set("BAD: {}".format(bad))

    def _append_result(self, text, tag=None):
        self.result_box.config(state=tk.NORMAL)
        if tag:
            self.result_box.insert(tk.END, text, tag)
        else:
            self.result_box.insert(tk.END, text)
        self.result_box.see(tk.END)
        self.result_box.config(state=tk.DISABLED)

    def _poll_progress_and_results(self):
        if not self._progress_poll_active:
            return

        self._refresh_progress_labels()

        try:
            while True:
                msg = self.result_queue.get_nowait()
                if msg is None:
                    self._compare_finished()
                    return
                kind = msg[0]
                if kind == "log":
                    self._append_result(msg[1], msg[2])
                elif kind == "discrepancy":
                    self._append_result(msg[1], msg[2])
                elif kind == "error":
                    self._append_result(msg[1], "error")
        except Queue.Empty:
            pass

        self.after(PROGRESS_POLL_MS, self._poll_progress_and_results)

    def _compare_finished(self):
        self._progress_poll_active = False
        self._refresh_progress_labels()
        self._set_compare_controls(False)
        self.compare_thread = None
        self.save_settings()
        try:
            self.result_box.config(state=tk.NORMAL)
            self.result_box.see(tk.END)
            self.result_box.config(state=tk.DISABLED)
        except tk.TclError:
            pass

    def cancel_compare(self):
        if self.compare_thread and self.compare_thread.is_alive():
            self.compare_cancel.set()
            self.compare_progress.set_phase("Cancelling...")

    def compare_directories(self):
        if self.compare_thread and self.compare_thread.is_alive():
            return

        source_dir = self.source_directory.get()
        copied_dir = self.copied_directory.get()

        self.result_box.config(state=tk.NORMAL)
        self.result_box.delete(1.0, tk.END)
        self._reset_status_labels()

        if not source_dir or not copied_dir:
            self._append_result("Please select BOTH Source and Copied directories first!\n", "warning")
            return

        if not os.path.isdir(source_dir):
            self._append_result("Error: Source path is not a valid directory!\n", "error")
            return
        if not os.path.isdir(copied_dir):
            self._append_result("Error: Copied path is not a valid directory!\n", "error")
            return

        self.save_settings()
        self._append_result("Starting comparison...\nSource: {}\nCopied: {}\n".format(source_dir, copied_dir))
        self.compare_progress.set_phase("Starting...")

        self.compare_cancel.clear()
        self._set_compare_controls(True)
        self._progress_poll_active = True

        self.compare_thread = threading.Thread(
            target=_compare_worker,
            args=(source_dir, copied_dir, self.compare_cancel, self.compare_progress, self.result_queue),
        )
        self.compare_thread.daemon = True
        self.compare_thread.start()
        self.after(PROGRESS_POLL_MS, self._poll_progress_and_results)


class XCompareApp(tk.Tk):
    """Standalone top-level window."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.title("xCompare")
        self.geometry(DEFAULT_GEOMETRY)
        self.minsize(520, 480)
        self.option_add("*Font", ("Arial", 10))
        self.panel = XComparePanel(self, geometry_save_widget=self)
        self.protocol("WM_DELETE_WINDOW", self.panel.on_root_close)


def xnavsl_embed(master):
    """Called by xNAVSL to show this tool inside a tab (no second Tk)."""
    panel = XComparePanel(master, geometry_save_widget=None)
    panel.pack(fill=tk.BOTH, expand=True)
    return panel


if __name__ == "__main__":
    app = XCompareApp()
    app.mainloop()
