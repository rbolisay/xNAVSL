#!/usr/bin/env python
# Ai assisted code by R. Bolisay
# Baseline from user upload, converted to Python 2.7,
# auto-detect reporting logic refined, MD5s sequential,
# multi-range user-defined reporting fixed, and warning logic refined.
# MD5 cache now includes mtime and size for robust change detection.

import os
import json
import hashlib
import csv
import time # For potential debugging or timing

# --- Configuration ---
# Define directories
NAV_P1_DIR = "/usr/local/trinop/dbase/links/P111/P111-SSREG"
OBP_P1_DIR = "/usr/local/trinop/dbase/links/nav2dp/c3190/P111"
CACHE_FILE = "/usr/local/trinop/dbase/links/qcfiles/md5sum/md5cache.json"
OUTPUT_HTML = "/usr/share/nginx/html/md5check_report.html"
OUTPUT_CSV = "/usr/local/trinop/dbase/links/qcfiles/md5sum/md5check.csv"

# Define sequence ranges to process.
# This is expected to be modified by an installer script or manually.
SEQUENCE_RANGES_STR = "001-500"

# MAX_MD5_THREADS is not used in this sequential version.
# --- End Configuration ---

def ensure_dir_exists(file_path):
    """Ensures the directory for the given file_path exists."""
    directory = os.path.dirname(file_path)
    if directory:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except OSError as e:
                if not os.path.isdir(directory): # Check to prevent error if dir was created by another process
                    print "Error creating directory {}: {}".format(directory, e)
                    # Depending on severity, you might want to: raise e

def parse_sequence_ranges_to_set(ranges_str):
    """
    Parses a string of sequence ranges into a flat set of individual sequence numbers.
    Returns None if ranges_str is empty or only whitespace.
    """
    if not ranges_str or not ranges_str.strip(): # Check if string is empty or just whitespace
        return None
    selected_sequences = set()
    parts = ranges_str.split(',')
    for part in parts:
        part = part.strip()
        if not part: continue
        if '-' in part:
            try:
                start_str, end_str = part.split('-', 1)
                start_num, end_num = int(start_str.strip()), int(end_str.strip())
                if start_num > end_num:
                    print "Warning: Invalid range '{}' (start > end) in parse_sequence_ranges_to_set. Skipping.".format(part)
                    continue
                selected_sequences.update(xrange(start_num, end_num + 1)) # Py2 xrange
            except ValueError:
                print "Warning: Invalid range format '{}' in parse_sequence_ranges_to_set. Skipping.".format(part)
        else:
            try:
                selected_sequences.add(int(part.strip()))
            except ValueError:
                print "Warning: Invalid sequence number format '{}' in parse_sequence_ranges_to_set. Skipping.".format(part)
    return selected_sequences if selected_sequences else None

def get_parsed_segments(ranges_str):
    """
    Parses a string of sequence ranges into a list of (start, end) tuples.
    Single numbers are represented as (num, num).
    Returns an empty list if ranges_str is empty or only whitespace.
    Segments are sorted by their start number.
    """
    if not ranges_str or not ranges_str.strip():
        return []
    segments = []
    parts = ranges_str.split(',')
    for part in parts:
        part = part.strip()
        if not part: continue
        if '-' in part:
            try:
                start_str, end_str = part.split('-', 1)
                start_num, end_num = int(start_str.strip()), int(end_str.strip())
                if start_num > end_num:
                    print "Warning: Invalid range '{}' (start > end) in get_parsed_segments. Skipping.".format(part)
                    continue
                segments.append((start_num, end_num))
            except ValueError:
                print "Warning: Invalid range format '{}' in get_parsed_segments. Skipping.".format(part)
                continue
        else:
            try:
                num = int(part.strip())
                segments.append((num, num)) # Represent single number as a range
            except ValueError:
                print "Warning: Invalid sequence number format '{}' in get_parsed_segments. Skipping.".format(part)
                continue
    segments.sort() # Sort by the first element of the tuple (start_num)
    return segments

