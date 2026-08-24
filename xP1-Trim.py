#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# xP1-Trim — trim an IOGP P1/11 or UKOOA P1/90 file to a selected shotpoint range.
# Python 2.7 only (Tkinter), stdlib only: runs on the frozen deployment server.
#
# P1/11 (CSV): keeps every non-per-shot line (OGP/HC/CC/H1 preamble, N1/M1
# trailer, anything unrecognised) plus the S1/P1/R1 records whose shotpoint
# (field index 4, as in TierMaps p111_parser: S1_REC_SPN_IDX = P_REC_SPN_IDX = 4)
# is in the selected ranges.
# P1/90 (fixed width): keeps H* headers plus every record of the selected shot
# blocks. V/E/S/W/T/C records carry the point number at columns 20-25 (TierMaps
# p190: slice_field(line, 20, 25)); R records carry no point number and inherit
# the current shot, exactly as TierMaps parse_p190_receiver_feathers does
# (current_shotpoint set on 'S', R records attributed to it).
# Lines are copied byte-for-byte in source order; a verify pass re-filters the
# source and cross-checks the output line-by-line against it.
#
# Embeds in xNAVSL via def xnavsl_embed(master) (Option A hook, same pattern as
# xShotinfo/xCompare/xSeisCal); runs standalone under __main__.

import Tkinter as tk
import tkFileDialog
import tkMessageBox
import ScrolledText
import json
import os
import re
import sys
import threading
import time
import Queue

# --- xNAVSL palette ---
COLOR_BG = "#aec6dd"
COLOR_BTN = "#9cb6cf"
COLOR_BTN_ACTIVE = "#8cabc2"
COLOR_TEXT = "#000000"
COLOR_HEADER = "#000033"
COLOR_STATUS_BG = "#f5f8fc"

APP_TITLE = "xP1-Trim - P1 Shotpoint Trimmer"
DEFAULT_WIDTH, DEFAULT_HEIGHT = 860, 560
DEFAULT_CONFIG_DIR = os.path.join(os.path.expanduser("~"), "xP1TrimConfigs")
LAST_CONFIG_MARKER = os.path.join(DEFAULT_CONFIG_DIR, ".last_config_path")

# P1/11 per-shot record types; shotpoint number at field index 4 (0-based after
# split(',')) — verified against SSFILTREG sample and TierMaps p111_parser.cpp.
PER_SHOT_TYPES = ("S1", "P1", "R1")
SPN_IDX = 4
# P1/11 file-level types that are expected to be kept wholesale. Anything else
# that is not per-shot is ALSO kept (never dropped), but reported as unknown.
P111_FILE_LEVEL = ("OGP", "HC", "CC", "C1", "H1", "N1", "M1")

# P1/90 record ids that carry the point number at columns 20-25 (1-based),
# i.e. line[19:25] — TierMaps p190 slice_field(line, 20, 25). R records carry
# no point number and inherit the current shot block, as in TierMaps
# parse_p190_receiver_feathers (current_shotpoint + R attribution).
P190_SP_SLICE = slice(19, 25)
P190_KNOWN_TYPES = "HVESWTCR"

PROGRESS_EVERY_LINES = 4000


