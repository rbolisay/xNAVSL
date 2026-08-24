#!/usr/bin/env python
# -*- coding: utf-8 -*-
import Tkinter as tk
import tkFileDialog
import subprocess
import os
import datetime

def convert_gps_raw(gps_seconds_str):
    """
    Convierte segundos GPS a formato: Sat Feb 21 00:05:40 2026
    Sin ajuste de segundos bisiestos (Raw).
    """
    try:
        seconds = float(gps_seconds_str)
        gps_epoch = datetime.datetime(1980, 1, 6, 0, 0, 0)
        raw_time = gps_epoch + datetime.timedelta(seconds=seconds)
        return raw_time.strftime("%a %b %d %H:%M:%S %Y")
    except ValueError:
        return gps_seconds_str

def replace_source_id(source_id_str):
    """
    Reemplaza IDs numéricos por etiquetas G01, G02, G03.
    """
    mapping = {
        "13416": "G01",
        "21608": "G02",
        "29800": "G03"
    }
    # Retorna el mapeo si existe, si no, deja el ID original
    return mapping.get(source_id_str, source_id_str)

def update_preview(*args):
    db = entry_db.get()
    line = entry_line.get()
    subline = entry_subline.get()
    folder = entry_folder.get()
    
    suffix = subline[-2:] if len(subline) >= 2 else "XX"
    filename = "Dither_Seq0" + suffix + ".txt"
    output_path = os.path.join(folder, filename)
    
    # Mantenemos el comando dbRead según tu archivo v3
    command_str = "/aw-navcon1/T60system/trinav/bin/dbRead -db {0} -line {1} -subl {2} -data ditherTesQcData > {3}".format(
        db, line, subline, output_path
    )
    
    txt_preview.config(state=tk.NORMAL)
    txt_preview.delete(1.0, tk.END)
    txt_preview.insert(tk.END, command_str)
    txt_preview.config(state=tk.DISABLED)

def run_command():
    db = entry_db.get()
    line = entry_line.get()
    subline = entry_subline.get()
    folder = entry_folder.get()
    
    suffix = subline[-2:]
    filename = "Dither_Seq0" + suffix + ".txt"
    output_path = os.path.join(folder, filename)
    temp_path = output_path + ".tmp"
    
    cmd = [
        "/aw-navcon1/T60system/trinav/bin/dbRead",
        "-db", db,
        "-line", line,
        "-subl", subline,
        "-data", "ditherTesQcData"
    ]
    
    try:
        if not os.path.exists(folder):
            os.makedirs(folder)
            
        status_label.config(text="Processing Trinav & Converting...", fg="orange")
        root.update_idletasks()

        with open(temp_path, "w") as f_temp:
            process = subprocess.Popen(cmd, stdout=f_temp, stderr=subprocess.PIPE)
            stderr = process.communicate()[1]

        if process.returncode == 0:
            with open(temp_path, "r") as f_in, open(output_path, "w") as f_out:
                header = f_in.readline()
                f_out.write(header) 
                
                for line_str in f_in:
                    parts = line_str.strip().split("\t")
                    if len(parts) >= 3:
                        # 1. Convertir columna 'time' (índice 1)
                        parts[1] = convert_gps_raw(parts[1])
                        
                        # 2. Reemplazar 'sourceId' (índice 2)
                        parts[2] = replace_source_id(parts[2])
                        
                        # La columna 3 (localShotTime) se queda igual
                        
                        f_out.write("\t".join(parts) + "\n")
            
            os.remove(temp_path)
            status_label.config(text="SUCCESS: " + filename, fg="green")
        else:
            status_label.config(text="ERROR in dbRead", fg="red")
            print "Stderr: ", stderr
            
    except Exception as e:
        status_label.config(text="SYSTEM ERROR", fg="red")
        print "Error: ", str(e)

# --- Color Palette (from xdbRead style) ---
GUI_BG      = "#B4C8E1"
BTN_BG      = "#8DA9CC"
BTN_FG      = "black"
ENTRY_BG    = "white"
LABEL_FG    = "black"
PREVIEW_BG  = "white"
PREVIEW_FG  = "black"

# --- UI Setup ---
root = tk.Tk()
root.title("DitherTesQc - Final Version")
root.geometry("700x520")
root.configure(bg=GUI_BG)

main_frame = tk.Frame(root, bg=GUI_BG)
main_frame.pack(padx=20, pady=20, fill="both", expand=True)

sv_db = tk.StringVar(value="dbof3190")
sv_line = tk.StringVar(value="4366B048")
sv_subl = tk.StringVar(value="a0048")
for var in [sv_db, sv_line, sv_subl]: var.trace("w", update_preview)

tk.Label(main_frame, text="Database:", bg=GUI_BG, fg=LABEL_FG).pack(anchor="w")
entry_db = tk.Entry(main_frame, textvariable=sv_db, bg=ENTRY_BG, fg=LABEL_FG)
entry_db.pack(fill="x", pady=2)

tk.Label(main_frame, text="Line:", bg=GUI_BG, fg=LABEL_FG).pack(anchor="w")
entry_line = tk.Entry(main_frame, textvariable=sv_line, bg=ENTRY_BG, fg=LABEL_FG)
entry_line.pack(fill="x", pady=2)

tk.Label(main_frame, text="Subline (a00XX):", bg=GUI_BG, fg=LABEL_FG).pack(anchor="w")
entry_subline = tk.Entry(main_frame, textvariable=sv_subl, bg=ENTRY_BG, fg=LABEL_FG)
entry_subline.pack(fill="x", pady=2)

tk.Label(main_frame, text="Output Folder:", bg=GUI_BG, fg=LABEL_FG).pack(anchor="w")
f_frame = tk.Frame(main_frame, bg=GUI_BG)
f_frame.pack(fill="x")
entry_folder = tk.Entry(f_frame, bg=ENTRY_BG, fg=LABEL_FG)
entry_folder.insert(0, "/aw-navoff1/data/JOB/3190/client_deliverables/Dither_QC")
entry_folder.pack(side="left", fill="x", expand=True)
tk.Button(
    f_frame, text="Browse", bg=BTN_BG, fg=BTN_FG,
    activebackground=BTN_BG, activeforeground=BTN_FG,
    command=lambda: [entry_folder.delete(0, tk.END),
                     entry_folder.insert(0, tkFileDialog.askdirectory()),
                     update_preview()]
).pack(side="right")

tk.Label(main_frame, text="Command Preview:", font=("Arial", 9, "bold"),
         bg=GUI_BG, fg=LABEL_FG).pack(anchor="w", pady=(15, 0))
txt_preview = tk.Text(main_frame, height=3, bg=PREVIEW_BG, fg=PREVIEW_FG,
                      font=("Courier", 10), relief="sunken", bd=1)
txt_preview.pack(fill="x", pady=5)

run_btn = tk.Button(
    main_frame, text="RUN & PROCESS DATA", command=run_command,
    bg=BTN_BG, fg=BTN_FG,
    activebackground=BTN_BG, activeforeground=BTN_FG,
    font=("Arial", 10, "bold"), height=2
)
run_btn.pack(fill="x", pady=10)

status_label = tk.Label(main_frame, text="Ready", fg="blue", bg=GUI_BG)
status_label.pack()

update_preview()
root.mainloop()
