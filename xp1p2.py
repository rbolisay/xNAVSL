#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Ai assisted Code by RBolisay
"""
A Python 2.7 Tkinter GUI for performing the QC process.
It allows you to select directories, specify a sequence range,
displays results in a table with clear borders, and shows a status area.
Error values are displayed in red.
The output CSV filename is modified to include the sequence range.
"""

import os
import json
import re
import threading
import time
import Queue

import Tkinter as tk
import tkFileDialog
import ttk
import ScrolledText

# Default paths
default_P111_DIR = "/usr/local/trinop/dbase/links/currentjob/P111/P111_SSREG"
default_P211_DIR = "/usr/local/trinop/dbase/links/currentjob/P211"
default_BACKUP_DIR = "/usr/local/trinop/dbase/links/backup_processed"
default_FESB_DIR = "/usr/local/trinop/dbase/links/fes_backup"
default_OUTPUT_CSV = "/usr/local/trinop/qcfiles/Misc/xp1p2.csv"
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".xp1p2_settings.json")

# Define error strings that should be shown in red.
error_strings = {"Missing!", "SP range BAD", "Missing Backup!", "Missing FESB!", "mismatch", "Backup subline BAD"}
COMPRESSED_EXTENSIONS = (".gz", ".bz2")

# Define GUI colors
GUI_BACKGROUND_COLOR = "#B4C8E1"  # Blue Aura
BUTTON_BACKGROUND_COLOR = "#8DA9CC" # Distinct, slightly darker blue
BUTTON_TEXT_COLOR = "black"

def get_files_in_range(directory, extension, seq_start, seq_end):
    """Retrieves files in the directory matching the sequence range."""
    file_map = {}
    try:
        files = [f for f in os.listdir(directory) if f.endswith(extension) and f[:4].isdigit()]
        files.sort(key=lambda x: os.path.getmtime(os.path.join(directory, x)), reverse=True)
        for f in files:
            try:
                seq_num = int(f[:4])
            except:
                continue
            if seq_start <= seq_num <= seq_end:
                if seq_num in file_map:
                    file_map[seq_num] = "Multiple Files!"
                else:
                    file_map[seq_num] = os.path.join(directory, f)
    except Exception as e:
        print("Error accessing {}: {}".format(directory, e))
    return file_map

def extract_shotpoints(file_path, record_type, shotpoint_index):
    """
    Extracts shotpoint numbers, preserving the file order, and also computes
    the numeric minimum and maximum.
    
    Returns a tuple:
      (display_FSP, display_LSP, numeric_min, numeric_max, line_name, subline)
      
    - display_FSP and display_LSP are the first and last shotpoints as encountered in the file.
    - numeric_min and numeric_max are the minimum and maximum shotpoint values (for QC checks).
    """
    if not file_path or file_path in ["Missing!", "Multiple Files!"]:
        return "Missing!", "Missing!", "Missing!", "Missing!", "Missing!", "Missing!"
    shotpoints = []
    display_list = []  # to preserve the order of appearance
    line_name, subline = "Missing!", "Missing!"
    try:
        f = open(file_path, "r")
    except Exception:
        return "Missing!", "Missing!", "Missing!", "Missing!", "Missing!", "Missing!"
    for line in f:
        parts = line.strip().split(",")
        if line.startswith(record_type) and len(parts) > shotpoint_index:
            try:
                val = int(parts[shotpoint_index])
                shotpoints.append(val)
                display_list.append(val)
            except ValueError:
                pass
        if "LINENAME/SUBLINE" in line:
            name_parts = line.split("=")[-1].strip().split("/")
            if len(name_parts) > 2:
                line_name = name_parts[1]
                subline = name_parts[2]
    f.close()
    if not shotpoints:
        return "Missing!", "Missing!", "Missing!", "Missing!", line_name, subline
    # Preserve display order exactly as in the file.
    display_FSP = display_list[0]
    display_LSP = display_list[-1]
    # For QC check, use the numeric min and max.
    numeric_min = min(shotpoints)
    numeric_max = max(shotpoints)
    return display_FSP, display_LSP, numeric_min, numeric_max, line_name, subline

def strip_compression_extension(filename):
    """Removes supported compression extensions from a filename."""
    lower_name = filename.lower()
    for extension in COMPRESSED_EXTENSIONS:
        if lower_name.endswith(extension):
            return filename[:-len(extension)]
    return filename