def compute_md5_and_meta(file_path): # Renamed from compute_md5
    """Computes the MD5 checksum, mtime, and size of a given file."""
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk: break
                hasher.update(chunk)
        md5_sum = hasher.hexdigest()
        # Get file metadata
        mtime = os.path.getmtime(file_path)
        size = os.path.getsize(file_path)
        return md5_sum, mtime, size
    except IOError as e: # Py2 FileNotFoundError is IOError
        print "Error accessing file for MD5 {}: {}".format(file_path, e)
        return None, None, None # Return None for all if error
    except Exception as e:
        print "Error computing MD5 for {}: {}".format(file_path, e)
        return None, None, None # Return None for all if error

# Ensure directories for output files exist
ensure_dir_exists(CACHE_FILE)
ensure_dir_exists(OUTPUT_CSV)
ensure_dir_exists(OUTPUT_HTML)

# Load existing MD5 cache
md5_cache = {}
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f: # encoding="utf-8" removed for Py2 basic open
            md5_cache = json.load(f)
    except (ValueError, TypeError) as e: # json.JSONDecodeError is ValueError/TypeError in Py2
        print "Warning: MD5 cache file {} is corrupted. Error: {}".format(CACHE_FILE, e)
    except Exception as e:
        print "Error loading MD5 cache file {}: {}. Starting with an empty cache.".format(CACHE_FILE, e)
else:
    print "MD5 cache file {} not found.".format(CACHE_FILE)

print "--- DIAGNOSTIC: SEQUENCE_RANGES_STR = '{}' ---".format(SEQUENCE_RANGES_STR)

# --- Determine sequences to process ---
user_defined_sequences_set = parse_sequence_ranges_to_set(SEQUENCE_RANGES_STR)
report_sequences_numeric = [] # Defines the full scope of sequences for which data will be collected

if user_defined_sequences_set:
    report_sequences_numeric = sorted(list(user_defined_sequences_set))
    print "DIAGNOSTIC: Mode: User-Defined Ranges."
    print "DIAGNOSTIC: Union of all user-defined sequences to process (sorted): {}".format(report_sequences_numeric)
else:
    print "DIAGNOSTIC: Mode: Auto-Detect."
    actual_sequences_with_files = set()
    for P_DIR in [NAV_P1_DIR, OBP_P1_DIR]:
        if not os.path.isdir(P_DIR):
            print "Warning: Directory not found: {}. Skipping.".format(P_DIR)
            continue
        try:
            for f_name in os.listdir(P_DIR):
                if os.path.isfile(os.path.join(P_DIR, f_name)) and \
                   (f_name.endswith(('.p111', '.p190'))) and \
                   len(f_name) >= 4 and f_name[:4].isdigit():
                    actual_sequences_with_files.add(int(f_name[:4]))
        except OSError as e:
            print "Error listing directory {}: {}".format(P_DIR, e)
    print "DIAGNOSTIC: Actual sequence numbers found with files: {}".format(sorted(list(actual_sequences_with_files)))
    if actual_sequences_with_files:
        min_overall_seq_with_files = min(actual_sequences_with_files)
        max_overall_seq_with_files = max(actual_sequences_with_files)
        print "DIAGNOSTIC: Min overall sequence with files: {}".format(min_overall_seq_with_files)
        print "DIAGNOSTIC: Max overall sequence with files: {}".format(max_overall_seq_with_files)
        report_sequences_numeric = list(xrange(min_overall_seq_with_files, max_overall_seq_with_files + 1))
        print "Auto-detected report range based on actual files: {} to {}.".format(min_overall_seq_with_files, max_overall_seq_with_files)
    else:
        print "No sequences with files found in directories. Report will be empty."

print "DIAGNOSTIC: `report_sequences_numeric` (all sequences script will collect data for): {}".format(report_sequences_numeric)

sequence_data = {}
for seq_num in report_sequences_numeric:
    seq_str = str(seq_num).zfill(4)
    sequence_data[seq_str] = {
        "p1_files": [], "obp_files": [], "p1_final": 'MISSING',
        "nav_md5": None, "obp_md5": None, # Initialize as None, will be 'MISSING' if no file
        "multiple_nav": False, "multiple_obp": False
    }

