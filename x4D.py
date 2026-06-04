#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Ai assisted code by R.Bolisay
# Python 2.7 GUI Application: x4D QC Tool
# This script creates a Tkinter-based GUI for performing quality control checks
# on navigation line data files, including a new tab with an interactive graph
# implemented directly on a Tkinter Canvas (no Matplotlib).

try:
    import Tkinter as tk
    import tkFileDialog
except ImportError:
    import tkinter as tk
    from tkinter import filedialog as tkFileDialog
import os
try:
    import ConfigParser
except ImportError:
    import configparser as ConfigParser
import re
import csv
try:
    import ttk # For Notebook (tabbed interface)
except ImportError:
    from tkinter import ttk
import math # For mathematical operations like min/max, abs
import time # For throttling operations
import json # For caching system
import hashlib # For file change detection

class SpatialDataCache:
    """High-performance spatial data cache with file change detection."""
    
    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".x4d_cache")
        self.cache_file = os.path.join(self.cache_dir, "spatial_data_cache.json")
        self.tile_size = 5000.0  # 5km tiles for good balance of performance vs memory
        self.cache_data = {}
        self.spatial_index = {}  # tile_id -> [sequence_numbers]
        self.sequence_bounds = {}  # sequence_number -> (min_x, min_y, max_x, max_y)
        
        # Ensure cache directory exists
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        
        self.load_cache()
    
    def get_tile_id(self, x, y):
        """Convert coordinates to tile ID."""
        tile_x = int(x // self.tile_size)
        tile_y = int(y // self.tile_size)
        return "%d_%d" % (tile_x, tile_y)
    
    def get_tile_bounds(self, tile_id):
        """Get geographic bounds of a tile."""
        tile_x, tile_y = map(int, tile_id.split('_'))
        min_x = tile_x * self.tile_size
        max_x = (tile_x + 1) * self.tile_size
        min_y = tile_y * self.tile_size
        max_y = (tile_y + 1) * self.tile_size
        return (min_x, min_y, max_x, max_y)
    
    def get_tiles_in_bounds(self, min_x, min_y, max_x, max_y):
        """Get all tile IDs that intersect with the given bounds."""
        tiles = set()
        
        # Add buffer to ensure we get adjacent tiles
        buffer = self.tile_size * 0.1  # 10% buffer
        min_x -= buffer
        min_y -= buffer
        max_x += buffer
        max_y += buffer
        
        start_tile_x = int(min_x // self.tile_size)
        end_tile_x = int(max_x // self.tile_size)
        start_tile_y = int(min_y // self.tile_size)
        end_tile_y = int(max_y // self.tile_size)
        
        for tile_x in range(start_tile_x, end_tile_x + 1):
            for tile_y in range(start_tile_y, end_tile_y + 1):
                tiles.add("%d_%d" % (tile_x, tile_y))
        
        return tiles
    
    def get_file_hash(self, file_path):
        """Calculate MD5 hash of file for change detection."""
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return None
    
    def is_file_changed(self, file_path, cached_info):
        """Check if file has changed since cache."""
        if not os.path.exists(file_path):
            return True
        
        current_mtime = os.path.getmtime(file_path)
        cached_mtime = cached_info.get('last_modified', 0)
        
        # Quick check: modification time
        if current_mtime != cached_mtime:
            return True
        
        # Detailed check: file hash
        current_hash = self.get_file_hash(file_path)
        cached_hash = cached_info.get('file_hash', '')
        
        return current_hash != cached_hash
    
    def load_cache(self):
        """Load cache from disk."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    self.cache_data = data.get('cache_data', {})
                    self.spatial_index = data.get('spatial_index', {})
                    self.sequence_bounds = data.get('sequence_bounds', {})
                    print("Loaded cache with %d sequences in %d tiles" % (len(self.cache_data), len(self.spatial_index)))
        except Exception as e:
            print("Cache load error (starting fresh): %s" % str(e))
            self.cache_data = {}
            self.spatial_index = {}
            self.sequence_bounds = {}
    
    def save_cache(self):
        """Save cache to disk."""
        try:
            cache_structure = {
                'cache_version': '1.0',
                'last_updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'cache_data': self.cache_data,
                'spatial_index': self.spatial_index,
                'sequence_bounds': self.sequence_bounds
            }
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_structure, f, indent=2)
            print("Cache saved with %d sequences" % len(self.cache_data))
        except Exception as e:
            print("Cache save error: %s" % str(e))
    
    def get_sequences_for_bounds(self, min_x, min_y, max_x, max_y):
        """Get all sequences that have data within the specified bounds."""
        relevant_tiles = self.get_tiles_in_bounds(min_x, min_y, max_x, max_y)
        sequences = set()
        
        for tile_id in relevant_tiles:
            if tile_id in self.spatial_index:
                sequences.update(self.spatial_index[tile_id])
        
        return list(sequences)
    
    def add_sequence_data(self, sequence_num, file_path, data_points):
        """Add sequence data to cache with spatial indexing."""
        if not data_points:
            return
        
        # Calculate sequence bounds
        eastings = [point[0] for point in data_points]
        northings = [point[1] for point in data_points]
        min_x, max_x = min(eastings), max(eastings)
        min_y, max_y = min(northings), max(northings)
        
        # Store sequence bounds
        self.sequence_bounds[str(sequence_num)] = (min_x, min_y, max_x, max_y)
        
        # Index sequence in spatial tiles
        tiles = self.get_tiles_in_bounds(min_x, min_y, max_x, max_y)
        for tile_id in tiles:
            if tile_id not in self.spatial_index:
                self.spatial_index[tile_id] = []
            if sequence_num not in self.spatial_index[tile_id]:
                self.spatial_index[tile_id].append(sequence_num)
        
        # Store sequence data
        file_info = {
            'file_path': file_path,
            'last_modified': os.path.getmtime(file_path) if os.path.exists(file_path) else 0,
            'file_hash': self.get_file_hash(file_path),
            'data_points': data_points,
            'bounds': (min_x, min_y, max_x, max_y)
        }
        
        self.cache_data[str(sequence_num)] = file_info
    
    def get_cached_data_for_bounds(self, min_x, min_y, max_x, max_y):
        """Get cached data points within specified bounds."""
        sequences = self.get_sequences_for_bounds(min_x, min_y, max_x, max_y)
        all_points = []
        
        for seq_num in sequences:
            seq_key = str(seq_num)
            if seq_key in self.cache_data:
                points = self.cache_data[seq_key]['data_points']
                # Filter points to exact bounds
                for point in points:
                    x, y = point[0], point[1]
                    if min_x <= x <= max_x and min_y <= y <= max_y:
                        all_points.append(point)
        
        return all_points
    
    def is_sequence_cached_and_valid(self, sequence_num, file_path):
        """Check if sequence is cached and file hasn't changed."""
        seq_key = str(sequence_num)
        if seq_key not in self.cache_data:
            return False
        
        cached_info = self.cache_data[seq_key]
        return not self.is_file_changed(file_path, cached_info)
    
    def remove_sequence_from_cache(self, sequence_num):
        """Remove sequence from cache and spatial index."""
        seq_key = str(sequence_num)
        if seq_key not in self.cache_data:
            return
        
        # Remove from spatial index
        for tile_id in list(self.spatial_index.keys()):
            if sequence_num in self.spatial_index[tile_id]:
                self.spatial_index[tile_id].remove(sequence_num)
                if not self.spatial_index[tile_id]:  # Remove empty tiles
                    del self.spatial_index[tile_id]
        
        # Remove from cache
        del self.cache_data[seq_key]
        if seq_key in self.sequence_bounds:
            del self.sequence_bounds[seq_key]

class X4DApp:
    def __init__(self, master):
        self.master = master
        master.title("x4D QC Tool")
        master.geometry("1200x975") # Increased default window size: width +20%, height +30%
        master.config(bg="#B4C8E1") # Set main window background color

        # Configure ttk style for Notebook tabs
        s = ttk.Style()
        s.theme_use('default') # Use a default theme as a base
        s.configure('TNotebook', background='#B4C8E1') # Background of the notebook itself
        s.configure('TNotebook.Tab', background='#8DA9CC', foreground='black', font=("TkDefaultFont", 10, "bold")) # Tab background and text
        s.map('TNotebook.Tab', background=[('selected', '#8DA9CC')], foreground=[('selected', 'black')]) # Selected tab color

        self.config_path = "" # Will be set by default or loaded config

        # --- Configuration Defaults ---
        try:
            if os.name == 'nt':
                self.default_nav_line_qc_dir = "J:\\7027\\qcfiles\\Nav_Line_QC"
            else:
                # Linux default
                self.default_nav_line_qc_dir = "/aw-navoff1/data/JOB/7027/qcfiles/Nav_Line_QC"
        except Exception:
            # Fallback to Linux path
            self.default_nav_line_qc_dir = "/aw-navoff1/data/JOB/7027/qcfiles/Nav_Line_QC"
        self.default_config_dir = "/usr/local/trinop/dbase/links/qcfiles/Misc/x4D"
        self.default_config_filename = "x4D_config.xcfg"
        self.default_config_filepath = os.path.join(self.default_config_dir, self.default_config_filename)

        # Ensure default config directory exists
        if not os.path.exists(self.default_config_dir):
            try:
                os.makedirs(self.default_config_dir)
                print("Created default config directory: %s" % self.default_config_dir)
            except Exception as e:
                print("Error creating default config directory: %s - %s" % (self.default_config_dir, e))

        # --- Variables to store GUI states ---
        self.nav_line_qc_dir_var = tk.StringVar(master, value=self.default_nav_line_qc_dir)
        self.config_name_var = tk.StringVar(master, value=self.default_config_filepath)
        self.sequences_var = tk.StringVar(master, value="")
        self.sl_search_var = tk.StringVar(master, value="")
        # Dynamic Pass/Fail Criteria variables
        self.num_criteria_var = tk.StringVar(master, value="1") # Number of criteria
        self.criteria_data = [] # List of dictionaries containing criteria widget variables
        # Removed self.excluded_shotpoints_var - now dynamic

        # For dynamic excluded shotpoint entries
        self.excluded_sp_entries_frame = None # Frame to hold dynamic entries
        self.excluded_sp_vars_by_sequence = {} # {seq_num: tk.StringVar}
        self.excluded_sp_entry_widgets = [] # List of (Label, Entry) widget pairs for easy clearing

        # --- Graphing variables ---
        # Stores (sp_no, stat_value_abs, original_stat_value, sequence_num) for plotting
        self.all_plot_data = []
        # Maps canvas item ID to (sp_no, stat_value_abs, original_stat_value, sequence_num)
        self.canvas_point_data_map = {}
        self.x_data_min, self.x_data_max = 0, 1 # Full data range X
        self.y_data_min, self.y_data_max = 0, 1 # Full data range Y
        self.current_x_min, self.current_x_max = 0, 1 # Current view X
        self.current_y_min, self.current_y_max = 0, 1 # Current view Y
        self.start_x_mouse = None
        self.start_y_mouse = None
        self.zoom_rect_id = None
        self.drag_mode = None # 'zoom_window' or 'pan'
        self.tooltip_id = None # Stores ID(s) of the currently displayed tooltip
        self.highlight_ring_id = None # Stores ID of the highlight ring around clicked point

        # Define sequence colors for passing points
        self.sequence_colors = [
            "green",        # 1st sequence
            "blue",         # 2nd sequence
            "purple",       # 3rd sequence
            "mediumpurple", # 4th sequence: "light purple" (more accurately named)
            "lightblue",    # 5th sequence
        ]
        # Store a mapping of sequence number to its index to assign colors consistently
        self.sequence_to_color_index = {}
        self.next_color_index = 0

        # --- Create widgets before loading configuration to ensure results_text exists ---
        self.create_widgets()

        # --- Load the last used config path and then load the settings from that path ---
        self._load_initial_config_path() # Load the path of the last used config file
        self.load_config(initial_load=True) # Load the settings from the determined config file

        # Bind window closing event to save configuration
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Trigger initial update of excluded SP entries if sequences are already set by config load
        self._update_excluded_sp_entries()


    def create_widgets(self):
        """Creates all the GUI elements and lays them out using grid."""
        # Create main notebook for top-level tabs
        self.main_notebook = ttk.Notebook(self.master)
        self.main_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create Sequence QC tab (existing functionality)
        self.sequence_qc_frame = tk.Frame(self.main_notebook, bg="#B4C8E1")
        self.main_notebook.add(self.sequence_qc_frame, text="Sequence QC")
        
        # Create Job Statistics tab (new functionality)
        self.job_stat_frame = tk.Frame(self.main_notebook, bg="#B4C8E1")
        self.main_notebook.add(self.job_stat_frame, text="Job Statistics")
        
        # Create the Sequence QC tab content
        self.create_sequence_qc_widgets()
        
        # Create the Job Statistics tab content
        self.create_job_stat_widgets()

    def create_sequence_qc_widgets(self):
        """Creates the widgets for the Sequence QC tab (original functionality)."""
        # --- Frame for Nav_Line_QC Directory ---
        frame_nav_qc = tk.LabelFrame(self.sequence_qc_frame, text="Nav_Line_QC Folder", padx=10, pady=10, bg="#B4C8E1")
        frame_nav_qc.grid(row=0, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        tk.Label(frame_nav_qc, text="Input Directory:", bg="#B4C8E1").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        tk.Entry(frame_nav_qc, textvariable=self.nav_line_qc_dir_var, width=60).grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        tk.Button(frame_nav_qc, text="Browse", command=self.browse_nav_qc_dir, bg="#8DA9CC", fg="black").grid(row=0, column=2, padx=5, pady=2)

        # --- Frame for Configuration Name ---
        frame_config = tk.LabelFrame(self.sequence_qc_frame, text="Configuration", padx=10, pady=10, bg="#B4C8E1")
        frame_config.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        tk.Label(frame_config, text="Configuration Name (.xcfg):", bg="#B4C8E1").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        tk.Entry(frame_config, textvariable=self.config_name_var, width=60).grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        # Modified Load button to allow Browse
        tk.Button(frame_config, text="Load", command=lambda: self.load_config(browse=True), bg="#8DA9CC", fg="black").grid(row=0, column=2, padx=5, pady=2)
        tk.Button(frame_config, text="Save", command=self.save_config, bg="#8DA9CC", fg="black").grid(row=0, column=3, padx=5, pady=2)

        # --- Frame for Pass/Fail Criteria Specifications ---
        self.frame_criteria_specs = tk.LabelFrame(self.sequence_qc_frame, text="Pass/Fail Criteria Specifications", padx=10, pady=10, bg="#B4C8E1")
        self.frame_criteria_specs.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        # Number of criteria input - layout in a single row
        criteria_input_frame = tk.Frame(self.frame_criteria_specs, bg="#B4C8E1")
        criteria_input_frame.grid(row=0, column=0, columnspan=6, sticky="w", padx=5, pady=2)
        
        tk.Label(criteria_input_frame, text="No. Pass/Fail Criteria:", bg="#B4C8E1").pack(side=tk.LEFT, padx=(0, 2))
        num_criteria_entry = tk.Entry(criteria_input_frame, textvariable=self.num_criteria_var, width=5)
        num_criteria_entry.pack(side=tk.LEFT, padx=(0, 2))
        tk.Button(criteria_input_frame, text="Update", command=self._update_criteria_entries, bg="#8DA9CC", fg="black").pack(side=tk.LEFT, padx=(2, 0))

        # Frame to hold dynamically created criteria entries
        self.criteria_entries_frame = tk.Frame(self.frame_criteria_specs, bg="#B4C8E1")
        self.criteria_entries_frame.grid(row=1, column=0, columnspan=6, sticky="ew", padx=0, pady=5)
        
        # Initialize with one criteria set
        self._update_criteria_entries()

        # --- Frame for Sequence and Excluded Shotpoints ---
        frame_selection = tk.LabelFrame(self.sequence_qc_frame, text="Selection", padx=10, pady=10, bg="#B4C8E1")
        frame_selection.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        tk.Label(frame_selection, text="Sequence(s) (comma-separated):", bg="#B4C8E1").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        sequence_entry = tk.Entry(frame_selection, textvariable=self.sequences_var, width=40)
        sequence_entry.grid(row=0, column=1, padx=5, pady=2, sticky="w")

        tk.Label(frame_selection, text="Search by Preplot Line:", bg="#B4C8E1").grid(row=0, column=2, sticky="e", padx=5, pady=2)
        sl_entry = tk.Entry(frame_selection, textvariable=self.sl_search_var, width=15)
        sl_entry.grid(row=0, column=3, padx=5, pady=2, sticky="w")
        tk.Button(frame_selection, text="Find Seqs", command=self._on_search_sl, bg="#8DA9CC", fg="black").grid(row=0, column=4, padx=5, pady=2, sticky="w")
        # Trace the sequence variable to update dynamic excluded SP entries
        self.sequences_var.trace("w", lambda name, index, mode: self._update_excluded_sp_entries())

        # Frame to hold dynamically created excluded shotpoint entries
        self.excluded_sp_entries_frame = tk.Frame(frame_selection, bg="#B4C8E1")
        self.excluded_sp_entries_frame.grid(row=1, column=0, columnspan=5, sticky="ew", padx=0, pady=0)
        # Configure columns: minimize extra space before entry
        self.excluded_sp_entries_frame.grid_columnconfigure(0, weight=0)
        self.excluded_sp_entries_frame.grid_columnconfigure(1, weight=1)

        # --- Sequence Info Panel (aligned table + Line (SL)) ---
        self.sequence_info_frame = tk.Frame(frame_selection, bg="#B4C8E1")
        self.sequence_info_frame.grid(row=2, column=0, columnspan=5, sticky="ew", padx=0, pady=4)
        self.seq_info_line_label = tk.Label(self.sequence_info_frame, text="Preplot Line: –", bg="#B4C8E1")
        self.seq_info_line_label.grid(row=0, column=0, sticky="w", padx=5)
        # Treeview for perfectly aligned columns
        columns = ("seq", "first_sp", "last_sp", "sol", "eol", "line")
        self.seq_info_table = ttk.Treeview(self.sequence_info_frame, columns=columns, show='headings', height=6)
        self.seq_info_table.grid(row=1, column=0, columnspan=5, sticky="ew", padx=5, pady=2)
        # Headings
        self.seq_info_table.heading("seq", text="Sequence")
        self.seq_info_table.heading("first_sp", text="First SP")
        self.seq_info_table.heading("last_sp", text="Last SP")
        self.seq_info_table.heading("sol", text="SOL date/time")
        self.seq_info_table.heading("eol", text="EOL date/time")
        self.seq_info_table.heading("line", text="Line name")
        # Column widths for alignment
        self.seq_info_table.column("seq", width=80, anchor='center')
        self.seq_info_table.column("first_sp", width=90, anchor='center')
        self.seq_info_table.column("last_sp", width=90, anchor='center')
        self.seq_info_table.column("sol", width=180, anchor='center')
        self.seq_info_table.column("eol", width=180, anchor='center')
        self.seq_info_table.column("line", width=150, anchor='center')
        # Scrollbar
        seq_scroll = tk.Scrollbar(self.sequence_info_frame, command=self.seq_info_table.yview)
        self.seq_info_table.configure(yscrollcommand=seq_scroll.set)
        seq_scroll.grid(row=1, column=5, sticky='ns')
        self.sequence_info_frame.grid_columnconfigure(0, weight=1)


        # --- Results Window (Now a Notebook/Tabbed Interface) ---
        self.results_notebook = ttk.Notebook(self.sequence_qc_frame)
        self.results_notebook.grid(row=4, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        self.sequence_qc_frame.grid_rowconfigure(4, weight=1) # Make notebook expandable
        self.sequence_qc_frame.grid_columnconfigure(0, weight=1)
        self.sequence_qc_frame.grid_columnconfigure(1, weight=1)

        # Tab 1: Text Results
        self.text_results_frame = tk.Frame(self.results_notebook, bg="#8DA9CC") # Set tab frame background
        self.results_notebook.add(self.text_results_frame, text="Statistic Results")

        self.results_text = tk.Text(self.text_results_frame, wrap="word", height=15)
        self.results_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        results_scrollbar = tk.Scrollbar(self.text_results_frame, command=self.results_text.yview)
        results_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.results_text.config(yscrollcommand=results_scrollbar.set)

        # Define tags for text formatting
        self.results_text.tag_config("pass", foreground="green", font=("TkDefaultFont", 10, "bold"))
        self.results_text.tag_config("fail", foreground="red", font=("TkDefaultFont", 10, "bold"))

        # Tab 2: Graph
        self.graph_frame = tk.Frame(self.results_notebook, bg="#8DA9CC") # Set tab frame background
        self.results_notebook.add(self.graph_frame, text="Data Graph")

        # Tab 3: Bad SP (added but hidden until results exist)
        self.reshoots_frame = tk.Frame(self.results_notebook, bg="#8DA9CC")
        self.results_notebook.add(self.reshoots_frame, text="Failed SP's")
        self.reshoots_text = tk.Text(self.reshoots_frame, wrap="word", height=15)
        self.reshoots_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _res_scroll = tk.Scrollbar(self.reshoots_frame, command=self.reshoots_text.yview)
        _res_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.reshoots_text.config(yscrollcommand=_res_scroll.set)
        self.reshoots_text.config(font=("Courier New", 10))
        # Hide Bad SP tab by default; will be shown only when bad SPs are detected
        try:
            self.results_notebook.hide(self.reshoots_frame)
        except Exception:
            self.results_notebook.forget(self.reshoots_frame)
        # Tkinter Canvas for plotting
        self.plot_canvas = tk.Canvas(self.graph_frame, bg="#E0EBF5", highlightbackground="#8DA9CC", highlightthickness=1)
        self.plot_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # (Removed Reshoots proposals tab per request)

        # Bind mouse events for interaction
        self.plot_canvas.bind("<ButtonPress-1>", self._on_canvas_press) # Left click for zoom window
        self.plot_canvas.bind("<B1-Motion>", self._on_canvas_motion)
        self.plot_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.plot_canvas.bind("<ButtonPress-3>", self._on_canvas_press) # Right click for pan
        self.plot_canvas.bind("<B3-Motion>", self._on_canvas_motion)
        self.plot_canvas.bind("<ButtonRelease-3>", self._on_canvas_release)
        self.plot_canvas.bind("<Button-4>", self._on_canvas_scroll) # Scroll up (Linux/macOS)
        self.plot_canvas.bind("<Button-5>", self._on_canvas_scroll) # Scroll down (Linux/macOS)
        self.plot_canvas.bind("<MouseWheel>", self._on_canvas_scroll) # Scroll (Windows)

        # Button container for graph controls
        graph_control_frame = tk.Frame(self.graph_frame, bg="#8DA9CC") # Set control frame background
        graph_control_frame.pack(pady=5)

        tk.Button(graph_control_frame, text="Reset Zoom", command=self._center_full_view, bg="#8DA9CC", fg="black").pack(side=tk.LEFT, padx=5)
        tk.Button(graph_control_frame, text="Center Nominal", command=self._center_nominal_view, bg="#8DA9CC", fg="black").pack(side=tk.LEFT, padx=5)


        # --- Execute Button ---
        tk.Button(self.sequence_qc_frame, text="Execute", command=self.execute_qc, height=2, width=20, bg="#8DA9CC", fg="black").grid(row=5, column=0, columnspan=2, pady=10)

    def create_job_stat_widgets(self):
        """Creates the widgets for the Job Statistics tab (new mapping functionality)."""
        # Configure grid columns for proper resizing
        self.job_stat_frame.grid_columnconfigure(0, weight=1)
        self.job_stat_frame.grid_rowconfigure(2, weight=1)  # Map row gets extra space
        
        # Top controls frame
        controls_frame = tk.Frame(self.job_stat_frame, bg="#B4C8E1")
        controls_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        controls_frame.grid_columnconfigure(1, weight=1)
        controls_frame.grid_columnconfigure(3, weight=1)
        
        # Dropdown for Sequences/Preplot Lines Statistics
        tk.Label(controls_frame, text="Sequences/Preplot Line Statistics:", bg="#B4C8E1").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.stat_type_var = tk.StringVar(self.master, value="Sequences")
        stat_type_menu = tk.OptionMenu(controls_frame, self.stat_type_var, "Sequences", "Preplot Lines")
        stat_type_menu.config(bg="#8DA9CC", fg="black", width=15)
        stat_type_menu.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        # Input box for Sequences/Preplot Lines range
        tk.Label(controls_frame, text="Sequences/Preplot Lines:", bg="#B4C8E1").grid(row=0, column=2, sticky="w", padx=5, pady=2)
        self.range_input_var = tk.StringVar(self.master, value="ALL")
        range_entry = tk.Entry(controls_frame, textvariable=self.range_input_var, width=30)
        range_entry.grid(row=0, column=3, sticky="ew", padx=5, pady=2)
        
        # Update button to refresh map based on selection
        self.update_map_btn = tk.Button(controls_frame, text="Update Map", command=self.update_job_stat_map, bg="#8DA9CC", fg="black")
        self.update_map_btn.grid(row=0, column=4, padx=5, pady=2)
        
        # Map controls frame
        map_controls_frame = tk.Frame(self.job_stat_frame, bg="#B4C8E1")
        map_controls_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        
        self.draw_exclusion_btn = tk.Button(map_controls_frame, text="Draw Excluded Zone", command=self.toggle_exclusion_drawing, bg="#8DA9CC", fg="black")
        self.draw_exclusion_btn.pack(side=tk.LEFT, padx=5)
        
        self.remove_exclusion_btn = tk.Button(map_controls_frame, text="Remove Excluded Zone", command=self.toggle_exclusion_removal, bg="#8DA9CC", fg="black") 
        self.remove_exclusion_btn.pack(side=tk.LEFT, padx=5)
        
        tk.Button(map_controls_frame, text="Clear All Zones", command=self.clear_all_exclusion_zones, bg="#8DA9CC", fg="black").pack(side=tk.LEFT, padx=5)
        
        # Project Data Map frame
        map_frame = tk.LabelFrame(self.job_stat_frame, text="Project Data Map", padx=5, pady=5, bg="#B4C8E1")
        map_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        map_frame.grid_rowconfigure(0, weight=1)
        map_frame.grid_columnconfigure(0, weight=1)
        
        # Map canvas
        self.map_canvas = tk.Canvas(map_frame, bg="#E0EBF5", highlightbackground="#8DA9CC", highlightthickness=1)
        self.map_canvas.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        
        # Map control buttons
        map_button_frame = tk.Frame(map_frame, bg="#B4C8E1")
        map_button_frame.grid(row=1, column=0, pady=5)
        tk.Button(map_button_frame, text="Zoom In", command=self.zoom_in_map, bg="#8DA9CC", fg="black").pack(side=tk.LEFT, padx=2)
        tk.Button(map_button_frame, text="Zoom Out", command=self.zoom_out_map, bg="#8DA9CC", fg="black").pack(side=tk.LEFT, padx=2)
        tk.Button(map_button_frame, text="Reset Zoom", command=self.reset_map_zoom, bg="#8DA9CC", fg="black").pack(side=tk.LEFT, padx=2)
        
        # Bind map canvas events
        self.map_canvas.bind("<ButtonPress-1>", self._on_map_left_press)
        self.map_canvas.bind("<B1-Motion>", self._on_map_left_motion) 
        self.map_canvas.bind("<ButtonRelease-1>", self._on_map_left_release)
        self.map_canvas.bind("<ButtonPress-3>", self._on_map_right_press)
        self.map_canvas.bind("<B3-Motion>", self._on_map_right_motion)
        self.map_canvas.bind("<ButtonRelease-3>", self._on_map_right_release)
        self.map_canvas.bind("<MouseWheel>", self._on_map_scroll)
        
        # Job Statistics frame
        stats_frame = tk.LabelFrame(self.job_stat_frame, text="Job Statistics", padx=10, pady=10, bg="#B4C8E1")
        stats_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        
        self.stats_text = tk.Text(stats_frame, wrap="word", height=8, font=("Courier New", 10))
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        
        # Initialize map variables
        self.map_data_points = []  # List of (easting, northing, is_passing, sp_no) tuples
        self.exclusion_circles = []  # List of (canvas_x, canvas_y, canvas_radius) tuples for display
        self.exclusion_circles_data = []  # List of (easting, northing, radius_meters) tuples for calculations
        self.drawing_exclusion = False
        self.removing_exclusion = False
        self.exclusion_start_point = None
        self.temp_exclusion_circle = None
        self.map_view_bounds = None  # (min_x, min_y, max_x, max_y)
        self.map_zoom_rect = None
        self.map_drag_start = None
        self.map_scale = 1.0  # Scale factor for coordinate conversion
        self.map_center_x = 0
        self.map_center_y = 0
        self.data_center_x = 0
        self.data_center_y = 0
        self.zoom_start_point = None
        self.is_dragging = False
        self.last_pan_time = 0  # For throttling pan updates
        self.last_scroll_time = 0  # For throttling scroll zoom
        
        # Initialize spatial cache
        self.spatial_cache = SpatialDataCache()
        self.current_view_bounds = None  # Track current visible area
        self.loaded_sequences = set()  # Track what sequences are currently loaded

    def update_job_stat_map(self):
        """Update the map display based on current selection (with spatial caching)."""
        # Set button to pressed state during loading
        self.update_map_btn.config(relief=tk.SUNKEN, text="Loading...", state=tk.DISABLED)
        self.update_map_btn.update()
        
        try:
            # Clear all previous canvas items
            self.map_canvas.delete("all")
            self.map_data_points = []
            
            # Get current settings
            range_text = self.range_input_var.get().strip()
            stat_type = self.stat_type_var.get()
            nav_qc_dir = self.nav_line_qc_dir_var.get()
            
            # Validate inputs
            if not os.path.isdir(nav_qc_dir):
                self.stats_text.delete(1.0, tk.END)
                self.stats_text.insert(tk.END, "Error: Nav_Line_QC directory not found: %s\n" % nav_qc_dir)
                return
                
            if not self.criteria_data:
                self.stats_text.delete(1.0, tk.END)
                self.stats_text.insert(tk.END, "Error: No Pass/Fail Criteria defined in Sequence QC tab.\n")
                return
            
            # Parse range input to get sequences or preplot lines
            if stat_type == "Sequences":
                target_sequences = self.parse_range_input(range_text)
                if not target_sequences:
                    self.stats_text.delete(1.0, tk.END)
                    self.stats_text.insert(tk.END, "Error: Invalid sequence range format.\n")
                    return
            else:
                # For Preplot Lines, convert to sequences
                target_sequences = self.convert_preplot_lines_to_sequences(range_text, nav_qc_dir)
                if not target_sequences:
                    self.stats_text.delete(1.0, tk.END)
                    self.stats_text.insert(tk.END, "Error: No sequences found for specified preplot lines.\n")
                    return
            
            # Store target sequences for progressive loading
            self.target_sequences = target_sequences
            self.loaded_sequences = set()
            
            # Clear previous cache info
            self.stats_text.delete(1.0, tk.END)
            self.stats_text.insert(tk.END, "Loading data...\n")
            self.stats_text.update()
            
            # Try cache-based loading first, fall back to traditional loading
            start_time = time.time()
            success, cache_hits, cache_misses = self.try_cached_loading(target_sequences, nav_qc_dir)
            
            if not success or len(self.map_data_points) < 100:
                if cache_hits == 0 and cache_misses > 0:
                    print("Building spatial cache for first time...")
                    self.stats_text.insert(tk.END, "Building spatial cache for first time...\n")
                elif not success:
                    print("Cache loading incomplete, falling back to traditional loading...")
                    self.stats_text.insert(tk.END, "Cache incomplete, using traditional loading...\n")
                else:
                    print("Insufficient data loaded, falling back to traditional loading...")
                    self.stats_text.insert(tk.END, "Loading additional data...\n")
                self.stats_text.update()
                
                # Fall back to traditional loading (load all data)
                self.map_data_points = []
                self.loaded_sequences = set()
                success = self.traditional_loading(target_sequences, nav_qc_dir)
            
            load_time = time.time() - start_time
            
            # Plot data points on map
            if self.map_data_points and success:
                print("Plotting %d data points..." % len(self.map_data_points))
                self.plot_map_data()
                
                # Redraw any loaded exclusion zones
                if hasattr(self, 'exclusion_circles_data') and self.exclusion_circles_data:
                    self.redraw_exclusion_zones()
                
                # Update statistics
                self.update_map_statistics()
                
                # Add performance info
                self.stats_text.insert(tk.END, "\n=== LOADING PERFORMANCE ===\n")
                self.stats_text.insert(tk.END, "Load time: %.2f seconds\n" % load_time)
                self.stats_text.insert(tk.END, "Data points loaded: %d\n" % len(self.map_data_points))
                self.stats_text.insert(tk.END, "Sequences processed: %d\n" % len(target_sequences))
                
                if stat_type == "Preplot Lines":
                    self.stats_text.insert(tk.END, "\n=== PREPLOT LINE PROCESSING ===\n")
                    self.stats_text.insert(tk.END, "Preplot lines specified: %s\n" % range_text)
                    if range_text.upper() == "ALL":
                        self.stats_text.insert(tk.END, "Processed ALL preplot lines in the project\n")
                    self.stats_text.insert(tk.END, "Found %d sequences under these preplot lines\n" % len(target_sequences))
                else:
                    # For Sequences mode
                    if range_text.upper() == "ALL":
                        self.stats_text.insert(tk.END, "\n=== SEQUENCE PROCESSING ===\n")
                        self.stats_text.insert(tk.END, "Processing ALL sequences in the project\n")
                        self.stats_text.insert(tk.END, "Found %d total sequences\n" % len(target_sequences))
            else:
                self.stats_text.insert(tk.END, "\nError: No data could be loaded. Check console for details.\n")
                print("ERROR: Failed to load any data points")
                
        except Exception as e:
            print("Error in update_job_stat_map: %s" % str(e))
            self.stats_text.insert(tk.END, "\nError during loading: %s\n" % str(e))
        
        finally:
            # Reset button state
            self.update_map_btn.config(relief=tk.RAISED, text="Update Map", state=tk.NORMAL)

    def load_sequences_with_cache(self, target_sequences, nav_qc_dir):
        """Load sequence data using spatial cache with file change detection."""
        cache_hits = 0
        cache_misses = 0
        
        # Get all sequence files first
        found_files = self.get_sequence_files(nav_qc_dir, target_sequences)
        
        for sequence_num in target_sequences:
            if sequence_num not in found_files:
                continue
            
            file_path = found_files[sequence_num][0]  # Get first file for sequence
            
            # Check if sequence is cached and file hasn't changed
            if self.spatial_cache.is_sequence_cached_and_valid(sequence_num, file_path):
                # Load from cache
                seq_key = str(sequence_num)
                cached_points = self.spatial_cache.cache_data[seq_key]['data_points']
                self.map_data_points.extend(cached_points)
                cache_hits += 1
            else:
                # Parse from file and update cache
                sequence_data = self.load_single_sequence_data(sequence_num, found_files[sequence_num])
                if sequence_data:
                    self.map_data_points.extend(sequence_data)
                    # Add to cache
                    self.spatial_cache.add_sequence_data(sequence_num, file_path, sequence_data)
                cache_misses += 1
        
        # Save cache after loading
        if cache_misses > 0:
            self.spatial_cache.save_cache()
        
        return cache_hits, cache_misses
    
    def load_single_sequence_data(self, sequence_num, file_paths):
        """Load data for a single sequence from its files."""
        sequence_data = []
        
        # Get criteria for determining pass/fail
        if not self.criteria_data:
            default_criteria = [{
                'stat_for_criteria': 'Radial',
                'spec_value': 1.0
            }]
            criteria_list = default_criteria
        else:
            criteria_list = []
            for criteria_vars in self.criteria_data:
                stat_name = criteria_vars['stat_for_criteria'].get() if hasattr(criteria_vars['stat_for_criteria'], 'get') else criteria_vars['stat_for_criteria']
                spec_value = float(criteria_vars['spec_value'].get()) if hasattr(criteria_vars['spec_value'], 'get') else float(criteria_vars['spec_value'])
                criteria_list.append({
                    'stat_for_criteria': stat_name,
                    'spec_value': spec_value
                })
        
        # Process each file for this sequence
        for file_path in file_paths:
            try:
                file_data = self.parse_file_data(file_path)
                
                for sp_no, sp_data in file_data.items():
                    # Extract coordinates
                    if "Source North" in sp_data and "Source East" in sp_data:
                        easting = sp_data["Source East"]
                        northing = sp_data["Source North"]
                    else:
                        # Fallback coordinates
                        easting = 400000 + (sp_no % 1000) * 25
                        northing = 6000000 + (sp_no // 1000) * 25
                    
                    # Calculate pass/fail for each criteria
                    criteria_results = []
                    overall_passing = True
                    for criteria in criteria_list:
                        stat_name = criteria['stat_for_criteria']
                        spec_value = criteria['spec_value']
                        stat_value = sp_data.get(stat_name, 0)
                        is_passing_criteria = abs(stat_value) <= spec_value
                        criteria_results.append(is_passing_criteria)
                        if not is_passing_criteria:
                            overall_passing = False
                    
                    # Store point data (easting, northing, overall_passing, sp_no, seq_num, criteria_results)
                    point_data = (easting, northing, overall_passing, sp_no, sequence_num, criteria_results)
                    sequence_data.append(point_data)
                    
            except Exception as e:
                print("Error processing file %s: %s" % (file_path, str(e)))
                continue
        
        return sequence_data
    
    def ensure_sequences_cached(self, target_sequences, nav_qc_dir):
        """Ensure all sequences are cached but don't load them into memory yet."""
        cache_hits = 0
        cache_misses = 0
        
        # Get all sequence files first
        found_files = self.get_sequence_files(nav_qc_dir, target_sequences)
        
        for sequence_num in target_sequences:
            if sequence_num not in found_files:
                continue
            
            file_path = found_files[sequence_num][0]  # Get first file for sequence
            
            # Check if sequence is cached and file hasn't changed
            if self.spatial_cache.is_sequence_cached_and_valid(sequence_num, file_path):
                cache_hits += 1
            else:
                # Parse from file and cache it
                sequence_data = self.load_single_sequence_data(sequence_num, found_files[sequence_num])
                if sequence_data:
                    # Add to cache
                    self.spatial_cache.add_sequence_data(sequence_num, file_path, sequence_data)
                cache_misses += 1
        
        # Save cache after loading
        if cache_misses > 0:
            self.spatial_cache.save_cache()
        
        return cache_hits, cache_misses
    
    def load_initial_view_data(self):
        """Load data for initial map view (robust approach with multiple fallbacks)."""
        if not hasattr(self, 'target_sequences') or not self.target_sequences:
            print("No target sequences available")
            return
        
        print("Loading initial view data for %d sequences..." % len(self.target_sequences))
        
        # Try to determine the best initial view from cached sequence bounds
        all_bounds = []
        for seq_num in self.target_sequences:
            seq_key = str(seq_num)
            if seq_key in self.spatial_cache.sequence_bounds:
                bounds = self.spatial_cache.sequence_bounds[seq_key]
                all_bounds.append(bounds)
        
        if all_bounds and len(all_bounds) > 0:
            print("Found bounds for %d sequences, calculating initial view..." % len(all_bounds))
            
            # Calculate overall bounds of all data
            min_x = min(bounds[0] for bounds in all_bounds)
            min_y = min(bounds[1] for bounds in all_bounds)
            max_x = max(bounds[2] for bounds in all_bounds)
            max_y = max(bounds[3] for bounds in all_bounds)
            
            # Calculate center and create initial view (bigger area to ensure data)
            center_x = (min_x + max_x) / 2.0
            center_y = (min_y + max_y) / 2.0
            
            # Create initial view that's about 50% of total data area (increased from 30%)
            data_width = max_x - min_x
            data_height = max_y - min_y
            view_width = data_width * 0.6  # Show 60% of data area initially
            view_height = data_height * 0.6
            
            initial_bounds = (
                center_x - view_width / 2,
                center_y - view_height / 2,
                center_x + view_width / 2,
                center_y + view_height / 2
            )
            
            print("Loading initial view: %.0f x %.0f area centered at (%.0f, %.0f)" % (view_width, view_height, center_x, center_y))
            
            # Load data for initial view
            self.load_data_for_bounds(initial_bounds)
            self.current_view_bounds = initial_bounds
            
            # Set map center for proper initial display
            self.data_center_x = center_x
            self.data_center_y = center_y
            
            print("Loaded %d points from spatial bounds approach" % len(self.map_data_points))
            
        # If spatial approach failed or loaded too few points, try direct loading
        if len(self.map_data_points) < 100:
            print("Spatial loading insufficient, trying direct sequence loading...")
            
            # Load first several sequences directly (more than before)
            limited_sequences = self.target_sequences[:min(10, len(self.target_sequences))]
            print("Loading first %d sequences directly for initial view" % len(limited_sequences))
            
            for seq_num in limited_sequences:
                seq_key = str(seq_num)
                if seq_key in self.spatial_cache.cache_data:
                    cached_points = self.spatial_cache.cache_data[seq_key]['data_points']
                    # Load more points per sequence
                    self.map_data_points.extend(cached_points[:5000])  # Increased from 1000
                    self.loaded_sequences.add(seq_num)
                    print("Loaded %d points from sequence %d" % (min(5000, len(cached_points)), seq_num))
            
            print("Direct loading completed: %d total points" % len(self.map_data_points))
            
        # Final fallback: load ALL data from cache if still insufficient
        if len(self.map_data_points) < 100:
            print("Still insufficient data, loading ALL cached sequences...")
            
            for seq_num in self.target_sequences:
                seq_key = str(seq_num)
                if seq_key in self.spatial_cache.cache_data:
                    cached_points = self.spatial_cache.cache_data[seq_key]['data_points']
                    self.map_data_points.extend(cached_points)
                    self.loaded_sequences.add(seq_num)
                    
                    # Stop if we have enough data
                    if len(self.map_data_points) > 10000:
                        break
            
            print("Final fallback completed: %d total points" % len(self.map_data_points))
    
    def try_cached_loading(self, target_sequences, nav_qc_dir):
        """Try to load data using the cached progressive loading approach."""
        try:
            # Ensure all sequences are cached
            cache_hits, cache_misses = self.ensure_sequences_cached(target_sequences, nav_qc_dir)
            print("Cache results: %d hits, %d misses" % (cache_hits, cache_misses))
            
            # Load initial view data
            self.load_initial_view_data()
            
            # Check if we got reasonable data
            if len(self.map_data_points) > 0:
                print("Cached loading successful: %d points loaded" % len(self.map_data_points))
                return True, cache_hits, cache_misses
            else:
                print("Cached loading failed: no points loaded")
                return False, cache_hits, cache_misses
                
        except Exception as e:
            print("Error in cached loading: %s" % str(e))
            return False, 0, 0
    
    def traditional_loading(self, target_sequences, nav_qc_dir):
        """Traditional loading method (load all data) as fallback."""
        try:
            print("Using traditional loading for %d sequences..." % len(target_sequences))
            
            # Get QC files for the sequences
            found_files = self.get_sequence_files(nav_qc_dir, target_sequences)
            if not found_files:
                print("No QC files found for sequences")
                return False
            
            # Load and process QC data (original method)
            self.load_qc_data_for_mapping(found_files)
            
            print("Traditional loading completed: %d points loaded" % len(self.map_data_points))
            return len(self.map_data_points) > 0
            
        except Exception as e:
            print("Error in traditional loading: %s" % str(e))
            return False

    def parse_range_input(self, range_text):
        """Parse range input like 'ALL', '1001-1010, 1020, 1021-2000' into list of integers."""
        if not range_text:
            return []
            
        range_text = range_text.upper().strip()
        
        if range_text == "ALL":
            # Return all available sequences from the nav_qc_dir
            return self.get_all_available_sequences()
        
        # Parse comma-separated ranges and individual numbers
        result = set()
        try:
            for part in range_text.split(','):
                part = part.strip()
                if '-' in part:
                    # Range like "1001-1010"
                    start, end = part.split('-', 1)
                    start = int(start.strip())
                    end = int(end.strip())
                    if start <= end:
                        result.update(range(start, end + 1))
                else:
                    # Individual number
                    result.add(int(part))
            return sorted(list(result))
        except ValueError:
            return []
    
    def convert_preplot_lines_to_sequences(self, range_text, nav_qc_dir):
        """Convert preplot line range input into sequences by finding all sequences under those preplot lines."""
        if not range_text:
            return []
            
        range_text = range_text.upper().strip()
        
        if range_text == "ALL":
            # Find ALL preplot lines and get all sequences under them
            return self.get_all_sequences_from_all_preplot_lines(nav_qc_dir)
        
        # Parse preplot line ranges and individual preplot lines
        preplot_lines = set()
        try:
            for part in range_text.split(','):
                part = part.strip()
                if '-' in part:
                    # Range like "51900-51980"
                    start, end = part.split('-', 1)
                    start = int(start.strip())
                    end = int(end.strip())
                    if start <= end:
                        preplot_lines.update(range(start, end + 1))
                else:
                    # Individual preplot line
                    preplot_lines.add(int(part))
        except ValueError:
            return []
        
        # Convert preplot lines to sequences
        all_sequences = set()
        for preplot_line in sorted(preplot_lines):
            # Use the same function that the Sequence QC tab uses
            seq_info_list = self._collect_sequences_for_sl(str(preplot_line), nav_qc_dir)
            for seq_info in seq_info_list:
                all_sequences.add(seq_info['seq'])
        
        result = sorted(list(all_sequences))
        print("Converted preplot lines %s to %d sequences: %s" % (range_text, len(result), str(result[:10]) + "..." if len(result) > 10 else str(result)))
        return result
    
    def get_all_sequences_from_all_preplot_lines(self, nav_qc_dir):
        """Find all preplot lines that have sequences and return all sequences under them."""
        if not os.path.isdir(nav_qc_dir):
            return []
        
        all_sequences = set()
        discovered_preplot_lines = set()
        
        # First pass: discover all preplot lines by scanning sequence directories
        for seq_folder in os.listdir(nav_qc_dir):
            try:
                seq_num = int(seq_folder)
            except ValueError:
                continue
                
            folder_path = os.path.join(nav_qc_dir, seq_folder)
            if not os.path.isdir(folder_path):
                continue
            
            # Look for ShotInfo files and extract preplot line information
            try:
                pattern = re.compile(r"^ShotInfo[-_].*?G25[A-Z]?(\d+)", re.IGNORECASE)
                for filename in os.listdir(folder_path):
                    if filename.lower().startswith('shotinfo') and filename.lower().endswith('.csv'):
                        match = pattern.match(filename)
                        if match:
                            line_digits = match.group(1)
                            # Take first 5 digits as preplot line identifier
                            if len(line_digits) >= 5:
                                preplot_line = line_digits[:5]
                                discovered_preplot_lines.add(preplot_line)
                                break
            except Exception:
                continue
        
        print("Discovered %d unique preplot lines in nav_qc_dir" % len(discovered_preplot_lines))
        
        # Second pass: for each discovered preplot line, get all sequences
        for preplot_line in sorted(discovered_preplot_lines):
            seq_info_list = self._collect_sequences_for_sl(preplot_line, nav_qc_dir)
            for seq_info in seq_info_list:
                all_sequences.add(seq_info['seq'])
        
        result = sorted(list(all_sequences))
        print("Found %d total sequences across all preplot lines: %s" % (len(result), str(result[:10]) + "..." if len(result) > 10 else str(result)))
        return result
    
    def get_all_available_sequences(self):
        """Get all available sequence numbers from the nav_qc_dir."""
        nav_qc_dir = self.nav_line_qc_dir_var.get()
        if not os.path.isdir(nav_qc_dir):
            return []
        
        sequences = set()
        try:
            for folder_name in os.listdir(nav_qc_dir):
                folder_path = os.path.join(nav_qc_dir, folder_name)
                if os.path.isdir(folder_path):
                    try:
                        # Sequence directories are named with numeric sequence numbers
                        seq_num = int(folder_name)
                        sequences.add(seq_num)
                    except ValueError:
                        continue  # Skip non-numeric directory names
        except Exception:
            pass
        
        result = sorted(list(sequences))
        print("Found %d available sequences in nav_qc_dir: %s" % (len(result), str(result[:10]) + "..." if len(result) > 10 else str(result)))
        return result
    
    def load_qc_data_for_mapping(self, found_files_by_sequence):
        """Load QC data for mapping, extracting positions and pass/fail status."""
        self.map_data_points = []
        
        # Get all criteria for determining pass/fail
        if not self.criteria_data:
            default_criteria = [{
                'stat_for_criteria': 'Radial',
                'spec_value': 1.0
            }]
            criteria_list = default_criteria
        else:
            criteria_list = []
            for criteria_vars in self.criteria_data:
                stat_name = criteria_vars['stat_for_criteria'].get() if hasattr(criteria_vars['stat_for_criteria'], 'get') else criteria_vars['stat_for_criteria']
                spec_value = float(criteria_vars['spec_value'].get()) if hasattr(criteria_vars['spec_value'], 'get') else float(criteria_vars['spec_value'])
                criteria_list.append({
                    'stat_for_criteria': stat_name,
                    'spec_value': spec_value
                })
        
        for seq_num in sorted(found_files_by_sequence.keys()):
            for filepath in found_files_by_sequence[seq_num]:
                # Parse file with first criteria's stat for compatibility
                primary_stat = criteria_list[0]['stat_for_criteria']
                file_data = self.parse_file_data(filepath, primary_stat)
                
                for sp_data in file_data:
                    sp_no = sp_data["Pos no"]
                    
                    # Use actual coordinates from QC file if available
                    if "Source North" in sp_data and "Source East" in sp_data:
                        easting = sp_data["Source East"]
                        northing = sp_data["Source North"]
                    else:
                        # Fallback to placeholder coordinates if source pos not available
                        easting = 400000 + (sp_no % 1000) * 25  # Placeholder easting
                        northing = 6000000 + (sp_no // 1000) * 25  # Placeholder northing
                    
                    # Check pass/fail status for each criteria
                    criteria_results = []
                    overall_passing = True
                    
                    for criteria in criteria_list:
                        stat_name = criteria['stat_for_criteria']
                        spec_value = criteria['spec_value']
                        stat_value = sp_data.get(stat_name, 0)
                        is_passing_criteria = abs(stat_value) <= spec_value
                        criteria_results.append(is_passing_criteria)
                        if not is_passing_criteria:
                            overall_passing = False
                    
                    # Store data point with all criteria results
                    point_data = (easting, northing, overall_passing, sp_no, seq_num, criteria_results)
                    self.map_data_points.append(point_data)
    
    def plot_map_data(self):
        """Plot data points on the map canvas."""
        if not self.map_data_points:
            print("No map data points to plot")
            return
        
        print("Plotting %d data points on map..." % len(self.map_data_points))
        
        # Calculate data bounds
        eastings = [point[0] for point in self.map_data_points]
        northings = [point[1] for point in self.map_data_points]
        
        min_east, max_east = min(eastings), max(eastings)
        min_north, max_north = min(northings), max(northings)
        
        # Add padding
        padding = max((max_east - min_east) * 0.1, (max_north - min_north) * 0.1, 100)
        self.map_view_bounds = (min_east - padding, min_north - padding, 
                               max_east + padding, max_north + padding)
        
        # Get canvas dimensions
        canvas_width = self.map_canvas.winfo_width()
        canvas_height = self.map_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            # Canvas not ready yet, try again later
            self.map_canvas.after(100, self.plot_map_data)
            return
        
        # Calculate scale factors
        data_width = self.map_view_bounds[2] - self.map_view_bounds[0]
        data_height = self.map_view_bounds[3] - self.map_view_bounds[1]
        
        scale_x = canvas_width / data_width
        scale_y = canvas_height / data_height
        
        # Use same scale for both axes to maintain aspect ratio
        scale = min(scale_x, scale_y) * 0.9  # 90% to leave some margin
        
        # Center the plot
        center_x = canvas_width / 2
        center_y = canvas_height / 2
        data_center_x = (self.map_view_bounds[0] + self.map_view_bounds[2]) / 2
        data_center_y = (self.map_view_bounds[1] + self.map_view_bounds[3]) / 2
        
        # Store for coordinate conversion
        self.map_scale = scale
        self.map_center_x = center_x
        self.map_center_y = center_y
        self.data_center_x = data_center_x
        self.data_center_y = data_center_y
        
        # Plot ALL data points for complete visibility
        visible_points = 0
        total_points = len(self.map_data_points)
        
        # Use smaller points for large datasets to improve performance
        if total_points > 100000:
            point_size = 1  # Very small for huge datasets
        elif total_points > 50000:
            point_size = 1  # Small for large datasets
        else:
            point_size = 2  # Normal size for smaller datasets
        
        # Process all points (Show All Points mode is always enabled)
        for i, point_data in enumerate(self.map_data_points):
                
            if len(point_data) == 6:
                easting, northing, overall_passing, sp_no, seq_num, criteria_results = point_data
            else:
                # Fallback for old format
                easting, northing, overall_passing, sp_no, seq_num = point_data[:5]
                criteria_results = [overall_passing]
                
            # Convert data coordinates to canvas coordinates
            canvas_x = center_x + (easting - data_center_x) * scale
            canvas_y = center_y - (northing - data_center_y) * scale  # Flip Y axis
            
            # Only draw if within canvas bounds (with margin for smooth scrolling)
            if -50 <= canvas_x <= canvas_width + 50 and -50 <= canvas_y <= canvas_height + 50:
                # Choose color
                if overall_passing:
                    color = "green"
                else:
                    color = "red"
                
                # Create point with adaptive size
                point_id = self.map_canvas.create_oval(
                    canvas_x - point_size, canvas_y - point_size, 
                    canvas_x + point_size, canvas_y + point_size,
                    fill=color, outline="", width=0,
                    tags="data_point"
                )
                
                # Bind events to every 50th point for performance with large datasets
                if visible_points % 50 == 0:
                    self.map_canvas.tag_bind(point_id, "<Button-1>", 
                        lambda e, sp=sp_no, seq=seq_num: self.on_map_point_click(e, sp, seq))
                
                visible_points += 1
        
        # Debug info for user
        print("Rendered ALL %d points from %d total data points" % (visible_points, len(self.map_data_points)))
    
    def get_current_view_bounds(self):
        """Calculate current visible map bounds based on canvas view and zoom."""
        if not hasattr(self, 'map_canvas') or not hasattr(self, 'map_scale') or self.map_scale <= 0:
            return None
        
        canvas_width = self.map_canvas.winfo_width()
        canvas_height = self.map_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            return None
        
        # Convert canvas bounds to data coordinates
        # Top-left corner
        min_x = self.data_center_x - (self.map_center_x / self.map_scale)
        max_y = self.data_center_y + (self.map_center_y / self.map_scale)
        
        # Bottom-right corner  
        max_x = self.data_center_x + ((canvas_width - self.map_center_x) / self.map_scale)
        min_y = self.data_center_y - ((canvas_height - self.map_center_y) / self.map_scale)
        
        return (min_x, min_y, max_x, max_y)
    
    def check_and_load_visible_data(self):
        """Check if current view needs additional data and load it progressively."""
        if not hasattr(self, 'target_sequences'):
            return
        
        current_bounds = self.get_current_view_bounds()
        if not current_bounds:
            return
        
        # Check if view has changed significantly
        if self.current_view_bounds:
            old_min_x, old_min_y, old_max_x, old_max_y = self.current_view_bounds
            new_min_x, new_min_y, new_max_x, new_max_y = current_bounds
            
            # Calculate overlap percentage
            overlap_x = max(0, min(old_max_x, new_max_x) - max(old_min_x, new_min_x))
            overlap_y = max(0, min(old_max_y, new_max_y) - max(old_min_y, new_min_y))
            old_area = (old_max_x - old_min_x) * (old_max_y - old_min_y)
            overlap_area = overlap_x * overlap_y
            
            # If more than 70% overlap, no need to reload
            if old_area > 0 and (overlap_area / old_area) > 0.7:
                return
        
        # Load data for current visible area
        self.load_data_for_bounds(current_bounds)
        self.current_view_bounds = current_bounds
    
    def load_data_for_bounds(self, bounds):
        """Load data points for specific geographic bounds."""
        min_x, min_y, max_x, max_y = bounds
        
        # Get sequences that intersect with current bounds
        relevant_sequences = self.spatial_cache.get_sequences_for_bounds(min_x, min_y, max_x, max_y)
        
        # Filter to only target sequences
        if hasattr(self, 'target_sequences'):
            relevant_sequences = [seq for seq in relevant_sequences if seq in self.target_sequences]
        
        # Load any sequences not already loaded
        new_sequences = [seq for seq in relevant_sequences if seq not in self.loaded_sequences]
        
        if new_sequences:
            print("Loading %d new sequences for current view..." % len(new_sequences))
            
            # Get cached data for these sequences
            for seq_num in new_sequences:
                seq_key = str(seq_num)
                if seq_key in self.spatial_cache.cache_data:
                    cached_points = self.spatial_cache.cache_data[seq_key]['data_points']
                    # Filter points to current bounds
                    for point in cached_points:
                        x, y = point[0], point[1]
                        if min_x <= x <= max_x and min_y <= y <= max_y:
                            if point not in self.map_data_points:  # Avoid duplicates
                                self.map_data_points.append(point)
                    
                    self.loaded_sequences.add(seq_num)
            
            print("Loaded data for %d sequences in visible area" % len(new_sequences))
    
    def refresh_map_display(self):
        """Refresh the map display when settings change."""
        if hasattr(self, 'map_data_points') and self.map_data_points:
            if hasattr(self, 'map_scale') and self.map_scale > 0:
                # We're in zoom mode, use the zoom redraw
                self.redraw_map_at_current_zoom()
            else:
                # Reset to full view
                self.plot_map_data()
                if hasattr(self, 'exclusion_circles_data') and self.exclusion_circles_data:
                    self.redraw_exclusion_zones()
                self.update_map_statistics()
    
    def on_map_point_click(self, event, sp_no, seq_num):
        """Handle click on a data point."""
        print("Clicked SP %d from Sequence %d" % (sp_no, seq_num))
    
    def update_map_statistics(self):
        """Update the statistics display based on current data points."""
        if not self.map_data_points:
            self.stats_text.delete(1.0, tk.END)
            self.stats_text.insert(tk.END, "No data points to analyze.\n")
            return
        
        # Filter out points in exclusion zones
        filtered_points = []
        for point_data in self.map_data_points:
            if len(point_data) == 6:
                easting, northing, overall_passing, sp_no, seq_num, criteria_results = point_data
            else:
                # Fallback for old format
                easting, northing, overall_passing, sp_no, seq_num = point_data[:5]
                criteria_results = [overall_passing]
            
            # Check if point is in any exclusion circle
            excluded = False
            if hasattr(self, 'exclusion_circles_data'):
                for circle_data in self.exclusion_circles_data:
                    circle_easting, circle_northing, radius_meters = circle_data
                    distance = ((easting - circle_easting)**2 + (northing - circle_northing)**2)**0.5
                    if distance <= radius_meters:
                        excluded = True
                        break
            
            if not excluded:
                filtered_points.append((easting, northing, overall_passing, sp_no, seq_num, criteria_results))
        
        # Calculate overall statistics
        total_points = len(filtered_points)
        overall_passing_points = sum(1 for point in filtered_points if point[2])
        overall_failing_points = total_points - overall_passing_points
        
        overall_pass_percentage = (overall_passing_points / total_points * 100) if total_points > 0 else 0
        overall_fail_percentage = (overall_failing_points / total_points * 100) if total_points > 0 else 0
        
        # Calculate statistics for each criteria
        criteria_stats = []
        if total_points > 0 and filtered_points:
            num_criteria = len(filtered_points[0][5]) if len(filtered_points[0]) > 5 else 1
            
            for i in range(num_criteria):
                passing_this_criteria = 0
                for point in filtered_points:
                    if len(point) > 5 and i < len(point[5]):
                        if point[5][i]:  # criteria_results[i]
                            passing_this_criteria += 1
                    else:
                        # Fallback for old format
                        if point[2]:  # overall_passing
                            passing_this_criteria += 1
                
                failing_this_criteria = total_points - passing_this_criteria
                pass_pct = (float(passing_this_criteria) / float(total_points) * 100)
                fail_pct = (float(failing_this_criteria) / float(total_points) * 100)
                
                criteria_stats.append({
                    'index': i + 1,
                    'passing': passing_this_criteria,
                    'failing': failing_this_criteria,
                    'pass_percentage': pass_pct,
                    'fail_percentage': fail_pct
                })
        
        # Update statistics display
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(tk.END, "=== PROJECT DATA MAP STATISTICS ===\n\n")
        self.stats_text.insert(tk.END, "Total SP's: %d\n" % total_points)
        self.stats_text.insert(tk.END, "Excluded SP's: %d\n" % (len(self.map_data_points) - total_points))
        self.stats_text.insert(tk.END, "\n")
        
        # Individual criteria statistics with descriptions
        if criteria_stats and hasattr(self, 'criteria_data') and self.criteria_data:
            self.stats_text.insert(tk.END, "INDIVIDUAL CRITERIA STATISTICS:\n\n")
            for i, stat in enumerate(criteria_stats):
                criteria_index = stat['index'] - 1  # Convert to 0-based index
                if criteria_index < len(self.criteria_data):
                    criteria_vars = self.criteria_data[criteria_index]
                    
                    # Get criteria information
                    pass_fail_type = criteria_vars['pass_fail_criteria'].get() if hasattr(criteria_vars['pass_fail_criteria'], 'get') else criteria_vars['pass_fail_criteria']
                    stat_name = criteria_vars['stat_for_criteria'].get() if hasattr(criteria_vars['stat_for_criteria'], 'get') else criteria_vars['stat_for_criteria']
                    spec_value = criteria_vars['spec_value'].get() if hasattr(criteria_vars['spec_value'], 'get') else str(criteria_vars['spec_value'])
                    criteria_value = criteria_vars['criteria_value'].get() if hasattr(criteria_vars['criteria_value'], 'get') else str(criteria_vars['criteria_value'])
                    
                    # Create description based on criteria type
                    if pass_fail_type == "Max % of Failure for Whole line":
                        description = "Max %% of Failure for Whole line. (%s spec %sm, Max %s%%)" % (stat_name, spec_value, criteria_value)
                    elif pass_fail_type == "Max Consecutive Failures":
                        description = "Max Consecutive Failures. (%s spec %sm, %s consecutive SPs)" % (stat_name, spec_value, criteria_value)
                    elif pass_fail_type == "Max % of Failure for Moving Window":
                        description = "Max %% of Failure for Moving Window. (%s spec %sm, Max %s%% in window)" % (stat_name, spec_value, criteria_value)
                    else:
                        description = "%s criteria. (%s spec %sm)" % (pass_fail_type, stat_name, spec_value)
                    
                    self.stats_text.insert(tk.END, "CRITERIA %d: %s\n" % (stat['index'], description))
                    self.stats_text.insert(tk.END, "  Passing: %d (%.1f%%)\n" % (stat['passing'], stat['pass_percentage']))
                    self.stats_text.insert(tk.END, "  Failed: %d (%.1f%%)\n\n" % (stat['failing'], stat['fail_percentage']))
                else:
                    # Fallback for missing criteria data
                    self.stats_text.insert(tk.END, "CRITERIA %d:\n" % stat['index'])
                    self.stats_text.insert(tk.END, "  Passing: %d (%.1f%%)\n" % (stat['passing'], stat['pass_percentage']))
                    self.stats_text.insert(tk.END, "  Failed: %d (%.1f%%)\n\n" % (stat['failing'], stat['fail_percentage']))
        elif criteria_stats:
            # Fallback when criteria_data is not available
            self.stats_text.insert(tk.END, "INDIVIDUAL CRITERIA STATISTICS:\n\n")
            for stat in criteria_stats:
                self.stats_text.insert(tk.END, "CRITERIA %d:\n" % stat['index'])
                self.stats_text.insert(tk.END, "  Passing: %d (%.1f%%)\n" % (stat['passing'], stat['pass_percentage']))
                self.stats_text.insert(tk.END, "  Failed: %d (%.1f%%)\n\n" % (stat['failing'], stat['fail_percentage']))
        
        # Add coordinate info if available
        if self.map_data_points:
            sample_point = self.map_data_points[0]
            self.stats_text.insert(tk.END, "\n")
            if len(str(int(sample_point[0]))) > 5:  # Real coordinates are typically large numbers
                self.stats_text.insert(tk.END, "Using real coordinates from QC files\n")
            else:
                self.stats_text.insert(tk.END, "Using placeholder coordinates (source pos not found)\n")
        
    def toggle_exclusion_drawing(self):
        """Toggle drawing mode for exclusion circles."""
        self.drawing_exclusion = not self.drawing_exclusion
        if self.removing_exclusion:
            self.removing_exclusion = False
            self.remove_exclusion_btn.config(relief=tk.RAISED, bg="#8DA9CC")
        
        if self.drawing_exclusion:
            self.draw_exclusion_btn.config(relief=tk.SUNKEN, bg="#7A95B8")
            self.map_canvas.config(cursor="crosshair")
        else:
            self.draw_exclusion_btn.config(relief=tk.RAISED, bg="#8DA9CC")
            self.map_canvas.config(cursor="")
            
    def toggle_exclusion_removal(self):
        """Toggle removal mode for exclusion circles."""
        self.removing_exclusion = not self.removing_exclusion
        print("Exclusion removal mode: %s" % ("ON" if self.removing_exclusion else "OFF"))
        
        if self.drawing_exclusion:
            self.drawing_exclusion = False
            self.draw_exclusion_btn.config(relief=tk.RAISED, bg="#8DA9CC")
        
        if self.removing_exclusion:
            self.remove_exclusion_btn.config(relief=tk.SUNKEN, bg="#7A95B8")
            self.map_canvas.config(cursor="target")
            print("Cursor changed to target for removal mode")
            # Show current exclusion zones for debugging
            if hasattr(self, 'exclusion_circles_data'):
                print("Available exclusion zones to remove:")
                for i, (easting, northing, radius) in enumerate(self.exclusion_circles_data):
                    print("  Zone %d: (%.1f, %.1f) radius %.1f" % (i, easting, northing, radius))
        else:
            self.remove_exclusion_btn.config(relief=tk.RAISED, bg="#8DA9CC")
            self.map_canvas.config(cursor="")
            print("Removal mode deactivated")
        
    def clear_all_exclusion_zones(self):
        """Remove all exclusion zones."""
        zones_count = len(self.exclusion_circles_data)
        
        self.map_canvas.delete("exclusion_circle")
        self.map_canvas.delete("temp_exclusion")
        self.exclusion_circles = []
        self.exclusion_circles_data = []
        self.drawing_exclusion = False
        self.removing_exclusion = False
        self.draw_exclusion_btn.config(relief=tk.RAISED, bg="#8DA9CC")
        self.remove_exclusion_btn.config(relief=tk.RAISED, bg="#8DA9CC")
        self.map_canvas.config(cursor="")
        
        # Update statistics after clearing all zones
        if hasattr(self, 'map_data_points') and self.map_data_points:
            self.update_map_statistics()
        
        # Auto-save to ensure persistence
        self.auto_save_exclusion_zones()
        print("Cleared all %d exclusion zones and auto-saved to config" % zones_count)
        
    def zoom_in_map(self):
        """Zoom in to the center of the map."""
        if hasattr(self, 'map_scale') and self.map_scale > 0:
            canvas_width = self.map_canvas.winfo_width()
            canvas_height = self.map_canvas.winfo_height()
            
            if canvas_width > 1 and canvas_height > 1:
                # Zoom in by factor of 1.5
                zoom_factor = 1.5
                new_scale = self.map_scale * zoom_factor
                
                if new_scale < 500:  # Reduced limit for performance
                    self.map_scale = new_scale
                    self.map_center_x = canvas_width / 2
                    self.map_center_y = canvas_height / 2
                    self.redraw_map_at_current_zoom()
    
    def zoom_out_map(self):
        """Zoom out from the center of the map."""
        if hasattr(self, 'map_scale') and self.map_scale > 0:
            canvas_width = self.map_canvas.winfo_width()
            canvas_height = self.map_canvas.winfo_height()
            
            if canvas_width > 1 and canvas_height > 1:
                # Zoom out by factor of 1.5
                zoom_factor = 1 / 1.5
                new_scale = self.map_scale * zoom_factor
                
                if new_scale > 0.001:  # Limit minimum zoom
                    self.map_scale = new_scale
                    self.map_center_x = canvas_width / 2
                    self.map_center_y = canvas_height / 2
                    self.redraw_map_at_current_zoom()
    
    def reset_map_zoom(self):
        """Reset map zoom to show all data points."""
        # Clear all canvas items first
        self.map_canvas.delete("all")
        
        if self.map_data_points:
            # Recalculate and reset the map view to show all data
            self.plot_map_data()
            
            # Redraw exclusion zones if any
            if hasattr(self, 'exclusion_circles_data') and self.exclusion_circles_data:
                self.redraw_exclusion_zones()
                
            # Update statistics
            self.update_map_statistics()

    # Map interaction event handlers
    def _on_map_left_press(self, event):
        """Handle left mouse press on map."""
        self.is_dragging = False
        
        if self.drawing_exclusion:
            self.exclusion_start_point = (event.x, event.y)
        elif self.removing_exclusion:
            # Check if clicking on an exclusion zone
            print("Left click detected in removal mode at (%d, %d)" % (event.x, event.y))
            self.remove_exclusion_at_point(event.x, event.y)
        else:
            # Start zoom window
            self.zoom_start_point = (event.x, event.y)
            
    def _on_map_left_motion(self, event):
        """Handle left mouse motion on map."""
        if self.drawing_exclusion and self.exclusion_start_point:
            # Draw temporary exclusion circle
            if self.temp_exclusion_circle:
                self.map_canvas.delete(self.temp_exclusion_circle)
            x1, y1 = self.exclusion_start_point
            radius = ((event.x - x1)**2 + (event.y - y1)**2)**0.5
            self.temp_exclusion_circle = self.map_canvas.create_oval(
                x1 - radius, y1 - radius, x1 + radius, y1 + radius,
                outline="red", width=2, tags="temp_exclusion"
            )
        elif self.zoom_start_point and not self.removing_exclusion:
            # Set dragging flag
            self.is_dragging = True
            # Draw zoom rectangle
            if self.map_zoom_rect:
                self.map_canvas.delete(self.map_zoom_rect)
            x1, y1 = self.zoom_start_point
            self.map_zoom_rect = self.map_canvas.create_rectangle(
                x1, y1, event.x, event.y,
                outline="blue", width=2, dash=(3,3), tags="zoom_rect"
            )
            
    def _on_map_left_release(self, event):
        """Handle left mouse release on map."""
        if self.drawing_exclusion and self.exclusion_start_point:
            # Finalize exclusion circle
            x1, y1 = self.exclusion_start_point
            radius = ((event.x - x1)**2 + (event.y - y1)**2)**0.5
            if radius > 10:  # Minimum radius increased
                self.map_canvas.create_oval(
                    x1 - radius, y1 - radius, x1 + radius, y1 + radius,
                    outline="red", width=2, fill="red", stipple="gray25",
                    tags="exclusion_circle"
                )
                self.exclusion_circles.append((x1, y1, radius))
                
                # Convert canvas coordinates to real-world coordinates
                if hasattr(self, 'map_scale') and self.map_scale > 0:
                    # Convert center point to real coordinates
                    center_easting = self.data_center_x + (x1 - self.map_center_x) / self.map_scale
                    center_northing = self.data_center_y - (y1 - self.map_center_y) / self.map_scale
                    radius_meters = radius / self.map_scale
                    
                    self.exclusion_circles_data.append((center_easting, center_northing, radius_meters))
                    
                    # Update statistics after adding exclusion zone
                    self.update_map_statistics()
                    
                    # Auto-save exclusion zones to ensure persistence
                    self.auto_save_exclusion_zones()
                    print("Added exclusion zone and auto-saved to config")
                    
            if self.temp_exclusion_circle:
                self.map_canvas.delete(self.temp_exclusion_circle)
                self.temp_exclusion_circle = None
            self.exclusion_start_point = None
            
        elif self.zoom_start_point and self.is_dragging and not self.removing_exclusion:
            # Apply zoom window
            x1, y1 = self.zoom_start_point
            x2, y2 = event.x, event.y
            
            # Ensure we have a reasonable rectangle
            if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
                self.zoom_to_rectangle(x1, y1, x2, y2)
            
            if self.map_zoom_rect:
                self.map_canvas.delete(self.map_zoom_rect)
                self.map_zoom_rect = None
                
        self.zoom_start_point = None
        self.is_dragging = False
        
    def remove_exclusion_at_point(self, x, y):
        """Remove exclusion zone at the clicked point (improved implementation)."""
        print("Attempting to remove exclusion zone at canvas point (%d, %d)" % (x, y))
        
        # Convert canvas coordinates to data coordinates first
        if hasattr(self, 'map_scale') and self.map_scale > 0:
            data_x = self.data_center_x + (x - self.map_center_x) / self.map_scale
            data_y = self.data_center_y - (y - self.map_center_y) / self.map_scale
            print("Converted to data coordinates: (%.1f, %.1f)" % (data_x, data_y))
        else:
            print("No valid map scale, cannot convert coordinates")
            return
        
        # Check which exclusion zone was clicked using data coordinates
        removed_index = -1
        for i, (center_easting, center_northing, radius_meters) in enumerate(self.exclusion_circles_data):
            distance = ((data_x - center_easting)**2 + (data_y - center_northing)**2)**0.5
            print("Zone %d: center=(%.1f, %.1f), radius=%.1f, distance=%.1f" % (i, center_easting, center_northing, radius_meters, distance))
            
            if distance <= radius_meters:
                removed_index = i
                print("Found zone %d to remove!" % i)
                break
        
        if removed_index >= 0:
            # Remove from data list
            removed_zone = self.exclusion_circles_data.pop(removed_index)
            print("Removed exclusion zone %d (%.1f, %.1f, %.1f)" % (removed_index, removed_zone[0], removed_zone[1], removed_zone[2]))
            
            # Redraw all exclusion zones (this will update self.exclusion_circles too)
            self.map_canvas.delete("exclusion_circle")
            self.redraw_exclusion_zones()
            
            # Update statistics without redrawing map
            self.update_map_statistics()
            
            # Auto-save exclusion zones to ensure persistence
            self.auto_save_exclusion_zones()
            print("Exclusion zone removal completed successfully")
        else:
            print("No exclusion zone found at clicked location")
            
            # Debug: show all current zones
            print("Current exclusion zones:")
            for i, (easting, northing, radius) in enumerate(self.exclusion_circles_data):
                print("  Zone %d: (%.1f, %.1f) radius %.1f" % (i, easting, northing, radius))
    
    def delayed_exclusion_zone_redraw(self):
        """Redraw exclusion zones after GUI is fully loaded (for config loading)."""
        if hasattr(self, 'exclusion_circles_data') and self.exclusion_circles_data:
            if hasattr(self, 'map_scale') and hasattr(self, 'map_canvas'):
                print("Redrawing %d loaded exclusion zones" % len(self.exclusion_circles_data))
                self.redraw_exclusion_zones()
                # Also save them to ensure persistence
                if hasattr(self, 'config_file_path') and self.config_file_path:
                    try:
                        self.save_config()
                        print("Exclusion zones re-saved to config after loading")
                    except:
                        pass  # Don't fail if save doesn't work
    
    def auto_save_exclusion_zones(self):
        """Auto-save exclusion zones to config file to ensure persistence."""
        if hasattr(self, 'config_file_path') and self.config_file_path:
            try:
                # Read existing config
                config = ConfigParser.ConfigParser()
                config.read(self.config_file_path)
                
                # Remove old exclusion zone section if it exists
                if config.has_section('ExclusionZones'):
                    config.remove_section('ExclusionZones')
                
                # Add new exclusion zones
                config.add_section('ExclusionZones')
                if hasattr(self, 'exclusion_circles_data'):
                    for i, (easting, northing, radius) in enumerate(self.exclusion_circles_data):
                        config.set('ExclusionZones', 'zone_%d' % i, '%f,%f,%f' % (easting, northing, radius))
                
                # Write config back
                with open(self.config_file_path, 'w') as f:
                    config.write(f)
                    
                print("Auto-saved %d exclusion zones to config" % len(self.exclusion_circles_data))
            except Exception as e:
                print("Error auto-saving exclusion zones: %s" % str(e))
    
    def zoom_to_rectangle(self, x1, y1, x2, y2):
        """Zoom to the specified rectangle."""
        if not hasattr(self, 'map_scale') or self.map_scale <= 0:
            return
        
        # Get canvas dimensions
        canvas_width = self.map_canvas.winfo_width()
        canvas_height = self.map_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            return
        
        # Ensure x1,y1 is top-left and x2,y2 is bottom-right
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
            
        # Convert rectangle corners to data coordinates
        data_x1 = self.data_center_x + (x1 - self.map_center_x) / self.map_scale
        data_y1 = self.data_center_y - (y1 - self.map_center_y) / self.map_scale
        data_x2 = self.data_center_x + (x2 - self.map_center_x) / self.map_scale
        data_y2 = self.data_center_y - (y2 - self.map_center_y) / self.map_scale
        
        # Calculate new bounds
        data_width = abs(data_x2 - data_x1)
        data_height = abs(data_y2 - data_y1)
        
        if data_width > 0 and data_height > 0:
            # Calculate new scale to fit the rectangle
            scale_x = canvas_width / data_width
            scale_y = canvas_height / data_height
            new_scale = min(scale_x, scale_y) * 0.9  # 90% to leave margin
            
            # Limit zoom level for performance
            if new_scale > 500:
                new_scale = 500
            elif new_scale < 0.001:
                new_scale = 0.001
            
            # Set new center and scale
            self.data_center_x = (data_x1 + data_x2) / 2
            self.data_center_y = (data_y1 + data_y2) / 2
            self.map_scale = new_scale
            self.map_center_x = canvas_width / 2
            self.map_center_y = canvas_height / 2
            
            # Redraw at new zoom
            self.redraw_map_at_current_zoom()
            
    def _on_map_right_press(self, event):
        """Handle right mouse press on map (start panning)."""
        self.map_drag_start = (event.x, event.y)
        self.map_drag_start_original = (event.x, event.y)  # Track original start point
        self.map_canvas.config(cursor="fleur")
        
    def _on_map_right_motion(self, event):
        """Handle right mouse motion on map (super fast panning using canvas translation)."""
        if self.map_drag_start and hasattr(self, 'map_scale') and self.map_scale > 0:
            current_time = time.time()
            
            # Much faster throttling - only limit to 60fps for smoothness
            if current_time - self.last_pan_time < 0.016:  # ~60fps
                return
                
            dx = event.x - self.map_drag_start[0]
            dy = event.y - self.map_drag_start[1]
            
            # Use canvas.move() to translate all existing objects instantly
            # This is MUCH faster than redrawing everything
            self.map_canvas.move("data_point", dx, dy)
            self.map_canvas.move("exclusion_circle", dx, dy)
            
            # Update map center for coordinate calculations
            self.map_center_x += dx
            self.map_center_y += dy
            
            self.map_drag_start = (event.x, event.y)
            self.last_pan_time = current_time
            
    def _on_map_right_release(self, event):
        """Handle right mouse release on map (end panning and recalculate coordinates)."""
        if hasattr(self, 'map_drag_start_original') and self.map_drag_start_original:
            # Calculate total movement during the pan session from original start point
            total_dx = event.x - self.map_drag_start_original[0]
            total_dy = event.y - self.map_drag_start_original[1]
            
            # Update data center to maintain coordinate accuracy
            if hasattr(self, 'map_scale') and self.map_scale > 0:
                data_dx = total_dx / self.map_scale
                data_dy = -total_dy / self.map_scale  # Flip Y axis
                
                self.data_center_x -= data_dx
                self.data_center_y -= data_dy
                
                # Reset map center since we've updated data center
                canvas_width = self.map_canvas.winfo_width()
                canvas_height = self.map_canvas.winfo_height()
                self.map_center_x = canvas_width / 2
                self.map_center_y = canvas_height / 2
                
                print("Pan completed. Total movement: dx=%d, dy=%d, New data center: (%.1f, %.1f)" % 
                      (total_dx, total_dy, self.data_center_x, self.data_center_y))
        
        self.map_drag_start = None
        self.map_drag_start_original = None
        self.map_canvas.config(cursor="")
        
    def _on_map_scroll(self, event):
        """Handle mouse scroll on map (zooming with throttling)."""
        current_time = time.time()
        
        # Optimized throttling for scroll zoom (reduced to 60fps for smoother experience)
        throttle_time = 0.016  # ~60fps for super smooth zooming
        if current_time - self.last_scroll_time < throttle_time:
            return
            
        # Get mouse position
        mouse_x = event.x
        mouse_y = event.y
        
        # Determine zoom direction (Windows uses event.delta, Linux uses event.num)
        if hasattr(event, 'delta'):
            zoom_in = event.delta > 0
        else:
            zoom_in = event.num == 4
        
        # Smaller zoom factor for smoother zooming
        zoom_factor = 1.2 if zoom_in else 1/1.2
        
        # Get current canvas dimensions
        canvas_width = self.map_canvas.winfo_width()
        canvas_height = self.map_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            return
        
        # Initialize zoom parameters if not set
        if not hasattr(self, 'map_scale') or self.map_scale <= 0:
            self.map_scale = 1.0
            self.data_center_x = 0.0
            self.data_center_y = 0.0
            self.map_center_x = canvas_width / 2
            self.map_center_y = canvas_height / 2
        
        # Calculate zoom around mouse position
        # Limit zoom levels for performance
        new_scale = self.map_scale * zoom_factor
        if new_scale < 0.001 or new_scale > 500:  # Reduced max zoom for performance
            return
        
        # Calculate new center to zoom around mouse position
        # Convert mouse position to data coordinates
        mouse_data_x = self.data_center_x + (mouse_x - self.map_center_x) / self.map_scale
        mouse_data_y = self.data_center_y - (mouse_y - self.map_center_y) / self.map_scale
        
        # Calculate new data center
        self.data_center_x = mouse_data_x - (mouse_x - canvas_width/2) / new_scale
        self.data_center_y = mouse_data_y + (mouse_y - canvas_height/2) / new_scale
        
        self.map_scale = new_scale
        self.map_center_x = canvas_width / 2
        self.map_center_y = canvas_height / 2
        
        # Use optimized redraw for scrolling - only redraw if we have data
        if self.map_data_points:
            self.redraw_map_at_current_zoom()
        else:
            # Clear canvas to show zoom change even without data
            self.map_canvas.delete("all")
            
        self.last_scroll_time = current_time
    
    def redraw_map_at_current_zoom(self):
        """Redraw map data points at current zoom level (with progressive loading)."""
        # Clear all existing canvas items to prevent leftover dots
        self.map_canvas.delete("all")
        
        # Check if we need to load more data for current view (disabled for initial troubleshooting)
        # self.check_and_load_visible_data()
        
        if not self.map_data_points:
            print("No map data points available for redraw")
            return
        
        canvas_width = self.map_canvas.winfo_width()
        canvas_height = self.map_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            return
        
        # Show ALL points optimization
        visible_points = 0
        total_points = len(self.map_data_points)
        
        # Adaptive point size and event binding based on zoom level and dataset size
        if hasattr(self, 'map_scale') and self.map_scale > 0:
            if self.map_scale > 5:  # Very zoomed in - larger points
                point_size = 3
                event_skip = 20  # More interactive
            elif self.map_scale > 1:  # Zoomed in - medium points
                point_size = 2
                event_skip = 30
            else:  # Normal/zoomed out - smaller points for performance
                point_size = 1
                event_skip = 50
        else:
            point_size = 2
            event_skip = 50
        
        # If dataset is huge, make points even smaller
        if total_points > 500000:
            point_size = 1
            event_skip = 100
        elif total_points > 100000:
            point_size = 1
            event_skip = 75
        
        # Plot all data points (Show All Points mode is always enabled)
        for i, point_data in enumerate(self.map_data_points):
                
            if len(point_data) == 6:
                easting, northing, overall_passing, sp_no, seq_num, criteria_results = point_data
            else:
                # Fallback for old format
                easting, northing, overall_passing, sp_no, seq_num = point_data[:5]
                criteria_results = [overall_passing]
                
            canvas_x = self.map_center_x + (easting - self.data_center_x) * self.map_scale
            canvas_y = self.map_center_y - (northing - self.data_center_y) * self.map_scale
            
            # Check if point is visible (with margin for smooth scrolling)
            if -50 <= canvas_x <= canvas_width + 50 and -50 <= canvas_y <= canvas_height + 50:
                if overall_passing:
                    color = "green"
                else:
                    color = "red"
                
                point_id = self.map_canvas.create_oval(
                    canvas_x - point_size, canvas_y - point_size, 
                    canvas_x + point_size, canvas_y + point_size,
                    fill=color, outline="", width=0,
                    tags="data_point"
                )
                
                # Bind events based on calculated skip factor
                if visible_points % event_skip == 0:
                    self.map_canvas.tag_bind(point_id, "<Button-1>", 
                        lambda e, sp=sp_no, seq=seq_num: self.on_map_point_click(e, sp, seq))
                
                visible_points += 1
        
        # Debug info for zoom/pan operations
        if hasattr(self, 'map_scale'):
            print("Zoom redraw: ALL %d visible points rendered at scale %.3f from %d total" % (visible_points, self.map_scale, total_points))
        
        # Redraw exclusion circles (optimized)
        self.redraw_exclusion_zones()
    
    def redraw_exclusion_zones(self):
        """Redraw exclusion zones from loaded data."""
        if not hasattr(self, 'map_scale') or self.map_scale <= 0:
            return
        
        canvas_width = self.map_canvas.winfo_width()
        canvas_height = self.map_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            return
        
        # Reset the canvas list (canvas is already cleared by calling function)
        self.exclusion_circles = []
        
        # Draw exclusion circles from data
        for circle_data in self.exclusion_circles_data:
            center_easting, center_northing, radius_meters = circle_data
            canvas_x = self.map_center_x + (center_easting - self.data_center_x) * self.map_scale
            canvas_y = self.map_center_y - (center_northing - self.data_center_y) * self.map_scale
            canvas_radius = radius_meters * self.map_scale
            
            # Only draw if visible and reasonable size
            if (canvas_radius > 1 and 
                -canvas_radius <= canvas_x <= canvas_width + canvas_radius and 
                -canvas_radius <= canvas_y <= canvas_height + canvas_radius):
                circle_id = self.map_canvas.create_oval(
                    canvas_x - canvas_radius, canvas_y - canvas_radius,
                    canvas_x + canvas_radius, canvas_y + canvas_radius,
                    outline="red", width=2, fill="red", stipple="gray25",
                    tags="exclusion_circle"
                )
                
                # Update canvas coordinates for removal detection
                self.exclusion_circles.append((canvas_x, canvas_y, canvas_radius))


    def _update_criteria_entries(self):
        """
        Dynamically creates or removes criteria entry fields
        based on the number of criteria entered by the user.
        """
        # Clear existing criteria widgets
        for widget in self.criteria_entries_frame.winfo_children():
            widget.destroy()
        self.criteria_data = []

        try:
            num_criteria = int(self.num_criteria_var.get())
            if num_criteria < 1:
                num_criteria = 1
            if num_criteria > 10:  # Reasonable limit
                num_criteria = 10
                self.num_criteria_var.set("10")
        except ValueError:
            num_criteria = 1
            self.num_criteria_var.set("1")

        # Create criteria entries with inline labels
        for i in range(num_criteria):
            row_idx = i  # Start from row 0 (no header)
            
            # Create variables for this criteria set
            criteria_vars = {
                'pass_fail_criteria': tk.StringVar(self.master, value="Max % of Failure for whole line"),
                'criteria_value': tk.StringVar(self.master, value="5.0"),
                'stat_for_criteria': tk.StringVar(self.master, value="Radial"),
                'spec_value': tk.StringVar(self.master, value="1.0"),
                'include_in_verdict': tk.BooleanVar(self.master, value=True)
            }
            
            col = 0
            
            # Pass/Fail Criteria label and dropdown
            tk.Label(self.criteria_entries_frame, text="Pass/Fail Criteria:", bg="#B4C8E1").grid(row=row_idx, column=col, sticky="w", padx=2, pady=2)
            col += 1
            criteria_options = [
                "Max % of Failure for whole line",
                "Average for the whole line", 
                "Max Consecutive Failures"
            ]
            criteria_menu = tk.OptionMenu(self.criteria_entries_frame, criteria_vars['pass_fail_criteria'], *criteria_options)
            criteria_menu.config(bg="#8DA9CC", fg="black", width=25)
            criteria_menu["menu"].config(bg="#8DA9CC", fg="black")
            criteria_menu.grid(row=row_idx, column=col, padx=2, pady=2, sticky="ew")
            col += 1
            
            # Criteria Value label and entry
            tk.Label(self.criteria_entries_frame, text="Criteria Value:", bg="#B4C8E1").grid(row=row_idx, column=col, sticky="w", padx=2, pady=2)
            col += 1
            tk.Entry(self.criteria_entries_frame, textvariable=criteria_vars['criteria_value'], width=10).grid(row=row_idx, column=col, padx=2, pady=2)
            col += 1
            
            # Stat for Criteria label and dropdown
            tk.Label(self.criteria_entries_frame, text="Stat for Criteria:", bg="#B4C8E1").grid(row=row_idx, column=col, sticky="w", padx=2, pady=2)
            col += 1
            stat_options = ["Radial", "Crossline", "Inline"]
            stat_menu = tk.OptionMenu(self.criteria_entries_frame, criteria_vars['stat_for_criteria'], *stat_options)
            stat_menu.config(bg="#8DA9CC", fg="black", width=10)
            stat_menu["menu"].config(bg="#8DA9CC", fg="black")
            stat_menu.grid(row=row_idx, column=col, padx=2, pady=2, sticky="ew")
            col += 1
            
            # Spec Value label and entry
            tk.Label(self.criteria_entries_frame, text="Spec Value (m):", bg="#B4C8E1").grid(row=row_idx, column=col, sticky="w", padx=2, pady=2)
            col += 1
            tk.Entry(self.criteria_entries_frame, textvariable=criteria_vars['spec_value'], width=10).grid(row=row_idx, column=col, padx=2, pady=2)
            col += 1
            
            # Include in Overall Verdict checkbox
            tk.Checkbutton(self.criteria_entries_frame, text="Include in Overall Verdict", 
                          variable=criteria_vars['include_in_verdict'], bg="#B4C8E1").grid(row=row_idx, column=col, sticky="w", padx=2, pady=2)
            
            # Store the variables
            self.criteria_data.append(criteria_vars)

        # Configure column weights for proper resizing
        for col in range(9):  # Now we have 9 columns (4 labels + 4 controls + 1 checkbox)
            self.criteria_entries_frame.grid_columnconfigure(col, weight=1)


    def _update_excluded_sp_entries(self):
        """
        Dynamically creates or removes excluded shotpoint entry fields
        based on the sequences entered by the user.
        """
        # Destroy existing widgets
        for label, entry in self.excluded_sp_entry_widgets:
            label.destroy()
            entry.destroy()
        self.excluded_sp_entry_widgets = []
        self.excluded_sp_vars_by_sequence = {} # Clear associated StringVars
        
        # Clear all widgets in the frame to remove any placeholder messages
        for widget in self.excluded_sp_entries_frame.winfo_children():
            widget.destroy()

        raw_sequences = self.sequences_var.get()
        if not raw_sequences:
            tk.Label(self.excluded_sp_entries_frame, text="Enter sequences above to add excluded shotpoint fields.", bg="#B4C8E1").grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=2)
            return

        try:
            sequences = [int(s.strip()) for s in raw_sequences.split(',') if s.strip()]
            sequences = sorted(list(set(sequences))) # Remove duplicates and sort for consistent order
        except ValueError:
            # If sequence input is invalid, don't create entries
            tk.Label(self.excluded_sp_entries_frame, text="Invalid sequence format. Please use comma-separated integers.", bg="#B4C8E1", fg="red").grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=2)
            return

        for i, seq_num in enumerate(sequences):
            row_idx = i # Each sequence gets its own row
            # Get line name from ShotInfo filename
            nav_qc_dir = self.nav_line_qc_dir_var.get()
            line_name = self._get_line_name_from_shotinfo(seq_num, nav_qc_dir)
            # If we detect a line name, update the Search by SL box with its first 5 digits (SL)
            if line_name:
                try:
                    sl_five = line_name[:5] if len(line_name) >= 5 else line_name
                    self.sl_search_var.set(sl_five)
                except Exception:
                    pass
            # Always show brackets; fill with '?' if missing
            label_text = "Excluded SP for Seq %d (%s):" % (seq_num, (line_name if line_name else '?'))
            label = tk.Label(self.excluded_sp_entries_frame, text=label_text, bg="#B4C8E1")
            # Reduce right padding and anchor west to cut the gap
            label.grid(row=row_idx, column=0, sticky="w", padx=(5,2), pady=2)

            sp_var = tk.StringVar(self.master, value="")
            entry = tk.Entry(self.excluded_sp_entries_frame, textvariable=sp_var, width=45)
            entry.grid(row=row_idx, column=1, padx=(2,5), pady=2, sticky="ew")

            self.excluded_sp_entry_widgets.append((label, entry))
            self.excluded_sp_vars_by_sequence[seq_num] = sp_var

        # Re-apply previously loaded values if they exist
        if hasattr(self, '_loaded_excluded_sps') and self._loaded_excluded_sps:
            for seq_num, sp_string in self._loaded_excluded_sps.items():
                if seq_num in self.excluded_sp_vars_by_sequence:
                    self.excluded_sp_vars_by_sequence[seq_num].set(sp_string)
            self._loaded_excluded_sps = {} # Clear after applying

        # Update the sequence info panel when sequences are modified
        self._update_sequence_info_panel()

    def _set_seq_info_text(self, content):
        """Helper to show a message in the Sequence Info area.
        If the Treeview exists, show a single placeholder row; otherwise
        fall back to the legacy text widget if present.
        """
        try:
            if hasattr(self, 'seq_info_table') and self.seq_info_table is not None:
                # Clear table and insert a placeholder message in the SOL column
                try:
                    for item_id in self.seq_info_table.get_children():
                        self.seq_info_table.delete(item_id)
                except Exception:
                    pass
                try:
                    self.seq_info_table.insert('', 'end', values=("—", "—", "—", content, "—"))
                except Exception:
                    pass
                return
            if hasattr(self, 'seq_info_text') and self.seq_info_text is not None:
                self.seq_info_text.config(state="normal")
                self.seq_info_text.delete("1.0", tk.END)
                self.seq_info_text.insert(tk.END, content)
        finally:
            if hasattr(self, 'seq_info_text') and self.seq_info_text is not None:
                self.seq_info_text.config(state="disabled")

    def _infer_sl_from_sequence(self, sequence_num, nav_qc_dir):
        """Infers the line (SL) from a stats file name within the sequence folder.
        The SL is the first 5 digits of the filename before the first dot, e.g., 53556 from '535561113309.a3309_...'
        """
        try:
            # Prefer inferring from ShotInfo filename for robustness
            try:
                line_name_from_shotinfo = self._get_line_name_from_shotinfo(sequence_num, nav_qc_dir)
                if line_name_from_shotinfo:
                    return line_name_from_shotinfo[:5] if len(line_name_from_shotinfo) >= 5 else line_name_from_shotinfo
            except Exception:
                pass
            seq_dir = os.path.join(nav_qc_dir, str(sequence_num))
            if not os.path.isdir(seq_dir):
                return None
            for filename in os.listdir(seq_dir):
                # Ensure this looks like the stats file we use elsewhere (now supports any letter prefix)
                if re.search(r"\.([a-zA-Z])\d+_", filename):
                    m = re.match(r"(\d{5})", filename)
                    if m:
                        return m.group(1)
            # Fallback: try any file starting with 5 digits
            for filename in os.listdir(seq_dir):
                m = re.match(r"(\d{5})", filename)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return None

    def _get_line_name_from_shotinfo(self, sequence_num, nav_qc_dir):
        """Extracts the full line name from ShotInfo filename for a given sequence.
        Accepts filenames like 'ShotInfo_NC21-G25A55356113720.csv' or with extra suffixes.
        """
        try:
            seq_dir = os.path.join(nav_qc_dir, str(sequence_num))
            if not os.path.isdir(seq_dir):
                return None
            # Be flexible on job code and optional letter after G25
            pattern = re.compile(r"^ShotInfo_.*?G25[A-Z]?(\d+)", re.IGNORECASE)
            for filename in os.listdir(seq_dir):
                m = pattern.match(filename)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return None

    def _format_shotinfo_datetime(self, value):
        """Attempts to parse a date/time string and render as MM/DD/YYYY  HH:MM:SS.
        If parsing fails, returns the original trimmed value.
        """
        try:
            from datetime import datetime
            import re
            v = (value or '').strip()
            if not v:
                return 'N/A'
            # Strip fractional seconds if present (e.g., HH:MM:SS.fff or HH:MM:SS,fff)
            v = re.sub(r"(\d{2}:\d{2}:\d{2})[\.,]\d+", r"\1", v)
            # Try several common formats
            formats = [
                '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S',
                '%d.%m.%Y %H:%M:%S', '%m.%d.%Y %H:%M:%S', '%Y-%m-%d %H:%M', '%m/%d/%Y %H:%M', '%d/%m/%Y %H:%M'
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(v, fmt)
                    # Render as '08 Sep 2025  14:27:46'
                    return dt.strftime('%d %b %Y  %H:%M:%S')
                except Exception:
                    pass
            # If none matched, return as-is
            return v
        except Exception:
            return (value or '').strip() or 'N/A'

    def _parse_shotinfo_datetime_key(self, value):
        """Parses a date/time string into a sortable epoch seconds float.
        Returns None if parsing fails.
        """
        try:
            from datetime import datetime
            import re, time
            v = (value or '').strip()
            if not v:
                return None
            v = re.sub(r"(\d{2}:\d{2}:\d{2})[\.,]\d+", r"\1", v)
            formats = [
                '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S',
                '%d.%m.%Y %H:%M:%S', '%m.%d.%Y %H:%M:%S', '%Y-%m-%d %H:%M', '%m/%d/%Y %H:%M', '%d/%m/%Y %H:%M'
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(v, fmt)
                    return time.mktime(dt.timetuple())
                except Exception:
                    pass
            return None
        except Exception:
            return None

    def _parse_shotinfo_sp_range(self, filepath):
        """Parses a ShotInfo CSV and returns (first_sp, last_sp, first_time, last_time, first_key, last_key)
        for production shots, where keys are sortable timestamps (epoch seconds).
        Only rows with shot type indicating production are considered. If a production
        indicator column cannot be found, no rows are counted.
        """
        first_sp = None
        last_sp = None
        first_time = None
        last_time = None
        first_key = None
        last_key = None
        try:
            with open(filepath, 'rb') as f:
                reader = csv.reader(f)
                try:
                    header = reader.next()
                except Exception:
                    try:
                        header = next(reader)
                    except Exception:
                        return (None, None)
                header_lower = [h.strip().lower() for h in header]
                # Candidate columns for SP
                sp_candidates = set([
                    'sp', 'shotpoint', 'shot point', 'pos', 'pos no', 'pos_no', 'posno', 'shot', 'shot no', 'shotno', 'pos no.'
                ])
                sp_idx = None
                for i, name in enumerate(header_lower):
                    if name in sp_candidates or (('shot' in name or 'sp' in name) and ('time' not in name and 'delay' not in name)):
                        sp_idx = i
                        break
                # Candidate columns for production indicator (normalized to lowercase)
                # Include common variations like "Shot Type"
                prod_candidates = set(['type', 'shot_type', 'shot type', 'shottype', 'mode', 'status', 'production', 'prod'])
                prod_idx = None
                for i, name in enumerate(header_lower):
                    if name in prod_candidates:
                        prod_idx = i
                        break

                def _is_prod(row):
                    # Only count production rows; if the indicator column is missing,
                    # treat as not production.
                    if prod_idx is None or prod_idx >= len(row):
                        return False
                    val = row[prod_idx].strip().lower()
                    return (val.startswith('prod') or val in ('production', 'prod', 'p', 'prd'))

                if sp_idx is None:
                    return (None, None, None, None, None, None)
                for row in reader:
                    if sp_idx >= len(row):
                        continue
                    if not _is_prod(row):
                        continue
                    sp_raw = row[sp_idx].strip()
                    if not sp_raw:
                        continue
                    try:
                        sp_val = int(round(float(sp_raw)))
                    except Exception:
                        continue
                    # Column A (index 0) is timestamp per requirement
                    ts_raw = row[0].strip() if len(row) > 0 else ''
                    ts_key = self._parse_shotinfo_datetime_key(ts_raw)
                    ts_fmt = self._format_shotinfo_datetime(ts_raw)
                    # First/last by chronological order within this file
                    if first_sp is None:
                        first_sp = sp_val
                        first_time = ts_fmt
                        first_key = ts_key
                    # Always update last to the current row
                    last_sp = sp_val
                    last_time = ts_fmt
                    last_key = ts_key
        except Exception:
            return (None, None, None, None, None, None)
        return (first_sp, last_sp, first_time, last_time, first_key, last_key)

    def _collect_sequences_for_sl(self, sl, nav_qc_dir):
        """Scans sequence subfolders for ShotInfo files belonging to the given SL.
        Returns a sorted list of dicts: { 'seq': int, 'first_sp': int|'N/A', 'last_sp': int|'N/A' }.
        """
        results = []
        try:
            # Normalize SL to digits only, using the first 5 digits if longer
            try:
                sl_key = re.sub(r"\D", "", sl or "")
                if len(sl_key) >= 5:
                    sl_key = sl_key[:5]
            except Exception:
                sl_key = (sl or '').strip()
            if not os.path.isdir(nav_qc_dir):
                return results
            for seq_folder in os.listdir(nav_qc_dir):
                try:
                    seq_num = int(seq_folder)
                except Exception:
                    continue
                folder_path = os.path.join(nav_qc_dir, seq_folder)
                if not os.path.isdir(folder_path):
                    continue
                try:
                    # Accept ShotInfo files whose digits immediately after 'G25' (optional letter) start with the SL key
                    candidates = []
                    _pat = re.compile(r"^ShotInfo[-_].*?G25[A-Z]?(\d+)", re.IGNORECASE)
                    matched_digits = []
                    for fn in os.listdir(folder_path):
                        fn_lower = fn.lower()
                        if not ((fn_lower.startswith('shotinfo_') or fn_lower.startswith('shotinfo-')) and fn_lower.endswith('.csv')):
                            continue
                        m = _pat.match(fn)
                        if not m:
                            continue
                        line_digits = m.group(1)
                        if sl_key and line_digits.startswith(sl_key):
                            candidates.append(os.path.join(folder_path, fn))
                            matched_digits.append(line_digits)
                except Exception:
                    continue
                # Fallback: if no ShotInfo match, infer SL from stats files and include if it matches
                include_by_infer = False
                if not candidates:
                    inferred = self._infer_sl_from_sequence(seq_num, nav_qc_dir)
                    try:
                        inferred_key = re.sub(r"\D", "", inferred or "")[:5] if inferred else None
                    except Exception:
                        inferred_key = inferred
                    if inferred_key and sl_key and inferred_key == sl_key:
                        include_by_infer = True
                if not candidates and not include_by_infer:
                    continue
                seq_first = None
                seq_last = None
                seq_sol = None
                seq_eol = None
                seq_first_key = None
                seq_last_key = None
                for fp in candidates:
                    fsp, lsp, ftm, ltm, fkey, lkey = self._parse_shotinfo_sp_range(fp)
                    if fkey is not None:
                        if seq_first_key is None or fkey < seq_first_key:
                            seq_first_key = fkey
                            seq_first = fsp
                            seq_sol = ftm
                    if lkey is not None:
                        if seq_last_key is None or lkey > seq_last_key:
                            seq_last_key = lkey
                            seq_last = lsp
                            seq_eol = ltm
                # Even if we could not parse SP/time (e.g., no production markers), still include the sequence
                # Determine full line name for this sequence from ShotInfo in the sequence folder
                try:
                    line_name_val = self._get_line_name_from_shotinfo(seq_num, nav_qc_dir)
                except Exception:
                    line_name_val = None
                results.append({
                    'seq': seq_num,
                    'first_sp': seq_first if seq_first is not None else 'N/A',
                    'last_sp': seq_last if seq_last is not None else 'N/A',
                    'sol': seq_sol if seq_sol is not None else 'N/A',
                    'eol': seq_eol if seq_eol is not None else 'N/A',
                    'line': line_name_val if line_name_val is not None else 'N/A'
                })
        except Exception:
            return results
        results.sort(key=lambda x: x['seq'])
        return results

    def _on_search_sl(self):
        """Search sequences by SL and populate the sequences field with results."""
        sl = self.sl_search_var.get().strip()
        if not sl:
            self.update_results_window("Enter an SL to search.")
            return
        nav_qc_dir = self.nav_line_qc_dir_var.get()
        seqs = self._collect_sequences_for_sl(sl, nav_qc_dir)
        if not seqs:
            self.update_results_window("No sequences found for SL %s." % sl)
            return
        seq_list = ", ".join(str(item['seq']) for item in seqs)
        self.sequences_var.set(seq_list)
        # Trigger updates
        self._update_excluded_sp_entries()

    def _update_sequence_info_panel(self):
        """Updates the SL label and sequence list for the inferred line of the first entered sequence."""
        raw_sequences = self.sequences_var.get()
        # Parse sequences
        seqs = []
        for token in [t.strip() for t in raw_sequences.split(',') if t.strip()]:
            try:
                seqs.append(int(token))
            except Exception:
                continue
        if not seqs:
            self.seq_info_line_label.config(text="Preplot Line: –")
            self._set_seq_info_text("Enter sequences to view SL and its sequences list.")
            return
        nav_qc_dir = self.nav_line_qc_dir_var.get()
        sl = self._infer_sl_from_sequence(seqs[0], nav_qc_dir)
        if not sl:
            self.seq_info_line_label.config(text="Preplot Line: Unknown")
            self._set_seq_info_text("Could not infer line from stats files for sequence %d." % seqs[0])
            return
        self.seq_info_line_label.config(text="Preplot Line: %s" % sl)

        # Always recalculate sequence list to avoid stale cache issues
        seq_info_list = self._collect_sequences_for_sl(sl, nav_qc_dir)

        if not seq_info_list:
            # Clear table
            for i in self.seq_info_table.get_children():
                self.seq_info_table.delete(i)
            try:
                self.seq_info_table.configure(height=1)
            except Exception:
                pass
            self.seq_info_table.insert('', 'end', values=("—", "—", "—", "No ShotInfo for SL %s" % sl, "—", "—"))
            return

        # Populate the table
        for i in self.seq_info_table.get_children():
            self.seq_info_table.delete(i)
        # Adjust visible rows based on number of sequences (bounded for usability)
        try:
            desired_rows = len(seq_info_list)
            if desired_rows < 1:
                desired_rows = 1
            if desired_rows > 12:
                desired_rows = 12
            self.seq_info_table.configure(height=desired_rows)
        except Exception:
            pass
        for item in seq_info_list:
            sol = item.get('sol', 'N/A')
            eol = item.get('eol', 'N/A')
            line_name_val = item.get('line', 'N/A')
            self.seq_info_table.insert('', 'end', values=(item['seq'], item['first_sp'], item['last_sp'], sol, eol, line_name_val))

    def _tab_is_added(self, frame):
        try:
            return str(frame) in self.results_notebook.tabs()
        except Exception:
            return False

    def _show_tab(self, frame, title):
        try:
            if not self._tab_is_added(frame):
                self.results_notebook.add(frame, text=title)
            else:
                try:
                    self.results_notebook.tab(frame, state='normal')
                except Exception:
                    pass
        except Exception:
            pass

    def _hide_tab(self, frame):
        try:
            if self._tab_is_added(frame):
                try:
                    self.results_notebook.hide(frame)
                except Exception:
                    self.results_notebook.forget(frame)
        except Exception:
            pass

    def _set_proposals_text(self, content):
        try:
            self.proposals_text.config(state="normal")
            self.proposals_text.delete("1.0", tk.END)
            self.proposals_text.insert(tk.END, content)
        finally:
            self.proposals_text.config(state="disabled")

    def _on_canvas_press(self, event):
        """Records the starting position for zoom window or pan."""
        self._clear_tooltip() # Clear any existing tooltip on new press
        self._clear_highlight_ring() # Clear any existing highlight ring on new press
        self.start_x_mouse = event.x
        self.start_y_mouse = event.y
        if event.num == 1: # Left click
            self.drag_mode = 'zoom_window'
            if self.zoom_rect_id:
                self.plot_canvas.delete(self.zoom_rect_id)
            self.zoom_rect_id = self.plot_canvas.create_rectangle(self.start_x_mouse, self.start_y_mouse, self.start_x_mouse, self.start_y_mouse, outline="blue", dash=(5, 5))
        elif event.num == 3: # Right click
            self.drag_mode = 'pan'

    def _on_canvas_motion(self, event):
        """Draws the zoom rectangle or performs panning."""
        if self.drag_mode == 'zoom_window' and self.start_x_mouse is not None:
            self.plot_canvas.coords(self.zoom_rect_id, self.start_x_mouse, self.start_y_mouse, event.x, event.y)
        elif self.drag_mode == 'pan' and self.start_x_mouse is not None:
            dx = event.x - self.start_x_mouse
            dy = event.y - self.start_y_mouse

            # Convert pixel delta to data delta
            canvas_width = self.plot_canvas.winfo_width() - 80 # Account for padding/margins
            canvas_height = self.plot_canvas.winfo_height() - 60 # Account for padding/margins

            if canvas_width > 0 and canvas_height > 0:
                x_range = self.current_x_max - self.current_x_min
                y_range = self.current_y_max - self.current_y_min

                data_dx = float(dx) / canvas_width * x_range
                data_dy = float(dy) / canvas_height * y_range # Invert Y-axis for panning

                self.current_x_min -= data_dx
                self.current_x_max -= data_dx
                self.current_y_min += data_dy # Y-axis in Tkinter is inverted
                self.current_y_max += data_dy # Y-axis in Tkinter is inverted

                self.start_x_mouse = event.x # Update start for continuous pan
                self.start_y_mouse = event.y
                self._draw_graph()

    def _on_canvas_release(self, event):
        """Processes zoom window or pan completion, or point click."""
        if self.zoom_rect_id:
            self.plot_canvas.delete(self.zoom_rect_id)
            self.zoom_rect_id = None

        if self.drag_mode == 'zoom_window' and self.start_x_mouse is not None:
            end_x_mouse, end_y_mouse = event.x, event.y

            # Ensure a meaningful drag occurred for zoom window
            if abs(end_x_mouse - self.start_x_mouse) > 5 or abs(end_y_mouse - self.start_y_mouse) > 5: # Small threshold to differentiate from click
                # Convert canvas coordinates to data coordinates for new view
                x1_data = self._canvas_to_data_x(min(self.start_x_mouse, end_x_mouse))
                x2_data = self._canvas_to_data_x(max(self.start_x_mouse, end_x_mouse))
                y1_data = self._canvas_to_data_y(max(self.start_y_mouse, end_y_mouse)) # Y-axis inverted
                y2_data = self._canvas_to_data_y(min(self.start_y_mouse, end_y_mouse)) # Y-axis inverted

                # Ensure a valid zoom area was selected
                if abs(x2_data - x1_data) > 0.01 and abs(y2_data - y1_data) > 0.01: # Small threshold
                    self.current_x_min = x1_data
                    self.current_x_max = x2_data
                    self.current_y_min = y1_data
                    self.current_y_max = y2_data
                    self._draw_graph()
                else:
                    # If it was a small click, check for point selection
                    self._check_point_click(event.x, event.y)
            else: # It was a short drag or just a click
                self._check_point_click(event.x, event.y)

        # No specific action needed for 'pan' release, motion already handled redraw
        # And we don't want to trigger _check_point_click after a pan.

        self.start_x_mouse = None
        self.start_y_mouse = None
        self.drag_mode = None

    def _on_canvas_scroll(self, event):
        """Handles mouse wheel scrolling for zooming."""
        self._clear_tooltip() # Clear tooltip on scroll
        self._clear_highlight_ring() # Clear highlight ring on scroll
        zoom_factor = 1.1 # How much to zoom in/out
        # Determine scroll direction
        if event.num == 4 or event.delta > 0: # Scroll up (zoom in)
            factor = 1.0 / zoom_factor
        else: # Scroll down (zoom out)
            factor = zoom_factor

        # Get mouse position in data coordinates
        mouse_x_data = self._canvas_to_data_x(event.x)
        mouse_y_data = self._canvas_to_data_y(event.y)

        # Calculate new view limits, keeping mouse position as anchor
        # new_x_range = (self.current_x_max - self.current_x_min) * factor # Not directly used
        # new_y_range = (self.current_y_max - self.current_y_min) * factor # Not directly used

        self.current_x_min = mouse_x_data - (mouse_x_data - self.current_x_min) * factor
        self.current_x_max = mouse_x_data + (self.current_x_max - mouse_x_data) * factor
        self.current_y_min = mouse_y_data - (mouse_y_data - self.current_y_min) * factor
        self.current_y_max = mouse_y_data + (self.current_y_max - mouse_y_data) * factor

        self._draw_graph()

    def _center_full_view(self):
        """Resets the graph view to show all data (equivalent to old _reset_zoom)."""
        self._clear_tooltip() # Clear tooltip on zoom reset
        self._clear_highlight_ring() # Clear highlight ring on zoom reset
        self.current_x_min, self.current_x_max = self.x_data_min, self.x_data_max
        self.current_y_min, self.current_y_max = self.y_data_min, self.y_data_max
        self._draw_graph()
        self.update_results_window("Graph view reset to full data range.")


    def _center_nominal_view(self):
        """Centers the graph view around a nominal y-value (0) and the average x-value."""
        self._clear_tooltip() # Clear tooltip on view change
        self._clear_highlight_ring() # Clear highlight ring on view change

        if not self.all_plot_data:
            self.update_results_window("Cannot center nominal: No data to plot.")
            return

        # Calculate average X of all data points
        # self.all_plot_data stores (sp_no, stat_value_abs, original_stat_value, sequence_num)
        sum_x = sum(data[0] for data in self.all_plot_data)
        count = len(self.all_plot_data)
        avg_x = float(sum_x) / count

        # Use a fixed range for Y around 0, and the full X range
        range_x = self.x_data_max - self.x_data_min
        # Define a nominal Y range, e.g., from -2 to 2 meters, or based on stat_spec
        # Let's make it dynamic based on stat_spec, ensuring 0 is in the middle.
        current_spec = 1.0
        if hasattr(self, 'criteria_data') and self.criteria_data:
            try:
                current_spec = float(self.criteria_data[0]['spec_value'].get())
            except ValueError:
                current_spec = 1.0
        y_nominal_range = max(current_spec * 1.5, 2.0) # At least 2.0 if spec is very small

        self.current_x_min = avg_x - range_x / 2.0
        self.current_x_max = avg_x + range_x / 2.0
        self.current_y_min = -y_nominal_range
        self.current_y_max = y_nominal_range

        self._draw_graph()
        self.update_results_window("Graph centered around nominal Y (0) and average Shotpoint (%.0f)." % avg_x)


    def _clear_tooltip(self):
        """Deletes the currently displayed tooltip from the canvas."""
        if self.tooltip_id:
            for item_id in self.tooltip_id:
                self.plot_canvas.delete(item_id)
            self.tooltip_id = None

    def _clear_highlight_ring(self):
        """Deletes the currently displayed highlight ring from the canvas."""
        if self.highlight_ring_id:
            self.plot_canvas.delete(self.highlight_ring_id)
            self.highlight_ring_id = None

    def _check_point_click(self, click_x, click_y, tolerance=10):
        """Checks if a click was near a data point and reports it with a tooltip and highlight ring."""
        self._clear_tooltip() # Clear any existing tooltip
        self._clear_highlight_ring() # Clear any existing highlight ring

        # Find all data points within a small rectangle around the click
        items_at_click = self.plot_canvas.find_overlapping(click_x - tolerance, click_y - tolerance,
                                                           click_x + tolerance, click_y + tolerance)

        clicked_data_point_info = None
        clicked_item_id = None # Store the actual item ID clicked
        for item_id in items_at_click:
            # Check if the item_id is a data point and is in our map
            if item_id in self.canvas_point_data_map:
                clicked_data_point_info = self.canvas_point_data_map[item_id]
                clicked_item_id = item_id # Store the ID
                break # Found a data point, take the first one

        if clicked_data_point_info and clicked_item_id:
            # Unpack the 4-tuple: (sp_no, stat_value_abs, original_stat_value, sequence_num)
            sp_no, stat_value_abs, original_stat_value, sequence_num = clicked_data_point_info
            # Get current stat name from first criteria
            current_stat = "Radial"
            if hasattr(self, 'criteria_data') and self.criteria_data:
                current_stat = self.criteria_data[0]['stat_for_criteria'].get()
            tooltip_text = "SP: %d (Seq: %d)\n%s: %.2f m" % (sp_no, sequence_num, current_stat, original_stat_value)

            # Get the exact canvas coordinates of the clicked point from the canvas
            x1_oval, y1_oval, x2_oval, y2_oval = self.plot_canvas.coords(clicked_item_id)
            px = (x1_oval + x2_oval) / 2.0 # Center X of the drawn oval
            py = (y1_oval + y2_oval) / 2.0 # Center Y of the drawn oval

            # Draw tooltip text with a background rectangle
            point_radius = 3 # Needs to match the radius used in _draw_graph
            text_x = px + point_radius + 5 # Increased offset
            text_y = py + point_radius + 5 # Increased offset

            # Create text item first to get its bounding box
            text_id = self.plot_canvas.create_text(text_x, text_y, text=tooltip_text,
                                                   fill="black", anchor="nw", font=("TkDefaultFont", 9))
            bbox = self.plot_canvas.bbox(text_id) # (x1, y1, x2, y2)

            # Create rectangle behind the text
            rect_id = self.plot_canvas.create_rectangle(bbox[0]-2, bbox[1]-2, bbox[2]+2, bbox[3]+2,
                                                        fill="lightyellow", outline="gray", tags="tooltip_bg")
            self.plot_canvas.tag_lower(rect_id, text_id) # Place rectangle behind text

            self.tooltip_id = [text_id, rect_id] # Store both IDs for easy deletion

            # Draw highlight ring
            ring_radius = 7 # Increased radius to be more visible around the point
            self.highlight_ring_id = self.plot_canvas.create_oval(px - ring_radius, py - ring_radius,
                                                                  px + ring_radius, py + ring_radius,
                                                                  outline="yellow", width=2, tags="highlight_ring")


            self.update_results_window("Clicked Point: Shotpoint %d (Seq: %d), %s: %.2f meters" % (sp_no, sequence_num, current_stat, original_stat_value))
            # Removed: self.results_notebook.select(self.text_results_frame) # No longer switch tabs automatically

    def _reset_zoom(self):
        """This method is now aliased to _center_full_view. Kept for backward compatibility if any internal calls exist."""
        self._center_full_view()

    def _data_to_canvas_x(self, x_data):
        """Converts data X-coordinate to canvas X-pixel."""
        canvas_width = self.plot_canvas.winfo_width() - 80 # Account for padding/margins
        if canvas_width <= 0 or (self.current_x_max - self.current_x_min) == 0: return 0
        return 40 + (x_data - self.current_x_min) / (self.current_x_max - self.current_x_min) * canvas_width

    def _data_to_canvas_y(self, y_data):
        """Converts data Y-coordinate to canvas Y-pixel (inverted for Tkinter)."""
        canvas_height = self.plot_canvas.winfo_height() - 60 # Account for padding/margins
        if canvas_height <= 0 or (self.current_y_max - self.current_y_min) == 0: return canvas_height + 30
        return (canvas_height + 30) - (y_data - self.current_y_min) / (self.current_y_max - self.current_y_min) * canvas_height

    def _canvas_to_data_x(self, x_pixel):
        """Converts canvas X-pixel to data X-coordinate."""
        canvas_width = self.plot_canvas.winfo_width() - 80
        if canvas_width <= 0: return self.current_x_min
        return self.current_x_min + (float(x_pixel) - 40) / canvas_width * (self.current_x_max - self.current_x_min)

    def _canvas_to_data_y(self, y_pixel):
        """Converts canvas Y-pixel to data Y-coordinate (inverted for Tkinter)."""
        canvas_height = self.plot_canvas.winfo_height() - 60
        if canvas_height <= 0: return self.current_y_min
        return self.current_y_min + (float(canvas_height + 30 - y_pixel)) / canvas_height * (self.current_y_max - self.current_y_min)

    def _draw_graph(self):
        """Draws all elements on the Tkinter canvas."""
        self.plot_canvas.delete("all") # Clear canvas

        # Ensure canvas has valid dimensions before drawing
        canvas_width = self.plot_canvas.winfo_width()
        canvas_height = self.plot_canvas.winfo_height()

        # If canvas dimensions are not yet available, schedule redraw
        if canvas_width == 1 or canvas_height == 1: # Default size before actual layout
            self.master.after(100, self._draw_graph) # Try again after 100ms
            return

        if not self.all_plot_data:
            self.plot_canvas.create_text(canvas_width/2, canvas_height/2,
                                         text="No data to plot.", fill="black", font=("TkDefaultFont", 12))
            return

        # Define margins/padding for axes
        left_margin = 60
        bottom_margin = 40
        right_margin = 20
        top_margin = 20

        plot_area_width = canvas_width - left_margin - right_margin
        plot_area_height = canvas_height - top_margin - bottom_margin

        if plot_area_width <= 0 or plot_area_height <= 0:
            # Canvas is too small, or layout issue persists. Draw a message.
            self.plot_canvas.create_text(canvas_width/2, canvas_height/2,
                                         text="Graph area too small to plot.", fill="black", font=("TkDefaultFont", 10))
            return

        # Draw X-axis
        self.plot_canvas.create_line(left_margin, canvas_height - bottom_margin,
                                     canvas_width - right_margin, canvas_height - bottom_margin,
                                     fill="black", width=2)
        # Draw Y-axis
        self.plot_canvas.create_line(left_margin, canvas_height - bottom_margin,
                                     left_margin, top_margin,
                                     fill="black", width=2)

        # Draw axis labels - need to get current stat from first criteria for backward compatibility
        current_stat = "Radial"
        if hasattr(self, 'criteria_data') and self.criteria_data:
            current_stat = self.criteria_data[0]['stat_for_criteria'].get()
        
        self.plot_canvas.create_text(canvas_width / 2, canvas_height - 10,
                                     text="Shotpoint Number", fill="black", font=("TkDefaultFont", 10))
        self.plot_canvas.create_text(20, canvas_height / 2,
                                     text="%s (meters)" % current_stat, fill="black",
                                     font=("TkDefaultFont", 10), angle=90)
        self.plot_canvas.create_text(canvas_width / 2, 10,
                                     text="%s Deviation vs. Shotpoint" % current_stat,
                                     fill="black", font=("TkDefaultFont", 12, "bold"))

        # Calculate Max, Min, Avg for display
        # all_plot_data stores (sp_no, stat_value_abs, original_stat_value, sequence_num)
        y_values_for_stats = [data[1] for data in self.all_plot_data] # Absolute values
        max_val = max(y_values_for_stats) if y_values_for_stats else 0.0
        min_val = min(y_values_for_stats) if y_values_for_stats else 0.0
        avg_val = sum(y_values_for_stats) / len(y_values_for_stats) if y_values_for_stats else 0.0

        # Display Max, Min, Avg in top-left
        stats_text = "Max: %.2f m\nMin: %.2f m\nAvg: %.2f m" % (max_val, min_val, avg_val)
        self.plot_canvas.create_text(left_margin + 5, top_margin + 5, text=stats_text,
                                     fill="black", anchor="nw", font=("TkDefaultFont", 9))


        # Calculate scaling factors for the current view
        x_scale = float(plot_area_width) / (self.current_x_max - self.current_x_min)
        y_scale = float(plot_area_height) / (self.current_y_max - self.current_y_min)

        # Draw X-axis ticks and labels
        num_x_ticks = 5
        x_tick_interval = (self.current_x_max - self.current_x_min) / float(num_x_ticks - 1)
        for i in range(num_x_ticks):
            x_val = self.current_x_min + i * x_tick_interval
            px = left_margin + (x_val - self.current_x_min) * x_scale
            self.plot_canvas.create_line(px, canvas_height - bottom_margin, px, canvas_height - bottom_margin + 5, fill="black")
            self.plot_canvas.create_text(px, canvas_height - bottom_margin + 15, text="%d" % x_val, fill="black", font=("TkDefaultFont", 8))
            # Grid line
            self.plot_canvas.create_line(px, canvas_height - bottom_margin, px, top_margin, fill="gray", dash=(2,2), tags="grid")

        # Draw Y-axis ticks and labels
        num_y_ticks = 5
        y_tick_interval = (self.current_y_max - self.current_y_min) / float(num_y_ticks - 1)
        for i in range(num_y_ticks):
            y_val = self.current_y_min + i * y_tick_interval
            py = (canvas_height - bottom_margin) - (y_val - self.current_y_min) * y_scale
            self.plot_canvas.create_line(left_margin, py, left_margin - 5, py, fill="black")
            self.plot_canvas.create_text(left_margin - 20, py, text="%.1f" % y_val, fill="black", font=("TkDefaultFont", 8))
            # Grid line
            self.plot_canvas.create_line(left_margin, py, canvas_width - right_margin, py, fill="gray", dash=(2,2), tags="grid")

        # Draw Stat Spec line - get spec value from first criteria
        current_spec = 1.0
        if hasattr(self, 'criteria_data') and self.criteria_data:
            try:
                current_spec = float(self.criteria_data[0]['spec_value'].get())
            except ValueError:
                current_spec = 1.0
        
        stat_spec_y_canvas = (canvas_height - bottom_margin) - (current_spec - self.current_y_min) * y_scale
        if top_margin < stat_spec_y_canvas < (canvas_height - bottom_margin):
            self.plot_canvas.create_line(left_margin, stat_spec_y_canvas,
                                         canvas_width - right_margin, stat_spec_y_canvas,
                                         fill="blue", width=2, dash=(4, 2), tags="spec_line")
            self.plot_canvas.create_text(canvas_width - right_margin - 50, stat_spec_y_canvas - 10,
                                         text="Stat Spec", fill="blue", anchor="e", font=("TkDefaultFont", 8))


        # Clear the old map before redrawing points
        self.canvas_point_data_map = {}
        self.sequence_to_color_index = {} # Reset sequence color mapping for new plot
        self.next_color_index = 0

        # Sort data for consistent color assignment based on sequence number
        # Although the prompt implies order by sequence, it's better to assign colors based on unique sequences encountered.
        # Let's get unique sequence numbers and sort them to ensure consistent color mapping
        unique_sequences = sorted(list(set(data[3] for data in self.all_plot_data)))
        for i, seq in enumerate(unique_sequences):
            self.sequence_to_color_index[seq] = i

        # Draw data points
        point_radius = 3
        # all_plot_data stores (sp_no, stat_value_abs, original_stat_value, sequence_num)
        for sp_no, stat_value_abs, original_stat_value, sequence_num in self.all_plot_data:
            # Check if point is within current view
            if not (self.current_x_min <= sp_no <= self.current_x_max and
                    self.current_y_min <= stat_value_abs <= self.current_y_max):
                continue

            px = left_margin + (sp_no - self.current_x_min) * x_scale
            py = (canvas_height - bottom_margin) - (stat_value_abs - self.current_y_min) * y_scale

            color = 'red' # Default to red for failure
            if abs(original_stat_value) <= current_spec:
                # Assign color based on sequence number for passing points
                color_idx = self.sequence_to_color_index.get(sequence_num, 0) # Get assigned index, default to 0
                color = self.sequence_colors[color_idx % len(self.sequence_colors)] # Cycle through colors


            # Create oval for the point and store its data in the map (now including sequence_num)
            point_id = self.plot_canvas.create_oval(px - point_radius, py - point_radius,
                                                    px + point_radius, py + point_radius,
                                                    fill=color, outline=color, tags="data_point")
            self.canvas_point_data_map[point_id] = (sp_no, stat_value_abs, original_stat_value, sequence_num)

        # Add interaction notes to top-right
        interaction_note_y_offset = top_margin + 5 # Initial Y for the first line
        self.plot_canvas.create_text(canvas_width - right_margin - 5, interaction_note_y_offset,
                                     text="Hold right click to Pan", fill="black", anchor="ne", font=("TkDefaultFont", 8))
        self.plot_canvas.create_text(canvas_width - right_margin - 5, interaction_note_y_offset + 13, # Offset for second line
                                     text="Mouse Scroll to zoom in/out", fill="black", anchor="ne", font=("TkDefaultFont", 8))


    def browse_nav_qc_dir(self):
        """Opens a directory selection dialog for Nav_Line_QC folder."""
        directory = tkFileDialog.askdirectory(initialdir=self.nav_line_qc_dir_var.get())
        if directory:
            self.nav_line_qc_dir_var.set(directory)

    def _load_initial_config_path(self):
        """Loads the path of the last used config file from the default config file."""
        config = ConfigParser.RawConfigParser()
        if os.path.exists(self.default_config_filepath):
            try:
                config.read(self.default_config_filepath)
                if config.has_section('Settings') and config.has_option('Settings', 'last_used_config_path'):
                    last_path = config.get('Settings', 'last_used_config_path')
                    if os.path.exists(last_path):
                        self.config_name_var.set(last_path)
                        self.update_results_window("Last used config path loaded: %s" % last_path)
                    else:
                        self.update_results_window("Last used config file not found: %s. Using default." % last_path)
                else:
                    self.update_results_window("Default config file exists but no last_used_config_path found. Using default.")
            except Exception as e:
                self.update_results_window("Error reading default config file for last path: %s. Using default." % e)
        else:
            self.update_results_window("Default config file not found. Using default config path.")


    def save_config(self):
        """Saves current GUI selections and window size to a .xcfg file."""
        config_file = self.config_name_var.get()
        if not config_file:
            self.update_results_window("Error: Configuration file path cannot be empty.", clear=True)
            return

        config = ConfigParser.RawConfigParser()
        # If the file exists, read it first to preserve other sections/options if any
        if os.path.exists(config_file):
            config.read(config_file)

        if not config.has_section('Settings'):
            config.add_section('Settings')

        config.set('Settings', 'nav_line_qc_dir', self.nav_line_qc_dir_var.get())
        config.set('Settings', 'num_criteria', self.num_criteria_var.get())
        config.set('Settings', 'sequences', self.sequences_var.get())

        # Save dynamic criteria data
        for i, criteria_vars in enumerate(self.criteria_data):
            config.set('Settings', 'criteria_%d_pass_fail' % i, criteria_vars['pass_fail_criteria'].get())
            config.set('Settings', 'criteria_%d_value' % i, criteria_vars['criteria_value'].get())
            config.set('Settings', 'criteria_%d_stat' % i, criteria_vars['stat_for_criteria'].get())
            config.set('Settings', 'criteria_%d_spec' % i, criteria_vars['spec_value'].get())
            config.set('Settings', 'criteria_%d_include' % i, str(criteria_vars['include_in_verdict'].get()))

        # Save dynamic excluded shotpoints
        # Store as a comma-separated string of key:value pairs or similar.
        # Simplest: a single string in config file, parsing on load.
        excluded_sps_str_list = []
        for seq_num, var in self.excluded_sp_vars_by_sequence.items():
            excluded_sps_str_list.append("%s:%s" % (seq_num, var.get()))
        config.set('Settings', 'excluded_shotpoints_by_sequence', ",".join(excluded_sps_str_list))


        # Save window geometry
        geometry = self.master.geometry()
        config.set('Settings', 'window_geometry', geometry)

        try:
            with open(config_file, 'wb') as configfile:
                config.write(configfile)
            self.update_results_window("Configuration saved to: %s" % config_file, clear=True)

            # Also update the default config file with the path of the current config
            default_config = ConfigParser.RawConfigParser()
            if os.path.exists(self.default_config_filepath):
                default_config.read(self.default_config_filepath)
            if not default_config.has_section('Settings'):
                default_config.add_section('Settings')
            default_config.set('Settings', 'last_used_config_path', config_file)
            with open(self.default_config_filepath, 'wb') as f:
                default_config.write(f)

        except Exception as e:
            self.update_results_window("Error saving configuration: %s" % e, clear=True)

    def load_config(self, browse=False, initial_load=False):
        """Loads GUI selections and window size from a .xcfg file.
           If browse is True, opens a file dialog.
           If initial_load is True, it's the first load on startup, suppress some messages.
        """
        config_file_to_load = self.config_name_var.get()

        if browse:
            selected_file = tkFileDialog.askopenfilename(
                initialdir=os.path.dirname(config_file_to_load) if os.path.exists(os.path.dirname(config_file_to_load)) else self.default_config_dir,
                filetypes=[("x4D Config Files", "*.xcfg"), ("All Files", "*.*")]
            )
            if selected_file:
                config_file_to_load = selected_file
                self.config_name_var.set(config_file_to_load) # Update the entry field
            else:
                if not initial_load: # Don't show "Load cancelled" on initial startup if no file is selected
                    self.update_results_window("Configuration load cancelled.")
                return

        if not os.path.exists(config_file_to_load):
            if not initial_load:
                self.update_results_window("Configuration file not found: %s. Please check the path or browse for it." % config_file_to_load, clear=True)
            return

        config = ConfigParser.RawConfigParser()
        try:
            config.read(config_file_to_load)
            if config.has_section('Settings'):
                self.nav_line_qc_dir_var.set(config.get('Settings', 'nav_line_qc_dir'))
                
                # Load number of criteria
                if config.has_option('Settings', 'num_criteria'):
                    self.num_criteria_var.set(config.get('Settings', 'num_criteria'))
                    # Update criteria entries based on loaded number
                    self._update_criteria_entries()
                    
                    # Load dynamic criteria data
                    for i, criteria_vars in enumerate(self.criteria_data):
                        if config.has_option('Settings', 'criteria_%d_pass_fail' % i):
                            criteria_vars['pass_fail_criteria'].set(config.get('Settings', 'criteria_%d_pass_fail' % i))
                        if config.has_option('Settings', 'criteria_%d_value' % i):
                            criteria_vars['criteria_value'].set(config.get('Settings', 'criteria_%d_value' % i))
                        if config.has_option('Settings', 'criteria_%d_stat' % i):
                            criteria_vars['stat_for_criteria'].set(config.get('Settings', 'criteria_%d_stat' % i))
                        if config.has_option('Settings', 'criteria_%d_spec' % i):
                            criteria_vars['spec_value'].set(config.get('Settings', 'criteria_%d_spec' % i))
                        if config.has_option('Settings', 'criteria_%d_include' % i):
                            include_val = config.get('Settings', 'criteria_%d_include' % i).lower()
                            criteria_vars['include_in_verdict'].set(include_val in ('true', '1', 'yes'))

                # Load sequences first, which triggers _update_excluded_sp_entries
                sequences_str = config.get('Settings', 'sequences')
                self.sequences_var.set(sequences_str)
                # Store excluded SPs temporarily to be applied after widgets are created by trace
                self._loaded_excluded_sps = {}
                if config.has_option('Settings', 'excluded_shotpoints_by_sequence'):
                    excluded_sps_raw = config.get('Settings', 'excluded_shotpoints_by_sequence')
                    pairs = [p.strip() for p in excluded_sps_raw.split(',') if p.strip()]
                    for pair in pairs:
                        if ':' in pair:
                            try:
                                seq_s, sp_s = pair.split(':', 1)
                                self._loaded_excluded_sps[int(seq_s)] = sp_s
                            except ValueError:
                                self.update_results_window("Warning: Could not parse excluded shotpoint pair: %s" % pair)
                # Calling _update_excluded_sp_entries again after sequences are set to apply loaded values
                self._update_excluded_sp_entries()

                # Load window geometry
                geometry = config.get('Settings', 'window_geometry')
                if geometry:
                    self.master.geometry(geometry)

                self.update_results_window("Configuration loaded from: %s" % config_file_to_load, clear=True)

                # After successful load, update the last_used_config_path in the default config file
                default_config = ConfigParser.RawConfigParser()
                if os.path.exists(self.default_config_filepath):
                    default_config.read(self.default_config_filepath)
                if not default_config.has_section('Settings'):
                    default_config.add_section('Settings')
                default_config.set('Settings', 'last_used_config_path', config_file_to_load)
                with open(self.default_config_filepath, 'wb') as f:
                    default_config.write(f)

            else:
                self.update_results_window("Configuration file is empty or malformed: %s" % config_file_to_load, clear=True)
        except Exception as e:
            self.update_results_window("Error loading configuration: %s" % e, clear=True)

    def on_closing(self):
        """Called when the window is closed, saves config before destroying."""
        self.save_config() # Save current settings and update last_used_config_path
        self.master.destroy()

    def update_results_window(self, message, clear=False, tag=None):
        """Appends a message to the results text area."""
        if clear:
            self.results_text.delete(1.0, tk.END)
        self.results_text.insert(tk.END, message + "\n", tag)
        self.results_text.see(tk.END) # Scroll to the end

    def parse_shotpoint_ranges(self, range_str):
        """
        Parses a comma-separated string of shotpoint ranges (e.g., "1-10, 20-25").
        Returns a set of individual shotpoint numbers.
        """
        excluded_sps = set()
        ranges = [r.strip() for r in range_str.split(',') if r.strip()]
        for r in ranges:
            if '-' in r:
                try:
                    # Support both incrementing (e.g., 1-10) and decrementing (e.g., 10-1)
                    parts = r.split('-')
                    if len(parts) != 2:
                        raise ValueError
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                    lo = start if start <= end else end
                    hi = end if start <= end else start
                    excluded_sps.update(range(lo, hi + 1))
                except ValueError:
                    self.update_results_window("Warning: Invalid shotpoint range format: %s. Skipping." % r)
            else:
                try:
                    excluded_sps.add(int(r))
                except ValueError:
                    self.update_results_window("Warning: Invalid single shotpoint format: %s. Skipping." % r)
        return excluded_sps

    def get_sequence_files(self, nav_qc_dir, sequences):
        """
        Finds relevant data files within the Nav_Line_QC directory for given sequences.
        Expected filename formats (in order of priority):
        Primary patterns:
        - "535561113309.a3309_source_pos_vs_source_preplot_pos" 
        - "535561113309.b3309_source_pos_vs_source_preplot_pos"
        - "535561113309.c3309_source_pos_vs_source_preplot_pos"
        (Supports any single letter prefix: .a, .b, .c, etc.)
        
        Fallback patterns (when no letter prefix exists, must contain "source_pos_vs_source_preplot_pos"):
        - "535561113309_source_pos_vs_source_preplot_pos" (extracts 3309 from last 4 digits)
        - "535561113309.source_pos_vs_source_preplot_pos" (extracts 3309 from last 4 digits)
        """
        found_files = {} # {sequence_num: [filepath1, filepath2]}
        target_sequences = set(sequences)
        
        print("DEBUG: Searching in directory: %s" % nav_qc_dir)
        print("DEBUG: Target sequences: %s" % target_sequences)

        if not os.path.isdir(nav_qc_dir):
            print("DEBUG: Directory does not exist: %s" % nav_qc_dir)
            self.update_results_window("Error: Nav_Line_QC directory not found: %s" % nav_qc_dir)
            return {}

        # List all directories in the Nav_Line_QC directory
        all_folders = os.listdir(nav_qc_dir)
        print("DEBUG: All folders found: %s" % all_folders)
        
        for seq_folder in all_folders:
            full_seq_folder_path = os.path.join(nav_qc_dir, seq_folder)
            if os.path.isdir(full_seq_folder_path):
                print("DEBUG: Checking folder: %s" % seq_folder)
                # Check if the folder name is a valid sequence number and in our target list
                try:
                    folder_seq_num = int(seq_folder)
                    print("DEBUG: Folder %s is numeric sequence: %d" % (seq_folder, folder_seq_num))
                    if folder_seq_num not in target_sequences:
                        print("DEBUG: Sequence %d not in target list, skipping" % folder_seq_num)
                        continue
                    print("DEBUG: Processing sequence folder: %d" % folder_seq_num)
                except ValueError:
                    print("DEBUG: Folder %s is not numeric, skipping" % seq_folder)
                    continue # Not a numeric sequence folder

                all_files = os.listdir(full_seq_folder_path)
                print("DEBUG: Files in folder %s: %s" % (folder_seq_num, all_files))
                
                for filename in all_files:
                    print("DEBUG: Checking file: %s" % filename)
                    file_seq_num = None
                    detection_method = None
                    
                    # Primary pattern: Extract sequence number from filename like "535561113309.a3309_..." or "535561113309.b3309_..."
                    # Supports any letter prefix (.a, .b, .c, etc.)
                    match = re.search(r'\.([a-zA-Z])(\d+)_', filename)
                    if match:
                        letter_prefix = match.group(1)
                        file_seq_num = int(match.group(2))
                        detection_method = "prefix pattern (.%s%d_)" % (letter_prefix, file_seq_num)
                        print("DEBUG: File %s matches prefix pattern - prefix: %s, sequence: %d" % (filename, letter_prefix, file_seq_num))
                    else:
                        # Fallback pattern: Extract last 4 digits before first "." or "_" 
                        # BUT only if filename contains "source_pos_vs_source_preplot_pos"
                        # For files like "535561113309_source_pos_vs_source_preplot_pos" or "535561113309.source_pos_vs_source_preplot_pos"
                        if "source_pos_vs_source_preplot_pos" in filename:
                            fallback_match = re.match(r'.*?(\d{4,})[\._]', filename)
                            if fallback_match:
                                # Extract the full number and take the last 4 digits
                                full_number = fallback_match.group(1)
                                if len(full_number) >= 4:
                                    file_seq_num = int(full_number[-4:])  # Last 4 digits
                                    detection_method = "fallback pattern (last 4 digits of %s)" % full_number
                                    print("DEBUG: File %s matches fallback pattern - extracted sequence: %d from number: %s" % (filename, file_seq_num, full_number))
                                else:
                                    print("DEBUG: File %s fallback match too short: %s" % (filename, full_number))
                            else:
                                print("DEBUG: File %s contains required string but no number pattern found" % filename)
                        else:
                            print("DEBUG: File %s doesn't match any pattern (missing 'source_pos_vs_source_preplot_pos')" % filename)
                    
                    # Process the file if we found a sequence number
                    if file_seq_num is not None:
                        if file_seq_num == folder_seq_num: # Ensure filename sequence matches folder sequence
                            filepath = os.path.join(full_seq_folder_path, filename)
                            if os.path.isfile(filepath):
                                if file_seq_num not in found_files:
                                    found_files[file_seq_num] = []
                                found_files[file_seq_num].append(filepath)
                                print("Found QC file: %s (sequence: %d, detection: %s)" % (filename, file_seq_num, detection_method))
                            else:
                                print("DEBUG: %s is not a file" % filepath)
                        else:
                            print("DEBUG: File sequence %d doesn't match folder sequence %d (detection: %s)" % (file_seq_num, folder_seq_num, detection_method))
        return found_files

    def parse_file_data(self, filepath, stat_to_check):
        """
        Parses the content of a single data file and extracts relevant columns.
        Returns a list of dictionaries, each representing a shotpoint's data.
        """
        data = []
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()

            # Find the header line to determine column indices
            header_line_idx = -1
            for i, line in enumerate(lines):
                if "Pos" in line and "Inline" in line and "Crossline" in line and "Radial" in line:
                    header_line_idx = i
                    break

            if header_line_idx == -1:
                self.update_results_window("Error: Could not find header line in file: %s" % filepath)
                return []

            # Parse the header more carefully to find source pos coordinates
            header_parts = lines[header_line_idx].strip().split()
            col_indices = {}
            
            # Find column positions for basic required columns
            for i, part in enumerate(header_parts):
                if part == "Pos":
                    col_indices["Pos no"] = i
                elif part == "Inline":
                    col_indices["Inline"] = i
                elif part == "Crossline":
                    col_indices["Crossline"] = i
                elif part == "Radial":
                    col_indices["Radial"] = i

            # Find North and East columns - we want the ones associated with "source pos"
            # Look for the pattern where we have North and East columns after seeing source pos indicators
            north_columns = []
            east_columns = []
            for i, part in enumerate(header_parts):
                if part == "North":
                    north_columns.append(i)
                elif part == "East":
                    east_columns.append(i)
            
            # If we have multiple North/East columns, assume the second set is for source pos
            # (first set would be for Source Preplot Pos)
            if len(north_columns) >= 2 and len(east_columns) >= 2:
                col_indices["Source North"] = north_columns[1]  # Second North column
                col_indices["Source East"] = east_columns[1]    # Second East column
            elif len(north_columns) >= 1 and len(east_columns) >= 1:
                # Only one set found, use them
                col_indices["Source North"] = north_columns[0]
                col_indices["Source East"] = east_columns[0]

            # Required columns for basic functionality
            required_cols = ["Pos no", "Inline", "Crossline", "Radial"]
            if not all(k in col_indices for k in required_cols):
                self.update_results_window("Error: Missing required columns (Pos no, Inline, Crossline, Radial) in file: %s" % filepath)
                return []

            # Parse data lines
            for line in lines[header_line_idx + 2:]: # Skip header and separator line
                parts = line.strip().split()
                if len(parts) > max(col_indices.values()): # Ensure enough columns exist
                    try:
                        sp_no = int(parts[col_indices["Pos no"]])
                        inline_val = float(parts[col_indices["Inline"]])
                        crossline_val = float(parts[col_indices["Crossline"]])
                        radial_val = float(parts[col_indices["Radial"]])

                        sp_data = {
                            "Pos no": sp_no,
                            "Inline": inline_val,
                            "Crossline": crossline_val,
                            "Radial": radial_val
                        }
                        
                        # Add source position coordinates if available
                        if "Source North" in col_indices:
                            sp_data["Source North"] = float(parts[col_indices["Source North"]])
                        if "Source East" in col_indices:
                            sp_data["Source East"] = float(parts[col_indices["Source East"]])

                        data.append(sp_data)
                    except (ValueError, IndexError):
                        # Skip lines that don't parse correctly (e.g., blank lines, footers)
                        continue
        except Exception as e:
            self.update_results_window("Error reading or parsing file %s: %s" % (filepath, e))
        return data

    def plot_results(self, all_shotpoints_data_for_plotting, stat_to_check, stat_spec):
        """Prepares data and calls _draw_graph to plot on the Tkinter canvas."""
        self.all_plot_data = [] # This will now hold all data for plotting
        x_values = []
        y_values = []

        # all_shotpoints_data_for_plotting contains dictionaries with 'Pos no', 'Inline', 'Crossline', 'Radial', 'Sequence'
        for sp_data in all_shotpoints_data_for_plotting:
            sp_no = sp_data["Pos no"]
            stat_value = sp_data.get(stat_to_check)
            sequence_num = sp_data.get("Sequence") # Get sequence number

            if stat_value is not None and sequence_num is not None:
                x_values.append(sp_no)
                y_values.append(abs(stat_value)) # Plot absolute value for consistency with spec
                # Store (sp_no, abs_val, original_val, sequence_num)
                self.all_plot_data.append((sp_no, abs(stat_value), stat_value, sequence_num))

        if x_values and y_values:
            # Set full data ranges
            self.x_data_min, self.x_data_max = min(x_values), max(x_values)
            self.y_data_min, self.y_data_max = 0, max(y_values) * 1.1 # Start Y from 0, add 10% buffer for max

            # Initialize current view to full data range
            self.current_x_min, self.current_x_max = self.x_data_min, self.x_data_max
            self.current_y_min, self.current_y_max = self.y_data_min, self.y_data_max

            # Adjust Y-axis min/max to include stat_spec if it's outside the data range
            if stat_spec > self.current_y_max:
                self.current_y_max = stat_spec * 1.1
            # Note: current_y_min is already 0, so stat_spec will always be >= it unless stat_spec < 0,
            # which is prevented by validation.

            # Add a small buffer to X-axis if min/max are the same
            if self.current_x_min == self.current_x_max:
                self.current_x_min -= 10
                self.current_x_max += 10
            # Add a small buffer to Y-axis if min/max are the same
            if self.current_y_min == self.current_y_max:
                self.current_y_min = 0
                self.current_y_max = stat_spec * 2 if stat_spec > 0 else 2.0 # Default to 2.0 if spec is 0

        self.plot_canvas.update_idletasks() # Force update of canvas size before drawing
        self._draw_graph()
        # self.results_notebook.select(self.graph_frame) # Removed: No longer switch to graph tab automatically


    def execute_qc(self):
        """Main function to perform the QC checks based on user inputs."""
        self.update_results_window("--- Starting QC Check ---", clear=True)

        # --- 1. Validate Inputs ---
        nav_qc_dir = self.nav_line_qc_dir_var.get()
        if not os.path.isdir(nav_qc_dir):
            self.update_results_window("Error: Nav_Line_QC directory not found or invalid: %s" % nav_qc_dir, tag="fail")
            return

        # Validate criteria data
        if not self.criteria_data:
            self.update_results_window("Error: No Pass/Fail Criteria defined. Please add at least one criteria.", tag="fail")
            return
            
        validated_criteria = []
        for i, criteria_vars in enumerate(self.criteria_data):
            try:
                criteria_value = float(criteria_vars['criteria_value'].get())
                if criteria_value < 0:
                    self.update_results_window("Error: Criteria Value for criteria %d must be a non-negative number." % (i+1), tag="fail")
                    return
                    
                spec_value = float(criteria_vars['spec_value'].get())
                if spec_value < 0:
                    self.update_results_window("Error: Spec Value for criteria %d must be a non-negative number." % (i+1), tag="fail")
                    return
                    
                validated_criteria.append({
                    'pass_fail_criteria': criteria_vars['pass_fail_criteria'].get(),
                    'criteria_value': criteria_value,
                    'stat_for_criteria': criteria_vars['stat_for_criteria'].get(),
                    'spec_value': spec_value,
                    'include_in_verdict': criteria_vars['include_in_verdict'].get()
                })
            except ValueError:
                self.update_results_window("Error: Invalid number format in criteria %d." % (i+1), tag="fail")
                return

        raw_sequences = self.sequences_var.get()
        if not raw_sequences:
            self.update_results_window("Error: Please enter at least one Sequence Number.", tag="fail")
            return
        try:
            sequences = [int(s.strip()) for s in raw_sequences.split(',') if s.strip()]
            if not sequences:
                raise ValueError("No valid sequences found.")
            sequences = sorted(list(set(sequences))) # Ensure unique and sorted
        except ValueError:
            self.update_results_window("Error: Sequence Numbers must be comma-separated integers.", tag="fail")
            return

        # Parse excluded shotpoints for each sequence
        excluded_sps_by_sequence = {} # {seq_num: set_of_excluded_sps}
        all_excluded_sps_for_summary = set() # For display in summary
        for seq_num in sequences:
            sp_string_var = self.excluded_sp_vars_by_sequence.get(seq_num)
            if sp_string_var:
                excluded_set = self.parse_shotpoint_ranges(sp_string_var.get())
                excluded_sps_by_sequence[seq_num] = excluded_set
                all_excluded_sps_for_summary.update(excluded_set)


        self.update_results_window("\n--- Input Summary ---")
        self.update_results_window("Nav_Line_QC Dir: %s" % nav_qc_dir)
        self.update_results_window("Number of Criteria: %d" % len(validated_criteria))
        for i, criteria in enumerate(validated_criteria):
            self.update_results_window("Criteria %d:" % (i+1))
            self.update_results_window("  Pass/Fail Criteria: %s" % criteria['pass_fail_criteria'])
            self.update_results_window("  Criteria Value: %.2f" % criteria['criteria_value'])
            self.update_results_window("  Stat for Criteria: %s" % criteria['stat_for_criteria'])
            self.update_results_window("  Spec Value: %.2f meters" % criteria['spec_value'])
            self.update_results_window("  Include in Overall Verdict: %s" % ("Yes" if criteria['include_in_verdict'] else "No"))
        self.update_results_window("Sequences: %s" % ", ".join(map(str, sequences)))
        if all_excluded_sps_for_summary:
            self.update_results_window("Total Excluded Shotpoints: %s" % ", ".join(map(str, sorted(list(all_excluded_sps_for_summary)))))
        else:
            self.update_results_window("Excluded Shotpoints: None")

        # --- 2. Find Files ---
        self.update_results_window("\n--- Searching for Files ---")
        self.update_results_window("Looking in directory: %s" % nav_qc_dir)
        self.update_results_window("Target sequences: %s" % sequences)
        found_files_by_sequence = self.get_sequence_files(nav_qc_dir, sequences)

        if not found_files_by_sequence:
            self.update_results_window("No files found for the specified sequences in %s." % nav_qc_dir, tag="fail")
            self.update_results_window("Check if sequence folders exist and contain files matching pattern: .{letter}{sequence_number}_", tag="fail")
            return

        all_shotpoints_data_for_statistics = [] # List of dictionaries for valid shotpoints (for overall stats)
        all_shotpoints_data_for_plotting = [] # List of dictionaries for *all* shotpoints (for plotting)
        all_failed_shotpoints_by_criteria = {} # Dictionary mapping criteria index to list of failed shotpoints
        all_included_shotpoints_numbers = [] # List of just shotpoint numbers (for duplicate check)
        processed_file_details = [] # To store details for each file
        
        # Initialize failed shotpoints for each criteria
        for i in range(len(validated_criteria)):
            all_failed_shotpoints_by_criteria[i] = []

        self.update_results_window("\n--- Processing Files ---")
        processed_files_count = 0
        for seq_num in sorted(found_files_by_sequence.keys()):
            self.update_results_window("Processing Sequence %d:" % seq_num)
            current_seq_excluded_sps = excluded_sps_by_sequence.get(seq_num, set()) # Get excluded SPs for THIS sequence

            for filepath in found_files_by_sequence[seq_num]:
                file_basename = os.path.basename(filepath)
                self.update_results_window("  File: %s" % file_basename)
                processed_files_count += 1
                # Parse file data for all stats (pass the first criteria's stat for compatibility)
                primary_stat = validated_criteria[0]['stat_for_criteria'] if validated_criteria else "Radial"
                file_data = self.parse_file_data(filepath, primary_stat)

                current_file_min_sp = float('inf')
                current_file_max_sp = float('-inf')
                current_file_sp_count = 0 # Count of *included* shotpoints for file details

                for sp_data in file_data:
                    sp_no = sp_data["Pos no"]
                    # Add sequence number to sp_data for sorting failed shotpoints later if needed
                    # This also ensures it's available for plotting tooltip
                    sp_data["Sequence"] = seq_num

                    # Always add to data for plotting, regardless of exclusion
                    all_shotpoints_data_for_plotting.append(sp_data)

                    # Check if this shotpoint is excluded for *this specific sequence*
                    if sp_no in current_seq_excluded_sps:
                        continue # Skip excluded shotpoints for statistics

                    all_shotpoints_data_for_statistics.append(sp_data) # Add to total data for statistics
                    all_included_shotpoints_numbers.append(sp_no) # Add for duplicate check

                    # Update min/max/count for current file (only for *included* points)
                    current_file_min_sp = min(current_file_min_sp, sp_no)
                    current_file_max_sp = max(current_file_max_sp, sp_no)
                    current_file_sp_count += 1

                    # Check against each criteria's spec value
                    for criteria_idx, criteria in enumerate(validated_criteria):
                        stat_value = sp_data.get(criteria['stat_for_criteria'])
                        if stat_value is not None and abs(stat_value) > criteria['spec_value']:
                            all_failed_shotpoints_by_criteria[criteria_idx].append(sp_data)

                # Store details for the current file
                if current_file_sp_count > 0:
                    processed_file_details.append({
                        'filepath': filepath,
                        'min_sp': current_file_min_sp,
                        'max_sp': current_file_max_sp,
                        'count_sp': current_file_sp_count
                    })
                    self.update_results_window("    Shotpoint Range (included): %d - %d" % (current_file_min_sp, current_file_max_sp))
                    self.update_results_window("    Number of Shotpoints (included): %d" % current_file_sp_count)
                else:
                    processed_file_details.append({
                        'filepath': filepath,
                        'min_sp': 'N/A',
                        'max_sp': 'N/A',
                        'count_sp': 0
                    })
                    self.update_results_window("    No valid shotpoints found in this file (or all were excluded).")


        self.update_results_window("\nProcessed %d files." % processed_files_count)
        self.update_results_window("Total valid shotpoints (excluding specified ranges): %d" % len(all_shotpoints_data_for_statistics))
        
        # Show failed shotpoints for each criteria
        for criteria_idx, criteria in enumerate(validated_criteria):
            failed_count = len(all_failed_shotpoints_by_criteria[criteria_idx])
            self.update_results_window("Criteria %d - %s (%.2f meters): %d failed shotpoints" % 
                                     (criteria_idx + 1, criteria['stat_for_criteria'], 
                                      criteria['spec_value'], failed_count))

        # --- Check for Duplicate Shotpoints Across Sequences ---
        if len(sequences) > 1:
            self.update_results_window("\n--- Duplicate Shotpoints Across Sequences ---")
            sp_counts = {}
            for sp_no in all_included_shotpoints_numbers:
                sp_counts[sp_no] = sp_counts.get(sp_no, 0) + 1

            duplicates_found = False
            for sp_no, count in sorted(sp_counts.items()):
                if count > 1:
                    self.update_results_window("  Shotpoint %d appears %d times." % (sp_no, count))
                    duplicates_found = True
            if not duplicates_found:
                self.update_results_window("  No duplicate shotpoints found across selected sequences.")
        else:
            self.update_results_window("\n--- Duplicate Shotpoints Across Sequences ---")
            self.update_results_window("  (Duplicate check skipped: only one sequence selected)")


        # --- 3. Determine Pass/Fail Verdict ---
        overall_verdict = "PASS"
        overall_verdict_tag = "pass"
        criteria_results = []

        if not all_shotpoints_data_for_statistics:
            overall_verdict = "FAIL" 
            overall_verdict_tag = "fail"
            criteria_results.append("No valid shotpoints found to perform checks after exclusions.")
        else:
            # Evaluate each criteria
            for criteria_idx, criteria in enumerate(validated_criteria):
                criteria_pass_fail = criteria['pass_fail_criteria']
                criteria_value = criteria['criteria_value']
                stat_for_criteria = criteria['stat_for_criteria']
                spec_value = criteria['spec_value']
                
                failed_shotpoints = all_failed_shotpoints_by_criteria[criteria_idx]
                criteria_verdict = "PASS"
                criteria_reason = ""
                
                if not failed_shotpoints:
                    criteria_verdict = "PASS"
                    criteria_reason = "No shotpoints failed the spec (%.2f meters) for %s" % (spec_value, stat_for_criteria)
                else:
                    if criteria_pass_fail in ("Max % of Failure for whole line", "Max Percentage of Failure for the whole line"):
                        fail_percentage = (float(len(failed_shotpoints)) / len(all_shotpoints_data_for_statistics)) * 100
                        criteria_reason = "Failure Percentage: %.2f%% (Criteria: Max %.2f%%)" % (fail_percentage, criteria_value)
                        if fail_percentage > criteria_value:
                            criteria_verdict = "FAIL"
                    elif criteria_pass_fail == "Average for the whole line":
                        # Average absolute deviation from the spec value must be within ±Criteria Value
                        diffs_sum = 0.0
                        valid_count = 0
                        for sp in all_shotpoints_data_for_statistics:
                            v = sp.get(stat_for_criteria)
                            if v is None:
                                continue
                            diffs_sum += abs(abs(v) - spec_value)
                            valid_count += 1
                        if valid_count > 0:
                            avg_abs_deviation = diffs_sum / valid_count
                            criteria_reason = "Avg |%s - Spec|: %.2f m (Tolerance ≤ %.2f m, Spec %.2f m)" % (stat_for_criteria, avg_abs_deviation, criteria_value, spec_value)
                            if avg_abs_deviation > criteria_value:
                                criteria_verdict = "FAIL"
                        else:
                            criteria_reason = "No valid %s values found" % stat_for_criteria
                    elif criteria_pass_fail == "Max Consecutive Failures":
                        # Count consecutive failures strictly by parsed order (ignore SP increments)
                        all_sps_for_criteria = list(all_shotpoints_data_for_statistics)
                        max_consecutive = 0
                        current_consecutive = 0
                        total_failed_sp = 0

                        for sp_data in all_sps_for_criteria:
                            stat_value = sp_data.get(stat_for_criteria)
                            if stat_value is not None and abs(stat_value) > spec_value:
                                total_failed_sp += 1
                                current_consecutive += 1
                                if current_consecutive > max_consecutive:
                                    max_consecutive = current_consecutive
                            else:
                                current_consecutive = 0

                        # criteria_value is the threshold for consecutive failures
                        criteria_reason = "Max Consecutive Failures: %d (Threshold: %d), Total Failed SP: %d" % (max_consecutive, int(criteria_value), total_failed_sp)
                        if max_consecutive >= criteria_value:
                            criteria_verdict = "FAIL"
                        else:
                            criteria_verdict = "PASS"
                    elif criteria_pass_fail == "Max SP exceeding Absolute Value":
                        # Count shotpoints that exceed the absolute value
                        exceeding_sp_count = 0
                        for sp_data in all_shotpoints_data_for_statistics:
                            stat_value = sp_data.get(stat_for_criteria)
                            if stat_value is not None and abs(stat_value) > criteria_value:
                                exceeding_sp_count += 1
                        
                        criteria_reason = "SP exceeding %.2f: %d (Criteria: Max %d)" % (criteria_value, exceeding_sp_count, int(spec_value))
                        if exceeding_sp_count > spec_value:
                            criteria_verdict = "FAIL"
                
                # Store criteria result
                criteria_results.append({
                    'index': criteria_idx + 1,
                    'criteria': criteria_pass_fail,
                    'stat': stat_for_criteria,
                    'verdict': criteria_verdict,
                    'reason': criteria_reason,
                    'include_in_verdict': criteria['include_in_verdict']
                })
                
                # If any criteria fails and is included in verdict, mark overall as fail
                if criteria_verdict == "FAIL" and criteria['include_in_verdict']:
                    overall_verdict = "FAIL"
                    overall_verdict_tag = "fail"

# --- 4. Display Results ---
        if isinstance(criteria_results, list) and len(criteria_results) > 0 and isinstance(criteria_results[0], dict):
            # Display failed shotpoints for each criteria
            for criteria_idx, criteria in enumerate(validated_criteria):
                failed_shotpoints = all_failed_shotpoints_by_criteria[criteria_idx]
                self.update_results_window("\n--- Failed Shotpoints for Criteria %d (%s, spec: %.2f meters) ---" % 
                                         (criteria_idx + 1, criteria['stat_for_criteria'], criteria['spec_value']))
                if failed_shotpoints:
                    # Sort by sequence number then shotpoint number
                    sorted_failed_sps_output = sorted(failed_shotpoints, key=lambda x: (x.get("Sequence", 0), x["Pos no"]))
                    for sp_data in sorted_failed_sps_output:
                        stat_value = sp_data.get(criteria['stat_for_criteria'])
                        self.update_results_window("  Seq: %d, SP: %d, %s: %.2f" % 
                                                 (sp_data["Sequence"], sp_data["Pos no"], 
                                                  criteria['stat_for_criteria'], stat_value))
                else:
                    self.update_results_window("  None")

            # Display criteria evaluation results
            self.update_results_window("\n--- Criteria Evaluation Results ---")
            for result in criteria_results:
                tag = "pass" if result['verdict'] == "PASS" else "fail"
                include_status = " (included in verdict)" if result['include_in_verdict'] else " (excluded from verdict)"
                self.update_results_window("Criteria %d: %s - %s%s" % 
                                         (result['index'], result['criteria'], result['verdict'], include_status), tag=tag)
                self.update_results_window("  %s" % result['reason'])

            self.update_results_window("\n--- Overall Verdict ---")
            self.update_results_window("Verdict: %s" % overall_verdict, tag=overall_verdict_tag)
            if overall_verdict == "FAIL":
                failed_criteria = [r for r in criteria_results if r['verdict'] == "FAIL" and r['include_in_verdict']]
                if failed_criteria:
                    self.update_results_window("Reason: %d criteria failed (included in verdict)" % len(failed_criteria))
                else:
                    self.update_results_window("Reason: Unknown failure")
            else:
                included_criteria = [r for r in criteria_results if r['include_in_verdict']]
                self.update_results_window("Reason: All %d included criteria passed" % len(included_criteria))
        else:
            # Handle case where criteria_results is just a string (error case)
            self.update_results_window("\n--- Overall Verdict ---")
            self.update_results_window("Verdict: %s" % overall_verdict, tag=overall_verdict_tag)
            if isinstance(criteria_results, list) and len(criteria_results) > 0:
                self.update_results_window("Reason: %s" % criteria_results[0])
            
        self.update_results_window("\n--- QC Check Complete ---")



        # --- Bad SP (based on defined criteria) ---
        try:
            self.reshoots_text.delete('1.0', tk.END)
            
            any_bad_ranges = False
            
            # Process each criteria and show failing ranges
            for criteria_idx, criteria in enumerate(validated_criteria):
                failed_shotpoints = all_failed_shotpoints_by_criteria[criteria_idx]
                
                if failed_shotpoints:
                    any_bad_ranges = True
                    stat_name = criteria['stat_for_criteria']
                    spec_value = criteria['spec_value']
                    criteria_name = criteria['pass_fail_criteria']
                    
                    # Sort failed shotpoints by position
                    sorted_failed_sps = sorted([sp["Pos no"] for sp in failed_shotpoints])
                    
                    # Group consecutive failed shotpoints into ranges
                    ranges = []
                    if sorted_failed_sps:
                        start = sorted_failed_sps[0]
                        end = start
                        
                        for i in range(1, len(sorted_failed_sps)):
                            if sorted_failed_sps[i] == sorted_failed_sps[i-1] + 1 or sorted_failed_sps[i] == sorted_failed_sps[i-1] + 2:
                                # Consecutive or every-other (same source)
                                end = sorted_failed_sps[i]
                            else:
                                # Gap found, close current range and start new one
                                ranges.append((start, end, end - start + 1))
                                start = sorted_failed_sps[i]
                                end = start
                        
                        # Add the last range
                        ranges.append((start, end, end - start + 1))
                    
                    # Display ranges for this criteria
                    self.reshoots_text.insert(tk.END, 'Criteria %d: %s (%.2fm spec) - %d failed SP\n' % 
                                            (criteria_idx + 1, stat_name, spec_value, len(failed_shotpoints)))
                    
                    if ranges:
                        # Failure % is the percent of the whole included line represented by this failing range
                        total_included_sp = float(len(all_shotpoints_data_for_statistics)) if len(all_shotpoints_data_for_statistics) else 1.0
                        fmt_row = "{:>12}  {:>10}  {:>7}  {:>9}\n"
                        self.reshoots_text.insert(tk.END, fmt_row.format('Start SP', 'End SP', 'Count', 'Failure %'))
                        
                        for start, end, count in ranges:
                            if start == end:
                                actual_count = 1
                            else:
                                # Range of shotpoints
                                actual_count = len([sp for sp in sorted_failed_sps if start <= sp <= end])
                            pct = (100.0 * actual_count / total_included_sp) if total_included_sp else 0.0
                            self.reshoots_text.insert(tk.END, "{:>12}  {:>10}  {:>7}  {:>8.1f}%\n".format(start, end, actual_count, pct))
                    
                    self.reshoots_text.insert(tk.END, '\n')
            
            if not any_bad_ranges:
                self.reshoots_text.insert(tk.END, 'No failed shotpoints detected for any criteria\n')
            
            # Show/Hide Failed SP tab depending on presence of bad ranges
            if any_bad_ranges:
                self._show_tab(self.reshoots_frame, "Failed SP's")
            else:
                self._hide_tab(self.reshoots_frame)
                
        except Exception as e:
            self.reshoots_text.delete('1.0', tk.END)
            self.reshoots_text.insert(tk.END, "Failed SP error: %s\n" % e)
        # --- Plot Results on Graph Tab ---
        # Use first criteria for plotting (maintain original behavior)
        if validated_criteria:
            stat_to_check = validated_criteria[0]['stat_for_criteria']
            stat_spec = validated_criteria[0]['spec_value']
        else:
            # Fallback if no criteria defined
            stat_to_check = "Radial"
            stat_spec = 1.0
        
        self.plot_results(all_shotpoints_data_for_plotting, stat_to_check, stat_spec)

    def save_config(self):
        """Save current settings to configuration file."""
        config_path = self.config_name_var.get()
        if not config_path:
            self.update_results_window("Error: No configuration file path specified.", tag="fail")
            return
        
        try:
            config = ConfigParser.ConfigParser()
            
            # Save Sequence QC settings
            config.add_section('SequenceQC')
            config.set('SequenceQC', 'nav_line_qc_dir', self.nav_line_qc_dir_var.get())
            config.set('SequenceQC', 'sequences', self.sequences_var.get())
            config.set('SequenceQC', 'sl_search', self.sl_search_var.get())
            config.set('SequenceQC', 'num_criteria', self.num_criteria_var.get())
            
            # Save criteria data
            for i, criteria_vars in enumerate(self.criteria_data):
                section_name = 'Criteria_%d' % (i + 1)
                config.add_section(section_name)
                config.set(section_name, 'pass_fail_criteria', criteria_vars['pass_fail_criteria'].get())
                config.set(section_name, 'criteria_value', criteria_vars['criteria_value'].get())
                config.set(section_name, 'stat_for_criteria', criteria_vars['stat_for_criteria'].get())
                config.set(section_name, 'spec_value', criteria_vars['spec_value'].get())
                config.set(section_name, 'include_in_verdict', str(criteria_vars['include_in_verdict'].get()))
            
            # Save excluded shotpoints by sequence
            config.add_section('ExcludedShotpoints')
            for seq_num, sp_var in self.excluded_sp_vars_by_sequence.items():
                config.set('ExcludedShotpoints', 'seq_%d' % seq_num, sp_var.get())
            
            # Save Job Stat settings
            config.add_section('JobStat')
            if hasattr(self, 'stat_type_var'):
                config.set('JobStat', 'stat_type', self.stat_type_var.get())
            if hasattr(self, 'range_input_var'):
                config.set('JobStat', 'range_input', self.range_input_var.get())
            
            # Save exclusion zones
            config.add_section('ExclusionZones')
            if hasattr(self, 'exclusion_circles_data'):
                for i, (easting, northing, radius) in enumerate(self.exclusion_circles_data):
                    config.set('ExclusionZones', 'zone_%d' % i, '%f,%f,%f' % (easting, northing, radius))
            
            with open(config_path, 'w') as f:
                config.write(f)
            
            self.update_results_window("Configuration saved to: %s" % config_path)
            
        except Exception as e:
            self.update_results_window("Error saving configuration: %s" % str(e), tag="fail")

    def load_config(self, browse=False, initial_load=False):
        """Load settings from configuration file."""
        if browse:
            try:
                from tkFileDialog import askopenfilename
            except ImportError:
                from tkinter.filedialog import askopenfilename
            config_path = askopenfilename(
                title="Select Configuration File",
                filetypes=[("Configuration files", "*.xcfg"), ("All files", "*.*")],
                initialdir=os.path.dirname(self.config_name_var.get()) if self.config_name_var.get() else self.default_config_dir
            )
            if not config_path:
                return
            self.config_name_var.set(config_path)
        else:
            config_path = self.config_name_var.get()
        
        if not config_path or not os.path.exists(config_path):
            if not initial_load:
                self.update_results_window("Error: Configuration file not found: %s" % config_path, tag="fail")
            return
        
        try:
            config = ConfigParser.ConfigParser()
            config.read(config_path)
            
            # Load Sequence QC settings
            if config.has_section('SequenceQC'):
                if config.has_option('SequenceQC', 'nav_line_qc_dir'):
                    self.nav_line_qc_dir_var.set(config.get('SequenceQC', 'nav_line_qc_dir'))
                if config.has_option('SequenceQC', 'sequences'):
                    self.sequences_var.set(config.get('SequenceQC', 'sequences'))
                if config.has_option('SequenceQC', 'sl_search'):
                    self.sl_search_var.set(config.get('SequenceQC', 'sl_search'))
                if config.has_option('SequenceQC', 'num_criteria'):
                    self.num_criteria_var.set(config.get('SequenceQC', 'num_criteria'))
                    self._update_criteria_entries()
            
            # Load criteria data
            for i, criteria_vars in enumerate(self.criteria_data):
                section_name = 'Criteria_%d' % (i + 1)
                if config.has_section(section_name):
                    if config.has_option(section_name, 'pass_fail_criteria'):
                        criteria_vars['pass_fail_criteria'].set(config.get(section_name, 'pass_fail_criteria'))
                    if config.has_option(section_name, 'criteria_value'):
                        criteria_vars['criteria_value'].set(config.get(section_name, 'criteria_value'))
                    if config.has_option(section_name, 'stat_for_criteria'):
                        criteria_vars['stat_for_criteria'].set(config.get(section_name, 'stat_for_criteria'))
                    if config.has_option(section_name, 'spec_value'):
                        criteria_vars['spec_value'].set(config.get(section_name, 'spec_value'))
                    if config.has_option(section_name, 'include_in_verdict'):
                        criteria_vars['include_in_verdict'].set(config.get(section_name, 'include_in_verdict') == 'True')
            
            # Load excluded shotpoints
            if config.has_section('ExcludedShotpoints'):
                for option in config.options('ExcludedShotpoints'):
                    if option.startswith('seq_'):
                        seq_num = int(option[4:])  # Remove 'seq_' prefix
                        if seq_num in self.excluded_sp_vars_by_sequence:
                            self.excluded_sp_vars_by_sequence[seq_num].set(config.get('ExcludedShotpoints', option))
            
            # Load Job Stat settings
            if config.has_section('JobStat'):
                if hasattr(self, 'stat_type_var') and config.has_option('JobStat', 'stat_type'):
                    self.stat_type_var.set(config.get('JobStat', 'stat_type'))
                if hasattr(self, 'range_input_var') and config.has_option('JobStat', 'range_input'):
                    self.range_input_var.set(config.get('JobStat', 'range_input'))
            
            # Load exclusion zones
            if config.has_section('ExclusionZones'):
                if hasattr(self, 'exclusion_circles_data'):
                    self.exclusion_circles_data = []
                    self.exclusion_circles = []
                    for option in config.options('ExclusionZones'):
                        if option.startswith('zone_'):
                            zone_data = config.get('ExclusionZones', option)
                            try:
                                easting, northing, radius = map(float, zone_data.split(','))
                                self.exclusion_circles_data.append((easting, northing, radius))
                            except ValueError:
                                continue  # Skip malformed zone data
                    
                    # Redraw exclusion zones on map if they exist
                    if self.exclusion_circles_data and hasattr(self, 'map_canvas'):
                        # Schedule redraw for after the GUI is fully loaded
                        self.master.after(100, self.delayed_exclusion_zone_redraw)
                    
                    # Update statistics after loading exclusion zones
                    if hasattr(self, 'map_data_points') and self.map_data_points:
                        self.update_map_statistics()
            
            if not initial_load:
                self.update_results_window("Configuration loaded from: %s" % config_path)
            
        except Exception as e:
            self.update_results_window("Error loading configuration: %s" % str(e), tag="fail")


# --- Main Application Entry Point ---
if __name__ == "__main__":
    root = tk.Tk()
    app = X4DApp(root)
    root.mainloop()