def directory_contains_token(directory, token):
    """Checks filenames, including .gz/.bz2 stems, for the requested token."""
    token = token.lower()
    try:
        for filename in os.listdir(directory):
            normalized_name = strip_compression_extension(filename).lower()
            if token in filename.lower() or token in normalized_name:
                return True
    except Exception as e:
        print("Error accessing {}: {}".format(directory, e))
    return False

def extract_backup_subline(filename):
    """Extracts the quoted backup subline from the filename when present."""
    normalized_name = strip_compression_extension(filename)
    match = re.search(r'"([^"]+)"', normalized_name)
    if match:
        return match.group(1).lower()
    return None

def backup_filename_matches_subline(filename, subline):
    """Checks whether a backup filename matches the expected subline."""
    normalized_name = strip_compression_extension(filename)
    extracted_subline = extract_backup_subline(normalized_name)
    if extracted_subline is not None:
        return extracted_subline == subline.lower()
    lowered_name = normalized_name.lower()
    return '"{}"'.format(subline.lower()) in lowered_name or subline.lower() in lowered_name

def check_backup_exists(p111_subline, p211_subline, backup_dir):
    """Checks whether any backup filename matches the P111/P211 subline."""
    expected_sublines = []
    for subline in (p111_subline, p211_subline):
        if subline not in ["Missing!", "Multiple Files!"] and subline not in expected_sublines:
            expected_sublines.append(subline)
    if not expected_sublines:
        return "Missing Backup!"
    try:
        backup_files = os.listdir(backup_dir)
    except Exception as e:
        print("Error accessing {}: {}".format(backup_dir, e))
        return "Missing Backup!"
    if not backup_files:
        return "Missing Backup!"
    for filename in backup_files:
        for subline in expected_sublines:
            if backup_filename_matches_subline(filename, subline):
                return "Backup GOOD"
    return "Backup subline BAD"

def check_fesb_exists(sequence, fesb_dir):
    """Checks if a FESB file, zipped or plain, exists in the FESB directory."""
    seq_str = "{:04d}".format(sequence)
    return "FESB GOOD" if directory_contains_token(fesb_dir, "rt_{}".format(seq_str)) else "Missing FESB!"

def save_csv(file_path, data, output_queue):
    """Saves the processed data to a CSV file."""
    try:
        directory = os.path.dirname(file_path)
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(file_path, "w") as f:
            f.write("Sequence Number,Filename P111,Line Name P111,Subline P111,FSP P111,LSP P111,"
                    "Filename P211,Line Name P211,Subline P211,FSP P211,LSP P211,Subline XCheck,SP Range XCheck,Backup XCheck,FESB XCheck\n")
            for row in data:
                f.write(",".join(map(str, row)) + "\n")
        output_queue.put(("status", "CSV saved to {}\n".format(file_path)))
    except Exception as e:
        output_queue.put(("status", "Error writing CSV file: {}\n".format(e)))

