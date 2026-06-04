#!/usr/bin/env python
# Ai assisted Code by RBolisay
import Tkinter as tk
import ttk
import tkFileDialog
import tkMessageBox
import os
import glob
import ConfigParser
import fnmatch
from collections import OrderedDict

# --- Constants ---
APP_NAME = "xDiag - Diagnostic Data Extractor"
CONFIG_EXTENSION = ".xcfg"
DIAG_FILE_PATTERN = "*35_Diag*"
BASE_DIAG_PATH = "/usr/local/trinop/dbase/links/qcfiles/Nav_Line_QC/"
DEFAULT_CONFIG_DIR = "/usr/local/trinop/dbase/links/qcfiles/Misc/xDiag/"
LAST_CONFIG_TRACKER_FILENAME = "last_config.path"

DIAG_TEST_HEADERS = [
    "Shot increment distance",
    "Shot increment time",
    "Bottom Speed",
    "Water Speed",
    "Feather",
    "Smooth Recomputed Position semi-major axis (95%)",
    "Smooth Recomputed Position (non source) variance factor",
    "Smooth Recomputed Position (source) variance factor",
    "Smooth Recomputed Position Acceleration xline",
    "Smooth Recomputed Position Acceleration iline",
    "Network Input position semi-major axis (95%)",
    "Difference Smoothed Reference Position GNSS (xline)",
    "Difference Smoothed Reference Position GNSS (iline)",
    "GNSS error ellipse semi-major axis (95%)",
    "GNSS PDOP",
    "GNSS number of sats",
    "GNSS WGS-84 ellipsoidal height",
    "GNSS external reliability",
    "GPS RB Calculation Mode",
    "Diff range bearing error ellipse semi-major axis (95%)",
    "Diff range bearing PDOP",
    "Diff range bearing number of sats",
    "Network Variance Factor",
    "Network Number of remaining outliers",
    "Network Number of rejected outliers",
    "Network Number of ranges with Std Residual > 1.64",
    "Network Number of ranges with Std Residual > 1.96",
    "Partial Variance factor IRMA",
    "Partial Variance factor Position",
    "Partial Variance factor Baseline",
    "Partial Variance factor Direction",
    "Network Computed Speed of Sound",
    "Network Estimated Acoustic Range bias",
    "CMG standardized residual",
    "CMG pooled estimate of the bias",
    "Baseline standardized residual",
    "Baseline pooled estimate of the bias",
    "Auto-Baseline standardized residual",
    "Auto-Baseline pooled estimate of the bias",
    "Float pos standardized residual (xline)",
    "Float pos standardized residual (iline)",
    "Float pos pooled estimate of the bias (xline)",
    "Float pos pooled estimate of the bias (iline)",
    "Smooth Tracking nodes (streamer) error ellipse semi-major axis (95%)",
    "Smooth Tracking nodes (source) error ellipse semi-major axis (95%)",
    "Smooth Tracking nodes (float) error ellipse semi-major axis (95%)",
    "Smooth Tracking nodes variance factor",
    "Smooth Tracking nodes (streamer) Acceleration xline",
    "Smooth Tracking nodes (source) Acceleration xline",
    "Smooth Tracking nodes (float) Acceleration xline",
    "Smooth Tracking nodes (streamer) Acceleration iline",
    "Smooth Tracking nodes (source) Acceleration iline",
    "Smooth Tracking nodes (float) Acceleration iline",
    "Acceleration source (xline)",
    "Acceleration source (iline)",
    "Streamer Depth",
    "Streamer Depth Acceleration",
    "Streamer Depth Max Interpolation Time",
    "Streamer Depth Non Changing Value",
    "Gun depth",
    "Separation RoC vessel-source-streamer (radial)",
    "Separation vessel-source-streamer (radial)",
    "Separation vessel-source-streamer (xline)",
    "Separation vessel-source-streamer (iline)",
    "Separation source (radial)",
    "Separation source (xline)",
    "Separation gunstring (radial)",
    "Separation gunstring (xline)",
    "Separation gunstring (iline)",
    "Separation gunstring length",
    "Separation streamer (radial)",
    "Separation streamer (xline)",
    "Separation Overall streamer",
    "Separation streamer Front (xline)",
    "Streamer node Cable Shape/Tracking Node Radial Diff",
    "Streamer node Cable Shape/Tracking Node Xtrack Diff",
    "Streamer node Cable Shape Azimuth",
    "Streamer node Cable Shape Azimuth Diff",
    "Streamer node Cable Shape Depth Diff",
    "Average Source Separation (xline)",
    "Average Gun-String Separation (xline)",
    "Average Streamer Separation (xline)",
    "Average Streamer Separation Front (xline)",
    "Average Streamer Separation Middle (xline)",
    "Average Streamer Separation Tail (xline)",
    "Streamer Tension",
    "Streamer TensionMeter Depth",
    "Streamer Stretch",
    "Streamer Number of bad receivers",
    "Streamer segment node distance"
]
STAT_TYPES = ["MIN", "MAX", "AVR"]
DEFAULT_NUM_SEGMENTS = 1

