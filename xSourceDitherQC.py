#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Ai assisted code by RBolisay
# xSourceDitherQC.py — Source/Dither Check GUI (Python 2.7 / RHEL 8). Window title: xSourceDitherQC - Source/Dither Check.
# Baseline: xDitherQC-NearF.py
# MODIFIED based on user request:
# - Added remembering last config path/name.
# - Added hide/show for parameters section on Start/Stop.
# MODIFIED to apply "Blue Aura" color theme.

# --- Applied User-Requested Modifications (based on latest request for segment/config) ---
# 1. Config file extension changed to .xcfg.
# 2. Last used config is remembered and loaded on startup (improved).
# 3. "Browse..." for config file now attempts to load the selected file immediately.
# 4. "Save" button saves current UI state accurately (improved).
# 5. Source segment data (paths, FS) is retained when number of sources is changed via "Set Sources" button.
# 6. "Number of Sources" entry requires "Set Sources" button to apply changes (trace removed).
# --- Source / dither UI (current) ---
# - Parameters: Shotpoint Check; Line name + Production Shotpoints; Anchored Shot; Line Direction (read-only, lineque); Source to Fire at Anchor; Refresh.
# - Shot log: tail -20 shotcontroller.log (or direct file read if tail fails). Line format: [date time] - [shotpoint] - [LEVEL] - message (shotpoint may be negative, e.g. 2364 or -10255). Parse NEW SHOT : SP then Source to fire ... src N; else Aimpoint dither lines (for shot supports signed SP).
# - Gun Firing Sequence source: Manual (up/down comma lists + anchor SP) or Preplot (P1/11).
#   Manual default 1,2,3 / 3,2,1 from SP 1001 reproduces the original hardcoded 3-source rule.
#   Preplot reads Source_Shooting_Sequence_Offset (cycles), Reference_Shot_Number (anchor),
#   Source_Shooting_Sequence_Length (wrap) and Source_Shooting_Constraints_Definition
#   jitteringAtIndex (dither), so source count and cycles follow the job rather than the code.
#   Index: upline (SP - ref) mod L, downline (ref - SP) mod L.
# - One "Dither File to Use" per source, used unless the preplot supplies the dither.
# - [General] dither_pattern_reference: Anchored SP | Production FSP | Adaptive. Row index: anchor or Prod FSP; Adaptive aligns file phase from last 3 shots' Trinav dither vs pattern. Upline: offset = SP-ref; downline: ref-SP; pattern[idx % L] with wrap.

import Tkinter as tk
import tkFont # Import tkFont for font handling
import tkFileDialog
import ScrolledText
import tkMessageBox
import subprocess
import ConfigParser
import os
import re
from collections import OrderedDict
import sys
import threading
import traceback
import signal

# --- Check Python Version ---
if sys.version_info[0] != 2 or sys.version_info[1] != 7:
     try: root_check = tk.Tk(); root_check.withdraw(); tkMessageBox.showerror("Version Error", "This script requires Python 2.7."); root_check.destroy()
     except tk.TclError: print "Error: This script requires Python 2.7."
     sys.exit(1)

SOURCE_CYCLE_ANCHOR_SP = 1001
SOURCE_CYCLE_COUNT = 3

# --- Gun firing sequence source ---
# Manual: cycles typed below (defaults reproduce the long-standing rule).
# Preplot: cycles, anchor, wrap length and dither all read from a P1/11 preplot.
SEQ_SOURCE_MANUAL = "Manual (sequence below)"
SEQ_SOURCE_PREPLOT = "Preplot (P1/11)"
SEQ_SOURCE_CHOICES = (SEQ_SOURCE_MANUAL, SEQ_SOURCE_PREPLOT)
DEFAULT_UP_SEQUENCE = "1,2,3"
DEFAULT_DOWN_SEQUENCE = "3,2,1"

PATTERN_REF_ANCHORED_SP = "Anchored SP"
PATTERN_REF_PRODUCTION_FSP = "Production FSP"
PATTERN_REF_ADAPTIVE = "Adaptive"
PATTERN_REF_CHOICES = (PATTERN_REF_ANCHORED_SP, PATTERN_REF_PRODUCTION_FSP, PATTERN_REF_ADAPTIVE)
# Not offered in the menu: selected implicitly whenever the gun sequence source is the preplot.
PATTERN_REF_PREPLOT = "Preplot"


# Long-run guards. The tool is left running for days: bound the log widget, never let one
# hung system command freeze the GUI, and never let one exception end the timer loop.
LOG_MAX_LINES = 4000          # trim the check log back to LOG_KEEP_LINES once it passes this
LOG_KEEP_LINES = 3000
COMMAND_TIMEOUT_S = 20        # ex_lineque / tail: kill and retry next cycle if slower than this

# Adaptive: after this many consecutive dither MISMATCHes while locked, clear alignment and re-search the file/log.
ADAPTIVE_MISMATCH_STREAK_TO_RESET = 3

def parse_preplot(filepath):
    """Read the shooting sequence and dither (jitter) out of a P1/11 design preplot.

    Returns (data, status). data is None on failure and status says why.

    data keys:
      ref_shot       survey-wide Reference_Shot_Number anchoring every sequence
      seq_len        sequence wrap length in shotpoints
      patterns       {pattern_id: {'seq': [source per index], 'dither': [secs per index] or None}}
      line_patterns  {line_name: (incremental_id, decremental_id)} from the N1 line records
      line_ranges    {line_name: (first_sp, last_sp)}
      default_pair   (incremental_id, decremental_id) used when a line is not listed
      inc_seq/dec_seq/dither/pat_inc/pat_dec  convenience views of default_pair
      sources        sorted source numbers used by default_pair
      num_srcs       len(sources) - 2, 3, ... never assumed

    Index convention (verified against acquired P1/11 postplot data, 173/173 shots):
      upline   idx = (SP - ref_shot) mod seq_len
      downline idx = (ref_shot - SP) mod seq_len
    """
    if not filepath or not os.path.exists(filepath):
        return None, "Preplot not found: {}".format(filepath)

    seq = {}            # pid -> {idx: source}
    jit = {}            # pid -> {idx: seconds}
    refs = {}           # pid -> reference shot
    line_patterns = {}  # line name -> (inc, dec)
    line_ranges = {}    # line name -> (fsp, lsp)
    pair_order = []     # distinct pairs in file order
    inc_first = True
    last_line_name = None
    pair_re = re.compile(r'^\s*(\d+)\s*;\s*(\d+)\s*$')
    try:
        fh = open(filepath, 'r')
    except IOError as e:
        return None, "Cannot open preplot: {}".format(e)
    try:
        for line in fh:
            if line.startswith('H1,4,0,0'):
                low = line.lower()
                i_inc = low.find('incremental')
                i_dec = low.find('decremental')
                if i_inc >= 0 and i_dec >= 0:
                    inc_first = i_inc < i_dec
                continue
            if line.startswith('N1,0,'):
                p = line.rstrip('\r\n').split(',')
                if len(p) >= 7:
                    last_line_name = p[4].strip()
                    try:
                        line_ranges[last_line_name] = (int(p[5]), int(p[6]))
                    except ValueError:
                        pass
                continue
            if line.startswith('N1,2,'):
                p = line.rstrip('\r\n').split(',')
                pair = None
                for fld in reversed(p):
                    m = pair_re.match(fld)
                    if m:
                        a, b = int(m.group(1)), int(m.group(2))
                        pair = (a, b) if inc_first else (b, a)
                        break
                if pair is not None:
                    if pair not in pair_order:
                        pair_order.append(pair)
                    if last_line_name:
                        line_patterns[last_line_name] = pair
                continue
            if not line.startswith('HC,2,3,1,'):
                continue
            p = line.rstrip('\r\n').split(',')
            if len(p) < 8:
                continue
            label = p[4].strip()
            try:
                pid = int(p[5])
            except ValueError:
                continue
            val = p[7]
            if label == 'Source_Shooting_Sequence_Offset':
                f = val.split('|')
                if len(f) >= 2:
                    try:
                        seq.setdefault(pid, {})[int(f[0])] = int(f[1])
                    except ValueError:
                        pass
            elif label == 'Source_Shooting_Constraints_Definition':
                f = val.split('|')
                if len(f) >= 4 and f[1].strip().lower() == 'jitteringatindex':
                    try:
                        jit.setdefault(pid, {})[int(f[3])] = float(f[2])
                    except ValueError:
                        pass
            elif label == 'Reference_Shot_Number':
                try:
                    refs[pid] = int(val)
                except ValueError:
                    pass
    except IOError as e:
        return None, "Error reading preplot: {}".format(e)
    finally:
        try:
            fh.close()
        except IOError:
            pass

    if not seq:
        return None, "No Source_Shooting_Sequence_Offset records found (not a design preplot?)"

    def _to_list(store, pid):
        idxs = store.get(pid, {})
        if not idxs:
            return None
        count = max(idxs) + 1
        if len(idxs) != count or min(idxs) != 0:
            return None
        return [idxs[i] for i in range(count)]

    patterns = {}
    for pid in sorted(seq.keys()):
        sq = _to_list(seq, pid)
        if sq is None:
            return None, "Shooting pattern {}: sequence indices not contiguous from 0".format(pid)
        dt = _to_list(jit, pid) if pid in jit else None
        if pid in jit and dt is None:
            return None, "Shooting pattern {}: dither indices not contiguous from 0".format(pid)
        patterns[pid] = {'seq': sq, 'dither': dt}

    if pair_order:
        default_pair = pair_order[0]
    else:
        ids = sorted(patterns.keys())
        if len(ids) < 2:
            return None, "Only one shooting pattern in preplot; cannot tell upline from downline"
        default_pair = (ids[0], ids[1])

    used = set([default_pair[0], default_pair[1]])
    for pr in line_patterns.values():
        used.update(pr)
    for pid in sorted(used):
        if pid not in patterns:
            return None, "Line records reference shooting pattern {} which has no sequence".format(pid)

    lens = set(len(patterns[pid]['seq']) for pid in used)
    if len(lens) != 1:
        return None, "Shooting patterns differ in sequence length: {}".format(sorted(lens))
    seq_len = lens.pop()

    ref_vals = set(refs[pid] for pid in used if pid in refs)
    if not ref_vals:
        return None, "No Reference_Shot_Number in preplot"
    if len(ref_vals) != 1:
        return None, "Shooting patterns carry different Reference_Shot_Number: {}".format(sorted(ref_vals))
    ref = ref_vals.pop()

    pat_inc, pat_dec = default_pair
    inc_seq = patterns[pat_inc]['seq']
    dec_seq = patterns[pat_dec]['seq']
    dither = patterns[pat_inc]['dither'] or patterns[pat_dec]['dither']
    sources = sorted(set(inc_seq) | set(dec_seq))
    return {
        'path': filepath,
        'ref_shot': ref,
        'seq_len': seq_len,
        'patterns': patterns,
        'line_patterns': line_patterns,
        'line_ranges': line_ranges,
        'default_pair': default_pair,
        'inc_seq': inc_seq,
        'dec_seq': dec_seq,
        'dither': dither,
        'pat_inc': pat_inc,
        'pat_dec': pat_dec,
        'sources': sources,
        'num_srcs': len(sources),
        'multi_pattern': len(pair_order) > 1,
    }, "OK"


def parse_postplot_p111(filepath):
    """Read acquired shots out of a Trinav P1/11 postplot.

    Returns (groups, status). groups is a list, one per (sequence, line) in file order:
      {'sequence', 'line', 'is_upline', 'shots': [(sp, source_number, dither_secs, time_str)]}
    Shots are in time order. The dither column is located from the H1,1,0,0 record type
    definitions ('Aimpoint Dither' attribute) rather than assumed, so a differently
    configured export still parses or is rejected with a reason.
    """
    if not filepath or not os.path.exists(filepath):
        return None, "Postplot not found: {}".format(filepath)
    try:
        fh = open(filepath, 'r')
    except IOError as e:
        return None, "Cannot open postplot: {}".format(e)
    try:
        head = fh.readline()
        if head.startswith('H00') or head.startswith('H0'):
            return None, ("P1/90 postplot detected. P1/90 has no 'Aimpoint Dither' attribute field; "
                          "only P1/11 exports carry the applied dither. Use the P1/11 output of this sequence.")
        if not head.startswith('OGP,') and not head.startswith('OGP '):
            return None, "Not a P1/11 file (no OGP header line)"
        fh.seek(0)
        type_attrs = {}     # record type -> (attr_count, dither_attr_index or None)
        groups = OrderedDict()
        src_digits = re.compile(r'(\d+)\s*$')
        n_s1 = 0
        for line in fh:
            if line.startswith('H1,1,0,0'):
                p = line.rstrip('\r\n').split(',')
                if len(p) < 12:
                    continue
                try:
                    rtype = int(p[5]); count = int(p[11])
                except ValueError:
                    continue
                dith_idx = None
                for i, d in enumerate(p[12:12 + count]):
                    if 'aimpoint dither' in d.lower():
                        dith_idx = i
                type_attrs[rtype] = (count, dith_idx)
                continue
            if not line.startswith('S1,'):
                continue
            n_s1 += 1
            p = line.rstrip('\r\n').split(',')
            if len(p) < 12:
                continue
            seq_id, line_name = p[2].strip(), p[3].strip()
            try:
                sp = int(p[4]); rtype = int(p[10])
            except ValueError:
                continue
            m = src_digits.search(p[9].strip())
            if not m:
                return None, "Cannot read source number from object name '{}' at SP {}".format(p[9], sp)
            src = int(m.group(1))
            count, dith_idx = type_attrs.get(rtype, (0, None))
            dither = None
            if dith_idx is not None and count > 0 and len(p) >= count:
                try:
                    dither = float(p[len(p) - count + dith_idx])
                except ValueError:
                    dither = None
            key = (seq_id, line_name)
            if key not in groups:
                groups[key] = {'sequence': seq_id, 'line': line_name, 'shots': []}
            groups[key]['shots'].append((sp, src, dither, p[7].strip()))
    except IOError as e:
        return None, "Error reading postplot: {}".format(e)
    finally:
        try:
            fh.close()
        except IOError:
            pass
    if n_s1 == 0:
        return None, "No S1 shot records in file (is this a design preplot rather than a postplot?)"
    out = []
    for g in groups.values():
        shots = g['shots']
        if len(shots) >= 2:
            g['is_upline'] = shots[-1][0] > shots[0][0]
        else:
            g['is_upline'] = None
        out.append(g)
    return out, "OK"