class QCWorker(threading.Thread):
    """Worker thread that performs the QC process."""
    def __init__(self, p111_dir, p211_dir, backup_dir, fesb_dir, output_csv, seq_range, output_queue):
        threading.Thread.__init__(self)
        self.p111_dir = p111_dir
        self.p211_dir = p211_dir
        self.backup_dir = backup_dir
        self.fesb_dir = fesb_dir
        self.output_csv = output_csv
        self.seq_range = seq_range
        self.output_queue = output_queue

    def run(self):
        try:
            seq_start, seq_end = map(int, self.seq_range.split("-"))
        except Exception:
            self.output_queue.put(("status", "Invalid sequence range! Please use format '1-5'\n"))
            return
        self.output_queue.put(("status", "Starting QC process for sequence range {} to {}\n".format(seq_start, seq_end)))
        p111_files = get_files_in_range(self.p111_dir, ".p111", seq_start, seq_end)
        p211_files = get_files_in_range(self.p211_dir, ".p211", seq_start, seq_end)
        extracted_data = []
        for seq in range(seq_start, seq_end + 1):
            p111_file = p111_files.get(seq, "Missing!")
            p211_file = p211_files.get(seq, "Missing!")
            # Get shotpoint values preserving file order for display, and numeric min/max for checking.
            fsp_p111_disp, lsp_p111_disp, fsp_p111_num, lsp_p111_num, line_p111, sub_p111 = \
                extract_shotpoints(p111_file, "S1", 4)
            fsp_p211_disp, lsp_p211_disp, fsp_p211_num, lsp_p211_num, line_p211, sub_p211 = \
                extract_shotpoints(p211_file, "E2", 6)
            backup_xcheck = check_backup_exists(sub_p111, sub_p211, self.backup_dir)
            fesb_xcheck = check_fesb_exists(seq, self.fesb_dir)
            # Implement SP range check using the numeric min and max values.
            try:
                if int(fsp_p111_num) >= int(fsp_p211_num) and int(lsp_p111_num) <= int(lsp_p211_num):
                    sp_range_xcheck = "SP range GOOD"
                else:
                    sp_range_xcheck = "SP range BAD"
            except Exception:
                sp_range_xcheck = "SP range BAD"
            # Build the result row using display values.
            result_line = [
                "{:04d}".format(seq),
                os.path.basename(p111_file),
                line_p111,
                sub_p111,
                fsp_p111_disp,
                lsp_p111_disp,
                os.path.basename(p211_file),
                line_p211,
                sub_p211,
                fsp_p211_disp,
                lsp_p211_disp,
                "Match",  # Subline XCheck currently hardcoded as "Match"
                sp_range_xcheck,
                backup_xcheck,
                fesb_xcheck
            ]
            extracted_data.append(result_line)
            # Send the row as a tuple ("row", list_of_values)
            self.output_queue.put(("row", result_line))
            time.sleep(0.1)  # simulate processing delay

        # Modify the output CSV filename to include the sequence range.
        base, ext = os.path.splitext(self.output_csv)
        output_csv_modified = base + "_" + self.seq_range + ext
        save_csv(output_csv_modified, extracted_data, self.output_queue)
        self.output_queue.put(("status", "QC process completed.\n"))

