#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Ai assisted Code by RBolisay
# --- xdbRead GUI ---
# Python 2.7 script using Tkinter.
# Supports dbRead and dumpDataclass commands based on segment type, using shared parameters.
# V3.6 - Changed config dir, added description, renamed remove button & title.
# V3.5 - Corrected dbRead awk script generation to handle space-separated input.
#        (Based on user feedback and sample output analysis)

import Tkinter as tk
import ttk
import tkFileDialog
import tkMessageBox
import os
import json
import re
import subprocess
import threading
import Queue
import sys
import datetime
from functools import partial
import collections # For OrderedDict
import tkFont # For button font modification

# --- Constants ---
DB_DIR = "/usr/local/trinop/dbase" # Set the correct path directly
# MODIFIED: Changed config directory to absolute path
# Ensure this directory exists and the script has write permissions
CONFIG_DIR = "/usr/local/trinop/dbase/links/qcfiles/Misc/xdbRead"
DEFAULT_CSV_DIR = "/usr/local/trinop/dbase/links/qcfiles/DBREAD/CSV/"

# Debugging flag for DB listing
DEBUG_DB_LISTING = True # Set to True to print debug info during DB scan

LAST_CONFIG_FILE = os.path.join(CONFIG_DIR, ".last_config")
JSON_EXT = ".json"

# --- Data Type Lists ---
DBREAD_DATA_TYPES = sorted([
    "auxShotData", "buoyPositionData", "currentMeterPosData", "depthData",
    "ditherTesQcData", "estimatorPosData", "gundata", "gyroData",
    "heavePitchRollData", "rgpsData", "shotData", "soundSpeedData",
    "sourcePositionData",
    "speedLogData", "ssePosData", "tensionData", "ultraTideData",
    "vesselPositionData"
])

DUMP_DATA_TYPES = sorted([
    "EstimatorPos", "DitherTesQc", "UltraTide", "WaterDepth", "GPSPositionData",
    "AuxShotData", "GyroData|QfinData", "GunposData", "GunData", "BoatPos",
    "FloatPos", "SourcePos", "CurrentMeter", "HeavePitchRollData",
    "SteeringPointData", "SoundVelocityData", "VesselTimingQcData"
])

try:
    reload(sys); sys.setdefaultencoding('utf-8')
except NameError: pass
except Exception as e: print("Note: Error setting default encoding: {}".format(e))


