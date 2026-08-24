#!/usr/bin/env python2.7
# Ai assisted Code by RBolisay
# Modified to include advanced UI, config persistence, range filtering, and a unified browse/load button.
# Further modified to change GUI background and button colors to user-specified Blue Aura theme.
# Modified to replace warning Label with a scrollable Text widget to handle long messages.
# Modified to implement per-pattern "Max Duplicate" control, replacing the global setting.
# Modified to add in-place Treeview editing, multiple selection, and styled headers.
# Modified to fix startup confirmation prompt by creating a silent clear method.
# Modified to make sequence folders clickable (open files in Firefox) with right-click Open in Explorer.
import os
import glob
import math
import json
import re
import subprocess
import urllib
import Tkinter as tk
import tkFileDialog
import tkMessageBox
import ttk

class SequenceCheckerApp(tk.Frame):
    DEFAULT_TARGET_DIR = "/usr/local/trinop/dbase/links/qcfiles/Nav_Line_QC"
    # Default patterns now include a per-pattern max duplicate count
    DEFAULT_PATTERNS = [
        ("35_Diag*", 1),
        ("50_NavPointP111*SSFILTREG*", 1),
        ("50_NavPointP211*", 1),
        ("50_P111_Header_Diff*", 1),
        ("50_P211_Header_Diff*", 1),
        ("*PositioningReport*", 1)
    ]
    DEFAULT_EXPECTED_COUNT = "1"
    DEFAULT_SEQUENCE_RANGE = ""
    DEFAULT_CONFIG_SAVE_DIR = "/usr/local/trinop/dbase/links/qcfiles/Misc/xNavLQC/"
    DEFAULT_CONFIG_FILENAME = "default_settings.json"
    APP_STATE_FILE = os.path.join(os.path.expanduser("~"), ".xnavlqc_app_state_p27.json")

    # User-specified Nippon Paint Blue Aura Theme Colors
    BLUE_AURA_BG = "#B4C8E1"  # Background Color
    BLUE_AURA_BUTTON = "#8DA9CC" # Button Background Color
    BUTTON_TEXT_COLOR = "black"

    def __init__(self, master=None):
        tk.Frame.__init__(self, master, bg=self.BLUE_AURA_BG)
        self.master = master
        self.master.configure(bg=self.BLUE_AURA_BG)
        self.pack(fill="both", expand=True)
        
        self.edit_entry = None # To hold the temporary entry widget for editing

        self.target_directory = self.DEFAULT_TARGET_DIR
        self.monitoring = False
        self.after_id = None

        self.config_save_dir = self.DEFAULT_CONFIG_SAVE_DIR
        self.config_filename = self.DEFAULT_CONFIG_FILENAME
        self.current_config_file_path = None
        self.sequence_range_str = self.DEFAULT_SEQUENCE_RANGE

        self.top_bar_frame = tk.Frame(self, bg=self.BLUE_AURA_BG)
        self.top_bar_frame.grid(row=0, column=0, sticky="ew", pady=(0,5))

        self.control_frame = tk.Frame(self, bg=self.BLUE_AURA_BG)
        self.control_frame.grid(row=1, column=0, sticky="nw")

        self.results_container = tk.Frame(self, bg=self.BLUE_AURA_BG)
        self.results_container.grid(row=2, column=0, sticky="nsew")

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_top_bar()
        self.create_controls()
        self.create_results_area()

        self.load_app_state()
        self.load_configuration(self.current_config_file_path, silent_startup=True)

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.control_frame.bind("<Configure>", self.on_control_frame_configure)
        self.top_bar_frame.bind("<Configure>", self.on_top_bar_frame_configure)

    def create_top_bar(self):
        desc_label = tk.Label(self.top_bar_frame, text="Tool for Maintaining/Monitoring files in Nav_Line_QC directory", font=("Helvetica", 12, "bold"), bg=self.BLUE_AURA_BG)
        desc_label.pack(pady=5, fill=tk.X)

        config_controls_frame = tk.Frame(self.top_bar_frame, bg=self.BLUE_AURA_BG)
        config_controls_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(config_controls_frame, text="xNav_Line_QC Config Name:", bg=self.BLUE_AURA_BG).grid(row=0, column=0, sticky="w", padx=(0,5))

        self.config_name_entry = tk.Entry(config_controls_frame, width=30)
        self.config_name_entry.grid(row=0, column=1, sticky="ew", padx=5)
        self.config_name_entry.insert(0, self.config_filename)

        self.browse_load_file_button = tk.Button(config_controls_frame, text="Browse/Load File", command=self.browse_and_load_config_file, bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.browse_load_file_button.grid(row=0, column=2, padx=5)

        self.save_config_button = tk.Button(config_controls_frame, text="Save Config", command=self.save_current_configuration, bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.save_config_button.grid(row=0, column=3, padx=5)

        config_controls_frame.grid_columnconfigure(1, weight=1)

        self.config_path_display_label = tk.Label(config_controls_frame, text="Config File Path: " + os.path.join(self.config_save_dir, self.config_filename), wraplength=600, justify="left", bg=self.BLUE_AURA_BG)
        self.config_path_display_label.grid(row=1, column=0, columnspan=4, sticky="w", pady=(5,0))
        self._update_config_path_display()


    def create_controls(self):
        current_row = 0
        self.dir_button = tk.Button(self.control_frame, text="Select Target Directory", command=self.select_directory, bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.dir_button.grid(row=current_row, column=0, padx=5, pady=5, sticky="w")
        self.dir_label = tk.Label(self.control_frame, text=self.target_directory, wraplength=300, justify="left", bg=self.BLUE_AURA_BG)
        self.dir_label.grid(row=current_row, column=1, padx=5, pady=5, sticky="w", columnspan=3)
        current_row += 1

        tk.Label(self.control_frame, text="File Patterns:", bg=self.BLUE_AURA_BG).grid(row=current_row, column=0, padx=5, pady=5, sticky="nw")
        patterns_ui_frame = tk.Frame(self.control_frame, bg=self.BLUE_AURA_BG)
        patterns_ui_frame.grid(row=current_row, column=1, columnspan=3, padx=5, pady=5, sticky="nsew")
        patterns_ui_frame.grid_columnconfigure(0, weight=1)
        current_row += 1

        # Style for Treeview Headers
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview.Heading", background=self.BLUE_AURA_BUTTON, foreground=self.BUTTON_TEXT_COLOR, relief="groove", font=('Helvetica', 10, 'bold'))
        style.map('Treeview.Heading', background=[('active', '#9CB7D8')])

        # Use a Treeview for multi-column display with multiple selection
        self.patterns_tree = ttk.Treeview(patterns_ui_frame, columns=("pattern", "max_dups"), show="headings", height=5, selectmode="extended")
        self.patterns_tree_scrollbar = ttk.Scrollbar(patterns_ui_frame, orient="vertical", command=self.patterns_tree.yview)
        self.patterns_tree.configure(yscrollcommand=self.patterns_tree_scrollbar.set)
        
        self.patterns_tree.heading("pattern", text="File Pattern")
        self.patterns_tree.heading("max_dups", text="Max Duplicate")
        self.patterns_tree.column("pattern", width=250)
        self.patterns_tree.column("max_dups", width=100, anchor="center")

        self.patterns_tree.grid(row=0, column=0, sticky="nsew")
        self.patterns_tree_scrollbar.grid(row=0, column=1, sticky="ns")
        self._populate_treeview_with_defaults()
        self.patterns_tree.bind("<Double-1>", self._on_tree_double_click)

        pattern_entry_frame = tk.Frame(self.control_frame, bg=self.BLUE_AURA_BG)
        pattern_entry_frame.grid(row=current_row, column=1, columnspan=3, sticky="ew", padx=5)
        pattern_entry_frame.grid_columnconfigure(1, weight=1)
        
        tk.Label(pattern_entry_frame, text="Add Pattern:", bg=self.BLUE_AURA_BG).grid(row=0, column=0, padx=(0,5), sticky="w")
        self.pattern_entry = tk.Entry(pattern_entry_frame)
        self.pattern_entry.grid(row=0, column=1, padx=5, sticky="ew")
        
        tk.Label(pattern_entry_frame, text="Max Duplicate:", bg=self.BLUE_AURA_BG).grid(row=0, column=2, padx=(0,5), sticky="w")
        self.pattern_max_dups_entry = tk.Entry(pattern_entry_frame, width=5)
        self.pattern_max_dups_entry.grid(row=0, column=3, padx=5, sticky="w")
        self.pattern_max_dups_entry.insert(0, "1")
        
        self.pattern_entry.bind("<Return>", self.add_pattern_from_entry_event)
        self.add_pattern_button = tk.Button(pattern_entry_frame, text="Add", command=self.add_pattern_from_entry_event, bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.add_pattern_button.grid(row=0, column=4, padx=5, sticky="e")
        current_row += 1

        pattern_buttons_frame = tk.Frame(self.control_frame, bg=self.BLUE_AURA_BG)
        pattern_buttons_frame.grid(row=current_row, column=1, columnspan=3, sticky="w", padx=5, pady=(0,5))
        self.remove_pattern_button = tk.Button(pattern_buttons_frame, text="Remove Selected", command=self.remove_selected_pattern, bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.remove_pattern_button.pack(side=tk.LEFT, padx=(0,5))
        self.clear_patterns_button = tk.Button(pattern_buttons_frame, text="Clear All Patterns", command=self.clear_all_patterns, bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.clear_patterns_button.pack(side=tk.LEFT, padx=5)
        current_row += 1

        tk.Label(self.control_frame, text="Expected File Count:", bg=self.BLUE_AURA_BG).grid(row=current_row, column=0, padx=5, pady=5, sticky="w")
        self.expected_count_entry = tk.Entry(self.control_frame, width=10)
        self.expected_count_entry.grid(row=current_row, column=1, padx=5, pady=5, sticky="w")
        self.expected_count_entry.insert(0, self.DEFAULT_EXPECTED_COUNT)
        current_row += 1

        tk.Label(self.control_frame, text="Sequence range (e.g., 1001-1100, 2001-2050):", bg=self.BLUE_AURA_BG).grid(row=current_row, column=0, padx=5, pady=5, sticky="w")
        self.sequence_range_entry = tk.Entry(self.control_frame, width=40)
        self.sequence_range_entry.grid(row=current_row, column=1, columnspan=3, padx=5, pady=5, sticky="ew")
        self.sequence_range_entry.insert(0, self.DEFAULT_SEQUENCE_RANGE)
        current_row += 1

        action_buttons_frame = tk.Frame(self.control_frame, bg=self.BLUE_AURA_BG)
        action_buttons_frame.grid(row=current_row, column=0, columnspan=4, pady=10, sticky="w")
        self.scan_button = tk.Button(action_buttons_frame, text="Scan Sequences", command=self.scan_sequences, bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.scan_button.pack(side=tk.LEFT, padx=5)
        self.start_monitor_button = tk.Button(action_buttons_frame, text="Start Monitoring", command=self.start_monitoring, bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.start_monitor_button.pack(side=tk.LEFT, padx=5)
        self.stop_monitor_button = tk.Button(action_buttons_frame, text="Stop Monitoring", command=self.stop_monitoring, state="disabled", bg=self.BLUE_AURA_BUTTON, fg=self.BUTTON_TEXT_COLOR)
        self.stop_monitor_button.pack(side=tk.LEFT, padx=5)
        current_row += 1

        warning_frame = tk.Frame(self.control_frame, bg=self.BLUE_AURA_BG)
        warning_frame.grid(row=current_row, column=0, columnspan=4, pady=5, sticky="nsew")
        warning_frame.grid_columnconfigure(0, weight=1)

        self.warning_text = tk.Text(warning_frame, height=4, wrap=tk.WORD, relief="sunken", borderwidth=1)
        self.warning_scrollbar = tk.Scrollbar(warning_frame, orient="vertical", command=self.warning_text.yview)
        self.warning_text.config(yscrollcommand=self.warning_scrollbar.set)

        self.warning_text.grid(row=0, column=0, sticky="nsew")
        self.warning_scrollbar.grid(row=0, column=1, sticky="ns")

        self.warning_text.insert(tk.END, "Scan results and warnings will appear here.")
        self.warning_text.config(state=tk.DISABLED, bg=self.BLUE_AURA_BG, fg="black")

        self.control_frame.grid_columnconfigure(1, weight=1)

    def _on_tree_double_click(self, event):
        # First, destroy any old edit box
        if self.edit_entry:
            self.edit_entry.destroy()
            self.edit_entry = None

        # Identify the clicked cell
        region = self.patterns_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        
        item_id = self.patterns_tree.identify_row(event.y)
        column = self.patterns_tree.identify_column(event.x)
        column_index = int(column.replace('#', '')) - 1

        # Get cell geometry
        x, y, width, height = self.patterns_tree.bbox(item_id, column)

        # Get the current value
        current_values = self.patterns_tree.item(item_id, "values")
        original_value = current_values[column_index]

        # Place an Entry widget over the cell
        self.edit_entry = tk.Entry(self.patterns_tree, justify="center" if column_index == 1 else "left")
        self.edit_entry.place(x=x, y=y, width=width, height=height)
        self.edit_entry.insert(0, original_value)
        self.edit_entry.focus_set()
        self.edit_entry.select_range(0, tk.END)

        # Commit edit on Enter or FocusOut (clicking away)
        def commit_edit(event):
            new_value = self.edit_entry.get().strip()
            # Validate Max Duplicate as an integer
            if column_index == 1:
                try:
                    int(new_value)
                except ValueError:
                    self.edit_entry.destroy()
                    self.edit_entry = None
                    tkMessageBox.showwarning("Validation Error", "Max Duplicate must be an integer.")
                    return
            
            # Update the treeview item
            new_values = list(current_values)
            new_values[column_index] = new_value
            self.patterns_tree.item(item_id, values=new_values)
            
            self.edit_entry.destroy()
            self.edit_entry = None

        self.edit_entry.bind("<Return>", commit_edit)
        self.edit_entry.bind("<FocusOut>", commit_edit)


    def on_control_frame_configure(self, event):
        new_wrap = event.width - 20
        if new_wrap < 50: new_wrap = 50
        self.dir_label.config(wraplength=max(50, new_wrap - self.dir_button.winfo_width() - 10))


    def on_top_bar_frame_configure(self, event):
        new_wrap = event.width - 20
        if new_wrap < 100: new_wrap = 100
        self.config_path_display_label.config(wraplength=new_wrap)

    def create_results_area(self):
        self.results_canvas = tk.Canvas(self.results_container, borderwidth=0, bg=self.BLUE_AURA_BG)
        self.v_scrollbar = tk.Scrollbar(self.results_container, orient="vertical", command=self.results_canvas.yview)
        self.results_canvas.configure(yscrollcommand=self.v_scrollbar.set)

        self.results_canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scrollbar.grid(row=0, column=1, sticky="ns")

        self.results_container.grid_rowconfigure(0, weight=1)
        self.results_container.grid_columnconfigure(0, weight=1)

        self.results_frame = tk.Frame(self.results_canvas, bg=self.BLUE_AURA_BG)
        self.results_canvas.create_window((0, 0), window=self.results_frame, anchor="nw")
        self.results_frame.bind("<Configure>", lambda event: self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all")))

    def _update_config_path_display(self):
        filename = self.config_name_entry.get()
        if not filename:
            filename = self.DEFAULT_CONFIG_FILENAME
        if not filename.endswith(".json"):
            display_filename = filename + ".json"
        else:
            display_filename = filename

        full_path = os.path.join(self.config_save_dir, display_filename)
        self.config_path_display_label.config(text="Config File Path: " + full_path)


    def browse_and_load_config_file(self):
        initial_dir = self.config_save_dir
        if self.current_config_file_path and os.path.exists(os.path.dirname(self.current_config_file_path)):
            initial_dir = os.path.dirname(self.current_config_file_path)

        selected_filepath = tkFileDialog.askopenfilename(
            initialdir=initial_dir,
            title="Select Configuration File to Load",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if selected_filepath:
            self.load_configuration(selected_filepath, silent_startup=False)

            self.config_save_dir = os.path.dirname(selected_filepath)
            self.config_filename = os.path.basename(selected_filepath)

            self.config_name_entry.delete(0, tk.END)
            self.config_name_entry.insert(0, self.config_filename)

            self._update_config_path_display()

            self.current_config_file_path = selected_filepath
            self.save_app_state()
            tkMessageBox.showinfo("Config Loaded", "Successfully loaded configuration from\n" + selected_filepath)


    def save_current_configuration(self):
        filename_from_entry = self.config_name_entry.get().strip()
        if not filename_from_entry:
            tkMessageBox.showerror("Error", "Config file name cannot be empty.")
            return

        if os.path.isabs(filename_from_entry):
            if not filename_from_entry.endswith(".json"):
                 filename_to_save = filename_from_entry + ".json"
            else:
                 filename_to_save = filename_from_entry
            self.config_save_dir = os.path.dirname(filename_to_save)
            self.config_filename = os.path.basename(filename_to_save)
        else:
            if not filename_from_entry.endswith(".json"):
                self.config_filename = filename_from_entry + ".json"
            else:
                self.config_filename = filename_from_entry

        save_to_path = os.path.join(self.config_save_dir, self.config_filename)

        patterns_to_save = []
        for item_id in self.patterns_tree.get_children():
            patterns_to_save.append(self.patterns_tree.item(item_id, "values"))

        settings = {
            "target_directory": self.target_directory,
            "patterns": patterns_to_save,
            "expected_count": self.expected_count_entry.get(),
            "sequence_range": self.sequence_range_entry.get(),
            "window_geometry": self.master.winfo_geometry(),
            "config_save_dir": self.config_save_dir,
            "config_filename": self.config_filename
        }
        try:
            if not os.path.exists(self.config_save_dir):
                os.makedirs(self.config_save_dir)
            with open(save_to_path, 'w') as f:
                json.dump(settings, f, indent=4)

            self.current_config_file_path = save_to_path
            tkMessageBox.showinfo("Success", "Configuration saved to\n" + save_to_path)
            self.save_app_state()
        except Exception as e:
            tkMessageBox.showerror("Error Saving Config", "Could not save configuration: " + str(e))
        self._update_config_path_display()

    def load_configuration(self, filepath, silent_startup=False):
        if filepath and os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    settings = json.load(f)

                self.target_directory = settings.get("target_directory", self.DEFAULT_TARGET_DIR)
                loaded_patterns = settings.get("patterns", self.DEFAULT_PATTERNS)

                self.expected_count_entry.delete(0, tk.END)
                self.expected_count_entry.insert(0, settings.get("expected_count", self.DEFAULT_EXPECTED_COUNT))

                self.sequence_range_entry.delete(0, tk.END)
                self.sequence_range_entry.insert(0, settings.get("sequence_range", self.DEFAULT_SEQUENCE_RANGE))

                if "window_geometry" in settings and not hasattr(self, '_app_state_geom_applied') and not silent_startup:
                     self.master.geometry(settings["window_geometry"])

                self.config_save_dir = os.path.dirname(filepath)
                self.config_filename = os.path.basename(filepath)

                self.config_name_entry.delete(0, tk.END)
                self.config_name_entry.insert(0, self.config_filename)

                self.dir_label.config(text=self.target_directory)
                
                self._clear_all_patterns_silent() # Use silent clear for programmatic loading
                for p in loaded_patterns:
                    if isinstance(p, (list, tuple)) and len(p) == 2:
                        self.patterns_tree.insert("", tk.END, values=p)
                    elif isinstance(p, basestring): # Backwards compatibility for old configs
                        self.patterns_tree.insert("", tk.END, values=(p, 1))

                self.current_config_file_path = filepath
            except Exception as e:
                if not silent_startup:
                    tkMessageBox.showerror("Error Loading Config", "Could not load configuration from " + filepath + ": " + str(e) + "\nLoading default settings.")
                else:
                    print "Startup Warning: Could not load configuration from " + filepath + ": " + str(e) + ". Loading defaults."
                self._apply_default_settings_to_ui()
        else:
            if filepath and not silent_startup :
                 tkMessageBox.showwarning("Config Not Found", "Configuration file not found:\n" + filepath + "\nLoading default settings.")
            self._apply_default_settings_to_ui()

        self._update_config_path_display()

    def _populate_treeview_with_defaults(self):
        self._clear_all_patterns_silent() # Use silent clear
        for p_tuple in self.DEFAULT_PATTERNS:
            self.patterns_tree.insert("", tk.END, values=p_tuple)

    def _apply_default_settings_to_ui(self):
        self.target_directory = self.DEFAULT_TARGET_DIR
        
        self.expected_count_entry.delete(0, tk.END)
        self.expected_count_entry.insert(0, self.DEFAULT_EXPECTED_COUNT)

        self.sequence_range_entry.delete(0, tk.END)
        self.sequence_range_entry.insert(0, self.DEFAULT_SEQUENCE_RANGE)

        self.dir_label.config(text=self.target_directory)
        self._populate_treeview_with_defaults()

        self.config_save_dir = self.DEFAULT_CONFIG_SAVE_DIR
        self.config_filename = self.DEFAULT_CONFIG_FILENAME
        self.config_name_entry.delete(0, tk.END)
        self.config_name_entry.insert(0, self.config_filename)
        self._update_config_path_display()


    def save_app_state(self):
        app_state = {
            "last_config_file_path": self.current_config_file_path,
            "window_geometry": self.master.winfo_geometry()
        }
        try:
            with open(self.APP_STATE_FILE, 'w') as f:
                json.dump(app_state, f, indent=4)
        except Exception as e:
            print "Warning: Could not save app state: " + str(e)

    def load_app_state(self):
        initial_geometry = "1000x730"
        self.current_config_file_path = None
        try:
            if os.path.exists(self.APP_STATE_FILE):
                with open(self.APP_STATE_FILE, 'r') as f:
                    app_state = json.load(f)
                self.current_config_file_path = app_state.get("last_config_file_path")
                loaded_geom = app_state.get("window_geometry")
                if loaded_geom:
                    initial_geometry = loaded_geom
                    self._app_state_geom_applied = True
            self.master.geometry(initial_geometry)
        except Exception as e:
            print "Warning: Could not load app state: " + str(e) + ". Using default window size."
            self.master.geometry(initial_geometry)

    def on_closing(self):
        self.save_app_state()
        if self.after_id:
            self.after_cancel(self.after_id)
        self.master.destroy()

    def add_pattern_from_entry_event(self, event=None):
        pattern = self.pattern_entry.get().strip()
        max_dups_str = self.pattern_max_dups_entry.get().strip()

        if not pattern:
            tkMessageBox.showwarning("Input Error", "Pattern cannot be empty.")
            return

        try:
            max_dups = int(max_dups_str)
            if max_dups < 0:
                tkMessageBox.showwarning("Input Error", "Max Duplicate must be a non-negative integer.")
                return
        except ValueError:
            tkMessageBox.showwarning("Input Error", "Max Duplicate must be a valid integer.")
            return

        self.patterns_tree.insert("", tk.END, values=(pattern, max_dups))
        self.pattern_entry.delete(0, tk.END)
        self.pattern_max_dups_entry.delete(0, tk.END)
        self.pattern_max_dups_entry.insert(0, "1")

    def remove_selected_pattern(self):
        selected_items = self.patterns_tree.selection()
        if not selected_items:
            tkMessageBox.showinfo("Information", "No patterns selected to remove.")
            return
        
        # Confirm before deleting
        msg = "Are you sure you want to remove the selected pattern?"
        if len(selected_items) > 1:
            msg = "Are you sure you want to remove the {} selected patterns?".format(len(selected_items))
        
        if tkMessageBox.askyesno("Confirm Deletion", msg):
            for item in selected_items:
                self.patterns_tree.delete(item)

    def _clear_all_patterns_silent(self):
        """Silently clears the treeview without user confirmation."""
        for item in self.patterns_tree.get_children():
            self.patterns_tree.delete(item)

    def clear_all_patterns(self):
        """Clears the treeview after user confirmation."""
        if not self.patterns_tree.get_children():
            return
        if tkMessageBox.askyesno("Confirm Clear", "Are you sure you want to clear all patterns?"):
            self._clear_all_patterns_silent()

    def select_directory(self):
        directory = tkFileDialog.askdirectory(initialdir=self.target_directory)
        if directory:
            self.target_directory = directory
            self.dir_label.config(text=self.target_directory)

    def _extract_number_from_foldername(self, foldername):
        try:
            return int(foldername)
        except ValueError:
            match = re.search(r'\d+', foldername)
            if match:
                try:
                    return int(match.group(0))
                except ValueError:
                    return None
            return None

    def _parse_sequence_ranges(self, range_str):
        parsed_ranges = []
        if not range_str.strip():
            return parsed_ranges

        parts = range_str.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue

            if '-' in part:
                try:
                    start_str, end_str = part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    if start <= end:
                        parsed_ranges.append((start, end))
                    else:
                        print "Warning: Invalid range ordering in '%s' (start > end), skipping." % part
                except ValueError:
                    print "Warning: Invalid range format in '%s', skipping." % part
            else:
                try:
                    num = int(part)
                    parsed_ranges.append((num, num))
                except ValueError:
                    print "Warning: Invalid number format for sequence '%s', skipping." % part
        return parsed_ranges

    def _update_warning_display(self, text, fg_color="black"):
        self.warning_text.config(state=tk.NORMAL)
        self.warning_text.delete(1.0, tk.END)
        self.warning_text.insert(tk.END, text)
        self.warning_text.config(state=tk.DISABLED, fg=fg_color, bg=self.BLUE_AURA_BG)

    def _path_to_file_uri(self, path):
        abs_path = os.path.abspath(path)
        if isinstance(abs_path, unicode):
            abs_path = abs_path.encode("utf-8")
        return "file://" + urllib.pathname2url(abs_path)

    def _subprocess_env(self):
        """Child GUI processes need DISPLAY (and PATH) when launched from Tk."""
        env = os.environ.copy()
        if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
            env["DISPLAY"] = ":0"
        return env

    def _find_executable(self, names):
        """Resolve a binary on Rocky/RHEL when PATH from the IDE is minimal."""
        if isinstance(names, basestring):
            names = (names,)
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        path_dirs.extend(("/usr/bin", "/usr/local/bin", "/bin"))
        for name in names:
            for directory in path_dirs:
                if not directory:
                    continue
                full = os.path.join(directory, name)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    return full
        return None

    def _popen_detached(self, args):
        """
        Launch a GUI helper without PIPE on stdout/stderr — piping can block
        firefox/xdg-open on Linux when buffers fill and nothing reads them.
        """
        devnull = open(os.devnull, "w")
        kwargs = {
            "stdout": devnull,
            "stderr": devnull,
            "env": self._subprocess_env(),
            "close_fds": True,
        }
        if hasattr(os, "setsid"):
            kwargs["preexec_fn"] = os.setsid
        return subprocess.Popen(args, **kwargs)

    def open_folder_files_in_firefox(self, folder_path):
        if not os.path.isdir(folder_path):
            tkMessageBox.showerror("Error", "Folder not found:\n" + folder_path)
            return
        firefox_bin = self._find_executable(("firefox", "firefox-esr"))
        if not firefox_bin:
            tkMessageBox.showerror(
                "Error",
                "Firefox not found in PATH.\n"
                "Install Firefox or ensure /usr/bin/firefox is available."
            )
            return
        try:
            files = sorted(
                os.path.join(folder_path, name)
                for name in os.listdir(folder_path)
                if os.path.isfile(os.path.join(folder_path, name))
            )
        except OSError as e:
            tkMessageBox.showerror("Error", "Could not read folder:\n" + str(e))
            return
        if not files:
            tkMessageBox.showinfo("No Files", "No files found in folder:\n" + folder_path)
            return
        file_uris = [self._path_to_file_uri(f) for f in files]
        try:
            self._popen_detached([firefox_bin] + file_uris)
        except OSError as e:
            tkMessageBox.showerror("Error", "Could not launch Firefox:\n" + str(e))

    def open_folder_in_explorer(self, folder_path):
        if not os.path.isdir(folder_path):
            tkMessageBox.showerror("Error", "Folder not found:\n" + folder_path)
            return
        xdg_bin = self._find_executable(("xdg-open", "nautilus", "nemo", "dolphin"))
        if not xdg_bin:
            tkMessageBox.showerror(
                "Error",
                "No file manager launcher found (xdg-open, nautilus, etc.)."
            )
            return
        try:
            self._popen_detached([xdg_bin, folder_path])
        except OSError as e:
            tkMessageBox.showerror("Error", "Could not open folder in file manager:\n" + str(e))

    def show_folder_context_menu(self, event, folder_path):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Open in Explorer",
            command=lambda p=folder_path: self.open_folder_in_explorer(p)
        )
        menu.post(event.x_root, event.y_root)
        return "break"

    def scan_sequences(self):
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        self.results_frame.configure(bg=self.BLUE_AURA_BG)

        patterns_to_check = []
        for item_id in self.patterns_tree.get_children():
            try:
                values = self.patterns_tree.item(item_id, "values")
                pattern = values[0]
                max_dups = int(values[1])
                patterns_to_check.append((pattern, max_dups))
            except (ValueError, IndexError):
                tkMessageBox.showerror("Error", "Invalid data in patterns list. Please check your entries.")
                return
        
        if not patterns_to_check:
            tkMessageBox.showerror("Error", "Please add at least one file pattern.")
            return

        if not self.target_directory:
            tkMessageBox.showerror("Error", "Please select a target directory first.")
            return

        try:
            expected_count = int(self.expected_count_entry.get().strip())
        except ValueError:
            tkMessageBox.showerror("Error", "Expected File Count must be an integer.")
            return

        range_str = self.sequence_range_entry.get()
        active_ranges = self._parse_sequence_ranges(range_str)

        results = []
        problem_sequences = []
        all_subdirs_count = 0
        filtered_subdirs_count = 0

        try:
            subdirs = [d for d in os.listdir(self.target_directory)
                       if os.path.isdir(os.path.join(self.target_directory, d))]
            all_subdirs_count = len(subdirs)
        except OSError as e:
            tkMessageBox.showerror("Error", "Failed to list subdirectories: " + str(e))
            return

        for subdir_name in sorted(subdirs):
            if active_ranges:
                subdir_num = self._extract_number_from_foldername(subdir_name)
                if subdir_num is None:
                    continue

                in_any_range = False
                for r_start, r_end in active_ranges:
                    if r_start <= subdir_num <= r_end:
                        in_any_range = True
                        break
                if not in_any_range:
                    continue

            filtered_subdirs_count +=1
            seq_path = os.path.join(self.target_directory, subdir_name)
            sequence_ok = True
            issue_type = ""

            for pattern_item, pattern_max_duplicate in patterns_to_check:
                search_pattern = os.path.join(seq_path, pattern_item)
                matching_files = glob.glob(search_pattern)
                num_matches = len(matching_files)
                
                if num_matches == 0:
                    sequence_ok = False
                    issue_type = "Pattern Mismatch"
                    break
                
                if num_matches > pattern_max_duplicate:
                    sequence_ok = False
                    issue_type = "Pattern Duplicate exceeded"
                    break

            if not sequence_ok:
                status = "Issue (" + issue_type + ")"
                results.append((subdir_name, status, seq_path))
                problem_sequences.append(subdir_name + " (" + issue_type + ")")
                continue

            try:
                folder_file_count = len([f for f in os.listdir(seq_path)
                                         if os.path.isfile(os.path.join(seq_path, f))])
            except OSError as e:
                status = "Issue (Read Error)"
                results.append((subdir_name, status, seq_path))
                problem_sequences.append(subdir_name + " (Read Error: " + str(e) + ")")
                continue

            if folder_file_count != expected_count:
                sequence_ok = False
                issue_type = "File Count (" + str(folder_file_count) + " vs " + str(expected_count) + ")"

            status = "OK" if sequence_ok else "Issue (" + issue_type + ")"
            results.append((subdir_name, status, seq_path))
            if not sequence_ok:
                problem_sequences.append(subdir_name + " (" + issue_type + ")")

        if problem_sequences:
            warning_text = "Please CHECK Sequence(s): " + ", ".join(problem_sequences)
            self._update_warning_display(warning_text, fg_color="red")
        elif filtered_subdirs_count > 0 :
            self._update_warning_display("All " + str(filtered_subdirs_count) + " checked sequence(s) OK.", fg_color="green")
        else:
            if all_subdirs_count > 0 and active_ranges:
                 self._update_warning_display("No sequences matched the specified range. " + str(all_subdirs_count) + " total folders found.", fg_color="orange")
            elif all_subdirs_count == 0:
                 self._update_warning_display("No subdirectories found in target directory.", fg_color="orange")
            else:
                 self._update_warning_display("No sequences processed or checked.", fg_color="orange")


        columns = 3
        n = len(results)
        if n == 0 :
            if filtered_subdirs_count == 0 and all_subdirs_count > 0 and active_ranges:
                msg = "No folders matched the specified sequence range."
            elif filtered_subdirs_count == 0 and all_subdirs_count == 0:
                msg = "No subdirectories found in target directory."
            elif filtered_subdirs_count > 0 :
                 msg = "All " + str(filtered_subdirs_count) + " checked sequences OK (or had issues before detailed checks)."
            else:
                msg = "No sequences to display."
            tk.Label(self.results_frame, text=msg, bg=self.BLUE_AURA_BG).pack()
            self.results_frame.update_idletasks()
            self.results_canvas.config(scrollregion=self.results_canvas.bbox("all"))
            if self.monitoring: self.after_id = self.after(30000, self.scan_sequences)
            return

        rows_per_column = int(math.ceil(n / float(columns)))

        for col_idx in range(columns):
            col_frame = tk.Frame(self.results_frame, bg=self.BLUE_AURA_BG)
            col_frame.grid(row=0, column=col_idx, padx=10, sticky="n", pady=5)

            header_folder = tk.Label(col_frame, text="Sequence Folder", width=25, anchor="w", font=("Helvetica", 10, "bold"), bg=self.BLUE_AURA_BG)
            header_folder.grid(row=0, column=0, padx=2, pady=2, sticky="w")
            header_status = tk.Label(col_frame, text="Status", width=20, anchor="w", font=("Helvetica", 10, "bold"), bg=self.BLUE_AURA_BG)
            header_status.grid(row=0, column=1, padx=2, pady=2, sticky="w")

            for r_idx in range(rows_per_column):
                index = col_idx * rows_per_column + r_idx
                if index < n:
                    folder, status_text, seq_path = results[index]
                    status_bg_color = "lightgreen" if "OK" in status_text else "salmon"
                    if "Read Error" in status_text: status_bg_color = "lightcoral"

                    folder_btn = tk.Button(
                        col_frame, text=folder, width=25, anchor="w",
                        relief="groove", borderwidth=1, padx=2, bg=self.BLUE_AURA_BG,
                        activebackground=self.BLUE_AURA_BUTTON, cursor="hand2",
                        highlightthickness=0,
                        command=lambda p=seq_path: self.open_folder_files_in_firefox(p)
                    )
                    folder_btn.bind(
                        "<Button-3>",
                        lambda e, p=seq_path: self.show_folder_context_menu(e, p)
                    )
                    folder_btn.grid(row=r_idx + 1, column=0, padx=1, pady=1, sticky="nsew")
                    label_status = tk.Button(
                        col_frame, text=status_text, width=20, anchor="w",
                        bg=status_bg_color, activebackground=status_bg_color,
                        relief="groove", borderwidth=1, padx=2,
                        state=tk.DISABLED, disabledforeground="black",
                        highlightthickness=0
                    )
                    label_status.grid(row=r_idx + 1, column=1, padx=1, pady=1, sticky="nsew")

        self.results_frame.update_idletasks()
        self.results_canvas.config(scrollregion=self.results_canvas.bbox("all"))

        if self.monitoring:
            self.after_id = self.after(30000, self.scan_sequences)

    def start_monitoring(self):
        if not self.target_directory:
            tkMessageBox.showerror("Error", "Please select a target directory first.")
            return
        if not len(self.patterns_tree.get_children()) > 0:
            tkMessageBox.showerror("Error", "Please add at least one file pattern before monitoring.")
            return

        self.monitoring = True
        self.start_monitor_button.config(state="disabled")
        self.stop_monitor_button.config(state="normal")
        self.scan_sequences()

    def stop_monitoring(self):
        self.monitoring = False
        self.start_monitor_button.config(state="normal")
        self.stop_monitor_button.config(state="disabled")
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None

if __name__ == "__main__":
    root = tk.Tk()
    root.title("xNav_Line_QC Sequence Checker (Python 2.7)")
    app = SequenceCheckerApp(master=root)
    app.mainloop()