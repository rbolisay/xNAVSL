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
# - Three sources; one "Dither File to Use" per source. Expected source: (SP - SOURCE_CYCLE_ANCHOR_SP) % 3 + direction rule.
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

# --- Check Python Version ---
if sys.version_info[0] != 2 or sys.version_info[1] != 7:
     try: root_check = tk.Tk(); root_check.withdraw(); tkMessageBox.showerror("Version Error", "This script requires Python 2.7."); root_check.destroy()
     except tk.TclError: print "Error: This script requires Python 2.7."
     sys.exit(1)

SOURCE_CYCLE_ANCHOR_SP = 1001
SOURCE_CYCLE_COUNT = 3

PATTERN_REF_ANCHORED_SP = "Anchored SP"
PATTERN_REF_PRODUCTION_FSP = "Production FSP"
PATTERN_REF_ADAPTIVE = "Adaptive"
PATTERN_REF_CHOICES = (PATTERN_REF_ANCHORED_SP, PATTERN_REF_PRODUCTION_FSP, PATTERN_REF_ADAPTIVE)

# Adaptive: after this many consecutive dither MISMATCHes while locked, clear alignment and re-search the file/log.
ADAPTIVE_MISMATCH_STREAK_TO_RESET = 3

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
        self.default_config_dir = '/usr/local/trinop/dbase/links/qcfiles/Misc/xDitherQC/'
        self.default_config_name = 'xDitherQC.xcfg';
        self.config_full_path = os.path.join(self.default_config_dir, self.default_config_name)
        self.log_file_path = '/usr/local/trinop/naverror/shotcontroller.log'
        self.lineque_cmd = 'ex_lineque -print'
        self.log_tail_cmd = 'tail -20 {}'.format(self.log_file_path)
        self.float_tolerance = 0.001; self.default_retry_interval_ms = 5000; self.loop_buffer_ms = 500; self.default_dither_dir = '/usr/local/trinop/dbase/links/qcfiles/Dither'

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

        self.params_frame = tk.LabelFrame(self.root, text="Source and Dither Parameters",
                                          bg=self.color_blue_aura_bg, fg=self.color_label_frame_fg, font=self.heading_font)
        self.params_frame.pack(fill=tk.X, padx=5, pady=5)

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
        tk.Label(gun_row, text="Source Sequence Check Only(Disable Dither QC)", bg=self.color_blue_aura_bg, fg=self.color_text_dark,
                 font=self.results_font, anchor='w').pack(side=tk.LEFT)
        tk.Checkbutton(
            gun_row, text="",
            variable=self.gun_sequence_only_var,
            bg=self.color_blue_aura_bg, fg=self.color_text_dark, activebackground=self.color_blue_aura_bg,
            selectcolor=self.color_entry_bg, anchor='w',
            font=self.results_font).pack(side=tk.LEFT, padx=(10, 0))

        tk.Frame(self.params_frame, height=2, bd=1, relief=tk.SUNKEN, bg=self.color_blue_aura_bg).pack(fill=tk.X, pady=5)
        self.sources_area = tk.Frame(self.params_frame, bg=self.color_blue_aura_bg)
        self.sources_area.pack(fill=tk.X, pady=(5, 0))

        self._build_ui_elements()

        rt_frame = tk.LabelFrame(self.root, text="Near Real Time Source Sequence and Dither Check",
                                 bg=self.color_blue_aura_bg, fg=self.color_label_frame_fg, font=self.heading_font)
        rt_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.log_text = ScrolledText.ScrolledText(rt_frame, wrap=tk.WORD, height=15, state=tk.DISABLED,
                                                  font=self.results_font, bg=self.color_log_bg, fg=self.color_text_dark,
                                                  insertbackground=self.color_text_dark)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0,5))
        self.log_text.tag_configure("ok", foreground="green")
        self.log_text.tag_configure("error", foreground="red")
        self.log_text.tag_configure("warning", foreground="orange")
        self.log_text.tag_configure("info", foreground="blue")
        self.log_text.tag_configure("debug", foreground="gray")
        self.log_text.tag_configure("heading", font=self.heading_font)
        self.log_text.tag_configure("separator", foreground="gray")

        self.status_label_text = tk.StringVar(value="Idle")
        self.status_label = tk.Label(rt_frame, textvariable=self.status_label_text, font=self.status_font, anchor='w',
                                     bg=self.color_blue_aura_bg)
        self.status_label.pack(fill=tk.X, padx=5, pady=2); self.status_label.config(fg="gray")

        btn_frame = tk.Frame(self.root, bg=self.color_blue_aura_bg)
        btn_frame.pack(pady=5)
        self.start_button = tk.Button(btn_frame, text="Start Source/Dither Check", command=self.start_checking, width=26,
                                      bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg)
        self.start_button.pack(side=tk.LEFT, padx=10)
        self.stop_button = tk.Button(btn_frame, text="Stop Source/Dither Check", command=self.stop_checking, state=tk.DISABLED, width=26,
                                     bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg,
                                     disabledforeground=self.color_disabled_fg)
        self.stop_button.pack(side=tk.LEFT, padx=10)

    def _info_help_text(self):
        a = SOURCE_CYCLE_ANCHOR_SP
        return (
            "SOURCE FIRING SEQUENCE CHECK\n"
            "===========================\n"
            "The app reads the latest shot from shotcontroller.log (NEW SHOT / Source to fire) and compares it to the\n"
            "expected source for that shotpoint.\n\n"
            "Line direction comes from the line queue (ex_lineque): Upline or Downline.\n"
            "The tool assumes exactly three sources in the shot cycle.\n\n"
            "Calculation:\n"
            "  index = (shotpoint - {a}) mod 3\n"
            "  Upline:  index 0 -> Source 1,  1 -> Source 2,  2 -> Source 3\n"
            "  Downline: index 0 -> Source 3, 1 -> Source 2, 2 -> Source 1\n\n"
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

        self.num_sources.set(SOURCE_CYCLE_COUNT)
        n_sources = SOURCE_CYCLE_COUNT

        for i in range(1, n_sources + 1):
            source_id = i
            segment = tk.LabelFrame(self.sources_area, text="Source {}".format(source_id), padx=5, pady=5,
                                    bg=self.color_blue_aura_bg, fg=self.color_label_frame_fg, font=self.results_font)
            segment.pack(fill=tk.X, padx=2, pady=(0, 3))
            new_src_config_dict = {}
            preserved_data = current_ui_values_cache.get(source_id, {})

            path_frame = tk.Frame(segment, bg=self.color_blue_aura_bg)
            path_frame.pack(fill=tk.X)
            tk.Label(path_frame, text="Dither File to Use:", width=18, anchor='w', bg=self.color_blue_aura_bg, fg=self.color_text_dark).pack(side=tk.LEFT)
            prev_path = preserved_data.get('path_var_dither_value', "")
            new_src_config_dict['path_var_dither'] = tk.StringVar(value=prev_path)
            new_src_config_dict['path_var_dither_value'] = prev_path
            tk.Entry(path_frame, textvariable=new_src_config_dict['path_var_dither'],
                     bg=self.color_entry_bg, fg=self.color_text_dark, insertbackground=self.color_text_dark).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
            tk.Button(path_frame, text="Browse...", command=lambda s=source_id: self.browse_dither_file(s),
                      bg=self.color_button_bg, fg=self.color_text_dark, activebackground=self.color_button_active_bg).pack(side=tk.LEFT)
            new_src_config_dict['status_label_dither'] = tk.Label(path_frame, text="Not Loaded", fg="gray", width=10, font=self.small_font, bg=self.color_blue_aura_bg)
            new_src_config_dict['status_label_dither'].pack(side=tk.LEFT, padx=5)
            new_src_config_dict['path_var_dither'].trace('w', lambda n, idx, m, var=new_src_config_dict['path_var_dither'], cfg=new_src_config_dict, key='path_var_dither_value': self._update_path_cache(cfg, key, var))

            self.source_configs[source_id] = new_src_config_dict
            if new_src_config_dict['path_var_dither'].get():
                self.load_dither_pattern(source_id, new_src_config_dict['path_var_dither'].get())

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
            title="Select or Create xSourceDitherQC Configuration File",
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
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)
        except tk.TclError: print "[Log-{}] {}".format(level, message)

    def run_command(self, cmd):
        try:
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate(); retcode = proc.returncode
            if retcode != 0: err_msg = stderr.strip() if stderr else "No stderr"; self.log_message("Error cmd '{}': RetCode={} | Err: {}".format(cmd, retcode, err_msg), "error"); return None
            if stderr: self.log_message("Stderr from '{}': {}".format(cmd, stderr.strip()), "warning")
            return stdout.strip()
        except OSError as e: self.log_message("Sys Error: Cmd for '{}': {}".format(cmd, e), "error"); return None
        except Exception as e: self.log_message("Unexpected err cmd '{}': {}".format(cmd, e), "error"); return None

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
        v = self.dither_pattern_reference_var.get()
        if v in PATTERN_REF_CHOICES:
            return v
        return PATTERN_REF_ANCHORED_SP

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
        for sid in range(1, SOURCE_CYCLE_COUNT + 1):
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
            "Adaptive: matched Trinav triple ({:.3f}, {:.3f}, {:.3f}) at SP {}–{} in files (row0 S1={} S2={} S3={}); "
            "QC row follows line (file top→bottom); next SP expects row+3 vs triple.".format(
                v1, v2, v3, sp1, sp3, new_starts[1], new_starts[2], new_starts[3]),
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
        """3-source cycle from *current* shot_number (from log), not line-queue Anchored shot.
        index = (shot_number - SOURCE_CYCLE_ANCHOR_SP) % 3  -> 0,1,2.
        Upline (is_upline True): 0->S1, 1->S2, 2->S3. Downline: 0->S3, 1->S2, 2->S1.
        Example: shot 1006, downline -> index 2 -> Source 1. anchored_shot unused here."""
        _ = anchored_shot
        try:
            num_sources_val = self.num_sources.get()
            if num_sources_val <= 0:
                return None, "Invalid Source Count ({})".format(num_sources_val)
        except (tk.TclError, ValueError) as e:
            return None, "Invalid GUI Params (SrcCount): {}".format(e)
        if num_sources_val != SOURCE_CYCLE_COUNT:
            return None, "Need {} sources for SP cycle (have {})".format(SOURCE_CYCLE_COUNT, num_sources_val)
        try:
            shot_n = int(shot_number)
        except (TypeError, ValueError):
            return None, "Invalid shot number"
        idx = (shot_n - SOURCE_CYCLE_ANCHOR_SP) % SOURCE_CYCLE_COUNT
        if is_upline:
            expected_source_id = idx + 1
        else:
            expected_source_id = (3, 2, 1)[idx]
        return expected_source_id, "OK"

    def check_first_dither_row_matches_reference(self, line_info):
        """Anchored SP: row0 = dither at anchor; Production FSP / Adaptive: alignment check N/A here."""
        mode = self._get_pattern_ref_mode()
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
        for sid in range(1, SOURCE_CYCLE_COUNT + 1):
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
        if mode == PATTERN_REF_ADAPTIVE:
            if self._adaptive_calibrated:
                return "Pattern Index Ref in Use: Adaptive (locked; triple starts at file row S1={} S2={} S3={})".format(
                    self._adaptive_triple_start_row[1], self._adaptive_triple_start_row[2], self._adaptive_triple_start_row[3])
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
        self.log_text.insert(tk.END, "  Dither from File: {} ".format(dither_file_val_str))
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
        num_src = SOURCE_CYCLE_COUNT
        self.num_sources.set(num_src)
        if not hasattr(self, 'source_configs') or len(self.source_configs) != num_src:
            self._build_ui_elements()
        patterns_ok = True
        files_missing = False
        if not self._is_gun_sequence_only():
            for i in range(1, num_src + 1):
                src_conf_dict = self.source_configs.get(i)
                if not src_conf_dict:
                    patterns_ok = False
                    self.log_message("Error: Config dict missing S{} in start.".format(i), "error")
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
        self.status_label.config(fg="blue")
        self.current_line_info = {}; self._reset_in_use_labels(); self.perform_check()

    def stop_checking(self):
        if not self.running: return
        self.running = False
        if self.timer_id: self.root.after_cancel(self.timer_id); self.timer_id = None
        self.start_button.config(state=tk.NORMAL, bg=self.color_button_bg)
        self.stop_button.config(state=tk.DISABLED, bg=self.color_disabled_bg if self.color_disabled_bg else self.color_button_bg)
        if self.params_frame:
            config_frame_ref = None
            for w in self.root.winfo_children():
                if isinstance(w, tk.Frame) and self.config_name_entry in w.winfo_children(): config_frame_ref = w; break
            if config_frame_ref: self.params_frame.pack(fill=tk.X, padx=5, pady=5, after=config_frame_ref)
            else: self.params_frame.pack(fill=tk.X, padx=5, pady=5)
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

                n_src_in_ui = SOURCE_CYCLE_COUNT
                for sid_iterator in range(1, n_src_in_ui + 1):
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