# --- GUI Colors ---
GUI_BACKGROUND_COLOR = "#B4C8E1"      # Blue Aura - User specified
BUTTON_BACKGROUND_COLOR = "#8DA9CC"   # Distinct, slightly darker blue - User specified
BUTTON_ACTIVE_COLOR = "#9FBBDD"       # Lighter shade for button active state
BUTTON_PRESSED_COLOR = "#7C98BB"      # Darker shade for button pressed state
SCROLLBAR_ACTIVE_COLOR = "#C0D4ED"    # Lighter shade for scrollbar active state (derived from GUI_BACKGROUND_COLOR)

TEXT_AREA_COLOR = "#E6F0FA"          # A lighter shade for text background (Unchanged)
BUTTON_TEXT_COLOR = "#000000"         # Black text for buttons (Unchanged)
ENTRY_FIELD_BG_COLOR = "#FFFFFF"      # White for entry fields for readability (Unchanged)
LISTBOX_BG_COLOR = "#FFFFFF"          # (Unchanged)
LISTBOX_FG_COLOR = "#000000"          # (Unchanged)

class DiagExtractorApp:
    def __init__(self, master):
        self.master = master
        master.title(APP_NAME)
        master.configure(bg=GUI_BACKGROUND_COLOR) # Set root window background

        self.config_name_var = tk.StringVar()
        self.sequence_number_var = tk.StringVar()
        self.num_segments_var = tk.StringVar(value=str(DEFAULT_NUM_SEGMENTS))
        self.current_config_filepath = None

        self.segment_frames = []
        self.segment_data_vars = []

        self._apply_styles()
        self._create_widgets()
        self._create_dynamic_segments(DEFAULT_NUM_SEGMENTS, None)

        self._load_last_config_on_startup()

        master.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _apply_styles(self):
        style = ttk.Style()
        style.theme_use('clam') # Using a theme that allows more customization

        # Global style for background of most ttk widgets
        style.configure('.', background=GUI_BACKGROUND_COLOR, foreground='black')
        style.configure('TFrame', background=GUI_BACKGROUND_COLOR)
        style.configure('TLabel', background=GUI_BACKGROUND_COLOR, foreground='black')
        style.configure('TLabelframe', background=GUI_BACKGROUND_COLOR, bordercolor=GUI_BACKGROUND_COLOR)
        style.configure('TLabelframe.Label', background=GUI_BACKGROUND_COLOR, foreground='black')

        # Button styles
        style.configure('TButton', background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR, borderwidth=1)
        style.map('TButton',
                  background=[('active', BUTTON_ACTIVE_COLOR), ('pressed', BUTTON_PRESSED_COLOR)],
                  foreground=[('active', BUTTON_TEXT_COLOR), ('pressed', BUTTON_TEXT_COLOR)])

        # Accent button style (e.g., for the main "Extract Diag" button)
        style.configure('Accent.TButton', font=("Arial", 10, "bold"), background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        style.map('Accent.TButton',
          background=[('active', BUTTON_ACTIVE_COLOR), ('pressed', BUTTON_PRESSED_COLOR)],
          foreground=[('active', BUTTON_TEXT_COLOR), ('pressed', BUTTON_TEXT_COLOR)])

        # Combobox style
        style.configure('TCombobox', fieldbackground=ENTRY_FIELD_BG_COLOR, background=GUI_BACKGROUND_COLOR, foreground='black', arrowcolor='black')
        style.map('TCombobox',
                  fieldbackground=[('readonly', ENTRY_FIELD_BG_COLOR)],
                  selectbackground=[('readonly', GUI_BACKGROUND_COLOR)], # Background of the dropdown list items when selected
                  selectforeground=[('readonly', 'black')])

        # Entry field style (already uses ENTRY_FIELD_BG_COLOR by default for fieldbackground with 'clam')
        style.configure('TEntry', fieldbackground=ENTRY_FIELD_BG_COLOR, foreground='black', insertcolor='black')
        
        # Scrollbar style
        style.configure('TScrollbar', troughcolor=GUI_BACKGROUND_COLOR, background=GUI_BACKGROUND_COLOR, bordercolor=GUI_BACKGROUND_COLOR, arrowcolor='black')
        style.map('TScrollbar', background=[('active', SCROLLBAR_ACTIVE_COLOR)])


    def _get_last_config_tracker_path(self):
        return os.path.join(DEFAULT_CONFIG_DIR, LAST_CONFIG_TRACKER_FILENAME)

    def _write_last_config_path(self, config_filepath_to_store):
        try:
            if not os.path.exists(DEFAULT_CONFIG_DIR):
                os.makedirs(DEFAULT_CONFIG_DIR)
            tracker_file = self._get_last_config_tracker_path()
            with open(tracker_file, 'w') as f:
                f.write(os.path.abspath(config_filepath_to_store))
        except Exception as e:
            print "Warning: Could not write last config path to {}: {}".format(tracker_file, e)

    def _read_last_config_path(self):
        tracker_file = self._get_last_config_tracker_path()
        try:
            if os.path.exists(tracker_file):
                with open(tracker_file, 'r') as f:
                    last_path = f.read().strip()
                    if last_path and os.path.exists(last_path):
                        return last_path
        except Exception as e:
            print "Warning: Could not read last config path from {}: {}".format(tracker_file, e)
        return None

    def _load_last_config_on_startup(self):
        self._startup_load_attempted = None
        last_config_file = self._read_last_config_path()
        if last_config_file:
            print "Attempting to load last used config: {}".format(last_config_file)
            self.load_config(last_config_file)
        else:
            self._startup_load_attempted = True # Mark as attempted if no file to load

    def _on_closing(self):
        config_to_update = None
        if self.current_config_filepath and os.path.exists(self.current_config_filepath):
            config_to_update = self.current_config_filepath
        elif self.config_name_var.get().strip(): # Check if there's a name in the box
            name_in_box = self.config_name_var.get().strip()
            potential_path = ""
            # Check if it's an absolute path or has directory components
            if os.path.isabs(name_in_box) or os.path.dirname(name_in_box):
                potential_path = name_in_box if name_in_box.endswith(CONFIG_EXTENSION) else name_in_box + CONFIG_EXTENSION
            else: # Assume it's a filename for the default directory
                filename = name_in_box if name_in_box.endswith(CONFIG_EXTENSION) else name_in_box + CONFIG_EXTENSION
                potential_path = os.path.join(DEFAULT_CONFIG_DIR, filename)

            if os.path.exists(potential_path): # Only update if this potential path actually exists
                config_to_update = potential_path

        if config_to_update:
            try:
                parser = ConfigParser.ConfigParser()
                config_dir = os.path.dirname(config_to_update)
                if config_dir and not os.path.exists(config_dir) : # Should not happen if config_to_update exists, but good check
                     os.makedirs(config_dir)

                parser.read(config_to_update) # Read existing to preserve other sections/options
                if not parser.has_section('General'):
                    parser.add_section('General')
                parser.set('General', 'window_geometry', self.master.geometry())

                with open(config_to_update, 'w') as configfile:
                    parser.write(configfile)
            except Exception as e:
                print "Error saving window geometry on close to {}: {}".format(config_to_update, e)
        self.master.destroy()

    def _create_widgets(self):
        # Main frame to hold all widgets
        main_frame = ttk.Frame(self.master, padding="10") # Style applied via _apply_styles
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)


        # Application description label
        desc_label = ttk.Label(main_frame, text="Tool for Extracting Data from Diagnostic Files", font=("Arial", 12, "bold"))
        desc_label.grid(row=0, column=0, columnspan=4, pady=(0, 10))

        # Configuration section
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="5")
        config_frame.grid(row=1, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)
        config_frame.columnconfigure(1, weight=1) # Allow config name entry to expand

        ttk.Label(config_frame, text="xDiag Config Name:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        config_name_entry = ttk.Entry(config_frame, textvariable=self.config_name_var, width=40)
        config_name_entry.grid(row=0, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))

        load_button = ttk.Button(config_frame, text="Load Config", command=self.load_config_dialog)
        load_button.grid(row=0, column=2, padx=5, pady=5)
        save_button = ttk.Button(config_frame, text="Save Config", command=self.save_config_dialog)
        save_button.grid(row=0, column=3, padx=5, pady=5)

        # Input file section
        seq_frame = ttk.LabelFrame(main_frame, text="Input File", padding="5")
        seq_frame.grid(row=2, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(seq_frame, text="Sequence Number:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        seq_entry = ttk.Entry(seq_frame, textvariable=self.sequence_number_var, width=15)
        seq_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        # Segments control section
        segments_control_frame = ttk.LabelFrame(main_frame, text="Diagnostic Test Segments Setup", padding="5")
        segments_control_frame.grid(row=3, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(segments_control_frame, text="Number of Diag Test Segment(s):").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        num_segments_entry = ttk.Entry(segments_control_frame, textvariable=self.num_segments_var, width=5)
        num_segments_entry.grid(row=0, column=1, padx=(5,0), pady=5, sticky=tk.W)
        set_segments_button = ttk.Button(segments_control_frame, text="Set", command=self.update_segments_display)
        set_segments_button.grid(row=0, column=2, padx=(2,5), pady=5, sticky=tk.W)

        # Scrollable area for dynamic segments
        self.segments_canvas = tk.Canvas(main_frame, borderwidth=0, background=GUI_BACKGROUND_COLOR, highlightthickness=0) # Set canvas background
        self.segments_canvas.grid(row=4, column=0, columnspan=4, sticky="nsew", pady=5)

        self.segments_scrollable_frame = ttk.Frame(self.segments_canvas, padding="5") # Style applied
        self.segments_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.segments_canvas.configure(
                scrollregion=self.segments_canvas.bbox("all")
            )
        )

        self.segments_canvas.create_window((0, 0), window=self.segments_scrollable_frame, anchor="nw")

        segments_scrollbar_y = ttk.Scrollbar(main_frame, orient="vertical", command=self.segments_canvas.yview) # Style applied
        segments_scrollbar_y.grid(row=4, column=4, sticky="ns")
        self.segments_canvas.configure(yscrollcommand=segments_scrollbar_y.set)

        main_frame.rowconfigure(4, weight=1) # Allow segments area to expand
        main_frame.columnconfigure(0, weight=1) # Allow main content to expand horizontally

        # Extracted data display area
        extracted_data_frame = ttk.LabelFrame(main_frame, text="Extracted Diagnostics Data", padding="5")
        extracted_data_frame.grid(row=5, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        extracted_data_frame.rowconfigure(0, weight=1) # Text area expands
        extracted_data_frame.columnconfigure(0, weight=1) # Text area expands

        self.extracted_data_text = tk.Text(extracted_data_frame, wrap=tk.WORD, height=15, width=80, relief=tk.SOLID, borderwidth=1,
                                           background=TEXT_AREA_COLOR, foreground="black") # Set text area background
        data_scrollbar_y = ttk.Scrollbar(extracted_data_frame, orient=tk.VERTICAL, command=self.extracted_data_text.yview) # Style applied
        data_scrollbar_x = ttk.Scrollbar(extracted_data_frame, orient=tk.HORIZONTAL, command=self.extracted_data_text.xview) # Style applied
        self.extracted_data_text.configure(yscrollcommand=data_scrollbar_y.set, xscrollcommand=data_scrollbar_x.set)

        self.extracted_data_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        data_scrollbar_y.grid(row=0, column=1, sticky=(tk.N, tk.S))
        data_scrollbar_x.grid(row=1, column=0, sticky=(tk.W, tk.E))

        main_frame.rowconfigure(5, weight=2) # Give more weight to data text area

        # Extract button
        extract_button = ttk.Button(main_frame, text="Extract Diag", command=self.extract_diagnostics, style="Accent.TButton") # Style applied
        extract_button.grid(row=6, column=0, columnspan=4, pady=10)


    def _create_dynamic_segments(self, num_segments_to_create, stored_data_list=None):
        # Clear existing segment frames
        for frame in self.segment_frames:
            frame.destroy()
        self.segment_frames = []
        new_segment_data_vars = [] # Use a temporary list to build up new vars

        for i in range(num_segments_to_create):
            segment_frame = ttk.LabelFrame(self.segments_scrollable_frame, text="Diag Test Segment {}".format(i + 1), padding="10") # Style applied
            segment_frame.grid(row=i, column=0, sticky=(tk.W, tk.E), pady=5, padx=5)
            self.segment_frames.append(segment_frame)

            # Variables for this segment's widgets
            current_data_vars = {
                "header": tk.StringVar(),
                "name_pattern_input": tk.StringVar(), # For the entry field
                "stat_MIN_var": tk.BooleanVar(value=False),
                "stat_MAX_var": tk.BooleanVar(value=False),
                "stat_AVR_var": tk.BooleanVar(value=False),
                # patterns_listbox_widget will be added below
            }

            # Populate from stored_data if available
            if stored_data_list and i < len(stored_data_list):
                stored_segment = stored_data_list[i]
                current_data_vars["header"].set(stored_segment.get("header", DIAG_TEST_HEADERS[0] if DIAG_TEST_HEADERS else ""))
                # name_patterns_list will be populated into listbox later
                current_data_vars["stat_MIN_var"].set(stored_segment.get("stat_MIN", False))
                current_data_vars["stat_MAX_var"].set(stored_segment.get("stat_MAX", False))
                current_data_vars["stat_AVR_var"].set(stored_segment.get("stat_AVR", False))
            else: # Default for new segments
                current_data_vars["header"].set(DIAG_TEST_HEADERS[0] if DIAG_TEST_HEADERS else "")
            
            new_segment_data_vars.append(current_data_vars)


            # Widgets for the segment
            ttk.Label(segment_frame, text="Diag Test Header:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W) # Style applied
            header_combo = ttk.Combobox(segment_frame, textvariable=current_data_vars["header"], values=DIAG_TEST_HEADERS, width=40, state="readonly") # Style applied
            header_combo.grid(row=0, column=1, columnspan=3, padx=5, pady=2, sticky=(tk.W, tk.E))

            ttk.Label(segment_frame, text="Name Pattern:").grid(row=1, column=0, padx=5, pady=2, sticky=tk.W) # Style applied
            name_pattern_entry = ttk.Entry(segment_frame, textvariable=current_data_vars["name_pattern_input"], width=25) # Style applied
            name_pattern_entry.grid(row=1, column=1, padx=5, pady=2, sticky=(tk.W, tk.E))

            add_pattern_button = ttk.Button(segment_frame, text="Add", width=5, # Style applied
                                            command=lambda idx=i: self._add_name_pattern(idx)) # Use lambda to pass current index
            add_pattern_button.grid(row=1, column=2, padx=(0,2), pady=2, sticky=tk.W)

            remove_pattern_button = ttk.Button(segment_frame, text="Remove", width=7, # Style applied
                                               command=lambda idx=i: self._remove_name_pattern(idx)) # Use lambda
            remove_pattern_button.grid(row=1, column=3, padx=(0,5), pady=2, sticky=tk.W)


            ttk.Label(segment_frame, text="Added Patterns:").grid(row=2, column=0, padx=5, pady=2, sticky=tk.NW) # Style applied
            patterns_listbox = tk.Listbox(segment_frame, height=3, width=30, exportselection=False,
                                          background=LISTBOX_BG_COLOR, foreground=LISTBOX_FG_COLOR,
                                          selectbackground=GUI_BACKGROUND_COLOR, selectforeground=BUTTON_TEXT_COLOR) # Direct styling for Listbox
            patterns_listbox.grid(row=2, column=1, columnspan=3, padx=5, pady=2, sticky=(tk.W, tk.E))
            current_data_vars["patterns_listbox_widget"] = patterns_listbox # Store reference to listbox

            # Populate listbox from stored_data if available
            if stored_data_list and i < len(stored_data_list):
                stored_patterns = stored_data_list[i].get("name_patterns_list", [])
                for p_item in stored_patterns:
                    patterns_listbox.insert(tk.END, p_item)


            # Frame for stats checkboxes for better alignment
            stats_frame = ttk.Frame(segment_frame) # Style applied
            stats_frame.grid(row=3, column=1, columnspan=3, padx=5, pady=2, sticky=tk.W)

            ttk.Label(segment_frame, text="Summary Stats:").grid(row=3, column=0, padx=5, pady=2, sticky=tk.W) # Style applied
            
            # For Checkbuttons, the background of the checkbutton itself is tricky with ttk themes.
            # The label part will pick up the Label style.
            min_cb = ttk.Checkbutton(stats_frame, text="MIN", variable=current_data_vars["stat_MIN_var"])
            min_cb.pack(side=tk.LEFT, padx=(0,5))
            max_cb = ttk.Checkbutton(stats_frame, text="MAX", variable=current_data_vars["stat_MAX_var"])
            max_cb.pack(side=tk.LEFT, padx=(0,5))
            avr_cb = ttk.Checkbutton(stats_frame, text="AVR", variable=current_data_vars["stat_AVR_var"])
            avr_cb.pack(side=tk.LEFT)

            segment_frame.columnconfigure(1, weight=1) # Allow combobox/entry to expand

        self.segment_data_vars = new_segment_data_vars # Assign the newly built list
        self.segments_scrollable_frame.update_idletasks() # Important for scrollregion update
        self.segments_canvas.config(scrollregion=self.segments_canvas.bbox("all"))


    def _add_name_pattern(self, segment_index):
        # Ensure segment_index is valid
        if not (0 <= segment_index < len(self.segment_data_vars)):
            print "Error: Invalid segment_index {} for add_name_pattern".format(segment_index)
            return

        pattern_input_var = self.segment_data_vars[segment_index]["name_pattern_input"]
        pattern_to_add = pattern_input_var.get().strip()
        if not pattern_to_add:
            tkMessageBox.showwarning("Input Error", "Name pattern cannot be empty.")
            return

        listbox = self.segment_data_vars[segment_index]["patterns_listbox_widget"]
        current_patterns = list(listbox.get(0, tk.END)) # Get current items as a list
        if pattern_to_add not in current_patterns:
            listbox.insert(tk.END, pattern_to_add)
            pattern_input_var.set("") # Clear input field
        else:
            tkMessageBox.showinfo("Info", "Pattern already exists in the list.")


    def _remove_name_pattern(self, segment_index):
        if not (0 <= segment_index < len(self.segment_data_vars)):
            print "Error: Invalid segment_index {} for remove_name_pattern".format(segment_index)
            return

        listbox = self.segment_data_vars[segment_index]["patterns_listbox_widget"]
        selected_indices = listbox.curselection() # Returns a tuple of selected indices
        if not selected_indices:
            tkMessageBox.showwarning("Selection Error", "Please select a pattern to remove.")
            return

        # Iterate in reverse to avoid index shifting issues when deleting multiple items
        for index in reversed(selected_indices):
            listbox.delete(index)

    def update_segments_display(self):
        # First, preserve data from existing segments if any
        stored_data_list = []
        for seg_vars in self.segment_data_vars: # Iterate through current segment data
            listbox = seg_vars.get("patterns_listbox_widget") # Use .get for safety
            patterns = []
            if listbox: # Check if listbox widget exists
                patterns = list(listbox.get(0, tk.END))

            stored_data_list.append({
                "header": seg_vars["header"].get(),
                "name_patterns_list": patterns, # This now correctly gets from the listbox
                "stat_MIN": seg_vars["stat_MIN_var"].get(),
                "stat_MAX": seg_vars["stat_MAX_var"].get(),
                "stat_AVR": seg_vars["stat_AVR_var"].get(),
            })

        try:
            num_new_segments = int(self.num_segments_var.get())
            if num_new_segments <= 0:
                tkMessageBox.showerror("Input Error", "Number of segments must be a positive integer.")
                return
        except ValueError:
            tkMessageBox.showerror("Input Error", "Invalid number for segments. Please enter an integer.")
            return

        self._create_dynamic_segments(num_new_segments, stored_data_list)


    def save_config_dialog(self):
        config_name = self.config_name_var.get().strip()
        filepath = ""

        if not config_name: # If name field is empty, open "save as" dialog
            filepath = tkFileDialog.asksaveasfilename(
                initialdir=DEFAULT_CONFIG_DIR,
                defaultextension=CONFIG_EXTENSION,
                filetypes=[("xDiag Config files", "*" + CONFIG_EXTENSION), ("All files", "*.*")],
                title="Save Configuration As"
            )
            if not filepath: # User cancelled
                return
            # Update the config name field with the chosen filename (without extension)
            self.config_name_var.set(os.path.splitext(os.path.basename(filepath))[0])
        else: # Config name is provided in the entry field
            # Check if it's an absolute path or contains directory separators
            if os.path.isabs(config_name) or os.path.dirname(config_name):
                # Assume it's a full or relative path
                filepath = config_name if config_name.endswith(CONFIG_EXTENSION) else config_name + CONFIG_EXTENSION
            else:
                # Assume it's just a filename, use default directory
                filename = config_name if config_name.endswith(CONFIG_EXTENSION) else config_name + CONFIG_EXTENSION
                filepath = os.path.join(DEFAULT_CONFIG_DIR, filename)
        
        # Ensure the directory exists before trying to save
        dir_to_save_in = os.path.dirname(filepath)
        if dir_to_save_in and not os.path.exists(dir_to_save_in):
            try:
                os.makedirs(dir_to_save_in)
            except OSError as e: # Handle potential error during directory creation
                tkMessageBox.showerror("Save Error", "Could not create directory {}: {}".format(dir_to_save_in, e))
                return

        self.save_config(filepath)


    def save_config(self, filepath):
        parser = ConfigParser.ConfigParser()

        # General section
        parser.add_section('General')
        parser.set('General', 'config_name', self.config_name_var.get())
        parser.set('General', 'sequence_number', self.sequence_number_var.get())
        parser.set('General', 'num_segments', str(len(self.segment_data_vars))) # Save actual number of segments
        parser.set('General', 'window_geometry', self.master.geometry())


        # Segments sections
        for i, seg_vars in enumerate(self.segment_data_vars):
            section_name = 'Segment_{}'.format(i)
            parser.add_section(section_name)
            parser.set(section_name, 'header', seg_vars["header"].get())
            
            # Get patterns from the listbox widget
            listbox = seg_vars.get("patterns_listbox_widget")
            patterns = []
            if listbox:
                 patterns = list(listbox.get(0, tk.END))
            parser.set(section_name, 'name_patterns', ",".join(patterns)) # Save as comma-separated string

            parser.set(section_name, 'stat_min', str(seg_vars["stat_MIN_var"].get()))
            parser.set(section_name, 'stat_max', str(seg_vars["stat_MAX_var"].get()))
            parser.set(section_name, 'stat_avr', str(seg_vars["stat_AVR_var"].get()))

        try:
            with open(filepath, 'w') as configfile:
                parser.write(configfile)
            self.current_config_filepath = os.path.abspath(filepath) # Store the full path
            tkMessageBox.showinfo("Success", "Configuration saved to {}".format(filepath))
            self._write_last_config_path(filepath) # Update last used config
        except IOError as e:
            tkMessageBox.showerror("Save Error", "Failed to save configuration: {}".format(e))


    def load_config_dialog(self):
        filepath = tkFileDialog.askopenfilename(
            initialdir=DEFAULT_CONFIG_DIR,
            defaultextension=CONFIG_EXTENSION,
            filetypes=[("xDiag Config files", "*" + CONFIG_EXTENSION), ("All files", "*.*")],
            title="Load Configuration"
        )
        if not filepath: # User cancelled
            return

        self.load_config(filepath)

    def load_config(self, filepath):
        parser = ConfigParser.ConfigParser()
        if not os.path.exists(filepath):
            # Only show error if it wasn't the startup auto-load attempt for a missing file
            # or if the user explicitly tried to load this non-existent file again.
            if self.current_config_filepath == os.path.abspath(filepath) or not hasattr(self, '_startup_load_attempted'):
                 tkMessageBox.showerror("Load Error", "Config file not found: {}".format(filepath))
            else:
                print "Info: Last config file specified in tracker not found: {}".format(filepath)
            if hasattr(self, '_startup_load_attempted') and self._startup_load_attempted is None:
                self._startup_load_attempted = True # Mark as attempted
            return

        try:
            parser.read(filepath)

            # General section
            try: self.config_name_var.set(parser.get('General', 'config_name'))
            except ConfigParser.NoOptionError: self.config_name_var.set(os.path.splitext(os.path.basename(filepath))[0]) # Fallback

            try: self.sequence_number_var.set(parser.get('General', 'sequence_number'))
            except ConfigParser.NoOptionError: self.sequence_number_var.set("")

            try: num_segments = parser.getint('General', 'num_segments')
            except ConfigParser.NoOptionError: num_segments = DEFAULT_NUM_SEGMENTS # Fallback
            self.num_segments_var.set(str(num_segments)) # Update the entry field as well

            try:
                window_geometry = parser.get('General', 'window_geometry')
                if window_geometry: self.master.geometry(window_geometry)
            except ConfigParser.NoOptionError: pass


            # Prepare data for creating segments
            stored_data_for_creation = []
            for i in range(num_segments): # Iterate based on num_segments from config
                section_name = 'Segment_{}'.format(i)
                segment_data = {} # Default empty dict
                if parser.has_section(section_name):
                    try: segment_data["header"] = parser.get(section_name, 'header')
                    except ConfigParser.NoOptionError: segment_data["header"] = DIAG_TEST_HEADERS[0] if DIAG_TEST_HEADERS else ""

                    try: patterns_str = parser.get(section_name, 'name_patterns')
                    except ConfigParser.NoOptionError: patterns_str = ""
                    segment_data["name_patterns_list"] = [p.strip() for p in patterns_str.split(',') if p.strip()] # Split and clean

                    try: segment_data["stat_MIN"] = parser.getboolean(section_name, 'stat_min')
                    except (ConfigParser.NoOptionError, ValueError): segment_data["stat_MIN"] = False
                    try: segment_data["stat_MAX"] = parser.getboolean(section_name, 'stat_max')
                    except (ConfigParser.NoOptionError, ValueError): segment_data["stat_MAX"] = False
                    try: segment_data["stat_AVR"] = parser.getboolean(section_name, 'stat_avr')
                    except (ConfigParser.NoOptionError, ValueError): segment_data["stat_AVR"] = False
                stored_data_for_creation.append(segment_data)

            # Recreate segments with loaded data
            self._create_dynamic_segments(num_segments, stored_data_for_creation)

            self.current_config_filepath = os.path.abspath(filepath)
            # Only show success message if not during initial silent startup load
            if not hasattr(self, '_startup_load_attempted') or self._startup_load_attempted == False : # if _startup_load_attempted is None or False
                 tkMessageBox.showinfo("Success", "Configuration loaded from {}".format(filepath))
            self._write_last_config_path(filepath) # Update last used config
            if hasattr(self, '_startup_load_attempted'): # Ensure it's marked as true after any load
                self._startup_load_attempted = True


        except (ConfigParser.Error, ValueError, IOError) as e: # Catch more specific errors
            tkMessageBox.showerror("Load Error", "Failed to load configuration: {}".format(e))
        except Exception as e: # Catch any other unexpected errors during load
            tkMessageBox.showerror("Load Error", "An unexpected error occurred during load: {}".format(e))
        finally:
            # Ensure startup load is marked as attempted even if there was an error during a startup load
            if hasattr(self, '_startup_load_attempted') and self._startup_load_attempted is None:
                self._startup_load_attempted = True


    def _find_latest_diag_file(self, sequence_num):
        if not sequence_num:
            tkMessageBox.showerror("Input Error", "Sequence Number cannot be empty.")
            return None

        diag_dir_path = os.path.join(BASE_DIAG_PATH, sequence_num)
        if not os.path.isdir(diag_dir_path):
            tkMessageBox.showerror("File Error", "Directory not found: {}".format(diag_dir_path))
            return None

        search_pattern = os.path.join(diag_dir_path, DIAG_FILE_PATTERN)
        diag_files = glob.glob(search_pattern)

        if not diag_files:
            tkMessageBox.showinfo("Info", "No diagnostic files ({}*) found in {}.".format(DIAG_FILE_PATTERN.replace("*",""), diag_dir_path))
            return None

        # Find the latest file by modification time
        latest_file = max(diag_files, key=os.path.getmtime)
        return latest_file

    def _parse_diag_data_line(self, line, target_patterns, requested_stats):
        parts = line.split()
        if not parts:
            return None

        name_parts = []
        data_idx = -1
        name = ""

        for i, part in enumerate(parts):
            is_numeric_id_like = False
            try:
                int(part)
                is_numeric_id_like = True
            except ValueError:
                pass
            
            if is_numeric_id_like:
                if i == 1 and parts[0].isalpha() and not name_parts : 
                    name = parts[0]
                    data_idx = i 
                    break
                elif name_parts: 
                    name = " ".join(name_parts)
                    data_idx = i 
                    break
                elif i == 0: 
                    return None
            else: 
                name_parts.append(part)
        
        if not name and name_parts: 
            name = " ".join(name_parts)
        
        if data_idx == -1 or not name: 
            return None

        matched_pattern = False
        for p_item in target_patterns:
            if fnmatch.fnmatch(name, p_item):
                matched_pattern = True
                break
        if not matched_pattern:
            return None
        
        # Corrected indices based on standard diag format:
        # NAME ID STAT Miss Pass Rej MIN MAX AVR STD
        # If data_idx points to ID:
        # MIN is at data_idx + 5
        # MAX is at data_idx + 6
        # AVR is at data_idx + 7
        extracted_values = {}
        try:
            if "MIN" in requested_stats and len(parts) > data_idx + 5: # CORRECTED INDEX
                extracted_values["MIN"] = float(parts[data_idx + 5])
            if "MAX" in requested_stats and len(parts) > data_idx + 6: # CORRECTED INDEX
                extracted_values["MAX"] = float(parts[data_idx + 6])
            if "AVR" in requested_stats and len(parts) > data_idx + 7: # CORRECTED INDEX
                extracted_values["AVR"] = float(parts[data_idx + 7])
            
            if extracted_values: 
                return name, extracted_values
        except (IndexError, ValueError) as e:
            if extracted_values:
                return name, extracted_values
            return None 
        return None


    def extract_diagnostics(self):
        sequence_num = self.sequence_number_var.get().strip()
        diag_filepath = self._find_latest_diag_file(sequence_num)

        if not diag_filepath:
            return 

        self.extracted_data_text.config(state=tk.NORMAL)
        self.extracted_data_text.delete(1.0, tk.END)
        self.extracted_data_text.insert(tk.END, "Sequence Number: {}\n".format(sequence_num))
        self.extracted_data_text.insert(tk.END, "Diagnostic File Used: {}\n\n".format(os.path.basename(diag_filepath)))

        try:
            with open(diag_filepath, 'r') as f:
                file_content = f.read()
        except IOError as e:
            tkMessageBox.showerror("File Error", "Could not read diagnostic file: {}".format(e))
            self.extracted_data_text.config(state=tk.DISABLED)
            return

        test_blocks_raw = file_content.split("==========================================================================================================================================")
        
        parsed_data_all_segments = OrderedDict() 

        for segment_idx, seg_vars_map in enumerate(self.segment_data_vars):
            target_header = seg_vars_map["header"].get()
            
            listbox_widget = seg_vars_map.get("patterns_listbox_widget")
            target_name_patterns = []
            if listbox_widget:
                target_name_patterns = list(listbox_widget.get(0, tk.END))

            requested_stats_for_segment = []
            if seg_vars_map["stat_MIN_var"].get(): requested_stats_for_segment.append("MIN")
            if seg_vars_map["stat_MAX_var"].get(): requested_stats_for_segment.append("MAX")
            if seg_vars_map["stat_AVR_var"].get(): requested_stats_for_segment.append("AVR")

            if not target_header or not target_name_patterns or not requested_stats_for_segment:
                continue 
            
            found_header_block = False
            for block_raw in test_blocks_raw:
                block_lines = [line.strip() for line in block_raw.splitlines() if line.strip()] 
                if not block_lines:
                    continue

                current_block_header = block_lines[0].strip() 

                if current_block_header == target_header:
                    found_header_block = True
                    is_data_section = False
                    data_table_header_keywords = ["NAME", "MIN", "MAX", "AVR", "STD"] 

                    for line_idx, line in enumerate(block_lines):
                        if all(keyword in line for keyword in data_table_header_keywords):
                            is_data_section = True
                            continue 
                        
                        if is_data_section:
                            if not line or "---- Acceptance range ----" in line or "test 1 :" in line or line.startswith("NAME"): 
                                continue
                            
                            parsed_line_data = self._parse_diag_data_line(line, target_name_patterns, requested_stats_for_segment)
                            if parsed_line_data:
                                name, extracted_stats_dict = parsed_line_data
                                if target_header not in parsed_data_all_segments:
                                    parsed_data_all_segments[target_header] = OrderedDict()
                                
                                if name not in parsed_data_all_segments[target_header]:
                                     parsed_data_all_segments[target_header][name] = extracted_stats_dict
                                else:
                                     parsed_data_all_segments[target_header][name].update(extracted_stats_dict)
                    break 
            
        if not parsed_data_all_segments:
            self.extracted_data_text.insert(tk.END, "No data extracted based on current segment configurations.\n")
        else:
            for header, names_data in parsed_data_all_segments.items():
                self.extracted_data_text.insert(tk.END, "--- {} ---\n\n".format(header)) # Space after header
                if not names_data: 
                    self.extracted_data_text.insert(tk.END, "(No matching names found for this header with current patterns)\n")
                else:
                    for name, stats_dict in names_data.items():
                        if not stats_dict: 
                            continue

                        stats_strings = []
                        for stat_type in STAT_TYPES: 
                            if stat_type in stats_dict: 
                                stats_strings.append("{} = {}".format(stat_type, stats_dict[stat_type]))
                        
                        if stats_strings: 
                             self.extracted_data_text.insert(tk.END, "{}: {}\n".format(name, ", ".join(stats_strings)))
                self.extracted_data_text.insert(tk.END, "\n") # Extra blank line after each segment's data

        self.extracted_data_text.config(state=tk.DISABLED) 

if __name__ == '__main__':
    root = tk.Tk()
    app = DiagExtractorApp(root)
    # Example: root.geometry("850x750") # You can set a default size if desired
    root.mainloop()
