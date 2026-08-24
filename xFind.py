#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Ai assisted Code by RBolisay
# Required imports for the GUI and file searching
import Tkinter as tk
import ScrolledText as scrolledtext
import tkFileDialog
import tkMessageBox
import os
import fnmatch
import threading
import Queue
import sys

# Defaults: avoid unbounded memory / UI freeze
_DEFAULT_MAX_RESULTS = 100000


def _depth_below_start(root_path, start_abs):
    """Directory depth below start_abs (0 = start directory itself)."""
    try:
        rel = os.path.relpath(root_path, start_abs)
    except ValueError:
        return 999
    if rel == ".":
        return 0
    parts = [p for p in rel.split(os.sep) if p]
    return len(parts)


def _is_filesystem_root(path):
    """True if path is / on Unix or a drive root (e.g. C:\\) or \\ on Windows."""
    p = os.path.abspath(os.path.normpath(path))
    if os.name == "nt":
        if p == "\\":
            return True
        if len(p) >= 3 and p[1:3] == ":\\" and len(os.path.splitdrive(p)[1]) <= 1:
            return True
        return False
    return p == "/"


# --- Application Class ---
class XFindApp:
    """
    A GUI application using Tkinter to find files and folders based on a wildcard pattern.
    Compatible with Python 2.7.
    Pattern matches file/folder *names* only (fnmatch), not full paths.
    Permission errors while walking are counted but paths are not printed to the console.
    """

    def __init__(self, master):
        """
        Initializes the application GUI and variables.
        Args:
            master: The root Tkinter window.
        """
        self.master = master
        master.title("xFind")
        master.minsize(520, 440)

        gui_bg_color = "#B4C8E1"
        button_bg_color = "#8DA9CC"
        button_fg_color = "black"
        results_text_bg_color = "#EAF0F6"

        self.search_thread = None
        self.cancel_event = threading.Event()
        self.results_queue = Queue.Queue()
        self._walk_errors = [0]

        master.configure(bg=gui_bg_color)

        master.grid_columnconfigure(1, weight=1)
        master.grid_rowconfigure(5, weight=1)

        self.description_label = tk.Label(
            master,
            text="Find files/folders matching the wildcard (name only, not full path).",
            bg=gui_bg_color,
        )
        self.description_label.grid(row=0, column=0, columnspan=3, padx=10, pady=(10, 5), sticky="w")

        self.wildcard_label = tk.Label(master, text="Search Wildcard:", bg=gui_bg_color)
        self.wildcard_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.wildcard_entry = tk.Entry(master)
        self.wildcard_entry.grid(row=1, column=1, columnspan=2, padx=10, pady=5, sticky="ew")
        self.wildcard_entry.insert(0, "*.*")

        self.dir_label = tk.Label(master, text="Start Directory:", bg=gui_bg_color)
        self.dir_label.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.dir_entry = tk.Entry(master)
        self.dir_entry.grid(row=2, column=1, padx=10, pady=5, sticky="ew")
        try:
            self.dir_entry.insert(0, os.getcwd())
        except Exception:
            pass
        self.browse_button = tk.Button(
            master, text="Browse...", command=self.browse_directory, bg=button_bg_color, fg=button_fg_color
        )
        self.browse_button.grid(row=2, column=2, padx=(0, 10), pady=5, sticky="e")

        self.options_frame = tk.Frame(master, bg=gui_bg_color)
        self.options_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=(0, 5), sticky="ew")
        tk.Label(self.options_frame, text="Max depth (blank = unlimited):", bg=gui_bg_color).pack(side=tk.LEFT)
        self.max_depth_entry = tk.Entry(self.options_frame, width=8)
        self.max_depth_entry.pack(side=tk.LEFT, padx=(4, 16))
        tk.Label(self.options_frame, text="Max results:", bg=gui_bg_color).pack(side=tk.LEFT)
        self.max_results_entry = tk.Entry(self.options_frame, width=10)
        self.max_results_entry.pack(side=tk.LEFT, padx=(4, 0))
        self.max_results_entry.insert(0, str(_DEFAULT_MAX_RESULTS))

        self.results_label = tk.Label(master, text="Results:", bg=gui_bg_color)
        self.results_label.grid(row=4, column=0, columnspan=3, padx=10, pady=(10, 0), sticky="w")
        self.results_text = scrolledtext.ScrolledText(
            master, wrap=tk.WORD, height=15, width=60, bg=results_text_bg_color
        )
        self.results_text.grid(row=5, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")
        self.results_text.configure(state="disabled")

        self.button_frame = tk.Frame(master, bg=gui_bg_color)
        self.button_frame.grid(row=6, column=0, columnspan=3, pady=(5, 10))

        self.start_button = tk.Button(
            self.button_frame, text="Start Search", command=self.start_search, bg=button_bg_color, fg=button_fg_color
        )
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.cancel_button = tk.Button(
            self.button_frame,
            text="Cancel Search",
            command=self.cancel_search,
            state=tk.DISABLED,
            bg=button_bg_color,
            fg=button_fg_color,
        )
        self.cancel_button.pack(side=tk.LEFT, padx=5)

        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def browse_directory(self):
        """Opens a dialog to choose the starting directory."""
        initial = (self.dir_entry.get() or "").strip()
        if not initial or not os.path.isdir(initial):
            try:
                initial = os.getcwd()
            except Exception:
                initial = os.path.expanduser("~")
        directory = tkFileDialog.askdirectory(title="Select Starting Directory", initialdir=initial)
        if directory:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, directory)

    def _parse_optional_positive_int(self, raw, field_name, allow_empty_as_none=True):
        """Return int >= 0, or None if empty and allowed. Raises ValueError on bad input."""
        s = (raw or "").strip()
        if not s:
            if allow_empty_as_none:
                return None
            raise ValueError("empty")
        n = int(s)
        if n < 0:
            raise ValueError("negative")
        return n

    def start_search(self):
        """Initiates the file search process."""
        wildcard = self.wildcard_entry.get().strip()
        start_dir = self.dir_entry.get().strip()

        if not wildcard:
            tkMessageBox.showwarning("Input Error", "Please enter a search wildcard.")
            return

        if not start_dir:
            try:
                start_dir = os.path.abspath(os.getcwd())
            except Exception:
                start_dir = os.path.abspath(os.path.expanduser("~"))
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, start_dir)
        else:
            start_dir = os.path.abspath(os.path.normpath(start_dir))

        if not os.path.isdir(start_dir):
            tkMessageBox.showerror(
                "Input Error", "The specified start directory does not exist or is not accessible."
            )
            return

        if _is_filesystem_root(start_dir):
            if not tkMessageBox.askyesno(
                "Large search",
                "The start path is a drive or filesystem root.\n\n"
                "This can scan the entire disk and take a long time.\n\n"
                "Continue?",
                parent=self.master,
            ):
                return

        try:
            max_depth = self._parse_optional_positive_int(self.max_depth_entry.get(), "Max depth", allow_empty_as_none=True)
        except ValueError:
            tkMessageBox.showerror("Input Error", "Max depth must be empty or a non-negative integer.")
            return

        try:
            max_results = self._parse_optional_positive_int(
                self.max_results_entry.get(), "Max results", allow_empty_as_none=False
            )
        except ValueError:
            tkMessageBox.showerror(
                "Input Error", "Max results must be a non-negative integer (default %s)." % _DEFAULT_MAX_RESULTS
            )
            return

        if max_results == 0:
            tkMessageBox.showwarning("Input Error", "Max results must be greater than zero.")
            return

        self._walk_errors = [0]

        self.results_text.configure(state="normal")
        self.results_text.delete(1.0, tk.END)
        depth_note = "unlimited" if max_depth is None else str(max_depth)
        self.results_text.insert(
            tk.END,
            "Starting search for '{}' in '{}'...\n(max depth: {}, max results: {})\n".format(
                wildcard, start_dir, depth_note, max_results
            ),
        )
        self.results_text.configure(state="disabled")

        self.cancel_event.clear()
        self.start_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)

        self.search_thread = threading.Thread(
            target=self.search_worker,
            args=(wildcard, start_dir, max_depth, max_results),
        )
        self.search_thread.daemon = True
        self.search_thread.start()

        self.master.after(100, self.process_queue)

    def cancel_search(self):
        if self.search_thread and self.search_thread.is_alive():
            self.cancel_event.set()
            self.log_message(">>> Cancel request sent. Waiting for search to stop...\n")

    def on_closing(self):
        if self.search_thread and self.search_thread.is_alive():
            self.cancel_search()
            if tkMessageBox.askokcancel("Quit", "A search is in progress. Quit anyway?"):
                self.master.destroy()
        else:
            self.master.destroy()

    def search_worker(self, wildcard, start_dir, max_depth, max_results):
        start_abs = os.path.abspath(os.path.normpath(start_dir))
        hit_limit = False
        try:
            count = 0
            for root, dirs, files in os.walk(start_abs, topdown=True, onerror=self.handle_walk_error):
                if self.cancel_event.is_set():
                    self.results_queue.put(">>> Search cancelled by user.\n")
                    break

                matched_dirs = [d for d in dirs if fnmatch.fnmatch(d, wildcard)]
                for name in matched_dirs:
                    if self.cancel_event.is_set():
                        break
                    full_path = os.path.join(root, name)
                    self.results_queue.put(full_path + os.sep + "\n")
                    count += 1
                    if count >= max_results:
                        hit_limit = True
                        break

                if hit_limit or self.cancel_event.is_set():
                    break

                matched_files = [f for f in files if fnmatch.fnmatch(f, wildcard)]
                for name in matched_files:
                    if self.cancel_event.is_set():
                        break
                    full_path = os.path.join(root, name)
                    self.results_queue.put(full_path + "\n")
                    count += 1
                    if count >= max_results:
                        hit_limit = True
                        break

                if hit_limit or self.cancel_event.is_set():
                    break

                # After matching this level, stop descending if at max depth (topdown prune).
                if max_depth is not None:
                    d = _depth_below_start(root, start_abs)
                    if d >= max_depth:
                        dirs[:] = []

            if not self.cancel_event.is_set():
                self.results_queue.put(">>> Search complete. Found {} items.\n".format(count))
                if hit_limit:
                    self.results_queue.put(
                        ">>> Stopped at max results ({}). Narrow the wildcard or raise the limit.\n".format(
                            max_results
                        )
                    )
                err_n = self._walk_errors[0]
                if err_n:
                    if err_n == 1:
                        self.results_queue.put(
                            ">>> Skipped 1 directory (permission denied or inaccessible).\n"
                        )
                    else:
                        self.results_queue.put(
                            ">>> Skipped {} directories (permission denied or inaccessible).\n".format(err_n)
                        )

        except Exception as e:
            print ">>> Error during search: {}".format(e)
        finally:
            self.results_queue.put(None)

    def handle_walk_error(self, os_error):
        if self.cancel_event.is_set():
            return
        try:
            self._walk_errors[0] += 1
        except (AttributeError, IndexError, TypeError):
            pass

    def process_queue(self):
        try:
            while True:
                msg = self.results_queue.get_nowait()

                if msg is None:
                    self.search_finished()
                    return
                else:
                    self.log_message(msg)

        except Queue.Empty:
            if self.search_thread and self.search_thread.is_alive():
                self.master.after(100, self.process_queue)
            else:
                self.search_finished()

    def search_finished(self):
        if self.start_button["state"] == tk.DISABLED:
            self.start_button.config(state=tk.NORMAL)
            self.cancel_button.config(state=tk.DISABLED)

        self.search_thread = None

        try:
            self.results_text.configure(state="normal")
            self.results_text.see(tk.END)
            self.results_text.configure(state="disabled")
        except tk.TclError:
            pass

    def log_message(self, message):
        try:
            self.results_text.configure(state="normal")
            self.results_text.insert(tk.END, message)
            self.results_text.see(tk.END)
            self.results_text.configure(state="disabled")
        except tk.TclError:
            pass


# --- Main Execution ---
if __name__ == "__main__":
    if sys.version_info[0] != 2 or sys.version_info[1] < 7:
        print "Error: This script requires Python 2.7."
        try:
            root_err = tk.Tk()
            root_err.withdraw()
            tkMessageBox.showerror("Python Version Error", "This application requires Python 2.7 to run.")
            root_err.destroy()
        except tk.TclError:
            pass
        sys.exit(1)

    root = tk.Tk()
    app = XFindApp(root)
    root.mainloop()