# --- Main Application Class ---
class XdbReadApp:
    def __init__(self, root):
        self.root = root
        # MODIFIED: Renamed GUI Title and updated version
        self.root.title("xdbRead/xdumpDataClass Tool v3.6")
        self.root.geometry("980x770") # Adjusted initial height slightly for description
        self.root.configure(bg="#B4C8E1") # GUI Background Color

        # --- Tkinter Variables ---
        self.config_name_var = tk.StringVar()
        self.csv_dir_var = tk.StringVar(value=DEFAULT_CSV_DIR)
        self.default_csv_name_var = tk.StringVar()

        # Shared Parameters (used by all segments as base)
        self.shared_db_var = tk.StringVar()
        self.shared_line_var = tk.StringVar()
        self.shared_subl_var = tk.StringVar()
        self.shared_fshot_var = tk.StringVar(value="-999")
        self.shared_lshot_var = tk.StringVar(value="99999")
        self.shared_grid_var = tk.IntVar(value=0) # Grid applies ONLY if segment is dbRead

        # --- Internal State Variables ---
        self.segment_widget_refs = collections.OrderedDict()
        self.csv_col_entries = []
        self.next_seg_id = 0
        self.canvas = None
        self.segments_inner_frame = None
        self.running_process = None
        self.status_queue = Queue.Queue()

        # Font not needed for new remove button style
        # self.remove_button_font = None

        self._create_dirs()
        self.configure_styles() # Call style configuration
        self.create_widgets()
        self.load_last_config_on_startup()
        self.check_status_queue()

    def _create_dirs(self):
        # Ensure consistent 4-space indentation
        # Now also checks the potentially absolute CONFIG_DIR
        for d in [CONFIG_DIR, DEFAULT_CSV_DIR]:
            if not os.path.exists(d):
                try:
                    os.makedirs(d)
                    print("Created directory: {}".format(d))
                except OSError as e:
                    # Provide more context on permissions error
                    log_msg = "ERROR: Could not create dir: {}\n{}".format(e.filename, e.strerror)
                    if "permission denied" in e.strerror.lower():
                         log_msg += "\n(Check write permissions for the script user in the parent directory)"
                    print(log_msg)
                    # Optionally, show a GUI error if appropriate, e.g., for CONFIG_DIR failure
                    if d == CONFIG_DIR:
                         tkMessageBox.showwarning("Directory Error", "Could not create required config directory:\n{}\n\nPlease check permissions or create it manually.".format(CONFIG_DIR), parent=self.root)

    def configure_styles(self):
        # Ensure consistent 4-space indentation
        style = ttk.Style()
        gui_bg_color = "#B4C8E1"
        button_bg_color = "#8DA9CC"
        button_fg_color = "black"

        # Configure a base style for ttk widgets to inherit background
        style.configure('.', background=gui_bg_color, foreground='black') # Default foreground for readability

        # Specific ttk widget styling
        style.configure('TFrame', background=gui_bg_color)
        style.configure('TLabel', background=gui_bg_color, foreground='black')
        
        # For ttk.LabelFrame - use 'TLabelframe' (lowercase 'f')
        style.configure('TLabelframe', background=gui_bg_color)
        style.configure('TLabelframe.Label', background=gui_bg_color, foreground='black') # Label of LabelFrame
        
        style.configure('TButton', background=button_bg_color, foreground=button_fg_color)
        style.map('TButton',
                  background=[('active', button_bg_color), ('pressed', button_bg_color)],
                  foreground=[('active', button_fg_color), ('pressed', button_fg_color)])

        style.configure('TEntry', fieldbackground='white', foreground='black') # Entries typically have white background
        style.configure('TCombobox', fieldbackground='white', foreground='black')
        style.map('TCombobox', fieldbackground=[('readonly','white')]) # Ensure readonly combobox is also white

        style.configure('TCheckbutton', background=gui_bg_color, foreground='black')
        style.configure('TScrollbar', background=gui_bg_color, troughcolor=button_bg_color)


    def create_widgets(self):
        # Ensure consistent 4-space indentation
        main_frame = ttk.Frame(self.root, padding="10", style='TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- MODIFIED: Updated Description Label ---
        desc_text = ("Extract Data from Database to output to CSV using dbRead and dumpDataClass.\n"
                     "Note: 'Data Type Header' entries are case-sensitive and must precisely match the target header names from the database output.")
        # Using justify=tk.LEFT for potentially multi-line text
        desc_label = ttk.Label(main_frame, text=desc_text, justify=tk.LEFT, relief="groove", padding=5, style='TLabel')
        desc_label.pack(fill=tk.X, pady=(0, 10)) # Pad below the label

        # --- Config Section ---
        config_frame = ttk.Frame(main_frame, style='TFrame')
        config_frame.pack(fill=tk.X, pady=5)
        ttk.Label(config_frame, text="Config Name:", style='TLabel').pack(side=tk.LEFT, padx=5)
        config_entry = ttk.Entry(config_frame, textvariable=self.config_name_var, width=30)
        config_entry.pack(side=tk.LEFT, padx=5)
        save_button = ttk.Button(config_frame, text="Save Config", command=self.save_config, style='TButton')
        save_button.pack(side=tk.LEFT, padx=5)
        browse_button = ttk.Button(config_frame, text="Browse Config", command=self.browse_load_config, style='TButton')
        browse_button.pack(side=tk.LEFT, padx=5)

        # --- CSV Output Section ---
        csv_frame = ttk.Frame(main_frame, style='TFrame')
        csv_frame.pack(fill=tk.X, pady=5)
        ttk.Label(csv_frame, text="CSV output directory:", style='TLabel').pack(side=tk.LEFT, padx=5)
        csv_entry = ttk.Entry(csv_frame, textvariable=self.csv_dir_var, width=60)
        csv_entry.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        csv_browse_button = ttk.Button(csv_frame, text="Browse...", command=self.browse_csv_dir, style='TButton')
        csv_browse_button.pack(side=tk.LEFT, padx=5)

        csv_name_frame = ttk.Frame(main_frame, style='TFrame')
        csv_name_frame.pack(fill=tk.X, pady=2)
        ttk.Label(csv_name_frame, text="Default CSV Name Format:", style='TLabel').pack(side=tk.LEFT, padx=5)
        ttk.Label(csv_name_frame, textvariable=self.default_csv_name_var, foreground="grey", style='TLabel').pack(side=tk.LEFT, padx=5) # Keeping grey for this specific label
        self.shared_line_var.trace("w", self.update_default_csv_name)
        self.shared_subl_var.trace("w", self.update_default_csv_name)
        self.update_default_csv_name()

        # --- Shared Parameters Section ---
        shared_param_frame = ttk.LabelFrame(main_frame, text="Shared Parameters (Used for all segments)", padding="10", style='TLabelframe') # Use TLabelframe style
        shared_param_frame.pack(fill=tk.X, pady=5)

        # Row 1: DB, Line, Subl
        param_row1 = ttk.Frame(shared_param_frame, style='TFrame')
        param_row1.pack(fill=tk.X, pady=2)
        ttk.Label(param_row1, text="Database:", width=10, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=5)
        self.db_combobox_shared = ttk.Combobox(param_row1, textvariable=self.shared_db_var, width=25, state='readonly')
        self.db_combobox_shared.pack(side=tk.LEFT, padx=5)
        ttk.Label(param_row1, text="Line Name:", width=10, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=(20, 5))
        line_entry_shared = ttk.Entry(param_row1, textvariable=self.shared_line_var, width=15)
        line_entry_shared.pack(side=tk.LEFT, padx=5)
        ttk.Label(param_row1, text="Subline:", width=8, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=(20, 5))
        subl_entry_shared = ttk.Entry(param_row1, textvariable=self.shared_subl_var, width=10)
        subl_entry_shared.pack(side=tk.LEFT, padx=5)

        # Row 2: fshot, lshot, grid
        param_row2 = ttk.Frame(shared_param_frame, style='TFrame')
        param_row2.pack(fill=tk.X, pady=2)
        ttk.Label(param_row2, text="First Shot:", width=10, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=5)
        fshot_entry_shared = ttk.Entry(param_row2, textvariable=self.shared_fshot_var, width=8)
        fshot_entry_shared.pack(side=tk.LEFT, padx=5)
        ttk.Label(param_row2, text="Last Shot:", width=10, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=(20,5))
        lshot_entry_shared = ttk.Entry(param_row2, textvariable=self.shared_lshot_var, width=8)
        lshot_entry_shared.pack(side=tk.LEFT, padx=5)

        # Grid Checkbox
        self.grid_check_shared = ttk.Checkbutton(param_row2, text="-grid (for dbRead segments only)", variable=self.shared_grid_var, state=tk.NORMAL, style='TCheckbutton')
        self.grid_check_shared.pack(side=tk.LEFT, padx=(20, 5))

        # Populate DB list
        self.populate_databases()

        # --- Add Segment Buttons ---
        seg_control_frame = ttk.Frame(main_frame, style='TFrame')
        seg_control_frame.pack(fill=tk.X, pady=(10, 0))
        add_dbread_button = ttk.Button(seg_control_frame, text="Add dbRead Segment", command=lambda: self.add_segment('dbRead'), style='TButton')
        add_dbread_button.pack(side=tk.LEFT, padx=5)
        add_dump_button = ttk.Button(seg_control_frame, text="Add dumpDataclass Segment", command=lambda: self.add_segment('dumpDataclass'), style='TButton')
        add_dump_button.pack(side=tk.LEFT, padx=5)
        clear_all_button = ttk.Button(seg_control_frame, text="Clear All Segments", command=self.clear_all_segments_action, style='TButton')
        clear_all_button.pack(side=tk.LEFT, padx=5)

        # --- Segment Configuration Area ---
        segments_outer_frame = ttk.LabelFrame(main_frame, text="Segment Configuration", padding="5", borderwidth=1, relief="sunken", style='TLabelframe') # Use TLabelframe style
        segments_outer_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.canvas = tk.Canvas(segments_outer_frame, borderwidth=0, bg="#B4C8E1", highlightthickness=0) # Canvas background
        self.segments_inner_frame = ttk.Frame(self.canvas, style='TFrame') # Inner frame background
        scrollbar = ttk.Scrollbar(segments_outer_frame, orient=tk.VERTICAL, command=self.canvas.yview, style='TScrollbar')
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas_frame_id = self.canvas.create_window((0, 0), window=self.segments_inner_frame, anchor="nw")
        self.segments_inner_frame.bind("<Configure>", self.on_inner_frame_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)

        # --- Status Area ---
        status_frame = ttk.LabelFrame(main_frame, text="Status / Errors", padding="5", style='TLabelframe') # Use TLabelframe style
        status_frame.pack(fill=tk.BOTH, pady=5, expand=False)
        self.status_text = tk.Text(status_frame, height=6, wrap=tk.WORD, state=tk.DISABLED, relief="sunken", borderwidth=1, font=("Courier", 9), bg="#B4C8E1", fg="black") # Status text background and foreground
        status_scroll = ttk.Scrollbar(status_frame, command=self.status_text.yview, style='TScrollbar')
        self.status_text.config(yscrollcommand=status_scroll.set)
        self.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        status_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Action Buttons ---
        action_outer_frame = ttk.Frame(main_frame, style='TFrame')
        action_outer_frame.pack(fill=tk.X, pady=10)
        action_inner_frame = ttk.Frame(action_outer_frame, style='TFrame')
        action_inner_frame.pack(anchor='center')
        
        # Create a specific style for Large buttons if not already defined or to override
        large_button_style = ttk.Style()
        large_button_style.configure('Large.TButton', padding=6, background="#8DA9CC", foreground="black")
        large_button_style.map('Large.TButton',
                               background=[('active', "#8DA9CC"), ('pressed', "#8DA9CC")],
                               foreground=[('active', "black"), ('pressed', "black")])
                               
        self.start_button = ttk.Button(action_inner_frame, text="Start Processing", command=self.start_processing, style='Large.TButton')
        self.start_button.pack(side=tk.LEFT, padx=10)
        self.cancel_button = ttk.Button(action_inner_frame, text="Cancel Process", command=self.cancel_processing, state=tk.DISABLED, style='Large.TButton')
        self.cancel_button.pack(side=tk.LEFT, padx=10)

    # --- Scrollbar Helpers ---
    # (No changes needed here)
    def on_inner_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_frame_id, width=event.width)

    # --- Helpers ---
    # (No changes needed here)
    def log_status(self, message):
        # ... (same as before) ...
        try:
            message_str = str(message)
        except Exception:
            message_str = repr(message)
        if hasattr(self, 'status_queue') and self.status_queue:
            self.status_queue.put(message_str)
        else:
            print("Log (pre-queue): {}".format(message_str))

    def _update_status_widget(self, message):
        # ... (same as before) ...
        try:
            if hasattr(self, 'status_text') and self.status_text.winfo_exists():
                self.status_text.config(state=tk.NORMAL)
                self.status_text.insert(tk.END, message + "\n")
                self.status_text.see(tk.END)
                self.status_text.config(state=tk.DISABLED)
        except tk.TclError as e:
            print("TclError updating status widget: {}".format(e))
        except Exception as e:
            print("Error updating status widget: {}".format(e))

    def check_status_queue(self):
        # ... (same as before) ...
        try:
            if hasattr(self, 'status_queue') and self.status_queue:
                while True:
                    self._update_status_widget(self.status_queue.get_nowait())
        except Queue.Empty:
            pass
        except Exception as e:
            print("Error checking status queue: {}".format(e))
        finally:
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.root.after(100, self.check_status_queue)

    def update_default_csv_name(self, *args):
        # ... (same as before) ...
        line = self.shared_line_var.get().strip()
        subl = self.shared_subl_var.get().strip()
        num_subl = ""
        if subl:
            match = re.search(r'\d+$', subl)
            if match:
                num_subl = match.group(0)
            else:
                num_subl_temp = re.sub(r'^\D+', '', subl)
                if num_subl_temp:
                    num_subl = num_subl_temp
                elif subl:
                    num_subl = subl
        if line and num_subl:
            safe_line = re.sub(r'[^\w\-.]', '_', line)
            safe_subl = re.sub(r'[^\w\-.]', '_', num_subl)
            self.default_csv_name_var.set("{}_{}_dbxtract.csv".format(safe_subl, safe_line))
        else:
            self.default_csv_name_var.set("")

    def populate_databases(self):
        # ... (same as before) ...
        dbs = []
        standard_test_dbs = ["dbTest", "dbtest"]
        prefixes_to_check = ("dbof", "dbt") # Lowercase

        if DEBUG_DB_LISTING:
            print("--- Populating Databases ---")
            print("DB_DIR:", DB_DIR)

        try:
            if os.path.isdir(DB_DIR):
                if DEBUG_DB_LISTING:
                    print("DB_DIR exists.")
                dir_contents = os.listdir(DB_DIR)
                if DEBUG_DB_LISTING:
                    print("Raw Contents:", dir_contents)

                dbs = [d for d in dir_contents
                           if os.path.isdir(os.path.join(DB_DIR, d))
                           and d.lower().startswith(prefixes_to_check)]

                if DEBUG_DB_LISTING:
                    print("Filtered Dirs matching prefixes {}: {}".format(prefixes_to_check, dbs))
            else:
                self.log_status("Warning: Database directory not found: {}".format(DB_DIR))
                if DEBUG_DB_LISTING:
                    print("DB_DIR does not exist or is not a directory.")
        except OSError as e:
            permission_error = "permission denied" in str(e).lower()
            log_msg = "Error reading DB dir {}: {}".format(DB_DIR, e)
            if permission_error:
                log_msg += " (Check Read Permissions for the script user)"
            self.log_status(log_msg)
            if DEBUG_DB_LISTING:
                print("OSError listing DB_DIR:", e)
        except Exception as e:
            self.log_status("Unexpected error listing DBs: {}".format(e))
            if DEBUG_DB_LISTING:
                print("Unexpected error listing DBs:", e)

        all_dbs = sorted(list(set(dbs + standard_test_dbs)))
        if DEBUG_DB_LISTING:
            print("Final DB List (incl. test):", all_dbs)

        db_values = tuple(all_dbs)
        if hasattr(self, 'db_combobox_shared') and self.db_combobox_shared:
            self.db_combobox_shared['values'] = db_values
            if all_dbs:
                if not self.shared_db_var.get():
                    self.shared_db_var.set(all_dbs[0])
            else:
                if not self.shared_db_var.get():
                    self.shared_db_var.set("")
                self.log_status("Warning: No databases found (check path/permissions/prefixes/filter).")
        else:
            self.log_status("Warning: Shared DB combobox not ready during populate_databases.")
        if DEBUG_DB_LISTING:
            print("--- Finished Populating ---")

    def browse_csv_dir(self):
        # ... (same as before) ...
        initial = self.csv_dir_var.get()
        initial = initial if os.path.isdir(initial) else DEFAULT_CSV_DIR
        if not os.path.isdir(initial):
            initial = os.path.expanduser("~")
        dir_p = tkFileDialog.askdirectory(initialdir=initial, title="Select CSV Output Directory", parent=self.root)
        if dir_p:
            self.csv_dir_var.set(dir_p)
            self.log_status("CSV output directory set to: {}".format(dir_p))

    # --- Config Load/Save/Browse ---
    def _write_last_config(self, config_name):
        # ... (same as before) ...
        try:
            # Check if CONFIG_DIR is writable before attempting write
            if not os.path.exists(CONFIG_DIR):
                 self.log_status("Warn: Config directory {} does not exist. Cannot write last config.".format(CONFIG_DIR))
                 return
            if not os.access(CONFIG_DIR, os.W_OK):
                 self.log_status("Warn: No write permission for {}. Cannot write last config.".format(CONFIG_DIR))
                 return
            with open(LAST_CONFIG_FILE, 'w') as f:
                f.write(config_name)
        except IOError as e:
            self.log_status("Warn: Could not write last config name: {}".format(e))
        except Exception as e:
             self.log_status("Warn: Unexpected error writing last config: {}".format(e))


    def load_last_config_on_startup(self):
        # ... (same as before, uses updated CONFIG_DIR) ...
        loaded = False
        if os.path.exists(LAST_CONFIG_FILE):
            try:
                with open(LAST_CONFIG_FILE, 'r') as f:
                    name = f.read().strip()
                if name:
                    json_path = os.path.join(CONFIG_DIR, name + JSON_EXT)
                    if os.path.exists(json_path):
                        self.log_status("Found last config: '{}'. Loading...".format(name))
                        self.config_name_var.set(name)
                        self.load_config()
                        loaded = True
                    else:
                        self.log_status("Last config file '{}' not found in {}.".format(name + JSON_EXT, CONFIG_DIR))
                        try:
                            os.remove(LAST_CONFIG_FILE)
                        except OSError:
                            pass
            except Exception as e:
                self.log_status("Err loading last config name: {}".format(e))
        if not loaded:
            self.log_status("Starting with default setup.")

    def save_config(self):
        # ... (uses updated CONFIG_DIR, sets version 3.6) ...
        name = self.config_name_var.get().strip()
        if not name:
            tkMessageBox.showerror("Error", "Please enter a configuration name.", parent=self.root)
            return
        safe_name = re.sub(r'[^\w\-.]', '_', name)
        if safe_name != name:
            self.log_status("Info: Config name adjusted: '{}'".format(safe_name))
            self.config_name_var.set(safe_name)
            name = safe_name
        if not name:
            tkMessageBox.showerror("Error", "Invalid configuration name.", parent=self.root)
            return

        json_path = os.path.join(CONFIG_DIR, name + JSON_EXT)
        self.log_status("Saving config '{}' to {}...".format(name, json_path)) # Show full path

        config_data = {
            "version": 3.6, # Version updated
            "window_geometry": self.root.geometry(),
            "csv_dir": self.csv_dir_var.get(),
            "shared_params": {
                "db_name": self.shared_db_var.get(),
                "line_name": self.shared_line_var.get(),
                "subline": self.shared_subl_var.get(),
                "first_shot": self.shared_fshot_var.get(),
                "last_shot": self.shared_lshot_var.get(),
                "use_grid": self.shared_grid_var.get(),
            },
            "segments": []
        }

        for seg_id, seg_ref in self.segment_widget_refs.items():
             if seg_ref['frame'].winfo_exists():
                 seg_struct = {
                     "seg_id": seg_id,
                     "type": seg_ref['type'],
                     "data_type": seg_ref['dtype_var'].get(),
                     "headers": []
                 }
                 for row_tuple in seg_ref['header_rows']:
                     if row_tuple[0].winfo_exists():
                         try:
                             hdr_struct = {
                                 "header_name": row_tuple[1].get(),
                                 "csv_header": row_tuple[2].get(),
                                 "csv_col": row_tuple[3].get(),
                                 "ascii_time": row_tuple[5].get()
                              }
                             if hdr_struct["header_name"] and hdr_struct["csv_header"] and hdr_struct["csv_col"]:
                                 seg_struct["headers"].append(hdr_struct)
                         except tk.TclError:
                             pass
                 config_data["segments"].append(seg_struct)

        try:
            if not os.path.isdir(CONFIG_DIR):
                self.log_status("Config dir {} missing, attempting create...".format(CONFIG_DIR))
                self._create_dirs() # Attempt creation
            if not os.path.isdir(CONFIG_DIR): # Check again after attempt
                raise IOError("Config dir missing or could not be created: {}".format(CONFIG_DIR))
            # Check writability before opening
            if not os.access(CONFIG_DIR, os.W_OK):
                 raise IOError("No write permission for config dir: {}".format(CONFIG_DIR))

            with open(json_path, 'w') as f:
                json.dump(config_data, f, indent=4)
            self.log_status("Saved {}".format(json_path)) # Show full path
            self._write_last_config(name)
        except Exception as e:
            tkMessageBox.showerror("Save Error", "Cannot save {}:\n{}".format(os.path.basename(json_path), e), parent=self.root)
            self.log_status("Error saving config: {}".format(e))

    def load_config(self):
        # ... (uses updated CONFIG_DIR) ...
        name = self.config_name_var.get().strip()
        if not name:
            tkMessageBox.showerror("Error", "Enter/Browse config name.", parent=self.root)
            return
        json_path = os.path.join(CONFIG_DIR, name + JSON_EXT)
        self.log_status("Loading config '{}' from {}...".format(name, json_path)) # Show full path

        if not os.path.exists(json_path):
            self.log_status("Error: Config file not found: {}".format(json_path))
            tkMessageBox.showerror("Load Error", "Config file not found:\n{}".format(json_path), parent=self.root)
            return

        try:
            with open(json_path, 'r') as f:
                config_data = json.load(f)
        except Exception as e:
            self.log_status("Error reading/parsing config file {}: {}".format(os.path.basename(json_path), e))
            tkMessageBox.showerror("Load Error", "Cannot read/parse {}:\n{}".format(os.path.basename(json_path), e), parent=self.root)
            return

        # --- Apply loaded config ---
        # ... (rest is same as before) ...
        try:
            # Window Geometry
            if "window_geometry" in config_data:
                try:
                    self.root.geometry(config_data["window_geometry"])
                except tk.TclError as e:
                    self.log_status("Warn: Bad geometry: {}".format(e))

            # CSV Dir
            self.csv_dir_var.set(config_data.get("csv_dir", DEFAULT_CSV_DIR))

            # Load Shared Params
            shared_params = config_data.get("shared_params", {})
            self.shared_db_var.set(shared_params.get("db_name", ""))
            self.shared_line_var.set(shared_params.get("line_name", ""))
            self.shared_subl_var.set(shared_params.get("subline", ""))
            self.shared_fshot_var.set(shared_params.get("first_shot", "-999"))
            self.shared_lshot_var.set(shared_params.get("last_shot", "99999"))
            self.shared_grid_var.set(shared_params.get("use_grid", 0))

            # Repopulate DBs
            self.populate_databases()

            # Segments - Clear existing and rebuild
            self._clear_all_segments()
            loaded_segments = config_data.get("segments", [])
            self.log_status("Loading {} segments...".format(len(loaded_segments)))
            temp_headers_data = {}
            for seg_data in loaded_segments:
                seg_type = seg_data.get("type")
                if seg_type not in ['dbRead', 'dumpDataclass']:
                    self.log_status("Warn: Unknown segment type '{}'".format(seg_type))
                    continue
                new_seg_id = self.add_segment(seg_type, rebuild_mode=True)
                if new_seg_id is None:
                    continue
                if new_seg_id in self.segment_widget_refs:
                    seg_ref = self.segment_widget_refs[new_seg_id]
                    seg_ref['dtype_var'].set(seg_data.get("data_type", ""))
                    temp_headers_data[new_seg_id] = seg_data.get("headers", [])
                else:
                    self.log_status("Warn: Failed to get reference for new segment ID {} during load.".format(new_seg_id))

            for seg_id, headers_to_load in temp_headers_data.items():
                if seg_id in self.segment_widget_refs:
                    seg_ref = self.segment_widget_refs[seg_id]
                    num_headers_str = str(len(headers_to_load))
                    if 'num_hdr_var' in seg_ref and seg_ref['num_hdr_var']:
                        seg_ref['num_hdr_var'].set(num_headers_str)
                    else:
                        self.log_status("Warn: num_hdr_var missing for seg_id {}.".format(seg_id))
                    self._build_header_rows(seg_id, headers_config=headers_to_load)
                else:
                    self.log_status("Warn: Could not find segment ref for ID {}.".format(seg_id))

            self.segments_inner_frame.update_idletasks()
            self.on_inner_frame_configure(None)
            self.log_status("Config '{}' loaded.".format(name))
            self.update_default_csv_name()
            self._write_last_config(name)

        except Exception as e:
            self.log_status("Error applying loaded config: {}".format(e))
            import traceback
            self.log_status(traceback.format_exc())
            tkMessageBox.showerror("Load Error", "Failed apply config:\n{}".format(e), parent=self.root)

    def browse_load_config(self):
        # ... (uses updated CONFIG_DIR for initialdir) ...
        self.log_status("Browse for config file (.json)...")
        # Use CONFIG_DIR as the initial directory for Browse
        initial_dir_browse = CONFIG_DIR if os.path.isdir(CONFIG_DIR) else os.path.expanduser("~")

        fpath = tkFileDialog.askopenfilename(initialdir=initial_dir_browse, title="Select Config (.json)",filetypes=[("xdbRead Config", "*" + JSON_EXT), ("All files", "*.*")], parent=self.root)
        if fpath:
            # Check if the selected file is inside the expected CONFIG_DIR
            # This is just informational, we still load the selected file
            if not fpath.startswith(os.path.abspath(CONFIG_DIR)):
                 self.log_status("Note: Selected config is outside the default config directory.")

            name = os.path.basename(fpath)
            if name.lower().endswith(JSON_EXT):
                name = name[:-len(JSON_EXT)]
            self.config_name_var.set(name)
            # Pass the full path to load_config if it's outside default dir?
            # Current load_config assumes name is relative to CONFIG_DIR.
            # Let's adjust load_config slightly if a full path might be needed.
            # For now, assuming user browses within CONFIG_DIR or saves first.
            # Sticking to original load_config logic which uses name + CONFIG_DIR.
            self.load_config()
        else:
            self.log_status("Config browse cancelled.")

    # --- Dynamic Segment Actions ---

    def add_segment(self, seg_type, rebuild_mode=False):
        if seg_type not in ['dbRead', 'dumpDataclass']:
            self.log_status("Error: Invalid segment type '{}'".format(seg_type))
            return None

        seg_id = self.next_seg_id
        self.next_seg_id += 1
        seg_num = len(self.segment_widget_refs) + 1
        # MODIFIED: Segment frame no longer has text itself
        segment_frame = ttk.LabelFrame(self.segments_inner_frame, text="", padding="10", style='TLabelframe') # Use TLabelframe style
        segment_frame.pack(fill=tk.X, padx=5, pady=5, anchor="nw")

        # --- MODIFIED: Create a top bar for label and remove button ---
        top_bar = ttk.Frame(segment_frame, style='TFrame')
        top_bar.pack(fill=tk.X, pady=(0,5)) # Pack top bar first

        # Label for segment type/number
        frame_text = "{} Segment {}".format(seg_type, seg_num)
        ttk.Label(top_bar, text=frame_text, style='TLabel').pack(side=tk.LEFT, padx=5, anchor='w')

        # MODIFIED: Remove Button - Changed text and using pack
        remove_button = tk.Button(top_bar, text="Remove Segment", # Changed text
                                   command=partial(self.remove_segment, seg_id),
                                   relief="raised",
                                   padx=4, pady=0,
                                   bg="#8DA9CC", fg="black", highlightbackground="#B4C8E1") # Button colors
        remove_button.pack(side=tk.RIGHT, padx=5) # Pack to the right
        # --- End of top bar modification ---

        dtype_var = tk.StringVar()
        num_headers_var = tk.StringVar(value="1")
        header_rows_container = ttk.Frame(segment_frame, style='TFrame') # Parent is still segment_frame

        self.segment_widget_refs[seg_id] = {
            'frame': segment_frame, 'type': seg_type, 'dtype_var': dtype_var,
            'num_hdr_var': num_headers_var, 'header_rows': [],
            'header_container': header_rows_container
        }

        # Widgets inside segment frame (now packed *after* top_bar)
        dt_frame = ttk.Frame(segment_frame, style='TFrame')
        dt_frame.pack(fill=tk.X, pady=2, anchor=tk.W)
        ttk.Label(dt_frame, text="Data Type:", width=12, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=5)
        dtype_list = DBREAD_DATA_TYPES if seg_type == 'dbRead' else DUMP_DATA_TYPES
        dtype_combo = ttk.Combobox(dt_frame, textvariable=dtype_var, values=dtype_list, width=25, state='readonly')
        dtype_combo.pack(side=tk.LEFT, padx=5)

        hdr_ctrl_frame = ttk.Frame(segment_frame, style='TFrame')
        hdr_ctrl_frame.pack(fill=tk.X, pady=2, anchor=tk.W)
        ttk.Label(hdr_ctrl_frame, text="# Headers:", width=10, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=5)
        num_headers_entry = ttk.Entry(hdr_ctrl_frame, textvariable=num_headers_var, width=5)
        num_headers_entry.pack(side=tk.LEFT, padx=5)
        set_hdr_button = ttk.Button(hdr_ctrl_frame, text="Set", command=partial(self._rebuild_header_rows, seg_id), style='TButton')
        set_hdr_button.pack(side=tk.LEFT, padx=5)
        clear_hdr_button = ttk.Button(hdr_ctrl_frame, text="Clear Headers", command=partial(self._clear_header_rows_action, seg_id), style='TButton')
        clear_hdr_button.pack(side=tk.LEFT, padx=5)

        header_rows_container.pack(fill=tk.X, expand=True, pady=5, padx=15, anchor=tk.W)

        if not rebuild_mode:
            self._build_header_rows(seg_id)
            self.segments_inner_frame.update_idletasks()
            self.on_inner_frame_configure(None)
        return seg_id

    def remove_segment(self, seg_id):
        # ... (logic is same, uses seg_ref['frame'] which is correct) ...
        if seg_id not in self.segment_widget_refs:
            self.log_status("Warn: Remove non-existent segment ID {}".format(seg_id))
            return
        seg_ref = self.segment_widget_refs[seg_id]
        segment_frame = seg_ref['frame']
        # Get text from the internal label now
        frame_label_widget = segment_frame.winfo_children()[0].winfo_children()[0] # top_bar -> label
        frame_text = frame_label_widget.cget('text') if frame_label_widget else "Segment"

        if tkMessageBox.askyesno("Confirm Removal", "Remove {}?".format(frame_text), parent=self.root):
            self.log_status("Removing {}...".format(frame_text))
            entries_to_remove = []
            if 'header_rows' in seg_ref:
                 for row_tuple in seg_ref['header_rows']:
                     entries_to_remove.append(row_tuple[4]) # The Entry widget itself
            self.csv_col_entries = [entry for entry in self.csv_col_entries if entry not in entries_to_remove]

            # Destroy the frame
            if segment_frame.winfo_exists():
                segment_frame.destroy()
            # Remove from internal tracking
            del self.segment_widget_refs[seg_id]

            self.validate_all_csv_cols() # Revalidate remaining column numbers
            self.renumber_segment_frames() # Update numbering of remaining segments
            self.segments_inner_frame.update_idletasks()
            self.on_inner_frame_configure(None) # Update scroll region
            self.log_status("Segment removed.")

    def renumber_segment_frames(self):
        current_num = 1
        for seg_id, seg_ref in self.segment_widget_refs.items():
             if seg_ref['frame'].winfo_exists():
                 # Find the label inside the top bar to update its text
                 try:
                      top_bar = seg_ref['frame'].winfo_children()[0]
                      label_widget = top_bar.winfo_children()[0]
                      label_widget.config(text="{} Segment {}".format(seg_ref['type'], current_num))
                 except IndexError:
                      self.log_status("Warn: Could not find label to renumber segment {}".format(seg_id))
                 current_num += 1

    def clear_all_segments_action(self):
        # ... (same as before) ...
        if tkMessageBox.askyesno("Confirm Clear", "Clear ALL segment configurations?", parent=self.root):
            self._clear_all_segments()

    def _clear_all_segments(self):
        # ... (same as before) ...
        self.log_status("Clearing all segments...")
        for seg_id in list(self.segment_widget_refs.keys()):
            seg_ref = self.segment_widget_refs[seg_id]
            if seg_ref['frame'].winfo_exists():
                seg_ref['frame'].destroy()
        self.segment_widget_refs.clear()
        self.csv_col_entries = []
        self.next_seg_id = 0
        if self.segments_inner_frame and self.segments_inner_frame.winfo_exists():
            self.segments_inner_frame.update_idletasks()
            self.on_inner_frame_configure(None)
        self.log_status("All segments cleared.")

    # --- Segment Header Row Build/Rebuild Logic ---
    # (No changes needed here)
    def _rebuild_header_rows(self, seg_id):
        # ... (same as before) ...
        if seg_id not in self.segment_widget_refs: return
        seg_ref = self.segment_widget_refs[seg_id]; old_header_rows_data = []
        for row_tuple in seg_ref['header_rows']:
            if row_tuple[0].winfo_exists():
                try:
                    old_header_rows_data.append({
                        "header_name": row_tuple[1].get(),
                        "csv_header": row_tuple[2].get(),
                        "csv_col": row_tuple[3].get(),
                        "ascii_time": row_tuple[5].get()
                    })
                except tk.TclError: pass
        self._build_header_rows(seg_id, headers_config=old_header_rows_data)

    def _clear_header_rows_action(self, seg_id):
        # ... (same as before) ...
        if seg_id not in self.segment_widget_refs: return
        if 'num_hdr_var' in self.segment_widget_refs[seg_id] and self.segment_widget_refs[seg_id]['num_hdr_var']:
            self.segment_widget_refs[seg_id]['num_hdr_var'].set("0")
            self._build_header_rows(seg_id, headers_config=[])
        else:
            self.log_status("Warning: Could not clear headers, num_hdr_var missing for seg_id {}".format(seg_id))

    def _build_header_rows(self, seg_id, headers_config=None):
        # ... (same as before) ...
        if seg_id not in self.segment_widget_refs:
            self.log_status("Error: Cannot build headers for non-existent seg_id {}".format(seg_id))
            return
        seg_ref = self.segment_widget_refs[seg_id]
        num_headers_var = seg_ref.get('num_hdr_var')
        header_rows_container = seg_ref.get('header_container')

        if not header_rows_container or not header_rows_container.winfo_exists():
            self.log_status("Err: No valid header container for seg_id {}".format(seg_id)); return
        if not num_headers_var:
            self.log_status("Err: num_headers_var missing for seg_id {}".format(seg_id)); return

        # Clear previous rows
        rows_to_clear = list(seg_ref['header_rows'])
        seg_ref['header_rows'] = []
        entries_to_remove = []
        for row_tuple in rows_to_clear:
            col_entry_widget = row_tuple[4]
            entries_to_remove.append(col_entry_widget)
            if row_tuple[0].winfo_exists():
                row_tuple[0].destroy()
        self.csv_col_entries = [entry for entry in self.csv_col_entries if entry not in entries_to_remove]

        num_headers = 0
        try:
            num_headers = int(num_headers_var.get())
            assert num_headers >= 0
        except:
            num_headers = 0
            num_headers_var.set("0")

        if not hasattr(self, 'vcmd_registered'):
            self.vcmd_registered = (self.root.register(self.validate_csv_col_keypress), '%P', '%W')

        # Build new rows
        for j in range(num_headers):
            row_frame = ttk.Frame(header_rows_container, style='TFrame') # Apply style to row_frame
            row_frame.pack(fill=tk.X, pady=2)
            hdr_var=tk.StringVar()
            csv_hdr_var=tk.StringVar()
            csv_col_var=tk.StringVar()
            ascii_time_var=tk.IntVar(value=0)

            curr_hdr, curr_csv_hdr, curr_csv_col, curr_ascii = "", "", "", 0
            if headers_config and j < len(headers_config):
                conf = headers_config[j]
                curr_hdr=conf.get("header_name","")
                curr_csv_hdr=conf.get("csv_header","")
                curr_csv_col=conf.get("csv_col","")
                curr_ascii = conf.get("ascii_time", 0)
            hdr_var.set(curr_hdr)
            csv_hdr_var.set(curr_csv_hdr)
            csv_col_var.set(curr_csv_col)
            ascii_time_var.set(curr_ascii)

            # Create widgets
            ttk.Label(row_frame, text="Data Type Header:", width=18, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=(0, 2))
            hdr_entry = ttk.Entry(row_frame, width=18, textvariable=hdr_var)
            hdr_entry.pack(side=tk.LEFT, padx=(0, 5))
            ttk.Label(row_frame, text="CSV Header:", width=12, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=(0, 2))
            csv_entry = ttk.Entry(row_frame, width=18, textvariable=csv_hdr_var)
            csv_entry.pack(side=tk.LEFT, padx=(0, 5))
            ttk.Label(row_frame, text="CSV Column #:", width=12, anchor=tk.W, style='TLabel').pack(side=tk.LEFT, padx=(0, 2))
            col_entry = ttk.Entry(row_frame, width=5, textvariable=csv_col_var, validate='key', validatecommand=self.vcmd_registered)
            col_entry.pack(side=tk.LEFT, padx=(0, 2))
            warn_lbl = ttk.Label(row_frame, text="", foreground="red", width=12, style='TLabel') # Apply style to warning label
            warn_lbl.pack(side=tk.LEFT, padx=(0,2))

            col_entry.warning_label = warn_lbl
            self.csv_col_entries.append(col_entry)
            col_entry.bind("<FocusOut>", lambda e, entry=col_entry: self.validate_csv_col_final(entry))
            col_entry.bind("<FocusIn>", lambda e, entry=col_entry: self.clear_col_warning(entry))

            ascii_check = ttk.Checkbutton(row_frame, text="Ascii Time", variable=ascii_time_var, style='TCheckbutton')
            ascii_check.pack(side=tk.LEFT, padx=5)

            seg_ref['header_rows'].append( (row_frame, hdr_var, csv_hdr_var, csv_col_var, col_entry, ascii_time_var) )
            self.validate_csv_col_final(col_entry)

        # Re-validate all columns
        self.validate_all_csv_cols()

        self.segments_inner_frame.update_idletasks()
        self.on_inner_frame_configure(None)


    # --- Validation ---
    # (No changes needed here)
    def clear_col_warning(self, entry_widget):
        # ... (same as before) ...
        if entry_widget.winfo_exists():
            entry_widget.config(foreground="black") # Default Entry foreground
            if hasattr(entry_widget, 'warning_label') and entry_widget.warning_label and entry_widget.warning_label.winfo_exists():
                 entry_widget.warning_label.config(text="")

    def validate_csv_col_keypress(self, P, W):
        # ... (same as before) ...
        if P == "" or P.isdigit():
            return True
        else:
            self.root.bell()
            return False

    def validate_csv_col_final(self, entry_widget):
        # ... (same as before) ...
        if not entry_widget.winfo_exists():
            return True

        value = entry_widget.get()
        is_ok = True
        warning_label = getattr(entry_widget, 'warning_label', None)

        # Reset appearance
        entry_widget.config(foreground="black") # Default Entry foreground
        if hasattr(entry_widget, 'warning_label') and warning_label and warning_label.winfo_exists():
            warning_label.config(text="")

        # Check value
        if value == "":
             is_ok = True
        else:
             try:
                 col_num = int(value)
                 if col_num <= 0:
                     entry_widget.config(foreground="red")
                     if warning_label and warning_label.winfo_exists():
                         warning_label.config(text="Must be > 0")
                     is_ok = False
             except (ValueError):
                 entry_widget.config(foreground="red")
                 if warning_label and warning_label.winfo_exists():
                     warning_label.config(text="Invalid #")
                 is_ok = False

        # Check for duplicates
        if is_ok and value != "":
             is_duplicate = False
             for other_entry in self.csv_col_entries:
                 if other_entry.winfo_exists() and other_entry is not entry_widget and other_entry.get() == value:
                     is_duplicate = True
                     break
             if is_duplicate:
                 entry_widget.config(foreground="red")
                 if warning_label and warning_label.winfo_exists():
                     warning_label.config(text="Duplicate")
                 is_ok = False
        return is_ok

    def validate_all_csv_cols(self):
        # ... (same as before) ...
        all_entries = [entry for entry in self.csv_col_entries if entry.winfo_exists()]
        counts = collections.Counter(entry.get() for entry in all_entries if entry.get() != "")
        overall_valid = True
        for entry in all_entries:
            value = entry.get()
            warning_label = getattr(entry, 'warning_label', None)
            is_entry_ok = True
            entry.config(foreground="black") # Default Entry foreground
            if warning_label and warning_label.winfo_exists():
                warning_label.config(text="")

            if value == "":
                is_entry_ok = True
            else:
                try:
                    col_num = int(value)
                    if col_num <= 0:
                        entry.config(foreground="red")
                        if warning_label and warning_label.winfo_exists(): warning_label.config(text="Must be > 0")
                        is_entry_ok = False
                    elif counts[value] > 1:
                        entry.config(foreground="red")
                        if warning_label and warning_label.winfo_exists(): warning_label.config(text="Duplicate")
                        is_entry_ok = False
                except ValueError:
                    entry.config(foreground="red")
                    if warning_label and warning_label.winfo_exists(): warning_label.config(text="Invalid #")
                    is_entry_ok = False
            if not is_entry_ok:
                overall_valid = False
        return overall_valid


    # --- Execution Logic ---
    # (No changes needed in start_processing, cancel_processing)
    def start_processing(self):
        # ... (same as before) ...
        self.log_status("Initiating data processing...")
        errors = []
        if not self.validate_all_csv_cols():
            errors.append("- Fix invalid/duplicate CSV Column #s.")
        if not self.shared_db_var.get():
            errors.append("- Select Database in Shared Parameters.")
        if not self.shared_line_var.get():
            errors.append("- Enter Line Name in Shared Parameters.")
        if not self.shared_subl_var.get():
            errors.append("- Enter Subline in Shared Parameters.")
        if not self.segment_widget_refs:
            errors.append("- Add at least one dbRead or dumpDataclass segment.")
        if errors:
            self.log_status("Validation failed.")
            tkMessageBox.showerror("Input Error", "Corrections needed:\n" + "\n".join(errors), parent=self.root)
            return

        # Gather Config Data
        self.log_status("Gathering configuration from GUI...")
        final_headers_map = collections.OrderedDict()
        all_segment_configs = []
        csv_headers_to_convert = set()
        try:
            shared_params = {
                "db": self.shared_db_var.get(), "line": self.shared_line_var.get(),
                "subl": self.shared_subl_var.get(), "fshot": self.shared_fshot_var.get(),
                "lshot": self.shared_lshot_var.get(), "grid": self.shared_grid_var.get()
            }
            csv_dir = self.csv_dir_var.get()
            temp_col_map = {}

            # Build final header map
            for seg_id, seg_ref in self.segment_widget_refs.items():
                 if seg_ref['frame'].winfo_exists():
                     for row_idx, row_tuple in enumerate(seg_ref['header_rows']):
                         if row_tuple[0].winfo_exists():
                             try:
                                 csv_header = row_tuple[2].get()
                                 csv_col_str = row_tuple[3].get()
                                 if csv_header and csv_col_str:
                                     csv_col = int(csv_col_str)
                                     if csv_col > 0:
                                         if csv_col in temp_col_map and temp_col_map[csv_col] != csv_header:
                                             self.log_status("Warn: Col #{} conflicting headers ('{}' vs '{}')".format(csv_col, temp_col_map[csv_col], csv_header))
                                         elif csv_col not in temp_col_map:
                                             temp_col_map[csv_col] = csv_header
                             except (ValueError, tk.TclError):
                                 pass

            for col_num in sorted(temp_col_map.keys()):
                final_headers_map[col_num] = temp_col_map[col_num]
            if not final_headers_map:
                raise Exception("No valid headers with positive CSV Column # found.")

            # Gather segment configs
            for seg_id, seg_ref in self.segment_widget_refs.items():
                 if seg_ref['frame'].winfo_exists():
                     seg_type = seg_ref['type']
                     data_type = seg_ref['dtype_var'].get()
                     if not data_type:
                         # Find label text for warning
                         frame_label_widget = seg_ref['frame'].winfo_children()[0].winfo_children()[0]
                         seg_label = frame_label_widget.cget('text') if frame_label_widget else "Segment {}".format(seg_id)
                         self.log_status("Warn: {} no Data Type, skipping.".format(seg_label))
                         continue
                     segment_config = {"type": seg_type, "data_type": data_type, "headers": []}
                     has_valid_headers_in_segment = False
                     for row_idx, row_tuple in enumerate(seg_ref['header_rows']):
                         if row_tuple[0].winfo_exists():
                             try:
                                 hdr_name = row_tuple[1].get()
                                 csv_header = row_tuple[2].get()
                                 csv_col_str = row_tuple[3].get()
                                 ascii_time_state = row_tuple[5].get()
                                 if hdr_name and csv_header and csv_col_str:
                                     csv_col = int(csv_col_str)
                                     if csv_col > 0:
                                         final_csv_header_for_col = final_headers_map.get(csv_col)
                                         if final_csv_header_for_col:
                                             segment_config["headers"].append({"header_name": hdr_name, "csv_header": final_csv_header_for_col, "csv_col": csv_col, "ascii_time": ascii_time_state})
                                             has_valid_headers_in_segment = True
                                             if ascii_time_state == 1:
                                                 csv_headers_to_convert.add(final_csv_header_for_col)
                             except (ValueError, tk.TclError):
                                 pass
                     if has_valid_headers_in_segment:
                         all_segment_configs.append(segment_config)

            if not all_segment_configs:
                 raise Exception("No segments with valid header configurations found.")

            final_csv_header_row = list(final_headers_map.values())
            self.update_default_csv_name()
            csv_filename = self.default_csv_name_var.get()
            if not csv_filename:
                csv_filename = "xdbRead_xdumpDataClass_output.csv" # Updated default name slightly
            csv_filepath = os.path.join(csv_dir, csv_filename)
            if not os.path.isdir(csv_dir):
                # Try to create if missing? Or just error out. Let's error out for now.
                # self._create_dirs() # This only creates CONFIG_DIR and DEFAULT_CSV_DIR
                 raise IOError("CSV output directory does not exist: {}".format(csv_dir))

        except Exception as e:
             self.log_status("Error preparing configuration: {}".format(e))
             import traceback
             self.log_status(traceback.format_exc())
             tkMessageBox.showerror("Config Error", "Failed to prepare:\n{}".format(e), parent=self.root)
             return

        # Start Thread
        self.start_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        self.log_status("Validation & config gathered. Starting worker thread...")
        thread_args = (shared_params, csv_filepath, all_segment_configs, final_csv_header_row, csv_headers_to_convert)
        thread = threading.Thread(target=self.run_processing_thread, args=thread_args)
        thread.daemon = True
        thread.start()

    def cancel_processing(self):
        # ... (same as before) ...
        self.log_status("Cancel requested.")
        if self.running_process and self.running_process.poll() is None:
            self.log_status("Terminating PID: {}...".format(self.running_process.pid))
            try:
                self.running_process.terminate()
                self.log_status("Sent SIGTERM.")
            except OSError as e:
                self.log_status("Error terminating: {}".format(e))
            except Exception as e:
                self.log_status("Unexpected cancel error: {}".format(e))
        else:
            self.log_status("No active process or process finished.")

        try:
            if self.cancel_button.winfo_exists():
                 self.cancel_button.config(state=tk.DISABLED)
        except tk.TclError:
            pass

    # --- Worker Thread ---
    # (No changes needed here, uses the corrected awk script from v3.5)
    def run_processing_thread(self, shared_params, csv_filepath, all_segment_configs, final_csv_header_row, csv_headers_to_convert):
        """Worker thread: Uses passed config, executes commands, processes, writes CSV."""
        try:
            self.status_queue.put("Worker started. Output CSV: {}".format(csv_filepath))
            self.status_queue.put("Final CSV Headers: {}".format(final_csv_header_row))
            if csv_headers_to_convert:
                self.status_queue.put("Ascii Time conversion for: {}".format(list(csv_headers_to_convert)))
            self.status_queue.put("Processing {} segment(s)...".format(len(all_segment_configs)))

            data_by_shot = collections.OrderedDict()

            # Write Header (Note: File is reopened in append mode later, this correctly overwrites/creates file first)
            self.status_queue.put("Opening {} (overwrite)...".format(os.path.basename(csv_filepath)))
            with open(csv_filepath, 'w') as f_csv:
                f_csv.write(",".join(map(str, final_csv_header_row)) + "\n")

            # Loop through each configured segment
            for seg_idx, segment_config in enumerate(all_segment_configs):
                segment_type = segment_config["type"]
                data_type = segment_config["data_type"]
                headers_info = segment_config["headers"]
                self.status_queue.put("--- Processing Seg {}: {} ({}) ---".format(seg_idx+1, data_type, segment_type))
                base_cmd_args = []
                command_name = ""

                # Build command based on SEGMENT type, using SHARED params
                if segment_type == 'dbRead':
                    command_name = "dbRead"
                    if not shared_params.get("db"): self.status_queue.put("Err: No DB. Skip segment."); continue
                    base_cmd_args = [command_name, "-db", shared_params["db"]]
                    if shared_params.get("line"): base_cmd_args.extend(["-line", shared_params["line"]])
                    if shared_params.get("subl"): base_cmd_args.extend(["-subl", shared_params["subl"]])
                    if shared_params.get("fshot"): base_cmd_args.extend(["-fshot", shared_params["fshot"]])
                    if shared_params.get("lshot"): base_cmd_args.extend(["-lshot", shared_params["lshot"]])
                    if shared_params.get("grid") == 1: base_cmd_args.append("-grid") # Apply grid conditionally
                    base_cmd_args.extend(["-data", data_type])
                elif segment_type == 'dumpDataclass':
                    command_name = "dumpDataclass" # Note: GUI Title uses xdumpDataClass, command is likely still dumpDataclass
                    if not shared_params.get("db"): self.status_queue.put("Err: No DB. Skip segment."); continue
                    base_cmd_args = [command_name, "-db", shared_params["db"]]
                    if shared_params.get("line"): base_cmd_args.extend(["-line", shared_params["line"]])
                    if shared_params.get("subl"): base_cmd_args.extend(["-subl", shared_params["subl"]])
                    if shared_params.get("fshot"): base_cmd_args.extend(["-fshot", shared_params["fshot"]])
                    if shared_params.get("lshot"): base_cmd_args.extend(["-lshot", shared_params["lshot"]])
                    base_cmd_args.extend(["-type", data_type])
                else: self.status_queue.put("Err: Unknown segment type '{}'".format(segment_type)); continue

                # Determine Headers Needed & Build Map
                source_headers_needed = set(["Shot", "time"]) # GUI Header names needed
                # Map GUI Header Name -> Final CSV Header Name
                source_to_csv_header_map = {"Shot": "Shot", "time": "time"}
                for item in headers_info:
                    gui_header_name = item["header_name"]
                    final_csv_header = item["csv_header"]
                    source_headers_needed.add(gui_header_name)
                    source_to_csv_header_map[gui_header_name] = final_csv_header

                # Build AWK Script based on Segment Type
                awk_script = ""
                # ===========================================================
                # FLEXIBLE HEADER MATCHING AWK CODE
                # Cleans header from command output (trims space, removes #_- prefix/suffix)
                # Compares cleaned header (fld) to the header entered in GUI (hname)
                # ===========================================================
                awk_clean_header_code = 'gsub(/^\\s+|\\s+$/,"",fld); gsub(/^[#_\\-\\s]+|[#_\\-\\s]+$/,"",fld);'

                # ***********************************************************************
                # ***** CORRECTED AWK SCRIPT FOR dbRead (Handles Space Delimiters) *****
                # ***********************************************************************
                if segment_type == 'dbRead':
                    # Assumes dbRead output is space/whitespace delimited like the sample images.
                    # Processes fields using NF and $i.
                    awk_script = "BEGIN{OFS=\",\"}NR==1{hdr_count=0;delete col_idx;delete hdr_order;gsub(/\\r$/,\"\",$0);for(i=1;i<=NF;i++){fld=$i;" + awk_clean_header_code + " "; # Use NF and $i
                    for hname in sorted(list(source_headers_needed)):
                        awk_script+='if(fld==\"{h}\"){{col_idx[\"{h}\"]=i;hdr_order[hdr_count++]=\"{h}\";}};'.format(h=hname.replace('"','\\"'))
                    # Error message updated slightly for clarity
                    awk_script+="}if(hdr_count>0){printf\"%s\",hdr_order[0];for(j=1;j<hdr_count;j++)printf\"%s%s\",OFS,hdr_order[j];print\"\";}else{print\"AWK_ERROR_DBREAD: No required headers found on Row 1 (check GUI: " + ",".join(sorted(list(source_headers_needed))[:3]) + "... vs cmd output)\";exit 1;}}NR>1{gsub(/\\r$/,\"\",$0);if(hdr_count>0&&NF>0){printf\"%s\",$col_idx[hdr_order[0]];for(j=1;j<hdr_count;j++)printf\"%s%s\",OFS,$col_idx[hdr_order[j]];print\"\";}}" # Use $col_idx[...]
                # ***********************************************************************
                # ***** END OF CORRECTED dbRead AWK SCRIPT                     *****
                # ***********************************************************************
                elif segment_type == 'dumpDataclass':
                    # This part remains the same, as it already handled space-separated input
                    awk_script = "BEGIN{OFS=\",\"}NR==2{sub(/^#/,\"\");hdr_count=0;delete col_idx;delete hdr_order;gsub(/\\r$/,\"\",$0);for(i=1;i<=NF;i++){fld=$i;" + awk_clean_header_code + " ";
                    for hname in sorted(list(source_headers_needed)):
                            awk_script+='if(fld==\"{h}\"){{col_idx[\"{h}\"]=i;hdr_order[hdr_count++]=\"{h}\";}};'.format(h=hname.replace('"','\\"'))
                    awk_script+="}if(hdr_count>0){printf\"%s\",hdr_order[0];for(j=1;j<hdr_count;j++)printf\"%s%s\",OFS,hdr_order[j];print\"\";}else{print\"AWK_ERROR_DUMP: No required headers found on Row 2 (check GUI: " + ",".join(sorted(list(source_headers_needed))[:3]) + "... vs cmd output)\";exit 1;}}NR>3{gsub(/\\r$/,\"\",$0);if(hdr_count>0&&NF>0){printf\"%s\",$col_idx[hdr_order[0]];for(j=1;j<hdr_count;j++)printf\"%s%s\",OFS,$col_idx[hdr_order[j]];print\"\";}}"

                # Execute Command
                full_command_str = " ".join(base_cmd_args) + " | awk '" + awk_script + "'"
                self.status_queue.put("Seg {} Cmd: {}".format(seg_idx+1, full_command_str))
                process = None
                try:
                    process = subprocess.Popen(full_command_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.running_process = process
                    stdout, stderr = process.communicate()
                    rc = process.returncode
                    self.running_process = None
                    stderr_str = stderr.strip()
                    if stderr_str:
                        self.status_queue.put("Seg {} Stderr: {}".format(seg_idx+1, stderr_str))
                    if rc != 0:
                        self.status_queue.put("Err: Seg {} Cmd failed (code {}). Skip...".format(seg_idx+1, rc))
                        # AWK errors now print a message to stdout before exiting with code 1
                        if stdout: self.status_queue.put("Seg {} Stdout on error: {}".format(seg_idx+1, stdout.strip()[:500])) # Show more stdout
                        continue

                    # Process awk output
                    stdout_str = stdout.strip()
                    if not stdout_str:
                        self.status_queue.put("Warn: Seg {}: No awk output.".format(seg_idx+1))
                        continue
                    lines = stdout_str.split('\n')
                    if len(lines) < 1:
                        self.status_queue.put("Warn: Seg {}: No awk lines.".format(seg_idx+1))
                        continue

                    # AWK output headers are the *GUI header names* that were found
                    awk_output_headers = lines[0].strip().split(',')
                    self.status_queue.put("Seg {} AWK Found Headers (GUI Names): {}".format(seg_idx+1, awk_output_headers))

                    if "Shot" not in awk_output_headers:
                        self.status_queue.put("CRIT Err: Seg {}: 'Shot' missing in awk output headers. Cannot merge. Skip...".format(seg_idx+1))
                        continue

                    shot_out_idx = awk_output_headers.index("Shot")
                    line_count = 0
                    if len(lines) > 1:
                        for data_line in lines[1:]:
                            if not data_line.strip(): continue
                            values = data_line.strip().split(',')
                            if len(values) != len(awk_output_headers):
                                self.status_queue.put("Warn: Seg {}: Malformed awk line ({}/{})".format(seg_idx+1, len(values),len(awk_output_headers)))
                                continue
                            shot_key_str = values[shot_out_idx]
                            try: shot_key = int(shot_key_str)
                            except ValueError:
                                self.status_queue.put("Warn: Seg {}: Invalid shot key '{}'".format(seg_idx+1, shot_key_str))
                                continue
                            if shot_key not in data_by_shot:
                                data_by_shot[shot_key] = {}

                            # Map data based on the header order from AWK output
                            for idx, gui_hdr_from_awk in enumerate(awk_output_headers):
                                # Find the corresponding Final CSV Header name using the map built earlier
                                final_csv_header_name = source_to_csv_header_map.get(gui_hdr_from_awk)
                                if final_csv_header_name:
                                    # Store value under the final CSV header name for this shot key
                                    data_by_shot[shot_key][final_csv_header_name] = values[idx]

                            line_count += 1
                    self.status_queue.put("Seg {}: Stored data for {} lines.".format(seg_idx+1, line_count))

                except OSError as e:
                    self.status_queue.put("Fatal OS Err running cmd for seg {}: {}".format(seg_idx+1, e))
                    raise
                except Exception as e:
                    self.status_queue.put("Fatal Err processing seg {}: {}".format(seg_idx+1, e))
                    import traceback
                    self.status_queue.put(traceback.format_exc())
                    raise
                finally:
                    if process and self.running_process is process:
                        self.running_process = None

            # Write Merged Data
            # Note: Using 'ab' to append to the file where header was written initially.
            # Consider using Python's csv module for more robust writing if needed.
            self.status_queue.put("--- Appending Merged Data ---")
            if not data_by_shot:
                self.status_queue.put("No data collected to write.")
            else:
                lines_written = 0
                # Using 'ab' - append binary to avoid newline issues in Python 2
                with open(csv_filepath, 'ab') as f_csv:
                    for shot_key in sorted(data_by_shot.keys()):
                        shot_data_dict = data_by_shot[shot_key]
                        row_values = []
                        for final_csv_header in final_csv_header_row:
                            raw_value = shot_data_dict.get(final_csv_header, "")
                            output_value = raw_value
                            if final_csv_header in csv_headers_to_convert:
                                if raw_value:
                                    try:
                                        timestamp_float = float(raw_value)
                                        # Basic range check to avoid potential errors with extreme values
                                        if timestamp_float < -6857222400: raise ValueError("Timestamp pre-epoch") # ~Year 1776
                                        if timestamp_float > 32503680000: raise ValueError("Timestamp too far in future") # Year 3000
                                        dt_object = datetime.datetime.utcfromtimestamp(timestamp_float)
                                        output_value = dt_object.strftime('%a %b %d %H:%M:%S %Y')
                                    except (ValueError, TypeError, OverflowError) as time_e:
                                        self.status_queue.put("Warn: Time convert error for '{}' (val='{}', shot={}): {}".format(final_csv_header, raw_value, shot_key, time_e))
                                        output_value = raw_value # Keep raw value if conversion fails
                            # Simple CSV: Ensure string, escape double quotes, add quotes if comma/quote/newline present
                            val_str = str(output_value)
                            if '"' in val_str or ',' in val_str or '\n' in val_str:
                                val_str = '"' + val_str.replace('"', '""') + '"'
                            row_values.append(val_str)

                        f_csv.write(",".join(row_values) + "\n")
                        lines_written +=1
                self.status_queue.put("Appended {} merged lines to {}".format(lines_written, os.path.basename(csv_filepath)))

        except IOError as e:
            self.status_queue.put("FATAL FILE ERROR: {}".format(e))
        except Exception as e:
            self.status_queue.put("FATAL ERROR in worker: {}".format(e))
            import traceback
            self.status_queue.put(traceback.format_exc())
        finally:
            self.running_process = None
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.root.after(0, self.finalize_run) # Schedule GUI update on main thread

    def finalize_run(self):
        # This runs in the main GUI thread
        # ... (same as before) ...
        try:
            if hasattr(self, 'start_button') and self.start_button.winfo_exists():
                self.start_button.config(state=tk.NORMAL)
            if hasattr(self, 'cancel_button') and self.cancel_button.winfo_exists():
                self.cancel_button.config(state=tk.DISABLED)
        except tk.TclError:
            pass # Widget might already be destroyed if app closing
        self.log_status("--- Processing finished. ---")

# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    root.configure(bg="#B4C8E1") # Set root background for consistency before app init
    
    # Configure ttk styles globally for Messagebox if possible, or handle locally
    # This might not affect tkMessageBox directly as it's older.
    # For a more themed messagebox, one might need to create a custom dialog.
    # However, tkMessageBox appearance is often OS-dependent.
    # The prompt did not ask to change messagebox colors.

    def on_closing():
        # tkMessageBox theming is limited. Colors here are for the box itself.
        # Standard tkMessageBox buttons are usually OS native.
        if tkMessageBox.askokcancel("Quit", "Do you want to quit?", parent=root):
            root.destroy()
            
    root.protocol("WM_DELETE_WINDOW", on_closing)
    try:
        app = XdbReadApp(root)
        root.mainloop()
    except Exception as e:
        print("FATAL ERROR during application startup: {}".format(e))
        import traceback
        print(traceback.format_exc())
        try:
            # Attempt to show error in a message box if Tkinter is partially working
            tkMessageBox.showerror("Fatal Error", "Application failed to start:\n{}".format(e), parent=root)
        except Exception:
            pass # If Tkinter itself failed badly, just rely on console print