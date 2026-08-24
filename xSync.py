#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Ai assisted code by RBolisay
# --- xSync ---
# VERSION: 2.0
# Python 2.7 GUI for synchronizing files to a Supervision server using rsync.
# NOTE: Paramiko dependency and remote SFTP Browse functionality removed.
# NOTE: Default SV Target Directory is now dynamic based on Vessel/Job Name.
# NOTE: Uses SSH Key Authentication (no password, sshpass removed).
# NOTE: GUI references .xcfg file, data stored in centralized .json file in DEFAULT_CONFIG_DIR.
# NOTE: Added validation for required fields before save/sync.
# NOTE: Rearranged segment layout (Target/Options below Source).
# NOTE: Changed Scan Time to Minutes.
# NOTE: Added IP validation, dynamic Vessel/Job dropdowns, state management.
# FIX: Corrected AttributeError with functools.partial and Tkinter.after.
# UPDATE: GUI layout changes based on user request (Title, Labels, IP width, Dropdown colors, Button text/position, Segment layout).
# UPDATE 2: Further layout rearrangement (Settings row, Segment options) and fix button visibility.
# FIX 2: Re-added <Return> and <FocusOut> bindings to Supervision IP entry.
# UPDATE 3: Suppress first-time load errors, add Connect button, auto-connect on load, relocate Auto Sync status.
# UPDATE 4: Fix SV Target Dir update on selection, adjust segment options layout, ensure dropdown color update.
# UPDATE 5: Adjust segment checkbox layout, set default .xcfg save/browse dir, adjust .xcfg entry width, rename config label, fix segment save/load.
# UPDATE 6: Correct segment loading sequence, refine segment options layout.
# UPDATE 7: Change "Start Sync" button text, refine dropdown color logic.
# UPDATE 8: Set default source directory, ensure dropdown color updates on selection, adjust config row layout.
# UPDATE 9: Correct segment checkbox layout using pack, ensure default browse dir, verify default source dir, fix dropdown color update.
# UPDATE 10: Change rsync flags to -av --no-times.
# UPDATE 11: Add --stats flag, parse output for summary, add --delete-excluded when pattern and delete are used.
# UPDATE 12: Refine rsync filter logic for patterns, improve stats parsing.
# UPDATE 13: Retain Vessel/Job selection on reconnect, add description for --Delete checkbox.
# UPDATE 14: Re-add --no-times flag to rsync command.
# UPDATE 15: Prevent segment source path from resetting on reconnect by prioritizing existing GUI values.
# UPDATE 16: Prevent segment target path from resetting on reconnect; prevent sync if target is the default path.
# UPDATE 17: Restore automatic target path updates on vessel/job change; reload config on Connect button press.
# UPDATE 18: Set default number of segments to 0; add Clear Segments button; rename Set button.
# UPDATE 19: Add ENV data handling section and functionality.
# UPDATE 20: Change default ENV data target directory.
# UPDATE 21: Change default ENV data *source* browse directory.
# FIX 6: Restore missing ENV data handling methods (_move_zip_env_action, _check_env_thread, _run_move_zip_env).
# UPDATE 22: Use pigz command instead of zipfile for ENV data compression.
# UPDATE 23: Add scrollbar for segment area.
# UPDATE 24: Remove automatic window height adjustment.
# FIX 8: Correctly configure canvas and inner frame for scrollable segments.
# UPDATE 25: Add descriptive label for Move/Zip ENV button.
# UPDATE 26: Apply user-requested color scheme.
# UPDATE 27: Remove --no-times flag from rsync command to enable timestamp-based file comparison.
# UPDATE 28: Add optional coverage (.cov) file selection and sync as .coverage.cov on supervision site.
# UPDATE 29 (v2.0): Improve rsync reliability for partial-transfer code 23 by pre-creating remote target directories,
#                   using safer metadata flags, and adding explicit rsync exit-code diagnostics in status logs.
# UPDATE 30 (v2.0): Ensure successful sync preserves source file timestamps on supervision target files (-t enabled).

import Tkinter as tk
import tkFileDialog
import tkMessageBox
import tkFont
import ttk # For Combobox (add fallback if needed)
import json
import os
import subprocess
import threading
import Queue
import time
import datetime # Added for timestamp in zip filename
import sys # To check platform for path separators if needed
import re # For cleaning names
import glob # Added for finding Env* files
import shutil # Added for moving files
# import zipfile # Removed - Using pigz now
# functools.partial is no longer strictly needed for the 'after' calls, but keep import
from functools import partial

# --- Theme Colors (User Specified) ---
GUI_BACKGROUND_COLOR = "#B4C8E1"
BUTTON_BACKGROUND_COLOR = "#8DA9CC"
BUTTON_TEXT_COLOR = "black"
# SUCCESS_BG_COLOR for comboboxes remains "white" as it's not a button or general GUI background.

# --- Configuration ---
DEFAULT_CONFIG_DIR = "/usr/local/trinop/dbase/links/qcfiles/Misc/xSync" # Central directory for JSON files AND default for .xcfg saving/Browse
DEFAULT_SOURCE_DIR = "/usr/local/trinop/dbase/links/qcfiles" # Default for segment source directory
DEFAULT_ENV_SOURCE_DIR = "/usr/local/trinop/dbase/links/backup" # Default ENV *source* directory for Browse
DEFAULT_ENV_TARGET_DIR = "/usr/local/trinop/dbase/links/qcfiles/EnvironmentalData" # Target remains the same
LAST_CONFIG_MARKER_FILE = os.path.join(os.path.expanduser("~"), ".xsync_last_config")
FALLBACK_SV_TARGET_DIR = "/home/shearwater/vessels/unknown_vessel/unknown_job" # Fallback if names are empty
REMOTE_VESSELS_PATH_CANDIDATES = [
    "/home/shearwater/vessels",
    "/data/local1/supervision/site/docs/active/vessels",
    "/local1/supervision/site/docs/active/vessels",
    "/supervision/site/docs/active/vessels"
]
SSH_USER = "shearwater"
XCFG_EXTENSION = ".xcfg"
JSON_EXTENSION = ".json"
XCFG_FILE_TYPE_DESC = "xSync Config files"
XCFG_FILE_TYPE_PATTERN = "*" + XCFG_EXTENSION
COVERAGE_FILE_TYPE_DESC = "Coverage files"
COVERAGE_FILE_TYPE_PATTERN = "*.cov"
DEFAULT_COVERAGE_TARGET_NAME = ".coverage.cov"
DEFAULT_SCAN_TIME_MINUTES = 5 # Default scan time now in minutes
SSH_TIMEOUT = 5 # Seconds for SSH connection attempts
SUCCESS_BG_COLOR = "white" # Background color for successful dropdown load (Not changed as per "Do not change anything else")


# --- Helper Function ---
def sanitize_for_path(name):
    """Replaces spaces and potentially problematic characters for directory names."""
    if not name:
        return ""
    name = name.strip().replace(" ", "_")
    name = re.sub(r'[^\w\-.]', '', name)
    return name