class QCAppPanel(tk.Frame):
    """
    Main QC UI as a Frame so it can be packed into xNAVSL or into a standalone Tk window.
    geometry_save_widget: when set (standalone root Tk), window geometry is saved/restored; when None (embedded), not.
    """
    def __init__(self, master, geometry_save_widget=None):
        tk.Frame.__init__(self, master, background=GUI_BACKGROUND_COLOR)
        self._geometry_save_widget = geometry_save_widget

        # Configure panel grid: two rows (controls and results)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Create a frame for controls at the top left.
        self.controls_frame = tk.Frame(self, background=GUI_BACKGROUND_COLOR)
        self.controls_frame.grid(row=0, column=0, sticky="nw", padx=5, pady=5)

        # Define StringVars for paths and sequence range.
        self.p111_dir = tk.StringVar(value=default_P111_DIR)
        self.p211_dir = tk.StringVar(value=default_P211_DIR)
        self.backup_dir = tk.StringVar(value=default_BACKUP_DIR)
        self.fesb_dir = tk.StringVar(value=default_FESB_DIR)
        self.output_csv = tk.StringVar(value=default_OUTPUT_CSV)
        self.seq_range = tk.StringVar(value="1-5")
        self._saved_geometry = None
        self.load_settings()

        # Populate the controls frame.
        row = 0
        # P111 Directory
        tk.Label(self.controls_frame, text="P111 Directory:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.p111_dir, width=50).grid(row=row, column=1)
        p111_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_p111, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        p111_browse_button.grid(row=row, column=2)

        row += 1
        # P211 Directory
        tk.Label(self.controls_frame, text="P211 Directory:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.p211_dir, width=50).grid(row=row, column=1)
        p211_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_p211, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        p211_browse_button.grid(row=row, column=2)

        row += 1
        # Backup Directory
        tk.Label(self.controls_frame, text="Backup Directory:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.backup_dir, width=50).grid(row=row, column=1)
        backup_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_backup, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        backup_browse_button.grid(row=row, column=2)

        row += 1
        # FESB Directory
        tk.Label(self.controls_frame, text="FESB Directory:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.fesb_dir, width=50).grid(row=row, column=1)
        fesb_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_fesb, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        fesb_browse_button.grid(row=row, column=2)

        row += 1
        # Output CSV File
        tk.Label(self.controls_frame, text="Output CSV File:", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.output_csv, width=50).grid(row=row, column=1)
        output_browse_button = tk.Button(self.controls_frame, text="Browse", command=self.browse_output, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        output_browse_button.grid(row=row, column=2)
        
        row += 1
        # Sequence Range
        tk.Label(self.controls_frame, text="Sequence Range (e.g., 1-5):", background=GUI_BACKGROUND_COLOR, foreground="black").grid(row=row, column=0, sticky="w")
        tk.Entry(self.controls_frame, textvariable=self.seq_range, width=20).grid(row=row, column=1, sticky="w")

        row += 1
        # Start QC Button
        self.start_button = tk.Button(self.controls_frame, text="Start QC", command=self.start_qc, background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR)
        self.start_button.grid(row=row, column=0, columnspan=3, pady=10)

        # Create a frame for the results.
        self.results_frame = tk.Frame(self, background=GUI_BACKGROUND_COLOR)
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.results_frame.grid_rowconfigure(0, weight=1)
        self.results_frame.grid_columnconfigure(0, weight=1)

        # Setup custom style for the Treeview and other ttk widgets.
        style = ttk.Style()
        # Configure Treeview style
        style.configure("mystyle.Treeview", borderwidth=1, relief="solid", rowheight=25, background="white", fieldbackground="white") # Treeview data area
        style.map("mystyle.Treeview", background=[('selected', BUTTON_BACKGROUND_COLOR)]) # Selected item color
        style.configure("mystyle.Treeview.Heading", borderwidth=1, relief="solid", background=BUTTON_BACKGROUND_COLOR, foreground=BUTTON_TEXT_COLOR) # Treeview headings
        
        # Configure Scrollbar style for consistency, though direct background might not apply easily to all parts
        style.configure("TScrollbar", background=BUTTON_BACKGROUND_COLOR, troughcolor=GUI_BACKGROUND_COLOR)


        # Define the columns.
        self.columns = ["Sequence Number", "Filename P111", "Line Name P111", "Subline P111",
                        "FSP P111", "LSP P111", "Filename P211", "Line Name P211", "Subline P211",
                        "FSP P211", "LSP P211", "Subline XCheck", "SP Range XCheck", "Backup XCheck", "FESB XCheck"]

        # Create the Treeview widget.
        self.tree = ttk.Treeview(self.results_frame, columns=self.columns, show="headings", style="mystyle.Treeview")
        # Set up headings and column widths.
        col_widths = [120, 150, 120, 120, 100, 100, 150, 120, 120, 100, 100, 120, 120, 120, 120]
        for col, width in zip(self.columns, col_widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="center")
        
        # Configure a tag for error rows to have red text.
        self.tree.tag_configure("error", foreground="red")
        
        # Attach vertical and horizontal scrollbars.
        vsb = ttk.Scrollbar(self.results_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.results_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        # Create a status area below the Treeview for miscellaneous messages.
        self.status_text = ScrolledText.ScrolledText(self.results_frame, height=5, wrap=tk.WORD, background="white", foreground="black")
        self.status_text.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5,0))
        self.status_text.configure(state="disabled")

        # Setup a thread-safe queue for communication from the worker thread.
        self.output_queue = Queue.Queue()
        self.after(100, self.process_queue)
        if self._geometry_save_widget is not None and self._saved_geometry:
            try:
                self._geometry_save_widget.geometry(self._saved_geometry)
            except Exception:
                pass
        if self._geometry_save_widget is None:
            self.bind("<Destroy>", self._on_embed_destroy)

    def load_settings(self):
        """Loads the last-used GUI settings from disk."""
        if not os.path.isfile(SETTINGS_FILE):
            return
        try:
            f = open(SETTINGS_FILE, "r")
            settings = json.load(f)
            f.close()
        except Exception as e:
            print("Error loading settings from {}: {}".format(SETTINGS_FILE, e))
            return
        self.p111_dir.set(settings.get("p111_dir", default_P111_DIR))
        self.p211_dir.set(settings.get("p211_dir", default_P211_DIR))
        self.backup_dir.set(settings.get("backup_dir", default_BACKUP_DIR))
        self.fesb_dir.set(settings.get("fesb_dir", default_FESB_DIR))
        self.output_csv.set(settings.get("output_csv", default_OUTPUT_CSV))
        self.seq_range.set(settings.get("seq_range", "1-5"))
        self._saved_geometry = settings.get("window_geometry")

    def save_settings(self):
        """Saves the current GUI settings to disk."""
        settings = {
            "p111_dir": self.p111_dir.get(),
            "p211_dir": self.p211_dir.get(),
            "backup_dir": self.backup_dir.get(),
            "fesb_dir": self.fesb_dir.get(),
            "output_csv": self.output_csv.get(),
            "seq_range": self.seq_range.get(),
        }
        if self._geometry_save_widget is not None:
            try:
                settings["window_geometry"] = self._geometry_save_widget.geometry()
            except Exception:
                settings["window_geometry"] = None
        try:
            f = open(SETTINGS_FILE, "w")
            json.dump(settings, f, indent=2, sort_keys=True)
            f.close()
        except Exception as e:
            print("Error saving settings to {}: {}".format(SETTINGS_FILE, e))

    def on_root_close(self):
        """Standalone window: save and destroy the Tk root."""
        self.save_settings()
        try:
            self.winfo_toplevel().destroy()
        except Exception:
            pass

    def _on_embed_destroy(self, event):
        # Tk may deliver a distinct wrapper; compare paths.
        try:
            if str(event.widget) != str(self):
                return
        except Exception:
            return
        try:
            self.save_settings()
        except Exception:
            pass

    def browse_p111(self):
        directory = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.p111_dir.get()
        )
        if directory:
            self.p111_dir.set(directory)

    def browse_p211(self):
        directory = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.p211_dir.get()
        )
        if directory:
            self.p211_dir.set(directory)

    def browse_backup(self):
        directory = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.backup_dir.get()
        )
        if directory:
            self.backup_dir.set(directory)

    def browse_fesb(self):
        directory = tkFileDialog.askdirectory(
            parent=self.winfo_toplevel(), initialdir=self.fesb_dir.get()
        )
        if directory:
            self.fesb_dir.set(directory)

    def browse_output(self):
        file_path = tkFileDialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            initialfile=self.output_csv.get(),
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if file_path:
            self.output_csv.set(file_path)

    def start_qc(self):
        # Disable the Start button to avoid multiple runs.
        self.start_button.config(state="disabled")
        # Clear previous results in the tree and status area.
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", tk.END)
        self.status_text.configure(state="disabled")
        # Start the QC process in a new thread.
        worker = QCWorker(self.p111_dir.get(), self.p211_dir.get(), self.backup_dir.get(),
                          self.fesb_dir.get(), self.output_csv.get(), self.seq_range.get(), self.output_queue)
        worker.start()

    def process_queue(self):
        """Polls the output queue and updates the Treeview and status area."""
        while True:
            try:
                item = self.output_queue.get_nowait()
            except Queue.Empty:
                break
            else:
                msg_type, content = item
                if msg_type == "row":
                    # Check if any cell contains an error value.
                    if any(str(cell) in error_strings for cell in content): # Ensure cell is compared as string
                        self.tree.insert("", "end", values=content, tags=("error",))
                    else:
                        self.tree.insert("", "end", values=content)
                elif msg_type == "status":
                    self.status_text.configure(state="normal")
                    self.status_text.insert(tk.END, content)
                    self.status_text.see(tk.END)
                    self.status_text.configure(state="disabled")
                    # Re-enable the Start button when QC process is completed.
                    if "QC process completed" in content or "Invalid sequence range!" in content: # Also re-enable on error
                        self.start_button.config(state="normal")
        self.after(100, self.process_queue)


class QCApp(tk.Tk):
    """Standalone top-level window (same behavior as before refactor)."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.title("xP1P2 Final QC")
        self.geometry("1800x700")
        self.minsize(1800, 700)
        self.configure(background=GUI_BACKGROUND_COLOR)
        self.panel = QCAppPanel(self, geometry_save_widget=self)
        self.panel.pack(fill=tk.BOTH, expand=True)
        self.protocol("WM_DELETE_WINDOW", self.panel.on_root_close)


def xnavsl_embed(master):
    """Called by xNAVSL to show this tool inside a tab (no second Tk)."""
    panel = QCAppPanel(master, geometry_save_widget=None)
    panel.pack(fill=tk.BOTH, expand=True)


if __name__ == "__main__":
    app = QCApp()
    app.mainloop()
