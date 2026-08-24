#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Ai assisted code by RBolisay
# xTapeManager - Python 2.7 GUI for Tape Operations
# Requires Tkinter, mt, and tar

try:
    import Tkinter as tk
    import tkFileDialog
    import tkMessageBox
    import ttk  # For themed widgets like Combobox
except ImportError:
    print("ERROR: Tkinter or ttk module not found. Please ensure Tkinter is installed correctly for Python 2.7.")
    exit(1)

import os
import subprocess
import glob
import threading
import Queue
import sys # For sys.getfilesystemencoding()
import traceback # For detailed error printing
import math # For size formatting

# --- Configuration ---
DEFAULT_OUTPUT_DIR = "/usr/local/trinop/dbase/links/qcfiles/Tape_ReadBack"
# Use a more specific pattern if needed, e.g., '/dev/nst*' for non-rewinding devices
TAPE_DEVICE_PATTERN = "/dev/IBMtape*"

# --- Constants for Status ---
STATUS_ONLINE = "ONLINE"
STATUS_NO_TAPE = "NO_TAPE"
STATUS_OFFLINE = "OFFLINE"
STATUS_ERROR = "ERROR"

# --- Color Configuration ---
GUI_BACKGROUND_COLOR = "#B4C8E1" # User specified background
BUTTON_BG_COLOR = "#8DA9CC"      # User specified button background
BUTTON_ACTIVE_BG_COLOR = "#7C9BCD" # Slightly darker for active button state
TEXT_COLOR = "#000000"          # Black text for good contrast

# --- Helper Functions ---

def format_size(size_bytes):
   """Formats size in bytes to human-readable string."""
   if size_bytes == 0:
       return "0 B"
   size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
   i = int(math.floor(math.log(size_bytes, 1024)))
   p = math.pow(1024, i)
   s = round(size_bytes / p, 2)
   return "%s %s" % (s, size_name[i])

def get_total_size(paths_unicode, status_queue):
    """
    Calculates the total size of files and folders in the list.
    Expects a list of unicode paths.
    Returns total size in bytes.
    """
    total_size = 0
    fs_encoding = sys.getfilesystemencoding()
    status_queue.put("Calculating total size...") # Log start

    for item_unicode in paths_unicode:
        try:
            # Encode path for os functions
            item_bytes = item_unicode.encode(fs_encoding)

            if os.path.islink(item_bytes):
                 # Optional: Decide how to handle symlinks (ignore, follow, add link size?)
                 # status_queue.put(u"Skipping symlink size calculation for: {}".format(item_unicode))
                 continue # Skipping symlinks for now
            elif os.path.isfile(item_bytes):
                total_size += os.path.getsize(item_bytes)
            elif os.path.isdir(item_bytes):
                for dirpath, dirnames, filenames in os.walk(item_bytes):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        # Check if it's not a symlink before getting size
                        if not os.path.islink(fp):
                             try:
                                 total_size += os.path.getsize(fp)
                             except OSError as e:
                                 # Log error getting size of specific file but continue
                                 status_queue.put(u"Warning: Could not get size of file {}: {}".format(fp.decode(fs_encoding, 'replace'), e.strerror))
        except UnicodeEncodeError:
             status_queue.put(u"ERROR: Cannot encode path for size calculation: {}".format(item_unicode))
        except OSError as e:
             status_queue.put(u"ERROR: Cannot access path for size calculation {}: {}".format(item_unicode, e.strerror))
        except Exception as e:
             status_queue.put(u"ERROR: Unexpected error calculating size for {}: {}".format(item_unicode, e))

    status_queue.put("Total size calculation complete.") # Log end
    return total_size


