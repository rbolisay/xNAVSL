#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Ai assisted Code by RBolisay
import Tkinter as tk
import tkFileDialog
import tkMessageBox
import os
import csv
import json
import subprocess
import threading
import datetime
from collections import defaultdict
import math # Needed for floor in format_bytes
try:
    import Queue
except ImportError:
    import queue as Queue

# --- Helper Function for Formatting Bytes ---
def format_bytes(size):
    """ Formats bytes into KB, MB, GB, TB """
    if size is None: return ""
    if size == 0: return "  0 bytes"
    power = 1024.0
    n = 0
    power_labels = {0 : ' bytes', 1: ' KB', 2: ' MB', 3: ' GB', 4: ' TB'}
    while size >= power and n < len(power_labels) - 1:
        size /= power
        n += 1
    if n == 0:
        formatted_size = "%d%s" % (int(size), power_labels[n])
    else:
        formatted_size = "%.1f%s" % (size, power_labels[n])
    return formatted_size

def format_datetime(timestamp):
    """ Formats epoch timestamp as dd/mm/yyyy hh:mm """
    if timestamp is None: return ""
    try:
        return datetime.datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""

# --- Helper Function for Sequence Checking ---
def is_sequential(key1, key2):
    """ Checks if key2 is the direct sequential successor of key1. """
    if len(key1) != len(key2) or not key1 or not key2: return False
    try: return int(key2) == int(key1) + 1
    except ValueError:
        if key1[:-1] == key2[:-1]:
            try: return ord(key2[-1]) == ord(key1[-1]) + 1
            except TypeError: return False
        else: return False

# --- Core Sorting Logic (Now returns total size) ---
def sort_and_check_files(target_dir, sort_range_str, sort_order, expected_duplicates, csv_output_path=None):
    """
    Sorts files, gets size, checks expected duplicate counts/zero-bytes/sequence gaps, optionally outputs CSV.
    Returns: tuple: (sorted_files_with_raw_sizes_list, ignored_items_list, warnings_list,
                     total_files_count_in_dir, total_sorted_size_bytes)
    """
    if not os.path.isdir(target_dir):
        return [], [], ["Error: Target directory not found."], 0, 0 # Added 0 for total size

    # --- Parse Sort Range ---
    try:
        start_str, end_str = sort_range_str.split('-')
        start_index = int(start_str) - 1
        end_index = int(end_str)
        if start_index < 0 or start_index >= end_index: raise ValueError("Invalid range")
    except ValueError:
        # Return 0 for total size on error
        return [], [], ["Error: Invalid sort range format. Use 'start-end' (e.g., '11-14')."], 0, 0

    # --- Read Directory ---
    try: all_items = os.listdir(target_dir)
    except OSError as e:
        return [], [], ["Error reading directory: {}".format(e)], 0, 0 # Added 0 for total size

    temp_files_data = [] # list of (key, filename, size_in_bytes, modified_timestamp)
    ignored_items = []
    total_files_count_in_dir = 0

    for item_name in all_items:
        item_path = os.path.join(target_dir, item_name)
        if os.path.isfile(item_path):
            total_files_count_in_dir += 1 # Count all files found in dir
            try:
                filesize = os.path.getsize(item_path)
                modified_time = os.path.getmtime(item_path)
                if len(item_name) < end_index: raise IndexError("Filename too short for range")
                sort_key = item_name[start_index:end_index]
                temp_files_data.append((sort_key, item_name, filesize, modified_time))
            except IndexError: ignored_items.append(item_name + " (Filename too short for range)")
            except OSError as e: ignored_items.append(item_name + " (Error getting size: {})".format(e))
            except Exception as e: ignored_items.append(item_name + " (Error processing: {})".format(e))
        elif os.path.isdir(item_path): ignored_items.append(item_name + " (Directory)")
        else: ignored_items.append(item_name + " (Not a file or directory)")

    # --- Sort Files ---
    reverse_sort = (sort_order == "Descending")
    try:
        temp_files_data.sort(key=lambda x: x[0], reverse=reverse_sort)
    except Exception as e:
         processed_for_output = [(fname, fsize, modified_time) for _, fname, fsize, modified_time in temp_files_data]
         # Calculate total size even if sorting fails (size of successfully read files)
         total_size_partial = sum(fsize for _, _, fsize, _ in temp_files_data)
         return processed_for_output, ignored_items, ["Error during sorting process: {}".format(e)], total_files_count_in_dir, total_size_partial

    # --- Process Sorted Data: Checks & Calculate Total Size ---
    sorted_files_with_sizes_list = [] # List of (filename, filesize_in_bytes, modified_timestamp) tuples
    warnings_list = set()
    key_counts = defaultdict(int)
    zero_byte_files = []
    total_sorted_size_bytes = 0 # Initialize total size counter

    for sort_key, filename, filesize, modified_time in temp_files_data:
        # Track count for each sort key so it can be validated after scanning.
        key_counts[sort_key] += 1
        # Check Zero Bytes
        if filesize == 0:
            zero_byte_files.append(filename)

        # Add to final list for display
        sorted_files_with_sizes_list.append((filename, filesize, modified_time))
        # Accumulate total size for successfully sorted/processed files
        total_sorted_size_bytes += filesize

    # Flag any sort key whose file count does not exactly match the expected value.
    for sort_key, actual_count in key_counts.items():
        if actual_count != expected_duplicates:
            warnings_list.add(
                "Warning: Expected {} file(s) for key '{}', found {}.".format(
                    expected_duplicates, sort_key, actual_count
                )
            )

    # Add zero-byte warning if needed
    if zero_byte_files:
        max_warn_files = 5; warn_msg_files = zero_byte_files[:max_warn_files]
        ellipsis = "..." if len(zero_byte_files) > max_warn_files else ""
        warnings_list.add("Warning: Zero-byte files found: {}{}".format(", ".join(warn_msg_files), ellipsis))

    # --- Check for Sequence Gaps ---
    if temp_files_data:
        unique_sorted_keys = []; seen_keys = set()
        key_source = temp_files_data if sort_order == "Ascending" else reversed(temp_files_data)
        for key, _, _, _ in key_source:
             if key not in seen_keys: unique_sorted_keys.append(key); seen_keys.add(key)
        if sort_order == "Descending": unique_sorted_keys.reverse()
        for i in xrange(1, len(unique_sorted_keys)):
            prev_key = unique_sorted_keys[i-1]; curr_key = unique_sorted_keys[i]
            if not is_sequential(prev_key, curr_key):
                warnings_list.add("Warning: Sequence gap detected between '{}' and '{}'.".format(prev_key, curr_key))

    # --- Optional CSV Output ---
    if csv_output_path:
        try:
            with open(csv_output_path, 'wb') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Sort Key', 'Filename', 'Size (bytes)', 'Modified Date Time'])
                for sort_key, filename, filesize, modified_time in temp_files_data:
                    writer.writerow([sort_key, filename, filesize, format_datetime(modified_time)]) # Write raw bytes and formatted time
        except IOError as e: warnings_list.add("Error writing CSV: {}".format(e))
        except Exception as e: warnings_list.add("Unexpected error during CSV export: {}".format(e))

    # Return all results including the total size
    return sorted_files_with_sizes_list, ignored_items, list(warnings_list), total_files_count_in_dir, total_sorted_size_bytes