for P_DIR, file_list_key, dir_type_msg in [(NAV_P1_DIR, "p1_files", "NAV"), (OBP_P1_DIR, "obp_files", "OBP")]:
    if not os.path.isdir(P_DIR):
        print "Warning: {} directory not found: {}.".format(dir_type_msg, P_DIR)
        continue
    try:
        for filename in os.listdir(P_DIR):
            if os.path.isfile(os.path.join(P_DIR, filename)) and (filename.endswith(('.p111', '.p190'))):
                seq_prefix = filename[:4]
                if seq_prefix in sequence_data:
                    sequence_data[seq_prefix][file_list_key].append(filename)
    except OSError as e:
        print "Error listing {} directory {}: {}".format(dir_type_msg, P_DIR, e)

max_actual_data_sequence_num_overall = -1 # Highest seq with data across ALL report_sequences_numeric
if report_sequences_numeric:
    for seq_num_int_iter in report_sequences_numeric:
        seq_key_iter = str(seq_num_int_iter).zfill(4)
        if seq_key_iter in sequence_data and \
           (sequence_data[seq_key_iter]["p1_files"] or sequence_data[seq_key_iter]["obp_files"]):
            max_actual_data_sequence_num_overall = max(max_actual_data_sequence_num_overall, seq_num_int_iter)
print "DIAGNOSTIC: `max_actual_data_sequence_num_overall` (for warning scope): {}".format(max_actual_data_sequence_num_overall)

print "Processing sequence details and computing MD5s..."
for seq_key, data_item in sequence_data.iteritems(): # Py2 iteritems
    # Process NAV files
    if len(data_item["p1_files"]) == 1:
        nav_file_name = data_item["p1_files"][0]
        nav_path = os.path.join(NAV_P1_DIR, nav_file_name)
        
        recompute_nav = True
        if os.path.exists(nav_path):
            try:
                current_mtime_nav = os.path.getmtime(nav_path)
                current_size_nav = os.path.getsize(nav_path)
                cached_entry_nav = md5_cache.get(nav_path)

                if cached_entry_nav and isinstance(cached_entry_nav, dict) and \
                   cached_entry_nav.get("mtime") == current_mtime_nav and \
                   cached_entry_nav.get("size") == current_size_nav and \
                   "md5" in cached_entry_nav:
                    data_item["nav_md5"] = cached_entry_nav["md5"]
                    recompute_nav = False
            except OSError as e:
                print "Warning: Could not get metadata for NAV file {}: {}".format(nav_path, e)
                data_item["nav_md5"] = "METADATA_ERROR" 
                recompute_nav = False # Cannot compare if metadata fails

            if recompute_nav:
                print "Recomputing MD5 for NAV file: {}".format(nav_path) # Diagnostic
                md5_sum, mtime, size = compute_md5_and_meta(nav_path)
                if md5_sum:
                    data_item["nav_md5"] = md5_sum
                    md5_cache[nav_path] = {"md5": md5_sum, "mtime": mtime, "size": size}
                else:
                    data_item["nav_md5"] = "COMPUTATION_FAILED"
        else:
            data_item["nav_md5"] = 'MISSING_AT_SOURCE'
            if nav_path in md5_cache: # Remove from cache if file is now missing
                del md5_cache[nav_path]

    elif len(data_item["p1_files"]) > 1:
        data_item["nav_md5"] = 'MULTIPLE_FILES_DETECTED'
        data_item["multiple_nav"] = True
    else: 
        data_item["nav_md5"] = 'MISSING'

    # Process OBP files
    if len(data_item["obp_files"]) == 1:
        obp_file_name = data_item["obp_files"][0]
        obp_path = os.path.join(OBP_P1_DIR, obp_file_name)

        recompute_obp = True
        if os.path.exists(obp_path):
            try:
                current_mtime_obp = os.path.getmtime(obp_path)
                current_size_obp = os.path.getsize(obp_path)
                cached_entry_obp = md5_cache.get(obp_path)

                if cached_entry_obp and isinstance(cached_entry_obp, dict) and \
                   cached_entry_obp.get("mtime") == current_mtime_obp and \
                   cached_entry_obp.get("size") == current_size_obp and \
                   "md5" in cached_entry_obp:
                    data_item["obp_md5"] = cached_entry_obp["md5"]
                    recompute_obp = False
            except OSError as e:
                print "Warning: Could not get metadata for OBP file {}: {}".format(obp_path, e)
                data_item["obp_md5"] = "METADATA_ERROR"
                recompute_obp = False

            if recompute_obp:
                print "Recomputing MD5 for OBP file: {}".format(obp_path) # Diagnostic
                md5_sum, mtime, size = compute_md5_and_meta(obp_path)
                if md5_sum:
                    data_item["obp_md5"] = md5_sum
                    md5_cache[obp_path] = {"md5": md5_sum, "mtime": mtime, "size": size}
                else:
                    data_item["obp_md5"] = "COMPUTATION_FAILED"
        else:
            data_item["obp_md5"] = 'MISSING_AT_SOURCE'
            if obp_path in md5_cache: # Remove from cache if file is now missing
                del md5_cache[obp_path]

    elif len(data_item["obp_files"]) > 1:
        data_item["obp_md5"] = 'MULTIPLE_FILES_DETECTED'
        data_item["multiple_obp"] = True
    else: 
        data_item["obp_md5"] = 'MISSING'