def run_command(command_list, status_queue, blocking=True):
    """
    Runs a shell command using subprocess, capturing output to status_queue.
    Expects command_list to contain byte strings.
    Returns the process return code.
    Handles potential encoding issues with command output.
    NOTE: This captures stdout/stderr, does NOT redirect stdout to a file.
    """
    # Log command using repr for clarity (decode for logging)
    try:
        # Decode using filesystem encoding, replace errors
        log_command = u" ".join(repr(arg.decode(sys.getfilesystemencoding(), 'replace')) for arg in command_list)
    except Exception: # Fallback if decoding fails
        log_command = u" ".join(map(repr, command_list))

    try:
        status_queue.put(u"Running command: {}".format(log_command))

        # Ensure all args are byte strings (should be passed correctly now)
        safe_command_list = [str(arg) for arg in command_list]

        if blocking:
            # Capture stdout and stderr
            process = subprocess.Popen(safe_command_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate() # Blocks until command finishes

            # Decode output using default filesystem encoding, ignore errors
            stdout_decoded = stdout.decode(sys.getfilesystemencoding(), 'ignore') if stdout else ""
            stderr_decoded = stderr.decode(sys.getfilesystemencoding(), 'ignore') if stderr else ""

            if stdout_decoded:
                status_queue.put("--- STDOUT ---")
                for line in stdout_decoded.splitlines():
                    status_queue.put(line)
            if stderr_decoded:
                status_queue.put("--- STDERR ---")
                for line in stderr_decoded.splitlines():
                    status_queue.put(line)

            status_queue.put("Command finished with exit code: {}".format(process.returncode))
            return process.returncode
        else:
            # Non-blocking execution (more complex to manage GUI updates)
            status_queue.put("Non-blocking execution not fully implemented in this example.")
            return -1 # Indicate not implemented/error

    except OSError as e:
        status_queue.put(u"ERROR: OS Error running command - {}: {}".format(e.strerror, log_command))
        # Check if it's a "No such file or directory" error for the command itself
        if e.errno == 2: # errno.ENOENT
             status_queue.put(u"Hint: Make sure the command '{}' is installed and in your PATH.".format(command_list[0]))
        return -1
    except Exception as e:
        status_queue.put(u"ERROR: Unexpected error running command - {}: {}".format(e, log_command))
        return -1

def check_tape_status(device_bytes, status_queue):
    """
    Checks the status of a single tape device using 'mt'.
    Handles potential encoding issues with command output.
    Returns a status string ("ONLINE", "NO_TAPE", "OFFLINE", "ERROR")
    and the raw status message (unicode).
    """
    # device_bytes argument should be byte string
    command = ['mt', '-f', device_bytes, 'status'] # Correct order for status check
    device_unicode = device_bytes.decode(sys.getfilesystemencoding(), 'replace') # For error messages

    try:
        # Use check_output for simpler status check
        output_bytes = subprocess.check_output(command, stderr=subprocess.STDOUT)
        # Decode output using default filesystem encoding, ignore errors
        output_unicode = output_bytes.decode(sys.getfilesystemencoding(), 'ignore')
        output_upper = output_unicode.upper()

        # Check for specific states first (used for button enabling)
        is_online_indicator = "ONLINE" in output_upper or "READY" in output_upper
        is_no_tape_indicator = "NO TAPE" in output_upper
        is_offline_indicator = "NOT ONLINE" in output_upper or "OFFLINE" in output_upper

        # Determine detailed status string
        if is_online_indicator and not is_no_tape_indicator and not is_offline_indicator:
            status = STATUS_ONLINE
        elif is_no_tape_indicator:
            status = STATUS_NO_TAPE
        elif is_offline_indicator:
             status = STATUS_OFFLINE
        # Add more specific error checks based on 'mt' output if needed
        # elif "SOME_OTHER_ERROR" in output_upper:
        #     status = STATUS_ERROR
        else:
            # If none of the above but command succeeded, treat as OFFLINE/Unknown
            status = STATUS_OFFLINE
            status_queue.put(u"Warning: Unknown status for {}. Treating as OFFLINE. Raw output:\n{}".format(device_unicode, output_unicode))


        return status, output_unicode # Return status string and the full message (unicode)

    except subprocess.CalledProcessError as e:
        # Command failed (non-zero exit code)
        error_output = e.output.decode(sys.getfilesystemencoding(), 'ignore') if e.output else "No error output from mt"
        status_queue.put(u"ERROR: 'mt status' command failed for {}. Output:\n{}".format(device_unicode, error_output))
        # Determine if it's likely offline or a different error
        if "offline" in error_output.lower() or "not online" in error_output.lower():
             return STATUS_OFFLINE, error_output
        else:
             return STATUS_ERROR, error_output
    except OSError as e:
        # Command not found or other OS error
        error_msg = u"ERROR: 'mt' command OS error checking {}: {}".format(device_unicode, e.strerror)
        if e.errno == 2: # No such file or directory
             error_msg += u"\nHint: Make sure 'mt' command is installed and in your PATH."
        status_queue.put(error_msg) # Log this critical error
        return STATUS_ERROR, error_msg
    except Exception as e:
        # Any other unexpected error
        error_msg = u"ERROR: Unexpected error checking status for {}: {}".format(device_unicode, e)
        status_queue.put(error_msg) # Log this critical error
        return STATUS_ERROR, error_msg


# --- Main Application Class ---

class TapeManagerApp:
    def __init__(self, master):
        self.master = master
        master.title("xTapeManager")
        master.configure(bg=GUI_BACKGROUND_COLOR) # Set main window background

        # --- Variables ---
        self.operation_mode = tk.StringVar(value="write") # 'write', 'read', 'extract'
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar(value=DEFAULT_OUTPUT_DIR)
        self.csv_output_dir = tk.StringVar(value=DEFAULT_OUTPUT_DIR) # Default CSV dir same as output
        self.selected_files = [] # List to hold full paths of files/dirs to write (stored as unicode)
        self.total_size_var = tk.StringVar(value="Total Size: 0 B") # Variable for total size label
        self.available_tape_devices = [] # List of detected /dev/IBMtape* (byte strings)
        self.selectable_tape_devices = [] # List of devices passing filter (unicode strings)
        self.selected_tape_device = tk.StringVar()
        self.status_queue = Queue.Queue() # For thread-safe status updates
        self.worker_thread = None # To keep track of the running operation thread

        # --- GUI Layout ---
        # Configure grid weights for main frames to allow resizing
        master.grid_rowconfigure(4, weight=1) # Status frame (row 4) expands vertically
        master.grid_columnconfigure(0, weight=1) # Allow horizontal expansion

        # Main frames using grid layout
        self.top_frame = tk.Frame(master, padx=10, pady=5, bg=GUI_BACKGROUND_COLOR)
        self.top_frame.grid(row=0, column=0, sticky="ew")

        self.mode_frame = tk.Frame(master, padx=10, pady=5, bg=GUI_BACKGROUND_COLOR)
        self.mode_frame.grid(row=1, column=0, sticky="ew")

        self.options_frame = tk.Frame(master, padx=10, pady=5, bg=GUI_BACKGROUND_COLOR)
        self.options_frame.grid(row=2, column=0, sticky="nsew") 
        self.options_frame.grid_columnconfigure(0, weight=1) 

        self.tape_control_frame = tk.Frame(master, padx=10, pady=10, bg=GUI_BACKGROUND_COLOR)
        self.tape_control_frame.grid(row=3, column=0, sticky="ew")
        self.tape_control_frame.grid_columnconfigure(1, weight=1) 

        self.status_frame = tk.Frame(master, padx=10, pady=5, bg=GUI_BACKGROUND_COLOR)
        self.status_frame.grid(row=4, column=0, sticky="nsew") 
        self.status_frame.grid_rowconfigure(1, weight=1) 
        self.status_frame.grid_columnconfigure(0, weight=1) 

        self.action_frame = tk.Frame(master, padx=10, pady=10, bg=GUI_BACKGROUND_COLOR)
        self.action_frame.grid(row=5, column=0, sticky="ew")
        self.action_frame.grid_columnconfigure(0, weight=1)


        # --- Top Frame: Description ---
        desc_label = tk.Label(self.top_frame, text="xTapeManager: Write files to tape or Read/Extract from tape.", justify=tk.LEFT, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR)
        desc_label.pack(anchor=tk.W) 

        # --- Mode Frame: Operation Selection ---
        tk.Radiobutton(self.mode_frame, text="Write to Tape", variable=self.operation_mode, value="write", command=self.update_options_ui, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR, activebackground=GUI_BACKGROUND_COLOR, selectcolor=BUTTON_BG_COLOR).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(self.mode_frame, text="Read Tape (List)", variable=self.operation_mode, value="read", command=self.update_options_ui, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR, activebackground=GUI_BACKGROUND_COLOR, selectcolor=BUTTON_BG_COLOR).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(self.mode_frame, text="Extract Tape", variable=self.operation_mode, value="extract", command=self.update_options_ui, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR, activebackground=GUI_BACKGROUND_COLOR, selectcolor=BUTTON_BG_COLOR).pack(side=tk.LEFT, padx=5)

        # --- Options Frame: Mode-Specific Widgets ---
        self.write_widgets = []
        self.read_extract_widgets = []
        self._create_write_options()
        self._create_read_extract_options()

        # --- Tape Control Frame (using grid) ---
        tape_label = tk.Label(self.tape_control_frame, text="Tape Device:", bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR)
        tape_label.grid(row=0, column=0, padx=(0, 5), sticky=tk.W)

        s = ttk.Style()
        s.configure('TCombobox', fieldbackground=GUI_BACKGROUND_COLOR, background=GUI_BACKGROUND_COLOR, foreground=TEXT_COLOR) # Try to style combobox
        self.tape_device_combobox = ttk.Combobox(self.tape_control_frame, textvariable=self.selected_tape_device, state="readonly", width=30) 
        self.tape_device_combobox.grid(row=0, column=1, padx=5, sticky=tk.EW) 
        self.tape_device_combobox.bind('<<ComboboxSelected>>', self.on_tape_device_selected)


        tape_button_frame = tk.Frame(self.tape_control_frame, bg=GUI_BACKGROUND_COLOR)
        tape_button_frame.grid(row=0, column=2, sticky=tk.E)

        self.refresh_button = tk.Button(tape_button_frame, text="Refresh List", command=self.refresh_tape_devices, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        self.refresh_button.pack(side=tk.LEFT, padx=(10, 5)) 

        self.status_button = tk.Button(tape_button_frame, text="Status", command=self.tape_status, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        self.status_button.pack(side=tk.LEFT, padx=5)

        self.rewind_button = tk.Button(tape_button_frame, text="Rewind", command=self.tape_rewind, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        self.rewind_button.pack(side=tk.LEFT, padx=5)

        self.eject_button = tk.Button(tape_button_frame, text="Rew/Eject", command=self.tape_eject, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        self.eject_button.pack(side=tk.LEFT, padx=5)

        self.erase_button = tk.Button(tape_button_frame, text="Erase", command=self.tape_erase, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        self.erase_button.pack(side=tk.LEFT, padx=5)


        # --- Status Frame (using grid) ---
        status_label = tk.Label(self.status_frame, text="Status / Output:", bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR)
        status_label.grid(row=0, column=0, columnspan=2, sticky=tk.W)

        self.status_text = tk.Text(self.status_frame, height=10, width=80, state=tk.DISABLED, wrap=tk.WORD, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR)
        self.status_scroll = tk.Scrollbar(self.status_frame, command=self.status_text.yview, bg=GUI_BACKGROUND_COLOR, troughcolor=BUTTON_BG_COLOR) # troughcolor matches button
        self.status_text.config(yscrollcommand=self.status_scroll.set)

        self.status_text.grid(row=1, column=0, sticky="nsew") 
        self.status_scroll.grid(row=1, column=1, sticky="ns") 


        # --- Action Frame ---
        self.start_button = tk.Button(self.action_frame, text="Start Operation", command=self.start_operation, width=15, height=2, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        self.start_button.grid(row=0, column=0) 

        # --- Initial UI State ---
        self.update_options_ui()
        self._enable_controls(initial=True) 
        self.master.after(200, self.refresh_tape_devices)
        self.master.after(100, self.process_status_queue) 

    def _log_status(self, message):
        """Appends a message to the status text widget in a thread-safe way."""
        if not hasattr(self, 'status_text') or not self.status_text: 
            print("Debug log (status_text not ready): {}".format(message))
            return
        try:
            if not self.status_text.winfo_exists():
                 print("Debug log (status_text destroyed): {}".format(message))
                 return

            self.status_text.config(state=tk.NORMAL)
            if isinstance(message, str):
                 try:
                     unicode_message = unicode(message)
                 except UnicodeDecodeError:
                     unicode_message = message.decode(sys.getfilesystemencoding(), 'replace')
            elif isinstance(message, unicode):
                unicode_message = message
            else:
                unicode_message = unicode(str(message)) 

            self.status_text.insert(tk.END, unicode_message + u"\n")
            self.status_text.see(tk.END) 
            self.status_text.config(state=tk.DISABLED)
        except tk.TclError as e:
            print("Error updating status text: {}".format(e))
        except Exception as e:
             print("Unexpected error in _log_status: {}".format(e))


    def process_status_queue(self):
        """Processes messages from the status queue to update the GUI."""
        try:
            while True:
                msg = self.status_queue.get_nowait()
                self._log_status(msg) 
        except Queue.Empty:
            pass 
        except Exception as e:
            print("ERROR processing status queue: {}".format(e))
        finally:
            if self.worker_thread and not self.worker_thread.is_alive():
                self._log_status("--- Operation Thread Finished ---")
                self.worker_thread = None 
                if self.master.winfo_exists():
                    self._enable_controls(operational=False)
                    self.on_tape_device_selected(None) 


            if self.master.winfo_exists():
                 self.master.after(100, self.process_status_queue)

    def _disable_controls(self):
        """Disables buttons during long operations."""
        try:
            if hasattr(self, 'start_button') and self.start_button.winfo_exists(): self.start_button.config(state=tk.DISABLED)
            if hasattr(self, 'refresh_button') and self.refresh_button.winfo_exists(): self.refresh_button.config(state=tk.DISABLED)
            if hasattr(self, 'status_button') and self.status_button.winfo_exists(): self.status_button.config(state=tk.DISABLED)
            if hasattr(self, 'rewind_button') and self.rewind_button.winfo_exists(): self.rewind_button.config(state=tk.DISABLED)
            if hasattr(self, 'eject_button') and self.eject_button.winfo_exists(): self.eject_button.config(state=tk.DISABLED)
            if hasattr(self, 'erase_button') and self.erase_button.winfo_exists(): self.erase_button.config(state=tk.DISABLED) 
            if self.master.winfo_exists(): self.master.config(cursor="watch")
        except tk.TclError:
             self._log_status("Warning: Could not disable controls (window may be closing).")


    def _enable_controls(self, operational=True, initial=False):
        """
        Enables buttons after operations complete or based on status.
        'operational': Controls Rewind, Eject, Erase, Start Operation buttons.
        'initial': Special case for startup, disables operational buttons.
        """
        try:
            if not initial:
                if hasattr(self, 'refresh_button') and self.refresh_button.winfo_exists(): self.refresh_button.config(state=tk.NORMAL)
                if hasattr(self, 'status_button') and self.status_button.winfo_exists(): self.status_button.config(state=tk.NORMAL)

            op_state = tk.NORMAL if operational and not initial else tk.DISABLED
            if hasattr(self, 'start_button') and self.start_button.winfo_exists(): self.start_button.config(state=op_state)
            if hasattr(self, 'rewind_button') and self.rewind_button.winfo_exists(): self.rewind_button.config(state=op_state)
            if hasattr(self, 'eject_button') and self.eject_button.winfo_exists(): self.eject_button.config(state=op_state)
            if hasattr(self, 'erase_button') and self.erase_button.winfo_exists(): self.erase_button.config(state=op_state) 

            if not initial and self.master.winfo_exists():
                 self.master.config(cursor="")
        except tk.TclError:
             self._log_status("Warning: Could not enable/disable controls (window may be closing).")

    def _create_write_options(self):
        """Creates widgets for the 'Write' mode using grid."""
        input_dir_frame = tk.Frame(self.options_frame, bg=GUI_BACKGROUND_COLOR)
        input_dir_frame.grid_columnconfigure(1, weight=1) 
        tk.Label(input_dir_frame, text="Input Directory:", bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR).grid(row=0, column=0, sticky=tk.W, padx=2, pady=2)
        entry = tk.Entry(input_dir_frame, textvariable=self.input_dir, width=50, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR) # insertbackground for cursor
        entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.EW)
        button = tk.Button(input_dir_frame, text="Browse...", command=self.browse_input_dir, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        button.grid(row=0, column=2, padx=2, pady=2)
        self.write_widgets.append(input_dir_frame)

        file_list_frame = tk.Frame(self.options_frame, bg=GUI_BACKGROUND_COLOR)
        file_list_frame.grid_columnconfigure(0, weight=1) 
        file_list_frame.grid_rowconfigure(2, weight=1) 

        add_button_frame = tk.Frame(file_list_frame, bg=GUI_BACKGROUND_COLOR)
        add_button_frame.grid(row=0, column=0, pady=(5,2)) 

        add_files_button = tk.Button(add_button_frame, text="Add Files...", command=self.add_files, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        add_files_button.pack(side=tk.LEFT, padx=5) 

        add_folder_button = tk.Button(add_button_frame, text="Add Folder...", command=self.add_folder, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        add_folder_button.pack(side=tk.LEFT, padx=5) 

        self.total_size_label = tk.Label(file_list_frame, textvariable=self.total_size_var, justify=tk.LEFT, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR)
        self.total_size_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=(5,0))

        list_frame_inner = tk.Frame(file_list_frame, bg=GUI_BACKGROUND_COLOR) 
        list_frame_inner.grid(row=2, column=0, sticky="nsew", pady=5) 
        list_frame_inner.grid_rowconfigure(0, weight=1)
        list_frame_inner.grid_columnconfigure(0, weight=1)

        self.files_listbox = tk.Listbox(list_frame_inner, selectmode=tk.EXTENDED, width=70, height=6, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR, selectbackground=BUTTON_BG_COLOR, selectforeground=TEXT_COLOR)
        list_scroll = tk.Scrollbar(list_frame_inner, command=self.files_listbox.yview, bg=GUI_BACKGROUND_COLOR, troughcolor=BUTTON_BG_COLOR)
        self.files_listbox.config(yscrollcommand=list_scroll.set)

        self.files_listbox.grid(row=0, column=0, sticky="nsew")
        list_scroll.grid(row=0, column=1, sticky="ns")

        remove_button = tk.Button(file_list_frame, text="Remove Selected", command=self.remove_files, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        remove_button.grid(row=3, column=0, pady=(2, 5)) 

        self.write_widgets.append(file_list_frame)


    def _create_read_extract_options(self):
        """Creates widgets for the 'Read'/'Extract' modes using grid."""
        output_dir_frame = tk.Frame(self.options_frame, bg=GUI_BACKGROUND_COLOR)
        output_dir_frame.grid_columnconfigure(1, weight=1) 
        tk.Label(output_dir_frame, text="Output Directory:", bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR).grid(row=0, column=0, sticky=tk.W, padx=2, pady=2)
        entry_out = tk.Entry(output_dir_frame, textvariable=self.output_dir, width=50, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR) 
        entry_out.grid(row=0, column=1, padx=5, pady=2, sticky=tk.EW)
        button_out = tk.Button(output_dir_frame, text="Browse...", command=self.browse_output_dir, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        button_out.grid(row=0, column=2, padx=2, pady=2)
        self.read_extract_widgets.append(output_dir_frame)

        csv_dir_frame = tk.Frame(self.options_frame, bg=GUI_BACKGROUND_COLOR)
        csv_dir_frame.grid_columnconfigure(1, weight=1) 
        tk.Label(csv_dir_frame, text="CSV List Output Dir:", bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR).grid(row=1, column=0, sticky=tk.W, padx=2, pady=2) 
        entry_csv = tk.Entry(csv_dir_frame, textvariable=self.csv_output_dir, width=50, bg=GUI_BACKGROUND_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR) 
        entry_csv.grid(row=1, column=1, padx=5, pady=2, sticky=tk.EW) 
        button_csv = tk.Button(csv_dir_frame, text="Browse...", command=self.browse_csv_output_dir, bg=BUTTON_BG_COLOR, fg=TEXT_COLOR, activebackground=BUTTON_ACTIVE_BG_COLOR)
        button_csv.grid(row=1, column=2, padx=2, pady=2) 
        self.read_extract_widgets.append(csv_dir_frame)


    def update_options_ui(self):
        """Shows/hides widgets based on the selected operation mode using grid."""
        mode = self.operation_mode.get()

        all_widgets = list(self.write_widgets) + list(self.read_extract_widgets)
        for widget in all_widgets:
            if widget.winfo_exists() and widget.winfo_manager() == "grid":
                widget.grid_forget()

        if self.options_frame.winfo_exists():
            for i in range(self.options_frame.grid_size()[1]): 
                 self.options_frame.grid_rowconfigure(i, weight=0)

        row_index = 0
        if mode == "write":
            for widget in self.write_widgets:
                 if widget.winfo_exists(): 
                    sticky_val = "ew" 
                    is_list_frame_container = False
                    if widget == self.write_widgets[1]: 
                         sticky_val = "nsew" 
                         is_list_frame_container = True

                    widget.grid(row=row_index, column=0, sticky=sticky_val, pady=2, padx=2)

                    if self.options_frame.winfo_exists():
                        self.options_frame.grid_rowconfigure(row_index, weight=1 if is_list_frame_container else 0)

                    row_index += 1
        elif mode == "read" or mode == "extract":
            for widget in self.read_extract_widgets:
                 if widget.winfo_exists():
                    widget.grid(row=row_index, column=0, sticky="ew", pady=2, padx=2)
                    if self.options_frame.winfo_exists():
                        self.options_frame.grid_rowconfigure(row_index, weight=0) 
                    row_index += 1

        if self.options_frame.winfo_exists():
            max_rows = max(len(self.write_widgets), len(self.read_extract_widgets))
            for i in range(row_index, max_rows):
                 self.options_frame.grid_rowconfigure(i, weight=0)


    def browse_input_dir(self):
        """Opens a directory dialog to select the input directory."""
        initial = self.input_dir.get() or os.getcwd()
        dir_path = tkFileDialog.askdirectory(title="Select Input Directory", initialdir=initial)
        if dir_path:
            try:
                unicode_path = dir_path.decode(sys.getfilesystemencoding()) if isinstance(dir_path, str) else dir_path
                self.input_dir.set(unicode_path)
                self._log_status(u"Input directory set to: {}".format(unicode_path))
            except UnicodeDecodeError:
                 tkMessageBox.showerror("Error", "Selected path contains characters that cannot be decoded.")


    def browse_output_dir(self):
        """Opens a directory dialog to select the output directory."""
        initial = self.output_dir.get()
        try:
            initial_bytes = initial.encode(sys.getfilesystemencoding())
            if not os.path.isdir(initial_bytes):
                initial = os.getcwd() 
        except:
             initial = os.getcwd() 

        dir_path = tkFileDialog.askdirectory(title="Select Output Directory", initialdir=initial)
        if dir_path:
            try:
                unicode_path = dir_path.decode(sys.getfilesystemencoding()) if isinstance(dir_path, str) else dir_path
                self.output_dir.set(unicode_path)
                self._log_status(u"Output directory set to: {}".format(unicode_path))
            except UnicodeDecodeError:
                 tkMessageBox.showerror("Error", "Selected path contains characters that cannot be decoded.")


    def browse_csv_output_dir(self):
        """Opens a directory dialog to select the CSV output directory."""
        initial = self.csv_output_dir.get()
        try:
            initial_bytes = initial.encode(sys.getfilesystemencoding())
            if not os.path.isdir(initial_bytes):
                initial = os.getcwd() 
        except:
             initial = os.getcwd() 

        dir_path = tkFileDialog.askdirectory(title="Select CSV Output Directory", initialdir=initial)
        if dir_path:
            try:
                unicode_path = dir_path.decode(sys.getfilesystemencoding()) if isinstance(dir_path, str) else dir_path
                self.csv_output_dir.set(unicode_path)
                self._log_status(u"CSV output directory set to: {}".format(unicode_path))
            except UnicodeDecodeError:
                 tkMessageBox.showerror("Error", "Selected path contains characters that cannot be decoded.")

    def update_total_size(self):
        """Calculates and updates the total size label."""
        self.master.config(cursor="watch") 
        self.master.update_idletasks()
        try:
            total_bytes = get_total_size(self.selected_files, self.status_queue)
            size_str = format_size(total_bytes)
            self.total_size_var.set("Total Size: {}".format(size_str))
        except Exception as e:
             self._log_status("Error updating total size: {}".format(e))
             self.total_size_var.set("Total Size: Error")
        finally:
            if self.master.winfo_exists():
                 self.master.config(cursor="") 

    def add_files(self):
        """Adds selected files from the input directory to the listbox."""
        input_path = self.input_dir.get() 
        try:
             input_path_bytes = input_path.encode(sys.getfilesystemencoding())
             if not input_path or not os.path.isdir(input_path_bytes):
                 tkMessageBox.showerror("Error", "Please select a valid input directory first.")
                 return
        except UnicodeEncodeError:
             tkMessageBox.showerror("Error", u"Input directory path contains non-encodable characters: {}".format(input_path))
             return
        except Exception as e:
             tkMessageBox.showerror("Error", u"Cannot access input directory {}: {}".format(input_path, e))
             return

        try:
            file_paths_tuple = tkFileDialog.askopenfilenames(title="Select Files to Add", initialdir=input_path_bytes)
            file_paths_bytes = list(file_paths_tuple)
        except Exception as e:
             self._log_status("Error selecting files: {}".format(e))
             file_paths_bytes = []

        added_count = 0
        if file_paths_bytes:
            for path_bytes in file_paths_bytes:
                try:
                    unicode_path = path_bytes.decode(sys.getfilesystemencoding())
                except UnicodeDecodeError:
                    unicode_path = path_bytes.decode(sys.getfilesystemencoding(), 'replace')
                    self._log_status(u"Warning: Used replacement characters for non-decodable filename: {}".format(repr(path_bytes)))

                if unicode_path not in self.selected_files:
                    self.selected_files.append(unicode_path)
                    self.files_listbox.insert(tk.END, unicode_path) 
                    added_count += 1
                else:
                    self._log_status(u"Note: '{}' already in list.".format(unicode_path))

        if added_count > 0:
             self._log_status("Added {} file(s). Current list count: {}".format(added_count, len(self.selected_files)))
             self.update_total_size() 

    def add_folder(self):
        """Adds a selected folder from the input directory to the listbox."""
        input_path = self.input_dir.get() 
        try:
             input_path_bytes = input_path.encode(sys.getfilesystemencoding())
             if not input_path or not os.path.isdir(input_path_bytes):
                 tkMessageBox.showerror("Error", "Please select a valid input directory first.")
                 return
        except UnicodeEncodeError:
             tkMessageBox.showerror("Error", u"Input directory path contains non-encodable characters: {}".format(input_path))
             return
        except Exception as e:
             tkMessageBox.showerror("Error", u"Cannot access input directory {}: {}".format(input_path, e))
             return

        try:
            dir_path_bytes = tkFileDialog.askdirectory(title="Select Folder to Add", initialdir=input_path_bytes)
        except Exception as e:
            self._log_status("Error selecting folder: {}".format(e))
            dir_path_bytes = None

        added_count = 0
        if dir_path_bytes:
            try:
                unicode_path = dir_path_bytes.decode(sys.getfilesystemencoding())
            except UnicodeDecodeError:
                unicode_path = dir_path_bytes.decode(sys.getfilesystemencoding(), 'replace')
                self._log_status(u"Warning: Used replacement characters for non-decodable folder name: {}".format(repr(dir_path_bytes)))

            if unicode_path not in self.selected_files:
                self.selected_files.append(unicode_path)
                self.files_listbox.insert(tk.END, unicode_path + u" [FOLDER]") 
                added_count += 1
            else:
                self._log_status(u"Note: '{}' already in list.".format(unicode_path))

        if added_count > 0:
             self._log_status("Added {} folder(s). Current list count: {}".format(added_count, len(self.selected_files)))
             self.update_total_size() 


    def remove_files(self):
        """Removes selected items from the listbox and the internal list."""
        selected_indices = self.files_listbox.curselection()
        if not selected_indices:
            tkMessageBox.showwarning("Warning", "No items selected to remove.") 
            return

        items_to_remove = [self.files_listbox.get(i) for i in selected_indices]

        for i in reversed(selected_indices):
            self.files_listbox.delete(i)

        removed_count = 0
        for item_text in items_to_remove:
            path_to_remove = item_text.replace(u" [FOLDER]", u"") 
            try:
                self.selected_files.remove(path_to_remove)
                removed_count += 1
            except ValueError:
                 self._log_status(u"Warning: Could not find '{}' in internal list for removal.".format(path_to_remove))

        if removed_count > 0:
            self._log_status("Removed {} item(s). Current list count: {}".format(removed_count, len(self.selected_files)))
            self.update_total_size() 


    def refresh_tape_devices(self):
        """
        Finds tape devices, checks status, filters based on 'General status bits on',
        and updates the dropdown. Runs SYNCHRONOUSLY.
        """
        if self.worker_thread and self.worker_thread.is_alive():
             self._log_status("Operation already in progress. Please wait.")
             return

        self._disable_controls()
        self.master.config(cursor="watch") 
        self.master.update_idletasks() 

        self._log_status("Refreshing tape device list (Synchronous)...")
        available_tape_devices_bytes = [] 
        self.selectable_tape_devices = [] 
        self.selected_tape_device.set("") 
        self.tape_device_combobox['values'] = [] 

        try:
            pattern_bytes = TAPE_DEVICE_PATTERN.encode(sys.getfilesystemencoding())
            available_tape_devices_bytes = sorted(glob.glob(pattern_bytes))
        except Exception as e:
            self._log_status("ERROR: Failed to glob tape devices ({}): {}".format(TAPE_DEVICE_PATTERN, e))
            tkMessageBox.showerror("Error", "Failed to search for tape devices.\nCheck pattern and permissions.")
            self._enable_controls(operational=False) 
            self.master.config(cursor="") 
            return

        if not available_tape_devices_bytes:
            self._log_status("No tape devices found matching pattern: {}".format(TAPE_DEVICE_PATTERN))
            tkMessageBox.showwarning("No Devices", "No tape devices found matching '{}'.".format(TAPE_DEVICE_PATTERN))
            self._enable_controls(operational=False) 
            self.master.config(cursor="") 
            return

        try:
            decoded_devices = [d.decode(sys.getfilesystemencoding(), 'replace') for d in available_tape_devices_bytes]
            self._log_status("Found devices: {}".format(", ".join(decoded_devices)))
        except Exception: 
             self._log_status("Found devices (raw): {}".format(", ".join(map(repr, available_tape_devices_bytes))))

        self._log_status("Checking status (Synchronous)...")

        temp_selectable_devices = []
        for device_bytes in available_tape_devices_bytes:
            try:
                status_string, status_msg = check_tape_status(device_bytes, self.status_queue)
                device_unicode = device_bytes.decode(sys.getfilesystemencoding(), 'replace')

                if status_string != STATUS_ERROR and "General status bits on".lower() in status_msg.lower():
                    temp_selectable_devices.append(device_unicode)
                    self._log_status(u"- {} : Status '{}' (Selectable - Found 'General status bits on')".format(device_unicode, status_string))
                else:
                    reason = "Status was ERROR" if status_string == STATUS_ERROR else "Did not find 'General status bits on'"
                    self._log_status(u"- {} : Status '{}' (Not selectable - {})".format(device_unicode, status_string, reason))

            except Exception as e:
                 device_unicode = device_bytes.decode(sys.getfilesystemencoding(), 'replace')
                 self._log_status(u"ERROR: Unexpected error checking device {}: {}".format(device_unicode, e))

        self._log_status("--- Tape status check complete ---")

        self.selectable_tape_devices = sorted(temp_selectable_devices)

        if self.selectable_tape_devices:
            self.tape_device_combobox['values'] = self.selectable_tape_devices
            current_selection = self.selected_tape_device.get() 
            if current_selection in self.selectable_tape_devices:
                self.selected_tape_device.set(current_selection)
            else:
                self.selected_tape_device.set(self.selectable_tape_devices[0])
            self._log_status(u"Selectable devices updated: {}".format(u", ".join(self.selectable_tape_devices)))
            self.on_tape_device_selected(None) 
        else:
            self._log_status("No selectable tape devices found (must have 'General status bits on').")
            self.tape_device_combobox['values'] = []
            self.selected_tape_device.set("")
            self._enable_controls(operational=False)
            if self.master.winfo_exists():
                    tkMessageBox.showwarning("No Selectable Devices", "No tape devices found reporting 'General status bits on'.")

        self._enable_controls(operational=False)
        self.master.config(cursor="") 


    def _process_refresh_results(self, result_queue):
        """
        DEPRECATED - No longer used with synchronous refresh.
        Kept here temporarily in case we revert.
        """
        pass 


    def on_tape_device_selected(self, event):
        """Callback when a device is selected in the Combobox."""
        device_unicode = self.selected_tape_device.get()
        if not device_unicode:
            self._enable_controls(operational=False) 
            return

        try:
            device_bytes = device_unicode.encode(sys.getfilesystemencoding())
            status_string, _ = check_tape_status(device_bytes, self.status_queue)

            if status_string == STATUS_ONLINE:
                 self._log_status(u"Selected device {} is ONLINE. Enabling operations.".format(device_unicode))
                 self._enable_controls(operational=True)
            else:
                 self._log_status(u"Selected device {} is {}. Disabling operations.".format(device_unicode, status_string))
                 self._enable_controls(operational=False)

        except UnicodeEncodeError:
             tkMessageBox.showerror("Error", u"Selected tape device path contains non-encodable characters: {}".format(device_unicode))
             self._enable_controls(operational=False)
        except Exception as e:
             self._log_status(u"ERROR checking status for selected device {}: {}".format(device_unicode, e))
             self._enable_controls(operational=False) 


    def _run_tape_command_threaded(self, command_bytes, outfile=None, list_command_after=None, list_outfile=None):
        """
        Wrapper to run tape commands (mt or tar) in a separate thread.
        Handles disabling/enabling controls and potential output redirection.
        Expects command_bytes to be the final list of byte strings for subprocess.
        Expects outfile and list_outfile to be byte strings.
        """
        if self.worker_thread and self.worker_thread.is_alive():
            self._log_status("Operation already in progress. Please wait.")
            tkMessageBox.showwarning("Busy", "Another tape operation is currently running.")
            return

        self._disable_controls()
        self.master.update_idletasks()

        def worker():
            primary_retcode = -1
            try:
                if outfile: 
                    outfile_unicode = outfile.decode(sys.getfilesystemencoding(), 'replace')
                    self.status_queue.put(u"Redirecting output to: {}".format(outfile_unicode))
                    try:
                        process = subprocess.Popen(command_bytes, stdout=open(outfile, 'wb'), stderr=subprocess.PIPE)
                        stderr_bytes = process.communicate()[1] 
                        primary_retcode = process.returncode
                        if stderr_bytes:
                            stderr_decoded = stderr_bytes.decode(sys.getfilesystemencoding(), 'ignore')
                            self.status_queue.put("--- STDERR ---")
                            for line in stderr_decoded.splitlines():
                                self.status_queue.put(line)
                        self.status_queue.put("Command finished with exit code: {}".format(primary_retcode))
                        if primary_retcode == 0:
                            self.status_queue.put(u"Successfully wrote output to: {}".format(outfile_unicode))
                        else:
                            self.status_queue.put(u"Command failed while writing to: {}".format(outfile_unicode))
                    except IOError as e:
                        self.status_queue.put(u"ERROR: Cannot write to output file {}: {}".format(outfile_unicode, e))
                        primary_retcode = -1 
                    except Exception as e:
                         self.status_queue.put(u"ERROR during redirection/command execution: {}".format(e))
                         primary_retcode = -1
                else:
                    primary_retcode = run_command(command_bytes, self.status_queue, blocking=True) 

                if primary_retcode == 0 and list_command_after and list_outfile:
                    list_outfile_unicode = list_outfile.decode(sys.getfilesystemencoding(), 'replace')
                    self.status_queue.put(u"--- Generating File List (Post-Operation) ---")
                    list_full_command_bytes = list_command_after
                    try:
                        log_list_command = u" ".join(repr(arg.decode(sys.getfilesystemencoding(), 'replace')) for arg in list_full_command_bytes)
                    except Exception: 
                        log_list_command = u" ".join(map(repr, list_full_command_bytes))
                    self.status_queue.put(u"Running command: {}".format(log_list_command))

                    try:
                         with open(list_outfile, 'wb') as f_list_out: 
                             process = subprocess.Popen(list_full_command_bytes, stdout=f_list_out, stderr=subprocess.PIPE)
                             stderr_bytes = process.communicate()[1] 
                             list_retcode = process.returncode
                             if stderr_bytes:
                                 stderr_decoded = stderr_bytes.decode(sys.getfilesystemencoding(), 'ignore')
                                 self.status_queue.put("--- STDERR (listing) ---")
                                 for line in stderr_decoded.splitlines():
                                     self.status_queue.put(line)
                             self.status_queue.put(u"Listing command finished with exit code: {}".format(list_retcode))
                             if list_retcode == 0:
                                 self.status_queue.put(u"Successfully wrote file list to: {}".format(list_outfile_unicode))
                             else:
                                 self.status_queue.put(u"Failed to generate file list (Exit Code: {})".format(list_retcode))
                    except IOError as e:
                        self.status_queue.put(u"ERROR: Cannot write to list file {}: {}".format(list_outfile_unicode, e))
                    except Exception as e:
                         self.status_queue.put(u"ERROR during list generation: {}".format(e))

            except Exception as e:
                 self.status_queue.put("FATAL ERROR in worker thread: {}".format(e))
                 traceback.print_exc(file=sys.stdout) 
            finally:
                 pass

        self.worker_thread = threading.Thread(target=worker)
        self.worker_thread.daemon = True 
        self.worker_thread.start()


    def tape_status(self):
        """Runs 'mt status' on the selected device."""
        device_unicode = self.selected_tape_device.get()
        if not device_unicode:
            tkMessageBox.showerror("Error", "Please select a tape device.")
            return

        try:
            device_bytes = device_unicode.encode(sys.getfilesystemencoding())
        except UnicodeEncodeError:
            tkMessageBox.showerror("Error", u"Selected tape device path contains non-encodable characters: {}".format(device_unicode))
            return

        self._log_status(u"--- Checking Status for {} ---".format(device_unicode))
        self.master.config(cursor="watch")
        self.master.update_idletasks()
        status_string, status_msg = check_tape_status(device_bytes, self.status_queue) 
        self.master.config(cursor="")
        self._log_status(u"Result: {}".format(status_string)) 
        self._log_status(u"Details:")
        for line in status_msg.splitlines():
             self._log_status(u"  " + line)
        self._log_status(u"--- Status Check Complete ---")
        self.on_tape_device_selected(None)


    def tape_rewind(self):
        """Runs 'mt rewind' on the selected device."""
        device_unicode = self.selected_tape_device.get()
        if not device_unicode:
            tkMessageBox.showerror("Error", "Please select a tape device.")
            return

        try:
            device_bytes = device_unicode.encode(sys.getfilesystemencoding())
        except UnicodeEncodeError:
            tkMessageBox.showerror("Error", u"Selected tape device path contains non-encodable characters: {}".format(device_unicode))
            return

        if tkMessageBox.askyesno("Confirm Rewind", u"Are you sure you want to rewind {}?".format(device_unicode)):
            self._log_status(u"--- Sending Rewind Command for {} ---".format(device_unicode))
            command_bytes = ['mt', '-f', device_bytes, 'rewind']
            self._run_tape_command_threaded(command_bytes)


    def tape_eject(self):
        """Runs 'mt rewoffl' (eject) on the selected device."""
        device_unicode = self.selected_tape_device.get()
        if not device_unicode:
            tkMessageBox.showerror("Error", "Please select a tape device.")
            return

        try:
            device_bytes = device_unicode.encode(sys.getfilesystemencoding())
        except UnicodeEncodeError:
            tkMessageBox.showerror("Error", u"Selected tape device path contains non-encodable characters: {}".format(device_unicode))
            return

        if tkMessageBox.askyesno("Confirm Eject", u"Are you sure you want to rewind and eject {}?".format(device_unicode)):
             self._log_status(u"--- Sending Rewind/Eject Command for {} ---".format(device_unicode))
             command_bytes = ['mt', '-f', device_bytes, 'rewoffl']
             self._run_tape_command_threaded(command_bytes)

    def tape_erase(self):
        """Runs 'mt erase' on the selected device."""
        device_unicode = self.selected_tape_device.get()
        if not device_unicode:
            tkMessageBox.showerror("Error", "Please select a tape device.")
            return

        try:
            device_bytes = device_unicode.encode(sys.getfilesystemencoding())
        except UnicodeEncodeError:
            tkMessageBox.showerror("Error", u"Selected tape device path contains non-encodable characters: {}".format(device_unicode))
            return

        warning_msg = u"*** WARNING! ***\n\nThis will ERASE ALL DATA on the tape in device {}.\nThis operation cannot be undone.\n\nAre you absolutely sure you want to proceed?".format(device_unicode)
        if tkMessageBox.askyesno("Confirm Tape Erase", warning_msg):
            self._log_status(u"--- Sending Erase Command for {} ---".format(device_unicode))
            command_bytes = ['mt', '-f', device_bytes, 'erase']
            self._run_tape_command_threaded(command_bytes)


    def start_operation(self):
        """Starts the selected tape operation (Write, Read, Extract)."""
        if self.worker_thread and self.worker_thread.is_alive():
            self._log_status("Operation already in progress. Please wait.")
            tkMessageBox.showwarning("Busy", "Another tape operation is currently running.")
            return

        mode = self.operation_mode.get()
        device_unicode = self.selected_tape_device.get() 
        out_dir_unicode = self.output_dir.get() 
        csv_dir_unicode = self.csv_output_dir.get() 

        if not device_unicode:
            tkMessageBox.showerror("Error", "No tape device selected.")
            return

        try:
            device_bytes = device_unicode.encode(sys.getfilesystemencoding())
            out_dir_bytes = out_dir_unicode.encode(sys.getfilesystemencoding())
            csv_dir_bytes = csv_dir_unicode.encode(sys.getfilesystemencoding())
            device_basename_bytes = os.path.basename(device_bytes) 

            if mode == "write":
                if not self.selected_files: 
                    tkMessageBox.showerror("Error", "No files or folders selected to write.")
                    return
                files_args_bytes = [] 
                for item_unicode in self.selected_files:
                    item_bytes = item_unicode.encode(sys.getfilesystemencoding())
                    if not os.path.exists(item_bytes):
                         tkMessageBox.showerror("Error", u"Selected item no longer exists: {}".format(item_unicode))
                         return
                    dir_bytes = os.path.dirname(item_bytes)
                    base_bytes = os.path.basename(item_bytes)
                    if not dir_bytes: dir_bytes = '.'
                    files_args_bytes.extend(['-C', dir_bytes, base_bytes]) 

            elif mode == "read" or mode == "extract":
                if not out_dir_unicode or not os.path.isdir(out_dir_bytes):
                     tkMessageBox.showerror("Error", "Please select a valid Output Directory.")
                     return
                if not csv_dir_unicode or not os.path.isdir(csv_dir_bytes):
                     tkMessageBox.showerror("Error", "Please select a valid CSV Output Directory.")
                     return

        except UnicodeEncodeError as e:
             problem_path = device_unicode
             if mode == "write":
                 for p in self.selected_files:
                     try: p.encode(sys.getfilesystemencoding());
                     except: problem_path = p; break;
             elif mode == "read" or mode == "extract":
                 try: out_dir_unicode.encode(sys.getfilesystemencoding());
                 except: problem_path = out_dir_unicode;
                 try: csv_dir_unicode.encode(sys.getfilesystemencoding());
                 except: problem_path = csv_dir_unicode;

             error_msg = u"ERROR: Path contains characters that cannot be encoded using '{}' encoding: {}".format(sys.getfilesystemencoding(), problem_path)
             self._log_status(error_msg)
             tkMessageBox.showerror("Encoding Error", error_msg)
             return
        except Exception as e:
             self._log_status("ERROR during input validation: {}".format(e))
             tkMessageBox.showerror("Validation Error", "Could not validate inputs: {}".format(e))
             return


        confirm_msg = u"Start '{}' operation on device {}?".format(mode.capitalize(), device_unicode)
        if mode == "write":
            confirm_msg += u"\nFiles/Folders to write: {}".format(len(self.selected_files))
        elif mode == "read":
            confirm_msg += u"\nList contents to CSV in: {}".format(csv_dir_unicode)
        elif mode == "extract":
            confirm_msg += u"\nExtract files to: {}".format(out_dir_unicode)
            confirm_msg += u"\nCreate CSV list of contents in: {}".format(csv_dir_unicode)

        if not tkMessageBox.askyesno("Confirm Operation", confirm_msg):
            self._log_status("Operation cancelled by user.")
            return

        self._log_status("--- Preparing Operation: {} ---".format(mode.upper()))

        try:
            if mode == "write":
                command_bytes = ['tar', 'cvf', device_bytes] + files_args_bytes
                self._run_tape_command_threaded(command_bytes)

            elif mode == "read":
                csv_filename_bytes = os.path.join(csv_dir_bytes, "tape_contents_{}.csv".format(device_basename_bytes))
                command_bytes = ['tar', 'tvf', device_bytes]
                self._run_tape_command_threaded(command_bytes, outfile=csv_filename_bytes)

            elif mode == "extract":
                csv_filename_bytes = os.path.join(csv_dir_bytes, "extracted_files_{}.csv".format(device_basename_bytes))
                command_extract_bytes = ['tar', 'xvf', device_bytes, '-C', out_dir_bytes]
                command_list_bytes = ['tar', 'tvf', device_bytes]

                self._run_tape_command_threaded(command_extract_bytes,
                                                list_command_after=command_list_bytes,
                                                list_outfile=csv_filename_bytes)

        except Exception as e:
            self._log_status("ERROR preparing operation command: {}".format(e))
            traceback.print_exc() 
            tkMessageBox.showerror("Error", "An unexpected error occurred preparing the operation command:\n{}".format(e))
            if not (self.worker_thread and self.worker_thread.is_alive()):
                 self._enable_controls(operational=False) 


# --- Main Execution ---
if __name__ == "__main__":
    if 'DISPLAY' not in os.environ and 'WAYLAND_DISPLAY' not in os.environ:
         try:
             subprocess.check_output(['xdpyinfo', '-display', os.environ.get('DISPLAY', ':0')], stderr=subprocess.STDOUT)
             print("Warning: DISPLAY variable not explicitly set, but X server seems reachable.")
         except (OSError, subprocess.CalledProcessError):
             print("Warning: No DISPLAY or WAYLAND_DISPLAY environment variable found, and X server check failed.")
             print("The GUI may not appear unless you are in a graphical session or using X forwarding.")
             if not raw_input("Attempt to proceed anyway? (y/n): ").lower().startswith('y'):
                 exit(1)


    root = None 
    try:
        root = tk.Tk()
        root.configure(bg=GUI_BACKGROUND_COLOR)
        root.minsize(600, 450)
        app = TapeManagerApp(root)
        root.mainloop()
    except tk.TclError as e:
         print("\n--- TKINTER ERROR ---")
         print("A TclError occurred: {}".format(e))
         print("This often means there's an issue with the Tk/Tcl installation on your system,")
         print("or the script cannot connect to the display server (check DISPLAY variable or X forwarding).")
         if sys.platform.startswith('linux'):
              print("On Linux, ensure the relevant Tk/Tcl packages (e.g., python-tk, tk-dev, tcl-dev) are installed.")
         exit(1)
    except Exception as e:
        print("\n--- UNEXPECTED ERROR DURING STARTUP ---")
        print("An unexpected error occurred during application startup:")
        traceback.print_exc()
        exit(1)