# --- GUI Application Class ---
class XSortXCheckApp:
    def __init__(self, master):
        self.master = master
        master.title("xSortxCheck - File Sorter and Checker")

        # --- Define Colors ---
        self.gui_bg_color = "#B4C8E1"  # Blue Aura
        self.button_bg_color = "#8DA9CC" # Distinct, slightly darker blue
        self.button_fg_color = "black"   # Black text for buttons

        # Apply background color to the master window
        master.configure(bg=self.gui_bg_color)

        # --- Variables ---
        self.target_dir_var = tk.StringVar()
        self.csv_dir_var = tk.StringVar()
        self.sort_range_var = tk.StringVar(value="11-14")
        self.sort_order_var = tk.StringVar(value="Ascending")
        self.expected_duplicates_var = tk.StringVar(value="1")
        self.compression_method_var = tk.StringVar(value="gzip")
        self.max_compression_threads_var = tk.StringVar(value="1")
        self.default_csv_dir = "/usr/local/trinop/dbase/links/qcfiles/Misc"
        self.default_window_width = 845
        self.default_window_height = 550
        self.settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xSort_settings.json")
        self.current_sorted_files_data = []
        self.delete_confirm_window = None
        self.delete_confirm_listbox = None
        self.pending_delete_files = []
        self.compression_in_progress = False
        self.compression_result_queue = None

        # --- Main Frame ---
        frame = tk.Frame(master, padx=10, pady=10, bg=self.gui_bg_color)
        frame.pack(fill=tk.BOTH, expand=True)

        # --- Description Label ---
        desc_label = tk.Label(frame, text="Utility to sort files based on filename characters, check duplicates/size/sequence gaps.", justify=tk.LEFT, bg=self.gui_bg_color)
        desc_label.grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))

        # --- Target Directory Widgets ---
        tk.Label(frame, text="Target Directory:", bg=self.gui_bg_color).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.target_entry = tk.Entry(frame, textvariable=self.target_dir_var, width=50)
        self.target_entry.grid(row=1, column=1, sticky=tk.EW, pady=2)
        self.target_button = tk.Button(frame, text="Browse...", command=self.browse_target_dir, bg=self.button_bg_color, fg=self.button_fg_color)
        self.target_button.grid(row=1, column=2, padx=(5,0), pady=2)

        # --- CSV Output Widgets ---
        tk.Label(frame, text="CSV Output (Optional):", bg=self.gui_bg_color).grid(row=2, column=0, sticky=tk.W, pady=2)
        self.csv_entry = tk.Entry(frame, textvariable=self.csv_dir_var, width=50)
        self.csv_entry.grid(row=2, column=1, sticky=tk.EW, pady=2)
        self.csv_button = tk.Button(frame, text="Browse...", command=self.browse_csv_dir, bg=self.button_bg_color, fg=self.button_fg_color)
        self.csv_button.grid(row=2, column=2, padx=(5,0), pady=2)

        # --- Sorting Parameters Frame ---
        params_frame = tk.LabelFrame(frame, text="Sorting Parameters", padx=5, pady=5, bg=self.gui_bg_color)
        params_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=5)

        tk.Label(params_frame, text="Filename Char Range (e.g., 11-14):", bg=self.gui_bg_color).grid(row=0, column=0, sticky=tk.W)
        self.range_entry = tk.Entry(params_frame, textvariable=self.sort_range_var, width=10)
        self.range_entry.grid(row=0, column=1, sticky=tk.W, padx=5)

        tk.Label(params_frame, text="Sort Order:", bg=self.gui_bg_color).grid(row=1, column=0, sticky=tk.W)
        # For OptionMenu, background of the menu itself is harder to style consistently across platforms.
        # We style the containing frame (params_frame) and the button part of OptionMenu.
        self.order_menu = tk.OptionMenu(params_frame, self.sort_order_var, "Ascending", "Descending")
        self.order_menu.config(bg=self.button_bg_color, fg=self.button_fg_color, activebackground=self.button_bg_color, highlightthickness=0)
        self.order_menu["menu"].config(bg=self.button_bg_color, fg=self.button_fg_color) # Style dropdown menu
        self.order_menu.grid(row=1, column=1, sticky=tk.W, padx=5)

        tk.Label(params_frame, text="Max Duplicate Expected:", bg=self.gui_bg_color).grid(row=2, column=0, sticky=tk.W)
        self.duplicates_entry = tk.Entry(params_frame, textvariable=self.expected_duplicates_var, width=5)
        self.duplicates_entry.grid(row=2, column=1, sticky=tk.W, padx=5)

        # --- Zip Parameters Frame ---
        zip_params_frame = tk.LabelFrame(frame, text="Zip Parameters", padx=5, pady=5, bg=self.gui_bg_color)
        zip_params_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=5)

        tk.Label(zip_params_frame, text="Zip Action:", bg=self.gui_bg_color).grid(row=0, column=0, sticky=tk.W)
        self.compress_button = tk.Button(zip_params_frame, text="Zip Selected", command=self.compress_selected_files, width=20, height=2, bg=self.button_bg_color, fg=self.button_fg_color, state=tk.DISABLED)
        self.compress_button.grid(row=0, column=1, sticky=tk.W, padx=5)

        tk.Label(zip_params_frame, text="Zip Method:", bg=self.gui_bg_color).grid(row=1, column=0, sticky=tk.W)
        zip_method_frame = tk.Frame(zip_params_frame, bg=self.gui_bg_color)
        zip_method_frame.grid(row=1, column=1, sticky=tk.W, padx=5)
        self.compress_method_buttons = []
        for column_index, method_name in enumerate(("gzip", "pigz", "bzip2")):
            method_button = tk.Radiobutton(
                zip_method_frame,
                text=method_name,
                variable=self.compression_method_var,
                value=method_name,
                bg=self.gui_bg_color,
                activebackground=self.gui_bg_color,
                highlightthickness=0,
                anchor=tk.W
            )
            method_button.grid(row=0, column=column_index, sticky=tk.W, padx=(0, 10))
            self.compress_method_buttons.append(method_button)

        tk.Label(zip_params_frame, text="Max Concurrent zip:", bg=self.gui_bg_color).grid(row=2, column=0, sticky=tk.W)
        self.max_compression_threads_entry = tk.Entry(zip_params_frame, textvariable=self.max_compression_threads_var, width=5)
        self.max_compression_threads_entry.grid(row=2, column=1, sticky=tk.W, padx=5)

        # --- Action Buttons ---
        actions_frame = tk.Frame(frame, bg=self.gui_bg_color)
        actions_frame.grid(row=5, column=0, columnspan=3, pady=10)
        self.sort_button = tk.Button(actions_frame, text="Sort & Check Files", command=self.perform_sort, width=20, height=2, bg=self.button_bg_color, fg=self.button_fg_color)
        self.sort_button.pack(side=tk.LEFT)
        self.delete_button = tk.Button(actions_frame, text="Delete Selected", command=self.delete_selected_files, width=20, height=2, bg=self.button_bg_color, fg=self.button_fg_color, state=tk.DISABLED)
        self.delete_button.pack(side=tk.LEFT, padx=(10, 0))

        # --- Results Frame ---
        results_frame = tk.LabelFrame(frame, text="Results", padx=5, pady=5, bg=self.gui_bg_color)
        results_frame.grid(row=6, column=0, columnspan=3, sticky=tk.NSEW, pady=(5,0))
        frame.grid_rowconfigure(6, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        self.sorted_files_label = tk.Label(results_frame, text="Sorted Files (0)", anchor=tk.W, bg=self.gui_bg_color)
        self.sorted_files_label.grid(row=0, column=0, sticky=tk.EW, pady=(0, 5))
        self.results_header_label = tk.Label(
            results_frame,
            text="",
            anchor=tk.W,
            justify=tk.LEFT,
            bg=self.gui_bg_color
        )
        self.results_header_label.grid(row=1, column=0, sticky=tk.EW)

        try:
            fixed_font = ("Courier New", 10)
            self.results_header_label.config(font=fixed_font)
            self.results_listbox = tk.Listbox(results_frame, selectmode=tk.EXTENDED, exportselection=False, width=90, height=10, font=fixed_font, bg="white", fg="black")
            self.results_text = tk.Text(results_frame, wrap=tk.NONE, width=90, height=5, state=tk.DISABLED, font=fixed_font, bg="white", fg="black") # Explicitly set text area colors
        except tk.TclError:
            print("Warning: Courier New font not found, using default. Alignment might be imperfect.")
            self.results_listbox = tk.Listbox(results_frame, selectmode=tk.EXTENDED, exportselection=False, width=90, height=10, bg="white", fg="black")
            self.results_text = tk.Text(results_frame, wrap=tk.NONE, width=90, height=5, state=tk.DISABLED, bg="white", fg="black") # Explicitly set text area colors

        self.results_listbox.bind('<<ListboxSelect>>', self.update_action_buttons_state)
        self.results_yscroll = tk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.on_results_scroll)
        self.results_xscroll = tk.Scrollbar(results_frame, orient=tk.HORIZONTAL, command=self.on_results_xscroll)
        self.results_listbox.configure(yscrollcommand=self.results_yscroll.set, xscrollcommand=self.results_xscroll.set)
        self.results_text.configure(yscrollcommand=self.results_yscroll.set, xscrollcommand=self.results_xscroll.set)
        self.results_listbox.grid(row=2, column=0, sticky=tk.NSEW)
        self.results_text.grid(row=3, column=0, sticky=tk.NSEW, pady=(5, 0))
        self.results_yscroll.grid(row=2, column=1, rowspan=2, sticky=tk.NS)
        self.results_xscroll.grid(row=4, column=0, sticky=tk.EW)
        results_frame.grid_rowconfigure(2, weight=3)
        results_frame.grid_rowconfigure(3, weight=2)
        results_frame.grid_columnconfigure(0, weight=1)

        # --- Status Bar ---
        status_frame = tk.Frame(frame, bg=self.gui_bg_color)
        status_frame.grid(row=7, column=0, columnspan=3, sticky=tk.NSEW, pady=(5,0))
        frame.grid_rowconfigure(7, weight=0)
        self.total_files_label = tk.Label(status_frame, text="Total Files in Directory: 0", bg=self.gui_bg_color)
        self.total_files_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 10), pady=(0, 5))

        warnings_frame = tk.LabelFrame(status_frame, text="Warnings", padx=5, pady=5, bg=self.gui_bg_color)
        warnings_frame.grid(row=1, column=0, sticky=tk.EW)
        status_frame.grid_columnconfigure(0, weight=1)
        warnings_frame.grid_columnconfigure(0, weight=1)

        try:
            fixed_font = ("Courier New", 10)
            self.warnings_text = tk.Text(warnings_frame, wrap=tk.WORD, width=75, height=10, state=tk.DISABLED, font=fixed_font, bg="white", fg="red")
        except tk.TclError:
            self.warnings_text = tk.Text(warnings_frame, wrap=tk.WORD, width=75, height=10, state=tk.DISABLED, bg="white", fg="red")
        self.warnings_scroll = tk.Scrollbar(warnings_frame, orient=tk.VERTICAL, command=self.warnings_text.yview)
        self.warnings_text.configure(yscrollcommand=self.warnings_scroll.set)
        self.warnings_text.grid(row=0, column=0, sticky=tk.EW)
        self.warnings_scroll.grid(row=0, column=1, sticky=tk.NS)

        self.load_settings()
        self.update_action_buttons_state()
        self.master.protocol("WM_DELETE_WINDOW", self.on_close)

    def browse_target_dir(self):
        directory = tkFileDialog.askdirectory(title="Select Target Directory")
        if directory: self.target_dir_var.set(directory)

    def browse_csv_dir(self):
        filepath = tkFileDialog.asksaveasfilename(
            initialdir=self.default_csv_dir, title="Save CSV Output As",
            defaultextension=".csv", initialfile="xSortxCheck_output.csv",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")) )
        if filepath: self.csv_dir_var.set(filepath)

    def load_settings(self):
        if not os.path.isfile(self.settings_path):
            self.master.geometry("{}x{}".format(self.default_window_width, self.default_window_height))
            return
        try:
            with open(self.settings_path, 'rb') as settings_file:
                settings = json.load(settings_file)
        except Exception:
            return

        self.target_dir_var.set(settings.get("target_dir", ""))
        self.csv_dir_var.set(settings.get("csv_path", ""))
        self.sort_range_var.set(settings.get("sort_range", "11-14"))
        self.sort_order_var.set(settings.get("sort_order", "Ascending"))
        self.expected_duplicates_var.set(settings.get("expected_duplicates", "1"))
        self.compression_method_var.set(settings.get("compression_method", "gzip"))
        self.max_compression_threads_var.set(settings.get("max_compression_threads", "1"))

        geometry = settings.get("window_geometry")
        if geometry:
            try:
                self.master.geometry(str(geometry))
            except Exception:
                pass

        if settings.get("window_state") == "zoomed":
            try:
                self.master.state("zoomed")
            except Exception:
                pass

    def save_settings(self):
        window_state = "normal"
        try:
            window_state = self.master.state()
        except Exception:
            pass

        geometry = ""
        try:
            if window_state == "zoomed":
                self.master.state("normal")
                self.master.update_idletasks()
                geometry = self.master.winfo_geometry()
                self.master.state("zoomed")
            else:
                self.master.update_idletasks()
                geometry = self.master.winfo_geometry()
        except Exception:
            geometry = ""

        settings = {
            "target_dir": self.target_dir_var.get(),
            "csv_path": self.csv_dir_var.get(),
            "sort_range": self.sort_range_var.get(),
            "sort_order": self.sort_order_var.get(),
            "expected_duplicates": self.expected_duplicates_var.get(),
            "compression_method": self.compression_method_var.get(),
            "max_compression_threads": self.max_compression_threads_var.get(),
            "window_geometry": geometry,
            "window_state": window_state,
        }

        try:
            with open(self.settings_path, 'wb') as settings_file:
                settings_file.write(json.dumps(settings, indent=2, sort_keys=True))
        except Exception:
            pass

    def on_close(self):
        self.save_settings()
        self.close_delete_confirm_window()
        self.master.destroy()

    def on_results_scroll(self, *args):
        self.results_listbox.yview(*args)
        self.results_text.yview(*args)

    def on_results_xscroll(self, *args):
        self.results_listbox.xview(*args)
        self.results_text.xview(*args)

    def clear_results(self):
        self.current_sorted_files_data = []
        self.sorted_files_label.config(text="Sorted Files (0)")
        self.results_header_label.config(text="")
        self.results_listbox.delete(0, tk.END)
        self.results_text.config(state=tk.NORMAL)
        self.results_text.delete('1.0', tk.END)
        self.results_text.config(state=tk.DISABLED)
        self.update_action_buttons_state()

    def set_warnings_text(self, warnings):
        self.warnings_text.config(state=tk.NORMAL)
        self.warnings_text.delete('1.0', tk.END)
        if warnings:
            self.warnings_text.insert(tk.END, "\n".join(warnings))
        self.warnings_text.config(state=tk.DISABLED)

    def append_results_text(self, header, items):
        self.results_text.config(state=tk.NORMAL)
        if self.results_text.get('1.0', tk.END).strip():
            self.results_text.insert(tk.END, "\n" + "="*30 + "\n\n")
        self.results_text.insert(tk.END, header + ":\n")
        if items:
            for item in items:
                try: display_string = u"  • {}\n".format(unicode(item))
                except NameError: display_string = u"  • {}\n".format(item)
                self.results_text.insert(tk.END, display_string)
        else:
            self.results_text.insert(tk.END, "  (None)\n")
        self.results_text.config(state=tk.DISABLED)

    def display_results(self, header, items, is_file_list=False):
        """ Displays items. If is_file_list, items are (filename, raw_bytes_size, modified_timestamp) tuples. """
        if is_file_list:
            self.current_sorted_files_data = list(items)
            self.sorted_files_label.config(text=header)
            self.results_header_label.config(
                text=u"{0:<48} {1:>12}  {2:<16}".format("Filename", "File Size", "Date and Time")
            )
            self.results_listbox.delete(0, tk.END)
            for filename, filesize_bytes, modified_time in items:
                formatted_size = format_bytes(filesize_bytes)
                formatted_time = format_datetime(modified_time)
                try: fname_unicode = unicode(filename)
                except NameError: fname_unicode = str(filename)
                self.results_listbox.insert(tk.END, u"{0:<48} {1:>12}  {2:<16}".format(fname_unicode, formatted_size, formatted_time))
            self.update_action_buttons_state()
            return
        self.append_results_text(header, items)

    def is_compressed_filename(self, filename):
        filename_lower = filename.lower()
        return filename_lower.endswith((".gz", ".bz2", ".zip", ".tgz", ".tbz", ".tbz2"))

    def get_selected_compressed_files(self, selected_files=None):
        if selected_files is None:
            selected_files = self.get_selected_filenames()
        return [filename for filename in selected_files if self.is_compressed_filename(filename)]

    def update_action_buttons_state(self, event=None):
        selected_files = self.get_selected_filenames()
        has_selection = bool(selected_files)
        has_compressed_selection = bool(self.get_selected_compressed_files(selected_files))
        buttons_state = tk.DISABLED if self.compression_in_progress else tk.NORMAL
        self.sort_button.config(state=buttons_state)
        self.delete_button.config(state=tk.NORMAL if has_selection and not self.compression_in_progress else tk.DISABLED)
        self.compress_button.config(text="Unzip Selected" if has_compressed_selection else "Zip Selected")
        self.compress_button.config(state=tk.NORMAL if has_selection and not self.compression_in_progress else tk.DISABLED)
        method_buttons_state = tk.DISABLED if self.compression_in_progress or has_compressed_selection else tk.NORMAL
        for method_button in self.compress_method_buttons:
            method_button.config(state=method_buttons_state)
        self.max_compression_threads_entry.config(state=buttons_state)

    def get_selected_filenames(self):
        selected_files = []
        for index in self.results_listbox.curselection():
            try:
                selected_files.append(self.current_sorted_files_data[int(index)][0])
            except (ValueError, IndexError, TypeError):
                pass
        return selected_files

    def close_delete_confirm_window(self):
        if self.delete_confirm_window and self.delete_confirm_window.winfo_exists():
            self.delete_confirm_window.destroy()
        self.delete_confirm_window = None
        self.delete_confirm_listbox = None
        self.pending_delete_files = []

    def refresh_delete_confirm_window(self):
        if not (self.delete_confirm_window and self.delete_confirm_window.winfo_exists()):
            return
        self.delete_confirm_listbox.delete(0, tk.END)
        for filename in self.pending_delete_files:
            self.delete_confirm_listbox.insert(tk.END, filename)
        self.position_delete_confirm_window()
        self.delete_confirm_window.lift()
        self.delete_confirm_window.focus_force()

    def position_delete_confirm_window(self):
        if not (self.delete_confirm_window and self.delete_confirm_window.winfo_exists()):
            return
        self.master.update_idletasks()
        self.delete_confirm_window.update_idletasks()
        master_x = self.master.winfo_rootx()
        master_y = self.master.winfo_rooty()
        master_width = self.master.winfo_width()
        master_height = self.master.winfo_height()
        window_width = self.delete_confirm_window.winfo_reqwidth()
        window_height = self.delete_confirm_window.winfo_reqheight()
        pos_x = master_x + max(0, (master_width - window_width) // 2)
        pos_y = master_y + max(0, (master_height - window_height) // 2)
        self.delete_confirm_window.geometry("+{}+{}".format(pos_x, pos_y))

    def delete_selected_files(self):
        selected_files = self.get_selected_filenames()
        if not selected_files:
            tkMessageBox.showwarning("No Selection", "Select one or more files from the results list first.")
            return

        self.pending_delete_files = selected_files
        if self.delete_confirm_window and self.delete_confirm_window.winfo_exists():
            self.refresh_delete_confirm_window()
            return

        confirm_window = tk.Toplevel(self.master)
        confirm_window.title("Confirm Delete Selected Files")
        confirm_window.configure(bg=self.gui_bg_color)
        confirm_window.transient(self.master)
        confirm_window.protocol("WM_DELETE_WINDOW", self.close_delete_confirm_window)
        self.delete_confirm_window = confirm_window

        tk.Label(confirm_window, text="Delete the following file(s)?", anchor=tk.W, bg=self.gui_bg_color).pack(fill=tk.X, padx=10, pady=(10, 5))
        self.delete_confirm_listbox = tk.Listbox(confirm_window, width=80, height=12, selectmode=tk.BROWSE, exportselection=False, bg="white", fg="black")
        self.delete_confirm_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        buttons_frame = tk.Frame(confirm_window, bg=self.gui_bg_color)
        buttons_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Button(buttons_frame, text="OK", width=12, command=self.confirm_delete_selected, bg=self.button_bg_color, fg=self.button_fg_color).pack(side=tk.RIGHT)
        tk.Button(buttons_frame, text="Cancel", width=12, command=self.close_delete_confirm_window, bg=self.button_bg_color, fg=self.button_fg_color).pack(side=tk.RIGHT, padx=(0, 5))

        self.refresh_delete_confirm_window()

    def confirm_delete_selected(self):
        if not self.pending_delete_files:
            self.close_delete_confirm_window()
            return

        target_dir = self.target_dir_var.get()
        deleted_files = []
        delete_errors = []
        for filename in self.pending_delete_files:
            file_path = os.path.join(target_dir, filename)
            try:
                os.remove(file_path)
                deleted_files.append(filename)
            except OSError as e:
                delete_errors.append("{} ({})".format(filename, e))

        self.close_delete_confirm_window()

        if deleted_files:
            tkMessageBox.showinfo("Delete Complete", "Deleted {} file(s).".format(len(deleted_files)))
            self.perform_sort()

        if delete_errors:
            tkMessageBox.showwarning("Delete Errors", "Some files could not be deleted:\n{}".format("\n".join(delete_errors)))

    def get_compression_command(self, method, file_path):
        if method == "gzip":
            return ["gzip", "-f", file_path]
        if method == "pigz":
            return ["pigz", "-f", file_path]
        if method == "bzip2":
            return ["bzip2", "-f", file_path]
        raise ValueError("Unsupported compression method: {}".format(method))

    def get_unzip_command(self, file_path, target_dir):
        filename_lower = file_path.lower()
        if filename_lower.endswith(".zip"):
            return ["unzip", "-o", file_path, "-d", target_dir]
        if filename_lower.endswith((".gz", ".tgz")):
            return ["gzip", "-df", file_path]
        if filename_lower.endswith((".bz2", ".tbz", ".tbz2")):
            return ["bzip2", "-df", file_path]
        raise ValueError("Unsupported compressed file: {}".format(os.path.basename(file_path)))

    def run_compression_batch(self, target_dir, selected_files, mode, method, max_threads, skipped_files, result_queue):
        work_queue = Queue.Queue()
        results = {"processed": [], "errors": [], "method": method, "mode": mode, "skipped": skipped_files}
        results_lock = threading.Lock()

        for filename in selected_files:
            work_queue.put(filename)

        def compression_worker():
            while True:
                try:
                    filename = work_queue.get_nowait()
                except Queue.Empty:
                    break

                file_path = os.path.join(target_dir, filename)
                try:
                    if not os.path.isfile(file_path):
                        raise IOError("File not found")
                    if mode == "unzip":
                        command = self.get_unzip_command(file_path, target_dir)
                    else:
                        command = self.get_compression_command(method, file_path)
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    _stdout_data, stderr_data = process.communicate()
                    if process.returncode != 0:
                        error_message = stderr_data.strip() or "Compression command failed."
                        raise RuntimeError(error_message)
                    with results_lock:
                        results["processed"].append(filename)
                except Exception as e:
                    with results_lock:
                        results["errors"].append("{} ({})".format(filename, e))

        worker_count = max(1, min(max_threads, len(selected_files)))
        workers = []
        for _index in range(worker_count):
            worker = threading.Thread(target=compression_worker)
            worker.daemon = True
            worker.start()
            workers.append(worker)

        for worker in workers:
            worker.join()

        result_queue.put(results)

    def finish_compression(self, results):
        self.compression_in_progress = False
        self.update_action_buttons_state()

        if results.get("processed"):
            self.perform_sort(show_csv_message=False)
            if results.get("mode") == "unzip":
                tkMessageBox.showinfo(
                    "Unzip Complete",
                    "Unzipped {} file(s).".format(len(results["processed"]))
                )
            else:
                tkMessageBox.showinfo(
                    "Compression Complete",
                    "Compressed {} file(s) using {}.".format(len(results["processed"]), results["method"])
                )

        if results.get("skipped"):
            self.append_results_text(
                "Skipped Files",
                ["Prioritized unzip and skipped non-zipped file(s): {}".format(", ".join(results["skipped"]))]
            )

        if results.get("errors"):
            if results.get("mode") == "unzip":
                tkMessageBox.showwarning(
                    "Unzip Errors",
                    "Some files could not be unzipped:\n{}".format("\n".join(results["errors"]))
                )
            else:
                tkMessageBox.showwarning(
                    "Compression Errors",
                    "Some files could not be compressed:\n{}".format("\n".join(results["errors"]))
                )

    def check_compression_status(self):
        if not self.compression_result_queue:
            return
        try:
            results = self.compression_result_queue.get_nowait()
        except Queue.Empty:
            self.master.after(200, self.check_compression_status)
            return

        self.compression_result_queue = None
        self.finish_compression(results)

    def compress_selected_files(self):
        selected_files = self.get_selected_filenames()
        if not selected_files:
            tkMessageBox.showwarning("No Selection", "Select one or more files from the results list first.")
            return

        target_dir = self.target_dir_var.get()
        if not target_dir or not os.path.isdir(target_dir):
            tkMessageBox.showerror("Input Error", "Please select a valid target directory.")
            return

        try:
            max_threads = int(self.max_compression_threads_var.get())
            if max_threads <= 0:
                raise ValueError()
        except ValueError:
            tkMessageBox.showerror("Input Error", "Max Concurrent zip must be a positive integer.")
            return

        method = self.compression_method_var.get()
        if method not in ("gzip", "pigz", "bzip2"):
            tkMessageBox.showerror("Input Error", "Zip Method must be gzip, pigz, or bzip2.")
            return

        compressed_files = self.get_selected_compressed_files(selected_files)
        mode = "unzip" if compressed_files else "zip"
        target_files = compressed_files if compressed_files else selected_files
        skipped_files = [filename for filename in selected_files if filename not in target_files]

        self.compression_in_progress = True
        self.update_action_buttons_state()
        if mode == "unzip":
            status_lines = ["Unzipping {} file(s) with {} concurrent job(s).".format(len(target_files), max_threads)]
            if skipped_files:
                status_lines.append("Skipping {} non-zipped file(s) because unzip takes priority.".format(len(skipped_files)))
            self.append_results_text("Unzip", status_lines)
        else:
            self.append_results_text(
                "Compression",
                ["Compressing {} file(s) using {} with {} concurrent job(s).".format(len(target_files), method, max_threads)]
            )

        self.compression_result_queue = Queue.Queue()
        compression_thread = threading.Thread(
            target=self.run_compression_batch,
            args=(target_dir, target_files, mode, method, max_threads, skipped_files, self.compression_result_queue)
        )
        compression_thread.daemon = True
        compression_thread.start()
        self.master.after(200, self.check_compression_status)

    def perform_sort(self, show_csv_message=True):
        target_dir = self.target_dir_var.get()
        csv_path = self.csv_dir_var.get() or None
        sort_range = self.sort_range_var.get()
        sort_order = self.sort_order_var.get()
        max_dup_str = self.expected_duplicates_var.get()

        if not target_dir: tkMessageBox.showerror("Input Error", "Please select a target directory."); return
        try:
            expected_duplicates = int(max_dup_str)
            if expected_duplicates < 0: raise ValueError()
        except ValueError: tkMessageBox.showerror("Input Error", "Max Duplicate Expected must be a non-negative integer."); return

        self.clear_results()
        self.results_text.config(state=tk.NORMAL)
        self.results_text.insert('1.0', "Processing files...\n")
        self.results_text.config(state=tk.DISABLED)
        self.set_warnings_text([])
        self.total_files_label.config(text="Total Files in Directory: 0")
        self.master.update_idletasks()

        sorted_files_data, ignored_items, warnings, total_files_count, total_sorted_size = sort_and_check_files(
            target_dir, sort_range, sort_order, expected_duplicates, csv_path
        )

        self.clear_results()

        fatal_errors = [w for w in warnings if "Error:" in w and "CSV" not in w]
        if fatal_errors and not sorted_files_data and not ignored_items:
             tkMessageBox.showerror("Processing Error", "\n".join(fatal_errors))
             self.total_files_label.config(text="Total Files in Directory: {}".format(total_files_count))
        else:
            self.display_results("Sorted Files ({})".format(len(sorted_files_data)), sorted_files_data, is_file_list=True)

            if sorted_files_data:
                total_size_formatted = format_bytes(total_sorted_size)
                self.append_results_text("Summary", [u"Total Size of Sorted Files: {}".format(total_size_formatted)])

            if ignored_items:
                self.display_results("Ignored/Skipped Items ({})".format(len(ignored_items)), ignored_items, is_file_list=False)

            self.total_files_label.config(text="Total Files in Directory: {}".format(total_files_count))

            display_warnings = sorted(list(warnings))
            self.set_warnings_text(display_warnings)

            csv_write_errors = [w for w in warnings if "Error writing CSV" in w]
            if show_csv_message and csv_path and not csv_write_errors and not fatal_errors: tkMessageBox.showinfo("CSV Output Successful", "CSV file saved to:\n{}".format(csv_path))
            elif csv_path and csv_write_errors: tkMessageBox.showwarning("CSV Error", "\n".join(csv_write_errors))


# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    root.minsize(650, 550) # You can adjust the minimum size if needed
    app = XSortXCheckApp(root)
    root.mainloop()