print "MD5 computation and sequence processing complete."

# Finalize P1 Final status
for seq, data in sequence_data.iteritems():
    if data["multiple_nav"]: 
        data["p1_final"] = 'CHECK NAV DIR!'
    elif data["multiple_obp"]:
        # Only set to CHECK OBP if NAV wasn't already an issue that took precedence for p1_final
        if data["p1_final"] == 'MISSING' or not data["p1_files"]: # Check if p1_final is still default or NAV was MISSING
             data["p1_final"] = 'CHECK OBP DIR!'
    elif data["p1_files"]: # Single NAV file
        data["p1_final"] = data["p1_files"][0]
    elif data["obp_files"]: # No NAV files (single or multiple), but single OBP file
        data["p1_final"] = data["obp_files"][0] # Or indicate it's from OBP
    # If still 'MISSING', it means neither NAV nor OBP had a single valid file.

    # Ensure MD5 fields are not None if they were meant to be computed but failed silently
    if data["nav_md5"] is None: data["nav_md5"] = "UNKNOWN_STATE_NAV"
    if data["obp_md5"] is None: data["obp_md5"] = "UNKNOWN_STATE_OBP"


# --- Identify sequences with issues for summary (conditional warning) ---
sequences_to_check = []
# Iterate based on the sorted report_sequences_numeric for consistent warning order
for seq_num_for_warning in report_sequences_numeric:
    seq_key_str = str(seq_num_for_warning).zfill(4)
    if seq_key_str not in sequence_data: continue

    data = sequence_data[seq_key_str]
    current_seq_num_int = seq_num_for_warning
    nav_md5_str, obp_md5_str = str(data["nav_md5"]), str(data["obp_md5"])
    issue_present_for_warning = False
    are_both_valid_md5s = len(nav_md5_str) == 32 and len(obp_md5_str) == 32

    if are_both_valid_md5s and nav_md5_str != obp_md5_str:
        issue_present_for_warning = True
    else:
        problem_keywords = ["MULTIPLE", "ERROR", "UNKNOWN", "FAILED", "SOURCE", "COMPUTATION_FAILED", "METADATA_ERROR"]
        is_nav_problem = any(kw in nav_md5_str for kw in problem_keywords)
        is_obp_problem = any(kw in obp_md5_str for kw in problem_keywords)
        if is_nav_problem or is_obp_problem:
            issue_present_for_warning = True
        elif (nav_md5_str == 'MISSING' and len(obp_md5_str) == 32) or \
             (obp_md5_str == 'MISSING' and len(nav_md5_str) == 32):
            issue_present_for_warning = True
    
    if issue_present_for_warning:
        if user_defined_sequences_set is None: # Auto-detect mode
            sequences_to_check.append(seq_key_str)
        else: # User-defined range mode
            if max_actual_data_sequence_num_overall == -1:
                sequences_to_check.append(seq_key_str)
            elif current_seq_num_int <= max_actual_data_sequence_num_overall:
                sequences_to_check.append(seq_key_str)
sequence_warning_html_parts = ['<span class="warning">{}</span>'.format(s) for s in sequences_to_check]