# --- Main Application ---
class XSyncApp:
    def __init__(self, master):
        self.master = master
        self.master.title("xSync - Supervision Synch Tool")
        # Apply theme color to the root window
        self.master.configure(bg=GUI_BACKGROUND_COLOR)


        # Ensure default config dir exists
        try:
            if not os.path.exists(DEFAULT_CONFIG_DIR):
                os.makedirs(DEFAULT_CONFIG_DIR)
                print("Created default configuration directory: {}".format(DEFAULT_CONFIG_DIR))
            else:
                 if not os.access(DEFAULT_CONFIG_DIR, os.W_OK):
                      raise OSError("Directory {} is not writable".format(DEFAULT_CONFIG_DIR))
            if not os.path.exists(DEFAULT_ENV_TARGET_DIR):
                 os.makedirs(DEFAULT_ENV_TARGET_DIR)
                 print("Created ENV target directory: {}".format(DEFAULT_ENV_TARGET_DIR))

        except OSError as e:
            print("ERROR: Could not create or access required directory: {}".format(e))
            tkMessageBox.showerror("Directory Error", "Could not create or access required directory:\n{}\n\nPlease ensure path exists and is writable.".format(e))

        # --- Data Variables ---
        self.config_path_var = tk.StringVar()
        self.env_data_path_var = tk.StringVar()
        self.coverage_enabled_var = tk.BooleanVar(value=False)
        self.coverage_file_path_var = tk.StringVar()
        self.coverage_target_file_var = tk.StringVar()
        self.supervision_ip_var = tk.StringVar()
        self.vessel_selection_var = tk.StringVar()
        self.job_selection_var = tk.StringVar()
        self._loaded_vessel_name = None
        self._loaded_job_name = None
        self.num_segments_var = tk.StringVar(value="0")
        self.scan_time_var = tk.StringVar(value=str(DEFAULT_SCAN_TIME_MINUTES))
        self.auto_sync_status_var = tk.StringVar(value="Auto Synch OFF")
        self.segment_widgets = []
        self.sync_thread = None
        self.env_thread = None
        self.auto_sync_timer = None
        self.is_auto_sync_on = False
        self.status_queue = Queue.Queue()
        self.bold_font = tkFont.Font(family="Helvetica", size=10, weight=tkFont.BOLD)
        self.italic_font = tkFont.Font(family="Helvetica", size=9, slant=tkFont.ITALIC)
        self.small_italic_font = tkFont.Font(family="Helvetica", size=8, slant=tkFont.ITALIC)
        self._update_defaults_timer = None
        self.status_text = None
        self.ip_validation_thread = None
        self.list_dir_thread = None
        self._loaded_segments_data = None
        self._default_widget_bg = None
        self.main_frame = None
        self.coverage_section_frame = None
        self._last_default_coverage_target = None
        self._remote_vessel_job_map = {}
        self._active_vessel_tree_request = 0
        self._remote_vessels_root = None

        # --- Build GUI ---
        self._create_widgets()
        try:
            style = ttk.Style()
            self._default_widget_bg = style.lookup("TCombobox", "fieldbackground") # Usually white
        except tk.TclError:
             try:
                  root_window = self.master.winfo_toplevel()
                  self._default_widget_bg = root_window.cget('bg')
             except (AttributeError, tk.TclError):
                   self._default_widget_bg = GUI_BACKGROUND_COLOR # Fallback to new GUI background

        config_loaded = self._load_last_config(suppress_errors=True)

        self.master.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.master.after(100, self._process_status_queue)

    def _create_widgets(self):
        self.main_frame = tk.Frame(self.master, padx=10, pady=10, bg=GUI_BACKGROUND_COLOR)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.main_frame.grid_columnconfigure(0, weight=1)

        row_index = 0

        desc_label = tk.Label(self.main_frame, text="Supervision Synch Tool", font=self.bold_font, bg=GUI_BACKGROUND_COLOR)
        desc_label.grid(row=row_index, column=0, columnspan=5, pady=(0, 2), sticky="w")
        row_index += 1
        ssh_key_label = tk.Label(self.main_frame, text="Please make sure passwordless connection to Supervision has been setup using SSH keygen", font=self.italic_font, fg="darkblue", bg=GUI_BACKGROUND_COLOR)
        ssh_key_label.grid(row=row_index, column=0, columnspan=5, pady=(0, 10), sticky="w")
        row_index += 1

        info_frame = tk.Frame(self.main_frame, bg=GUI_BACKGROUND_COLOR)
        info_frame.grid(row=row_index, column=0, columnspan=5, sticky="ew", pady=5)
        info_frame.grid_columnconfigure(1, weight=0)
        info_frame.grid_columnconfigure(2, weight=0)
        info_frame.grid_columnconfigure(3, weight=0)
        info_frame.grid_columnconfigure(4, weight=1)
        info_frame.grid_columnconfigure(5, weight=0)
        info_frame.grid_columnconfigure(6, weight=1)

        tk.Label(info_frame, text="*Supervision IP:", bg=GUI_BACKGROUND_COLOR).grid(row=0, column=0, sticky="w", padx=(0, 5))
        ip_entry = tk.Entry(info_frame, textvariable=self.supervision_ip_var, width=20)
        ip_entry.grid(row=0, column=1, sticky="w", padx=(0, 5))
        
        connect_button = tk.Button(info_frame, text="Connect", command=self._handle_ip_change, width=8, 
                                   bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, 
                                   activebackground=BUTTON_BACKGROUND_COLOR)
        connect_button.grid(row=0, column=2, sticky="w", padx=(5, 15)) 

        tk.Label(info_frame, text="*Vessel Name:", bg=GUI_BACKGROUND_COLOR).grid(row=0, column=3, sticky="w", padx=(0, 5), pady=(0,0))
        self.vessel_combobox = ttk.Combobox(info_frame, textvariable=self.vessel_selection_var, state='disabled', postcommand=self._update_vessel_dropdown_width)
        self.vessel_combobox.grid(row=0, column=4, sticky="ew", pady=(0,0), padx=(0, 15))
        self.vessel_combobox.bind("<<ComboboxSelected>>", self._handle_vessel_selected)

        tk.Label(info_frame, text="*Job Name:", bg=GUI_BACKGROUND_COLOR).grid(row=0, column=5, sticky="w", padx=(0, 5), pady=(0,0))
        self.job_combobox = ttk.Combobox(info_frame, textvariable=self.job_selection_var, state='disabled', postcommand=self._update_job_dropdown_width)
        self.job_combobox.grid(row=0, column=6, sticky="ew", pady=(0,0))
        self.job_combobox.bind("<<ComboboxSelected>>", self._handle_job_selected)
        row_index += 1

        settings_frame = tk.Frame(self.main_frame, bg=GUI_BACKGROUND_COLOR)
        settings_frame.grid(row=row_index, column=0, columnspan=5, sticky="ew", pady=5)
        settings_frame.grid_columnconfigure(7, weight=1) 

        tk.Label(settings_frame, text="Synch Segments:", bg=GUI_BACKGROUND_COLOR).grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.num_segments_entry = tk.Entry(settings_frame, textvariable=self.num_segments_var, width=5, state='disabled')
        self.num_segments_entry.grid(row=0, column=1, sticky="w")
        
        self.set_segments_button = tk.Button(settings_frame, text="Set Segment", command=self._update_segment_rows, state='disabled', 
                                             bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                                             activebackground=BUTTON_BACKGROUND_COLOR)
        self.set_segments_button.grid(row=0, column=2, padx=(5, 5)) 
        
        self.clear_segments_button = tk.Button(settings_frame, text="Clear Segments", command=self._clear_segments_action, state='disabled', 
                                               bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                                               activebackground=BUTTON_BACKGROUND_COLOR)
        self.clear_segments_button.grid(row=0, column=3, padx=(0, 20)) 

        tk.Label(settings_frame, text="Synch Scan Time (min):", bg=GUI_BACKGROUND_COLOR).grid(row=0, column=4, sticky="w", padx=(0, 5))
        tk.Entry(settings_frame, textvariable=self.scan_time_var, width=7).grid(row=0, column=5, sticky="w", padx=(0, 5))

        self.auto_sync_label = tk.Label(settings_frame, textvariable=self.auto_sync_status_var, font=self.bold_font, fg="orange", bg=GUI_BACKGROUND_COLOR)
        self.auto_sync_label.grid(row=0, column=6, sticky="w", padx=(0,0)) 
        row_index += 1

        config_frame = tk.Frame(self.main_frame, bg=GUI_BACKGROUND_COLOR)
        config_frame.grid(row=row_index, column=0, columnspan=5, sticky="ew", pady=(2,2)) 
        config_frame.grid_columnconfigure(4, weight=1) 

        tk.Label(config_frame, text="xSync Config:", bg=GUI_BACKGROUND_COLOR).grid(row=0, column=0, sticky="w", padx=(0, 5))
        config_entry = tk.Entry(config_frame, textvariable=self.config_path_var, width=50)
        config_entry.grid(row=0, column=1, sticky="w", padx=(0, 5)) 
        tk.Button(config_frame, text="Browse...", command=self._browse_config, 
                  bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                  activebackground=BUTTON_BACKGROUND_COLOR).grid(row=0, column=2, sticky="w", padx=(0, 5)) 
        tk.Button(config_frame, text="Save Config", command=self._save_config_action, 
                  bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                  activebackground=BUTTON_BACKGROUND_COLOR).grid(row=0, column=3, sticky="w", padx=(0, 0)) 
        row_index += 1

        env_frame = tk.Frame(self.main_frame, bg=GUI_BACKGROUND_COLOR)
        env_frame.grid(row=row_index, column=0, columnspan=5, sticky="ew", pady=(2,1)) 
        env_frame.grid_columnconfigure(4, weight=1) 

        tk.Label(env_frame, text="ENV data:", bg=GUI_BACKGROUND_COLOR).grid(row=0, column=0, sticky="w", padx=(0, 5))
        env_entry = tk.Entry(env_frame, textvariable=self.env_data_path_var, width=50)
        env_entry.grid(row=0, column=1, sticky="w", padx=(0, 5)) 
        tk.Button(env_frame, text="Browse...", command=self._browse_env_dir, 
                  bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                  activebackground=BUTTON_BACKGROUND_COLOR).grid(row=0, column=2, sticky="w", padx=(0, 5)) 
        self.move_zip_env_button = tk.Button(env_frame, text="Move/Zip ENV", command=self._move_zip_env_action, 
                                             bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                                             activebackground=BUTTON_BACKGROUND_COLOR)
        self.move_zip_env_button.grid(row=0, column=3, sticky="w", padx=(0, 5)) 
        
        env_desc_text = "Move Env* files to {} and compress".format(DEFAULT_ENV_TARGET_DIR)
        env_desc_label = tk.Label(env_frame, text=env_desc_text, font=self.small_italic_font, fg="grey", bg=GUI_BACKGROUND_COLOR)
        env_desc_label.grid(row=1, column=1, columnspan=3, sticky="w", padx=(0,0)) 

        row_index += 1

        coverage_toggle_frame = tk.Frame(self.main_frame, bg=GUI_BACKGROUND_COLOR)
        coverage_toggle_frame.grid(row=row_index, column=0, columnspan=5, sticky="w", pady=(0,0))
        tk.Checkbutton(
            coverage_toggle_frame,
            text="Coverage File (Y/N)",
            variable=self.coverage_enabled_var,
            command=self._toggle_coverage_section,
            bg=GUI_BACKGROUND_COLOR,
            fg=BUTTON_TEXT_COLOR,
            activebackground=GUI_BACKGROUND_COLOR,
            selectcolor=BUTTON_BACKGROUND_COLOR
        ).pack(side=tk.LEFT, padx=(0, 0), pady=(0, 0))
        row_index += 1

        self.coverage_section_frame = tk.LabelFrame(self.main_frame, text="Coverage File", padx=3, pady=3, bg=GUI_BACKGROUND_COLOR, fg="black")
        self.coverage_section_frame.grid(row=row_index, column=0, columnspan=5, sticky="ew", pady=(0,2))
        self.coverage_section_frame.grid_columnconfigure(1, weight=1)
        self.coverage_section_frame.grid_columnconfigure(2, weight=0)

        tk.Label(self.coverage_section_frame, text="Source File:", bg=GUI_BACKGROUND_COLOR).grid(row=0, column=0, sticky="w", padx=(0,2), pady=(1, 1))
        tk.Entry(self.coverage_section_frame, textvariable=self.coverage_file_path_var).grid(row=0, column=1, sticky="ew", padx=2, pady=(1, 1))
        tk.Button(
            self.coverage_section_frame,
            text="...",
            width=3,
            command=self._browse_coverage_file,
            bg=BUTTON_BACKGROUND_COLOR,
            fg=BUTTON_TEXT_COLOR,
            activebackground=BUTTON_BACKGROUND_COLOR
        ).grid(row=0, column=2, sticky="e", padx=(5,0), pady=(1, 1))

        tk.Label(self.coverage_section_frame, text="SV Target File:", bg=GUI_BACKGROUND_COLOR).grid(row=1, column=0, sticky="w", padx=(0,2), pady=(1, 1))
        tk.Entry(self.coverage_section_frame, textvariable=self.coverage_target_file_var).grid(row=1, column=1, sticky="ew", padx=2, pady=(1, 1))
        tk.Label(self.coverage_section_frame, text="Synced only when file changed", font=self.small_italic_font, fg="grey", bg=GUI_BACKGROUND_COLOR).grid(row=2, column=1, columnspan=2, sticky="w", padx=(0,0), pady=(0,1))

        row_index += 1

        self.main_frame.grid_rowconfigure(row_index, weight=1)
        self.segments_canvas_frame = tk.Frame(self.main_frame, bd=1, relief=tk.GROOVE, bg=GUI_BACKGROUND_COLOR)
        self.segments_canvas_frame.grid(row=row_index, column=0, columnspan=5, sticky="nsew", pady=5)
        self.segments_canvas_frame.grid_rowconfigure(0, weight=1)
        self.segments_canvas_frame.grid_columnconfigure(0, weight=1)

        self.segments_canvas = tk.Canvas(self.segments_canvas_frame, borderwidth=0, background=GUI_BACKGROUND_COLOR)
        self.segments_scrollbar = tk.Scrollbar(self.segments_canvas_frame, orient="vertical", command=self.segments_canvas.yview)
        
        self.segments_frame = tk.Frame(self.segments_canvas, background=GUI_BACKGROUND_COLOR)

        self.segments_canvas.configure(yscrollcommand=self.segments_scrollbar.set)
        self.segments_scrollbar.pack(side="right", fill="y")
        self.segments_canvas.pack(side="left", fill="both", expand=True)
        self.canvas_window = self.segments_canvas.create_window((0, 0), window=self.segments_frame, anchor="nw")

        self.segments_frame.bind("<Configure>", self._on_segment_frame_configure)
        self.segments_canvas.bind_all("<Button-4>", lambda event: self._on_mousewheel(event, -1)) 
        self.segments_canvas.bind_all("<Button-5>", lambda event: self._on_mousewheel(event, 1))  
        self.segments_canvas.bind_all("<MouseWheel>", self._on_mousewheel) 
        row_index += 1

        status_frame = tk.LabelFrame(self.main_frame, text="Status Log", padx=5, pady=5, bg=GUI_BACKGROUND_COLOR, fg="black")
        status_frame.grid(row=row_index, column=0, columnspan=5, sticky="nsew", pady=5)
        status_frame.grid_rowconfigure(0, weight=1)
        status_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(row_index, weight=0) 

        self.status_text = tk.Text(status_frame, height=8, wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT, bd=0)
        status_scroll = tk.Scrollbar(status_frame, command=self.status_text.yview)
        self.status_text.config(yscrollcommand=status_scroll.set)
        self.status_text.grid(row=0, column=0, sticky="nsew")
        status_scroll.grid(row=0, column=1, sticky="ns")
        row_index += 1

        button_frame = tk.Frame(self.main_frame, bg=GUI_BACKGROUND_COLOR)
        button_frame.grid(row=row_index, column=0, columnspan=5, sticky="ew", pady=(10, 5))
        button_frame.grid_columnconfigure(0, weight=1)

        center_button_frame = tk.Frame(button_frame, bg=GUI_BACKGROUND_COLOR)
        center_button_frame.pack(anchor=tk.CENTER) 

        self.auto_sync_button = tk.Button(center_button_frame, text="Start Auto Synch", command=self._toggle_auto_sync, width=15, 
                                          bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                                          activebackground=BUTTON_BACKGROUND_COLOR)
        self.auto_sync_button.pack(side=tk.RIGHT, padx=5) 
        
        self.start_sync_button = tk.Button(center_button_frame, text="Start Synch", command=self._start_sync_action, width=12, 
                                           bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                                           activebackground=BUTTON_BACKGROUND_COLOR)
        self.start_sync_button.pack(side=tk.RIGHT, padx=5)

        self._update_default_coverage_target(force=True)
        self._toggle_coverage_section()


    def _on_segment_frame_configure(self, event):
        self.segments_canvas.configure(scrollregion=self.segments_canvas.bbox("all"))
        canvas_width = self.segments_canvas.winfo_width()
        scrollbar_width = self.segments_scrollbar.winfo_width()
        self.segments_canvas.itemconfig(self.canvas_window, width=max(1, canvas_width - scrollbar_width - 4)) 


    def _on_mousewheel(self, event, direction=None):
        if direction is not None: 
             scroll_dir = direction
        elif hasattr(event, 'delta') and event.delta != 0: 
             scroll_dir = -1 * (event.delta / abs(event.delta)) 
        else:
             return 
        self.segments_canvas.yview_scroll(int(scroll_dir), "units")


    def _update_dropdown_width(self, combobox):
        try:
            longest = 0
            values = combobox.cget('values')
            if isinstance(values, basestring): 
                 values_list = combobox.tk.splitlist(values)
            elif isinstance(values, (list, tuple)):
                 values_list = values
            else:
                 values_list = [] 

            if values_list:
                for item in values_list:
                    item_str = str(item) 
                    if len(item_str) > longest:
                        longest = len(item_str)
                combobox.configure(width=max(longest + 1, 15)) 
        except tk.TclError: pass 
        except Exception as e: print("Error updating dropdown width: {}".format(e)) 


    def _update_vessel_dropdown_width(self): self._update_dropdown_width(self.vessel_combobox)
    def _update_job_dropdown_width(self): self._update_dropdown_width(self.job_combobox)

    def _log_status(self, message):
        if not hasattr(self, 'status_text') or not isinstance(self.status_text, tk.Text) or not self.status_text.winfo_exists():
            print("Log (status_text not ready/valid): {}".format(message)); return
        try:
            import datetime
            utc_now = datetime.datetime.utcnow()
            pht_offset = datetime.timedelta(hours=8) 
            pht_now = utc_now + pht_offset
            now_str = pht_now.strftime("%Y-%m-%d %H:%M:%S PHT")
        except ImportError: now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = "[{}] {}".format(now_str, message)
        try:
            self.status_text.config(state=tk.NORMAL)
            self.status_text.insert(tk.END, formatted_message + "\n")
            self.status_text.see(tk.END)
            self.status_text.config(state=tk.DISABLED)
        except tk.TclError as e:
            print("Error logging to status_text: {}".format(e)); print(formatted_message)

    def _log_status_from_thread(self, message): self.status_queue.put(message)

    def _process_status_queue(self):
        try:
            while True: message = self.status_queue.get_nowait(); self._log_status(message)
        except Queue.Empty: pass
        finally: self.master.after(100, self._process_status_queue)

    def _format_debug_items(self, values, limit=8):
        if not values:
            return "(none)"
        cleaned_values = [str(value) for value in values if value is not None and str(value) != ""]
        if not cleaned_values:
            return "(none)"
        if len(cleaned_values) <= limit:
            return ", ".join(cleaned_values)
        return "{}, ... (+{} more)".format(", ".join(cleaned_values[:limit]), len(cleaned_values) - limit)

    def _find_case_insensitive_match(self, wanted_value, candidates):
        normalized_wanted = self._normalize_remote_component(wanted_value).lower()
        if not normalized_wanted:
            return None
        for candidate in (candidates or []):
            if self._normalize_remote_component(candidate).lower() == normalized_wanted:
                return candidate
        return None

    def _inspect_remote_path_entry(self, ip_address, entry_path):
        if not ip_address or not entry_path:
            return "inspection skipped: missing IP or path"
        quoted_path = self._shell_single_quote(entry_path)
        remote_cmd = (
            "if [ -L {path} ]; then "
            "target=$(readlink {path} 2>/dev/null || echo '?'); "
            "printf 'exists=yes type=symlink target=%s\\n' \"$target\"; "
            "elif [ -d {path} ]; then "
            "printf 'exists=yes type=directory\\n'; "
            "elif [ -e {path} ]; then "
            "printf 'exists=yes type=other\\n'; "
            "else "
            "printf 'exists=no\\n'; "
            "fi"
        ).format(path=quoted_path)
        cmd = [
            'ssh', '-q',
            '-o', 'BatchMode=yes',
            '-o', 'ConnectTimeout={}'.format(SSH_TIMEOUT),
            '-o', 'StrictHostKeyChecking=no',
            '{}@{}'.format(SSH_USER, ip_address),
            remote_cmd
        ]
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).strip()
            return output if output else "inspection returned no output"
        except subprocess.CalledProcessError as e:
            output = e.output.strip() if getattr(e, 'output', None) else ""
            return "inspection failed (exit code {}): {}".format(e.returncode, output or "no output")
        except Exception as e:
            return "inspection failed: {}".format(e)

    def _log_remote_scan_debug(self, remote_path, debug_info):
        if not debug_info:
            return
        self._log_status_from_thread(
            "Scan debug for {}: raw hits={}, top-level={}, vessels-with-jobs={}, skipped={}".format(
                remote_path,
                debug_info.get('raw_count', 0),
                len(debug_info.get('top_level_dirs', [])),
                len(debug_info.get('vessels_with_jobs', [])),
                len(debug_info.get('skipped_dirs', []))
            )
        )
        top_level_dirs = debug_info.get('top_level_dirs', [])
        if top_level_dirs:
            self._log_status_from_thread("Scan debug top-level entries: {}".format(self._format_debug_items(top_level_dirs, limit=12)))
        raw_path_samples = debug_info.get('raw_path_samples', [])
        if raw_path_samples:
            self._log_status_from_thread("Scan debug sample paths: {}".format(self._format_debug_items(raw_path_samples, limit=12)))
        case_match = debug_info.get('expected_case_insensitive_match')
        expected_vessel_name = debug_info.get('expected_vessel_name')
        if expected_vessel_name and case_match and case_match != expected_vessel_name:
            self._log_status_from_thread(
                "Scan debug: loaded vessel '{}' matched remote entry '{}' only by case.".format(
                    expected_vessel_name, case_match
                )
            )
        for inspected_name, inspected_status in debug_info.get('entry_inspections', []):
            self._log_status_from_thread(
                "Scan debug entry '{}': {}".format(inspected_name, inspected_status)
            )

    def _log_vessels_path_candidate_result(self, ip_address, candidate_path, success, vessel_list, message, debug_info):
        root_status = self._inspect_remote_path_entry(ip_address, candidate_path)
        self._log_status_from_thread("Candidate root '{}': {}".format(candidate_path, root_status))
        if success:
            self._log_remote_scan_debug(candidate_path, debug_info)
            if vessel_list:
                self._log_status_from_thread(
                    "Candidate '{}' detected {} vessel(s).".format(candidate_path, len(vessel_list))
                )
            else:
                self._log_status_from_thread(
                    "Candidate '{}' is accessible but returned no vessel directories. {}".format(candidate_path, message)
                )
        else:
            self._log_status_from_thread(
                "Candidate '{}' scan failed: {}".format(candidate_path, message)
            )

    def _split_find_output_lines(self, output):
        data_lines = []
        warning_lines = []
        for raw_line in (output or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith('find:'):
                warning_lines.append(line)
            else:
                data_lines.append(line)
        return data_lines, warning_lines

    def _check_ssh_connection(self, ip_address, callback):
        if not ip_address:
            self.master.after(0, lambda: callback(False, "IP address is empty.")); return
        cmd = ['ssh', '-q', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout={}'.format(SSH_TIMEOUT), '-o', 'StrictHostKeyChecking=no', '{}@{}'.format(SSH_USER, ip_address), 'exit']
        self._log_status_from_thread("Attempting SSH connection to {}...".format(ip_address))
        success = False; message = ""
        try:
            with open(os.devnull, 'w') as DEVNULL: exit_code = subprocess.call(cmd, stdout=DEVNULL, stderr=DEVNULL)
            if exit_code == 0: success = True; message = "SSH connection successful."; self._log_status_from_thread(message)
            else: message = "SSH connection failed (exit code {}). Check IP, user '{}', SSH keys, and network.".format(exit_code, SSH_USER); self._log_status_from_thread(message)
        except OSError as e: message = "Failed to run SSH command: {}. Is 'ssh' installed and in PATH?".format(e); self._log_status_from_thread(message)
        except Exception as e: message = "Unexpected error during SSH check: {}".format(e); self._log_status_from_thread(message)
        self.master.after(0, lambda cb=callback, s=success, m=message: cb(s, m))

    def _list_remote_dirs(self, ip_address, remote_path, callback):
        if not ip_address or not remote_path:
             self.master.after(0, lambda: callback(False, [], "IP or remote path is empty.")); return
        quoted_remote_path = self._shell_single_quote(remote_path.rstrip('/') or '/')
        remote_cmd = "find -L {} -maxdepth 1 -mindepth 1 -type d -printf '%f\\n'".format(quoted_remote_path)
        cmd = ['ssh', '-q', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout={}'.format(SSH_TIMEOUT), '-o', 'StrictHostKeyChecking=no', '{}@{}'.format(SSH_USER, ip_address), remote_cmd]
        self._log_status_from_thread("Listing directories in {} on {}...".format(remote_path, ip_address))
        dir_list = []; success = False; message = ""
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            data_lines, warning_lines = self._split_find_output_lines(output)
            dir_list = sorted(data_lines)
            success = True; message = "Successfully listed {} directories.".format(len(dir_list)); self._log_status_from_thread(message)
            if warning_lines:
                self._log_status_from_thread("Remote directory listing warning(s): {}".format(" | ".join(warning_lines[:3])))
        except subprocess.CalledProcessError as e:
            data_lines, warning_lines = self._split_find_output_lines(getattr(e, 'output', ''))
            if data_lines:
                dir_list = sorted(data_lines)
                success = True
                message = "Listed {} directories with find warning(s) (exit code {}).".format(len(dir_list), e.returncode)
                self._log_status_from_thread(message)
                if warning_lines:
                    self._log_status_from_thread("Remote directory listing warning(s): {}".format(" | ".join(warning_lines[:3])))
            else:
                message = "Failed to list remote directories (exit code {}):\n{}".format(e.returncode, e.output); self._log_status_from_thread(message)
        except OSError as e: message = "Failed to run SSH command for listing: {}. Is 'ssh' installed?".format(e); self._log_status_from_thread(message)
        except Exception as e: message = "Unexpected error listing remote directories: {}".format(e); self._log_status_from_thread(message)
        self.master.after(0, lambda cb=callback, s=success, d=dir_list, m=message: cb(s, d, m))

    def _scan_remote_vessel_job_tree_data(self, ip_address, remote_path):
        if not ip_address or not remote_path:
            return False, [], {}, [], "IP or remote path is empty.", {}
        quoted_remote_path = self._shell_single_quote(remote_path.rstrip('/') or '/')
        remote_cmd = "find -L {} -mindepth 1 -maxdepth 2 -type d -printf '%P\\n'".format(quoted_remote_path)
        cmd = ['ssh', '-q', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout={}'.format(SSH_TIMEOUT), '-o', 'StrictHostKeyChecking=no', '{}@{}'.format(SSH_USER, ip_address), remote_cmd]
        vessel_job_map = {}
        top_level_dirs = set()
        success = False
        message = ""
        skipped_dirs = []
        vessel_list = []
        debug_info = {}
        raw_paths = []
        warning_lines = []
        expected_vessel_name = self._normalize_remote_component(self._loaded_vessel_name)
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            data_lines, warning_lines = self._split_find_output_lines(output)
            for raw_line in data_lines:
                rel_path = raw_line.strip().strip('/')
                if not rel_path:
                    continue
                raw_paths.append(rel_path)
                parts = [part for part in rel_path.split('/') if part]
                if len(parts) == 1:
                    top_level_dirs.add(parts[0])
                elif len(parts) == 2:
                    vessel_name, job_name = parts
                    top_level_dirs.add(vessel_name)
                    vessel_job_map.setdefault(vessel_name, set()).add(job_name)

            normalized_map = {}
            for vessel_name, jobs in vessel_job_map.items():
                normalized_map[vessel_name] = sorted(jobs)
            vessel_job_map = normalized_map

            vessels_with_jobs = sorted(vessel_job_map.keys())
            skipped_dirs = sorted(top_level_dirs.difference(vessels_with_jobs))
            if vessels_with_jobs:
                vessel_list = vessels_with_jobs
            else:
                vessel_list = sorted(top_level_dirs)
                skipped_dirs = []

            case_insensitive_match = self._find_case_insensitive_match(expected_vessel_name, vessel_list or sorted(top_level_dirs))
            entry_inspections = []
            names_to_inspect = []
            if expected_vessel_name:
                names_to_inspect.append(expected_vessel_name)
            if case_insensitive_match and case_insensitive_match not in names_to_inspect:
                names_to_inspect.append(case_insensitive_match)
            for vessel_name in names_to_inspect:
                entry_path = "{}/{}".format(remote_path.rstrip('/'), vessel_name)
                entry_inspections.append((vessel_name, self._inspect_remote_path_entry(ip_address, entry_path)))

            debug_info = {
                'raw_count': len(raw_paths),
                'raw_path_samples': raw_paths[:20],
                'warning_lines': warning_lines[:10],
                'top_level_dirs': sorted(top_level_dirs),
                'vessels_with_jobs': vessels_with_jobs,
                'skipped_dirs': skipped_dirs,
                'expected_vessel_name': expected_vessel_name,
                'expected_case_insensitive_match': case_insensitive_match,
                'entry_inspections': entry_inspections
            }

            success = True
            message = "Successfully scanned {} vessels and {} jobs.".format(
                len(vessel_list),
                sum(len(jobs) for jobs in vessel_job_map.values())
            )
            if warning_lines:
                message += " Find warning(s): {}".format(" | ".join(warning_lines[:3]))
        except subprocess.CalledProcessError as e:
            data_lines, warning_lines = self._split_find_output_lines(getattr(e, 'output', ''))
            for raw_line in data_lines:
                rel_path = raw_line.strip().strip('/')
                if not rel_path:
                    continue
                raw_paths.append(rel_path)
                parts = [part for part in rel_path.split('/') if part]
                if len(parts) == 1:
                    top_level_dirs.add(parts[0])
                elif len(parts) == 2:
                    vessel_name, job_name = parts
                    top_level_dirs.add(vessel_name)
                    vessel_job_map.setdefault(vessel_name, set()).add(job_name)

            normalized_map = {}
            for vessel_name, jobs in vessel_job_map.items():
                normalized_map[vessel_name] = sorted(jobs)
            vessel_job_map = normalized_map

            vessels_with_jobs = sorted(vessel_job_map.keys())
            skipped_dirs = sorted(top_level_dirs.difference(vessels_with_jobs))
            if vessels_with_jobs:
                vessel_list = vessels_with_jobs
            else:
                vessel_list = sorted(top_level_dirs)
                skipped_dirs = []

            case_insensitive_match = self._find_case_insensitive_match(expected_vessel_name, vessel_list or sorted(top_level_dirs))
            entry_inspections = []
            names_to_inspect = []
            if expected_vessel_name:
                names_to_inspect.append(expected_vessel_name)
            if case_insensitive_match and case_insensitive_match not in names_to_inspect:
                names_to_inspect.append(case_insensitive_match)
            for vessel_name in names_to_inspect:
                entry_path = "{}/{}".format(remote_path.rstrip('/'), vessel_name)
                entry_inspections.append((vessel_name, self._inspect_remote_path_entry(ip_address, entry_path)))

            debug_info = {
                'raw_count': len(raw_paths),
                'raw_path_samples': raw_paths[:20],
                'warning_lines': warning_lines[:10],
                'top_level_dirs': sorted(top_level_dirs),
                'vessels_with_jobs': vessels_with_jobs,
                'skipped_dirs': skipped_dirs,
                'expected_vessel_name': expected_vessel_name,
                'expected_case_insensitive_match': case_insensitive_match,
                'entry_inspections': entry_inspections
            }

            if raw_paths:
                success = True
                message = "Scanned {} vessels and {} jobs with find warning(s) (exit code {}).".format(
                    len(vessel_list),
                    sum(len(jobs) for jobs in vessel_job_map.values()),
                    e.returncode
                )
                if warning_lines:
                    message += " Warnings: {}".format(" | ".join(warning_lines[:3]))
            else:
                message = "Failed to scan vessel/job tree (exit code {}):\n{}".format(e.returncode, e.output)
        except OSError as e: message = "Failed to run SSH command for vessel/job scan: {}. Is 'ssh' installed?".format(e)
        except Exception as e: message = "Unexpected error scanning vessel/job tree: {}".format(e)
        return success, vessel_list, vessel_job_map, skipped_dirs, message, debug_info

    def _list_remote_vessel_job_tree(self, ip_address, remote_path, callback):
        if not ip_address or not remote_path:
             self.master.after(0, lambda: callback(False, [], {}, [], "IP or remote path is empty.")); return
        self._log_status_from_thread("Scanning vessel/job tree in {} on {}...".format(remote_path, ip_address))
        success, vessel_list, vessel_job_map, skipped_dirs, message, debug_info = self._scan_remote_vessel_job_tree_data(ip_address, remote_path)
        if success:
            self._log_remote_scan_debug(remote_path, debug_info)
            if skipped_dirs:
                self._log_status_from_thread(
                    "Skipping {} top-level folders with no job subfolders: {}".format(
                        len(skipped_dirs), ", ".join(skipped_dirs)
                    )
                )
            self._log_status_from_thread(message)
        else:
            self._log_status_from_thread(message)
        self.master.after(0, lambda cb=callback, s=success, v=vessel_list, vm=vessel_job_map, sd=skipped_dirs, m=message: cb(s, v, vm, sd, m))

    def _detect_remote_vessels_path(self, ip_address):
        if not ip_address:
            return None, None, {}, [], "IP address is empty."
        first_successful_empty_scan = None
        for candidate_path in REMOTE_VESSELS_PATH_CANDIDATES:
            try:
                self._log_status_from_thread("Checking remote vessels path candidate: {}".format(candidate_path))
                success, vessel_list, vessel_job_map, skipped_dirs, message, debug_info = self._scan_remote_vessel_job_tree_data(ip_address, candidate_path)
                self._log_vessels_path_candidate_result(ip_address, candidate_path, success, vessel_list, message, debug_info)
                if success and vessel_list:
                    self._log_status_from_thread("Using remote vessels path: {}".format(candidate_path))
                    return candidate_path, vessel_list, vessel_job_map, skipped_dirs, message
                if success and first_successful_empty_scan is None:
                    first_successful_empty_scan = (candidate_path, vessel_list, vessel_job_map, skipped_dirs, message)
            except OSError as e:
                return None, None, {}, [], "Failed to run SSH command for vessel path detection: {}. Is 'ssh' installed?".format(e)
            except Exception as e:
                return None, None, {}, [], "Unexpected error detecting vessel path: {}".format(e)
        if first_successful_empty_scan is not None:
            candidate_path, vessel_list, vessel_job_map, skipped_dirs, message = first_successful_empty_scan
            self._log_status_from_thread("Using remote vessels path with no detected vessels: {}".format(candidate_path))
            return candidate_path, vessel_list, vessel_job_map, skipped_dirs, message
        return None, None, {}, [], "Could not find a valid remote 'vessels' directory in configured locations."

    def _detect_and_list_remote_vessel_job_tree(self, ip_address, callback):
        detected_path, vessel_list, vessel_job_map, skipped_dirs, detect_message = self._detect_remote_vessels_path(ip_address)
        if not detected_path:
            self.master.after(0, lambda: callback(False, [], {}, [], detect_message, None))
            return
        self.master.after(0, lambda: callback(True, vessel_list, vessel_job_map, skipped_dirs, detect_message, detected_path))

    def _handle_ip_change(self, event=None):
        ip = self.supervision_ip_var.get().strip()
        config_path_to_reload = self.config_path_var.get() 
        self._set_combobox_style(self.vessel_combobox, self._default_widget_bg)
        self._set_combobox_style(self.job_combobox, self._default_widget_bg)
        if not ip:
            tkMessageBox.showwarning("Missing IP", "Please enter the Supervision IP address.", parent=self.master)
            self._reset_vessel_job_state("IP address empty."); return
        if config_path_to_reload and os.path.isfile(config_path_to_reload):
             self._log_status("Connect clicked. Reloading config: {}".format(config_path_to_reload))
             self._load_config(config_path_to_reload, suppress_errors=True)
        else:
             self._log_status("Connect clicked. No config file specified, validating IP directly...")
             self._set_ssh_dependent_fields_enabled(False)
             self._validate_ip_and_connect()

    def _validate_ip_and_connect(self):
        ip = self.supervision_ip_var.get().strip(); 
        if not ip: return 
        self._log_status("Validating Supervision IP via SSH...")
        if self.ip_validation_thread and self.ip_validation_thread.is_alive():
            self._log_status("SSH validation already in progress..."); return
        self.ip_validation_thread = threading.Thread(target=self._check_ssh_connection, args=(ip, self._on_ssh_check_complete))
        self.ip_validation_thread.daemon = True; self.ip_validation_thread.start()

    def _set_combobox_style(self, combobox, background_color):
         if background_color is None: background_color = GUI_BACKGROUND_COLOR # Fallback to new GUI background
         try:
              style_name = "{}.TCombobox".format(combobox.winfo_class())
              style = ttk.Style()
              try: style.layout(style_name) 
              except tk.TclError: style.layout(style_name, style.layout('TCombobox'))
              style.configure(style_name, fieldbackground=background_color)
              combobox.configure(style=style_name); combobox.update_idletasks()
         except tk.TclError as e:
              print("Warning: Could not set combobox background using ttk style: {}".format(e))
              try: combobox.configure(background=background_color)
              except tk.TclError: pass 
         except Exception as e: print("Error setting combobox style: {}".format(e))

    def _on_ssh_check_complete(self, success, message):
        if success:
            self._log_status("IP Validated. Fetching vessel list...")
            self.vessel_combobox.config(state='readonly'); self._fetch_vessel_list()
        else:
            self._reset_vessel_job_state(message)
            tkMessageBox.showerror("SSH Connection Failed", message, parent=self.master)
            self._loaded_vessel_name = None; self._loaded_job_name = None

    def _fetch_vessel_list(self):
        ip = self.supervision_ip_var.get().strip()
        if self.list_dir_thread and self.list_dir_thread.is_alive():
            self._log_status("Directory listing already in progress..."); return
        self._active_vessel_tree_request += 1
        request_id = self._active_vessel_tree_request
        callback = lambda success, vessel_list, vessel_job_map, skipped_dirs, message, remote_root, req=request_id: self._on_vessel_list_fetched(req, success, vessel_list, vessel_job_map, skipped_dirs, message, remote_root)
        self.list_dir_thread = threading.Thread(target=self._detect_and_list_remote_vessel_job_tree, args=(ip, callback))
        self.list_dir_thread.daemon = True; self.list_dir_thread.start()

    def _on_vessel_list_fetched(self, request_id, success, dir_list, vessel_job_map, skipped_dirs, message, remote_root):
        if request_id != self._active_vessel_tree_request:
            self._log_status("Ignoring stale vessel list response.")
            return
        attempt_select = self._loaded_vessel_name
        if success:
            self._log_status("Vessel list fetched.")
            self._remote_vessel_job_map = vessel_job_map or {}
            self._remote_vessels_root = remote_root
            self.vessel_combobox['values'] = dir_list
            if not dir_list:
                 self._log_status("Warning: No vessel directories found under {}.".format(remote_root or "remote vessels path"))
                 self.vessel_combobox.set(''); self._reset_job_state("No vessels found.")
                 self._set_combobox_style(self.vessel_combobox, self._default_widget_bg) 
            else:
                 if attempt_select and attempt_select in dir_list:
                      self.vessel_selection_var.set(attempt_select)
                      self._log_status("Selected loaded/reloaded vessel: {}".format(attempt_select))
                      self.master.after_idle(self._handle_vessel_selected)
                 else:
                      if attempt_select:
                          case_match = self._find_case_insensitive_match(attempt_select, dir_list)
                          if case_match and case_match != attempt_select:
                              self._log_status("Warning: Loaded vessel '{}' not found exactly, but remote vessel '{}' differs only by case.".format(attempt_select, case_match))
                          else:
                              self._log_status("Warning: Loaded vessel '{}' not found on server.".format(attempt_select))
                          self._log_status("Available remote vessels: {}".format(self._format_debug_items(dir_list, limit=12)))
                      self.vessel_combobox.set(''); self._reset_job_state("Please select a vessel.")
                 if self.vessel_selection_var.get(): self._set_combobox_style(self.vessel_combobox, SUCCESS_BG_COLOR)
                 else: self._set_combobox_style(self.vessel_combobox, self._default_widget_bg)
                 self._loaded_vessel_name = None 
        else:
            self._log_status("Failed to fetch vessel list: {}".format(message))
            self._remote_vessel_job_map = {}
            self._remote_vessels_root = None
            self._reset_vessel_job_state("Failed to list vessels.")
            self._set_combobox_style(self.vessel_combobox, self._default_widget_bg) 
            self._loaded_vessel_name = None 

    def _handle_vessel_selected(self, event=None):
        vessel = self.vessel_selection_var.get()
        if vessel: self._set_combobox_style(self.vessel_combobox, SUCCESS_BG_COLOR)
        else: self._set_combobox_style(self.vessel_combobox, self._default_widget_bg)
        self._set_combobox_style(self.job_combobox, self._default_widget_bg)
        if not vessel:
            self._reset_job_state("No vessel selected."); self._update_segment_rows(); return
        cached_jobs = self._remote_vessel_job_map.get(vessel)
        if cached_jobs is not None:
            self._log_status("Vessel '{}' selected. Using cached job list...".format(vessel))
            self.job_combobox.config(state='readonly'); self._set_segments_enabled(False)
            self._on_job_list_fetched(vessel, True, cached_jobs, "Loaded cached job list.")
            self._update_segment_rows()
            return
        self._log_status("Vessel '{}' selected. Fetching job list...".format(vessel))
        self.job_combobox.config(state='readonly'); self._set_segments_enabled(False)
        self._fetch_job_list(vessel); self._update_segment_rows() 

    def _fetch_job_list(self, vessel_name):
        ip = self.supervision_ip_var.get().strip()
        remote_vessels_root = self._remote_vessels_root or REMOTE_VESSELS_PATH_CANDIDATES[0]
        remote_job_path = "{}/{}/".format(remote_vessels_root.rstrip('/'), vessel_name)
        if self.list_dir_thread and self.list_dir_thread.is_alive():
            self._log_status("Directory listing already in progress..."); return
        callback = lambda success, dir_list, message, selected_vessel=vessel_name: self._on_job_list_fetched(selected_vessel, success, dir_list, message)
        self.list_dir_thread = threading.Thread(target=self._list_remote_dirs, args=(ip, remote_job_path, callback))
        self.list_dir_thread.daemon = True; self.list_dir_thread.start()

    def _on_job_list_fetched(self, vessel_name, success, dir_list, message):
        if vessel_name != self.vessel_selection_var.get():
            self._log_status("Ignoring stale job list response for vessel '{}'.".format(vessel_name))
            return
        attempt_select = self._loaded_job_name
        if success:
            self._log_status("Job list fetched.")
            self.job_combobox['values'] = dir_list
            if not dir_list:
                 self._log_status("Warning: No job directories found for selected vessel.")
                 self.job_combobox.set(''); self._set_segments_enabled(False)
                 self._set_combobox_style(self.job_combobox, self._default_widget_bg) 
            else:
                 if attempt_select and attempt_select in dir_list:
                      self.job_selection_var.set(attempt_select)
                      self._log_status("Selected loaded/reloaded job: {}".format(attempt_select))
                      self.master.after_idle(self._handle_job_selected)
                 else:
                      if attempt_select: self._log_status("Warning: Loaded job '{}' not found for vessel.".format(attempt_select))
                      self.job_combobox.set(''); self._set_segments_enabled(False)
                 if self.job_selection_var.get(): self._set_combobox_style(self.job_combobox, SUCCESS_BG_COLOR)
                 else: self._set_combobox_style(self.job_combobox, self._default_widget_bg)
                 self._loaded_job_name = None 
        else:
            self._log_status("Failed to fetch job list: {}".format(message))
            self._reset_job_state("Failed to list jobs.")
            self._loaded_segments_data = None
            self._set_combobox_style(self.job_combobox, self._default_widget_bg) 
            self._loaded_job_name = None 

    def _handle_job_selected(self, event=None):
        job = self.job_selection_var.get()
        if job: self._set_combobox_style(self.job_combobox, SUCCESS_BG_COLOR)
        else: self._set_combobox_style(self.job_combobox, self._default_widget_bg)
        self._update_default_coverage_target()
        if job:
             self._log_status("Job '{}' selected.".format(job))
             self._set_segments_enabled(True); self._update_segment_rows(); self._apply_loaded_segment_data() 
        else: self._set_segments_enabled(False); self._update_segment_rows() 

    def _set_segments_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        try:
            if self.num_segments_entry: self.num_segments_entry.config(state=state)
            if self.set_segments_button: self.set_segments_button.config(state=state)
            if self.clear_segments_button: self.clear_segments_button.config(state=state)
            for seg_widgets in self.segment_widgets:
                 if 'frame' in seg_widgets:
                      for child in seg_widgets['frame'].winfo_children():
                           try:
                                if 'state' in child.configure(): child.configure(state=state)
                           except tk.TclError: pass 
        except tk.TclError: pass 
        except Exception as e: print("Error setting segment state: {}".format(e))

    def _set_ssh_dependent_fields_enabled(self, enabled):
        vessel_state = 'readonly' if enabled else 'disabled'; job_state = 'disabled' 
        try:
            if self.vessel_combobox: self.vessel_combobox.config(state=vessel_state)
            if self.job_combobox: self.job_combobox.config(state=job_state)
        except tk.TclError: pass

    def _reset_vessel_job_state(self, reason=""):
        self._log_status("Resetting Vessel/Job state. Reason: {}".format(reason))
        self.vessel_selection_var.set(''); self.job_selection_var.set('')
        self._remote_vessel_job_map = {}
        self._remote_vessels_root = None
        self._update_default_coverage_target(force=True)
        try:
            if self.vessel_combobox:
                 self.vessel_combobox['values'] = []; self.vessel_combobox.config(state='disabled')
                 self._set_combobox_style(self.vessel_combobox, self._default_widget_bg) 
            if self.job_combobox:
                 self.job_combobox['values'] = []; self.job_combobox.config(state='disabled')
                 self._set_combobox_style(self.job_combobox, self._default_widget_bg) 
            self._set_segments_enabled(False) 
        except tk.TclError: pass

    def _reset_job_state(self, reason=""):
        self._log_status("Resetting Job state. Reason: {}".format(reason))
        self.job_selection_var.set('')
        self._update_default_coverage_target(force=True)
        try:
            if self.job_combobox:
                 self.job_combobox['values'] = []; self.job_combobox.config(state='disabled')
                 self._set_combobox_style(self.job_combobox, self._default_widget_bg) 
            self._set_segments_enabled(False) 
        except tk.TclError: pass

    def _get_dynamic_default_target_path(self):
        return self._get_dynamic_default_target_path_from_names(
            self.vessel_selection_var.get(),
            self.job_selection_var.get(),
            self._remote_vessels_root
        )

    def _normalize_remote_path(self, remote_path):
        if not remote_path:
            return ""
        normalized = remote_path.strip()
        if not normalized:
            return ""
        if normalized == '/':
            return '/'
        normalized = re.sub(r'/+', '/', normalized)
        return normalized.rstrip('/')

    def _normalize_remote_component(self, value):
        if not value:
            return ""
        return str(value).strip().strip('/')

    def _get_remote_vessels_root(self, remote_vessels_root=None):
        resolved_root = remote_vessels_root or self._remote_vessels_root
        resolved_root = self._normalize_remote_path(resolved_root)
        return resolved_root if resolved_root else None

    def _get_dynamic_default_target_path_from_names(self, vessel_name_raw, job_name_raw, remote_vessels_root=None):
        vessel_name = self._normalize_remote_component(vessel_name_raw)
        job_name = self._normalize_remote_component(job_name_raw)
        resolved_root = self._get_remote_vessels_root(remote_vessels_root)
        if not vessel_name or not job_name or not resolved_root:
            return FALLBACK_SV_TARGET_DIR
        return "{}/{}/{}".format(resolved_root, vessel_name, job_name)

    def _is_remote_path_within_root(self, remote_path, root_path, allow_equal=False):
        normalized_path = self._normalize_remote_path(remote_path)
        normalized_root = self._normalize_remote_path(root_path)
        if not normalized_path or not normalized_root:
            return False
        if allow_equal and normalized_path == normalized_root:
            return True
        return normalized_path.startswith(normalized_root + '/')

    def _get_allowed_job_roots(self, vessel_name_raw, job_name_raw, remote_vessels_root=None):
        vessel_name = self._normalize_remote_component(vessel_name_raw)
        job_name = self._normalize_remote_component(job_name_raw)
        if not vessel_name or not job_name:
            return []

        candidate_roots = []
        preferred_root = self._get_remote_vessels_root(remote_vessels_root)
        if preferred_root:
            candidate_roots.append(preferred_root)
        for candidate in REMOTE_VESSELS_PATH_CANDIDATES:
            normalized_candidate = self._normalize_remote_path(candidate)
            if normalized_candidate and normalized_candidate not in candidate_roots:
                candidate_roots.append(normalized_candidate)

        allowed_roots = []
        for candidate_root in candidate_roots:
            allowed_roots.append("{}/{}/{}".format(candidate_root, vessel_name, job_name))
        return allowed_roots

    def _is_remote_path_within_selected_job(self, remote_path, vessel_name_raw, job_name_raw, remote_vessels_root=None, allow_equal=False):
        normalized_path = self._normalize_remote_path(remote_path)
        if not normalized_path:
            return False
        allowed_job_roots = self._get_allowed_job_roots(vessel_name_raw, job_name_raw, remote_vessels_root)
        for allowed_root in allowed_job_roots:
            if self._is_remote_path_within_root(normalized_path, allowed_root, allow_equal=allow_equal):
                return True
        return False

    def _get_default_coverage_target_file_from_names(self, vessel_name_raw, job_name_raw, remote_vessels_root=None):
        base_target = self._get_dynamic_default_target_path_from_names(vessel_name_raw, job_name_raw, remote_vessels_root)
        return "{}/{}".format(base_target.rstrip('/'), DEFAULT_COVERAGE_TARGET_NAME)

    def _update_default_coverage_target(self, force=False):
        new_default_target = self._get_default_coverage_target_file_from_names(
            self.vessel_selection_var.get(),
            self.job_selection_var.get()
        )
        current_value = self.coverage_target_file_var.get().strip()
        if force or not current_value or current_value == self._last_default_coverage_target:
            self.coverage_target_file_var.set(new_default_target)
        self._last_default_coverage_target = new_default_target

    def _toggle_coverage_section(self):
        if not self.coverage_section_frame:
            return
        if self.coverage_enabled_var.get():
            self.coverage_section_frame.grid()
        else:
            self.coverage_section_frame.grid_remove()

    def _update_segment_rows(self):
        initial_state = 'normal' if self.job_selection_var.get() else 'disabled'
        try:
            num_segments = int(self.num_segments_var.get())
            if num_segments < 0: raise ValueError("Number of segments cannot be negative.")
        except ValueError as e:
            self._log_status("Invalid value for Synch Segments, defaulting to 0.")
            self.num_segments_var.set("0"); num_segments = 0
        existing_data = []
        for widgets in self.segment_widgets:
             existing_data.append({
                 'source': widgets['src_var'].get() if 'src_var' in widgets else '',
                 'target': widgets['tgt_var'].get() if 'tgt_var' in widgets else '',
                 'pattern': widgets['pat_var'].get() if 'pat_var' in widgets else '*',
                 'delete': widgets['del_var'].get() if 'del_var' in widgets else False
             })
        for child in self.segments_frame.winfo_children(): child.destroy()
        self.segment_widgets = []
        current_default_target_path = self._get_dynamic_default_target_path()

        for i in range(num_segments):
            widgets = {}
            seg_frame = tk.LabelFrame(self.segments_frame, text="Segment {}".format(i+1), padx=5, pady=5, 
                                      bg=GUI_BACKGROUND_COLOR, fg="black") # fg="black" is for LabelFrame title
            seg_frame.pack(fill=tk.X, expand=False, pady=(0, 5), anchor="nw") 
            widgets['frame'] = seg_frame
            seg_frame.grid_columnconfigure(1, weight=1); seg_frame.grid_columnconfigure(2, weight=0) 

            widgets['src_label'] = tk.Label(seg_frame, text="Source Dir:", bg=GUI_BACKGROUND_COLOR)
            widgets['src_label'].grid(row=0, column=0, sticky="w", padx=(0,2), pady=(2, 1))
            widgets['src_var'] = tk.StringVar()
            widgets['src_var'].set(existing_data[i].get('source', DEFAULT_SOURCE_DIR) if i < len(existing_data) else DEFAULT_SOURCE_DIR)
            widgets['src_entry'] = tk.Entry(seg_frame, textvariable=widgets['src_var'], state=initial_state)
            widgets['src_entry'].grid(row=0, column=1, sticky="ew", padx=2, pady=(2, 1)) 
            widgets['src_browse'] = tk.Button(seg_frame, text="...", width=3, command=lambda idx=i: self._browse_local_dir(idx), state=initial_state, 
                                              bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR,
                                              activebackground=BUTTON_BACKGROUND_COLOR)
            widgets['src_browse'].grid(row=0, column=2, sticky="e", padx=(5,0), pady=(2, 1)) 

            widgets['tgt_label'] = tk.Label(seg_frame, text="SV Target Dir:", bg=GUI_BACKGROUND_COLOR)
            widgets['tgt_label'].grid(row=1, column=0, sticky="w", padx=(0, 2), pady=(1, 2))
            widgets['tgt_var'] = tk.StringVar()
            widgets['tgt_var'].set(existing_data[i].get('target', current_default_target_path) if i < len(existing_data) else current_default_target_path)
            widgets['tgt_entry'] = tk.Entry(seg_frame, textvariable=widgets['tgt_var'], state=initial_state)
            widgets['tgt_entry'].grid(row=1, column=1, sticky="ew", padx=2, pady=(1, 2)) 

            pattern_options_frame = tk.Frame(seg_frame, bg=GUI_BACKGROUND_COLOR)
            pattern_options_frame.grid(row=2, column=0, columnspan=3, sticky="w", pady=(1,0)) 

            widgets['pat_label'] = tk.Label(pattern_options_frame, text="Synch Pattern:", bg=GUI_BACKGROUND_COLOR)
            widgets['pat_label'].pack(side=tk.LEFT, padx=(0, 2)) 
            widgets['pat_var'] = tk.StringVar(value="*")
            widgets['pat_entry'] = tk.Entry(pattern_options_frame, textvariable=widgets['pat_var'], width=15, state=initial_state)
            widgets['pat_entry'].pack(side=tk.LEFT, padx=(0, 10)) 

            widgets['del_var'] = tk.BooleanVar()
            widgets['del_check'] = tk.Checkbutton(pattern_options_frame, text="--Delete", variable=widgets['del_var'], state=initial_state, 
                                                  bg=GUI_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, # Checkbutton text color
                                                  activebackground=GUI_BACKGROUND_COLOR, 
                                                  selectcolor=BUTTON_BACKGROUND_COLOR) # Color of the check box when selected
            widgets['del_check'].pack(side=tk.LEFT, padx=(0, 5)) 

            delete_desc_label = tk.Label(seg_frame, text="`--Delete` removes files in target not present in source", font=self.italic_font, fg="grey", bg=GUI_BACKGROUND_COLOR)
            delete_desc_label.grid(row=3, column=0, columnspan=3, sticky="w", padx=(0,0), pady=(0,5))

            if i < len(existing_data):
                 widgets['pat_var'].set(existing_data[i].get('pattern', '*'))
                 widgets['del_var'].set(existing_data[i].get('delete', False))
            self.segment_widgets.append(widgets)

    def _clear_segments_action(self):
        self._log_status("Clearing all segments.")
        self.num_segments_var.set("0"); self._update_segment_rows()

    def _browse_local_dir(self, index):
        initial_dir = "/"
        if index < len(self.segment_widgets):
             current_val = self.segment_widgets[index]['src_var'].get()
             if current_val and os.path.isdir(current_val): initial_dir = current_val
             elif os.path.isdir(DEFAULT_SOURCE_DIR): initial_dir = DEFAULT_SOURCE_DIR
        dirname = tkFileDialog.askdirectory(mustexist=True, title="Select Source Directory", initialdir=initial_dir, parent=self.master)
        if dirname and index < len(self.segment_widgets): self.segment_widgets[index]['src_var'].set(dirname)

    def _browse_env_dir(self):
        initial_dir = self.env_data_path_var.get()
        if not initial_dir or not os.path.isdir(initial_dir):
             initial_dir = DEFAULT_ENV_SOURCE_DIR 
             if not os.path.isdir(initial_dir): initial_dir = os.path.expanduser("~")
        dirname = tkFileDialog.askdirectory(mustexist=True, title="Select ENV Data Source Directory", initialdir=initial_dir, parent=self.master)
        if dirname: self.env_data_path_var.set(dirname)

    def _browse_coverage_file(self):
        initial_dir = self.coverage_file_path_var.get()
        if initial_dir and os.path.isfile(initial_dir):
            initial_dir = os.path.dirname(initial_dir)
        if not initial_dir or not os.path.isdir(initial_dir):
            initial_dir = DEFAULT_SOURCE_DIR
            if not os.path.isdir(initial_dir): initial_dir = os.path.expanduser("~")
        file_path = tkFileDialog.askopenfilename(
            title="Select Coverage File (.cov)",
            initialdir=initial_dir,
            filetypes=[(COVERAGE_FILE_TYPE_DESC, COVERAGE_FILE_TYPE_PATTERN), ("All files", "*.*")],
            parent=self.master
        )
        if file_path: self.coverage_file_path_var.set(file_path)

    def _validate_required_inputs(self, check_selections=True):
        errors = []
        if not self.config_path_var.get(): errors.append("xSync Config file path (.xcfg)")
        if not self.supervision_ip_var.get(): errors.append("Supervision IP")
        if check_selections:
            if not self.vessel_selection_var.get(): errors.append("Vessel Name (select from dropdown after IP validation)")
            if not self.job_selection_var.get(): errors.append("Job Name (select from dropdown after Vessel selection)")
            if self.coverage_enabled_var.get():
                if not self.coverage_file_path_var.get().strip(): errors.append("Coverage Source File (.cov)")
                if not self.coverage_target_file_var.get().strip(): errors.append("Coverage SV Target File")
        if errors:
            action = "syncing" if check_selections else "saving"
            message = "Please ensure the following are set before {}:\n- ".format(action) + "\n- ".join(errors)
            tkMessageBox.showwarning("Missing Information", message, parent=self.master); return False
        return True

    def _collect_config_data(self):
        if not hasattr(self.master, 'geometry') or not self.master.winfo_exists(): return None
        config_data = {
            'window_geometry': self.master.geometry(), 'config_path': self.config_path_var.get(),
            'supervision_ip': self.supervision_ip_var.get(), 'vessel_name': self.vessel_selection_var.get(),
            'job_name': self.job_selection_var.get(), 'num_segments': self.num_segments_var.get(),
            'scan_time_minutes': self.scan_time_var.get(), 'env_data_path': self.env_data_path_var.get(),
            'remote_vessels_root': self._remote_vessels_root,
            'coverage_enabled': self.coverage_enabled_var.get(),
            'coverage_file_path': self.coverage_file_path_var.get(),
            'coverage_target_file': self.coverage_target_file_var.get(),
            'segments': []
        }
        for widgets in self.segment_widgets:
            segment_data = {
                'source': widgets['src_var'].get() if 'src_var' in widgets else '',
                'target': widgets['tgt_var'].get() if 'tgt_var' in widgets else '',
                'pattern': widgets['pat_var'].get() if 'pat_var' in widgets else '*',
                'delete': widgets['del_var'].get() if 'del_var' in widgets else False
            }
            config_data['segments'].append(segment_data)
        return config_data

    def _apply_config_data(self, config_data, suppress_errors=False):
        if not config_data: return
        try:
            loaded_coverage_target = config_data.get('coverage_target_file', '')
            if 'window_geometry' in config_data and self.master.winfo_exists():
                 try: self.master.geometry(config_data['window_geometry'])
                 except tk.TclError as e: print("Warning: Could not apply window geometry '{}': {}".format(config_data['window_geometry'], e))
            loaded_ip = config_data.get('supervision_ip', '')
            self.supervision_ip_var.set(loaded_ip)
            self.num_segments_var.set(config_data.get('num_segments', '1'))
            scan_time_val = config_data.get('scan_time_minutes', config_data.get('scan_time', str(DEFAULT_SCAN_TIME_MINUTES)))
            self.scan_time_var.set(scan_time_val)
            self.env_data_path_var.set(config_data.get('env_data_path', ''))
            self.coverage_file_path_var.set(config_data.get('coverage_file_path', ''))
            self.coverage_enabled_var.set(bool(config_data.get('coverage_enabled', False)))
            self.coverage_target_file_var.set(loaded_coverage_target)
            if not loaded_coverage_target:
                self._update_default_coverage_target(force=True)
            self._toggle_coverage_section()
            self._loaded_vessel_name = config_data.get('vessel_name', '')
            self._loaded_job_name = config_data.get('job_name', '')
            self._loaded_segments_data = config_data.get('segments', []) 

            if not config_data.get('coverage_enabled') and config_data.get('coverage_file_path', '').strip():
                self.coverage_enabled_var.set(True)
                self._toggle_coverage_section()

            self._reset_vessel_job_state("Loading configuration...")
            if loaded_coverage_target:
                self.coverage_target_file_var.set(loaded_coverage_target)
            else:
                self._update_default_coverage_target(force=True)
            if loaded_ip:
                 self._log_status("IP address loaded, attempting auto-connect...")
                 self._validate_ip_and_connect()
            else:
                 self._log_status("Configuration loaded, but Supervision IP is missing.")
                 self._update_segment_rows(); self._apply_loaded_segment_data()
        except Exception as e:
            self._log_status("Error applying configuration: {}".format(e))
            if not suppress_errors: tkMessageBox.showerror("Config Error", "Failed to apply configuration settings: {}".format(e))
            self._loaded_vessel_name = None; self._loaded_job_name = None; self._loaded_segments_data = None
            self._update_segment_rows() 

    def _apply_loaded_segment_data(self):
         if hasattr(self, '_loaded_segments_data') and self._loaded_segments_data is not None:
              num_loaded = len(self._loaded_segments_data); num_current_widgets = len(self.segment_widgets)
              if num_current_widgets == num_loaded:
                  self._log_status("Applying loaded segment data...")
                  for i, seg_data in enumerate(self._loaded_segments_data):
                       widgets = self.segment_widgets[i]
                       widgets['src_var'].set(seg_data.get('source', DEFAULT_SOURCE_DIR))
                       saved_target = seg_data.get('target')
                       if saved_target: widgets['tgt_var'].set(saved_target)
                       widgets['pat_var'].set(seg_data.get('pattern', '*'))
                       widgets['del_var'].set(seg_data.get('delete', False))
                  self._log_status("Segment data applied.")
              else: self._log_status("ERROR: Mismatch between loaded segments ({}) and current widgets ({}). Cannot apply segment data.".format(num_loaded, num_current_widgets))
         else: self._log_status("No loaded segment data to apply.")
         self._loaded_segments_data = None 

    def _save_config(self, xcfg_file_path):
        if not self._validate_required_inputs(check_selections=False): return False
        if not xcfg_file_path:
             self._log_status("Save cancelled: No .xcfg file path specified.")
             tkMessageBox.showwarning("Save Error", "Please specify a configuration file path (.xcfg) first using 'Browse...' or 'Save Config'.", parent=self.master); return False
        if not xcfg_file_path.lower().endswith(XCFG_EXTENSION): xcfg_file_path += XCFG_EXTENSION
        xcfg_basename = os.path.basename(xcfg_file_path)
        json_filename = xcfg_basename[:-len(XCFG_EXTENSION)] + JSON_EXTENSION
        json_file_path = os.path.join(DEFAULT_CONFIG_DIR, json_filename)
        config_data = self._collect_config_data()
        if config_data is None: self._log_status("Error collecting config data (window may be closing)."); return False
        try:
            xcfg_dir_name = os.path.dirname(xcfg_file_path)
            if xcfg_dir_name and not os.path.exists(xcfg_dir_name): os.makedirs(xcfg_dir_name)
            if not os.path.exists(DEFAULT_CONFIG_DIR): os.makedirs(DEFAULT_CONFIG_DIR)
            with open(json_file_path, 'w') as f_json: json.dump(config_data, f_json, indent=4, sort_keys=True)
            self._log_status("Configuration data saved to: {}".format(json_file_path))
            try:
                 with open(xcfg_file_path, 'w') as f_xcfg:
                      f_xcfg.write("# xSync Configuration Reference File\n"); f_xcfg.write("# Data is stored in the central JSON file: {}\n".format(json_file_path)); f_xcfg.write("# Last saved: {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S")))
                 self._log_status("Configuration reference file updated: {}".format(xcfg_file_path))
            except IOError as e_xcfg: self._log_status("Warning: Could not write reference {}: {}".format(xcfg_file_path, e_xcfg))
            self._save_last_config_path(xcfg_file_path); self.config_path_var.set(xcfg_file_path); return True
        except Exception as e:
            self._log_status("Error saving configuration data to {}: {}".format(json_file_path, e))
            tkMessageBox.showerror("Save Error", "Failed to save configuration data:\n{}".format(e), parent=self.master); return False

    def _save_config_action(self):
        if not self._validate_required_inputs(check_selections=False): return
        suggested_name = ""; vessel = sanitize_for_path(self.vessel_selection_var.get()); job = sanitize_for_path(self.job_selection_var.get())
        if vessel: suggested_name += vessel
        if job: suggested_name += ("_" + job) if vessel else job
        suggested_name = suggested_name if suggested_name else "xSync_config"; suggested_name += XCFG_EXTENSION
        current_path = self.config_path_var.get()
        initial_file = os.path.basename(current_path) if current_path else suggested_name
        initial_dir = DEFAULT_CONFIG_DIR
        if not os.path.isdir(initial_dir): initial_dir = os.path.expanduser("~")
        file_path = tkFileDialog.asksaveasfilename(title="Save xSync Configuration Reference As (.xcfg)", initialdir=initial_dir, initialfile=initial_file, defaultextension=XCFG_EXTENSION, filetypes=[(XCFG_FILE_TYPE_DESC, XCFG_FILE_TYPE_PATTERN), ("All files", "*.*")], parent=self.master)
        if file_path: self._save_config(file_path)

    def _load_config(self, xcfg_file_path, suppress_errors=False):
        if not xcfg_file_path or not os.path.isfile(xcfg_file_path):
            self._log_status("Configuration reference file (.xcfg) not found: {}".format(xcfg_file_path))
            if not suppress_errors: tkMessageBox.showerror("Load Error", "Configuration reference file (.xcfg) not found:\n{}".format(xcfg_file_path), parent=self.master)
            return False
        xcfg_basename = os.path.basename(xcfg_file_path)
        json_filename = xcfg_basename[:-len(XCFG_EXTENSION)] + JSON_EXTENSION
        json_file_path = os.path.join(DEFAULT_CONFIG_DIR, json_filename)
        if not os.path.isfile(json_file_path):
             self._log_status("Associated JSON data file not found in central directory: {}".format(json_file_path))
             if not suppress_errors: tkMessageBox.showerror("Load Error", "Could not find the data file (.json) in the central config directory:\n{}\nReferenced by:\n{}".format(json_file_path, xcfg_file_path), parent=self.master)
             return False
        try:
            with open(json_file_path, 'r') as f_json: config_data = json.load(f_json)
            self._apply_config_data(config_data, suppress_errors=suppress_errors)
            self._save_last_config_path(xcfg_file_path); self.config_path_var.set(xcfg_file_path)
            self._log_status("Configuration load initiated from: {} (via {})".format(json_file_path, xcfg_file_path)); return True
        except Exception as e:
            self._log_status("Error loading configuration data from {}: {}".format(json_file_path, e))
            if not suppress_errors: tkMessageBox.showerror("Load Error", "Failed to load configuration data from JSON:\n{}".format(e), parent=self.master)
            return False

    def _browse_config(self):
        current_dir = DEFAULT_CONFIG_DIR
        if not os.path.isdir(current_dir): current_dir = os.path.expanduser("~") 
        file_path = tkFileDialog.askopenfilename(title="Select xSync Configuration Reference File", initialdir=current_dir, filetypes=[(XCFG_FILE_TYPE_DESC, XCFG_FILE_TYPE_PATTERN), ("All files", "*.*")], parent=self.master)
        if file_path: self._load_config(file_path, suppress_errors=False)

    def _save_last_config_path(self, xcfg_file_path):
        try:
            with open(LAST_CONFIG_MARKER_FILE, 'w') as f: f.write(xcfg_file_path)
        except IOError as e: print("Warning: Could not save last config path to {}: {}".format(LAST_CONFIG_MARKER_FILE, e))

    def _load_last_config(self, suppress_errors=False):
        loaded = False
        if os.path.isfile(LAST_CONFIG_MARKER_FILE):
            try:
                with open(LAST_CONFIG_MARKER_FILE, 'r') as f: last_xcfg_path = f.read().strip()
                if last_xcfg_path and os.path.isfile(last_xcfg_path):
                    self._log_status("Loading last used configuration reference: {}".format(last_xcfg_path))
                    loaded = self._load_config(last_xcfg_path, suppress_errors=suppress_errors)
                else: self._log_status("Last used config file reference not found or invalid, applying defaults.")
            except IOError as e: self._log_status("Error reading last config path marker: {}".format(e))
        else: self._log_status("No last configuration found, applying defaults.")
        if not loaded:
             self.num_segments_var.set("0"); self._update_segment_rows(); self._set_segments_enabled(False)
        return loaded

    def _start_sync_action(self):
        if self.sync_thread and self.sync_thread.is_alive():
            tkMessageBox.showwarning("Sync Busy", "Synchronization is already in progress.", parent=self.master); return
        if not self._validate_required_inputs(check_selections=True): return
        current_config_path = self.config_path_var.get()
        if not self._save_config(current_config_path): self._log_status("Sync cancelled: Failed to auto-save configuration."); return
        self._log_status("Starting manual synch...") 
        self.start_sync_button.config(state=tk.DISABLED); self.auto_sync_button.config(state=tk.DISABLED)
        config_data = self._collect_config_data()
        if not config_data:
             self._log_status("Synch failed: Could not collect config data.") 
             if self.job_selection_var.get(): self.start_sync_button.config(state=tk.NORMAL); self.auto_sync_button.config(state=tk.NORMAL)
             return
        self.sync_thread = threading.Thread(target=self._run_sync_operation, args=(config_data,))
        self.sync_thread.daemon = True; self.sync_thread.start(); self._check_sync_thread()

    def _check_sync_thread(self):
        if self.sync_thread and self.sync_thread.is_alive(): self.master.after(500, self._check_sync_thread)
        else:
            if not self.is_auto_sync_on:
                 if self.job_selection_var.get(): self.start_sync_button.config(state=tk.NORMAL); self.auto_sync_button.config(state=tk.NORMAL)
                 else: self.start_sync_button.config(state=tk.DISABLED); self.auto_sync_button.config(state=tk.DISABLED)
            self._log_status("Manual synch thread finished.") 

    def _shell_single_quote(self, value):
        if value is None:
            return "''"
        return "'{}'".format(str(value).replace("'", "'\"'\"'"))

    def _get_rsync_base_cmd(self):
        return [
            'rsync',
            '-rltD',
            '-v',
            '--stats',
            '--omit-dir-times',
            '--no-perms',
            '--no-owner',
            '--no-group'
        ]

    def _log_rsync_exit_details(self, return_code, context_label):
        details = {
            1: "Syntax/usage error.",
            2: "Protocol incompatibility.",
            3: "Errors selecting input/output files or directories.",
            10: "Error in socket I/O.",
            11: "Error in file I/O.",
            12: "Error in rsync protocol data stream.",
            13: "Errors with program diagnostics.",
            14: "Error in IPC code.",
            20: "Received SIGUSR1 or SIGINT.",
            21: "Some error returned by waitpid().",
            22: "Error allocating core memory buffers.",
            23: "Partial transfer due to error.",
            24: "Partial transfer due to vanished source files.",
            25: "The --max-delete limit stopped deletions.",
            30: "Timeout in data send/receive.",
            35: "Timeout waiting for daemon connection."
        }
        msg = details.get(return_code, "Unknown rsync exit code.")
        self._log_status_from_thread("{}: rsync exit {} ({})".format(context_label, return_code, msg))
        if return_code == 23:
            self._log_status_from_thread(
                "{}: Exit 23 often indicates permission/metadata issues on target, missing source files, or target path problems. "
                "This tool uses '--times' (via '-t') to preserve source file timestamps while avoiding owner/group/perms sync to reduce metadata failures.".format(context_label)
            )

    def _ensure_remote_directory(self, ip, target_dir):
        if not ip or not target_dir:
            self._log_status_from_thread("Remote directory check skipped: missing IP or target directory.")
            return False
        quoted_dir = self._shell_single_quote(target_dir)
        remote_cmd = "mkdir -p {}".format(quoted_dir)
        cmd = [
            'ssh',
            '-q',
            '-o', 'BatchMode=yes',
            '-o', 'ConnectTimeout={}'.format(SSH_TIMEOUT),
            '-o', 'StrictHostKeyChecking=no',
            '{}@{}'.format(SSH_USER, ip),
            remote_cmd
        ]
        try:
            with open(os.devnull, 'w') as devnull:
                exit_code = subprocess.call(cmd, stdout=devnull, stderr=devnull)
            if exit_code == 0:
                return True
            self._log_status_from_thread("Failed to create/verify remote directory '{}' (exit code {}).".format(target_dir, exit_code))
            return False
        except Exception as e:
            self._log_status_from_thread("Remote directory check failed for '{}': {}".format(target_dir, e))
            return False

    def _run_sync_operation(self, config_data):
        ip = config_data.get('supervision_ip'); segments = config_data.get('segments', [])
        coverage_enabled = bool(config_data.get('coverage_enabled', False))
        coverage_source = config_data.get('coverage_file_path', '').strip()
        coverage_target = config_data.get('coverage_target_file', '').strip()
        remote_vessels_root = self._get_remote_vessels_root(config_data.get('remote_vessels_root'))
        default_target_dir = self._get_dynamic_default_target_path_from_names(
            config_data.get('vessel_name', ''),
            config_data.get('job_name', ''),
            remote_vessels_root
        )
        if not coverage_target:
            coverage_target = self._get_default_coverage_target_file_from_names(
                config_data.get('vessel_name', ''),
                config_data.get('job_name', ''),
                remote_vessels_root
            )
        if not ip: self._log_status_from_thread("Synch ERROR: Supervision IP is not set."); return 
        if not remote_vessels_root:
            self._log_status_from_thread("Synch ERROR: Remote vessels root is not detected. Reconnect and reselect Vessel/Job before syncing.")
            return
        if not segments and not coverage_enabled:
            self._log_status_from_thread("Synch WARNING: No synchronization segments defined and no coverage file selected.")
            return
        overall_success = True 
        if coverage_enabled:
            coverage_success = self._sync_coverage_file(
                ip,
                coverage_source,
                coverage_target,
                config_data.get('vessel_name', ''),
                config_data.get('job_name', ''),
                remote_vessels_root
            )
            if not coverage_success:
                overall_success = False
        for i, segment in enumerate(segments):
            source = segment.get('source', '').strip(); target_dir = segment.get('target', '').strip()
            pattern = segment.get('pattern', '*').strip(); delete = segment.get('delete', False)
            if not source or not target_dir: self._log_status_from_thread("Synch Segment {}: Skipping - Source or Target directory is empty.".format(i+1)); continue 
            if not os.path.exists(source): self._log_status_from_thread("Synch Segment {}: ERROR - Source path does not exist: '{}'".format(i+1, source)); overall_success = False; continue 
            normalized_target_dir = self._normalize_remote_path(target_dir)
            if not self._is_remote_path_within_selected_job(
                normalized_target_dir,
                config_data.get('vessel_name', ''),
                config_data.get('job_name', ''),
                remote_vessels_root,
                allow_equal=True
            ):
                self._log_status_from_thread("Synch Segment {}: BLOCKED - Target directory '{}' is outside the selected job folder '{}'.".format(i+1, target_dir, default_target_dir))
                overall_success = False; continue
            if not self._ensure_remote_directory(ip, normalized_target_dir):
                self._log_status_from_thread("Synch Segment {}: ERROR - Cannot access/create target directory '{}' on supervision server.".format(i+1, target_dir))
                overall_success = False; continue
            source_path = source; is_dir_sync = os.path.isdir(source)
            if is_dir_sync and not source_path.endswith('/'): source_path += '/'
            remote_target = "{}@{}:{}".format(SSH_USER, ip, normalized_target_dir)
            cmd = self._get_rsync_base_cmd()
            if delete: cmd.append('--delete'); 
            if pattern and pattern != '*':
                 cmd.extend(['--filter=+ */', '--filter=+ {}'.format(pattern), '--filter=- *']); cmd.append('-m') 
                 self._log_status_from_thread("Applying pattern: {}".format(pattern))
            cmd.append(source_path); cmd.append(remote_target) 
            self._log_status_from_thread("--- Synch Segment {} Start ---".format(i+1)) 
            self._log_status_from_thread("Command: {}".format(' '.join(["'{}'".format(arg) if ' ' in arg else arg for arg in cmd])))
            segment_success = False
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)
                stdout_lines = []; stderr_lines = []
                def stream_output(pipe, prefix, output_list):
                    try:
                        for line in iter(pipe.readline, ''):
                            line_strip = line.strip()
                            if line_strip: output_list.append(line_strip); self._log_status_from_thread("{}{}".format(prefix, line_strip))
                    except Exception as e: self._log_status_from_thread("{} Stream Error: {}".format(prefix, e))
                    finally: pipe.close()
                stdout_thread = threading.Thread(target=stream_output, args=(process.stdout,"OUT: ", stdout_lines)); stderr_thread = threading.Thread(target=stream_output, args=(process.stderr,"ERR: ", stderr_lines))
                stdout_thread.daemon = True; stderr_thread.daemon = True; stdout_thread.start(); stderr_thread.start(); stdout_thread.join(); stderr_thread.join()
                return_code = process.wait()
                stats_summary = "Stats: "; stats_values = {}; stats_found = False
                for line in reversed(stdout_lines):
                     if ":" in line and any(kw in line for kw in ["Number of", "Total file", "Total bytes", "Literal data", "Matched data", "File list", "Total transferred"]):
                         key, val = line.split(":", 1); key = key.strip(); val = val.strip()
                         if key not in stats_values: stats_values[key] = val; stats_found = True
                     elif not stats_found and line.strip() == "": break
                     elif stats_found and "speedup is" in line: break
                if stats_found:
                    num_transferred = stats_values.get("Number of regular files transferred", "0"); num_created = stats_values.get("Number of created files", "0") 
                    num_deleted = stats_values.get("Number of deleted files", "0"); total_size = stats_values.get("Total file size", "0 bytes")
                    sent = stats_values.get("Total bytes sent", "0"); received = stats_values.get("Total bytes received", "0")
                    stats_summary += "Transferred: {}; Created: {}; Deleted: {}; Sent: {}; Received: {}".format(num_transferred, num_created, num_deleted, sent, received)
                if return_code == 0:
                     self._log_status_from_thread("Synch Segment {}: Completed Successfully.".format(i+1)); segment_success = True
                     if stats_found: self._log_status_from_thread(stats_summary)
                     else: self._log_status_from_thread("Stats: No transfer statistics found in output.")
                else:
                    self._log_status_from_thread("Synch Segment {}: Exited with code {}.".format(i+1, return_code))
                    self._log_rsync_exit_details(return_code, "Synch Segment {}".format(i+1))
                    overall_success = False 
            except OSError as e:
                self._log_status_from_thread("Synch Segment {}: Execution ERROR - {}".format(i+1, e)) 
                if e.errno == 2: self._log_status_from_thread("ERROR: 'rsync' command not found or not executable. Please ensure it is installed and in the system's PATH.")
                overall_success = False
            except Exception as e: self._log_status_from_thread("Synch Segment {}: Unexpected ERROR - {}".format(i+1, e)); overall_success = False 
            finally: self._log_status_from_thread("--- Synch Segment {} End ---".format(i+1)); time.sleep(0.1) 
        if overall_success: self._log_status_from_thread("Synchronization finished successfully.")
        else: self._log_status_from_thread("Synchronization finished with ERRORS.")

    def _sync_coverage_file(self, ip, coverage_source, target_file, vessel_name, job_name, remote_vessels_root):
        if not coverage_source:
            self._log_status_from_thread("Coverage: ERROR - Source file is empty.")
            return False
        if not os.path.isfile(coverage_source):
            self._log_status_from_thread("Coverage: ERROR - Source file does not exist: '{}'".format(coverage_source))
            return False
        if not coverage_source.lower().endswith('.cov'):
            self._log_status_from_thread("Coverage: ERROR - Selected file is not a .cov file: '{}'".format(coverage_source))
            return False
        if not target_file or target_file.startswith(FALLBACK_SV_TARGET_DIR):
            self._log_status_from_thread("Coverage: ERROR - Invalid supervision target directory. Please verify Vessel/Job selection.")
            return False

        normalized_target_file = self._normalize_remote_path(target_file)
        coverage_target_dir = os.path.dirname(normalized_target_file)
        if not coverage_target_dir:
            self._log_status_from_thread("Coverage: ERROR - Could not determine target directory from '{}'".format(target_file))
            return False
        if not self._is_remote_path_within_selected_job(
            coverage_target_dir,
            vessel_name,
            job_name,
            remote_vessels_root,
            allow_equal=True
        ):
            self._log_status_from_thread("Coverage: BLOCKED - Target file '{}' is outside the selected job folder for vessel '{}' and job '{}'.".format(target_file, vessel_name, job_name))
            return False
        if not self._ensure_remote_directory(ip, coverage_target_dir):
            self._log_status_from_thread("Coverage: ERROR - Cannot access/create target directory '{}' on supervision server.".format(coverage_target_dir))
            return False

        remote_file = "{}@{}:{}".format(SSH_USER, ip, normalized_target_file)
        cmd = self._get_rsync_base_cmd() + [coverage_source, remote_file]
        self._log_status_from_thread("--- Coverage Sync Start ---")
        self._log_status_from_thread("Coverage command: {}".format(' '.join(["'{}'".format(arg) if ' ' in arg else arg for arg in cmd])))
        self._log_status_from_thread("Coverage: rsync transfers only when the source file has changed (size/timestamp).")
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)
            stdout, stderr = process.communicate()
            transferred_count = None
            for line in (stdout or '').splitlines():
                line_strip = line.strip()
                if line_strip:
                    self._log_status_from_thread("COV OUT: {}".format(line_strip))
                if line_strip.startswith("Number of regular files transferred:"):
                    try:
                        transferred_count = int(line_strip.split(":", 1)[1].strip())
                    except Exception:
                        transferred_count = None
            for line in (stderr or '').splitlines():
                line_strip = line.strip()
                if line_strip:
                    self._log_status_from_thread("COV ERR: {}".format(line_strip))
            if process.returncode == 0:
                if transferred_count == 0:
                    self._log_status_from_thread("Coverage: No changes detected, target file left unchanged.")
                else:
                    self._log_status_from_thread("Coverage: Synced '{}' to '{}'".format(os.path.basename(coverage_source), target_file))
                self._log_status_from_thread("--- Coverage Sync End ---")
                return True
            self._log_status_from_thread("Coverage: Sync exited with code {}.".format(process.returncode))
            self._log_rsync_exit_details(process.returncode, "Coverage")
            self._log_status_from_thread("--- Coverage Sync End ---")
            return False
        except OSError as e:
            self._log_status_from_thread("Coverage: Execution ERROR - {}".format(e))
            if e.errno == 2:
                self._log_status_from_thread("ERROR: 'rsync' command not found or not executable. Please ensure it is installed and in the system's PATH.")
            self._log_status_from_thread("--- Coverage Sync End ---")
            return False
        except Exception as e:
            self._log_status_from_thread("Coverage: Unexpected ERROR - {}".format(e))
            self._log_status_from_thread("--- Coverage Sync End ---")
            return False

    def _toggle_auto_sync(self):
        if self.sync_thread and self.sync_thread.is_alive():
            tkMessageBox.showwarning("Sync Busy", "Cannot change Auto Sync mode while manual sync is running.", parent=self.master); return
        if self.is_auto_sync_on:
            self.is_auto_sync_on = False
            if self.auto_sync_timer: self.master.after_cancel(self.auto_sync_timer); self.auto_sync_timer = None
            self.auto_sync_status_var.set("Auto Synch OFF"); self.auto_sync_label.config(fg="orange")
            self.auto_sync_button.config(text="Start Auto Synch")
            if self.job_selection_var.get(): self.start_sync_button.config(state=tk.NORMAL); self.auto_sync_button.config(state=tk.NORMAL)
            else: self.start_sync_button.config(state=tk.DISABLED); self.auto_sync_button.config(state=tk.DISABLED)
            self._log_status("Auto Synch stopped.")
        else:
            if not self._validate_required_inputs(check_selections=True): return
            current_config_path = self.config_path_var.get()
            if not self._save_config(current_config_path): self._log_status("Auto Synch cancelled: Failed to auto-save configuration."); return
            try:
                scan_interval_min = int(self.scan_time_var.get())
                if scan_interval_min <= 0: raise ValueError("Scan time must be positive.")
            except ValueError: tkMessageBox.showerror("Invalid Input", "Please enter a valid positive integer for Synch Scan Time (minutes).", parent=self.master); return
            self.is_auto_sync_on = True
            self.auto_sync_status_var.set("Auto Synch ON"); self.auto_sync_label.config(fg="green")
            self.start_sync_button.config(state=tk.DISABLED); self.auto_sync_button.config(text="Stop Auto Synch")
            self._log_status("Auto Synch started (Interval: {} minutes). First sync starting now...".format(scan_interval_min))
            self._run_auto_sync_cycle()

    def _run_auto_sync_cycle(self):
        if not self.is_auto_sync_on: return
        if self.sync_thread and self.sync_thread.is_alive(): self._log_status("Auto Synch Cycle: Previous sync still running, skipping this cycle.")
        else:
            self._log_status("Auto Synch Cycle: Starting sync operation.")
            config_data = self._collect_config_data()
            if not config_data: self._log_status("Auto Synch Cycle: Failed to collect config data, skipping.")
            elif not config_data.get('supervision_ip') or not config_data.get('vessel_name') or not config_data.get('job_name'):
                 self._log_status("Auto Synch Cycle: Missing required IP/Vessel/Job selection, stopping Auto Synch.")
                 self._toggle_auto_sync(); return
            else:
                self.sync_thread = threading.Thread(target=self._run_sync_operation, args=(config_data,))
                self.sync_thread.daemon = True; self.sync_thread.start()
        if self.is_auto_sync_on:
             try:
                scan_interval_min = int(self.scan_time_var.get())
                if scan_interval_min <= 0: scan_interval_min = DEFAULT_SCAN_TIME_MINUTES
                scan_interval_ms = scan_interval_min * 60 * 1000
             except ValueError: scan_interval_ms = DEFAULT_SCAN_TIME_MINUTES * 60 * 1000
             self._log_status("Auto Synch: Scheduling next run in {} ms ({} min)".format(scan_interval_ms, scan_interval_min))
             self.auto_sync_timer = self.master.after(scan_interval_ms, self._run_auto_sync_cycle)

    def _on_closing(self):
        if self.is_auto_sync_on:
             if tkMessageBox.askyesno("Exit Confirmation", "Auto Synch is running. Are you sure you want to exit?", parent=self.master):
                  self.is_auto_sync_on = False
                  if self.auto_sync_timer: self.master.after_cancel(self.auto_sync_timer)
                  self._save_geometry(); self.master.destroy()
             else: return
        else:
            if self.sync_thread and self.sync_thread.is_alive():
                 if not tkMessageBox.askyesno("Exit Confirmation", "A manual synch might be running. Exit anyway?", parent=self.master): return 
            self._save_geometry(); self.master.destroy()

    def _save_geometry(self):
        xcfg_path = self.config_path_var.get()
        if xcfg_path and self.master.winfo_exists():
             if not os.path.exists(xcfg_path): print("Warning: Cannot save geometry, config file reference does not exist: {}".format(xcfg_path)); return
             xcfg_basename = os.path.basename(xcfg_path)
             json_filename = xcfg_basename[:-len(XCFG_EXTENSION)] + JSON_EXTENSION
             json_path = os.path.join(DEFAULT_CONFIG_DIR, json_filename)
             if os.path.exists(json_path):
                 try:
                      with open(json_path, 'r') as f: config_data = json.load(f)
                      config_data['window_geometry'] = self.master.geometry()
                      with open(json_path, 'w') as f: json.dump(config_data, f, indent=4, sort_keys=True)
                      print("Saved window geometry to {}".format(json_path))
                 except Exception as e: print("Warning: Could not save window geometry to {}: {}".format(json_path, e))
             else: print("Warning: Cannot save geometry, associated JSON file not found in central dir: {}. Save the config first.".format(json_path))

    def _browse_env_dir(self): # Consolidated earlier
        initial_dir = self.env_data_path_var.get()
        if not initial_dir or not os.path.isdir(initial_dir):
             initial_dir = DEFAULT_ENV_SOURCE_DIR 
             if not os.path.isdir(initial_dir): initial_dir = os.path.expanduser("~")
        dirname = tkFileDialog.askdirectory(mustexist=True, title="Select ENV Data Source Directory", initialdir=initial_dir, parent=self.master)
        if dirname: self.env_data_path_var.set(dirname)

    def _move_zip_env_action(self):
        source_dir = self.env_data_path_var.get()
        if not source_dir or not os.path.isdir(source_dir):
            tkMessageBox.showerror("Error", "Please select a valid ENV data source directory first.", parent=self.master); return
        if self.env_thread and self.env_thread.is_alive():
            tkMessageBox.showwarning("Busy", "ENV data processing is already in progress.", parent=self.master); return
        self._log_status("Starting ENV data move and compress process...")
        self.move_zip_env_button.config(state=tk.DISABLED)
        self.env_thread = threading.Thread(target=self._run_move_zip_env, args=(source_dir,))
        self.env_thread.daemon = True; self.env_thread.start(); self._check_env_thread()

    def _check_env_thread(self):
        if self.env_thread and self.env_thread.is_alive(): self.master.after(500, self._check_env_thread)
        else: self.move_zip_env_button.config(state=tk.NORMAL); self._log_status("ENV data processing thread finished.")

    def _run_move_zip_env(self, source_dir):
        target_dir = DEFAULT_ENV_TARGET_DIR; env_pattern = os.path.join(source_dir, "Env*")
        moved_files_count = 0; compressed_files_count = 0; errors = False
        try:
            if not os.path.exists(target_dir): os.makedirs(target_dir); self._log_status_from_thread("Created ENV target directory: {}".format(target_dir))
            env_files = glob.glob(env_pattern)
            if not env_files: self._log_status_from_thread("No 'Env*' files found in '{}'.".format(source_dir)); return 
            self._log_status_from_thread("Found {} 'Env*' files to process.".format(len(env_files)))
            for src_path in env_files:
                if os.path.isfile(src_path): 
                    filename = os.path.basename(src_path); dest_path = os.path.join(target_dir, filename)
                    try:
                        shutil.move(src_path, dest_path); self._log_status_from_thread("Moved '{}' to '{}'".format(filename, target_dir)); moved_files_count += 1
                        try:
                            cmd = ['pigz', dest_path]; self._log_status_from_thread("Compressing '{}' with pigz...".format(filename))
                            with open(os.devnull, 'w') as DEVNULL: subprocess.check_call(cmd, stdout=DEVNULL, stderr=subprocess.STDOUT)
                            self._log_status_from_thread("Compressed '{}' successfully.".format(filename)); compressed_files_count += 1
                        except subprocess.CalledProcessError as e: self._log_status_from_thread("ERROR compressing '{}' with pigz (exit code {}): {}".format(filename, e.returncode, e.output or 'No output')); errors = True
                        except OSError as e:
                             if e.errno == 2: self._log_status_from_thread("ERROR: 'pigz' command not found. Please install pigz.")
                             else: self._log_status_from_thread("ERROR running pigz on '{}': {}".format(filename, e))
                             errors = True
                        except Exception as e: self._log_status_from_thread("ERROR during pigz compression of '{}': {}".format(filename, e)); errors = True
                    except Exception as e: self._log_status_from_thread("ERROR moving '{}': {}".format(filename, e)); errors = True
            self._log_status_from_thread("Finished processing ENV files. Moved: {}, Compressed: {}.".format(moved_files_count, compressed_files_count))
        except Exception as e: self._log_status_from_thread("ERROR during ENV processing: {}".format(e)); errors = True
        finally:
             if errors: self._log_status_from_thread("ENV data processing finished with ERRORS.")
             else: self._log_status_from_thread("ENV data processing finished successfully.")

if __name__ == "__main__":
    try: import fnmatch
    except ImportError: print("ERROR: 'fnmatch' module not found."); sys.exit(1)
    try:
        with open(os.devnull, 'w') as DEVNULL: subprocess.check_call(['which', 'rsync'], stdout=DEVNULL, stderr=DEVNULL)
    except (subprocess.CalledProcessError, OSError):
         print("ERROR: 'rsync' command not found.")
         print("Please install it on this system (e.g., 'sudo dnf install rsync' or 'sudo apt-get install rsync').")
         temp_root = tk.Tk(); temp_root.withdraw() 
         tkMessageBox.showerror("Dependency Error", "'rsync' command not found.\nPlease install it and restart xSync.", parent=temp_root)
         temp_root.destroy(); sys.exit(1)
    try:
        with open(os.devnull, 'w') as DEVNULL: subprocess.check_call(['which', 'pigz'], stdout=DEVNULL, stderr=DEVNULL)
    except (subprocess.CalledProcessError, OSError): print("WARNING: 'pigz' command not found. The 'Move/Zip ENV' button will move files but cannot compress them.")
    root = tk.Tk()
    app = XSyncApp(root)
    root.mainloop()
