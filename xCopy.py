#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Ai assisted code by RBolisay
import Tkinter as tk
import tkFont # For bold fonts
import tkFileDialog
import tkMessageBox
import ScrolledText # Use ScrolledText for the status window
import os
import sys
import glob
import shutil
import json
import threading
import time
# functools is needed for cleaner lambda with arguments in loops
import functools
import re # For parsing geometry string
import fnmatch # For recursive pattern matching

try:
    # distutils is generally available in Python 2.7 stdlib
    from distutils import dir_util
except ImportError:
    # Provide a fallback or error if distutils is not available
    dir_util = None
    print "Warning: distutils.dir_util not found. Directory copying will be disabled."
    # Optionally, raise an error or disable directory copying features

# --- Theme Colors ---
GUI_BACKGROUND_COLOR = "#B4C8E1" # User-specified GUI background
BUTTON_BACKGROUND_COLOR = "#8DA9CC" # User-specified button background
BUTTON_TEXT_COLOR = "black" # User-specified button text color

# --- Configuration ---
DEFAULT_CONFIG_DIR = "/usr/local/trinop/dbase/links/qcfiles/Misc/xCopy"
LAST_CONFIG_MARKER_FILE = os.path.join(DEFAULT_CONFIG_DIR, ".last_config_path")
COPIED_FILES_DB_NAME = "copied_files.json" # Stored relative to the config file

# --- Constants for UI Adjustment ---
MIN_SEGMENT_AREA_HEIGHT = 60   # Min height for the scrollable segments area (pixels)
MAX_SEGMENT_AREA_HEIGHT = 300  # Max height before scrolling is definitely needed
SEGMENT_FRAME_PADDING = 10     # Extra padding for segment area height calculation
DEFAULT_WIDTH = 750            # Increased default width slightly
DEFAULT_HEIGHT = 450           # Default window height if no config/geometry found
VERTICAL_PADDING = 40          # Extra vertical padding for dynamic resize calculation
DEFAULT_SCAN_INTERVAL = 5      # Default auto scan interval in minutes

# --- Colors ---
COLOR_AUTO_ON = "green"
COLOR_AUTO_OFF = "orange"

# --- Helper Functions ---
def safe_makedirs(path):
    """Creates directory if it doesn't exist, handles potential race conditions."""
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError as e:
            # Handle race condition: directory created between check and makedirs
            if e.errno != 17: # errno 17: File exists
                raise

def load_last_config_path():
    """Loads the path of the last used config file."""
    try:
        if os.path.exists(LAST_CONFIG_MARKER_FILE):
            with open(LAST_CONFIG_MARKER_FILE, 'r') as f:
                path = f.read().strip()
                if os.path.isfile(path): return path
                elif os.path.exists(path): print "Warning: Last config path exists but is not a file: {}".format(path)
    except Exception as e:
        print "Warning: Could not load last config path: {}".format(e)
    return ""

def save_last_config_path(config_path):
    """Saves the path of the currently used config file."""
    try:
        safe_makedirs(DEFAULT_CONFIG_DIR)
        with open(LAST_CONFIG_MARKER_FILE, 'w') as f: f.write(config_path)
    except Exception as e:
        print "Warning: Could not save last config path: {}".format(e)