# --- Prepare data for table reporting ---
sequence_data_for_table_report = {}
if user_defined_sequences_set is not None:
    print "DIAGNOSTIC: Populating table report for User-Defined Mode."
    parsed_segments = get_parsed_segments(SEQUENCE_RANGES_STR)
    print "DIAGNOSTIC: Parsed segments for table: {}".format(parsed_segments)
    for start_segment, end_segment in parsed_segments:
        max_in_this_segment = -1
        for seq_num_in_segment in xrange(start_segment, end_segment + 1):
            seq_key_in_segment = str(seq_num_in_segment).zfill(4)
            if seq_key_in_segment in sequence_data and \
               (sequence_data[seq_key_in_segment]["p1_files"] or sequence_data[seq_key_in_segment]["obp_files"]):
                if seq_num_in_segment > max_in_this_segment:
                    max_in_this_segment = seq_num_in_segment
        
        limit_for_this_segment_display = end_segment
        if max_in_this_segment != -1: # Data found in this segment
            limit_for_this_segment_display = max_in_this_segment
        # If max_in_this_segment is -1 (no data in segment), limit_for_this_segment_display remains end_segment
        # meaning all sequences in this user-defined-but-empty segment will be shown (as MISSING).
        
        print "DIAGNOSTIC: Segment ({}-{}), max_in_this_segment: {}, display_limit_for_table: {}".format(start_segment,end_segment,max_in_this_segment,limit_for_this_segment_display)

        for seq_num_to_add in xrange(start_segment, limit_for_this_segment_display + 1):
            seq_key_to_add = str(seq_num_to_add).zfill(4)
            if seq_key_to_add in sequence_data: # Ensure it's a sequence we collected data for
                sequence_data_for_table_report[seq_key_to_add] = sequence_data[seq_key_to_add]
else: # Auto-detect mode
    print "DIAGNOSTIC: Populating table report for Auto-Detect Mode."
    # report_sequences_numeric is already min_actual_overall to max_actual_overall
    # So, sequence_data itself is correctly scoped.
    sequence_data_for_table_report = sequence_data

print "DIAGNOSTIC: Keys in `sequence_data_for_table_report` (final for table): {}".format(sorted(sequence_data_for_table_report.keys()))
if user_defined_sequences_set is not None:
     print "Report table will show user-defined segments, truncated if data exists within them (or full segment if empty)."
elif report_sequences_numeric: # Auto-detect mode and there are sequences
     print "Report table will show auto-detected range from {} to {}.".format(report_sequences_numeric[0], report_sequences_numeric[-1])


# --- Write CSV output ---
try:
    with open(OUTPUT_CSV, "wb") as csvfile: # Python 2: 'wb' for csv
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["Sequence Number", "P1 Final", "NAV MD5SUM", "OBP MD5SUM", "MD5SUM XCHECK"])
        # Iterate over sequence_data_for_table_report which is correctly scoped
        for seq, data in sorted(sequence_data_for_table_report.iteritems()): # Py2 iteritems
            p1_final_str = str(data["p1_final"]) # Ensure string for CSV
            nav_md5_val = str(data["nav_md5"])
            obp_md5_val = str(data["obp_md5"])

            md5_xcheck = "ERROR_STATE" # Default
            is_nav_valid, is_obp_valid = len(nav_md5_val) == 32, len(obp_md5_val) == 32
            
            # More specific checks first
            if "MULTIPLE_FILES_DETECTED" in nav_md5_val or "MULTIPLE_FILES_DETECTED" in obp_md5_val: md5_xcheck = "MULTIPLE_FILES_DETECTED"
            elif "MISSING_AT_SOURCE" in nav_md5_val or "MISSING_AT_SOURCE" in obp_md5_val: md5_xcheck = "SOURCE_FILE_MISSING"
            elif "COMPUTATION_FAILED" in nav_md5_val or "COMPUTATION_FAILED" in obp_md5_val: md5_xcheck = "MD5_COMPUTATION_FAILED"
            elif "METADATA_ERROR" in nav_md5_val or "METADATA_ERROR" in obp_md5_val: md5_xcheck = "FILE_METADATA_ERROR"
            elif nav_md5_val == "MISSING" and obp_md5_val == "MISSING": md5_xcheck = "MISSING_FILES" # Both purely missing
            elif not is_nav_valid or not is_obp_valid: # One or both invalid, and not caught by specific errors above
                # This will catch UNKNOWN_STATE or if one is MISSING and other is not a valid MD5
                if nav_md5_val == "MISSING" or obp_md5_val == "MISSING":
                    md5_xcheck = "MISSING_FILES" # One side missing, other invalid (but not error)
                else:
                    md5_xcheck = "INVALID_MD5_DATA" 
            elif nav_md5_val == obp_md5_val: # Both valid and matching
                md5_xcheck = "MD5SUM_MATCHING"
            else: # Both valid but mismatching
                md5_xcheck = "MD5SUM_MISMATCH"
            
            csv_writer.writerow([seq, p1_final_str, nav_md5_val, obp_md5_val, md5_xcheck])
    print "CSV report generated: {}".format(OUTPUT_CSV)