# --- Main Application Class ---
class xSourceDitherQCApp:
    def __init__(self, root):
        self.root = root
        self.root.title("xSourceDitherQC - Source/Dither Check")

        # --- Color Palette ---
        self.color_blue_aura_bg = "#B4C8E1"
        self.color_text_dark = "#000000"
        self.color_text_light = "#FFFFFF"
        self.color_button_bg = "#8DA9CC"
        self.color_button_active_bg = "#8cabc2"
        self.color_entry_bg = "#FFFFFF"
        self.color_log_bg = "#FFFFFF"
        self.color_label_frame_fg = self.color_text_dark
        self.color_disabled_fg = "#555555"
        self.color_disabled_bg = "#c0c0c0"


        # --- Defaults ---
        self.default_config_dir = '/usr/local/trinop/qcfiles/Misc/xSourceDitherQC/'
        self.default_config_name = 'xSourceDitherQC.xcfg'
        self.config_full_path = os.path.join(self.default_config_dir, self.default_config_name)
        self._ensure_default_config_dir()
        self.log_file_path = '/usr/local/trinop/naverror/shotcontroller.log'
        self.lineque_cmd = 'ex_lineque -print'
        self.log_tail_cmd = 'tail -20 {}'.format(self.log_file_path)
        self.float_tolerance = 0.001; self.default_retry_interval_ms = 5000; self.loop_buffer_ms = 500; self.default_dither_dir = '/usr/local/trinop/dbase/links/qcfiles/Dither'
        self.default_preplot_dir = '/usr/local/trinop/qcfiles'

        # --- State ---
        self.config_name_var = tk.StringVar(value=self.default_config_name)
        self.num_sources = tk.IntVar(value=SOURCE_CYCLE_COUNT)
        self.shot_increment_var = tk.IntVar(value=1)
        self.source_configs = OrderedDict()
        self.dither_patterns = {}
        self.running = False
        self.timer_id = None
        self.current_line_info = {}
        self._refresh_line_info_cache = None
        self.display_anchored_shot_var = tk.StringVar(value="—")
        self.display_line_direction_var = tk.StringVar(value="—")
        self.display_source_at_anchor_var = tk.StringVar(value="—")
        self.shotpoint_check_var = tk.StringVar(value="")
        self.shotpoint_check_source_var = tk.StringVar(value="—")
        self.display_line_name_var = tk.StringVar(value="—")
        self.display_prod_shotpoints_var = tk.StringVar(value="—")
        self.dither_pattern_reference_var = tk.StringVar(value=PATTERN_REF_ANCHORED_SP)
        self.gun_sequence_only_var = tk.IntVar(value=0)
        self.seq_source_var = tk.StringVar(value=SEQ_SOURCE_MANUAL)
        self.preplot_path_var = tk.StringVar(value="")
        self.up_sequence_var = tk.StringVar(value=DEFAULT_UP_SEQUENCE)
        self.down_sequence_var = tk.StringVar(value=DEFAULT_DOWN_SEQUENCE)
        self.seq_anchor_var = tk.StringVar(value=str(SOURCE_CYCLE_ANCHOR_SP))
        self.postplot_path_var = tk.StringVar(value="")
        self._postplot_frame = None
        self._preplot = None
        self._preplot_crosscheck_key = None
        self._preplot_status_label = None
        self._preplot_widgets = []
        self._manual_seq_widgets = []
        self._pat_row = None
        self._gun_row = None
        self._seq_src_row = None
        self._preplot_row = None
        self._manual_row = None
        self._sources_sep = None
        self.params_frame = None
        self._adaptive_triple_start_row = {1: None, 2: None, 3: None}
        self._adaptive_sp_base = None
        self._adaptive_calibrated = False
        self._adaptive_line_fingerprint = None
        self._adaptive_dither_mismatch_streak = 0
        self._info_window = None
        self._info_text_widget = None

        self.setup_gui()
        self.load_config() # Initial load on startup
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _ensure_default_config_dir(self):
        """Create the default config directory up front so Save and Browse always have a home."""
        d = self.default_config_dir
        if os.path.isdir(d):
            return True
        try:
            os.makedirs(d)
            print "Created default config directory: {}".format(d)
            return True
        except OSError as e:
            print "Warning: could not create default config directory {}: {}".format(d, e)
            return False

    def setup_gui(self):
        self.root.configure(bg=self.color_blue_aura_bg)

        self.default_font_size = 10
        self.heading_font_size = 10
        self.status_font_size = 28
        self.small_font_size = 8

        self.results_font = tkFont.Font(family='TkDefaultFont', size=self.default_font_size)
        self.heading_font = tkFont.Font(family='TkDefaultFont', size=self.heading_font_size, weight='bold')
        self.status_font = tkFont.Font(family='TkDefaultFont', size=self.status_font_size, weight='bold')
        self.small_font = tkFont.Font(family='TkDefaultFont', size=self.small_font_size)

        top_title_row = tk.Frame(self.root, bg=self.color_blue_aura_bg)
        top_title_row.pack(fill=tk.X, padx=5, pady=(5, 0))
        desc_label = tk.Label(
            top_title_row,
            text="Near Real Time Monitoring and xcheck of Source Firing Sequence and Dither applied by Trinav vs Dither file",
            bg=self.color_blue_aura_bg, fg=self.color_text_dark, anchor='w')
        desc_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(
            top_title_row, text="Info", command=self._show_info_window, width=6,
            bg=self.color_button_bg, fg=self.color_text_dark,
            activebackground=self.color_button_active_bg, activeforeground=self.color_text_dark
        ).pack(side=tk.RIGHT, padx=(8, 0))

        config_outer_frame = tk.Frame(self.root, bg=self.color_blue_aura_bg)
        config_outer_frame.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(config_outer_frame, text="xSourceDitherQC Config Name:",
                 bg=self.color_blue_aura_bg, fg=self.color_text_dark).pack(side=tk.LEFT)
        self.config_name_entry = tk.Entry(config_outer_frame, textvariable=self.config_name_var, width=30,
                                          bg=self.color_entry_bg, fg=self.color_text_dark, insertbackground=self.color_text_dark)
        self.config_name_entry.pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(config_outer_frame, text="Browse...", command=self.select_config_file,
                  bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg).pack(side=tk.LEFT, padx=(0, 5))
        config_btn_frame = tk.Frame(config_outer_frame, bg=self.color_blue_aura_bg)
        config_btn_frame.pack(side=tk.LEFT)
        tk.Button(config_btn_frame, text="Save", command=self.save_config,
                  bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg).pack(side=tk.LEFT)

        # Pack order is Tk's allocation priority when the window is too short. Buttons go
        # first (never squeezed), then the parameters, and the log last (shrinks first).
        btn_frame = tk.Frame(self.root, bg=self.color_blue_aura_bg)
        btn_frame.pack(side=tk.BOTTOM, pady=5)
        self.start_button = tk.Button(btn_frame, text="Start Source/Dither Check", command=self.start_checking, width=26,
                                      bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg)
        self.start_button.pack(side=tk.LEFT, padx=10)
        self.stop_button = tk.Button(btn_frame, text="Stop Source/Dither Check", command=self.stop_checking, state=tk.DISABLED, width=26,
                                     bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg,
                                     disabledforeground=self.color_disabled_fg)
        self.stop_button.pack(side=tk.LEFT, padx=10)
        # Status line lives with the buttons (priority over the parameters), not in the log frame.
        self.status_label_text = tk.StringVar(value="Idle")
        self.status_label = tk.Label(self.root, textvariable=self.status_label_text, font=self.status_font, anchor='w',
                                     bg=self.color_blue_aura_bg)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2); self.status_label.config(fg="gray")

        self.params_frame = tk.LabelFrame(self.root, text="Source and Dither Parameters",
                                          bg=self.color_blue_aura_bg, fg=self.color_label_frame_fg, font=self.heading_font)
        self.params_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        live_frame = tk.Frame(self.params_frame, bg=self.color_blue_aura_bg)
        live_frame.pack(fill=tk.X, padx=8, pady=4)
        def _live_row(parent, title, var_ref, bold=False, readonly=False, label_width=18):
            row = tk.Frame(parent, bg=self.color_blue_aura_bg)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=title, width=label_width, anchor='w', bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                     font=self.heading_font if bold else self.results_font).pack(side=tk.LEFT)
            vbg = self.color_disabled_bg if readonly else self.color_entry_bg
            vfg = self.color_disabled_fg if readonly else self.color_text_dark
            tk.Label(row, textvariable=var_ref, anchor='w', bg=vbg, fg=vfg,
                     relief=tk.GROOVE, padx=6, pady=2).pack(side=tk.LEFT, fill=tk.X, expand=True)
        shot_chk_row = tk.Frame(live_frame, bg=self.color_blue_aura_bg)
        shot_chk_row.pack(fill=tk.X, pady=2)
        tk.Label(shot_chk_row, text="Shotpoint Check", width=18, anchor='w', bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                 font=self.results_font).pack(side=tk.LEFT)
        tk.Entry(shot_chk_row, textvariable=self.shotpoint_check_var, width=14,
                 bg=self.color_entry_bg, fg=self.color_text_dark, insertbackground=self.color_text_dark).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(shot_chk_row, text="Source to Fire", anchor='w', bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                 font=self.results_font).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(shot_chk_row, textvariable=self.shotpoint_check_source_var, anchor='w',
                 bg=self.color_disabled_bg, fg=self.color_disabled_fg,
                 relief=tk.GROOVE, padx=6, pady=2).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.shotpoint_check_var.trace('w', lambda *args: self._update_shotpoint_check_source())
        _live_row(live_frame, "Line name", self.display_line_name_var, readonly=True)
        _live_row(live_frame, "Production Shotpoints", self.display_prod_shotpoints_var, readonly=True, label_width=22)
        _live_row(live_frame, "Anchored Shot", self.display_anchored_shot_var, readonly=True)
        _live_row(live_frame, "Line Direction", self.display_line_direction_var, readonly=True)
        _live_row(live_frame, "Source to Fire at Anchor", self.display_source_at_anchor_var, readonly=True, label_width=22)
        tk.Button(live_frame, text="Refresh from Line Queue and Log", command=self.refresh_params_from_system,
                  bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg).pack(anchor='w', pady=(6, 2))

        align_frame = tk.Frame(self.params_frame, bg=self.color_blue_aura_bg)
        align_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        pat_row = tk.Frame(align_frame, bg=self.color_blue_aura_bg)
        pat_row.pack(fill=tk.X, pady=(2, 6))
        self._pat_row = pat_row
        tk.Label(pat_row, text="Dither Pattern Reference", bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                 font=self.results_font, anchor='w').pack(side=tk.LEFT)
        self._dither_pattern_ref_menu = tk.OptionMenu(
            pat_row, self.dither_pattern_reference_var, *PATTERN_REF_CHOICES)
        self._dither_pattern_ref_menu.config(
            bg=self.color_button_bg, fg=self.color_text_dark,
            activebackground=self.color_button_active_bg, activeforeground=self.color_text_dark,
            highlightthickness=0, bd=1, relief=tk.RAISED)
        _dm = self._dither_pattern_ref_menu
        _dm['menu'].config(
            bg=self.color_button_bg, fg=self.color_text_dark,
            activebackground=self.color_button_active_bg, activeforeground=self.color_text_dark,
            bd=1, relief=tk.FLAT)
        self._dither_pattern_ref_menu.pack(side=tk.LEFT, padx=(10, 0))
        self.dither_pattern_reference_var.trace('w', lambda *args: self._on_dither_pattern_reference_changed())

        gun_row = tk.Frame(align_frame, bg=self.color_blue_aura_bg)
        gun_row.pack(fill=tk.X, pady=(0, 2))
        self._gun_row = gun_row
        tk.Label(gun_row, text="Source Sequence Check Only(Disable Dither QC)", bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                 font=self.results_font, anchor='w').pack(side=tk.LEFT)
        tk.Checkbutton(
            gun_row, text="",
            variable=self.gun_sequence_only_var,
            bg=self.color_blue_aura_bg, fg=self.color_text_dark, activebackground=self.color_blue_aura_bg,
            selectcolor=self.color_entry_bg, anchor='w',
            font=self.results_font).pack(side=tk.LEFT, padx=(10, 0))

        seq_frame = tk.LabelFrame(self.params_frame, text="Gun Firing Sequence",
                                  bg=self.color_blue_aura_bg, fg=self.color_label_frame_fg, font=self.results_font)
        seq_frame.pack(fill=tk.X, padx=8, pady=(0, 6))

        seq_src_row = tk.Frame(seq_frame, bg=self.color_blue_aura_bg)
        seq_src_row.pack(fill=tk.X, padx=5, pady=(3, 2))
        self._seq_src_row = seq_src_row
        tk.Label(seq_src_row, text="Sequence Source:", width=18, anchor='w',
                 bg=self.color_blue_aura_bg, fg=self.color_text_dark, font=self.results_font).pack(side=tk.LEFT)
        self._seq_source_menu = tk.OptionMenu(seq_src_row, self.seq_source_var, *SEQ_SOURCE_CHOICES)
        self._seq_source_menu.config(
            bg=self.color_button_bg, fg=self.color_text_dark,
            activebackground=self.color_button_active_bg, activeforeground=self.color_text_dark,
            highlightthickness=0, bd=1, relief=tk.RAISED)
        self._seq_source_menu['menu'].config(
            bg=self.color_button_bg, fg=self.color_text_dark,
            activebackground=self.color_button_active_bg, activeforeground=self.color_text_dark,
            bd=1, relief=tk.FLAT)
        self._seq_source_menu.pack(side=tk.LEFT, padx=(10, 0))
        self.seq_source_var.trace('w', lambda *args: self._on_seq_source_changed())
        self.up_sequence_var.trace('w', lambda *args: self._rebuild_source_rows_if_changed())
        self.down_sequence_var.trace('w', lambda *args: self._rebuild_source_rows_if_changed())

        preplot_row = tk.Frame(seq_frame, bg=self.color_blue_aura_bg)
        preplot_row.pack(fill=tk.X, padx=5, pady=2)
        self._preplot_row = preplot_row
        tk.Label(preplot_row, text="Preplot File:", width=18, anchor='w',
                 bg=self.color_blue_aura_bg, fg=self.color_text_dark).pack(side=tk.LEFT)
        self._preplot_entry = tk.Entry(preplot_row, textvariable=self.preplot_path_var,
                                       bg=self.color_entry_bg, fg=self.color_text_dark,
                                       insertbackground=self.color_text_dark,
                                       disabledbackground=self.color_disabled_bg,
                                       disabledforeground=self.color_disabled_fg)
        self._preplot_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        self._preplot_entry.bind('<Return>', lambda e: self._ensure_preplot_current())
        self._preplot_entry.bind('<FocusOut>', lambda e: self._ensure_preplot_current())
        self._preplot_browse_btn = tk.Button(preplot_row, text="Browse...", command=self.browse_preplot_file,
                                             bg=self.color_button_bg, fg=self.color_text_dark,
                                             activebackground=self.color_button_active_bg,
                                             disabledforeground=self.color_disabled_fg)
        self._preplot_browse_btn.pack(side=tk.LEFT)
        self._preplot_status_label = tk.Label(preplot_row, text="Not Loaded", fg="gray", width=10,
                                              font=self.small_font, bg=self.color_blue_aura_bg)
        self._preplot_status_label.pack(side=tk.LEFT, padx=5)
        self._preplot_widgets = [self._preplot_entry, self._preplot_browse_btn]

        manual_row = tk.Frame(seq_frame, bg=self.color_blue_aura_bg)
        manual_row.pack(fill=tk.X, padx=5, pady=(2, 5))
        self._manual_row = manual_row
        tk.Label(manual_row, text="Manual Sequence:", width=18, anchor='w',
                 bg=self.color_blue_aura_bg, fg=self.color_text_dark).pack(side=tk.LEFT)
        self._manual_seq_widgets = []
        for _cap, _var, _w in (("Up", self.up_sequence_var, 12),
                               ("Down", self.down_sequence_var, 12),
                               ("Anchor SP", self.seq_anchor_var, 9)):
            tk.Label(manual_row, text=_cap, bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                     font=self.small_font).pack(side=tk.LEFT, padx=(6, 2))
            _e = tk.Entry(manual_row, textvariable=_var, width=_w,
                          bg=self.color_entry_bg, fg=self.color_text_dark,
                          insertbackground=self.color_text_dark,
                          disabledbackground=self.color_disabled_bg,
                          disabledforeground=self.color_disabled_fg)
            _e.pack(side=tk.LEFT)
            self._manual_seq_widgets.append(_e)
        tk.Label(manual_row, text="(comma list, e.g. 1,2 for two sources)",
                 bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                 font=self.small_font).pack(side=tk.LEFT, padx=(8, 0))

        self._sources_sep = tk.Frame(self.params_frame, height=2, bd=1, relief=tk.SUNKEN, bg=self.color_blue_aura_bg)
        self._sources_sep.pack(fill=tk.X, pady=5)
        self.sources_area = tk.Frame(self.params_frame, bg=self.color_blue_aura_bg)
        self.sources_area.pack(fill=tk.X, pady=(5, 0))

        self._build_ui_elements()

        self._postplot_frame = tk.LabelFrame(
            self.params_frame, text="Postplot Dither QC (offline - live check must be stopped)",
            bg=self.color_blue_aura_bg, fg=self.color_label_frame_fg, font=self.results_font)
        self._postplot_frame.pack(fill=tk.X, padx=8, pady=(8, 4))
        pq_row = tk.Frame(self._postplot_frame, bg=self.color_blue_aura_bg)
        pq_row.pack(fill=tk.X, padx=5, pady=(3, 5))
        tk.Label(pq_row, text="P1/11 Postplot:", width=18, anchor='w',
                 bg=self.color_blue_aura_bg, fg=self.color_text_dark).pack(side=tk.LEFT)
        tk.Entry(pq_row, textvariable=self.postplot_path_var,
                 bg=self.color_entry_bg, fg=self.color_text_dark,
                 insertbackground=self.color_text_dark).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        tk.Button(pq_row, text="Browse...", command=self.browse_postplot_file,
                  bg=self.color_button_bg, fg=self.color_text_dark,
                  activebackground=self.color_button_active_bg).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(pq_row, text="QC Dither", command=self.run_postplot_qc, width=12,
                  bg=self.color_button_bg, fg=self.color_text_dark,
                  activebackground=self.color_button_active_bg,
                  font=self.heading_font).pack(side=tk.LEFT)

        rt_frame = tk.LabelFrame(self.root, text="Near Real Time Source Sequence and Dither Check",
                                 bg=self.color_blue_aura_bg, fg=self.color_label_frame_fg, font=self.heading_font)
        rt_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._rt_frame = rt_frame

        self.log_text = ScrolledText.ScrolledText(rt_frame, wrap=tk.WORD, height=15, state=tk.DISABLED,
                                                  font=self.results_font, bg=self.color_log_bg, fg=self.color_text_dark,
                                                  insertbackground=self.color_text_dark)
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0,5))
        self.log_text.tag_configure("ok", foreground="green")
        self.log_text.tag_configure("error", foreground="red")
        self.log_text.tag_configure("warning", foreground="orange")
        self.log_text.tag_configure("info", foreground="blue")
        self.log_text.tag_configure("debug", foreground="gray")
        self.log_text.tag_configure("heading", font=self.heading_font)
        self.log_text.tag_configure("separator", foreground="gray")

    def _info_help_text(self):
        a = SOURCE_CYCLE_ANCHOR_SP
        return (
            "SOURCE FIRING SEQUENCE CHECK\n"
            "===========================\n"
            "The app reads the latest shot from shotcontroller.log (NEW SHOT / Source to fire) and compares it to the\n"
            "expected source for that shotpoint.\n\n"
            "Line direction comes from the line queue (ex_lineque): Upline or Downline.\n\n"
            "Gun Firing Sequence -> Sequence Source picks where the cycle comes from.\n\n"
            "Manual (sequence below)\n"
            "  Up and Down are comma lists of source numbers; Anchor SP fixes the phase.\n"
            "  index = (shotpoint - Anchor SP) mod (number of entries in the list)\n"
            "  expected source = list[index]\n"
            "  Defaults Up 1,2,3 / Down 3,2,1 / Anchor {a} are the original three-source rule.\n"
            "  Two sources is just Up 1,2 and Down 2,1 - nothing else needs changing.\n\n"
            "Preplot (P1/11)\n"
            "  Cycles, anchor, cycle length and dither are all read from the design preplot,\n"
            "  so source count and firing order follow the job instead of being typed in.\n"
            "  Read from: Source_Shooting_Sequence_Offset (cycle per direction),\n"
            "  Reference_Shot_Number (anchor), Source_Shooting_Sequence_Length (wrap),\n"
            "  Source_Shooting_Constraints_Definition / jitteringAtIndex (dither seconds).\n"
            "  index = (shotpoint - reference) mod length upline,\n"
            "          (reference - shotpoint) mod length downline.\n"
            "  While this is selected the per-source dither files and the Dither Pattern\n"
            "  Reference row are hidden - the preplot supplies both. Switch back to\n"
            "  Manual to bring them back; nothing typed into them is lost.\n\n"
            "PASS when the source in the log matches this expected source.\n\n"
            "DITHER CHECK (by Dither Pattern Reference mode)\n"
            "=================================================\n"
            "Each source has its own .dither file (values top row to bottom). The expected value is compared to\n"
            "Trinav applied dither from the log (Aimpoint dither mode / delta time).\n\n"
            "Anchored SP\n"
            "  Reference shot = Anchored Shot from the line queue. Along the line, row offset from that reference is:\n"
            "    Upline:   (shotpoint - anchor)\n"
            "    Downline: (anchor - shotpoint)\n"
            "  File row index wraps with the pattern length. Row 0 of the file is the dither at the anchor SP.\n\n"
            "Production FSP\n"
            "  Same idea, but the reference shot is the Production FSP from the line queue (not the anchor).\n\n"
            "Adaptive\n"
            "  Uses the last three distinct shotpoints in the log (with Trinav dither) that are consecutive along the\n"
            "  line (step = Shot increment). Their three Trinav values must match three consecutive rows in each\n"
            "  source .dither file (same order, top to bottom). That sets where the pattern aligns.\n"
            "  For the current shot, expected row = (match start row) + (steps from the oldest SP of that triple);\n"
            "  Upline: steps = shot - oldest SP; Downline: steps = oldest SP - shot. Wraps by pattern length.\n"
            "  Until calibration succeeds, dither QC stays in WAIT (Adaptive calibrating).\n"
            "  If Trinav restarts or the pattern phase shifts, consecutive dither mismatches while locked will clear\n"
            "  alignment and start triple matching again (see constant ADAPTIVE_MISMATCH_STREAK_TO_RESET in script).\n\n"
            "Source Sequence Check Only\n"
            "  When enabled, only the source sequence is checked; dither is not compared.\n"
        ).format(a=a)

    def _show_info_window(self):
        if self._info_window is not None:
            try:
                if self._info_window.winfo_exists():
                    self._info_window.lift()
                    try:
                        self._info_window.focus_force()
                    except tk.TclError:
                        pass
                    if getattr(self, '_info_text_widget', None) is not None:
                        try:
                            if self._info_text_widget.winfo_exists():
                                self._info_text_widget.config(state=tk.NORMAL)
                                self._info_text_widget.delete('1.0', tk.END)
                                self._info_text_widget.insert(tk.END, self._info_help_text())
                                self._info_text_widget.config(state=tk.DISABLED)
                        except tk.TclError:
                            pass
                    return
            except tk.TclError:
                pass
            self._info_window = None

        w = tk.Toplevel(self.root)
        w.title("xSourceDitherQC — Info")
        w.configure(bg=self.color_blue_aura_bg)
        w.transient(self.root)
        try:
            w.minsize(420, 320)
        except tk.TclError:
            pass

        hdr = tk.Label(w, text="How checks work", bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                       font=self.heading_font)
        hdr.pack(anchor='w', padx=10, pady=(10, 4))

        self._info_text_widget = ScrolledText.ScrolledText(
            w, wrap=tk.WORD, width=72, height=22, state=tk.NORMAL,
            font=self.results_font, bg=self.color_log_bg, fg=self.color_text_dark,
            insertbackground=self.color_text_dark, relief=tk.FLAT, bd=0)
        self._info_text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        self._info_text_widget.insert(tk.END, self._info_help_text())
        self._info_text_widget.config(state=tk.DISABLED)

        btn_row = tk.Frame(w, bg=self.color_blue_aura_bg)
        btn_row.pack(fill=tk.X, pady=(0, 10))

        def _on_info_close():
            self._info_window = None
            self._info_text_widget = None
            try:
                w.destroy()
            except tk.TclError:
                pass

        tk.Button(btn_row, text="Close", command=_on_info_close, width=10,
                  bg=self.color_button_bg, fg=self.color_text_dark,
                  activebackground=self.color_button_active_bg).pack(side=tk.RIGHT, padx=10)

        w.protocol("WM_DELETE_WINDOW", _on_info_close)
        self._info_window = w

    def _build_ui_elements(self):
        current_ui_values_cache = {}
        for sid, existing_cfg_dict in self.source_configs.items():
            if not isinstance(existing_cfg_dict, dict):
                continue
            cfg_data_to_preserve = {}
            if 'path_var_dither' in existing_cfg_dict:
                try:
                    cfg_data_to_preserve['path_var_dither_value'] = existing_cfg_dict['path_var_dither'].get()
                except (tk.TclError, AttributeError):
                    cfg_data_to_preserve['path_var_dither_value'] = existing_cfg_dict.get('path_var_dither_value', '')
            else:
                cfg_data_to_preserve['path_var_dither_value'] = existing_cfg_dict.get('path_var_dither_value', '')
            current_ui_values_cache[sid] = cfg_data_to_preserve

        for widget in self.sources_area.winfo_children():
            widget.destroy()
        self.source_configs.clear()

        active_ids = self._active_source_ids()
        self.num_sources.set(len(active_ids))

        for source_id in active_ids:
            segment = tk.LabelFrame(self.sources_area, text="Source {}".format(source_id), padx=5, pady=5,
                                    bg=self.color_blue_aura_bg, fg=self.color_label_frame_fg, font=self.results_font)
            segment.pack(fill=tk.X, padx=2, pady=(0, 3))
            new_src_config_dict = {'segment': segment}
            preserved_data = current_ui_values_cache.get(source_id, {})

            path_frame = tk.Frame(segment, bg=self.color_blue_aura_bg)
            path_frame.pack(fill=tk.X)
            tk.Label(path_frame, text="Dither File to Use:", width=18, anchor='w', bg=self.color_blue_aura_bg, fg=self.color_text_dark).pack(side=tk.LEFT)
            prev_path = preserved_data.get('path_var_dither_value', "")
            new_src_config_dict['path_var_dither'] = tk.StringVar(value=prev_path)
            new_src_config_dict['path_var_dither_value'] = prev_path
            _dither_entry = tk.Entry(path_frame, textvariable=new_src_config_dict['path_var_dither'],
                     bg=self.color_entry_bg, fg=self.color_text_dark, insertbackground=self.color_text_dark,
                     disabledbackground=self.color_disabled_bg, disabledforeground=self.color_disabled_fg)
            _dither_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
            _dither_btn = tk.Button(path_frame, text="Browse...", command=lambda s=source_id: self.browse_dither_file(s),
                      bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg,
                      disabledforeground=self.color_disabled_fg)
            _dither_btn.pack(side=tk.LEFT)
            new_src_config_dict['entry_dither'] = _dither_entry
            new_src_config_dict['btn_dither'] = _dither_btn
            new_src_config_dict['status_label_dither'] = tk.Label(path_frame, text="Not Loaded", fg="gray", width=10, font=self.small_font, bg=self.color_blue_aura_bg)
            new_src_config_dict['status_label_dither'].pack(side=tk.LEFT, padx=5)
            new_src_config_dict['path_var_dither'].trace('w', lambda n, idx, m, var=new_src_config_dict['path_var_dither'], cfg=new_src_config_dict, key='path_var_dither_value': self._update_path_cache(cfg, key, var))

            self.source_configs[source_id] = new_src_config_dict
            if new_src_config_dict['path_var_dither'].get():
                self.load_dither_pattern(source_id, new_src_config_dict['path_var_dither'].get())

        self._apply_seq_source_state()

    def _rebuild_source_rows_if_changed(self):
        if not hasattr(self, 'sources_area') or self.sources_area is None:
            return
        want = self._active_source_ids()
        have = sorted((self.source_configs or {}).keys())
        if want != have:
            self._build_ui_elements()

    def _on_seq_source_changed(self):
        """Sequence source switched: reset adaptive alignment, reload the preplot, regrey widgets."""
        self._reset_adaptive_calibration()
        self._adaptive_line_fingerprint = None
        if self._is_preplot_mode():
            path = ""
            try:
                path = self.preplot_path_var.get().strip()
            except (tk.TclError, AttributeError):
                path = ""
            if path:
                self.load_preplot(path)
            else:
                self._preplot = None
                if self._preplot_status_label:
                    self._preplot_status_label.config(text="Not Loaded", fg="gray")
                self.log_message("Sequence source is Preplot: select a P1/11 preplot file.", "warning")
        self._apply_seq_source_state()
        self._update_shotpoint_check_source()

    def _apply_seq_source_state(self):
        """Show only the inputs the selected sequence source actually uses.

        Rows are re-packed in a fixed order every time rather than restored in
        place, so hiding and re-showing cannot scramble the layout."""
        preplot_on = self._is_preplot_mode()

        def _show(widget, **pack_opts):
            if widget is None:
                return
            try:
                widget.pack_forget()
                widget.pack(**pack_opts)
            except tk.TclError:
                pass

        def _hide(widget):
            if widget is None:
                return
            try:
                widget.pack_forget()
            except tk.TclError:
                pass

        def _enable(widget):
            if widget is None:
                return
            try:
                widget.config(state=tk.NORMAL)
            except tk.TclError:
                pass

        # Gun Firing Sequence: source selector always, then whichever input it needs.
        _show(self._seq_src_row, fill=tk.X, padx=5, pady=(3, 2))
        _hide(self._preplot_row)
        _hide(self._manual_row)
        if preplot_on:
            _show(self._preplot_row, fill=tk.X, padx=5, pady=(2, 5))
            for w in self._preplot_widgets or []:
                _enable(w)
        else:
            _show(self._manual_row, fill=tk.X, padx=5, pady=(2, 5))
            for w in self._manual_seq_widgets or []:
                _enable(w)

        # Dither Pattern Reference only indexes .dither files, so it is moot
        # once the preplot supplies its own reference shot.
        _hide(self._pat_row)
        _hide(self._gun_row)
        if not preplot_on:
            _show(self._pat_row, fill=tk.X, pady=(2, 6))
            _enable(getattr(self, '_dither_pattern_ref_menu', None))
        _show(self._gun_row, fill=tk.X, pady=(0, 2))

        # Per-source .dither files, and the rule above them. The container is hidden as
        # well: an emptied Tk frame keeps its last size, which would leave a dead gap.
        _hide(self._sources_sep)
        _hide(getattr(self, 'sources_area', None))
        for cfg in (self.source_configs or {}).values():
            if isinstance(cfg, dict):
                _hide(cfg.get('segment'))
        if not preplot_on:
            try:
                self.sources_area.pack_forget()
                if self._postplot_frame is not None:
                    self.sources_area.pack(fill=tk.X, pady=(5, 0), before=self._postplot_frame)
                else:
                    self.sources_area.pack(fill=tk.X, pady=(5, 0))
                self._sources_sep.pack(fill=tk.X, pady=5, before=self.sources_area)
            except (tk.TclError, AttributeError):
                pass
            for sid in sorted((self.source_configs or {}).keys()):
                cfg = self.source_configs.get(sid)
                if not isinstance(cfg, dict):
                    continue
                _show(cfg.get('segment'), fill=tk.X, padx=2, pady=(0, 3))
                _enable(cfg.get('entry_dither'))
                _enable(cfg.get('btn_dither'))

    def _update_path_cache(self, config_dict, value_key_in_dict, tk_string_var):
        try:
            config_dict[value_key_in_dict] = tk_string_var.get()
        except (tk.TclError, AttributeError):
            pass

    def _line_upline_for_shotpoint_preview(self):
        """True=upline, False=downline, None=unknown (need lineque)."""
        li = self._refresh_line_info_cache or self.current_line_info
        if not li:
            return None
        up = li.get('upline')
        if up == 1:
            return True
        if up == 0:
            return False
        return None

    def _update_shotpoint_check_source(self, *args):
        raw = (self.shotpoint_check_var.get() or "").strip()
        if not raw:
            self.shotpoint_check_source_var.set("—")
            return
        is_up = self._line_upline_for_shotpoint_preview()
        if is_up is None:
            self.shotpoint_check_source_var.set("Need Line Queue (upline); Refresh")
            return
        anchored = None
        li = self._refresh_line_info_cache or self.current_line_info
        if li:
            anchored = li.get('anchored_shot')
        exp, st = self.get_expected_source(raw, anchored, is_up)
        if st != "OK" or exp is None:
            self.shotpoint_check_source_var.set(st)
        else:
            self.shotpoint_check_source_var.set("Source {}".format(exp))

    def _apply_parsed_lineque_to_param_display(self, line_info):
        """Fill read-only lineque fields from first/current block, or clear to dash."""
        dash = "—"
        if line_info and line_info.get('anchored_shot') is not None:
            self.display_anchored_shot_var.set(str(line_info['anchored_shot']))
            self.display_line_name_var.set(line_info.get('name') or dash)
            self.display_prod_shotpoints_var.set(line_info.get('prod_shotpoint_display') or dash)
            up = line_info.get('upline')
            if up == 1:
                self.display_line_direction_var.set("Upline (upline 1)")
            elif up == 0:
                self.display_line_direction_var.set("Downline (upline 0)")
            else:
                self.display_line_direction_var.set("Unknown (upline {})".format(up))
            anc = line_info['anchored_shot']
            is_up = line_info.get('upline') == 1
            exp, st = self.get_expected_source(anc, anc, is_up)
            if st == "OK" and exp is not None:
                self.display_source_at_anchor_var.set("Source {}".format(exp))
            else:
                self.display_source_at_anchor_var.set(st if st else dash)
            return
        self.display_anchored_shot_var.set(dash)
        self.display_line_name_var.set(dash)
        self.display_prod_shotpoints_var.set(dash)
        self.display_line_direction_var.set(dash)
        self.display_source_at_anchor_var.set(dash)

    def refresh_params_from_system(self):
        line_info = None
        out = self.run_command(self.lineque_cmd)
        if out:
            line_info = self.parse_lineque_output(out, quiet=True)
        if line_info and line_info.get('anchored_shot') is not None:
            self._apply_parsed_lineque_to_param_display(line_info)
            self._refresh_line_info_cache = line_info
        else:
            self._apply_parsed_lineque_to_param_display(None)

        self._update_shotpoint_check_source()

    def select_config_file(self):
        start_dir = self.default_config_dir
        if self.config_full_path and os.path.isdir(os.path.dirname(self.config_full_path)):
            start_dir = os.path.dirname(self.config_full_path)
        elif not os.path.exists(start_dir):
            try: os.makedirs(start_dir); self.log_message("Created default config directory: {}".format(start_dir), "info")
            except OSError as e: self.log_message("Error creating directory {}: {}. Falling back to user home.".format(start_dir, e), "error"); start_dir = os.path.expanduser("~")
        initial_file = self.config_name_var.get() or self.default_config_name
        filepath = tkFileDialog.asksaveasfilename(
            title="Load an existing .xcfg, or go to a folder and type a new name to save there",
            initialdir=start_dir, initialfile=initial_file, defaultextension=".xcfg",
            filetypes=(("xSourceDitherQC Config", "*.xcfg"), ("Old Config files", "*.cfg"), ("All files", "*.*"))
        )
        if filepath:
            filepath = os.path.normpath(filepath)
            self.log_message("User selected file: {}. Attempting to load...".format(filepath), "info")
            self.load_config(filepath_to_load=filepath)

    def browse_dither_file(self, source_id):
        start_dir = self.default_dither_dir
        src_conf_dict = self.source_configs.get(source_id)
        if not src_conf_dict:
            self.log_message("Error: Source {} config not found for Browse.".format(source_id), "error")
            return
        current_path_val = ""
        if 'path_var_dither' in src_conf_dict:
            try:
                current_path_val = src_conf_dict['path_var_dither'].get()
            except (tk.TclError, AttributeError):
                current_path_val = src_conf_dict.get('path_var_dither_value', '')
        if current_path_val and os.path.isdir(os.path.dirname(current_path_val)):
            start_dir = os.path.dirname(current_path_val)
        elif not os.path.exists(start_dir):
            try:
                os.makedirs(start_dir)
            except OSError as e:
                self.log_message("Error creating dither dir {}: {}. Fallback home.".format(start_dir, e), "error")
                start_dir = os.path.expanduser("~")

        filepath = tkFileDialog.askopenfilename(
            title="Select dither file for Source {}".format(source_id),
            initialdir=start_dir, filetypes=(("Dither files", "*.dither"), ("Text files", "*.txt"), ("All files", "*.*"))
        )
        if filepath:
            filepath = os.path.normpath(filepath)
            try:
                src_conf_dict['path_var_dither'].set(filepath)
                src_conf_dict['path_var_dither_value'] = filepath
                self.load_dither_pattern(source_id, filepath)
            except (tk.TclError, AttributeError) as e:
                self.log_message("Error setting file path S{}: {}".format(source_id, e), "error")

    def load_dither_pattern(self, source_id, filepath):
        pattern_key = source_id
        status_label = None
        src_conf_dict = self.source_configs.get(source_id)
        if src_conf_dict:
            status_label = src_conf_dict.get('status_label_dither')

        if not filepath or not os.path.exists(filepath):
            if filepath:
                self.log_message("Dither file path invalid S{}: {}".format(source_id, filepath), "warning")
            self.dither_patterns.pop(pattern_key, None)
            if status_label:
                status_label.config(text="Load Err", fg="red")
            return False
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
            pattern = []
            line_num = 0
            for line in lines:
                line_num += 1
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                val_str = line
                match = re.match(r'^\s*(?:\[.*\])?\s*(-?\d+\.?\d*)\s*$', line)
                if match:
                    val_str = match.group(1)
                try:
                    pattern.append(float(val_str))
                except ValueError:
                    if not match:
                        self.log_message("Warn: Skipping invalid line {} in {}: '{}'".format(line_num, os.path.basename(filepath), line), "warning")
            if not pattern:
                self.log_message("Error: No valid dither values found in: {}".format(os.path.basename(filepath)), "error")
                self.dither_patterns[pattern_key] = None
                if status_label:
                    status_label.config(text="Load Err", fg="red")
                return False
            self.dither_patterns[pattern_key] = pattern
            if status_label:
                status_label.config(text="Loaded", fg="blue")
            return True
        except IOError as e:
            self.log_message("Error loading {}: {}".format(os.path.basename(filepath), e), "error")
            self.dither_patterns[pattern_key] = None
        except Exception as e:
            self.log_message("Error processing {}: {}".format(os.path.basename(filepath), e), "error")
            self.dither_patterns[pattern_key] = None
        if status_label:
            status_label.config(text="Load Err", fg="red")
        return False

    def log_message(self, message, level="info"):
        if level == "debug": return
        try:
            if not hasattr(self, 'log_text') or not self.log_text: print "[Log-{}] {}".format(level, message); return
            if level == "status_ok" or level == "status_fail":
                 if hasattr(self, 'status_label') and self.status_label:
                     self.status_label_text.set(message)
                     self.status_label.config(fg="green" if level == "status_ok" else "red")
            else:
                self.log_text.config(state=tk.NORMAL)
                tag = level if level in ["ok", "error", "warning", "info", "debug", "heading", "separator"] else "info"
                self.log_text.insert(tk.END, message + "\n", tag)
                self._trim_log()
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)
        except tk.TclError: print "[Log-{}] {}".format(level, message)

    def run_command(self, cmd):
        """Run a system command; None on any failure. Bounded by COMMAND_TIMEOUT_S so a hung
        ex_lineque/tail costs one cycle instead of freezing the tool for good."""
        try:
            # Own process group, so a timeout can kill the command itself and not just the shell.
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    preexec_fn=os.setsid)
        except OSError as e:
            self.log_message("Sys Error: Cmd for '{}': {}".format(cmd, e), "error"); return None
        except Exception as e:
            self.log_message("Unexpected err cmd '{}': {}".format(cmd, e), "error"); return None
        box = {}
        def _wait():
            try:
                box['out'] = proc.communicate()
            except Exception as e:
                box['exc'] = e
        t = threading.Thread(target=_wait); t.daemon = True; t.start()
        t.join(COMMAND_TIMEOUT_S)
        if t.is_alive():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
            t.join(2.0)
            self.log_message("Error cmd '{}': no response after {}s - killed, will retry next cycle.".format(
                cmd, COMMAND_TIMEOUT_S), "error")
            return None
        if 'exc' in box:
            self.log_message("Unexpected err cmd '{}': {}".format(cmd, box['exc']), "error"); return None
        stdout, stderr = box.get('out', ("", ""))
        retcode = proc.returncode
        if retcode != 0:
            err_msg = stderr.strip() if stderr else "No stderr"
            self.log_message("Error cmd '{}': RetCode={} | Err: {}".format(cmd, retcode, err_msg), "error"); return None
        if stderr:
            self.log_message("Stderr from '{}': {}".format(cmd, stderr.strip()), "warning")
        return stdout.strip()

    def _trim_log(self):
        """Keep the check log bounded so a multi-day run cannot grow the Text widget without limit."""
        try:
            n_lines = int(self.log_text.index('end-1c').split('.')[0])
            if n_lines > LOG_MAX_LINES:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.delete('1.0', '{}.0'.format(n_lines - LOG_KEEP_LINES + 1))
                self.log_text.config(state=tk.DISABLED)
        except (tk.TclError, ValueError, AttributeError):
            pass

    def _read_shotcontroller_log_via_file(self, max_lines=20):
        """Last N lines without shell tail (e.g. missing tail or cmd failed)."""
        try:
            with open(self.log_file_path, 'r') as f:
                lines = f.readlines()
        except (IOError, OSError) as e:
            self.log_message("Shot log read failed ({}): {}".format(self.log_file_path, e), "error")
            return None
        if not lines:
            return ''
        n = max(1, int(max_lines))
        chunk = lines[-n:] if len(lines) > n else lines
        return ''.join(chunk)

    def _fetch_shotcontroller_log_tail(self, max_lines=20):
        if max_lines != 20:
            cmd = 'tail -{} {}'.format(int(max_lines), self.log_file_path)
            out = self.run_command(cmd)
            if out is not None:
                return out
            self.log_message("Trying direct read of shot log (tail unavailable or failed)...", "warning")
            return self._read_shotcontroller_log_via_file(max_lines=max_lines)
        out = self.run_command(self.log_tail_cmd)
        if out is not None:
            return out
        self.log_message("Trying direct read of shot log (tail command unavailable or failed)...", "warning")
        return self._read_shotcontroller_log_via_file(max_lines=20)

    def parse_lineque_output(self, output, quiet=False):
        if output is None:
            return None
        lines = output.splitlines()
        top_line_data = {}
        in_line_queue_section = False
        found_first_line = False
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("Line Queue:"):
                in_line_queue_section = True
                continue
            if not in_line_queue_section:
                continue
            if not found_first_line and line.startswith("Line:") and re.search(r'\bupline\b', line, re.I):
                parts = line.split()
                lineque_key_aliases = {
                    'name': 'name', 'preplot': 'preplot', 'sailline': 'sailLine', 'upline': 'upline',
                    'sequence': 'sequence', 'type': 'type', 'shootingpattern': 'shootingPattern',
                }
                lineque_keys_lower = frozenset(lineque_key_aliases.keys())
                data_map = {}
                try:
                    i = 0
                    while i < len(parts):
                        tok = parts[i]
                        tlow = tok.lower().rstrip(':')
                        if tlow == 'line':
                            i += 1
                            continue
                        if tlow in lineque_keys_lower:
                            key = lineque_key_aliases[tlow]
                            i += 1
                            sub = []
                            while i < len(parts):
                                nt = parts[i].lower().rstrip(':')
                                if nt in lineque_keys_lower:
                                    break
                                sub.append(parts[i])
                                i += 1
                            if key == 'upline':
                                if not sub:
                                    raise ValueError("missing upline value")
                                top_line_data['upline'] = int(sub[0])
                            else:
                                data_map[key] = ' '.join(sub) if sub else 'N/A'
                        else:
                            i += 1
                    top_line_data['name'] = data_map.get('name', 'N/A')
                    top_line_data['preplot'] = data_map.get('preplot', 'N/A')
                    top_line_data['sequence'] = data_map.get('sequence', 'N/A')
                    top_line_data['shooting_pattern'] = data_map.get('shootingPattern', 'N/A')
                    if 'upline' not in top_line_data:
                        raise ValueError("missing upline field")
                    if top_line_data['upline'] not in [0, 1]:
                        raise ValueError("'upline' value ({}) invalid".format(top_line_data['upline']))
                    found_first_line = True
                except (ValueError, KeyError) as e:
                    self.log_message("Error parsing 'Line:' details: {} from '{}'".format(e, line), "error")
                    return None
            elif found_first_line and re.search(r'anchored\s+shot\s+\d+', line, re.I):
                match = re.search(r'Anchored\s+shot\s+(\d+)', line, re.I)
                if match:
                    top_line_data['anchored_shot'] = int(match.group(1))
                    prod_seg = re.search(r'\bProd\s+(.+?)(?=\s+Coverage\b|\s+Extra\b|$)', line, re.I)
                    if prod_seg:
                        top_line_data['prod_shotpoint_display'] = 'Prod {}'.format(prod_seg.group(1).strip())
                    prod_m = re.search(r'\bProd\s+(\d+)', line, re.I)
                    if prod_m:
                        top_line_data['prod_fsp'] = int(prod_m.group(1))
                    if not quiet:
                        self.log_message("Line Info: Name={}, Preplot={}, Upline={}, Anchor={}, {}, Prod FSP={}".format(
                            top_line_data.get('name'), top_line_data.get('preplot'),
                            top_line_data.get('upline'), top_line_data.get('anchored_shot'),
                            top_line_data.get('prod_shotpoint_display', 'Prod (n/a)'),
                            top_line_data.get('prod_fsp', 'N/A')), "info")
                    return top_line_data
                if not quiet:
                    self.log_message("Warn: Could not parse Anchor SP# from: '{}'".format(line), "warning")
                return None
            elif found_first_line and line.startswith("Line:") and re.search(r'\bupline\b', line, re.I):
                break
        if not top_line_data or 'anchored_shot' not in top_line_data:
            if not quiet:
                self.log_message("Could not find complete line details (Anchor SP) in Line Queue.", "warning")
            return None
        return top_line_data

    def _log_line_references_shot(self, line, shot_num):
        s = str(int(shot_num))
        if ' - {} - '.format(s) in line:
            return True
        if re.search(r'\bShot Number\s*=\s*{}\b'.format(re.escape(s)), line):
            return True
        if re.search(r'\bfor shot {}\b'.format(re.escape(s)), line, re.I):
            return True
        return False

    def _parse_new_shot_and_source_from_lines(self, lines):
        """Latest NEW SHOT in tail with Source to fire / Source To Fire on a following line (same block).
        Shot in message may match the log column after date/time (signed SP allowed)."""
        shot_data = None
        for i, line in enumerate(lines):
            raw = line.strip()
            m_ns = re.search(r'NEW\s+SHOT\s*:?\s*(-?\d+)', raw, re.I)
            if not m_ns:
                continue
            try:
                sn = int(m_ns.group(1))
            except ValueError:
                continue
            src = None
            for j in range(i + 1, len(lines)):
                sub = lines[j].strip()
                if re.search(r'NEW\s+SHOT', sub, re.I):
                    break
                m_sf = re.search(r'Source\s+to\s+fire:\s*.+?\bsrc\s+(\d+)', sub, re.I)
                if not m_sf:
                    m_sf = re.search(r'Source\s+To\s+Fire\s*=\s*(\d+)', sub, re.I)
                if m_sf:
                    try:
                        src = int(m_sf.group(1))
                        break
                    except ValueError:
                        pass
            if src is not None:
                shot_data = {'shot_number': sn, 'source_to_fire': src}
        return shot_data

    def _attach_aimpoint_dither_for_shot(self, lines, shot_number, shot_data, quiet):
        """Fill applied_dither (and source if missing) from Aimpoint dither lines for shot_number."""
        for line in reversed(lines):
            line = line.strip()
            if "Aimpoint dither mode" not in line or "applying delta time" not in line:
                continue
            m_old = re.search(
                r'sourceToFire\s+(\d+)\s+applying\s+delta\s+time\s+(-?\d+\.?\d*)\s+for\s+shot\s+(-?\d+)', line, re.I)
            if m_old:
                try:
                    sn = int(m_old.group(3))
                    if sn != shot_number:
                        continue
                    shot_data['applied_dither'] = float(m_old.group(2))
                    if 'source_to_fire' not in shot_data:
                        shot_data['source_to_fire'] = int(m_old.group(1))
                    return True
                except (ValueError, IndexError):
                    if not quiet:
                        self.log_message("Error parsing legacy dither line: {}".format(line), "error")
                    continue
            m_new = re.search(
                r'Aimpoint\s+dither\s+mode,?\s*applying\s+delta\s+time\s+(-?\d+\.?\d*)\s+for\s+shot\s+(-?\d+)', line, re.I)
            if m_new:
                try:
                    sn = int(m_new.group(2))
                    if sn != shot_number:
                        continue
                    shot_data['applied_dither'] = float(m_new.group(1))
                    return True
                except (ValueError, IndexError):
                    if not quiet:
                        self.log_message("Error parsing dither line: {}".format(line), "error")
                    continue
        return False

    def parse_shotcontroller_log(self, output, quiet=False):
        if output is None:
            return None
        lines = output.splitlines()
        shot_data = self._parse_new_shot_and_source_from_lines(lines)
        if shot_data:
            shot_data.setdefault('applied_dither', float('nan'))
            self._attach_aimpoint_dither_for_shot(lines, shot_data['shot_number'], shot_data, quiet)
        else:
            shot_data = {}
            dither_line_found = False
            for line in reversed(lines):
                line = line.strip()
                if "Aimpoint dither mode" not in line or "applying delta time" not in line:
                    continue
                m_old = re.search(
                    r'sourceToFire\s+(\d+)\s+applying\s+delta\s+time\s+(-?\d+\.?\d*)\s+for\s+shot\s+(-?\d+)', line, re.I)
                if m_old:
                    try:
                        shot_data['source_to_fire'] = int(m_old.group(1))
                        shot_data['applied_dither'] = float(m_old.group(2))
                        shot_data['shot_number'] = int(m_old.group(3))
                        dither_line_found = True
                        break
                    except (ValueError, IndexError):
                        if not quiet:
                            self.log_message("Error parsing legacy dither line: {}".format(line), "error")
                        continue
                m_new = re.search(
                    r'Aimpoint\s+dither\s+mode,?\s*applying\s+delta\s+time\s+(-?\d+\.?\d*)\s+for\s+shot\s+(-?\d+)', line, re.I)
                if m_new:
                    try:
                        shot_data['applied_dither'] = float(m_new.group(1))
                        shot_data['shot_number'] = int(m_new.group(2))
                        dither_line_found = True
                        break
                    except (ValueError, IndexError):
                        if not quiet:
                            self.log_message("Error parsing dither line: {}".format(line), "error")
                        continue
                if not quiet:
                    self.log_message("Warn: Could not parse 'Aimpoint dither mode' line: {}".format(line), "warning")
            if not dither_line_found:
                if not quiet:
                    self.log_message("No NEW SHOT / Source to fire pair or Aimpoint dither line in log tail.", "warning")
                return None
            if 'source_to_fire' not in shot_data:
                sn = shot_data['shot_number']
                for line in reversed(lines):
                    line = line.strip()
                    if not self._log_line_references_shot(line, sn):
                        continue
                    m = re.search(r'Source\s+to\s+fire:\s*.+?\bsrc\s+(\d+)', line, re.I)
                    if not m:
                        m = re.search(r'Source\s+to\s+fire:\s*\S+\s+src\s+(\d+)', line, re.I)
                    if not m:
                        m = re.search(r'Source\s+To\s+Fire\s*=\s*(\d+)', line, re.I)
                    if m:
                        try:
                            shot_data['source_to_fire'] = int(m.group(1))
                            break
                        except ValueError:
                            continue
                if 'source_to_fire' not in shot_data:
                    if not quiet:
                        self.log_message("Could not find Source to fire for shot {} in log tail.".format(sn), "warning")
                    return None
        interval_found = False
        target_shot_number = shot_data['shot_number']
        for line in reversed(lines):
            line = line.strip()
            match_shot_context = re.match(
                r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+-\s+(-?\d+)\s+-', line)
            current_line_shot = -1
            if match_shot_context:
                try:
                    current_line_shot = int(match_shot_context.group(1))
                except ValueError:
                    pass
            if "Shot Time Interval:" in line:
                if current_line_shot == target_shot_number:
                    match_interval = re.search(r'Shot Time Interval:\s*(\d+\.?\d*)', line)
                    if match_interval:
                        try:
                            shot_data['interval'] = float(match_interval.group(1))
                            interval_found = True
                            break
                        except ValueError:
                            self.log_message("Error parsing interval value from line: {}".format(line), "error")
                    else:
                        self.log_message("Warn: Could not parse 'Shot Time Interval:' value from: {}".format(line), "warning")
        if not interval_found:
            if not quiet:
                self.log_message("Could not find 'Shot Time Interval' for SP {}. Using default.".format(target_shot_number), "warning")
            shot_data['interval'] = float(self.default_retry_interval_ms / 1000.0)
        return shot_data

    def _get_pattern_ref_mode(self):
        # Preplot mode supplies its own reference shot, so it overrides the menu selection.
        if self._is_preplot_mode():
            return PATTERN_REF_PREPLOT
        v = self.dither_pattern_reference_var.get()
        if v in PATTERN_REF_CHOICES:
            return v
        return PATTERN_REF_ANCHORED_SP

    def _preplot_line_name_from(self, line_info):
        """Preplot line name for a line-queue block.

        Live ex_lineque (verified 2026-09-22): 'name' is the SEQUENCE name, e.g.
        0406-06850P2002, and 'preplot' is the preplot LINE name, e.g. 6850_T1_315.
        The preplot's line list is keyed by the latter."""
        if not line_info:
            return None
        for key in ('preplot', 'name'):
            v = line_info.get(key)
            if v not in (None, '', 'N/A'):
                return str(v)
        return None

    def _current_line_name(self):
        return self._preplot_line_name_from(self._refresh_line_info_cache or self.current_line_info)

    def _preplot_pattern_for_direction(self, is_upline, line_name=None):
        """(pattern_id, entry) for this direction - the current line's own pair when
        the preplot lists it, else the preplot default pair."""
        pp = self._preplot
        if not pp:
            return None, None
        if line_name is None:
            line_name = self._current_line_name()
        pair = pp['line_patterns'].get(line_name) if line_name else None
        if pair is None:
            pair = pp['default_pair']
        pid = pair[0] if is_upline else pair[1]
        return pid, pp['patterns'].get(pid)

    def _is_preplot_mode(self):
        try:
            return self.seq_source_var.get() == SEQ_SOURCE_PREPLOT
        except (tk.TclError, AttributeError):
            return False

    def _parse_sequence_text(self, txt):
        """'1,2,3' -> [1, 2, 3]. Plain comma list, no expression evaluation."""
        if txt is None:
            return None, "empty"
        parts = [p.strip() for p in str(txt).replace(';', ',').split(',') if p.strip()]
        if not parts:
            return None, "empty"
        out = []
        for p in parts:
            try:
                v = int(p)
            except ValueError:
                return None, "non-numeric entry '{}'".format(p)
            if v < 1:
                return None, "source numbers start at 1 (got {})".format(v)
            out.append(v)
        return out, "OK"

    def _manual_cycle(self, is_upline):
        var = self.up_sequence_var if is_upline else self.down_sequence_var
        label = "Up sequence" if is_upline else "Down sequence"
        try:
            txt = var.get()
        except (tk.TclError, AttributeError):
            return None, "{} unreadable".format(label)
        cyc, st = self._parse_sequence_text(txt)
        if cyc is None:
            return None, "{}: {}".format(label, st)
        return cyc, "OK"

    def _manual_anchor(self):
        try:
            txt = self.seq_anchor_var.get().strip()
        except (tk.TclError, AttributeError):
            return None, "Anchor SP unreadable"
        try:
            return int(txt), "OK"
        except ValueError:
            return None, "Anchor SP invalid: '{}'".format(txt)

    def _active_source_ids(self):
        """Source numbers actually used by the active cycle, ascending.

        Drives which .dither files must be loaded, so a two-source job is not
        held up waiting for a Source 3 file it will never fire."""
        if self._is_preplot_mode():
            if self._preplot and self._preplot.get('sources'):
                return sorted(self._preplot['sources'])
            return list(range(1, SOURCE_CYCLE_COUNT + 1))
        ids = set()
        for up in (True, False):
            cyc, _st = self._manual_cycle(up)
            if cyc:
                ids.update(cyc)
        if not ids:
            return list(range(1, SOURCE_CYCLE_COUNT + 1))
        return sorted(ids)

    def _active_source_count(self):
        """Sources actually in the cycle - preplot-derived, or counted from the manual cycle."""
        if self._is_preplot_mode():
            if self._preplot:
                return self._preplot.get('num_srcs', SOURCE_CYCLE_COUNT)
            return SOURCE_CYCLE_COUNT
        up, _st = self._manual_cycle(True)
        if up:
            return len(set(up))
        return SOURCE_CYCLE_COUNT

    def browse_preplot_file(self):
        cur = ""
        try:
            cur = self.preplot_path_var.get()
        except (tk.TclError, AttributeError):
            pass
        start_dir = os.path.dirname(cur) if cur else ""
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = self.default_preplot_dir
        if not os.path.isdir(start_dir):
            start_dir = os.path.expanduser("~")
        filepath = tkFileDialog.askopenfilename(
            title="Select preplot (P1/11) to read gun sequence and dither from",
            initialdir=start_dir,
            filetypes=(("P1/11 preplot", "*.p111"), ("P1 files", "*.p1*"), ("All files", "*.*")))
        if filepath:
            filepath = os.path.normpath(filepath)
            try:
                self.preplot_path_var.set(filepath)
            except (tk.TclError, AttributeError):
                pass
            self.load_preplot(filepath)

    def browse_postplot_file(self):
        cur = ""
        try:
            cur = self.postplot_path_var.get()
        except (tk.TclError, AttributeError):
            pass
        start_dir = os.path.dirname(cur) if cur else ""
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = self.default_preplot_dir
        if not os.path.isdir(start_dir):
            start_dir = os.path.expanduser("~")
        fp = tkFileDialog.askopenfilename(
            title="Select acquired P1/11 postplot to QC", initialdir=start_dir,
            filetypes=(("P1/11", "*.p111"), ("P1 files", "*.p1*"), ("All files", "*.*")))
        if fp:
            try:
                self.postplot_path_var.set(os.path.normpath(fp))
            except (tk.TclError, AttributeError):
                pass

    def _postplot_expected(self, sp, is_upline, line_name):
        """(expected_source, expected_dither or None, status) for one acquired shot."""
        if self._is_preplot_mode():
            pp = self._preplot
            if not pp:
                return None, None, "Preplot not loaded"
            pid, pat = self._preplot_pattern_for_direction(is_upline, line_name)
            if pat is None:
                return None, None, "no pattern {}".format(pid)
            L = len(pat['seq'])
            idx = (sp - pp['ref_shot']) % L if is_upline else (pp['ref_shot'] - sp) % L
            dith = pat.get('dither')
            if not dith:
                _o, opat = self._preplot_pattern_for_direction(not is_upline, line_name)
                dith = opat.get('dither') if opat else None
            exp_d = float(dith[idx % len(dith)]) if dith else None
            return int(pat['seq'][idx]), exp_d, "OK"
        src, st = self.get_expected_source(sp, None, is_upline)
        return src, None, st

    def run_postplot_qc(self):
        """Offline QC of an acquired P1/11 against the active sequence source. Never runs live."""
        if self.running:
            tkMessageBox.showwarning("Postplot QC", "Stop the live Source/Dither check first.")
            return
        try:
            path = self.postplot_path_var.get().strip()
        except (tk.TclError, AttributeError):
            path = ""
        if not path:
            tkMessageBox.showwarning("Postplot QC", "Select a P1/11 postplot first.")
            return
        preplot_mode = self._is_preplot_mode()
        if preplot_mode and not self._ensure_preplot_current(for_start=False):
            tkMessageBox.showerror("Postplot QC", "Sequence Source is Preplot but no valid preplot is loaded.")
            return
        groups, st = parse_postplot_p111(path)
        self.log_message("", "separator")
        self.log_message("POSTPLOT DITHER QC - {}".format(os.path.basename(path)), "heading")
        if groups is None:
            self.log_message("  {}".format(st), "error")
            self._set_postplot_status(False, "cannot read file")
            return
        if preplot_mode:
            self.log_message("  Reference: preplot {} (ref shot {}, cycle {})".format(
                os.path.basename(self._preplot['path']), self._preplot['ref_shot'], self._preplot['seq_len']), "info")
        else:
            up_c, _u = self._manual_cycle(True); dn_c, _d = self._manual_cycle(False)
            self.log_message("  Reference: manual sequence up {} / down {} anchor {} - "
                             "SOURCE SEQUENCE ONLY (dither needs Sequence Source = Preplot)".format(
                                 ",".join(str(x) for x in up_c or []), ",".join(str(x) for x in dn_c or []),
                                 self.seq_anchor_var.get()), "warning")

        tol = self.float_tolerance
        all_ok = True
        total_sp = 0
        for g in groups:
            shots = g['shots']
            n_sh = len(shots)
            total_sp += n_sh
            if g['is_upline'] is None:
                self.log_message("  Sequence {} line {}: only {} shot - cannot tell direction, skipped".format(
                    g['sequence'], g['line'], n_sh), "warning")
                all_ok = False
                continue
            is_up = g['is_upline']
            sps = [sh[0] for sh in shots]
            lo, hi = min(sps), max(sps)
            uniq = len(set(sps))
            gaps = (hi - lo + 1) - uniq
            dups = n_sh - uniq
            self.log_message("  Sequence {}  line {}  {}  SP {} -> {}  ({} shots, {} missing SP, {} duplicate)".format(
                g['sequence'], g['line'], "UPLINE" if is_up else "DOWNLINE",
                sps[0], sps[-1], n_sh, gaps, dups), "info")
            if preplot_mode:
                pid, _pat = self._preplot_pattern_for_direction(is_up, g['line'])
                listed = g['line'] in self._preplot['line_patterns']
                self.log_message("  Preplot pattern {} for this direction{}".format(
                    pid, "" if listed else "  (line NOT listed in preplot - using default pair)"), "info" if listed else "warning")
                if not listed:
                    all_ok = False

            src_bad = []; dit_bad = []; dit_checked = 0; dit_missing = 0; max_res = 0.0; exp_err = None
            for sp, src, dither, _t in shots:
                exp_src, exp_d, est = self._postplot_expected(sp, is_up, g['line'])
                if est != "OK":
                    exp_err = est
                    break
                if exp_src != src:
                    src_bad.append((sp, src, exp_src))
                if exp_d is not None:
                    if dither is None:
                        dit_missing += 1
                    else:
                        dit_checked += 1
                        res = abs(dither - exp_d)
                        if res > max_res:
                            max_res = res
                        if res >= tol:
                            dit_bad.append((sp, dither, exp_d))
            if exp_err:
                self.log_message("  Expected values unavailable: {}".format(exp_err), "error")
                all_ok = False
                continue

            fired = []
            for _sp, src, _d, _t in shots:
                if src in fired:
                    break
                fired.append(src)
            exp_cycle = []
            for sp, _s, _d, _t in shots:
                es, _ed, _st = self._postplot_expected(sp, is_up, g['line'])
                if es in exp_cycle:
                    break
                exp_cycle.append(es)
            self.log_message("  Source sequence (time order): fired {}   expected {}".format(
                ",".join(str(x) for x in fired), ",".join(str(x) for x in exp_cycle)), "info")
            if src_bad:
                all_ok = False
                self.log_message("  Source check: {} of {} WRONG".format(len(src_bad), n_sh), "error")
                for sp, got, exp in src_bad[:10]:
                    self.log_message("      SP {}: fired S{}, expected S{}".format(sp, got, exp), "error")
                if len(src_bad) > 10:
                    self.log_message("      ... {} more".format(len(src_bad) - 10), "error")
            else:
                self.log_message("  Source check: {}/{} OK".format(n_sh, n_sh), "ok")

            if not preplot_mode:
                self.log_message("  Dither check: skipped (manual mode)", "warning")
            elif dit_checked == 0:
                self.log_message("  Dither check: no Aimpoint Dither values in this postplot ({} shots without)".format(dit_missing), "error")
                all_ok = False
            else:
                if dit_missing:
                    self.log_message("  Dither: {} shots carry no Aimpoint Dither value".format(dit_missing), "warning")
                    all_ok = False
                if dit_bad:
                    all_ok = False
                    self.log_message("  Dither check: {} of {} WRONG (tol {:.3f} s, worst {:.3f} s)".format(
                        len(dit_bad), dit_checked, tol, max_res), "error")
                    for sp, got, exp in dit_bad[:10]:
                        self.log_message("      SP {}: applied {:+.3f}, preplot {:+.3f}".format(sp, got, exp), "error")
                    if len(dit_bad) > 10:
                        self.log_message("      ... {} more".format(len(dit_bad) - 10), "error")
                else:
                    self.log_message("  Dither check: {}/{} OK, worst residual {:.3f} s (tol {:.3f})".format(
                        dit_checked, dit_checked, max_res, tol), "ok")
            if gaps or dups:
                self.log_message("  Note: {} shotpoint(s) missing in range, {} duplicate(s) - "
                                 "not counted as failure".format(gaps, dups), "warning")

        self.log_message("  Total shotpoints checked: {}".format(total_sp), "info")
        self._set_postplot_status(all_ok, "{} SP{}".format(total_sp, "" if preplot_mode else ", sequence only"))

    def _set_postplot_status(self, ok, detail):
        msg = "Postplot QC: {} ({})".format("PASS" if ok else "FAIL", detail)
        self.log_message("RESULT: {}".format(msg), "ok" if ok else "error")
        try:
            self.status_label_text.set(msg)
            self.status_label.config(fg="green" if ok else "red")
        except (tk.TclError, AttributeError):
            pass

    def _preplot_crosscheck(self, line_info):
        """Warn loudly if the line queue disagrees with the loaded preplot. Once per line."""
        pp = self._preplot
        if not pp or not line_info:
            return
        key = (line_info.get('name'), line_info.get('upline'), line_info.get('preplot'),
               line_info.get('shooting_pattern'), pp.get('path'))
        if key == getattr(self, '_preplot_crosscheck_key', None):
            return
        self._preplot_crosscheck_key = key
        problems = []

        name = self._preplot_line_name_from(line_info)
        if name and pp['line_patterns'] and name not in pp['line_patterns']:
            problems.append("preplot line '{}' is not in the loaded preplot ({} lines listed) - wrong preplot file?".format(
                name, len(pp['line_patterns'])))

        sp_txt = line_info.get('shooting_pattern')
        is_up = line_info.get('upline') == 1
        exp_pid, _pat = self._preplot_pattern_for_direction(is_up, name)
        try:
            lq_pid = int(str(sp_txt).strip())
        except (ValueError, TypeError):
            lq_pid = None
        if lq_pid is not None and exp_pid is not None and lq_pid != exp_pid:
            if lq_pid in pp['patterns']:
                problems.append("line queue shooting pattern {} but preplot expects {} for {} on this line".format(
                    lq_pid, exp_pid, "upline" if is_up else "downline"))
            else:
                problems.append("line queue shooting pattern {} is not in the preplot (has {})".format(
                    lq_pid, ", ".join(str(k) for k in sorted(pp['patterns']))))

        if problems:
            for msg in problems:
                self.log_message("PREPLOT CHECK: " + msg, "error")
            self.log_message("PREPLOT CHECK: expected source/dither below may be for the WRONG preplot.", "error")
        else:
            self.log_message("Preplot check OK: sequence {} on preplot line {} ({}), pattern {}, ref shot {}.".format(
                line_info.get('name'), name, "upline" if is_up else "downline", exp_pid, pp['ref_shot']), "info")

    def _ensure_preplot_current(self, for_start=False):
        """Make _preplot match the path in the entry. Returns True when a usable preplot is held.

        Called on Return / focus-out of the path entry and again on Start, so a path that
        was typed rather than browsed can never leave a stale preplot behind."""
        try:
            path = self.preplot_path_var.get().strip()
        except (tk.TclError, AttributeError):
            path = ""
        if not path:
            self._preplot = None
            if self._preplot_status_label:
                self._preplot_status_label.config(text="Not Loaded", fg="gray")
            if for_start:
                tkMessageBox.showerror("Config Error", "Sequence Source is Preplot but no preplot file is set.")
            return False
        if self._preplot is None or self._preplot.get('path') != path:
            if not self.load_preplot(path):
                if for_start:
                    tkMessageBox.showerror("Config Error", "Preplot could not be loaded:\n{}\nSee log.".format(path))
                return False
        if for_start and not self._is_gun_sequence_only():
            has_dither = any(p.get('dither') for p in self._preplot['patterns'].values())
            if not has_dither:
                tkMessageBox.showerror(
                    "Config Error",
                    "Preplot has no jitteringAtIndex dither values.\n"
                    "Tick 'Source Sequence Check Only' or switch Sequence Source to Manual with .dither files.")
                return False
        return True

    def load_preplot(self, filepath):
        data, status = parse_preplot(filepath)
        lbl = getattr(self, '_preplot_status_label', None)
        if data is None:
            self._preplot = None
            if filepath:
                self.log_message("Preplot load failed: {}".format(status), "error")
            if lbl:
                lbl.config(text="Load Err", fg="red")
            return False
        self._preplot = data
        if data.get('multi_pattern'):
            self.log_message(
                "Warn: preplot declares more than one shooting-pattern pair; using {}/{}.".format(
                    data['pat_inc'], data['pat_dec']), "warning")
        ncyc = data['num_srcs']
        self.log_message(
            "Preplot loaded: {} - ref shot {}, cycle length {}, {} sources, "
            "up {} (pattern {}) / down {} (pattern {}), dither {}, {} lines.".format(
                os.path.basename(filepath), data['ref_shot'], data['seq_len'], ncyc,
                ",".join(str(v) for v in data['inc_seq'][:ncyc]), data['pat_inc'],
                ",".join(str(v) for v in data['dec_seq'][:ncyc]), data['pat_dec'],
                "{} values".format(len(data['dither'])) if data.get('dither') else "NONE",
                len(data['line_patterns'])),
            "info")
        self._preplot_crosscheck_key = None
        if not data.get('dither'):
            self.log_message(
                "Warn: preplot has no jitteringAtIndex values; dither QC needs .dither files or "
                "Source Sequence Check Only.", "warning")
        if lbl:
            lbl.config(text="Loaded", fg="blue")
        self._rebuild_source_rows_if_changed()
        return True

    def _format_triple_start_rows(self, starts):
        """'S1=4 S2=4 S3=4' for however many sources the active cycle actually uses."""
        if not starts:
            return "-"
        return " ".join("S{}={}".format(sid, starts[sid]) for sid in sorted(starts))

    def _reset_adaptive_calibration(self):
        self._adaptive_triple_start_row = {1: None, 2: None, 3: None}
        self._adaptive_sp_base = None
        self._adaptive_calibrated = False
        self._adaptive_dither_mismatch_streak = 0

    def _line_identity_tuple(self, line_info):
        """Stable tuple for detecting line-queue changes (new line / new anchor / FSP / direction)."""
        if not line_info:
            return None
        return (
            line_info.get('name'),
            line_info.get('anchored_shot'),
            line_info.get('prod_fsp'),
            line_info.get('upline'),
        )

    def _on_dither_pattern_reference_changed(self):
        self._reset_adaptive_calibration()
        self._adaptive_line_fingerprint = None

    def _parse_all_shot_blocks_in_order(self, output):
        """Parse shot log into ordered list of dicts with shot_number, source_to_fire, applied_dither per NEW SHOT block."""
        if not output:
            return []
        lines = output.splitlines() if isinstance(output, basestring) else output
        lines = list(lines)
        results = []
        n = len(lines)
        i = 0
        while i < n:
            raw = lines[i].strip()
            m_ns = re.search(r'NEW\s+SHOT\s*:?\s*(-?\d+)', raw, re.I)
            if not m_ns:
                i += 1
                continue
            try:
                sn = int(m_ns.group(1))
            except ValueError:
                i += 1
                continue
            block_end = n
            for j in range(i + 1, n):
                if re.search(r'NEW\s+SHOT', lines[j].strip(), re.I):
                    block_end = j
                    break
            block = lines[i:block_end]
            src = None
            for line in block:
                line = line.strip()
                m_sf = re.search(r'Source\s+to\s+fire:\s*.+?\bsrc\s+(\d+)', line, re.I)
                if not m_sf:
                    m_sf = re.search(r'Source\s+To\s+Fire\s*=\s*(\d+)', line, re.I)
                if m_sf:
                    try:
                        src = int(m_sf.group(1))
                        break
                    except ValueError:
                        pass
            shot_data = {'shot_number': sn}
            if src is not None:
                shot_data['source_to_fire'] = src
            shot_data.setdefault('applied_dither', float('nan'))
            self._attach_aimpoint_dither_for_shot(lines, sn, shot_data, quiet=True)
            ad = shot_data.get('applied_dither')
            if src is not None and ad == ad:
                results.append({
                    'shot_number': sn,
                    'source_to_fire': src,
                    'applied_dither': ad,
                })
            i = block_end
        return results

    def _last_n_unique_shots_chronological(self, all_recs, count):
        """Last `count` distinct shotpoints in chronological order (oldest first)."""
        seen = set()
        out = []
        for rec in reversed(all_recs):
            sp = rec['shot_number']
            if sp in seen:
                continue
            seen.add(sp)
            out.append(rec)
            if len(out) >= count:
                break
        out.reverse()
        return out

    def _find_triple_start_in_pattern(self, pat, v1, v2, v3, tol):
        """First row index i where pat[i], pat[i+1], pat[i+2] match v1,v2,v3 within tol. File is top-to-bottom."""
        if not pat or len(pat) < 3:
            return None
        L = len(pat)
        a, b, c = float(v1), float(v2), float(v3)
        for i in range(L - 2):
            try:
                p0 = float(pat[i])
                p1 = float(pat[i + 1])
                p2 = float(pat[i + 2])
            except (ValueError, TypeError, IndexError):
                continue
            if abs(p0 - a) <= tol and abs(p1 - b) <= tol and abs(p2 - c) <= tol:
                return i
        return None

    def _three_sp_consecutive_line_order(self, sp1, sp2, sp3, is_upline, inc):
        """sp1,sp2,sp3 are chronological (oldest shot first). Must match line progression by inc."""
        try:
            a, b, c = int(sp1), int(sp2), int(sp3)
        except (TypeError, ValueError):
            return False
        inc = max(1, int(inc))
        if is_upline:
            return b == a + inc and c == b + inc
        return b == a - inc and c == b - inc

    def _try_adaptive_calibrate(self, line_info, is_upline, shot_log_output):
        """Lock when last 3 consecutive SPs' Trinav dithers match 3 consecutive rows in each source file (top-to-bottom)."""
        if self._get_pattern_ref_mode() != PATTERN_REF_ADAPTIVE:
            return
        if self._adaptive_calibrated:
            return
        all_recs = self._parse_all_shot_blocks_in_order(shot_log_output)
        hist = self._last_n_unique_shots_chronological(all_recs, 3)
        if len(hist) < 3:
            return
        try:
            inc = max(1, int(self.shot_increment_var.get()))
        except (tk.TclError, ValueError):
            inc = 1
        sp1 = hist[0]['shot_number']
        sp2 = hist[1]['shot_number']
        sp3 = hist[2]['shot_number']
        if not self._three_sp_consecutive_line_order(sp1, sp2, sp3, is_upline, inc):
            return
        v1 = hist[0]['applied_dither']
        v2 = hist[1]['applied_dither']
        v3 = hist[2]['applied_dither']
        tol = max(self.float_tolerance, 0.0005)
        new_starts = {}
        for sid in self._active_source_ids():
            pat = self.dither_patterns.get(sid)
            if not pat or not isinstance(pat, list) or len(pat) < 3:
                return
            idx = self._find_triple_start_in_pattern(pat, v1, v2, v3, tol)
            if idx is None:
                return
            new_starts[sid] = idx
        self._adaptive_triple_start_row = new_starts
        self._adaptive_sp_base = int(sp1)
        self._adaptive_calibrated = True
        self.log_message(
            "Adaptive: matched Trinav triple ({:.3f}, {:.3f}, {:.3f}) at SP {}–{} in files (row0 {}); "
            "QC row follows line (file top→bottom); next SP expects row+3 vs triple.".format(
                v1, v2, v3, sp1, sp3, self._format_triple_start_rows(new_starts)),
            "info")

    def get_expected_dither(self, shot_number, is_upline, anchored_shot, line_info):
        """Expected dither from expected source file. Reference: Anchored SP, Production FSP, or Adaptive (triple match in file)."""
        exp_src, src_st = self.get_expected_source(shot_number, anchored_shot, is_upline)
        if src_st != "OK" or exp_src is None:
            return None, "Expected source: {}".format(src_st), None, None, None, None

        mode = self._get_pattern_ref_mode()
        try:
            sn = int(shot_number)
        except (TypeError, ValueError):
            return None, "Invalid shot number", None, None, None, None

        if mode == PATTERN_REF_PREPLOT:
            pp = self._preplot
            if not pp:
                return None, "Preplot not loaded", None, None, None, None
            pid, pat = self._preplot_pattern_for_direction(is_upline)
            dith = pat.get('dither') if pat else None
            if not dith:
                # Fall back to the other direction's jitter only if this pattern has none.
                _opid, opat = self._preplot_pattern_for_direction(not is_upline)
                dith = opat.get('dither') if opat else None
            if not dith:
                return None, "Preplot carries no dither values", None, None, None, None
            pp_len = len(dith)
            ref = pp['ref_shot']
            row_idx = (sn - ref) if is_upline else (ref - sn)
            idx_wrapped = row_idx % pp_len
            try:
                return float(dith[idx_wrapped]), "OK", exp_src, row_idx, idx_wrapped, pp_len
            except (ValueError, TypeError, IndexError) as e:
                self.log_message("Error reading preplot dither [{}]: {}".format(idx_wrapped, e), "error")
                return None, "Preplot dither read error", None, None, None, None

        row_idx = None
        ref_shot = None
        if mode != PATTERN_REF_ADAPTIVE:
            if mode == PATTERN_REF_ANCHORED_SP:
                if anchored_shot is None:
                    return None, "Missing anchored shot (row ref)", None, None, None, None
                try:
                    ref_shot = int(anchored_shot)
                except (TypeError, ValueError):
                    return None, "Invalid anchored shot", None, None, None, None
            else:
                pf = line_info.get('prod_fsp') if line_info else None
                if pf is None:
                    return None, "Missing Prod FSP on anchored line", None, None, None, None
                try:
                    ref_shot = int(pf)
                except (TypeError, ValueError):
                    return None, "Invalid Prod FSP", None, None, None, None
            if is_upline:
                row_idx = sn - ref_shot
            else:
                row_idx = ref_shot - sn

        pattern_key = exp_src
        pattern = self.dither_patterns.get(pattern_key)
        if pattern is None:
            src_conf_dict = self.source_configs.get(exp_src)
            if not src_conf_dict:
                return None, "Config dict missing for S{}".format(exp_src), None, None, None, None
            filepath = ""
            if 'path_var_dither' in src_conf_dict:
                try:
                    filepath = src_conf_dict['path_var_dither'].get()
                except (tk.TclError, AttributeError):
                    filepath = src_conf_dict.get('path_var_dither_value', '')
            else:
                filepath = src_conf_dict.get('path_var_dither_value', '')
            if filepath and os.path.exists(filepath):
                if self.load_dither_pattern(exp_src, filepath):
                    pattern = self.dither_patterns.get(pattern_key)
                else:
                    return None, "Pattern load failed S{}".format(exp_src), None, None, None, None
            else:
                return None, "No dither file S{}".format(exp_src), None, None, None, None

        if pattern is None or not isinstance(pattern, list):
            return None, "Pattern invalid S{}".format(exp_src), None, None, None, None
        L = len(pattern)
        if L == 0:
            return None, "Pattern empty S{}".format(exp_src), None, None, None, None

        if mode == PATTERN_REF_ADAPTIVE:
            if not self._adaptive_calibrated:
                return None, "Adaptive calibrating", None, None, None, None
            start_row = self._adaptive_triple_start_row.get(exp_src)
            sp_base = self._adaptive_sp_base
            if start_row is None or sp_base is None:
                return None, "Adaptive: triple row missing S{}".format(exp_src), None, None, None, None
            delta = (sn - sp_base) if is_upline else (sp_base - sn)
            idx_wrapped = (int(start_row) + int(delta)) % L
            row_idx = int(delta)
        else:
            idx_wrapped = row_idx % L
        try:
            expected_dither = float(pattern[idx_wrapped])
            return expected_dither, "OK", exp_src, row_idx, idx_wrapped, L
        except (ValueError, TypeError, IndexError) as e:
            self.log_message("Error reading pattern S{} [{}]: {}".format(exp_src, idx_wrapped, e), "error")
            return None, "Pattern read error", None, None, None, None

    def get_expected_source(self, shot_number, anchored_shot, is_upline):
        """Expected source for a shotpoint, from whichever sequence source is selected.

        Preplot: idx = (SP - ref) mod L upline, (ref - SP) mod L downline; source = seq[idx].
        Manual:  idx = (SP - anchor) mod len(cycle); source = cycle[idx].
        The manual defaults (up 1,2,3 / down 3,2,1 from SP 1001) reproduce the original
        hardcoded rule exactly, so an existing config behaves as before.
        anchored_shot is unused - the cycle keys off the shot number itself."""
        _ = anchored_shot
        try:
            shot_n = int(shot_number)
        except (TypeError, ValueError):
            return None, "Invalid shot number"

        if self._is_preplot_mode():
            pp = self._preplot
            if not pp:
                return None, "Preplot not loaded"
            pid, pat = self._preplot_pattern_for_direction(is_upline)
            if pat is None:
                return None, "Preplot has no pattern {} for this direction".format(pid)
            seq = pat['seq']
            seq_len = len(seq)
            if seq_len <= 0:
                return None, "Preplot pattern {} sequence empty".format(pid)
            ref = pp['ref_shot']
            idx = (shot_n - ref) % seq_len if is_upline else (ref - shot_n) % seq_len
            try:
                return int(seq[idx]), "OK"
            except (IndexError, ValueError, TypeError):
                return None, "Preplot sequence read error at index {}".format(idx)

        cycle, cyc_st = self._manual_cycle(is_upline)
        if cycle is None:
            return None, cyc_st
        anchor, anc_st = self._manual_anchor()
        if anchor is None:
            return None, anc_st
        idx = (shot_n - anchor) % len(cycle)
        return int(cycle[idx]), "OK"

    def check_first_dither_row_matches_reference(self, line_info):
        """Anchored SP: row0 = dither at anchor; Production FSP / Adaptive: alignment check N/A here."""
        mode = self._get_pattern_ref_mode()
        if mode == PATTERN_REF_PREPLOT:
            return True, "N/A (preplot supplies the reference shot)", "Preplot"
        if mode == PATTERN_REF_ADAPTIVE:
            return True, "N/A (Adaptive)", "Adaptive"
        if mode == PATTERN_REF_PRODUCTION_FSP:
            return True, "N/A (FSP ref for row index)", "Prod FSP"

        anc = line_info.get('anchored_shot')
        if anc is None:
            return False, "no anchored shot", "anchor SP"
        try:
            int(anc)
        except (TypeError, ValueError):
            return False, "invalid anchored shot", "anchor SP"

        bad = []
        for sid in self._active_source_ids():
            pat = self.dither_patterns.get(sid)
            if pat is None or not isinstance(pat, list) or len(pat) < 1:
                bad.append("S{}: not loaded".format(sid))

        if bad:
            return False, "; ".join(bad), "anchor SP"
        return True, "OK (row0 = dither at anchor SP; cells are values not SP#)", "anchor SP"

    def _pattern_index_ref_in_use_text(self, line_info, gun_only):
        """Human-readable label: which reference indexes rows in the .dither files."""
        if gun_only:
            return "Pattern Index Ref in Use: — (gun sequence only)"
        mode = self._get_pattern_ref_mode()
        if mode == PATTERN_REF_PREPLOT:
            pp = self._preplot
            if pp:
                return "Pattern Index Ref in Use: Preplot ref shot {} (cycle {} SPs)".format(
                    pp['ref_shot'], pp['seq_len'])
            return "Pattern Index Ref in Use: Preplot - (not loaded)"
        if mode == PATTERN_REF_ADAPTIVE:
            if self._adaptive_calibrated:
                return "Pattern Index Ref in Use: Adaptive (locked; triple starts at file row {})".format(
                    self._format_triple_start_rows(self._adaptive_triple_start_row))
            return "Pattern Index Ref in Use: Adaptive (calibrating — need 3 consecutive SPs with Trinav dither in log)"
        if mode == PATTERN_REF_ANCHORED_SP:
            anc = line_info.get('anchored_shot') if line_info else None
            if anc is not None:
                return "Pattern Index Ref in Use: Anchor SP {}".format(anc)
            return "Pattern Index Ref in Use: Anchor SP — (missing)"
        pf = line_info.get('prod_fsp') if line_info else None
        if pf is not None:
            return "Pattern Index Ref in Use: Production FSP {}".format(pf)
        return "Pattern Index Ref in Use: Production FSP — (missing)"

    def _is_gun_sequence_only(self):
        try:
            return int(self.gun_sequence_only_var.get()) != 0
        except (tk.TclError, ValueError):
            return False

    def perform_check(self):
        """Timer entry point. Whatever happens inside, the loop is re-armed while running."""
        if not self.running:
            return
        if self.timer_id:
            # We are the running tick: drop any stale pending one so two chains can never coexist.
            try:
                self.root.after_cancel(self.timer_id)
            except tk.TclError:
                pass
            self.timer_id = None
        try:
            self._perform_check_inner()
        except Exception as e:
            tb = traceback.format_exc().strip().splitlines()
            self.log_message("Internal error in check loop: {!r} ({}) - continuing.".format(e, tb[-2].strip() if len(tb) > 1 else "?"), "error")
            try:
                self.status_label_text.set("Error: internal - retrying"); self.status_label.config(fg="red")
            except tk.TclError:
                pass
            if self.running and self.timer_id is None:
                self.timer_id = self.root.after(self.default_retry_interval_ms, self.perform_check)

    def _perform_check_inner(self):
        if not self.running: return
        gun_only = self._is_gun_sequence_only()
        line_info_output = self.run_command(self.lineque_cmd); line_info = self.parse_lineque_output(line_info_output)
        if not line_info:
             if self.current_line_info: self.log_message("Warn: Failed to get line info, using cached.", "warning"); line_info = self.current_line_info
             else: self.log_message("Error: Failed to get line info. Retrying...", "error"); self.status_label_text.set("Error: Check Line Info"); self.status_label.config(fg="red"); self._reset_in_use_labels(); self.timer_id = self.root.after(self.default_retry_interval_ms, self.perform_check); return
        else: self.current_line_info = line_info
        if self._get_pattern_ref_mode() == PATTERN_REF_ADAPTIVE and self._adaptive_calibrated:
            fp = self._line_identity_tuple(line_info)
            if fp is not None and self._adaptive_line_fingerprint is not None and fp != self._adaptive_line_fingerprint:
                self._reset_adaptive_calibration()
                self.log_message(
                    "Adaptive: line queue changed (line / anchor / Prod FSP / direction); alignment cleared. Will re-lock when a new triple matches.",
                    "warning")
        if line_info:
            self._adaptive_line_fingerprint = self._line_identity_tuple(line_info)
        self._apply_parsed_lineque_to_param_display(line_info)
        self._update_shotpoint_check_source()
        if self._is_preplot_mode():
            self._preplot_crosscheck(line_info)
        is_upline = line_info.get('upline') == 1; direction_str = "Upline" if is_upline else "Downline"; anchored_shot = line_info.get('anchored_shot', None); line_name = line_info.get('name', 'N/A')
        if anchored_shot is None: self.log_message("Error: Missing Anchor SP info.", "error"); self.status_label_text.set("Error: Missing Anchor SP"); self.status_label.config(fg="red"); self._reset_in_use_labels(); self.timer_id = self.root.after(self.default_retry_interval_ms, self.perform_check); return
        tail_lines = 120 if (not gun_only and self._get_pattern_ref_mode() == PATTERN_REF_ADAPTIVE) else 20
        shot_log_output = self._fetch_shotcontroller_log_tail(tail_lines)
        shot_info = self.parse_shotcontroller_log(shot_log_output); next_interval_ms = self.default_retry_interval_ms
        if not shot_info: self.log_message("Error: Failed to get shot info from log. Retrying...", "error"); self.status_label_text.set("Error: Check Shot Log"); self.status_label.config(fg="red"); self._reset_in_use_labels(); self.timer_id = self.root.after(next_interval_ms, self.perform_check); return
        else: interval_s = shot_info.get('interval', float(self.default_retry_interval_ms / 1000.0)); next_interval_ms = max(500, int(interval_s * 1000) - self.loop_buffer_ms)
        source_fired = shot_info.get('source_to_fire', -1); shot_num = shot_info.get('shot_number', -1); applied_dither = shot_info.get('applied_dither', float('nan'))
        if source_fired == -1 or shot_num == -1:
            self.log_message("Error: Incomplete shot info from log.", "error")
            self.status_label_text.set("Error: Incomplete Shot Log")
            self.status_label.config(fg="red")
            self._reset_in_use_labels()
            self.timer_id = self.root.after(next_interval_ms, self.perform_check)
            return
        if not gun_only and applied_dither != applied_dither:
            self.log_message("Error: Incomplete shot info from log.", "error")
            self.status_label_text.set("Error: Incomplete Shot Log")
            self.status_label.config(fg="red")
            self._reset_in_use_labels()
            self.timer_id = self.root.after(next_interval_ms, self.perform_check)
            return

        if gun_only:
            dither_match = True
            dither_file_val_str = "— (disabled, gun sequence only)"
            dither_check_status_str = "OFF"
            self._update_in_use_labels(source_fired)
        else:
            if self._get_pattern_ref_mode() == PATTERN_REF_ADAPTIVE:
                self._try_adaptive_calibrate(line_info, is_upline, shot_log_output)
            expected_dither, dither_status, dither_src, row_from_ref, file_row_idx, pat_len = self.get_expected_dither(
                shot_num, is_upline, anchored_shot, line_info)
            self._update_in_use_labels(dither_src if dither_src is not None else source_fired)
            dither_match = False
            dither_file_val_str = "N/A"
            dither_check_status_str = "ERROR ({})".format(dither_status)
            if dither_status == "Adaptive calibrating":
                dither_file_val_str = "— (Adaptive calibrating)"
                dither_check_status_str = "WAIT"
                dither_match = True
            elif dither_status == "OK" and expected_dither is not None:
                dither_file_val_str = "{:.3f}".format(expected_dither)
                if row_from_ref is not None and dither_src is not None and file_row_idx is not None and pat_len:
                    if self._get_pattern_ref_mode() == PATTERN_REF_PREPLOT:
                        # row_from_ref is (ref-SP) on a downline; show plain shots-from-ref.
                        extra = " (S{}, {} shots from ref {} -> preplot index {} of {})".format(
                            dither_src, abs(row_from_ref), self._preplot['ref_shot'] if self._preplot else '?',
                            file_row_idx, pat_len)
                    else:
                        extra = " (S{}, step {} -> file line {} of {})".format(
                            dither_src, row_from_ref, file_row_idx + 1, pat_len)
                    if row_from_ref >= pat_len:
                        extra += " [wrap/repeat]"
                    dither_file_val_str += extra
                if abs(applied_dither - expected_dither) < self.float_tolerance:
                    dither_match = True
                    dither_check_status_str = "OK"
                else:
                    dither_check_status_str = "MISMATCH"
            if self._get_pattern_ref_mode() == PATTERN_REF_ADAPTIVE:
                if dither_status == "Adaptive calibrating" or dither_check_status_str == "WAIT":
                    self._adaptive_dither_mismatch_streak = 0
                elif dither_status == "OK" and expected_dither is not None:
                    if dither_match:
                        self._adaptive_dither_mismatch_streak = 0
                    elif dither_check_status_str == "MISMATCH" and self._adaptive_calibrated:
                        self._adaptive_dither_mismatch_streak += 1
                        if self._adaptive_dither_mismatch_streak >= ADAPTIVE_MISMATCH_STREAK_TO_RESET:
                            self.log_message(
                                "Adaptive: {} consecutive dither mismatches; alignment cleared. Re-searching for a triple match in the log.".format(
                                    ADAPTIVE_MISMATCH_STREAK_TO_RESET),
                                "warning")
                            self._reset_adaptive_calibration()
                else:
                    self._adaptive_dither_mismatch_streak = 0
        expected_source, fs_status = self.get_expected_source(shot_num, anchored_shot, is_upline); fs_match = False; fs_check_str = "ERROR ({})".format(fs_status)
        if fs_status == "OK" and expected_source is not None:
             if expected_source == source_fired: fs_match = True; fs_check_str = "OK (S{})".format(source_fired)
             else: fs_check_str = "MISMATCH (Exp: S{}, Got: S{})".format(expected_source, source_fired)
        if gun_only:
            first_row_ok = True
            first_row_msg = "N/A (gun sequence only)"
        else:
            first_row_ok, first_row_msg, _ = self.check_first_dither_row_matches_reference(line_info)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, "SP: {} ".format(shot_num), "heading")
        self.log_text.insert(tk.END, "(Line: {}, Dir: {}, Anchor: {})\n".format(line_name, direction_str, anchored_shot), "info")
        if gun_only:
            if applied_dither == applied_dither:
                self.log_text.insert(tk.END, "  Trinav Applied Dither: {:.3f} (not compared)\n".format(applied_dither))
            else:
                self.log_text.insert(tk.END, "  Trinav Applied Dither: — (not compared)\n")
        else:
            self.log_text.insert(tk.END, "  Trinav Applied Dither: {:.3f}\n".format(applied_dither))
        self.log_text.insert(tk.END, "  Dither from {}: {} ".format(
            "Preplot" if self._get_pattern_ref_mode() == PATTERN_REF_PREPLOT else "File", dither_file_val_str))
        if dither_check_status_str == "WAIT":
            _dither_tag = "info"
        elif dither_match:
            _dither_tag = "ok"
        else:
            _dither_tag = "error"
        self.log_text.insert(tk.END, "({})".format(dither_check_status_str) + "\n", _dither_tag)
        self.log_text.insert(tk.END, "  {}\n".format(self._pattern_index_ref_in_use_text(line_info, gun_only)), "info")
        if not gun_only and not first_row_ok:
            self.log_text.insert(tk.END, "  Pattern alignment: ")
            self.log_text.insert(tk.END, "{}\n".format(first_row_msg), "error")
        self.log_text.insert(tk.END, "  Expected Source Check: ")
        self.log_text.insert(tk.END, "{}\n".format(fs_check_str), "ok" if fs_match else "error")
        self.log_text.insert(tk.END, "------------------------------------\n", "separator")
        self.log_text.see(tk.END); self.log_text.config(state=tk.DISABLED)
        adaptive_waiting = (not gun_only and self._get_pattern_ref_mode() == PATTERN_REF_ADAPTIVE and not self._adaptive_calibrated)
        all_ok = fs_match if gun_only else (dither_match and fs_match and first_row_ok and not adaptive_waiting)
        if adaptive_waiting and fs_match:
            self.status_label_text.set("SP: {} Adaptive: calibrating...".format(shot_num))
            self.status_label.config(fg="blue")
        elif all_ok:
            status_msg = "SP: {} SRC Sequence OK".format(shot_num) if gun_only else "SP: {} SRC Sequence/Dither OK".format(shot_num)
            self.status_label_text.set(status_msg)
            self.status_label.config(fg="green")
        else:
            fail_reason = []
            if not gun_only:
                if not dither_match:
                    if "MISMATCH" in dither_check_status_str:
                        fail_reason.append("Dither MISMATCH")
                    elif dither_check_status_str != "WAIT":
                        fail_reason.append("Dither ERROR")
            if not fs_match:
                if fs_status == "OK" and expected_source is not None:
                    fail_reason.append("Source Sequence MISMATCH")
                else:
                    fail_reason.append("Source Sequence ERROR")
            if not gun_only and not first_row_ok:
                fail_reason.append("Pattern alignment MISMATCH")
            status_msg = "SP: {} QC FAIL: {}".format(shot_num, ", ".join(fail_reason))
            self.status_label_text.set(status_msg); self.status_label.config(fg="red")
        self._trim_log()
        if self.running: self.timer_id = self.root.after(next_interval_ms, self.perform_check)

    def _reset_in_use_labels(self):
        status_font_normal = tkFont.Font(family='TkDefaultFont', size=self.small_font_size, weight='normal')
        if hasattr(self, 'source_configs'):
            for config_dict in self.source_configs.values():
                if isinstance(config_dict, dict):
                    lbl = config_dict.get('status_label_dither')
                    if lbl:
                        lbl.config(text="Not Loaded", fg="gray", font=status_font_normal)

    def _update_in_use_labels(self, highlight_source_id):
        status_font_bold = tkFont.Font(family='TkDefaultFont', size=self.small_font_size, weight='bold')
        status_font_normal = tkFont.Font(family='TkDefaultFont', size=self.small_font_size, weight='normal')
        if hasattr(self, 'source_configs'):
            for src_id, config_dict in self.source_configs.items():
                if isinstance(config_dict, dict):
                    label_widget = config_dict.get('status_label_dither')
                    if not label_widget:
                        continue
                    pattern_val = self.dither_patterns.get(src_id, "Not Found")
                    current_status = "Load Err" if pattern_val is None else ("Loaded" if isinstance(pattern_val, list) else "Not Loaded")
                    current_color = "red" if current_status == "Load Err" else ("blue" if current_status == "Loaded" else "gray")
                    label_widget.config(text=current_status, fg=current_color, font=status_font_normal)
                    if src_id == highlight_source_id:
                        label_widget.config(text="In USE", fg="green", font=status_font_bold)

    def start_checking(self):
        if self.running:
            return
        self._rebuild_source_rows_if_changed()
        patterns_ok = True
        files_missing = False
        if self._is_preplot_mode():
            if not self._ensure_preplot_current(for_start=True):
                return
        elif not self._is_gun_sequence_only():
            for i in self._active_source_ids():
                src_conf_dict = self.source_configs.get(i)
                if not src_conf_dict:
                    patterns_ok = False
                    files_missing = True
                    self.log_message("Error: no dither file row for Source {} named in the sequence.".format(i), "error")
                    continue
                path_d = src_conf_dict['path_var_dither'].get() if 'path_var_dither' in src_conf_dict else src_conf_dict.get('path_var_dither_value', '')
                if not path_d:
                    files_missing = True
                    patterns_ok = False
                    continue
                if not self.load_dither_pattern(i, path_d):
                    patterns_ok = False
            if files_missing:
                tkMessageBox.showerror("Config Error", "One or more sources missing dither file path.")
            elif not patterns_ok:
                tkMessageBox.showerror("Config Error", "Failed to load one or more dither files. Check paths/logs.")
            if not patterns_ok:
                return
        self._reset_adaptive_calibration()
        self._adaptive_line_fingerprint = None
        self.running = True
        self.start_button.config(state=tk.DISABLED, bg=self.color_disabled_bg if self.color_disabled_bg else self.color_button_bg )
        self.stop_button.config(state=tk.NORMAL, bg=self.color_button_bg)
        if self.params_frame: self.params_frame.pack_forget()
        self.log_message("Starting {}...".format("Source Sequence check" if self._is_gun_sequence_only() else "Source/Dither check"), "info")
        self.status_label_text.set("Starting...")
        self.status_label_text.set("Starting...")
        self.status_label.config(fg="blue")
        self.current_line_info = {}; self._reset_in_use_labels(); self.perform_check()

    def stop_checking(self):
        if not self.running: return
        self.running = False
        if self.timer_id: self.root.after_cancel(self.timer_id); self.timer_id = None
        self.start_button.config(state=tk.NORMAL, bg=self.color_button_bg)
        self.stop_button.config(state=tk.DISABLED, bg=self.color_disabled_bg if self.color_disabled_bg else self.color_button_bg)
        if self.params_frame:
            # before=rt_frame keeps the log as the lowest-priority block, so a short window
            # squeezes the log and never the Start/Stop buttons.
            try:
                self.params_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5, before=self._rt_frame)
            except (tk.TclError, AttributeError):
                self.params_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        self._reset_in_use_labels()
        self.log_message("Source/Dither check stopped.", "info")
        self.status_label_text.set("Stopped")
        self.status_label.config(fg="gray")
        self.refresh_params_from_system()

    def _config_entry_is_filename_only(self, name):
        """True if the entry is a single path component (e.g. mycopy.xcfg), not a relative/absolute path."""
        if not name or not name.strip():
            return False
        n = os.path.normpath(name.strip())
        if os.path.isabs(n):
            return False
        return os.path.dirname(n) == ''

    def _get_current_config_path(self):
        config_name_from_var = self.config_name_var.get()
        if not config_name_from_var: config_name_from_var = self.default_config_name; self.config_name_var.set(config_name_from_var)
        config_name_from_var = config_name_from_var.strip()
        if self.config_full_path and os.path.basename(self.config_full_path).lower() == config_name_from_var.lower():
            dir_part = os.path.dirname(self.config_full_path)
            if dir_part and os.path.isdir(dir_part): return self.config_full_path
        # Typing a new basename only: save next to the current config when possible (Save As by name).
        if self.config_full_path and self._config_entry_is_filename_only(config_name_from_var):
            parent_dir = os.path.dirname(self.config_full_path)
            if parent_dir and os.path.isdir(parent_dir):
                return os.path.normpath(os.path.join(parent_dir, config_name_from_var))
        if not os.path.exists(self.default_config_dir):
            try: os.makedirs(self.default_config_dir); self.log_message("Created default config directory: {}".format(self.default_config_dir), "info")
            except OSError as e: self.log_message("Error creating default config dir {}: {}. Path may be relative.".format(self.default_config_dir, e), "error")
        constructed_path = os.path.join(self.default_config_dir, config_name_from_var)
        return os.path.normpath(constructed_path)

    def save_config(self):
        config_parser = ConfigParser.RawConfigParser(dict_type=OrderedDict)
        save_path = self._get_current_config_path()
        if not save_path: tkMessageBox.showwarning("Save Warning", "Cannot determine config path to save."); return
        try:
            config_parser.add_section('General')
            config_parser.set('General', 'num_sources', SOURCE_CYCLE_COUNT)
            config_parser.set('General', 'shot_increment', self.shot_increment_var.get())
            try:
                config_parser.set('General', 'geometry', self.root.geometry())
            except tk.TclError:
                config_parser.set('General', 'geometry', '')
            try:
                config_parser.set('General', 'dither_pattern_reference', self._get_pattern_ref_mode())
            except tk.TclError:
                config_parser.set('General', 'dither_pattern_reference', PATTERN_REF_ANCHORED_SP)
            pm = self._get_pattern_ref_mode()
            config_parser.set('General', 'pattern_first_row_use_anchor', '1' if pm == PATTERN_REF_ANCHORED_SP else '0')
            try:
                config_parser.set('General', 'gun_sequence_only', 1 if self.gun_sequence_only_var.get() else 0)
            except tk.TclError:
                config_parser.set('General', 'gun_sequence_only', '0')
            for _key, _var, _fallback in (
                    ('sequence_source', 'seq_source_var', SEQ_SOURCE_MANUAL),
                    ('preplot_file', 'preplot_path_var', ''),
                    ('postplot_file', 'postplot_path_var', ''),
                    ('up_sequence', 'up_sequence_var', DEFAULT_UP_SEQUENCE),
                    ('down_sequence', 'down_sequence_var', DEFAULT_DOWN_SEQUENCE),
                    ('sequence_anchor_sp', 'seq_anchor_var', str(SOURCE_CYCLE_ANCHOR_SP))):
                try:
                    config_parser.set('General', _key, getattr(self, _var).get())
                except (tk.TclError, AttributeError):
                    config_parser.set('General', _key, _fallback)
            if hasattr(self, 'source_configs'):
                for source_id, src_config_dict in self.source_configs.items():
                    if isinstance(src_config_dict, dict):
                        section = 'Source_{}'.format(source_id)
                        config_parser.add_section(section)
                        path_to_save = src_config_dict.get('path_var_dither_value', '')
                        if 'path_var_dither' in src_config_dict:
                            try:
                                path_to_save = src_config_dict['path_var_dither'].get()
                            except (tk.TclError, AttributeError):
                                pass
                        config_parser.set(section, 'dither_file', path_to_save)
            config_dir = os.path.dirname(save_path)
            if config_dir and not os.path.exists(config_dir):
                 try: os.makedirs(config_dir)
                 except OSError as e: tkMessageBox.showerror("Save Error", "Could not create directory:\n{}".format(e)); return
            with open(save_path, 'wb') as configfile_to_write: config_parser.write(configfile_to_write)
            self.log_message("Configuration saved to {}".format(save_path), "info")
            self.config_full_path = save_path
            default_cfg_file_path = os.path.join(self.default_config_dir, self.default_config_name)
            default_cfg_dir = os.path.dirname(default_cfg_file_path)
            if default_cfg_dir and not os.path.exists(default_cfg_dir):
                try: os.makedirs(default_cfg_dir)
                except OSError as e: self.log_message("Error creating dir for default config pointer: {}".format(e), "error")
            persistent_settings = ConfigParser.RawConfigParser(dict_type=OrderedDict)
            if os.path.exists(default_cfg_file_path) and os.path.getsize(default_cfg_file_path) > 0:
                try:
                    read_files = persistent_settings.read(default_cfg_file_path)
                    if not read_files: self.log_message("Warning: Default config {} existed but read() failed.".format(default_cfg_file_path), "warning")
                except ConfigParser.Error as e_read_default: self.log_message("Warning: Could not parse default config {} to update last_path: {}. Will overwrite.".format(default_cfg_file_path, e_read_default), "warning")
            if not persistent_settings.has_section('General'): persistent_settings.add_section('General')
            persistent_settings.set('General', 'last_config_path', save_path)
            try:
                with open(default_cfg_file_path, 'wb') as p_cfg_file: persistent_settings.write(p_cfg_file)
            except IOError as e_write_pointer: self.log_message("Error writing last_config_path to default config {}: {}".format(default_cfg_file_path, e_write_pointer), "error")
        except (IOError, OSError, ConfigParser.Error, tk.TclError, ValueError) as e_save: tkMessageBox.showerror("Save Error", "Could not save config to {}:\n{}".format(save_path, e_save)); self.log_message("Save Error for {}: {}".format(save_path, e_save), "error")
        except Exception as e_unexp_save: tkMessageBox.showerror("Save Error", "Unexpected error saving config to {}:\n{}".format(save_path, e_unexp_save)); self.log_message("Unexpected save error for {}: {}".format(save_path, e_unexp_save), "error")

    def load_config(self, filepath_to_load=None):
        config_parser_obj = ConfigParser.RawConfigParser(dict_type=OrderedDict)
        config_successfully_parsed = False; path_that_was_read = None
        determined_path_to_try = None; is_explicit_load_request = bool(filepath_to_load)
        if is_explicit_load_request:
            if not filepath_to_load:
                self.log_message("Error: No path given for load.", "error")
                return
            fp_norm = os.path.normpath(filepath_to_load)
            if os.path.exists(fp_norm) and os.path.getsize(fp_norm) > 0:
                determined_path_to_try = fp_norm
            else:
                # New path (Save As) or empty file: set target; keep current UI — Save will create the file.
                self.config_full_path = fp_norm
                self.config_name_var.set(os.path.basename(fp_norm))
                self.log_message(
                    "Config file not found or empty: '{}'. Target set; use Save to write it.".format(fp_norm),
                    "info")
                return
        else:
            default_cfg_full_path = os.path.join(self.default_config_dir, self.default_config_name)
            pointer_config_reader = ConfigParser.RawConfigParser(); last_path_from_pointer = None
            if os.path.exists(default_cfg_full_path) and os.path.getsize(default_cfg_full_path) > 0:
                try:
                    if pointer_config_reader.read(default_cfg_full_path) and pointer_config_reader.has_section('General') and pointer_config_reader.has_option('General', 'last_config_path'):
                        last_path_from_pointer = pointer_config_reader.get('General', 'last_config_path')
                except Exception as e_read_ptr: self.log_message("Warn: Error reading last_config_path from {}: {}".format(default_cfg_full_path, e_read_ptr), "warning")
            if last_path_from_pointer and os.path.exists(last_path_from_pointer) and os.path.getsize(last_path_from_pointer) > 0: determined_path_to_try = last_path_from_pointer
            else:
                if last_path_from_pointer: self.log_message("Warn: last_config_path '{}' (from default file) invalid. Falling back.".format(last_path_from_pointer), "warning")
                determined_path_to_try = default_cfg_full_path
        if determined_path_to_try and os.path.exists(determined_path_to_try) and os.path.getsize(determined_path_to_try) > 0:
            try:
                files_read_by_parser = config_parser_obj.read(determined_path_to_try)
                if files_read_by_parser: config_successfully_parsed = True; path_that_was_read = determined_path_to_try
                else: self.log_message("Warn: ConfigParser.read returned empty for {}".format(determined_path_to_try), "warning")
            except (ConfigParser.Error, IOError) as e_parse: msg_detail = "Could not read/parse config {}:\n{}".format(determined_path_to_try, e_parse); tkMessageBox.showerror("Load Error", msg_detail); self.log_message(msg_detail, "error");
            except Exception as e_unexp_parse: msg_detail = "Unexpected error reading/parsing config {}:\n{}".format(determined_path_to_try, e_unexp_parse); tkMessageBox.showerror("Load Error", msg_detail); self.log_message(msg_detail, "error");
            if not config_successfully_parsed and is_explicit_load_request: return
        else:
            if determined_path_to_try: self.log_message("Config file not found or empty: '{}'. Applying defaults (if startup).".format(determined_path_to_try), "info")

        if config_successfully_parsed and path_that_was_read:
            self.log_message("Applying configuration from: {}".format(path_that_was_read), "info")
            self.dither_patterns.clear(); self._reset_in_use_labels()
            try:
                self.num_sources.set(SOURCE_CYCLE_COUNT)
                self._build_ui_elements()
                if config_parser_obj.has_section('General'):
                    if config_parser_obj.has_option('General', 'shot_increment'):
                        try:
                            self.shot_increment_var.set(max(1, config_parser_obj.getint('General', 'shot_increment')))
                        except ValueError:
                            self.log_message("Warn: Invalid 'shot_increment'. Using 1.", "warning")
                            self.shot_increment_var.set(1)
                    if config_parser_obj.has_option('General', 'geometry'):
                        loaded_geometry = config_parser_obj.get('General', 'geometry')
                        if loaded_geometry and re.match(r"^\d+x\d+[+-]\d+[+-]\d+$", loaded_geometry):
                            try:
                                self.root.geometry(loaded_geometry)
                            except tk.TclError as e_geom:
                                self.log_message("Warn: Could not apply geometry '{}': {}".format(loaded_geometry, e_geom), "warning")
                    if config_parser_obj.has_option('General', 'dither_pattern_reference'):
                        dr = config_parser_obj.get('General', 'dither_pattern_reference').strip()
                        if dr in PATTERN_REF_CHOICES:
                            self.dither_pattern_reference_var.set(dr)
                    elif config_parser_obj.has_option('General', 'pattern_first_row_use_anchor'):
                        try:
                            v = config_parser_obj.getint('General', 'pattern_first_row_use_anchor')
                            self.dither_pattern_reference_var.set(
                                PATTERN_REF_ANCHORED_SP if v else PATTERN_REF_PRODUCTION_FSP)
                        except ValueError:
                            pass
                    if config_parser_obj.has_option('General', 'gun_sequence_only'):
                        try:
                            g = config_parser_obj.getint('General', 'gun_sequence_only')
                            self.gun_sequence_only_var.set(1 if g else 0)
                        except ValueError:
                            pass
                    # Sequence inputs first, source last: the trace on sequence_source
                    # loads the preplot and regreys the widgets once everything is in place.
                    for _key, _var, _default in (
                            ('up_sequence', self.up_sequence_var, DEFAULT_UP_SEQUENCE),
                            ('down_sequence', self.down_sequence_var, DEFAULT_DOWN_SEQUENCE),
                            ('sequence_anchor_sp', self.seq_anchor_var, str(SOURCE_CYCLE_ANCHOR_SP)),
                            ('preplot_file', self.preplot_path_var, ''),
                            ('postplot_file', self.postplot_path_var, '')):
                        if config_parser_obj.has_option('General', _key):
                            _var.set(config_parser_obj.get('General', _key).strip())
                        else:
                            _var.set(_default)
                    if config_parser_obj.has_option('General', 'sequence_source'):
                        _ss = config_parser_obj.get('General', 'sequence_source').strip()
                        self.seq_source_var.set(_ss if _ss in SEQ_SOURCE_CHOICES else SEQ_SOURCE_MANUAL)
                    else:
                        self.seq_source_var.set(SEQ_SOURCE_MANUAL)
                    self._rebuild_source_rows_if_changed()

                for sid_iterator in sorted(self.source_configs.keys()):
                    section_name_in_cfg = 'Source_{}'.format(sid_iterator)
                    src_dict_in_app = self.source_configs.get(sid_iterator)
                    if not src_dict_in_app:
                        continue
                    if not config_parser_obj.has_section(section_name_in_cfg):
                        continue
                    path_cfg = ''
                    if config_parser_obj.has_option(section_name_in_cfg, 'dither_file'):
                        path_cfg = config_parser_obj.get(section_name_in_cfg, 'dither_file')
                    elif config_parser_obj.has_option(section_name_in_cfg, 'file_is_anchor_source'):
                        path_cfg = config_parser_obj.get(section_name_in_cfg, 'file_is_anchor_source')
                    elif config_parser_obj.has_option(section_name_in_cfg, 'file_not_anchor_source'):
                        path_cfg = config_parser_obj.get(section_name_in_cfg, 'file_not_anchor_source')
                    if 'path_var_dither' in src_dict_in_app:
                        src_dict_in_app['path_var_dither'].set(path_cfg)
                    src_dict_in_app['path_var_dither_value'] = path_cfg
                    if path_cfg:
                        self.load_dither_pattern(sid_iterator, path_cfg)
                self.config_full_path = path_that_was_read
                self.config_name_var.set(os.path.basename(path_that_was_read))
                self.log_message("Config loaded from: {}".format(path_that_was_read), "info")
                default_cfg_pointer_path = os.path.join(self.default_config_dir, self.default_config_name)
                pointer_cfg_to_write = ConfigParser.RawConfigParser(dict_type=OrderedDict)
                if os.path.exists(default_cfg_pointer_path) and os.path.getsize(default_cfg_pointer_path) > 0:
                    try: pointer_cfg_to_write.read(default_cfg_pointer_path)
                    except: pass
                if not pointer_cfg_to_write.has_section('General'): pointer_cfg_to_write.add_section('General')
                pointer_cfg_to_write.set('General', 'last_config_path', path_that_was_read)
                try:
                    with open(default_cfg_pointer_path, 'wb') as p_cfg_file_write: pointer_cfg_to_write.write(p_cfg_file_write)
                except IOError as e_ptr_write: self.log_message("Error updating last_config_path in {}: {}".format(default_cfg_pointer_path, e_ptr_write), "error")
                self.refresh_params_from_system()
            except Exception as e_apply_settings: tkMessageBox.showerror("Apply Settings Error", "Error applying settings from {}:\n{}".format(path_that_was_read, e_apply_settings)); self.log_message("Error applying settings from {}: {}".format(path_that_was_read, e_apply_settings), "error")
        else:
            if not is_explicit_load_request:
                self.log_message("No config loaded. Applying internal defaults.", "info")
                self.config_full_path = os.path.join(self.default_config_dir, self.default_config_name)
                self.config_name_var.set(self.default_config_name)
                self.num_sources.set(SOURCE_CYCLE_COUNT)
                self.shot_increment_var.set(1)
                self.dither_patterns.clear()
                self._preplot = None
                self.up_sequence_var.set(DEFAULT_UP_SEQUENCE)
                self.down_sequence_var.set(DEFAULT_DOWN_SEQUENCE)
                self.seq_anchor_var.set(str(SOURCE_CYCLE_ANCHOR_SP))
                self.preplot_path_var.set("")
                self.seq_source_var.set(SEQ_SOURCE_MANUAL)
                self._build_ui_elements()
                self._reset_in_use_labels()
                self.refresh_params_from_system()

    def on_closing(self):
        if self.running: self.stop_checking()
        self.log_message("Saving configuration on exit...", "info")
        self.save_config()
        self.root.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    app = xSourceDitherQCApp(root)
    root.mainloop()