# --- Main Application Class ---
class XCopyApp:
    def __init__(self, master):
        self.master = master
        master.title("xCopy - Multi-File Copier")
        master.configure(bg=GUI_BACKGROUND_COLOR) # Apply theme to master window
        master.geometry("{}x{}".format(DEFAULT_WIDTH, DEFAULT_HEIGHT))
        master.minsize(DEFAULT_WIDTH - 100, 350)

        # --- Fonts ---
        self.bold_font = tkFont.Font(weight='bold')

        # --- Ensure default config dir exists ---
        try: safe_makedirs(DEFAULT_CONFIG_DIR)
        except Exception as e: tkMessageBox.showerror("Error", "Could not create default config directory:\n{}\n\nPlease check permissions.".format(DEFAULT_CONFIG_DIR))

        # --- Instance Variables ---
        self.segment_widgets = []
        self.copied_files_data = {}
        self.current_config_file = None
        self.config_data = {'segments': [], 'window_geometry': '', 'scan_interval_minutes': DEFAULT_SCAN_INTERVAL}
        self.copy_thread = None
        self.auto_mode_active = False
        self.auto_scan_job_id = None
        self.scan_interval_ms = DEFAULT_SCAN_INTERVAL * 60 * 1000

        self.desc_label = None; self.config_frame = None; self.segment_setup_frame = None;
        self.segments_container_frame = None; self.status_label = None; self.status_text = None;
        self.button_frame = None; self.segments_canvas = None; self.segments_scrollable_frame = None;
        self.config_path_var = tk.StringVar(); self.config_entry = None;
        self.num_segments_var = tk.StringVar(); self.num_segments_entry = None;
        self.set_segments_button = None; self.scan_interval_var = tk.StringVar();
        self.scan_interval_entry = None; self.auto_mode_status_label = None;
        self.start_button = None; self.auto_copy_button = None;

        self.build_ui()

        last_config = load_last_config_path()
        if last_config:
            self.config_path_var.set(last_config)
            self.load_config(show_success=False)
        else:
            self.config_path_var.set(os.path.join(DEFAULT_CONFIG_DIR, "my_config.xcfg"))
            self.scan_interval_var.set(str(DEFAULT_SCAN_INTERVAL))
            self.master.geometry("{}x{}".format(DEFAULT_WIDTH, DEFAULT_HEIGHT))
            self.create_segment_fields()

        if not last_config:
             self.create_segment_fields()

        if dir_util is None:
             self.log_status("ERROR: Directory copying disabled (distutils.dir_util not found).")
             tkMessageBox.showerror("Missing Module", "Could not import 'distutils.dir_util'.\nDirectory copying will be disabled.")


    def build_ui(self):
        master = self.master

        desc_text = ("Copies files/dirs segment by segment. Each segment runs in a thread.\n"
                     "Copies new items and updates modified items based on timestamps.\n"
                     "- Copy Pattern: Matches top-level items unless 'Recursive' is checked. '*' or empty matches all.\n"
                     "- Recursive Checkbox:\n"
                     "    - Unchecked: Copies matching top-level files. Copies matching top-level dirs recursively.\n"
                     "    - Checked: Recursively searches subdirs for *files* matching pattern.")
        self.desc_label = tk.Label(master, text=desc_text, justify=tk.LEFT, bg=GUI_BACKGROUND_COLOR)
        self.desc_label.grid(row=0, column=0, sticky='ew', padx=10, pady=5)

        self.config_frame = tk.Frame(master, padx=5, pady=5, bg=GUI_BACKGROUND_COLOR)
        self.config_frame.grid(row=1, column=0, sticky='ew', padx=5)
        config_label = tk.Label(self.config_frame, text="Copy Config:", bg=GUI_BACKGROUND_COLOR)
        config_label.pack(side=tk.LEFT, padx=(0, 5))
        
        save_button = tk.Button(self.config_frame, text="Save Config", command=lambda: self.save_config(show_messages=True), 
                                bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, activebackground=BUTTON_BACKGROUND_COLOR)
        save_button.pack(side=tk.RIGHT, padx=(5, 0))
        browse_button = tk.Button(self.config_frame, text="Browse...", command=self.browse_config_file, 
                                  bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, activebackground=BUTTON_BACKGROUND_COLOR)
        browse_button.pack(side=tk.RIGHT, padx=(5, 0))
        self.config_entry = tk.Entry(self.config_frame, textvariable=self.config_path_var) # Entry bg default white
        self.config_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.segment_setup_frame = tk.Frame(master, padx=5, pady=5, bg=GUI_BACKGROUND_COLOR)
        self.segment_setup_frame.grid(row=2, column=0, sticky='ew', padx=5)
        
        num_segments_label = tk.Label(self.segment_setup_frame, text="Number of Copy Segments:", bg=GUI_BACKGROUND_COLOR)
        num_segments_label.pack(side=tk.LEFT, padx=(0, 5))
        self.num_segments_var.set("1")
        self.num_segments_entry = tk.Entry(self.segment_setup_frame, textvariable=self.num_segments_var, width=4) # Entry bg default white
        self.num_segments_entry.pack(side=tk.LEFT)
        self.set_segments_button = tk.Button(self.segment_setup_frame, text="Set", command=self.create_segment_fields, 
                                             bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, activebackground=BUTTON_BACKGROUND_COLOR)
        self.set_segments_button.pack(side=tk.LEFT, padx=(2, 10))

        scan_interval_label = tk.Label(self.segment_setup_frame, text="Scan Interval (min):", bg=GUI_BACKGROUND_COLOR)
        scan_interval_label.pack(side=tk.LEFT, padx=(0, 5))
        self.scan_interval_var.set(str(DEFAULT_SCAN_INTERVAL))
        self.scan_interval_entry = tk.Entry(self.segment_setup_frame, textvariable=self.scan_interval_var, width=4) # Entry bg default white
        self.scan_interval_entry.pack(side=tk.LEFT)

        self.auto_mode_status_label = tk.Label(self.segment_setup_frame, text="Auto Mode OFF", fg=COLOR_AUTO_OFF, font=self.bold_font, bg=GUI_BACKGROUND_COLOR)
        self.auto_mode_status_label.pack(side=tk.LEFT, padx=(10, 0))

        self.segments_container_frame = tk.Frame(master, borderwidth=1, relief="sunken", bg=GUI_BACKGROUND_COLOR)
        self.segments_container_frame.grid(row=3, column=0, sticky='nsew', padx=10, pady=5)
        master.grid_rowconfigure(3, weight=1)
        master.grid_columnconfigure(0, weight=1)
        self.segments_canvas = tk.Canvas(self.segments_container_frame, bg=GUI_BACKGROUND_COLOR) # Canvas background
        scrollbar = tk.Scrollbar(self.segments_container_frame, orient="vertical", command=self.segments_canvas.yview) # Scrollbar default
        self.segments_scrollable_frame = tk.Frame(self.segments_canvas, bg=GUI_BACKGROUND_COLOR) # Frame inside canvas
        self.segments_scrollable_frame.bind("<Configure>", lambda e: self.segments_canvas.configure(scrollregion=self.segments_canvas.bbox("all")))
        self.segments_canvas.create_window((0, 0), window=self.segments_scrollable_frame, anchor="nw")
        self.segments_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.segments_canvas.pack(side="left", fill="both", expand=True)

        self.status_label = tk.Label(master, text="Status:", anchor='w', bg=GUI_BACKGROUND_COLOR)
        self.status_label.grid(row=4, column=0, sticky='w', padx=10, pady=(5,0))
        self.status_text = ScrolledText.ScrolledText(master, height=8, wrap=tk.WORD, state=tk.DISABLED) # ScrolledText bg default white
        self.status_text.grid(row=5, column=0, sticky='ew', padx=10, pady=(0,5))

        self.button_frame = tk.Frame(master, pady=5, bg=GUI_BACKGROUND_COLOR)
        self.button_frame.grid(row=6, column=0, pady=5)
        self.start_button = tk.Button(self.button_frame, text="Start Copy", command=self.start_copy_thread, width=15, 
                                      bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, activebackground=BUTTON_BACKGROUND_COLOR)
        self.start_button.pack(side=tk.LEFT, padx=10)
        
        self.auto_copy_button = tk.Button(self.button_frame, text="Start Auto Copy", command=self.toggle_auto_mode, width=15, 
                                          bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, activebackground=BUTTON_BACKGROUND_COLOR)
        self.auto_copy_button.pack(side=tk.LEFT, padx=10)

    def log_status(self, message):
        def update_gui():
            if self.status_text and self.status_text.winfo_exists():
                self.status_text.config(state=tk.NORMAL)
                self.status_text.insert(tk.END, message + "\n")
                self.status_text.see(tk.END)
                self.status_text.config(state=tk.DISABLED)
        if self.master and self.master.winfo_exists():
            self.master.after(0, update_gui)

    def browse_directory(self, entry_widget):
        initial_dir = entry_widget.get()
        if not os.path.isdir(initial_dir):
             initial_dir = DEFAULT_CONFIG_DIR if os.path.isdir(DEFAULT_CONFIG_DIR) else os.path.expanduser("~")
        dirname = tkFileDialog.askdirectory(
            parent=self.master, title="Select Directory", initialdir=initial_dir
        )
        if dirname:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, dirname)

    def browse_config_file(self):
        current_val = self.config_path_var.get()
        initial_dir = os.path.dirname(current_val) if os.path.dirname(current_val) else DEFAULT_CONFIG_DIR
        initial_file = os.path.basename(current_val) if current_val else "my_config.xcfg"
        if not os.path.isdir(initial_dir): initial_dir = DEFAULT_CONFIG_DIR
        filepath = tkFileDialog.asksaveasfilename(
            parent=self.master, title="Select or Create Config File", initialdir=initial_dir,
            initialfile=initial_file, filetypes=[("xCopy Config", "*.xcfg"), ("All Files", "*.*")],
            defaultextension=".xcfg"
        )
        if filepath:
            self.config_path_var.set(filepath)
            self.load_config()

    def load_config(self, show_success=True):
        filepath = self.config_path_var.get()
        default_interval = self.config_data.get('scan_interval_minutes', DEFAULT_SCAN_INTERVAL)
        self.config_data = {'segments': [], 'window_geometry': '', 'scan_interval_minutes': default_interval}
        self.current_config_file = None; self.copied_files_data = {}; loaded_geometry = None; loaded_interval = default_interval

        if not filepath:
            self.num_segments_var.set("1"); self.scan_interval_var.set(str(default_interval))
            self.create_segment_fields(); self.apply_geometry(None); return

        if not filepath.endswith(".xcfg"): print "Warning: Config file does not end with '.xcfg': {}".format(filepath)

        try:
            if os.path.isfile(filepath):
                with open(filepath, 'r') as f: loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    self.config_data = loaded_data
                    if 'segments' not in self.config_data: self.config_data['segments'] = []
                    if 'window_geometry' not in self.config_data: self.config_data['window_geometry'] = ''
                    if 'scan_interval_minutes' not in self.config_data: self.config_data['scan_interval_minutes'] = DEFAULT_SCAN_INTERVAL
                    for seg in self.config_data.get('segments', []):
                        if 'recursive' not in seg: seg['recursive'] = False
                    loaded_geometry = self.config_data.get('window_geometry')
                    loaded_interval = self.config_data.get('scan_interval_minutes', DEFAULT_SCAN_INTERVAL)
                elif isinstance(loaded_data, list): 
                    print "Warning: Loading old config format (list). Converting."
                    self.config_data['segments'] = [{'source': s.get('source',''), 'target': s.get('target',''), 'wildcard': s.get('wildcard',''), 'recursive': False} for s in loaded_data]
                    self.config_data['window_geometry'] = ''; self.config_data['scan_interval_minutes'] = DEFAULT_SCAN_INTERVAL
                    loaded_interval = DEFAULT_SCAN_INTERVAL
                else: raise ValueError("Config file format is incorrect (should be a dict or list).")

                self.current_config_file = filepath
                if show_success: self.log_status("Loaded configuration from: {}".format(filepath))
                save_last_config_path(filepath)
                self.num_segments_var.set(str(len(self.config_data.get('segments', [])))); self.scan_interval_var.set(str(loaded_interval))
                self.create_segment_fields(); self.load_copied_files_db()
                if show_success: tkMessageBox.showinfo("Load Config", "Configuration loaded successfully.")
            elif os.path.exists(filepath):
                tkMessageBox.showerror("Load Config Error", "Specified path is not a valid file:\n{}".format(filepath))
                self.num_segments_var.set("1"); self.scan_interval_var.set(str(DEFAULT_SCAN_INTERVAL)); self.create_segment_fields(); loaded_geometry = None
            else: 
                 if show_success: self.log_status("Config file does not exist yet: {}. Will be created on save.".format(filepath))
                 self.num_segments_var.set("1"); self.scan_interval_var.set(str(DEFAULT_SCAN_INTERVAL)); self.create_segment_fields(); loaded_geometry = None
        except (IOError, ValueError, json.JSONDecodeError) as e:
            tkMessageBox.showerror("Load Config Error", "Failed to load or parse config file:\n{}\n\nError: {}".format(filepath, e))
            self.num_segments_var.set("1"); self.scan_interval_var.set(str(DEFAULT_SCAN_INTERVAL)); self.create_segment_fields(); loaded_geometry = None
        except Exception as e:
            tkMessageBox.showerror("Load Config Error", "An unexpected error occurred during load:\n{}".format(e))
            self.num_segments_var.set("1"); self.scan_interval_var.set(str(DEFAULT_SCAN_INTERVAL)); self.create_segment_fields(); loaded_geometry = None
        self.apply_geometry(loaded_geometry)

    def apply_geometry(self, geometry_string):
        if not self.master or not self.master.winfo_exists(): return
        if geometry_string and re.match(r"^\d+x\d+$", geometry_string):
            try:
                width, height = map(int, geometry_string.split('x')); min_w, min_h = self.master.minsize()
                safe_w = max(width, min_w); safe_h = max(height, min_h); safe_geometry = "{}x{}".format(safe_w, safe_h)
                self.master.geometry(safe_geometry)
            except Exception as e: print "Warning: Failed to apply geometry '{}': {}".format(geometry_string, e); self.master.geometry("{}x{}".format(DEFAULT_WIDTH, DEFAULT_HEIGHT))
        elif geometry_string: print "Warning: Invalid geometry string found in config: '{}'".format(geometry_string); self.master.geometry("{}x{}".format(DEFAULT_WIDTH, DEFAULT_HEIGHT))

    def populate_segment_fields_from_config(self):
         segments = self.config_data.get('segments', [])
         num_to_populate = min(len(segments), len(self.segment_widgets))
         for i in range(num_to_populate):
             segment = segments[i]
             if len(self.segment_widgets[i]) == 4:
                 src_entry, tgt_entry, wc_entry, recursive_var = self.segment_widgets[i]
                 src_entry.delete(0, tk.END); src_entry.insert(0, segment.get('source', ''))
                 tgt_entry.delete(0, tk.END); tgt_entry.insert(0, segment.get('target', ''))
                 wc_entry.delete(0, tk.END); wc_val = segment.get('wildcard', ''); wc_entry.insert(0, wc_val if wc_val else '*')
                 recursive_var.set(segment.get('recursive', False))
             else:
                 print "Error: Segment widget structure mismatch during population."


    def save_config(self, show_messages=False):
        filepath = self.config_path_var.get()
        if not filepath:
            self.log_status("Error: Cannot save config, no file path specified.")
            if show_messages: tkMessageBox.showerror("Save Config", "Please specify a configuration file path first.")
            return False
        if os.path.isdir(filepath):
            self.log_status("Error: Cannot save config, specified path is a directory: {}".format(filepath))
            if show_messages: tkMessageBox.showerror("Save Config", "Cannot save config, specified path is a directory:\n{}".format(filepath))
            return False

        if not filepath.endswith(".xcfg"):
            if show_messages and os.path.sep not in filepath and not tkMessageBox.askyesno("Save Config", "Config file does not end with '.xcfg'.\nSave anyway?"):
                return False
            elif os.path.sep in filepath:
                 print "Info: Saving config file without '.xcfg' extension: {}".format(filepath)

        config_to_save = {'segments': [], 'window_geometry': '', 'scan_interval_minutes': DEFAULT_SCAN_INTERVAL}
        for i, (src_entry, tgt_entry, wc_entry, recursive_var) in enumerate(self.segment_widgets):
            config_to_save['segments'].append({
                'source': src_entry.get().strip(),
                'target': tgt_entry.get().strip(),
                'wildcard': wc_entry.get().strip(),
                'recursive': recursive_var.get()
            })
        if self.master and self.master.winfo_exists():
             geom = self.master.winfo_geometry(); match = re.match(r"(\d+x\d+)", geom)
             if match: config_to_save['window_geometry'] = match.group(1)
             else: print "Warning: Could not parse current window geometry: {}".format(geom)
        try:
            interval_val = int(self.scan_interval_var.get())
            if interval_val > 0: config_to_save['scan_interval_minutes'] = interval_val
            else: print "Warning: Invalid scan interval '{}' not saved.".format(interval_val)
        except ValueError: print "Warning: Non-integer scan interval '{}' not saved.".format(self.scan_interval_var.get())

        self.config_data = config_to_save

        try:
            config_dir = os.path.dirname(filepath);
            if config_dir: safe_makedirs(config_dir)
            with open(filepath, 'w') as f: json.dump(self.config_data, f, indent=4)
            self.current_config_file = filepath;
            self.log_status("Configuration saved to: {}".format(filepath))
            save_last_config_path(filepath);
            if show_messages: tkMessageBox.showinfo("Save Config", "Configuration saved successfully.")
            self.load_copied_files_db()
            return True
        except IOError as e:
             self.log_status("Error: Failed to save config file: {}".format(e))
             if show_messages: tkMessageBox.showerror("Save Config Error", "Failed to save config file:\n{}\n\nError: {}".format(filepath, e));
             self.current_config_file = None
             return False
        except Exception as e:
             self.log_status("Error: An unexpected error occurred during save: {}".format(e))
             if show_messages: tkMessageBox.showerror("Save Config Error", "An unexpected error occurred during save:\n{}".format(e));
             self.current_config_file = None
             return False

    def create_segment_fields(self):
        try:
            num_segments = int(self.num_segments_var.get())
            if num_segments < 0: raise ValueError("Number of segments cannot be negative.")
        except ValueError: tkMessageBox.showerror("Invalid Input", "Please enter a valid non-negative number for segments."); self.num_segments_var.set(str(len(self.segment_widgets) if self.segment_widgets else 1)); return

        for widget in self.segments_scrollable_frame.winfo_children(): widget.destroy()
        self.segment_widgets = []

        if num_segments > 0:
            for i in range(num_segments):
                segment_frame = tk.Frame(self.segments_scrollable_frame, borderwidth=1, relief="groove", padx=5, pady=3, bg=GUI_BACKGROUND_COLOR); # Frame bg
                segment_frame.pack(fill=tk.X, pady=(1,2), padx=5)
                segment_frame.columnconfigure(1, weight=1)

                src_label = tk.Label(segment_frame, text="Source Dir {}:".format(i+1), anchor='w', bg=GUI_BACKGROUND_COLOR); 
                src_label.grid(row=0, column=0, padx=(0, 5), pady=1, sticky='w')
                src_entry = tk.Entry(segment_frame); # Entry bg default white
                src_entry.grid(row=0, column=1, padx=(0, 5), pady=1, sticky='ew')
                src_browse_cmd = functools.partial(self.browse_directory, src_entry); 
                src_browse_button = tk.Button(segment_frame, text="...", command=src_browse_cmd, width=3, 
                                              bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, activebackground=BUTTON_BACKGROUND_COLOR); 
                src_browse_button.grid(row=0, column=2, pady=1, sticky='w')

                tgt_label = tk.Label(segment_frame, text="Target Dir {}:".format(i+1), anchor='w', bg=GUI_BACKGROUND_COLOR); 
                tgt_label.grid(row=1, column=0, padx=(0, 5), pady=1, sticky='w')
                tgt_entry = tk.Entry(segment_frame); # Entry bg default white
                tgt_entry.grid(row=1, column=1, padx=(0, 5), pady=1, sticky='ew')
                tgt_browse_cmd = functools.partial(self.browse_directory, tgt_entry); 
                tgt_browse_button = tk.Button(segment_frame, text="...", command=tgt_browse_cmd, width=3, 
                                              bg=BUTTON_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, activebackground=BUTTON_BACKGROUND_COLOR); 
                tgt_browse_button.grid(row=1, column=2, pady=1, sticky='w')

                wc_label = tk.Label(segment_frame, text="Copy Pattern {}:".format(i+1), anchor='w', bg=GUI_BACKGROUND_COLOR); 
                wc_label.grid(row=2, column=0, padx=(0, 5), pady=1, sticky='w')
                wc_entry = tk.Entry(segment_frame); # Entry bg default white
                wc_entry.grid(row=2, column=1, padx=(0, 5), pady=1, sticky='ew')

                recursive_var = tk.BooleanVar()
                # For Checkbutton:
                # bg: background of the label part
                # fg: text color
                # activebackground: background when hovered
                # selectcolor: color of the check indicator box when selected
                recursive_check = tk.Checkbutton(segment_frame, text="Recursive", variable=recursive_var, 
                                                 bg=GUI_BACKGROUND_COLOR, fg=BUTTON_TEXT_COLOR, 
                                                 activebackground=GUI_BACKGROUND_COLOR, 
                                                 selectcolor=BUTTON_BACKGROUND_COLOR) 
                recursive_check.grid(row=2, column=2, padx=(5, 0), pady=1, sticky='w')

                self.segment_widgets.append((src_entry, tgt_entry, wc_entry, recursive_var))

        if self.config_data.get('segments') and num_segments > 0: self.populate_segment_fields_from_config()
        elif num_segments > 0:
             for _, _, wc_entry, recursive_var in self.segment_widgets:
                 if not wc_entry.get(): wc_entry.insert(0, "*")
                 recursive_var.set(False)

        self.master.update_idletasks()
        req_height_segments = self.segments_scrollable_frame.winfo_reqheight()
        canvas_height = MIN_SEGMENT_AREA_HEIGHT if num_segments == 0 else max(MIN_SEGMENT_AREA_HEIGHT, min(req_height_segments + SEGMENT_FRAME_PADDING, MAX_SEGMENT_AREA_HEIGHT))
        self.segments_canvas.config(height=canvas_height)
        self.segments_canvas.configure(scrollregion=self.segments_canvas.bbox("all"))

        loaded_geom = self.config_data.get('window_geometry')
        if not loaded_geom:
            try:
                if all([self.desc_label, self.config_frame, self.segment_setup_frame, self.status_label, self.status_text, self.button_frame]):
                    other_elements_height = ( self.desc_label.winfo_reqheight() + self.config_frame.winfo_reqheight() + self.segment_setup_frame.winfo_reqheight() + self.status_label.winfo_reqheight() + self.status_text.winfo_reqheight() + self.button_frame.winfo_reqheight() )
                    grid_padding = 40; total_required_height = other_elements_height + canvas_height + grid_padding + VERTICAL_PADDING
                    current_width = self.master.winfo_width(); min_w, min_h = self.master.minsize()
                    current_width = max(current_width, DEFAULT_WIDTH, min_w); total_required_height = max(total_required_height, min_h)
                    new_geometry = "{}x{}".format(current_width, total_required_height); self.master.geometry(new_geometry)
            except tk.TclError as e: print "Warning: TclError during dynamic resize calculation: {}".format(e)

    def toggle_auto_mode(self):
        if self.auto_mode_active:
            self.auto_mode_active = False
            if self.auto_scan_job_id:
                try: self.master.after_cancel(self.auto_scan_job_id); self.log_status("Scheduled auto-scan cancelled.")
                except tk.TclError: pass
                self.auto_scan_job_id = None
            self.auto_mode_status_label.config(text="Auto Mode OFF", fg=COLOR_AUTO_OFF, bg=GUI_BACKGROUND_COLOR) # Updated bg
            self.auto_copy_button.config(text="Start Auto Copy")
            if self.scan_interval_entry: self.scan_interval_entry.config(state=tk.NORMAL)
            if self.set_segments_button: self.set_segments_button.config(state=tk.NORMAL)
            if self.num_segments_entry: self.num_segments_entry.config(state=tk.NORMAL)
            self.log_status("Auto Mode Stopped.")
        else:
            self.log_status("Attempting to save current configuration...")
            save_success = self.save_config(show_messages=False)
            if not save_success:
                self.log_status("Error: Failed to save configuration automatically. Auto Mode aborted.")
                tkMessageBox.showerror("Auto Mode Error", "Failed to save current configuration.\nPlease check config path and permissions.\nAuto Mode cannot start.")
                return
            self.log_status("Configuration saved successfully.")

            try: 
                interval_min = int(self.scan_interval_var.get())
                if interval_min <= 0: tkMessageBox.showerror("Invalid Interval", "Scan interval must be a positive number of minutes."); return
                self.scan_interval_ms = interval_min * 60 * 1000
            except ValueError: tkMessageBox.showerror("Invalid Interval", "Please enter a valid number for the scan interval (minutes)."); return

            self.auto_mode_active = True
            self.auto_mode_status_label.config(text="Auto Mode ON", fg=COLOR_AUTO_ON, bg=GUI_BACKGROUND_COLOR) # Updated bg
            self.auto_copy_button.config(text="Stop Auto Copy")
            if self.scan_interval_entry: self.scan_interval_entry.config(state=tk.DISABLED)
            if self.set_segments_button: self.set_segments_button.config(state=tk.DISABLED)
            if self.num_segments_entry: self.num_segments_entry.config(state=tk.DISABLED)
            self.log_status("Auto Mode Started. Interval: {} minutes.".format(interval_min))
            self.auto_scan_job_id = self.master.after(1000, self.perform_auto_scan)

    def perform_auto_scan(self):
        if not self.master or not self.master.winfo_exists(): print "Info: Master window closed, stopping auto-scan."; self.auto_mode_active = False; return
        if not self.auto_mode_active: return
        reschedule_delay = self.scan_interval_ms
        try:
            if self.copy_thread and self.copy_thread.is_alive(): self.log_status("[Auto-Scan] Skipping check - copy already in progress.")
            else:
                segments_data = self.config_data.get('segments', [])
                if not segments_data: self.log_status("[Auto-Scan] No segments defined, skipping check.")
                else:
                    if isinstance(segments_data, list):
                        self.load_copied_files_db()
                        self.copy_thread = threading.Thread(target=self.copy_worker, args=(list(segments_data),))
                        self.copy_thread.daemon = True; self.copy_thread.start()
                    else:
                         self.log_status("[Auto-Scan] Invalid segment data structure found, skipping check.")

        except Exception as e: self.log_status("[Auto-Scan] Error during scan: {}".format(e))
        finally:
            if self.auto_mode_active and self.master.winfo_exists(): self.auto_scan_job_id = self.master.after(reschedule_delay, self.perform_auto_scan)

    def get_copied_files_db_path(self):
        current_config_path = self.config_path_var.get()
        if current_config_path:
             config_dir = os.path.dirname(current_config_path)
             if not config_dir: config_dir = DEFAULT_CONFIG_DIR; print "Info: Config path has no directory, using default for tracking DB: {}".format(config_dir)
             safe_makedirs(config_dir); return os.path.join(config_dir, COPIED_FILES_DB_NAME)
        else: print "Warning: No config path set. Using default directory for copy tracking."; safe_makedirs(DEFAULT_CONFIG_DIR); return os.path.join(DEFAULT_CONFIG_DIR, COPIED_FILES_DB_NAME)

    def load_copied_files_db(self):
        db_path = self.get_copied_files_db_path(); self.copied_files_data = {}
        if not db_path: self.log_status("Warning: Could not determine path for copy tracking database."); return
        try:
            if os.path.isfile(db_path):
                with open(db_path, 'r') as f: loaded_db = json.load(f)
                if not isinstance(loaded_db, dict): print "Warning: Copied files DB format incorrect ({}), resetting.".format(db_path)
                else: self.copied_files_data = loaded_db;
            elif os.path.exists(db_path): self.log_status("Warning: Expected copy tracking DB is not a file: {}. Starting fresh.".format(db_path))
        except (IOError, json.JSONDecodeError) as e: self.log_status("Error loading copied files DB '{}': {}. Starting fresh.".format(db_path, e)); self.copied_files_data = {}
        except Exception as e: self.log_status("Unexpected error loading copied files DB '{}': {}. Starting fresh.".format(db_path, e)); self.copied_files_data = {}

    def save_copied_files_db(self):
        db_path = self.get_copied_files_db_path()
        if not db_path: self.log_status("Error: Cannot determine path to save copied files database."); return
        try:
            with open(db_path, 'w') as f: json.dump(self.copied_files_data, f, indent=4)
        except IOError as e: self.log_status("Error saving copied files DB '{}': {}".format(db_path, e))
        except Exception as e: self.log_status("Unexpected error saving copied files DB '{}': {}".format(db_path, e))

    def start_copy_thread(self):
        if self.copy_thread and self.copy_thread.is_alive(): tkMessageBox.showwarning("Busy", "A copy operation is already in progress."); return

        self.log_status("Attempting to save current configuration...")
        save_success = self.save_config(show_messages=False)
        if not save_success:
            self.log_status("Error: Failed to save configuration automatically. Manual copy aborted.")
            return
        self.log_status("Configuration saved successfully.")

        self.start_button.config(state=tk.DISABLED, text="Copying...")
        if self.auto_copy_button: self.auto_copy_button.config(state=tk.DISABLED)
        self.status_text.config(state=tk.NORMAL); self.status_text.delete('1.0', tk.END); self.status_text.config(state=tk.DISABLED)
        self.log_status("Starting manual copy process...")
        self.load_copied_files_db()

        segments_data = list(self.config_data.get('segments', []))

        if not segments_data:
            self.log_status("No segments defined in configuration.")
            self.start_button.config(state=tk.NORMAL, text="Start Copy")
            if self.auto_copy_button: self.auto_copy_button.config(state=tk.NORMAL); return

        self.copy_thread = threading.Thread(target=self.copy_worker, args=(list(segments_data),))
        self.copy_thread.daemon = True; self.copy_thread.start()
        self.monitor_copy_thread()


    def monitor_copy_thread(self):
        if self.copy_thread and self.copy_thread.is_alive(): self.master.after(100, self.monitor_copy_thread)
        else:
            if self.start_button and self.start_button.winfo_exists(): self.start_button.config(state=tk.NORMAL, text="Start Copy")
            if not self.auto_mode_active and self.auto_copy_button and self.auto_copy_button.winfo_exists():
                 self.auto_copy_button.config(state=tk.NORMAL)

    def copy_worker(self, segments):
        files_copied_count = 0; dirs_copied_count = 0; files_skipped_count = 0; dirs_skipped_count = 0; items_failed_count = 0
        db_updated = False 
        process_name = "[Auto-Scan]" if self.auto_mode_active else "[Manual Copy]"
        can_copy_dirs = dir_util is not None 

        current_config_basename = None
        if self.current_config_file:
            try:
                if isinstance(self.current_config_file, (str, unicode)) and self.current_config_file:
                     current_config_basename = os.path.basename(self.current_config_file)
            except Exception as e:
                 print "Warning: Could not get basename for current_config_file '{}': {}".format(self.current_config_file, e)


        try:
            for i, segment in enumerate(segments):
                source_dir = segment.get('source',''); target_dir = segment.get('target','')
                wildcard = segment.get('wildcard', ''); wildcard = wildcard if wildcard else "*"
                is_recursive_search = segment.get('recursive', False)

                if not source_dir or not target_dir:
                    self.log_status("{} Info: Skipping segment {} (Source or Target is empty).".format(process_name, i+1))
                    items_failed_count += 1
                    continue
                if not os.path.isdir(source_dir):
                    self.log_status("{} Error: Source '{}' not found/not dir. Skipping segment.".format(process_name, source_dir))
                    items_failed_count += 1; continue
                try: safe_makedirs(target_dir)
                except OSError as e:
                    self.log_status("{} Error: Cannot create target '{}': {}. Skipping segment.".format(process_name, target_dir, e))
                    items_failed_count += 1; continue

                if is_recursive_search:
                    self.log_status("{} Segment {}: Recursive search for files matching '{}' in '{}'".format(process_name, i+1, wildcard, source_dir))
                    try:
                        for dirpath, dirnames, filenames in os.walk(source_dir):
                            if COPIED_FILES_DB_NAME in filenames: filenames.remove(COPIED_FILES_DB_NAME)
                            if current_config_basename and current_config_basename in filenames: filenames.remove(current_config_basename)

                            for filename in filenames:
                                if fnmatch.fnmatch(filename, wildcard):
                                    abs_src_file_path = os.path.abspath(os.path.join(dirpath, filename))
                                    target_file_path = os.path.join(target_dir, filename) 

                                    try: 
                                        current_mtime = os.path.getmtime(abs_src_file_path)
                                        recorded_mtime = self.copied_files_data.get(abs_src_file_path)
                                        target_exists = os.path.exists(target_file_path)
                                        copy_needed = False
                                        copy_reason = ""

                                        if not target_exists:
                                            copy_needed = True
                                            copy_reason = "Copying missing target file"
                                        else:
                                            if recorded_mtime is not None and recorded_mtime == current_mtime:
                                                self.log_status("{} Skipping file (unchanged vs DB): {} (in {})".format(process_name, filename, os.path.basename(dirpath)))
                                                files_skipped_count += 1
                                                continue 
                                            else:
                                                try:
                                                    target_mtime = os.path.getmtime(target_file_path)
                                                    if current_mtime > target_mtime:
                                                        copy_needed = True
                                                        copy_reason = "Overwriting existing target file (source is newer)"
                                                    else:
                                                        self.log_status("{} Skipping file (target is newer/same): {}".format(process_name, filename))
                                                        files_skipped_count += 1
                                                        if recorded_mtime is None: 
                                                             self.copied_files_data[abs_src_file_path] = target_mtime
                                                             db_updated = True
                                                        continue 
                                                except OSError as e_stat:
                                                     self.log_status("{} Warning: Cannot stat existing target file '{}': {}. Attempting copy.".format(process_name, target_file_path, e_stat))
                                                     copy_needed = True 
                                                     copy_reason = "Copying file (target stat failed)"

                                        if copy_needed:
                                            self.log_status("{} {}: {} -> {}".format(process_name, copy_reason, filename, target_dir))
                                            shutil.copy2(abs_src_file_path, target_file_path)
                                            files_copied_count += 1
                                            self.copied_files_data[abs_src_file_path] = current_mtime
                                            db_updated = True

                                    except Exception as e_copy:
                                        self.log_status("{} Error processing recursively found file '{}': {}".format(process_name, filename, e_copy))
                                        items_failed_count += 1
                    except Exception as e_walk:
                         self.log_status("{} Error walking directory '{}': {}".format(process_name, source_dir, e_walk))
                         items_failed_count += 1

                else:
                    self.log_status("{} Segment {}: Top-level search for '{}'".format(process_name, i+1, wildcard))
                    source_pattern = os.path.join(source_dir, wildcard)
                    try: items_to_check = glob.glob(source_pattern)
                    except Exception as e: self.log_status("{} Error finding items '{}': {}. Skipping segment.".format(process_name, source_pattern, e)); continue
                    if not items_to_check: self.log_status("{} No top-level items found matching '{}'".format(process_name, wildcard)); continue

                    for src_path in items_to_check:
                        item_basename = os.path.basename(src_path)
                        abs_src_path = os.path.abspath(src_path)

                        if item_basename == COPIED_FILES_DB_NAME:
                            self.log_status("{} Skipping tracking DB file: {}".format(process_name, item_basename))
                            continue
                        if current_config_basename and item_basename == current_config_basename:
                            self.log_status("{} Skipping current config file: {}".format(process_name, item_basename))
                            continue

                        if os.path.isdir(abs_src_path):
                            target_subdir_path = os.path.join(target_dir, item_basename)
                            try:
                                if not os.path.exists(target_subdir_path):
                                    self.log_status("{} Copying new directory tree: {} -> {}".format(process_name, item_basename, target_dir))
                                    shutil.copytree(abs_src_path, target_subdir_path, symlinks=False) 
                                    dirs_copied_count += 1
                                elif can_copy_dirs: 
                                    self.log_status("{} Updating existing directory tree: {} -> {}".format(process_name, item_basename, target_dir))
                                    copied_list = dir_util.copy_tree(abs_src_path, target_subdir_path, update=1, verbose=0)
                                    if copied_list:
                                         self.log_status("{} Updated directory: {} ({} files changed)".format(process_name, item_basename, len(copied_list)))
                                         dirs_copied_count += 1
                                else: 
                                     self.log_status("{} Skipping directory update (distutils not found): {}".format(process_name, item_basename))
                                     dirs_skipped_count += 1

                            except Exception as e:
                                self.log_status("{} Error processing directory '{}': {}".format(process_name, item_basename, e))
                                items_failed_count += 1
                            continue 


                        elif os.path.isfile(abs_src_path):
                            try: 
                                target_path = os.path.join(target_dir, item_basename)
                                current_mtime = os.path.getmtime(abs_src_path)
                                recorded_mtime = self.copied_files_data.get(abs_src_path)
                                target_exists = os.path.exists(target_path)
                                copy_needed = False
                                copy_reason = ""

                                if not target_exists:
                                    copy_needed = True
                                    copy_reason = "Copying missing target file"
                                else:
                                    if recorded_mtime is not None and recorded_mtime == current_mtime:
                                        self.log_status("{} Skipping file (unchanged vs DB): {}".format(process_name, item_basename))
                                        files_skipped_count += 1
                                        continue 
                                    else:
                                        try:
                                            target_mtime = os.path.getmtime(target_path)
                                            if current_mtime > target_mtime:
                                                copy_needed = True
                                                copy_reason = "Overwriting existing target file (source is newer)"
                                            else:
                                                self.log_status("{} Skipping file (target is newer/same): {}".format(process_name, item_basename))
                                                files_skipped_count += 1
                                                if recorded_mtime is None: 
                                                     self.copied_files_data[abs_src_path] = target_mtime
                                                     db_updated = True
                                                continue 
                                        except OSError as e_stat:
                                             self.log_status("{} Warning: Cannot stat existing target file '{}': {}. Attempting copy.".format(process_name, target_path, e_stat))
                                             copy_needed = True 
                                             copy_reason = "Copying file (target stat failed)"
                                if copy_needed:
                                    self.log_status("{} {}: {} -> {}".format(process_name, copy_reason, item_basename, target_dir))
                                    shutil.copy2(abs_src_path, target_path)
                                    files_copied_count += 1
                                    self.copied_files_data[abs_src_path] = current_mtime
                                    db_updated = True

                            except Exception as e: self.log_status("{} Error processing file '{}': {}".format(process_name, item_basename, e)); items_failed_count += 1
                            continue 
                        else: self.log_status("{} Skipping unsupported item: {}".format(process_name, item_basename)); items_failed_count += 1
        except Exception as e:
             self.log_status("\n{} FATAL ERROR DURING COPY PROCESS ---".format(process_name)); self.log_status("Error: {}".format(e))
             if db_updated: self.save_copied_files_db() 
        finally:
            if db_updated: self.save_copied_files_db()

            log_summary = (files_copied_count > 0 or dirs_copied_count > 0 or items_failed_count > 0 or not self.auto_mode_active)
            if log_summary:
                self.log_status("\n{} --- Finished ---".format(process_name))
                self.log_status("Files Copied:  {}".format(files_copied_count))
                self.log_status("Dirs Copied:   {}".format(dirs_copied_count))
                self.log_status("Files Skipped: {}".format(files_skipped_count))
                self.log_status("Items Failed/Skipped: {}".format(items_failed_count))
            elif self.auto_mode_active:
                 pass


# --- Main Execution ---
if __name__ == "__main__":
    if dir_util is None or fnmatch is None:
         root = tk.Tk()
         root.withdraw() 
         tkMessageBox.showerror("Missing Modules", "Could not import required modules (distutils.dir_util or fnmatch).\nPlease ensure a standard Python 2.7 distribution is used.\nApplication will exit.")
         sys.exit(1)

    root = tk.Tk()
    app = XCopyApp(root)
    def on_closing():
        print "Window closing..."
        if app.auto_mode_active: print "Stopping auto mode..."; app.toggle_auto_mode()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
