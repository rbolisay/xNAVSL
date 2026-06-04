#!/usr/bin/env python
# -*- coding: utf-8 -*-

# xSCR - A simple screen recorder for RHEL/Linux
# Author: Gemini
# Version: 1.9.1
#
# This script is a graphical frontend. It REQUIRES backend command-line
# tools like 'ffmpeg' and 'xwininfo'. If they are not installed,
# you can place their static/portable executables in the same directory
# as this script.

import Tkinter as tk
import tkFileDialog
import subprocess
import os
import re
import sys
from datetime import datetime
from threading import Thread

class ScreenRecorderApp:
    def __init__(self, master):
        self.master = master
        self.master.title("xSCR - Screen Recorder")
        self.master.geometry("500x200") # Adjusted height for fewer buttons
        self.master.resizable(False, False)

        # --- Style Configuration ---
        self.BG_COLOR = "#B4C8E1"
        self.BTN_COLOR = "#8DA9CC"
        self.BTN_TEXT_COLOR = "black"
        self.master.configure(bg=self.BG_COLOR)

        # --- State Variables ---
        self.recording_process = None
        self.output_directory = tk.StringVar()
        
        # --- Set Default Output Directory ---
        default_path = "/usr/local/trinop/dbase/links/qcfiles/Misc/"
        try:
            if os.path.isdir(default_path) and os.access(default_path, os.W_OK):
                self.output_directory.set(default_path)
            else:
                self.output_directory.set(os.path.expanduser("~"))
        except OSError:
            self.output_directory.set(os.path.expanduser("~"))

        # --- Paths to dependencies ---
        self.ffmpeg_path = None
        self.xwininfo_path = None

        # --- GUI Widgets ---
        self.create_widgets()

        # --- Dependency Check ---
        self.check_dependencies()

        # --- Handle Window Closing ---
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)


    def on_closing(self):
        """
        This function is called when the user clicks the window's close button.
        It ensures that any active recording is stopped before the app exits.
        """
        if self.recording_process:
            self.stop_recording()
        self.master.destroy()


    def _show_custom_dialog(self, title, message, dialog_type='error'):
        """Creates a custom, themed dialog box."""
        dialog = tk.Toplevel(self.master)
        dialog.title(title)
        dialog.configure(bg=self.BG_COLOR)
        dialog.resizable(False, False)
        
        msg_frame = tk.Frame(dialog, bg=self.BG_COLOR, padx=20, pady=10)
        msg_frame.pack()
        icon_text = "!" if dialog_type == 'warning' else "X"
        icon_color = "#E8A824" if dialog_type == 'warning' else "#E57373"
        icon_label = tk.Label(msg_frame, text=icon_text, font=("Helvetica", 24, "bold"),
                              fg=icon_color, bg=self.BG_COLOR)
        icon_label.grid(row=0, column=0, rowspan=2, padx=(0, 15), sticky='n')
        message_label = tk.Label(msg_frame, text=message, justify=tk.LEFT,
                                 wraplength=350, bg=self.BG_COLOR)
        message_label.grid(row=0, column=1, sticky='w')
        ok_button = tk.Button(msg_frame, text="OK", width=10,
                              bg=self.BTN_COLOR, fg=self.BTN_TEXT_COLOR,
                              command=dialog.destroy)
        ok_button.grid(row=1, column=1, pady=(10, 0), sticky='e')
        ok_button.focus_set()
        dialog.update_idletasks()
        x = self.master.winfo_x() + (self.master.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.master.winfo_y() + (self.master.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry("+{}+{}".format(x, y))
        dialog.transient(self.master)
        dialog.grab_set()
        self.master.wait_window(dialog)


    def create_widgets(self):
        """Creates and arranges all the GUI elements in the window."""
        main_frame = tk.Frame(self.master, padx=10, pady=10, bg=self.BG_COLOR)
        main_frame.pack(fill=tk.BOTH, expand=True)

        dir_frame = tk.Frame(main_frame, bg=self.BG_COLOR)
        dir_frame.pack(fill=tk.X, pady=(0, 15))
        dir_label = tk.Label(dir_frame, text="Output Directory:", bg=self.BG_COLOR)
        dir_label.pack(side=tk.LEFT)
        self.dir_entry = tk.Entry(dir_frame, textvariable=self.output_directory)
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.browse_button = tk.Button(dir_frame, text="Browse...", bg=self.BTN_COLOR, fg=self.BTN_TEXT_COLOR, command=self.browse_directory)
        self.browse_button.pack(side=tk.LEFT)

        self.controls_frame = tk.Frame(main_frame, bg=self.BG_COLOR)
        self.controls_frame.pack(fill=tk.BOTH, expand=True)
        self.controls_frame.grid_rowconfigure(0, weight=1)
        self.controls_frame.grid_columnconfigure(0, weight=1)
        self.controls_frame.grid_columnconfigure(1, weight=1)

        btn_options = {'bg': self.BTN_COLOR, 'fg': self.BTN_TEXT_COLOR, 'activebackground': '#A0B9D9'}
        self.record_screen_button = tk.Button(self.controls_frame, text="Record Full Screen", command=lambda: self.start_recording('screen'), **btn_options)
        self.record_screen_button.grid(row=0, column=0, sticky="nsew", padx=5)
        self.record_window_button = tk.Button(self.controls_frame, text="Record Window", command=lambda: self.start_recording('window'), **btn_options)
        self.record_window_button.grid(row=0, column=1, sticky="nsew", padx=5)
        
        self.stop_button = tk.Button(self.controls_frame, text="Stop Recording", bg="#E57373", fg=self.BTN_TEXT_COLOR, activebackground="#EF5350", command=self.stop_recording)

        self.status_var = tk.StringVar()
        self.status_var.set("Initializing...")
        status_bar = tk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, bd=1)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

    def find_executable(self, name):
        """Finds an executable in the system PATH or next to this script (not sys.argv[0])."""
        try:
            path = subprocess.check_output(["which", name]).strip()
            if os.access(path, os.X_OK):
                return path
        except (subprocess.CalledProcessError, OSError):
            pass
        try:
            here = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            here = os.path.dirname(os.path.abspath(sys.argv[0]))
        local_path = os.path.join(here, name)
        if os.path.isfile(local_path) and os.access(local_path, os.X_OK):
            return local_path
        return None

    def check_dependencies(self):
        """Checks for dependencies on startup and disables controls if not found."""
        self.ffmpeg_path = self.find_executable('ffmpeg')
        self.xwininfo_path = self.find_executable('xwininfo')

        if self.ffmpeg_path:
            self.status_var.set("Ready. Select a recording option.")
        else:
            self.status_var.set("ERROR: ffmpeg not found. Recording is disabled.")
            self._show_custom_dialog("Dependency Missing", "ffmpeg could not be found.\n\nSOLUTION:\nDownload a 'static build' of ffmpeg and place it in the same directory as this script.")
            self.record_screen_button.config(state=tk.DISABLED)
            self.record_window_button.config(state=tk.DISABLED)

        if not self.xwininfo_path:
            self.record_window_button.config(state=tk.DISABLED)

    def browse_directory(self):
        """Opens a dialog to choose an output directory."""
        path = tkFileDialog.askdirectory(title="Select Output Folder")
        if path:
            self.output_directory.set(path)

    def get_recording_geometry(self, mode):
        """Gets the required geometry for window recording."""
        if mode == 'window':
            self.status_var.set("Please click on the window you want to record...")
            self.master.update()
            try:
                xwininfo_output = subprocess.check_output([self.xwininfo_path, "-frame"])
                geometry_match = re.search(r'-geometry (\d+x\d+)([+-]\d+)([+-]\d+)', xwininfo_output)
                if not geometry_match:
                    self.status_var.set("Could not determine window geometry.")
                    return None, None
                size, x_pos, y_pos = geometry_match.group(1), geometry_match.group(2), geometry_match.group(3)
                
                # BUG FIX: The position format for ffmpeg is +X+Y (e.g., +100+200), not +X,+Y.
                # The regex captures the signs (+/-), so we just need to concatenate them.
                position = "{}{}".format(x_pos, y_pos)
                return size, position
                
            except subprocess.CalledProcessError:
                self.status_var.set("Window selection cancelled or failed.")
                return None, None
        return None, None

    def start_recording(self, mode):
        """Handles the logic for starting a recording."""
        if self.recording_process:
            self._show_custom_dialog("In Progress", "A recording is already in progress.", dialog_type='warning')
            return

        display = os.environ.get('DISPLAY')
        if not display:
            self._show_custom_dialog("Display Error", "Could not find the DISPLAY environment variable.")
            self.master.destroy()
            return

        screen_size = None
        if mode == 'screen':
            try:
                xdpy_output = subprocess.check_output(["xdpyinfo"])
                match = re.search(r'dimensions:\s+(\d+x\d+)', xdpy_output)
                if match:
                    screen_size = match.group(1)
            except Exception as e:
                print("Could not determine screen size. Error: {}".format(e))
        
        video_size, position_args = None, ""
        if mode == 'window':
            video_size, position_args = self.get_recording_geometry(mode)
            if not video_size:
                self.status_var.set("Ready. Select a recording option.")
                return

        output_dir = self.output_directory.get()
        if not os.path.isdir(output_dir):
            self._show_custom_dialog("Invalid Path", "The output directory does not exist.")
            return

        filename = "recording_{}.mp4".format(datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))
        output_path = os.path.join(output_dir, filename)

        command = [self.ffmpeg_path, '-y', '-f', 'x11grab', '-framerate', '30']
        final_video_size = video_size if video_size else screen_size
        if final_video_size:
            command.extend(['-video_size', final_video_size])
        
        input_display = "{}{}".format(display, position_args)
        command.extend(['-i', input_display])
        
        # --- File Size & Quality Settings ---
        # -crf (Constant Rate Factor) is used for quality. Lower is better quality, higher is smaller file. 23 is a good default.
        # -preset controls encoding speed vs. compression. 'veryfast' is a good balance.
        command.extend(['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', output_path])

        self.status_var.set("Recording to: {}".format(filename))
        print("Executing command: {}".format(' '.join(command)))

        def run_ffmpeg():
            """Starts the ffmpeg process in a separate thread."""
            try:
                # Redirect stderr to DEVNULL to prevent blocking
                with open(os.devnull, 'wb') as devnull:
                    self.recording_process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=devnull, stdout=devnull)
                    self.recording_process.wait()
            except Exception as e:
                print("Error during ffmpeg execution: {}".format(e))

        self.recording_thread = Thread(target=run_ffmpeg)
        self.recording_thread.start()
        self.toggle_controls(is_recording=True)

    def stop_recording(self):
        """Stops the currently running ffmpeg process."""
        if not self.recording_process: return
        
        try:
            self.recording_process.stdin.write('q')
            self.recording_process.stdin.flush()
            self.status_var.set("Recording saved. Ready for next task.")
        except (IOError, AttributeError) as e:
            print("Could not send 'q', attempting to terminate. Error: {}".format(e))
            self.recording_process.terminate()
            self.status_var.set("Recording stopped forcefully.")
        
        self.recording_process = None
        self.toggle_controls(is_recording=False)

    def toggle_controls(self, is_recording):
        """Toggles the visibility and state of control buttons."""
        if is_recording:
            self.record_screen_button.grid_remove()
            self.record_window_button.grid_remove()
            self.stop_button.grid(row=0, column=0, columnspan=2, sticky="nsew", ipady=10)
        else:
            self.stop_button.grid_remove()
            self.record_screen_button.grid()
            self.record_window_button.grid()

if __name__ == "__main__":
    root = tk.Tk()
    app = ScreenRecorderApp(root)
    root.mainloop()