except IOError as e:
    print "Error writing CSV file {}: {}".format(OUTPUT_CSV, e)
except Exception as e:
    print "An unexpected error occurred while writing CSV: {}".format(e)


# --- Generate HTML output ---
html_parts = [] # Build HTML as a list of strings for Py2 .join()
html_parts.append("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><meta http-equiv=\"refresh\" content=\"30\">")
html_parts.append("<title>MD5SUM Checker</title><style>body{font-family:Arial,sans-serif;margin:20px}table{border-collapse:collapse;width:100%;table-layout:auto;box-shadow:0 2px 5px rgba(0,0,0,.1)}")
html_parts.append("td,th{border:1px solid #ddd;padding:8px 10px;white-space:nowrap;text-align:left;word-break:break-all}th{background-color:#f2f2f2;font-weight:bold}")
html_parts.append("tr:nth-child(even){background-color:#f9f9f9}tr:hover{background-color:#f1f1f1}.missing{background-color:#fff3cd;color:#856404;font-weight:bold}")
html_parts.append(".missing-source{background-color:#fddfdf;color:#721c24;font-weight:bold}.multiple{background-color:#ffeeba;color:#856404;font-weight:bold}")
html_parts.append(".nomatch{background-color:#f8d7da;color:#721c24;font-weight:bold}.match{background-color:#d4edda;color:#155724;font-weight:bold}")
html_parts.append(".error{background-color:#f5c6cb;color:#721c24;font-weight:bold}.unknown{background-color:#e2e3e5;color:#383d41;font-weight:bold}")
html_parts.append(".warning{color:red;font-weight:bold;font-size:1.2em;padding:0 3px}h1{text-align:center;font-size:2em;font-weight:bold;margin-bottom:10px;color:#333}")
html_parts.append(".sequence-summary{font-size:1.2em;font-weight:bold;color:black;text-align:center;margin-bottom:20px;padding:10px;border:1px solid #eee;background-color:#f8f9fa;border-radius:5px}")
html_parts.append(".sequence-summary p{margin:5px 0}</style></head><body><h1>MD5SUM Checker Report</h1><div class=\"sequence-summary\">")

if sequences_to_check:
    html_parts.append("<p style=\"color: red;\">Please CHECK Sequence(s): {}</p>".format(", ".join(sequence_warning_html_parts)))
else:
    html_parts.append("<p style=\"color: green;\">All processed sequences appear consistent or have known states within the active data range.</p>")

html_parts.append("</div><table><tr><th>Sequence Number</th><th>P1 Final</th><th>NAV MD5SUM</th><th>OBP MD5SUM</th><th>MD5SUM XCHECK</th></tr>")

