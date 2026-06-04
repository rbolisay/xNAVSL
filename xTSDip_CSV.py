#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
from __future__ import print_function

import io
import os
from datetime import datetime

try:
    import Tkinter as tk
    import ttk
    import tkFileDialog as filedialog
    import tkMessageBox as messagebox
except ImportError:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox


FALLBACK_HEADER_TEMPLATE = [
    "Previous File Location :\t0",
    "No of Bytes Stored in Previous File :\t0",
    "Model Name :\t",
    "File Name :\tUNKNOWN",
    "Site Information :\t",
    "Serial No. :\t",
    "No. of Modules Connected :\t2",
    "Fitted Address List :\t21;49;",
    "Parameters for each module :\t2;1;",
    "User Calibrations :",
    "15;0.000000e+00;0.000000e+00;0.000000e+00;-2.000000e-06;9.943000e-01;0.000000e+00",
    "15;0.000000e+00;0.000000e+00;0.000000e+00;0.000000e+00;1.000000e+00;0.000000e+00",
    "15;0.000000e+00;0.000000e+00;0.000000e+00;0.000000e+00;1.000000e+00;0.000000e+00",
    "Secondary Cal Used :\t1;1;0;1;0;0;",
    "Gain :\t10000;1000;0;500;0;0;",
    "Offset :\t0;-20000;0;-20000;0;0;",
    "Gain Control Settings :\t24;0;",
    "SD Selected Flag :\t1",
    "Average Mode :\tNONE",
    "Moving Average Length :\t1",
    "Sample Mode :\tCONTINUOUS",
    "Sample Interval :\t1",
    "Sample Rate :\t1",
    "Sample Period :\t20",
    "Tare Setting :\t0.000",
    "Tare Time Stamp :\t01/01/2000 00:00:00",
    "Density :\t1025.000",
    "Gravity :\t9.807",
    "Time Stamp :\t01/01/2000 00:00:00",
    "External PSU Voltage :\t0",
]

OUTPUT_DATA_HEADER = (
    "Date / Time\tPRESSURE;M\tTEMPERATURE;C\tCONDUCTIVITY;MS/CM"
    "\tCalc. SALINITY; PSU\tCalc. DENSITY ANOMALY; KG/M3 [EOS-80]\tCalc. SOS; M/SEC\t"
)

MAX_GRAPH_POINTS = 4000
DEPTH_DEDUP_BIN_M = 0.01


def new_parsed(source_name, header, data_columns, data_rows):
    return {
        "source_name": source_name,
        "header": header,
        "data_columns": data_columns,
        "data_rows": data_rows,
    }


def clone_parsed(parsed):
    return new_parsed(
        parsed.get("source_name", ""),
        dict(parsed.get("header", {})),
        list(parsed.get("data_columns", [])),
        [list(row) for row in parsed.get("data_rows", [])],
    )


def read_text(path):
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with io.open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue

    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def split_sections(lines):
    sections = {}
    current = ""
    for raw in lines:
        line = raw.rstrip("\r")
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    return sections


def parse_key_value_lines(lines):
    output = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        output[key.strip()] = value.strip()
    return output


def normalize(name):
    return "".join(ch.lower() for ch in name if ch.isalnum())