def detect_format(path):
    """'p111' or 'p190' by extension, else by sniffing the first line."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".p190", ".190"):
        return "p190"
    if ext in (".p111", ".111"):
        return "p111"
    try:
        f = open(path, "rb")
        try:
            first = f.read(4096).split("\n", 1)[0]
        finally:
            f.close()
    except (IOError, OSError):
        return "p111"
    if first.startswith("OGP,"):
        return "p111"
    if first[:1] == "H" and first[1:5].isdigit():
        return "p190"
    return "p111"


class P111Classifier(object):
    """Stateless: S1/P1/R1 filtered by field index 4; everything else kept."""
    format_name = "P1/11"

    def rectype(self, line):
        return line.split(",", 1)[0].strip() if "," in line[:12] else line[:8].strip()

    def classify(self, line):
        return classify_line(line)

    def unknown_kept_types(self, census):
        return sorted(t for t in census
                      if t not in P111_FILE_LEVEL and t not in PER_SHOT_TYPES)


class P190Classifier(object):
    """Stateful: H* kept; V/E/S/W/T/C own the point at cols 20-25 and update the
    current shot block; R (and anything without a readable point) inherits it."""
    format_name = "P1/90"

    def __init__(self):
        self.current = None

    def rectype(self, line):
        return line[:1] if line[:1] not in ("", "\n", "\r") else "<blank>"

    def classify(self, line):
        c = line[:1]
        if c == "H":
            return False, None
        if c != "R":
            s = line[P190_SP_SLICE].strip()
            if s:
                try:
                    spn = int(s)
                    self.current = spn
                    return True, spn
                except ValueError:
                    pass
        return True, self.current

    def unknown_kept_types(self, census):
        return sorted(t for t in census if t[:1] not in P190_KNOWN_TYPES)


def make_classifier(path):
    return P190Classifier() if detect_format(path) == "p190" else P111Classifier()


# ----------------------------------------------------------------- core logic
def parse_sp_ranges(text):
    """'1001-1010, 1015, 1020-1100' -> sorted list of ints. ValueError on junk."""
    spset = set()
    for token in re.split(r"[,;]+", text.strip()):
        token = token.strip()
        if not token:
            continue
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", token)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            if b - a > 5000000:
                raise ValueError("Range too large: %s" % token)
            spset.update(xrange(a, b + 1))
            continue
        if re.match(r"^\d+$", token):
            spset.add(int(token))
            continue
        raise ValueError("Bad shotpoint token: %r (use e.g. 1001-1010, 1015)" % token)
    if not spset:
        raise ValueError("No shotpoints given")
    return sorted(spset)


def classify_line(line):
    """Return (is_per_shot, spn or None). Non-per-shot lines are always kept."""
    rectype = line[:3]
    if rectype[:2] in PER_SHOT_TYPES and rectype[2:3] == ",":
        parts = line.split(",", SPN_IDX + 1)
        if len(parts) > SPN_IDX:
            try:
                return True, int(parts[SPN_IDX].strip())
            except ValueError:
                return True, None
        return True, None
    return False, None


def _own_spn(line, fmt):
    """Point number carried BY this line (no block inheritance), else None."""
    if fmt == "p190":
        c = line[:1]
        if c in ("H", "R", ""):
            return None
        s = line[P190_SP_SLICE].strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    per_shot, spn = classify_line(line)
    return spn if per_shot else None


def scan_sp_extent(path):
    """(first_spn, last_spn) in file order, from the head and a tail chunk only —
    never scans the middle, so it is fast even on multi-GB files."""
    fmt = detect_format(path)
    first = None
    f = open(path, "rb")
    try:
        for i, line in enumerate(f):
            spn = _own_spn(line, fmt)
            if spn is not None:
                first = spn
                break
            if i > 100000:
                break
        size = os.path.getsize(path)
        last = None
        chunk = 1024 * 1024
        while last is None:
            off = max(0, size - chunk)
            f.seek(off)
            lines = f.read(chunk).split("\n")
            start_idx = 1 if off > 0 else 0  # first element may be a partial line
            for ln in reversed(lines[start_idx:]):
                spn = _own_spn(ln, fmt)
                if spn is not None:
                    last = spn
                    break
            if off == 0:
                break
            chunk *= 4
        return first, last
    finally:
        f.close()


def sanitize_range_for_filename(text):
    out = re.sub(r"\s+", "", text).replace(";", ",").replace(",", "_")
    return re.sub(r"[^0-9_\-]", "", out)


def default_output_name(source_path, range_text):
    base = os.path.basename(source_path)
    stem, ext = os.path.splitext(base)
    if ext.lower() not in (".p111", ".111", ".p190", ".190"):
        stem, ext = base, ".p111"
    rng = sanitize_range_for_filename(range_text)
    suffix = "_SP%s" % rng if rng else "_trimmed"
    return "%s%s%s" % (stem, suffix, ext)


def trim_p111(src_path, dst_path, spset, log, progress, cancelled):
    """Stream src -> dst keeping headers + selected shotpoint records.
    Returns stats dict, or None if cancelled (partial output removed)."""
    total_bytes = os.path.getsize(src_path)
    cls = make_classifier(src_path)
    stats = {"lines": 0, "kept_headers": 0, "kept_records": 0, "skipped_records": 0,
             "bad_spn": 0, "type_census": {}, "kept_by_type": {}, "sps_found": set(),
             "sps_kept": set(), "out_lines": 0, "format": cls.format_name,
             "unknown_types": []}
    read_bytes = 0
    src = open(src_path, "rb")
    dst = open(dst_path, "wb")
    try:
        for line in src:
            stats["lines"] += 1
            read_bytes += len(line)
            rectype = cls.rectype(line)
            stats["type_census"][rectype] = stats["type_census"].get(rectype, 0) + 1
            per_shot, spn = cls.classify(line)
            if per_shot:
                if spn is None:
                    stats["bad_spn"] += 1
                    stats["skipped_records"] += 1
                else:
                    stats["sps_found"].add(spn)
                    if spn in spset:
                        dst.write(line)
                        stats["kept_records"] += 1
                        stats["out_lines"] += 1
                        stats["sps_kept"].add(spn)
                        stats["kept_by_type"][rectype] = stats["kept_by_type"].get(rectype, 0) + 1
                    else:
                        stats["skipped_records"] += 1
            else:
                dst.write(line)
                stats["kept_headers"] += 1
                stats["out_lines"] += 1
            if stats["lines"] % PROGRESS_EVERY_LINES == 0:
                if cancelled.is_set():
                    return None
                progress("Trim", read_bytes, total_bytes, stats["lines"])
        progress("Trim", total_bytes, total_bytes, stats["lines"])
    finally:
        src.close()
        dst.close()
        if cancelled.is_set() and os.path.exists(dst_path):
            try:
                os.remove(dst_path)
                log("Cancelled - partial output removed.")
            except OSError as e:
                log("Cancelled - could not remove partial output: %s" % e)
    if cancelled.is_set():
        return None
    stats["unknown_types"] = cls.unknown_kept_types(stats["type_census"])
    return stats


def verify_trim(src_path, dst_path, spset, log, progress, cancelled):
    """Re-filter source and compare with output byte-for-byte, in order.
    Returns stats dict, or None if cancelled."""
    total_bytes = os.path.getsize(src_path)
    cls = make_classifier(src_path)  # fresh state: verify re-derives every decision
    stats = {"headers_checked": 0, "records_checked": 0, "match": 0, "mismatch": 0,
             "extra_in_output": 0, "records_per_sp": {}, "lines": 0}
    read_bytes = 0
    src = open(src_path, "rb")
    out = open(dst_path, "rb")
    try:
        for line in src:
            stats["lines"] += 1
            read_bytes += len(line)
            per_shot, spn = cls.classify(line)
            expected = None
            if per_shot:
                if spn is not None and spn in spset:
                    expected = line
            else:
                expected = line
            if expected is not None:
                got = out.readline()
                if got == expected:
                    stats["match"] += 1
                else:
                    stats["mismatch"] += 1
                    if stats["mismatch"] <= 5:
                        log("MISMATCH at source line %d (%s...)" %
                            (stats["lines"], expected[:40].rstrip()))
                if per_shot:
                    stats["records_checked"] += 1
                    stats["records_per_sp"][spn] = stats["records_per_sp"].get(spn, 0) + 1
                else:
                    stats["headers_checked"] += 1
            if stats["lines"] % PROGRESS_EVERY_LINES == 0:
                if cancelled.is_set():
                    return None
                progress("Verify", read_bytes, total_bytes, stats["lines"])
        rest = out.readline()
        while rest:
            stats["extra_in_output"] += 1
            rest = out.readline()
        progress("Verify", total_bytes, total_bytes, stats["lines"])
    finally:
        src.close()
        out.close()
    if cancelled.is_set():
        return None
    return stats


# ------------------------------------------------------------------------ GUI
class XP1TrimPanel(tk.Frame):
    def __init__(self, master, **kw):
        tk.Frame.__init__(self, master, bg=COLOR_BG, **kw)
        self.master = master
        self.worker = None
        self.cancelled = threading.Event()
        self.msg_queue = Queue.Queue()
        self._poll_id = None

        self.config_path_var = tk.StringVar()
        self.config_name_var = tk.StringVar(value="Default")
        self.source_var = tk.StringVar()
        self.range_var = tk.StringVar()
        self.output_name_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self._out_name_edited = [False]
        self._out_dir_chosen = [False]
        self._last_scanned = [None]

        self._build_ui()
        self._load_last_config()
        self.range_var.trace("w", self._auto_output_name)
        self.source_var.trace("w", self._on_source_change)
        self._on_source_change()
        self._start_poll()

    # ---- UI construction
    def _build_ui(self):
        pad = dict(padx=6, pady=3)
        self.columnconfigure(1, weight=1)

        hdr = tk.Label(self, text="xP1-Trim  -  P1 Shotpoint Trimmer",
                       bg=COLOR_BG, fg=COLOR_HEADER, font=("TkDefaultFont", 11, "bold"))
        hdr.grid(row=0, column=0, columnspan=4, sticky="w", **pad)

        tk.Label(self, text="Configuration Name", bg=COLOR_BG, fg=COLOR_TEXT
                 ).grid(row=1, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.config_name_var
                 ).grid(row=1, column=1, sticky="ew", **pad)
        self._btn(self, "Save", self.save_config).grid(row=1, column=2, **pad)
        self._btn(self, "Browse/Select", self.browse_config).grid(row=1, column=3, **pad)

        tk.Label(self, text="Source P1", bg=COLOR_BG, fg=COLOR_TEXT
                 ).grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.source_var
                 ).grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        self._btn(self, "Browse/Select", self.browse_source).grid(row=2, column=3, **pad)

        self.sp_extent_label = tk.Label(self, text="", bg=COLOR_BG, fg="#404040")
        self.sp_extent_label.grid(row=3, column=1, columnspan=3, sticky="w",
                                  padx=6, pady=(0, 2))

        tk.Label(self, text="Shotpoint Range", bg=COLOR_BG, fg=COLOR_TEXT
                 ).grid(row=4, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.range_var
                 ).grid(row=4, column=1, columnspan=2, sticky="ew", **pad)
        tk.Label(self, text="e.g. 1001-1010, 1015, 1020-1100", bg=COLOR_BG, fg="#404040"
                 ).grid(row=4, column=3, sticky="w", **pad)

        tk.Label(self, text="Output P1 - Trimmed", bg=COLOR_BG, fg=COLOR_TEXT
                 ).grid(row=5, column=0, sticky="w", **pad)
        out_entry = tk.Entry(self, textvariable=self.output_name_var)
        out_entry.grid(row=5, column=1, columnspan=2, sticky="ew", **pad)
        out_entry.bind("<Key>", lambda e: self._out_name_edited.__setitem__(0, True))
        self._btn(self, "Browse/Select", self.browse_output_dir).grid(row=5, column=3, **pad)

        self.out_dir_label = tk.Label(self, text="", bg=COLOR_BG, fg="#404040")
        self.out_dir_label.grid(row=6, column=1, columnspan=3, sticky="w",
                                padx=6, pady=(0, 2))

        self.status = ScrolledText.ScrolledText(self, height=14, wrap=tk.NONE,
                                                bg=COLOR_STATUS_BG, fg=COLOR_TEXT,
                                                state=tk.DISABLED)
        self.status.grid(row=7, column=0, columnspan=4, sticky="nsew", padx=6, pady=6)
        self.rowconfigure(7, weight=1)

        self.exec_btn = self._btn(self, "Execute Trim", self.on_execute)
        self.exec_btn.config(width=18)
        self.exec_btn.grid(row=8, column=0, columnspan=4, pady=(0, 8))

    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=COLOR_BTN,
                         activebackground=COLOR_BTN_ACTIVE, fg=COLOR_TEXT)

    # ---- status helpers
    def log(self, msg):
        self.msg_queue.put(("log", msg))

    def _append_status(self, msg):
        self.status.config(state=tk.NORMAL)
        self.status.insert(tk.END, msg + "\n")
        self.status.see(tk.END)
        self.status.config(state=tk.DISABLED)

    def _progress(self, phase, done, total, lines):
        pct = 100.0 * done / total if total else 0.0
        self.msg_queue.put(("progress", "%s: %5.1f%%  (%s lines)" % (phase, pct, lines)))

    def _start_poll(self):
        try:
            self._poll_id = self.after(120, self._poll_queue)
        except tk.TclError:
            pass

    def _poll_queue(self):
        try:
            while True:
                kind, msg = self.msg_queue.get_nowait()
                if kind == "progress":
                    self.status.config(state=tk.NORMAL)
                    last = self.status.get("end-2l", "end-1l")
                    if last.startswith(("Trim:", "Verify:")):
                        self.status.delete("end-2l", "end-1l")
                    self.status.insert(tk.END, msg + "\n")
                    self.status.see(tk.END)
                    self.status.config(state=tk.DISABLED)
                elif kind == "done":
                    self.exec_btn.config(text="Execute Trim")
                    self.worker = None
                elif kind == "spinfo":
                    path, text = msg
                    if path == self.source_var.get().strip():
                        self.sp_extent_label.config(text=text)
                else:
                    self._append_status(msg)
        except Queue.Empty:
            pass
        except tk.TclError:
            return
        self._start_poll()

    # ---- config handling
    def _config_dict(self):
        geo = ""
        try:
            top = self.winfo_toplevel()
            if isinstance(top, tk.Tk):
                geo = top.geometry()
        except tk.TclError:
            pass
        return {"config_name": self.config_name_var.get(),
                "source_p1": self.source_var.get(),
                "sp_range": self.range_var.get(),
                "output_name": self.output_name_var.get(),
                "output_dir": self.output_dir_var.get(),
                "window_geometry": geo}

    def _apply_config(self, data):
        self.config_name_var.set(data.get("config_name", "Default"))
        self.source_var.set(data.get("source_p1", ""))
        self.range_var.set(data.get("sp_range", ""))
        self.output_name_var.set(data.get("output_name", ""))
        self.output_dir_var.set(data.get("output_dir", ""))
        if data.get("output_name"):
            self._out_name_edited[0] = True
        if data.get("output_dir"):
            self._out_dir_chosen[0] = True
        self._show_out_dir()
        geo = data.get("window_geometry", "")
        if geo:
            try:
                top = self.winfo_toplevel()
                if isinstance(top, tk.Tk) and re.match(r"^\d+x\d+", geo):
                    top.geometry(geo)
            except tk.TclError:
                pass

    def save_config(self):
        path = self.config_path_var.get()
        if not path:
            path = os.path.join(DEFAULT_CONFIG_DIR,
                                self.config_name_var.get().strip() or "Default")
        d = os.path.dirname(path)
        name = self.config_name_var.get().strip() or "Default"
        path = os.path.join(d, name if name.endswith(".json") else name + ".json")
        try:
            if not os.path.isdir(d):
                os.makedirs(d)
            with open(path, "w") as f:
                json.dump(self._config_dict(), f, indent=2)
            self.config_path_var.set(path)
            self._remember_last_config(path)
            self.log("Config saved: %s" % path)
        except (IOError, OSError) as e:
            tkMessageBox.showerror("Save Config", "Could not save config:\n%s" % e,
                                   parent=self)

    def browse_config(self):
        cur = self.config_path_var.get()
        initdir = os.path.dirname(cur) if cur else DEFAULT_CONFIG_DIR
        if not os.path.isdir(initdir):
            initdir = os.path.expanduser("~")
        path = tkFileDialog.asksaveasfilename(
            parent=self, title="Select Config (existing loads it; new name sets save target)",
            initialdir=initdir, initialfile=os.path.basename(cur) or "Default.json",
            filetypes=[("xP1-Trim Config", "*.json"), ("All Files", "*.*")],
            defaultextension=".json", confirmoverwrite=False)
        if not path:
            return
        self.config_path_var.set(path)
        name = os.path.basename(path)
        if name.endswith(".json"):
            name = name[:-5]
        self.config_name_var.set(name)
        if os.path.isfile(path):
            self.load_config(path)
        else:
            self.log("Config will be saved to: %s" % path)

    def load_config(self, path):
        try:
            with open(path) as f:
                self._apply_config(json.load(f))
            self._remember_last_config(path)
            self.log("Config loaded: %s" % path)
        except (IOError, OSError, ValueError) as e:
            tkMessageBox.showerror("Load Config", "Could not load config:\n%s" % e,
                                   parent=self)

    def _remember_last_config(self, path):
        try:
            if not os.path.isdir(DEFAULT_CONFIG_DIR):
                os.makedirs(DEFAULT_CONFIG_DIR)
            with open(LAST_CONFIG_MARKER, "w") as f:
                f.write(path)
        except (IOError, OSError):
            pass

    def _load_last_config(self):
        try:
            if os.path.isfile(LAST_CONFIG_MARKER):
                with open(LAST_CONFIG_MARKER) as f:
                    path = f.read().strip()
                if path and os.path.isfile(path):
                    self.config_path_var.set(path)
                    self.load_config(path)
        except (IOError, OSError):
            pass

    # ---- browse handlers
    def browse_source(self):
        cur = self.source_var.get()
        initdir = os.path.dirname(cur) if cur else os.path.expanduser("~")
        path = tkFileDialog.askopenfilename(
            parent=self, title="Select Source P1/11 File", initialdir=initdir,
            filetypes=[("P1 Files", "*.p111 *.111 *.p190 *.190"),
                       ("P1/11 Files", "*.p111 *.111"), ("P1/90 Files", "*.p190 *.190"),
                       ("All Files", "*.*")])
        if path:
            self.source_var.set(path)

    def browse_output_dir(self):
        cur = self.output_dir_var.get() or os.path.dirname(self.source_var.get())
        path = tkFileDialog.askdirectory(parent=self, title="Select Output Directory",
                                         initialdir=cur or os.path.expanduser("~"))
        if path:
            self.output_dir_var.set(path)
            self._out_dir_chosen[0] = True
            self._show_out_dir()
            self.log("Output directory: %s" % path)

    def _show_out_dir(self):
        d = self.output_dir_var.get().strip()
        self.out_dir_label.config(text=("Output directory: %s" % d) if d else "")

    def _on_source_change(self, *args):
        path = self.source_var.get().strip()
        if not self._out_dir_chosen[0] and os.path.isfile(path):
            self.output_dir_var.set(os.path.dirname(path))
            self._show_out_dir()
        self._auto_output_name()
        if not path or not os.path.isfile(path):
            self._last_scanned[0] = None
            self.sp_extent_label.config(text="")
            return
        if path == self._last_scanned[0]:
            return
        self._last_scanned[0] = path
        self.sp_extent_label.config(text="Scanning source shotpoints...")
        t = threading.Thread(target=self._scan_sp_extent_worker, args=(path,))
        t.daemon = True
        t.start()

    def _scan_sp_extent_worker(self, path):
        # No Tkinter access here: worker thread. Staleness is checked in
        # _poll_queue on the main thread using the path carried in the message.
        try:
            fmt = "P1/90" if detect_format(path) == "p190" else "P1/11"
            first, last = scan_sp_extent(path)
        except (IOError, OSError) as e:
            self.msg_queue.put(("spinfo", (path, "Could not scan source: %s" % e)))
            return
        if first is None:
            self.msg_queue.put(("spinfo", (path, "No shotpoint records found in source")))
        elif first == last:
            self.msg_queue.put(("spinfo", (path, "%s source shotpoints: %d (single)" % (fmt, first))))
        else:
            direction = "descending" if first > last else "ascending"
            self.msg_queue.put(("spinfo",
                                (path, "%s source shotpoints: %d -> %d (%s)"
                                 % (fmt, first, last, direction))))

    def _auto_output_name(self, *args):
        if self._out_name_edited[0]:
            return
        src = self.source_var.get().strip()
        if src:
            self.output_name_var.set(
                default_output_name(src, self.range_var.get().strip()))

    # ---- execute / cancel
    def on_execute(self):
        if self.worker is not None and self.worker.is_alive():
            self.cancelled.set()
            self.log("Cancelling...")
            return
        src = self.source_var.get().strip()
        rng_text = self.range_var.get().strip()
        out_name = self.output_name_var.get().strip()
        out_dir = self.output_dir_var.get().strip() or os.path.dirname(src)
        if not src or not os.path.isfile(src):
            tkMessageBox.showerror(APP_TITLE, "Select a valid Source P1 file.", parent=self)
            return
        try:
            spset = set(parse_sp_ranges(rng_text))
        except ValueError as e:
            tkMessageBox.showerror(APP_TITLE, str(e), parent=self)
            return
        if not out_name:
            out_name = default_output_name(src, rng_text)
            self.output_name_var.set(out_name)
        dst = os.path.join(out_dir, out_name)
        if os.path.abspath(dst) == os.path.abspath(src):
            tkMessageBox.showerror(APP_TITLE, "Output would overwrite the source.", parent=self)
            return
        if os.path.exists(dst):
            if not tkMessageBox.askyesno(APP_TITLE, "Output exists:\n%s\nOverwrite?" % dst,
                                         parent=self):
                return
        self.cancelled.clear()
        self.exec_btn.config(text="Cancel")
        self.worker = threading.Thread(target=self._run_job,
                                       args=(src, dst, spset, rng_text))
        self.worker.daemon = True
        self.worker.start()

    def _run_job(self, src, dst, spset, rng_text):
        t0 = time.time()
        try:
            self.log("=" * 66)
            self.log("TRIM   source : %s (%s bytes)" % (src, "{:,}".format(os.path.getsize(src))))
            self.log("       output : %s" % dst)
            self.log("       shotpoints selected: %d  (%s)" % (len(spset), rng_text))
            stats = trim_p111(src, dst, spset, self.log, self._progress, self.cancelled)
            if stats is None:
                return
            self.log("       format : %s" % stats["format"])
            if stats["unknown_types"]:
                self.log("WARNING: unrecognised record types %s - kept/attributed "
                         "conservatively, check the census" % ", ".join(stats["unknown_types"]))
            kept_types = ", ".join("%s=%d" % (k, v)
                                   for k, v in sorted(stats["kept_by_type"].items()))
            census = ", ".join("%s=%d" % (k, v)
                               for k, v in sorted(stats["type_census"].items()))
            self.log("Record census (source): %s" % census)
            self.log("Headers/metadata kept : %d lines" % stats["kept_headers"])
            self.log("Shot records kept     : %d  (%s)" % (stats["kept_records"], kept_types))
            self.log("Shot records skipped  : %d" % stats["skipped_records"])
            if stats["bad_spn"]:
                self.log("WARNING: %d per-shot lines had unreadable shotpoint (excluded)"
                         % stats["bad_spn"])
            missing = sorted(spset - stats["sps_found"])
            if missing:
                self.log("WARNING: %d requested shotpoints not in source: %s"
                         % (len(missing), _summarize_sps(missing)))
            self.log("Shotpoints written    : %d of %d requested"
                     % (len(stats["sps_kept"]), len(spset)))
            self.log("Output size           : %s bytes"
                     % "{:,}".format(os.path.getsize(dst)))
            self.log("-" * 66)
            self.log("VERIFY output vs source (byte-for-byte, in order)")
            v = verify_trim(src, dst, spset, self.log, self._progress, self.cancelled)
            if v is None:
                return
            sps_ok = len(stats["sps_kept"]) if v["mismatch"] == 0 else 0
            self.log("Headers checked       : %d, matching: %d"
                     % (v["headers_checked"],
                        v["headers_checked"] if v["mismatch"] == 0 else -1))
            self.log("Shot records checked  : %d, matching: %d"
                     % (v["records_checked"], v["match"] - v["headers_checked"]))
            self.log("Total lines checked   : %d, matching: %d" % (v["match"] + v["mismatch"], v["match"]))
            self.log("Shotpoints OK         : %d / %d" % (sps_ok, len(stats["sps_kept"])))
            if v["mismatch"] or v["extra_in_output"]:
                self.log("RESULT: FAIL  (%d mismatches, %d extra lines in output)"
                         % (v["mismatch"], v["extra_in_output"]))
            else:
                self.log("RESULT: PASS - every output line matches the source, "
                         "nothing missing, nothing extra.")
            self.log("Elapsed: %.1f s" % (time.time() - t0))
        except Exception as e:
            self.log("ERROR: %s" % e)
        finally:
            self.msg_queue.put(("done", None))


def _summarize_sps(sps, limit=12):
    """Compact 'a-b, c' summary of a sorted int list."""
    if not sps:
        return ""
    parts, start, prev = [], sps[0], sps[0]
    for n in sps[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append("%d-%d" % (start, prev) if start != prev else "%d" % start)
        start = prev = n
    parts.append("%d-%d" % (start, prev) if start != prev else "%d" % start)
    if len(parts) > limit:
        parts = parts[:limit] + ["..."]
    return ", ".join(parts)


def xnavsl_embed(master):
    """Host inside xNAVSL (or any parent Frame); does not create a new Tk."""
    panel = XP1TrimPanel(master)
    panel.pack(fill=tk.BOTH, expand=True)
    return panel


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.configure(bg=COLOR_BG)
    root.geometry("%dx%d" % (DEFAULT_WIDTH, DEFAULT_HEIGHT))
    root.minsize(640, 420)
    panel = XP1TrimPanel(root)
    panel.pack(fill=tk.BOTH, expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