# Iterate over sequence_data_for_table_report which is correctly scoped
for seq, data in sorted(sequence_data_for_table_report.iteritems()): # Py2 iteritems
    p1_final_display = str(data["p1_final"])
    nav_md5_display = str(data["nav_md5"])
    obp_md5_display = str(data["obp_md5"])

    p1_class = ""
    if "CHECK" in p1_final_display: p1_class = "multiple"
    elif p1_final_display == "MISSING": p1_class = "missing"

    nav_class = ""
    if "MULTIPLE" in nav_md5_display: nav_class = "multiple"
    elif nav_md5_display == "MISSING": nav_class = "missing"
    elif "MISSING_AT_SOURCE" in nav_md5_display: nav_class = "missing-source"
    elif any(e in nav_md5_display for e in ["ERROR", "FAILED", "COMPUTATION_FAILED", "METADATA_ERROR"]): nav_class = "error"
    elif "UNKNOWN" in nav_md5_display: nav_class = "unknown"
    elif len(nav_md5_display) == 32: nav_class = "" # Valid MD5, class determined by match status

    obp_class = ""
    if "MULTIPLE" in obp_md5_display: obp_class = "multiple"
    elif obp_md5_display == "MISSING": obp_class = "missing"
    elif "MISSING_AT_SOURCE" in obp_md5_display: obp_class = "missing-source"
    elif any(e in obp_md5_display for e in ["ERROR", "FAILED", "COMPUTATION_FAILED", "METADATA_ERROR"]): obp_class = "error"
    elif "UNKNOWN" in obp_md5_display: obp_class = "unknown"
    elif len(obp_md5_display) == 32: obp_class = ""
    
    # MD5SUM XCHECK logic for HTML (mirrors CSV)
    md5_xcheck_display, xcheck_class = "ERROR_STATE", "error" # Default
    is_nav_valid_html, is_obp_valid_html = len(nav_md5_display)==32, len(obp_md5_display)==32

    if "MULTIPLE_FILES_DETECTED" in nav_md5_display or "MULTIPLE_FILES_DETECTED" in obp_md5_display: md5_xcheck_display, xcheck_class = "MULTIPLE_FILES_DETECTED", "multiple"
    elif "MISSING_AT_SOURCE" in nav_md5_display or "MISSING_AT_SOURCE" in obp_md5_display: md5_xcheck_display, xcheck_class = "SOURCE_FILE_MISSING", "missing-source"
    elif "COMPUTATION_FAILED" in nav_md5_display or "COMPUTATION_FAILED" in obp_md5_display: md5_xcheck_display, xcheck_class = "MD5_COMPUTATION_FAILED", "error"
    elif "METADATA_ERROR" in nav_md5_display or "METADATA_ERROR" in obp_md5_display: md5_xcheck_display, xcheck_class = "FILE_METADATA_ERROR", "error"
    elif nav_md5_display == "MISSING" and obp_md5_display == "MISSING": md5_xcheck_display, xcheck_class = "MISSING_FILES", "missing"
    elif not is_nav_valid_html or not is_obp_valid_html:
        if nav_md5_display == "MISSING" or obp_md5_display == "MISSING":
             md5_xcheck_display, xcheck_class = "MISSING_FILES", "missing"
        else:
            md5_xcheck_display = "INVALID_MD5_DATA"
            if "UNKNOWN_STATE" in nav_md5_display or "UNKNOWN_STATE" in obp_md5_display: xcheck_class="unknown"
            # else stays error
    elif nav_md5_display == obp_md5_display:
        md5_xcheck_display, xcheck_class = "MD5SUM_MATCHING", "match"
        if not nav_class : nav_class = "match"
        if not obp_class : obp_class = "match"
    else: # Valid MD5s but mismatch
        md5_xcheck_display, xcheck_class = "MD5SUM_MISMATCH", "nomatch"
        if not nav_class : nav_class = "nomatch"
        if not obp_class : obp_class = "nomatch"
    
    html_parts.append("<tr><td>{}</td><td class=\"{}\">{}</td><td class=\"{}\">{}</td><td class=\"{}\">{}</td><td class=\"{}\">{}</td></tr>".format(
        seq, p1_class, p1_final_display, nav_class, nav_md5_display, obp_class, obp_md5_display, xcheck_class, md5_xcheck_display
    ))
html_parts.append("</table></body></html>")
html_output_content = "".join(html_parts)

try:
    with open(OUTPUT_HTML, "w") as f: # In Py2, 'w' is fine for writing str (which html_output_content is)
        f.write(html_output_content)
    print "HTML report generated: {}".format(OUTPUT_HTML)
except IOError as e:
    print "Error writing HTML file {}: {}".format(OUTPUT_HTML, e)
except Exception as e:
    print "An unexpected error occurred while writing HTML: {}".format(e)

# --- Save updated MD5 cache ---
if md5_cache:
    try:
        ensure_dir_exists(CACHE_FILE) # Ensure directory exists before writing
        with open(CACHE_FILE, "w") as f: # Py2: 'w' for text, json.dump handles encoding
            json.dump(md5_cache, f, indent=4)
        print "MD5 cache updated successfully: {}".format(CACHE_FILE)
    except IOError as e:
        print "Error writing MD5 cache file {}: {}".format(CACHE_FILE, e)
    except Exception as e: # Catch other potential errors during save
        print "An unexpected error occurred while saving MD5 cache: {}".format(e)
else:
    print "MD5 cache is empty. Not writing cache file."
print "Script finished."