def to_dd_mm_yyyy(value):
    value = value.strip()
    if not value:
        return ""

    for fmt in (
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S.%f",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            continue
    return value


def number_part(value):
    value = value.strip()
    if not value:
        return ""
    return value.split()[0]


def mode_part(value):
    value = value.strip()
    if not value:
        return ""
    parts = value.split(None, 1)
    if len(parts) == 2:
        return parts[1].upper()
    return parts[0].upper()


def to_float(value):
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_vpd(vpd_path):
    text = read_text(vpd_path)
    lines = text.splitlines()
    sections = split_sections(lines)

    if "Header" not in sections:
        raise ValueError("Input file is missing [Header] section.")
    if "Data" not in sections:
        raise ValueError("Input file is missing [Data] section.")

    header = parse_key_value_lines(sections["Header"])
    data_lines = [line for line in sections["Data"] if line.strip()]
    if len(data_lines) < 3:
        raise ValueError("[Data] section does not contain header/units/data rows.")

    data_columns = [c.strip() for c in data_lines[0].split("\t")]
    data_rows = []
    for line in data_lines[2:]:
        cells = [c.strip() for c in line.split("\t")]
        if len(cells) < len(data_columns):
            continue
        data_rows.append(cells[: len(data_columns)])

    if not data_rows:
        raise ValueError("No data rows found in [Data] section.")

    return new_parsed(os.path.basename(vpd_path), header, data_columns, data_rows)


def load_legacy_header_template(template_path=None):
    if template_path and os.path.exists(template_path):
        lines = read_text(template_path).splitlines()
        header_lines = []
        for line in lines:
            if line.startswith("Date / Time\t"):
                break
            if line.strip() == "":
                continue
            header_lines.append(line.rstrip("\r"))
        if header_lines:
            return header_lines
    return list(FALLBACK_HEADER_TEMPLATE)


def replace_header_value(header_line, mapping):
    if ":" not in header_line:
        return header_line
    key, _ = header_line.split(":", 1)
    key = key.strip()
    if key in mapping:
        return "{} :\t{}".format(key, mapping[key])
    return header_line


def build_legacy_rows(parsed):
    column_map = {}
    for idx, name in enumerate(parsed["data_columns"]):
        column_map[normalize(name)] = idx

    def get(row, aliases):
        for alias in aliases:
            idx = column_map.get(normalize(alias))
            if idx is not None and idx < len(row):
                return row[idx]
        return ""

    rows = []
    for row in parsed["data_rows"]:
        rows.append("\t".join([
            to_dd_mm_yyyy(get(row, ["Date/Time", "Date Time"])),
            get(row, ["Pressure", "Depth"]),
            get(row, ["Temperature"]),
            get(row, ["Conductivity"]),
            get(row, ["Salinity"]),
            get(row, ["Density"]),
            get(row, ["Sound Velocity", "SoundVelocity", "SOS"]),
        ]) + "\t")
    return rows


def build_legacy_output(parsed, header_template):
    hdr = parsed["header"]
    replacements = {
        "Model Name": hdr.get("Device_Type") or hdr.get("Instrument", ""),
        "File Name": parsed.get("source_name", ""),
        "Site Information": hdr.get("Site_Info", ""),
        "Serial No.": hdr.get("Serial_Number", ""),
        "Average Mode": mode_part(hdr.get("Average_Type", "")),
        "Moving Average Length": number_part(hdr.get("Average_Period", "")),
        "Sample Mode": mode_part(hdr.get("Sampling_Mode", "")),
        "Sample Interval": number_part(hdr.get("Time_Interval", "")),
        "Sample Rate": number_part(hdr.get("Sampling_Rate", "")),
        "Sample Period": number_part(hdr.get("Sampling_Period", "")),
        "Tare Setting": hdr.get("Pressure_Tare", ""),
        "Tare Time Stamp": to_dd_mm_yyyy(hdr.get("Pressure_Tare_Time", "")),
        "Density": hdr.get("Density", ""),
        "Gravity": hdr.get("Gravity", ""),
        "Time Stamp": to_dd_mm_yyyy(hdr.get("Time_Stamp", "")),
        "External PSU Voltage": number_part(hdr.get("Battery", "")),
    }

    output_lines = [replace_header_value(line, replacements) for line in header_template]
    output_lines.append(OUTPUT_DATA_HEADER)
    output_lines.extend(build_legacy_rows(parsed))
    return "\r\n".join(output_lines) + "\r\n"


def write_legacy_from_parsed(parsed, output_path, template_path=None):
    header_template = load_legacy_header_template(template_path)
    output = build_legacy_output(parsed, header_template)
    with io.open(output_path, "w", encoding="utf-8") as f:
        f.write(output)


def convert_vpd_to_legacy(vpd_path, output_path, template_path=None):
    parsed = parse_vpd(vpd_path)
    write_legacy_from_parsed(parsed, output_path, template_path)


def extract_tsdip_csv_rows(parsed):
    column_map = {}
    for idx, name in enumerate(parsed["data_columns"]):
        column_map[normalize(name)] = idx

    def get(row, aliases):
        for alias in aliases:
            idx = column_map.get(normalize(alias))
            if idx is not None and idx < len(row):
                return row[idx].strip()
        return ""

    rows = []
    for row in parsed["data_rows"]:
        rows.append((
            get(row, ["Conductivity"]),
            get(row, ["Temperature"]),
            get(row, ["Depth", "Pressure"]),
            get(row, ["Salinity"]),
            get(row, ["Density"]),
            get(row, ["Sound Velocity", "SoundVelocity", "SOS", "Calc. SOS; M/SEC"]),
        ))
    return rows


def build_tsdip_csv_output(parsed, metadata):
    rows = extract_tsdip_csv_rows(parsed)

    from_seq = metadata["from_seq"]
    to_seq = metadata["to_seq"]
    selected = rows[from_seq - 1 : to_seq]

    lines = [
        "# Exported data from TRINAV TS Dip Utility",
        "#",
        "# Description:\t\t\t{}".format(metadata["description"]),
        "# Instrument:\t\t\t{}".format(metadata["instrument"]),
        "# Date:\t\t\t\t{}".format(metadata["date"]),
        "# Time:\t\t\t\t{}".format(metadata["time"]),
        "# Latitude:\t\t\t {}".format(metadata["latitude"]),
        "# Longitude:\t\t\t{}".format(metadata["longitude"]),
        "# Speed of sound formula:\tVelProfiler",
        "# Depth unit:\t\t\tmetres",
        "# Velocity unit:\t\tm/s",
        "# Temperature unit:\t\tdeg Celsius",
        "# Salinity unit:\t\tper 1000 (Salt)",
        "# Water depth:\t\t\t{}".format(metadata["water_depth"]),
        "# Wind state:\t\t\t{}".format(metadata["wind"]),
        "# Sea state:\t\t\t{}".format(metadata["sea_state"]),
        "# From seq. no.:\t\t{}".format(metadata["from_seq"]),
        "# To seq. no.:\t\t\t{}".format(metadata["to_seq_text"]),
        "Conductivity;Temperature;Depth;Salinity;Density;SpeedOfSound",
    ]

    for row in selected:
        lines.append(";".join(row))

    return "\n".join(lines) + "\n"


def write_tsdip_csv_from_parsed(parsed, output_path, metadata):
    output = build_tsdip_csv_output(parsed, metadata)
    with io.open(output_path, "w", encoding="utf-8") as f:
        f.write(output)


def filter_leg_by_depth(leg_rows, increasing, depth_bin_m=DEPTH_DEDUP_BIN_M):
    last_by_depth_key = {}
    rows_without_depth = []
    removed_outliers = 0
    removed_zero_sos = 0
    depth_rows_kept_for_dedup = 0
    last_kept_depth = None
    monotonic_tol = depth_bin_m / 2.0

    for row_idx, row, depth, sos in leg_rows:
        if sos is not None and abs(sos) <= 1e-12:
            removed_zero_sos += 1
            continue
        if depth is None:
            rows_without_depth.append((row_idx, row))
            continue
        if last_kept_depth is not None:
            if increasing and depth < (last_kept_depth - monotonic_tol):
                removed_outliers += 1
                continue
            if (not increasing) and depth > (last_kept_depth + monotonic_tol):
                removed_outliers += 1
                continue

        last_kept_depth = depth
        depth_rows_kept_for_dedup += 1
        depth_key = int(round(depth / depth_bin_m))
        last_by_depth_key[depth_key] = (row_idx, row)

    kept = rows_without_depth + list(last_by_depth_key.values())
    kept.sort(key=lambda item: item[0])
    removed_duplicates = depth_rows_kept_for_dedup - len(last_by_depth_key)
    if removed_duplicates < 0:
        removed_duplicates = 0
    return [row for _, row in kept], removed_duplicates, removed_outliers, removed_zero_sos


def deduplicate_down_up_by_depth(parsed, depth_col_idx, sos_col_idx, depth_bin_m=DEPTH_DEDUP_BIN_M):
    indexed_rows = []
    valid_depths = []

    for idx, row in enumerate(parsed["data_rows"]):
        depth = to_float(row[depth_col_idx]) if depth_col_idx < len(row) else None
        sos = to_float(row[sos_col_idx]) if sos_col_idx < len(row) else None
        indexed_rows.append((idx, row, depth, sos))
        if depth is not None:
            valid_depths.append((idx, depth))

    if not valid_depths:
        raise ValueError("No valid depth values found for duplicate removal.")

    max_depth = max(depth for _, depth in valid_depths)
    turn_idx = max(idx for idx, depth in valid_depths if depth == max_depth)

    down_rows = [item for item in indexed_rows if item[0] <= turn_idx]
    up_rows = [item for item in indexed_rows if item[0] > turn_idx]

    dedup_down, dup_down, outlier_down, zero_down = filter_leg_by_depth(down_rows, True, depth_bin_m)
    dedup_up, dup_up, outlier_up, zero_up = filter_leg_by_depth(up_rows, False, depth_bin_m)

    deduped = new_parsed(
        parsed["source_name"],
        dict(parsed["header"]),
        list(parsed["data_columns"]),
        dedup_down + dedup_up,
    )

    stats = {
        "removed_duplicate_down": dup_down,
        "removed_duplicate_up": dup_up,
        "removed_outlier_down": outlier_down,
        "removed_outlier_up": outlier_up,
        "removed_zero_sos": zero_down + zero_up,
    }
    return deduped, stats, max_depth

class App(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("xTSDip CSV Exporter")
        self.geometry("1280x920")
        self.minsize(1020, 700)

        self.in_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select a .vpd file to preview and process.")
        self.table_info_var = tk.StringVar(value="No preview loaded.")
        self.graph_info_var = tk.StringVar(value="No preview loaded.")

        # CSV header fields
        self.desc_var = tk.StringVar(value="TS-DIP_02")
        self.instrument_var = tk.StringVar(value="VALEPORT MIDAS SVX2 6000")
        self.date_var = tk.StringVar(value=datetime.now().strftime("%b %d %Y"))
        self.time_var = tk.StringVar(value=datetime.now().strftime("%H:%M"))
        self.lat_var = tk.StringVar(value="07 43 00.000 N")
        self.lon_var = tk.StringVar(value="055 09 18.000 W")
        self.water_depth_var = tk.StringVar(value="1900")
        self.wind_var = tk.StringVar(value="W 12")
        self.sea_state_var = tk.StringVar(value="NE 1.5")
        self.from_seq_var = tk.StringVar(value="1")
        self.to_seq_var = tk.StringVar(value="")

        self.preview_input_path = None
        self.original_preview_data = None
        self.preview_data = None
        self.duplicates_removed = False

        self.graph_profile = []
        self.graph_sos_profile = []
        self.graph_plot_points = []
        self.graph_plot_bounds = None

        self.remove_duplicates_btn = None
        self.table = None
        self.graph_canvas = None

        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Input .vpd").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.in_var).grid(row=0, column=1, sticky="we", padx=6, pady=6)
        ttk.Button(top, text="Browse...", command=self._browse_input, width=12).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(top, text="Output .csv").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.out_var).grid(row=1, column=1, sticky="we", padx=6, pady=6)
        ttk.Button(top, text="Save as...", command=self._browse_output, width=12).grid(row=1, column=2, padx=6, pady=6)

        meta_frame = ttk.LabelFrame(top, text="CSV Header Inputs")
        meta_frame.grid(row=2, column=0, columnspan=3, sticky="we", padx=6, pady=(4, 8))
        meta_frame.columnconfigure(1, weight=1)

        self._add_meta_input(meta_frame, 0, "Description", self.desc_var, "TS-DIP_02")
        self._add_meta_input(meta_frame, 1, "Instrument", self.instrument_var, "VALEPORT MIDAS SVX2 6000")
        self._add_meta_input(meta_frame, 2, "Date", self.date_var, "Dec 27 2024")
        self._add_meta_input(meta_frame, 3, "Time", self.time_var, "14:15")
        self._add_meta_input(meta_frame, 4, "Latitude", self.lat_var, "07 43 00.000 N")
        self._add_meta_input(meta_frame, 5, "Longitude", self.lon_var, "055 09 18.000 W")
        self._add_meta_input(meta_frame, 6, "Water depth", self.water_depth_var, "1900")
        self._add_meta_input(meta_frame, 7, "Wind", self.wind_var, "W 12")
        self._add_meta_input(meta_frame, 8, "Sea state", self.sea_state_var, "NE 1.5")
        self._add_meta_input(meta_frame, 9, "From seq. no.", self.from_seq_var, "17")
        self._add_meta_input(meta_frame, 10, "To seq. no.", self.to_seq_var, "blank = all remaining")

        button_row = ttk.Frame(top)
        button_row.grid(row=3, column=1, sticky="w", padx=6, pady=6)

        ttk.Button(button_row, text="Load Preview", command=self._load_preview, width=14).pack(side="left", padx=(0, 8))

        self.remove_duplicates_btn = ttk.Button(
            button_row,
            text="Remove Dublicates",
            command=self._remove_duplicates,
            width=18,
            state="disabled",
        )
        self.remove_duplicates_btn.pack(side="left", padx=(0, 8))

        ttk.Button(button_row, text="Convert", command=self._convert, width=14).pack(side="left")

        ttk.Label(
            top,
            text=(
                "Note: CSV export format follows TRINAV TS Dip Utility with ';' delimiter and "
                "column order Conductivity;Temperature;Depth;Salinity;Density;SpeedOfSound."
            ),
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 2))

        ttk.Label(top, textvariable=self.status_var).grid(row=5, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 6))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        table_tab = ttk.Frame(notebook)
        graph_tab = ttk.Frame(notebook)
        notebook.add(table_tab, text="Table Preview")
        notebook.add(graph_tab, text="Graph Preview")

        table_tab.columnconfigure(0, weight=1)
        table_tab.rowconfigure(0, weight=1)

        self.table = ttk.Treeview(table_tab, show="headings")
        table_y = ttk.Scrollbar(table_tab, orient="vertical", command=self.table.yview)
        table_x = ttk.Scrollbar(table_tab, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=table_y.set, xscrollcommand=table_x.set)

        self.table.grid(row=0, column=0, sticky="nsew")
        table_y.grid(row=0, column=1, sticky="ns")
        table_x.grid(row=1, column=0, sticky="ew")

        ttk.Label(table_tab, textvariable=self.table_info_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=6)

        ttk.Label(
            graph_tab,
            text="Graph: Sound Velocity (m/s) vs Depth (m), with depth increasing downward.",
        ).pack(anchor="w", padx=6, pady=(8, 2))

        self.graph_canvas = tk.Canvas(
            graph_tab,
            bg="white",
            highlightthickness=1,
            highlightbackground="#c8c8c8",
        )
        self.graph_canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.graph_canvas.bind("<Configure>", self._draw_graph)
        self.graph_canvas.bind("<Motion>", self._on_graph_hover)
        self.graph_canvas.bind("<Leave>", self._clear_graph_hover)

        ttk.Label(graph_tab, textvariable=self.graph_info_var).pack(anchor="w", padx=6, pady=(0, 8))

    def _add_meta_input(self, parent, row, label, var, example):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="we", padx=6, pady=3)
        tk.Label(parent, text="e.g., {}".format(example), fg="#606060", bg=self.cget("bg")).grid(
            row=row, column=2, sticky="w", padx=6, pady=3
        )

    def _collect_csv_metadata(self, total_rows):
        required = {
            "description": self.desc_var.get().strip(),
            "instrument": self.instrument_var.get().strip(),
            "date": self.date_var.get().strip(),
            "time": self.time_var.get().strip(),
            "latitude": self.lat_var.get().strip(),
            "longitude": self.lon_var.get().strip(),
            "water_depth": self.water_depth_var.get().strip(),
            "wind": self.wind_var.get().strip(),
            "sea_state": self.sea_state_var.get().strip(),
        }

        for key, value in required.items():
            if not value:
                raise ValueError("Please fill '{}' field.".format(key.replace("_", " ").title()))

        from_seq_text = self.from_seq_var.get().strip()
        if not from_seq_text:
            raise ValueError("From seq. no. is required.")
        try:
            from_seq = int(from_seq_text)
        except ValueError:
            raise ValueError("From seq. no. must be an integer.")

        to_seq_text = self.to_seq_var.get().strip()
        if to_seq_text:
            try:
                to_seq = int(to_seq_text)
            except ValueError:
                raise ValueError("To seq. no. must be an integer or blank.")
        else:
            to_seq = total_rows

        if from_seq < 1:
            raise ValueError("From seq. no. must be >= 1.")
        if from_seq > total_rows:
            raise ValueError("From seq. no. cannot exceed total rows ({})".format(total_rows))
        if to_seq < from_seq:
            raise ValueError("To seq. no. must be >= From seq. no.")
        if to_seq > total_rows:
            raise ValueError("To seq. no. cannot exceed total rows ({})".format(total_rows))

        meta = dict(required)
        meta["from_seq"] = from_seq
        meta["to_seq"] = to_seq
        meta["to_seq_text"] = to_seq_text
        return meta

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select VPD file",
            filetypes=[("VPD files", "*.vpd"), ("All files", "*.*")],
        )
        if not path:
            return

        self.in_var.set(path)
        in_dir = os.path.dirname(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        self.out_var.set(os.path.join(in_dir, stem + "_processed.csv"))
        self._load_preview()

    def _browse_output(self):
        suggested = "processed.csv"
        input_path = self.in_var.get().strip()
        if input_path:
            stem = os.path.splitext(os.path.basename(input_path))[0]
            suggested = stem + "_processed.csv"

        path = filedialog.asksaveasfilename(
            title="Save processed CSV file",
            defaultextension=".csv",
            initialfile=suggested,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.out_var.set(path)

    def _load_preview(self):
        in_path = self.in_var.get().strip()
        if not in_path:
            messagebox.showerror("Missing Input", "Please select a .vpd file.")
            return

        input_file = os.path.abspath(in_path)
        if not os.path.exists(input_file):
            messagebox.showerror("Invalid Input", "Selected .vpd file does not exist.")
            return

        try:
            parsed = parse_vpd(input_file)
        except Exception as exc:
            messagebox.showerror("Preview Failed", str(exc))
            return

        self.preview_input_path = input_file
        self.original_preview_data = clone_parsed(parsed)
        self.preview_data = parsed
        self.duplicates_removed = False

        self._populate_table(parsed)
        self._prepare_graph_profile(parsed)

        if self.remove_duplicates_btn is not None:
            self.remove_duplicates_btn.configure(state="normal")

        self.status_var.set(
            "Loaded {}: {} rows, {} columns.".format(
                os.path.basename(input_file),
                len(parsed["data_rows"]),
                len(parsed["data_columns"]),
            )
        )

    def _populate_table(self, parsed):
        self.table.delete(*self.table.get_children())

        column_ids = ["col_{}".format(i) for i in range(len(parsed["data_columns"]))]
        self.table["columns"] = column_ids

        for col_id, title in zip(column_ids, parsed["data_columns"]):
            width = max(110, min(240, len(title) * 9))
            self.table.heading(col_id, text=title)
            self.table.column(col_id, width=width, anchor="w", stretch=True)

        for row in parsed["data_rows"]:
            self.table.insert("", "end", values=row)

        self.table_info_var.set("Previewing all {} rows.".format(len(parsed["data_rows"])))

    def _find_column_index(self, parsed, aliases):
        normalized_map = {}
        for idx, name in enumerate(parsed["data_columns"]):
            normalized_map[normalize(name)] = idx

        for alias in aliases:
            idx = normalized_map.get(normalize(alias))
            if idx is not None:
                return idx
        return None

    def _nearest_sos_at_depth(self, target_depth_m):
        if not self.graph_sos_profile:
            return None

        best_depth = None
        best_sos = None
        best_diff = float("inf")
        for depth, sos in self.graph_sos_profile:
            diff = abs(depth - target_depth_m)
            if diff <= best_diff:
                best_diff = diff
                best_depth = depth
                best_sos = sos

        if best_depth is None:
            return None
        return best_depth, best_sos

    def _prepare_graph_profile(self, parsed):
        depth_idx = self._find_column_index(parsed, ["Depth", "Pressure"])
        sos_idx = self._find_column_index(parsed, ["Sound Velocity", "SOS", "Calc. SOS; M/SEC"])

        self.graph_profile = []
        self.graph_sos_profile = []

        if depth_idx is None or sos_idx is None:
            self.graph_info_var.set("Cannot draw graph: Depth/Pressure or SoS column missing.")
            self._draw_graph()
            return

        for row in parsed["data_rows"]:
            if depth_idx >= len(row) or sos_idx >= len(row):
                continue
            depth_val = to_float(row[depth_idx])
            sos_val = to_float(row[sos_idx])
            if depth_val is None or sos_val is None:
                continue
            self.graph_profile.append((depth_val, sos_val))
            self.graph_sos_profile.append((depth_val, sos_val))

        if len(self.graph_profile) < 2:
            self.graph_info_var.set("Not enough valid Depth/SoS points to draw graph.")
        else:
            self.graph_info_var.set("Prepared {} points for SoS vs Depth.".format(len(self.graph_profile)))

        self._draw_graph()

    def _clear_graph_hover(self, _event=None):
        self.graph_canvas.delete("hover")

    def _on_graph_hover(self, event):
        if not self.graph_plot_points or self.graph_plot_bounds is None:
            return

        canvas = self.graph_canvas
        mouse_x = float(event.x)
        mouse_y = float(event.y)

        left, top, right, bottom = self.graph_plot_bounds
        if mouse_x < left - 10 or mouse_x > right + 10 or mouse_y < top - 10 or mouse_y > bottom + 10:
            self._clear_graph_hover()
            return

        nearest = min(
            self.graph_plot_points,
            key=lambda p: (p[0] - mouse_x) * (p[0] - mouse_x) + (p[1] - mouse_y) * (p[1] - mouse_y),
        )
        px, py, depth, sos = nearest

        self._clear_graph_hover()
        canvas.create_line(left, py, right, py, fill="#9a9a9a", dash=(2, 3), tags="hover")
        canvas.create_line(px, top, px, bottom, fill="#9a9a9a", dash=(2, 3), tags="hover")
        canvas.create_oval(px - 4, py - 4, px + 4, py + 4, outline="#c0392b", fill="white", width=2, tags="hover")

        label = "SoS: {:.3f} m/s\nDepth: {:.2f} m".format(sos, depth)
        tip_x = mouse_x + 14
        tip_y = mouse_y - 18
        tip_text_id = canvas.create_text(tip_x, tip_y, text=label, anchor="nw", fill="#111111", tags="hover")
        bbox = canvas.bbox(tip_text_id)
        if bbox:
            tip_w = bbox[2] - bbox[0]
            tip_h = bbox[3] - bbox[1]
            canvas_w = canvas.winfo_width()
            canvas_h = canvas.winfo_height()

            if tip_x + tip_w + 10 > canvas_w:
                tip_x = max(8, mouse_x - tip_w - 16)
            if tip_y + tip_h + 10 > canvas_h:
                tip_y = max(8, mouse_y - tip_h - 16)

            canvas.coords(tip_text_id, tip_x, tip_y)
            bbox = canvas.bbox(tip_text_id)
            if bbox:
                tip_bg_id = canvas.create_rectangle(
                    bbox[0] - 6,
                    bbox[1] - 4,
                    bbox[2] + 6,
                    bbox[3] + 4,
                    fill="#fffbe6",
                    outline="#7f7f7f",
                    tags="hover",
                )
                canvas.tag_lower(tip_bg_id, tip_text_id)

    def _remove_duplicates(self):
        if not self.preview_data:
            messagebox.showerror("Missing Preview", "Load a .vpd file preview before removing duplicates.")
            return

        if self.duplicates_removed:
            messagebox.showinfo("Already Applied", "Duplicates were already removed for this loaded preview.")
            if self.remove_duplicates_btn is not None:
                self.remove_duplicates_btn.configure(state="disabled")
            return

        base_data = self.original_preview_data or self.preview_data

        depth_idx = self._find_column_index(base_data, ["Depth", "Pressure"])
        if depth_idx is None:
            messagebox.showerror("Depth Missing", "Depth/Pressure column not found. Cannot remove duplicates.")
            return

        sos_idx = self._find_column_index(base_data, ["Sound Velocity", "SOS", "Calc. SOS; M/SEC"])
        if sos_idx is None:
            messagebox.showerror("SoS Missing", "Sound Velocity (SoS) column not found. Cannot remove duplicates.")
            return

        try:
            deduped, stats, max_depth = deduplicate_down_up_by_depth(
                base_data,
                depth_idx,
                sos_idx,
                DEPTH_DEDUP_BIN_M,
            )
        except Exception as exc:
            messagebox.showerror("Remove Duplicates Failed", str(exc))
            return

        removed_duplicates = stats["removed_duplicate_down"] + stats["removed_duplicate_up"]
        removed_outliers = stats["removed_outlier_down"] + stats["removed_outlier_up"]
        total_removed = removed_duplicates + removed_outliers + stats["removed_zero_sos"]

        before_rows = len(base_data["data_rows"])
        after_rows = len(deduped["data_rows"])

        self.preview_data = deduped
        self.duplicates_removed = True

        self._populate_table(deduped)
        self._prepare_graph_profile(deduped)

        if self.remove_duplicates_btn is not None:
            self.remove_duplicates_btn.configure(state="disabled")

        self.status_var.set(
            "Removed {} rows (duplicates: {}, outliers: {}, SoS=0: {}) at .XX depth bins. "
            "Down dup/out: {}/{}, Up dup/out: {}/{}, max depth {:.2f} m. Rows: {} -> {}.".format(
                total_removed,
                removed_duplicates,
                removed_outliers,
                stats["removed_zero_sos"],
                stats["removed_duplicate_down"],
                stats["removed_outlier_down"],
                stats["removed_duplicate_up"],
                stats["removed_outlier_up"],
                max_depth,
                before_rows,
                after_rows,
            )
        )

    def _draw_graph(self, _event=None):
        canvas = self.graph_canvas
        canvas.delete("all")
        self.graph_plot_points = []
        self.graph_plot_bounds = None

        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 120 or height < 120:
            return

        if not self.preview_data:
            canvas.create_text(width / 2.0, height / 2.0, text="Load a .vpd file to preview graph.")
            return

        if len(self.graph_profile) < 2:
            canvas.create_text(
                width / 2.0,
                height / 2.0,
                text="Unable to draw graph. Ensure file contains valid Depth and SoS values.",
            )
            return

        points = list(self.graph_profile)
        if len(points) > MAX_GRAPH_POINTS:
            step = (len(points) // MAX_GRAPH_POINTS) + 1
            points = points[::step]

        left = 88
        right = 30
        top = 40
        bottom = 70
        plot_w = max(10.0, float(width - left - right))
        plot_h = max(10.0, float(height - top - bottom))
        self.graph_plot_bounds = (float(left), float(top), float(left) + plot_w, float(top) + plot_h)

        sos_values = [sos for _, sos in points]
        depth_values = [depth for depth, _ in points]

        x_min = min(sos_values)
        x_max = max(sos_values)
        if x_min == x_max:
            x_min -= 0.5
            x_max += 0.5
        x_range = x_max - x_min

        y_min = min(depth_values)
        y_max = max(depth_values)
        if y_min == y_max:
            y_min -= 1.0
            y_max += 1.0
        y_range = y_max - y_min

        def to_x(sos):
            return float(left) + ((sos - x_min) / x_range) * plot_w

        def to_y(depth):
            return float(top) + ((depth - y_min) / y_range) * plot_h

        grid_color = "#e4e4e4"
        axis_color = "#444444"

        x_ticks = 6
        y_ticks = 7

        for i in range(x_ticks + 1):
            frac = float(i) / float(x_ticks)
            x = float(left) + frac * plot_w
            val = x_min + frac * x_range
            canvas.create_line(x, top, x, top + plot_h, fill=grid_color)
            canvas.create_line(x, top + plot_h, x, top + plot_h + 5, fill=axis_color)
            canvas.create_text(x, top + plot_h + 18, text="{:.3f}".format(val), anchor="n", fill="#222222")

        for i in range(y_ticks + 1):
            frac = float(i) / float(y_ticks)
            y = float(top) + frac * plot_h
            val = y_min + frac * y_range
            canvas.create_line(left, y, left + plot_w, y, fill=grid_color)
            canvas.create_line(left - 5, y, left, y, fill=axis_color)
            canvas.create_text(left - 10, y, text="{:.2f}".format(val), anchor="e", fill="#222222")

        canvas.create_rectangle(left, top, left + plot_w, top + plot_h, outline=axis_color)

        graph_xy = []
        for depth, sos in points:
            x = to_x(sos)
            y = to_y(depth)
            graph_xy.extend([x, y])
            self.graph_plot_points.append((x, y, depth, sos))

        if len(graph_xy) >= 4:
            canvas.create_line(*graph_xy, fill="#0c5da5", width=2)

        canvas.create_text(
            width / 2.0,
            14,
            text="Sound Velocity vs Depth (Depth Increases Downward)",
            anchor="n",
            fill="#222222",
        )
        canvas.create_text(width / 2.0, height - 14, text="Sound Velocity (m/s)", anchor="s", fill="#222222")
        canvas.create_text(left - 50, top - 10, text="Depth (m)", anchor="w", fill="#222222")

        full_profile_sos_text = "n/a"
        if self.graph_sos_profile:
            full_profile_sos = sum(sos for _, sos in self.graph_sos_profile) / float(len(self.graph_sos_profile))
            full_profile_sos_text = "{:.3f}".format(full_profile_sos)

        sos_20 = self._nearest_sos_at_depth(20.0)
        sos_8 = self._nearest_sos_at_depth(8.0)

        sos_20_text = "n/a"
        if sos_20 is not None:
            depth_20, sos_20_val = sos_20
            sos_20_text = "{:.3f} (at {:.2f} m)".format(sos_20_val, depth_20)

        sos_8_text = "n/a"
        if sos_8 is not None:
            depth_8, sos_8_val = sos_8
            sos_8_text = "{:.3f} (at {:.2f} m)".format(sos_8_val, depth_8)

        self.graph_info_var.set(
            "Plotted {} points. Full Profile SoS={} m/s, 20m SoS={} m/s, 8m SoS={} m/s. "
            "SoS range {:.3f} to {:.3f}, Depth range {:.2f} to {:.2f} m.".format(
                len(points),
                full_profile_sos_text,
                sos_20_text,
                sos_8_text,
                x_min,
                x_max,
                y_min,
                y_max,
            )
        )

    def _convert(self):
        in_path = self.in_var.get().strip()
        out_path = self.out_var.get().strip()

        if not in_path:
            messagebox.showerror("Missing Input", "Please select a .vpd file.")
            return
        if not out_path:
            messagebox.showerror("Missing Output", "Please choose where to save the processed .csv file.")
            return

        input_file = os.path.abspath(in_path)
        output_file = out_path

        try:
            used_filtered = False
            if self.preview_data and self.preview_input_path == input_file:
                parsed_for_output = self.preview_data
                used_filtered = self.duplicates_removed
            else:
                parsed_for_output = parse_vpd(input_file)

            metadata = self._collect_csv_metadata(len(parsed_for_output["data_rows"]))
            write_tsdip_csv_from_parsed(parsed_for_output, output_file, metadata)
        except Exception as exc:
            messagebox.showerror("Conversion Failed", str(exc))
            return

        filter_note = " (with duplicates removed)" if used_filtered else ""
        self.status_var.set("Processed CSV file saved: {}{}".format(output_file, filter_note))
        messagebox.showinfo("Success", "Processed CSV file saved to:\n{}".format(output_file))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
