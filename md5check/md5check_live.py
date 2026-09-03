#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
md5check_live.py - P1 MD5SUM cross-check service + web console.

Single-file service, Python standard library only.
Runs on Python 2.7 and Python 3.6+ (RHEL 8: python3 / platform-python).

Replaces the cron-driven md5check.py + install_md5check.sh pair:

  - Cross-checks every sequence's P1 file (.p111 / .p190) between the NAV
    directory and the OBP directory by MD5.
  - MD5s are cached against (mtime, size), so a rescan only re-hashes files
    that actually changed - the job's files run to tens of MB each.
  - Reads Sequence No., Linename, Subline, FSP and LSP straight out of each
    P1 file (header block + first/last shot record) and puts them in the CSV.
  - Serves md5check_live.html + a JSON API on the configured port (6770).
  - Setup lives in the web page: NAV / OBP / output directories and the check
    interval are set there and saved to config.json. No installer to re-run
    for a new job.
  - Start / Stop P1 md5sum monitoring from the page; stopping needs the
    control password.
  - Emits one CSV atomically each time the picture changes.

Nothing is ever deleted: the journal is append-only, source P1 files are
opened read-only, and a failed scan never truncates a delivered CSV.
"""
from __future__ import print_function

import argparse
import csv
import hashlib
import io
import json
import logging
import logging.handlers
import os
import re
import socket
import sys
import threading
import time as time_mod
from datetime import datetime

try:  # Python 3
    from http.server import BaseHTTPRequestHandler
    import socketserver
    from urllib.parse import urlparse, parse_qs, unquote
except ImportError:  # Python 2.7
    from BaseHTTPServer import BaseHTTPRequestHandler
    import SocketServer as socketserver
    from urlparse import urlparse, parse_qs
    from urllib import unquote

try:
    import fcntl
except ImportError:
    fcntl = None  # Windows dev box; flock is POSIX-only
try:
    import msvcrt
except ImportError:
    msvcrt = None  # POSIX; single-instance lock uses fcntl there

APP_VERSION = "1.1.0"

# Bump whenever the P1 metadata extractor changes its output for any input.
# Cached entries carrying an older version have their METADATA re-parsed
# (two small window reads); the cached MD5 is kept, so nothing is re-hashed.
META_VERSION = 1

log = logging.getLogger("md5check_live")

P1_EXTENSIONS = (".p111", ".p190")

# Auto mode lists every sequence between the lowest and highest file it finds so
# a genuinely missing one shows up as MISSING. It stops filling across a jump
# wider than this, which is what keeps one stray filename from inventing
# thousands of phantom rows.
AUTO_MAX_GAP = 100

# Cache entries untouched for this many scans are dropped. Long enough that a
# quiet directory is never re-hashed needlessly, short enough that re-pointing
# Setup at a new job does not carry the old one's entries for ever.
CACHE_RETENTION_SCANS = 500

# The widest span a single "a-b" segment may cover. Shared by the two range
# parsers so they can never disagree about which segments exist.
MAX_RANGE_SPAN = 100000

# CSV column order. The five identity columns come first so a reader can see
# WHICH sequence a row is about before the checksum verdict.
CSV_COLUMNS = ["Sequence No.", "Linename", "Subline", "FSP", "LSP",
               "P1 Final", "NAV MD5SUM", "OBP MD5SUM", "MD5SUM XCHECK"]

# Verdicts written to the MD5SUM XCHECK column.
XCHECK_MATCH = "MD5SUM_MATCHING"
XCHECK_MISMATCH = "MD5SUM_MISMATCH"
XCHECK_MULTIPLE = "MULTIPLE_FILES_DETECTED"
XCHECK_SOURCE_MISSING = "SOURCE_FILE_MISSING"
XCHECK_FAILED = "MD5_COMPUTATION_FAILED"
XCHECK_META_ERROR = "FILE_METADATA_ERROR"
XCHECK_MISSING = "MISSING_FILES"
XCHECK_INVALID = "INVALID_MD5_DATA"

# Per-side markers, carried over from md5check.py so existing readers of the
# CSV keep recognising the states they already know.
M_MISSING = "MISSING"
M_MISSING_AT_SOURCE = "MISSING_AT_SOURCE"
M_MULTIPLE = "MULTIPLE_FILES_DETECTED"
M_FAILED = "COMPUTATION_FAILED"
M_META_ERROR = "METADATA_ERROR"

PROBLEM_KEYWORDS = ("MULTIPLE", "ERROR", "UNKNOWN", "FAILED", "SOURCE")


# ------------------------------------------------------------------ helpers --

def utcnow():
    return datetime.utcnow()


def iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def atomic_write(path, data_bytes):
    """Write bytes via temp file + fsync + rename. Never leaves a partial file."""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    # The temp name carries the pid and thread id: the monitor thread and a
    # request thread can both be writing (CSV, cache, config) at once, and a
    # shared ".tmp" would let one truncate the other's half-written file.
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.current_thread().ident or 0)
    try:
        with open(tmp, "wb") as f:
            f.write(data_bytes)
            f.flush()
            os.fsync(f.fileno())
        if hasattr(os, "replace"):
            os.replace(tmp, path)
        else:  # py2 on Windows cannot atomically overwrite
            if os.path.exists(path):
                os.remove(path)
            os.rename(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)      # never leave a stray temp behind
        except OSError:
            pass
        raise


def sd_notify(msg):
    """Best-effort systemd notify (Type=notify / WatchdogSec). No-op elsewhere."""
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return
    try:
        if path.startswith("@"):
            path = "\0" + path[1:]
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.sendto(msg.encode("utf-8"), path)
        s.close()
    except Exception:
        pass


def browse_roots(config):
    """Folders the web folder-picker may look inside.

    The picker exists to save typing a path, not to be a filesystem browser, so
    it is confined. The configured directories are always included, which keeps
    Setup usable on a machine whose layout differs from the defaults.
    """
    roots = []
    for value in (config.get("browse_roots") or []):
        value = str(value).strip()
        if value:
            roots.append(os.path.abspath(value))
    for key in ("nav_p1_dir", "obp_p1_dir", "output_dir"):
        value = str(config.get(key) or "").strip()
        if value:
            parent = os.path.dirname(os.path.abspath(value)) or os.path.abspath(value)
            if parent not in roots:
                roots.append(parent)
    return roots or [os.path.abspath(os.sep)]


def within_roots(path, roots):
    """True when path is one of the roots or sits underneath one."""
    try:
        target = os.path.abspath(path)
    except (ValueError, TypeError, UnicodeError):
        return False
    if chr(0) in target:
        return False
    for root in roots:
        if target == root:
            return True
        if target.startswith(root.rstrip(os.sep) + os.sep):
            return True
    return False


def csv_bytes(header, rows):
    """Render a CSV as bytes on both interpreters (py2 wants str, py3 unicode)."""
    buf = io.BytesIO() if sys.version_info[0] == 2 else io.StringIO()
    w = csv.writer(buf, lineterminator="\n")

    def cell(v):
        if v is None:
            return ""
        if sys.version_info[0] == 2 and isinstance(v, unicode):  # noqa: F821
            return v.encode("utf-8")
        return v if isinstance(v, str) else str(v)

    w.writerow([cell(h) for h in header])
    for r in rows:
        w.writerow([cell(c) for c in r])
    data = buf.getvalue()
    if isinstance(data, bytes):
        return data
    # A filename that arrived over a share as latin-1 comes back from
    # os.listdir carrying surrogates, which plain utf-8 refuses to encode.
    # The CSV must still be written: the name is escaped, not lost.
    return data.encode("utf-8", "backslashreplace")


# ------------------------------------------------- sequence range selection --

def parse_sequence_ranges(ranges_str):
    """'3001-3500, 4005' -> set([3001..3500, 4005]). Empty/blank -> None.

    None means auto-detect: the scan then covers every sequence that actually
    has a file, which is what an unattended vessel install wants.
    """
    if not ranges_str or not str(ranges_str).strip():
        return None
    selected = set()
    for part in str(ranges_str).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s.strip()), int(end_s.strip())
            except ValueError:
                log.warning("Sequence ranges: ignoring malformed range %r", part)
                continue
            if start > end:
                log.warning("Sequence ranges: ignoring reversed range %r", part)
                continue
            if end - start > MAX_RANGE_SPAN:
                log.warning("Sequence ranges: ignoring absurd range %r", part)
                continue
            selected.update(range(start, end + 1))
        else:
            try:
                selected.add(int(part))
            except ValueError:
                log.warning("Sequence ranges: ignoring malformed number %r", part)
    return selected or None


def sequence_range_problems(ranges_str):
    """Names every segment of a range string that cannot be used.

    Empty list means the whole string is usable (a blank string is usable: it
    means auto-detect).
    """
    problems = []
    if not ranges_str or not str(ranges_str).strip():
        return problems
    for part in str(ranges_str).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s.strip()), int(end_s.strip())
                if start > end:
                    problems.append("%r starts after it ends" % part)
                elif end - start > MAX_RANGE_SPAN:
                    problems.append("%r spans more than %d sequences"
                                    % (part, MAX_RANGE_SPAN))
            else:
                int(part)
        except ValueError:
            problems.append("%r is not a number or a range" % part)
    return problems


def parsed_segments(ranges_str):
    """Same string as ordered (start, end) tuples; a bare number is (n, n)."""
    if not ranges_str or not str(ranges_str).strip():
        return []
    segments = []
    for part in str(ranges_str).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s.strip()), int(end_s.strip())
                if start > end or end - start > MAX_RANGE_SPAN:
                    continue      # same guard as parse_sequence_ranges
            else:
                start = end = int(part)
        except ValueError:
            continue
        segments.append((start, end))
    segments.sort()
    return segments


# ------------------------------------------------- P1 metadata (p111 / p190) --
#
# A production .p111 on this job is tens of megabytes, so the extractor never
# reads a whole file: the header block sits in the first few hundred lines and
# the closing shot record within the last few hundred, so two small windows are
# enough. Results are cached against (mtime, size) alongside the MD5.
#
# Everything here is deliberately forgiving. Real vessel deliveries arrive with
# a byte-order mark, CRLF or bare-CR line endings, latin-1 bytes in a comment,
# lowercase record tags, tabs instead of spaces, quoted fields, keys spelled
# "LINENAME/SUBLINE" or "Line Name / Sub-line", "=" or ":" as the separator,
# and shot points that have drifted out of their standard columns. None of that
# may cost a row in the CSV: a field we cannot read becomes empty, never an
# exception, and never a wrong value.

HEAD_BYTES = 256 * 1024
TAIL_BYTES = 512 * 1024
MAX_TAIL_BYTES = 8 * 1024 * 1024      # give up rather than read a whole file

# Plausible P1/90 data-record identifiers, in the order we prefer them for
# shot points: S = centre of source, V = vessel reference, then the rest.
P190_TYPES = "SVRTCAGZEQ"
P190_PREFERENCE = ("S", "V", "G", "R", "T", "C", "A", "Z", "E", "Q")

# P1/11 record tags that identify the format. Compared case-insensitively.
P111_TAGS = frozenset(("HC", "CC", "H1", "H2", "H3", "H4", "H5", "H6",
                       "S1", "S2", "P1", "P2", "R1", "E1", "T1", "N1",
                       "M1", "V1", "OGP"))

# UKOOA P1/90 standard slots, 0-based [start, end):
#   [0:1]  record identifier      [1:13]  line name
#   [19:25] point number          [25:35] latitude
P190_NAME_SPAN = (1, 13)
P190_POINT_SPAN = (19, 25)

_H_SPLIT = re.compile(r"\s{2,}")
_INT_TOKEN = re.compile(r"[-+]?\d+")
# Latitude in P1/90 is DDMMSS.SS[N|S] - always exactly six digits before the
# decimal point. Matching the DECIMAL POINT is exact where matching the digit
# run is not, because the point-number field runs straight into it with no
# separator ("2113" + "110744.92N" is one unbroken run of digits).
_P190_LAT_DOT = re.compile(r"\.\d{2,4}\s?[NS]")
# Shapes the site's naming convention uses, so a filename missing a component
# is recognised as such instead of being read one slot out of step.
_LINENAME_SHAPE = re.compile(r"^\d+[A-Za-z]\d+$")
_SUBLINE_SHAPE = re.compile(r"^[A-Za-z]\d+$")
P190_LAT_DEGREE_DIGITS = 6
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_BOM = b"\xef\xbb\xbf"


def _norm_key(text):
    """Fold a header key to a comparable form.

    'LINENAME/SUBLINE', 'Line Name / Sub-Line' and 'linename_subline' all
    become 'LINENAMESUBLINE', so a vendor's spelling cannot cost us the field.
    """
    return _NON_ALNUM.sub("", (text or "").upper())


def _clean(value):
    """Trim whitespace and one layer of matching quotes."""
    value = (value or "").strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value


def _read_head(path, nbytes=HEAD_BYTES):
    f = open(path, "rb")
    try:
        blob = f.read(nbytes)
    finally:
        f.close()
    return blob[len(_BOM):] if blob.startswith(_BOM) else blob


def _read_tail(path, nbytes):
    f = open(path, "rb")
    try:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - nbytes)
        f.seek(start)
        return f.read(size - start), start
    finally:
        f.close()


def _text_lines(blob, byte_columns=False):
    """Decode a byte window to text lines, tolerating any 8-bit garbage.

    `byte_columns` picks latin-1, which is total (never raises) and maps one
    byte to exactly one character. Fixed-width P1/90 columns ARE byte columns,
    and utf-8 collapses a multi-byte sequence into a single character, shifting
    every column after it. Comma-delimited P1/11 has no such constraint and is
    decoded as utf-8 so real text survives readably.

    Tabs are expanded because a fixed-width record that picked up tabs
    somewhere in its life still has to line up on the standard boundaries.
    """
    if isinstance(blob, bytes):
        if blob.startswith(_BOM):
            blob = blob[len(_BOM):]
        text = blob.decode("latin-1" if byte_columns else "utf-8", "replace")
    else:
        text = blob
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [ln.expandtabs(8) if "\t" in ln else ln for ln in text.split("\n")]


def _split_csv(line):
    """Split a comma-delimited record, honouring double-quoted fields."""
    if '"' not in line:
        return line.split(",")
    out, field, in_q = [], [], False
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if in_q:
            if ch == '"':
                if i + 1 < n and line[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    in_q = False
            else:
                field.append(ch)
        elif ch == '"':
            in_q = True
        elif ch == ",":
            out.append("".join(field))
            field = []
        else:
            field.append(ch)
        i += 1
    out.append("".join(field))
    return out


def _tag_of(line):
    """The record tag of a comma-delimited line, upper-cased and trimmed."""
    head = line.split(",", 1)[0]
    return _clean(head).upper()


def _int_or_none(tok):
    """The integer a token holds, or None. Accepts '  5471 ', '"5471"', '5471.0'.

    Deliberately strict: a token like '3300A040' is a LINE NAME, not the number
    3300. Digging digits out of alphanumeric text is how a parser silently
    reports a wrong shot point, which is worse than reporting none.
    """
    tok = _clean(tok)
    if not tok:
        return None
    try:
        return int(float(tok))
    except (ValueError, TypeError):
        return None
    except OverflowError:
        return None          # float("inf") parses, int(inf) does not


# --------------------------------------------------------------- format sniff

def sniff_p1_format(path):
    """Return 'p111', 'p190' or ''. Content decides; the extension breaks ties.

    Operations rename files, so a mislabelled file must still be read right.
    Both votes are counted over the same window rather than returning on the
    first hint, because a P1/90 comment line can contain a comma and a P1/11
    header line can look fixed-width.
    """
    votes111 = votes190 = 0
    for raw in _text_lines(_read_head(path, 16384))[:400]:
        line = raw.rstrip()
        if not line.strip():
            continue
        if "," in line:
            tag = _tag_of(line)
            if tag in P111_TAGS:
                votes111 += 3 if tag in ("OGP", "HC", "CC", "S1") else 1
                continue
        ident = line[0:1].upper()
        if ident == "H" and len(line) >= 6 and line[1:5].strip().isdigit():
            votes190 += 2          # H0100-style header record
        elif ident in P190_TYPES and len(line) >= 25:
            if _int_or_none(line[P190_POINT_SPAN[0]:P190_POINT_SPAN[1]]) is not None:
                votes190 += 2
            else:
                votes190 += 1
    if votes111 or votes190:
        return "p111" if votes111 >= votes190 else "p190"
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext if ext in ("p111", "p190") else ""


# ------------------------------------------------------------- P1/11 (comma)

# Normalised header keys -> the field they populate. Checked as an exact match
# first, then as a substring, so both "LINE SEQUENCE NUMBER" and a vendor's
# "SEQUENCE NUMBER OF LINE" land in the right place.
_P111_KEYS = (
    ("LINENAMESUBLINE", "namesub"),
    ("LINENAMESUBLINENAME", "namesub"),
    ("LINESEQUENCENUMBER", "sequence"),
    ("SEQUENCENUMBER", "sequence"),
    ("LINESEQUENCE", "sequence"),
    ("SEQUENCENO", "sequence"),
    ("SEQNO", "sequence"),
    ("SEQUENCE", "sequence"),
    ("LINEPREFIX", "prefix"),
    ("LINENAME", "linename"),
    ("SUBLINE", "subline"),
)


def _p111_key_field(key):
    norm = _norm_key(key)
    if not norm:
        return ""
    for candidate, field in _P111_KEYS:
        if norm == candidate:
            return field
    # Substring pass. "SUB LINE NAME" contains both SUBLINE and LINENAME, and
    # picking whichever appears first in the table is a coin toss - so when the
    # matches disagree, report nothing and let a cleaner record or the filename
    # supply the value.
    matched = set(field for candidate, field in _P111_KEYS if candidate in norm)
    if len(matched) == 1:
        return matched.pop()
    return ""


def _p111_cc_pair(line):
    """`CC,1,0,0,LINE PREFIX = T26A` -> ('LINE PREFIX', 'T26A').

    The comment body is everything after the 4th comma, so a body that itself
    contains commas survives intact. Either '=' or ':' separates key from value.
    """
    parts = line.split(",", 4)
    if len(parts) < 5:
        return "", ""
    body = parts[4]
    cut = -1
    for sep in ("=", ":"):
        idx = body.find(sep)
        if idx >= 0 and (cut < 0 or idx < cut):
            cut = idx
    if cut < 0:
        return "", ""
    return _clean(body[:cut]), _clean(body[cut + 1:])


def _split_name_sub(value):
    """'/3682A001/c0001' -> ('3682A001', 'c0001').

    Accepts '/' or '\\' as the separator, a missing leading separator, and a
    missing half. Anything else yields empty strings rather than a guess.
    """
    bits = [_clean(b) for b in re.split(r"[/\\]", value or "")]
    bits = [b for b in bits if b]
    if len(bits) >= 2:
        return bits[-2], bits[-1]
    if len(bits) == 1:
        return bits[0], ""
    return "", ""


def _p111_sp_from_fields(f, linename):
    """Point number of an S1 record.

    The standard puts it at field 4 (0-based) with field 5 repeating it, and
    field 2 carrying the line name. If the file's columns have shifted, locate
    the line name and take the first integer that follows it, so a re-ordered
    record still yields the right value instead of a neighbouring field.
    """
    # P1/11 writes the point number TWICE in a row (preplot point, then actual
    # point). That duplicated pair is a self-validating anchor: it identifies
    # the field no matter where the columns sit, and it needs no agreement with
    # the header, which a re-shot or hand-edited file may contradict. The
    # search starts past the line-name/line-number pair so "0,0"-style leading
    # flags cannot be mistaken for it.
    for idx in range(3, len(f) - 1):
        left = _int_or_none(f[idx])
        if left is None:
            continue
        if left == _int_or_none(f[idx + 1]):
            return left
    # No duplicated pair. Fall back to the standard slot, but only when the
    # record really has the standard shape - otherwise we would be reading
    # whichever field happens to sit at index 4.
    if len(f) > 2 and (not linename or _clean(f[2]) == linename):
        for idx in (4, 5):
            if len(f) > idx:
                value = _int_or_none(f[idx])
                if value is not None:
                    return value
    return None


def _p111_head(path):
    """Header comment metadata plus the first S1 (source) record.

    Reads a growing head window: a delivery with one enormous comment line at
    the top can push the header block and the first shot record past the
    default window, and returning "no data" for a perfectly good file is not
    acceptable. The window only grows while the previous read came back full,
    so a small file is still read exactly once.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    want = HEAD_BYTES
    while True:
        blob = _read_head(path, want)
        # A window that did not reach EOF ends mid-record; that fragment must
        # not be parsed as if it were a whole one.
        out = _p111_head_window(blob, truncated=(size > want))
        if out["fsp"] is not None or want >= MAX_TAIL_BYTES or size <= want:
            return out
        want *= 4


def _p111_head_window(blob, truncated=False):
    out = {"linename": "", "subline": "", "sequence": "", "prefix": "",
           "fsp": None, "s1_fields": None}
    lines = _text_lines(blob)
    if truncated and lines:
        lines = lines[:-1]
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        tag = _tag_of(line)
        if tag == "CC":
            key, value = _p111_cc_pair(line)
            if not key:
                continue
            field = _p111_key_field(key)
            if field == "namesub":
                name, sub = _split_name_sub(value)
                out["linename"] = out["linename"] or name
                out["subline"] = out["subline"] or sub
            elif field and not out.get(field):
                out[field] = value
        elif tag == "S1" and out["fsp"] is None:
            f = _split_csv(line)
            out["s1_fields"] = f
            if not out["linename"] and len(f) > 2:
                out["linename"] = _clean(f[2])
            out["fsp"] = _p111_sp_from_fields(f, out["linename"])
    return out


def _p111_last_sp(path, linename):
    """Point number of the closing S1 record, read backwards from EOF."""
    want = TAIL_BYTES
    while want <= MAX_TAIL_BYTES:
        blob, start = _read_tail(path, want)
        lines = _text_lines(blob)
        if start > 0 and lines:
            lines = lines[1:]           # the first line is a fragment
        for raw in reversed(lines):
            line = raw.rstrip()
            if not line.strip() or _tag_of(line) != "S1":
                continue
            value = _p111_sp_from_fields(_split_csv(line), linename)
            if value is not None:
                return value
        if start == 0:
            break                        # the whole file has been scanned
        want *= 4
    return None


# ------------------------------------------------------- P1/90 (fixed width)

def _h_value(body):
    """Trailing value of a fixed-slot P1/90 header line."""
    parts = _H_SPLIT.split(body.strip())
    return _clean(parts[-1]) if len(parts) >= 2 else ""


def _p190_line(raw):
    """Normalise one P1/90 record.

    A whole record shifted right by stray leading whitespace is realistic and
    recoverable: column 1 is always the record identifier, so if the line does
    not start with one but does after trimming, the trim is the fix. Nothing
    else about the fixed-width layout is second-guessed.
    """
    line = raw.rstrip()
    if not line:
        return ""
    if line[0:1].upper() in ("H",) + tuple(P190_TYPES):
        return line
    stripped = line.lstrip()
    if stripped[0:1].upper() in ("H",) + tuple(P190_TYPES):
        return stripped
    return line


def _p190_point(line, span):
    """Point number of a P1/90 record, or None if the columns were not located.

    A slice that runs past the end of the line is a record the file cut short;
    the digits present are half a field, so they are refused.
    """
    if span is None or len(line) <= span[0]:
        return None
    if len(line) < span[1]:
        return None
    return _int_or_none(line[span[0]:span[1]])


def _p190_detect_point_span(samples):
    """Find the column span holding the point number.

    The standard is [19:25) and is tried first. If a vendor has shifted the
    columns, the span is inferred from the first integer token that starts at
    or after the line-name field and agrees across every sample - agreement is
    what stops us locking on to a latitude or a vessel id.
    """
    if not samples:
        return P190_POINT_SPAN
    # Fixed-width records cannot be tokenised - "2113" followed by latitude
    # "110744.92N" reads as the single run "2113110744". So anchor on the
    # latitude instead: it has an unmistakable shape and begins exactly where
    # the point-number field ends.
    cands = []
    for text in samples:
        m = _P190_LAT_DOT.search(text)
        if not m:
            continue
        end = m.start() - P190_LAT_DEGREE_DIGITS   # where latitude begins
        if end <= P190_NAME_SPAN[1]:
            continue
        start = end
        while start > P190_NAME_SPAN[1] and text[start - 1].isdigit():
            start -= 1
        if start < end:
            cands.append((start, end))
    # The field is right-aligned, so its END column is the stable one; every
    # sample must agree on it before the detection is trusted at all.
    if len(cands) == len(samples):
        ends = set(end for _, end in cands)
        if len(ends) == 1:
            span = (min(start for start, _ in cands), ends.pop())
            if all(_int_or_none(t[span[0]:span[1]]) is not None
                   for t in samples):
                return span
    # No usable latitude anchor. Fall back to the standard slot only when it is
    # not visibly bleeding into a neighbouring field: a digit hard against
    # either edge means the columns have shifted and the slice would be a
    # truncation. Better an empty FSP than a confidently wrong one.
    lo, hi = P190_POINT_SPAN
    for text in samples:
        if _int_or_none(text[lo:hi]) is None:
            return None
        if text[lo - 1:lo].isdigit() or text[hi:hi + 1].isdigit():
            return None
    return P190_POINT_SPAN


def _p190_head(path):
    """First data record per identifier, the point-column span, and H metadata."""
    firsts, samples = {}, {}
    header = {"linename": "", "sequence": "", "subline": ""}
    for raw in _text_lines(_read_head(path), byte_columns=True):
        line = _p190_line(raw)
        if not line.strip():
            continue
        ident = line[0:1].upper()
        if ident == "H":
            upper = line.upper()
            body = line[5:] if len(line) > 5 else ""
            if "LINE NAME" in upper or "LINE NUMBER" in upper:
                header["linename"] = header["linename"] or _h_value(body)
            if "SEQUENCE" in upper:
                header["sequence"] = header["sequence"] or _h_value(body)
            if "SUB LINE" in upper or "SUBLINE" in upper:
                header["subline"] = header["subline"] or _h_value(body)
            continue
        if ident in P190_TYPES and len(line) > P190_NAME_SPAN[1]:
            bucket = samples.setdefault(ident, [])
            if len(bucket) < 8:
                bucket.append(line)
    for ident, lines in samples.items():
        span = _p190_detect_point_span(lines)
        for line in lines:
            point = _p190_point(line, span)
            if point is not None:
                firsts[ident] = (_clean(line[P190_NAME_SPAN[0]:P190_NAME_SPAN[1]]),
                                 point, span)
                break
    return firsts, header


def _p190_last_sp(path, ident, span):
    """Point of the last record sharing the identifier that gave us FSP."""
    want = TAIL_BYTES
    while want <= MAX_TAIL_BYTES:
        blob, start = _read_tail(path, want)
        lines = _text_lines(blob, byte_columns=True)
        if start > 0 and lines:
            lines = lines[1:]
        for raw in reversed(lines):
            line = _p190_line(raw)
            if not line.strip() or line[0:1].upper() != ident:
                continue
            point = _p190_point(line, span)
            if point is not None:
                return point
        if start == 0:
            break
        want *= 4
    return None


# ------------------------------------------------------------ filename hints

def filename_hints(filename):
    """What the site's naming convention already encodes.

    Observed on this job:
        0001.T26A.3682A001.c0001.GFUNREG.VES.p111
        seq .prefix.linename.subline.type   .vessel.ext
    Separators may be '.', '_' or '-'; leading and trailing whitespace in a
    filename is ignored. These are fallbacks only - a value read out of the
    file itself always wins.
    """
    hints = {"sequence": "", "prefix": "", "linename": "", "subline": ""}
    base = os.path.basename(filename or "").strip()
    if len(base) >= 4 and base[:4].isdigit():
        hints["sequence"] = base[:4]
    stem = os.path.splitext(base)[0]
    parts = [p.strip() for p in re.split(r"[._-]", stem)]
    parts = [p for p in parts if p]
    # seq.prefix.linename.subline... - but only when the slots actually look
    # like a line name and a subline. A name that omits the prefix would
    # otherwise shift every field one place left and report a vessel code as
    # the subline.
    if len(parts) >= 4 and parts[0].isdigit()             and _LINENAME_SHAPE.match(parts[2]) and _SUBLINE_SHAPE.match(parts[3]):
        hints["prefix"] = parts[1]
        hints["linename"] = parts[2]
        hints["subline"] = parts[3]
    return hints


def sequence_key_from_name(filename, width=4):
    """The grouping key for a file, or '' if the name carries no number.

    md5check.py grouped strictly on the leading four digits and this keeps that
    as the primary rule. The relaxed fallback (first run of digits anywhere in
    the name) is only ever consulted by the scanner when the strict rule
    matched nothing at all in a directory that plainly holds P1 files.
    """
    base = os.path.basename(filename or "").strip()
    if len(base) >= width and base[:width].isdigit():
        if base[width:width + 1].isdigit():
            return ""      # a longer run: 10001 is not sequence 1000
        return base[:width]
    return ""


def relaxed_sequence_key(filename, width=4):
    """First run of digits anywhere in the name, zero-padded. '' if none."""
    stem = os.path.splitext(os.path.basename(filename or "").strip())[0]
    values = set()
    for token in re.split(r"[^0-9A-Za-z]+", stem):
        if not token:
            continue
        if token.isdigit():
            values.add(int(token))
            continue
        m = re.search(r"\d+$", token)
        if m:
            # A TRAILING digit run ("SEQ42", "c0001", "3682A001") is a
            # plausible sequence. Digits buried mid-token ("T26A") are part of
            # a code, not a number, and must never win.
            values.add(int(m.group(0)))
    if len(values) != 1:
        return ""          # nothing, or candidates that disagree: refuse
    value = values.pop()
    if value >= 10 ** width:
        return ""          # will not fit the key width without truncating
    return str(value).zfill(width)


# ------------------------------------------------------------------- public

def parse_p1_metadata(path):
    """Sequence / Linename / Subline / FSP / LSP for one .p111 or .p190 file.

    Every field degrades to "" (or None for the shot points) rather than
    raising: a half-written, renamed or unfamiliar file must still produce a
    CSV row.
    """
    meta = {"format": "", "sequence": "", "linename": "", "subline": "",
            "fsp": None, "lsp": None, "prefix": "", "error": ""}
    hints = filename_hints(path)
    try:
        fmt = sniff_p1_format(path)
        meta["format"] = fmt
        if fmt == "p111":
            head = _p111_head(path)
            meta["linename"] = head["linename"]
            meta["subline"] = head["subline"]
            meta["sequence"] = head["sequence"]
            meta["prefix"] = head["prefix"]
            meta["fsp"] = head["fsp"]
            if head["fsp"] is not None:
                meta["lsp"] = _p111_last_sp(path, head["linename"])
        elif fmt == "p190":
            firsts, header = _p190_head(path)
            ident = ""
            for cand in P190_PREFERENCE:
                if cand in firsts:
                    ident = cand
                    break
            if not ident and firsts:
                ident = sorted(firsts.keys())[0]
            if ident:
                linename, point, span = firsts[ident]
                meta["linename"] = linename
                meta["fsp"] = point
                meta["lsp"] = _p190_last_sp(path, ident, span)
            meta["linename"] = meta["linename"] or header["linename"]
            meta["sequence"] = header["sequence"]
            meta["subline"] = header["subline"]
    except (IOError, OSError) as exc:
        meta["error"] = str(exc)
    except Exception as exc:            # never let one odd file stop a scan
        meta["error"] = "parse error: %s" % exc

    for key in ("sequence", "linename", "subline", "prefix"):
        if not meta[key]:
            meta[key] = hints[key]
        meta[key] = _clean(meta[key])
    meta["sequence"] = _normalise_sequence(meta["sequence"]) or         _normalise_sequence(hints["sequence"])
    return meta


def _normalise_sequence(value):
    """'0001' / '1' / ' 12 ' -> '0001' / '0001' / '0012'. Anything else -> ''.

    Scraping digits out of a value is what turns "0001 (RESHOOT 2)" into
    sequence 00012 and a stray unicode digit into a crash. A sequence either
    IS a plain number or we do not have one.
    """
    value = _clean(value)
    if not value or not all("0" <= c <= "9" for c in value):
        return ""
    try:
        return str(int(value)).zfill(4)
    except (ValueError, OverflowError):
        return ""


def compute_md5_and_meta(path):
    """MD5 + mtime + size of one file, streamed so a 70 MB P1 stays cheap."""
    hasher = hashlib.md5()
    try:
        mtime_before = os.path.getmtime(path)
        size_before = os.path.getsize(path)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        # A P1 file still being written by the navigation system would
        # otherwise be hashed half-complete and that hash CACHED, so the
        # mismatch would never clear. Re-stat: if anything moved, report no
        # hash and let the next tick pick it up.
        if (os.path.getmtime(path) != mtime_before
                or os.path.getsize(path) != size_before):
            log.info("%s changed while being hashed - retrying next tick", path)
            return None, None, None
        return hasher.hexdigest(), mtime_before, size_before
    except (IOError, OSError) as exc:
        log.warning("Cannot hash %s: %s", path, exc)
        return None, None, None


# ------------------------------------------------------------------- config --

DEFAULT_CONFIG = {
    "nav_p1_dir": "/usr/local/trinop/dbase/links/P111/P111-SSREG",
    "obp_p1_dir": "/usr/local/trinop/dbase/links/nav2dp/c3190/P111",
    "output_dir": "/usr/local/trinop/qcfiles/md5sum",
    "csv_name": "md5check.csv",
    "bind": "0.0.0.0",
    "port": 6770,
    "check_interval_seconds": 60,
    "sequence_ranges": "",
    "control_password": "swadmin!",
    "journal_dir": "",
    "running": False,
    # Folders the web folder-picker may look inside. The configured NAV/OBP/
    # output parents are always added to this list at request time.
    "browse_roots": ["/usr/local/trinop", "/home", "/mnt", "/media"],
}


class Config(object):
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.lock = threading.Lock()
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with io.open(self.path, "r", encoding="utf-8",
                             errors="replace") as f:
                    stored = json.load(f)
                for k, v in stored.items():
                    self.data[k] = v
            except Exception as exc:
                log.error("Cannot read config %s: %s (using defaults)", self.path, exc)
        else:
            self.save()

    def save(self):
        with self.lock:
            data = json.dumps(self.data, indent=2, sort_keys=True).encode("utf-8")
        atomic_write(self.path, data)

    def get(self, key):
        with self.lock:
            return self.data.get(key, DEFAULT_CONFIG.get(key))

    def update(self, patch):
        with self.lock:
            self.data.update(patch)
        self.save()

    def snapshot(self):
        with self.lock:
            return dict(self.data)


# ------------------------------------------------------------------ journal --

class Journal(object):
    """Append-only JSONL, SHA-256 hash-chained.

    The durable record of every Setup save and every start/stop. There is no
    delete path: entries are only ever appended.
    """

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.n = 0
        self.last_hash = ""
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with io.open(self.path, "r", encoding="utf-8",
                             errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    self.n += 1
                    self.last_hash = rec.get("hash", self.last_hash)
        except (IOError, OSError) as exc:
            log.error("Cannot read journal %s: %s", self.path, exc)

    def append(self, entry):
        with self.lock:
            entry = dict(entry)
            entry["n"] = self.n + 1
            entry["t"] = iso(utcnow())
            entry["prev"] = self.last_hash
            payload = json.dumps(entry, sort_keys=True)
            entry["hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            d = os.path.dirname(self.path)
            if d and not os.path.isdir(d):
                os.makedirs(d)
            try:
                with io.open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, sort_keys=True) + u"\n")
            except (IOError, OSError) as exc:
                log.error("Cannot append to journal %s: %s", self.path, exc)
                return self.n
            self.n += 1
            self.last_hash = entry["hash"]
            return self.n

    def verify(self):
        """Re-walk the chain. Returns (ok, entries, first_bad_line_number)."""
        prev, count = "", 0
        if not os.path.exists(self.path):
            return True, 0, None
        with io.open(self.path, "r", encoding="utf-8",
                             errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    return False, count, lineno
                stored = rec.pop("hash", "")
                if rec.get("prev", "") != prev:
                    return False, count, lineno
                calc = hashlib.sha256(
                    json.dumps(rec, sort_keys=True).encode("utf-8")).hexdigest()
                if calc != stored:
                    return False, count, lineno
                prev = stored
                count += 1
        return True, count, None

    def count(self):
        return self.n


# -------------------------------------------------------------------- store --

class Store(object):
    """The current cross-check picture plus the (mtime, size)-keyed cache.

    The cache carries both the MD5 and the parsed P1 metadata: neither has to
    be recomputed while a file's mtime and size are unchanged, which is what
    keeps a 60-second interval affordable over a multi-gigabyte directory.
    """

    def __init__(self, cache_path):
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self.read_only = False        # `verify` sets this: audit, never write
        self.cache = {}
        self.meta_refreshed = 0
        self.listing_error = ""
        self.rows = []
        self.last_scan = None
        self.last_scan_secs = 0.0
        self.last_scan_hashed = 0
        self.scan_count = 0
        self.csv_md5 = ""
        self.csv_rows = 0
        self.csv_path_written = ""
        self.last_error = ""
        self.load_cache()

    # -- cache ---------------------------------------------------------------

    def load_cache(self):
        if not os.path.exists(self.cache_path):
            return
        try:
            with io.open(self.cache_path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self.cache = stored
        except Exception as exc:
            log.warning("MD5 cache %s unreadable (%s) - starting empty",
                        self.cache_path, exc)
            self.cache = {}

    def save_cache(self):
        if self.read_only:
            return
        try:
            atomic_write(self.cache_path,
                         json.dumps(self.cache, indent=1, sort_keys=True).encode("utf-8"))
        except (IOError, OSError) as exc:
            log.error("Cannot write MD5 cache %s: %s", self.cache_path, exc)

    def lookup(self, path):
        """Cached (md5, meta) for path if its mtime and size still match."""
        entry = self.cache.get(path)
        if not isinstance(entry, dict):
            return None, None
        try:
            mtime = os.path.getmtime(path)
            size = os.path.getsize(path)
        except OSError:
            return None, None
        if entry.get("mtime") != mtime or entry.get("size") != size:
            return None, None
        meta = entry.get("meta")
        if entry.get("mv") != META_VERSION:
            meta = None          # extractor changed: re-parse, but do not re-hash
        return entry.get("md5"), meta

    def remember(self, path, md5, mtime, size, meta):
        self.cache[path] = {"md5": md5, "mtime": mtime, "size": size,
                            "meta": meta, "mv": META_VERSION,
                            "seen": self.scan_count}

    def touch(self, path):
        entry = self.cache.get(path)
        if isinstance(entry, dict):
            entry["seen"] = self.scan_count

    def prune(self):
        """Drop entries no scan has touched for a long time.

        A file is only forgotten when it goes missing DURING a scan, so a
        directory that is re-pointed at a new job would otherwise leave the old
        job's entries in the cache for ever. Ageing them out bounds the file
        without ever discarding an entry still in use.
        """
        cutoff = self.scan_count - CACHE_RETENTION_SCANS
        if cutoff <= 0:
            return 0
        stale = [k for k, v in self.cache.items()
                 if not isinstance(v, dict) or v.get("seen", 0) < cutoff]
        for k in stale:
            del self.cache[k]
        if stale:
            log.info("MD5 cache: dropped %d entry(ies) untouched for %d scans",
                     len(stale), CACHE_RETENTION_SCANS)
        return len(stale)

    def remember_meta(self, path, meta):
        """Refresh only the metadata of an entry whose MD5 is still valid."""
        entry = self.cache.get(path)
        if isinstance(entry, dict):
            entry["meta"] = meta
            entry["mv"] = META_VERSION

    def forget(self, path):
        self.cache.pop(path, None)

    # -- snapshot ------------------------------------------------------------

    def snapshot(self):
        with self.lock:
            return list(self.rows)


# ------------------------------------------------------------------ scanner --

def classify(nav_md5, obp_md5):
    """The MD5SUM XCHECK verdict for one sequence.

    Ordering matters: a specific fault (two files on one side, a file that
    vanished mid-scan, an unreadable file) is more useful than the generic
    "these two strings differ", so those are decided first.
    """
    nav, obp = str(nav_md5), str(obp_md5)
    nav_valid, obp_valid = len(nav) == 32, len(obp) == 32
    if M_MULTIPLE in nav or M_MULTIPLE in obp:
        return XCHECK_MULTIPLE
    if M_MISSING_AT_SOURCE in nav or M_MISSING_AT_SOURCE in obp:
        return XCHECK_SOURCE_MISSING
    if M_FAILED in nav or M_FAILED in obp:
        return XCHECK_FAILED
    if M_META_ERROR in nav or M_META_ERROR in obp:
        return XCHECK_META_ERROR
    if nav == M_MISSING and obp == M_MISSING:
        return XCHECK_MISSING
    if not nav_valid or not obp_valid:
        if nav == M_MISSING or obp == M_MISSING:
            return XCHECK_MISSING
        return XCHECK_INVALID
    return XCHECK_MATCH if nav == obp else XCHECK_MISMATCH


def needs_attention(verdict):
    return verdict not in (XCHECK_MATCH,)


class Scanner(object):
    """One pass over the NAV and OBP directories."""

    def __init__(self, config, store):
        self.config = config
        self.store = store

    # -- directory listing ---------------------------------------------------

    def p1_names(self, directory):
        """Every .p111/.p190 file in one directory, plus a listing error.

        The extension test is case-insensitive and tolerates trailing
        whitespace in a name. A name that cannot even be joined to a path
        (an undecodable byte sequence on py2) is skipped rather than
        aborting the whole directory.
        """
        names = []
        if not directory or not os.path.isdir(directory):
            return names, "directory not found: %s" % (directory or "(not set)")
        try:
            entries = os.listdir(directory)
        except OSError as exc:
            return names, str(exc)
        for name in entries:
            try:
                if not name.strip().lower().endswith(P1_EXTENSIONS):
                    continue
                if not os.path.isfile(os.path.join(directory, name)):
                    continue
            except (OSError, UnicodeError, ValueError):
                continue
            names.append(name)
        return names, ""

    @staticmethod
    def group_by_sequence(names, relaxed):
        """{seq_key: [filename, ...]}, sorted for stable 'multiple files' order."""
        found = {}
        for name in names:
            key = sequence_key_from_name(name)
            if not key and relaxed:
                key = relaxed_sequence_key(name)
            if not key:
                continue
            found.setdefault(key, []).append(name)
        for key in found:
            found[key].sort()
        return found

    def list_p1_files(self, directory, relaxed=False):
        """{seq_key: [filename, ...]} for one directory, plus a listing error."""
        names, err = self.p1_names(directory)
        return self.group_by_sequence(names, relaxed), err

    # -- per-file md5 + metadata --------------------------------------------

    def file_state(self, directory, filenames):
        """(md5_or_marker, metadata_or_None, hashed_flag) for one side."""
        if not filenames:
            return M_MISSING, None, False
        if len(filenames) > 1:
            return M_MULTIPLE, None, False
        path = os.path.join(directory, filenames[0])
        if not os.path.exists(path):
            self.store.forget(path)
            return M_MISSING_AT_SOURCE, None, False

        cached_md5, cached_meta = self.store.lookup(path)
        if cached_md5:
            self.store.touch(path)
            if cached_meta is None:
                # The hash is still good; only the extractor moved on.
                cached_meta = parse_p1_metadata(path)
                self.store.remember_meta(path, cached_meta)
                self.store.meta_refreshed += 1
            return cached_md5, cached_meta, False

        try:
            os.path.getmtime(path)
            os.path.getsize(path)
        except OSError as exc:
            log.warning("Cannot stat %s: %s", path, exc)
            return M_META_ERROR, None, False

        md5, mtime, size = compute_md5_and_meta(path)
        if not md5:
            return M_FAILED, None, False
        meta = parse_p1_metadata(path)
        self.store.remember(path, md5, mtime, size, meta)
        return md5, meta, True

    # -- the scan ------------------------------------------------------------

    def scan(self):
        started = time_mod.time()
        cfg = self.config.snapshot()
        nav_dir = str(cfg.get("nav_p1_dir") or "")
        obp_dir = str(cfg.get("obp_p1_dir") or "")

        nav_names, nav_err = self.p1_names(nav_dir)
        obp_names, obp_err = self.p1_names(obp_dir)

        # md5check.py has always grouped on the leading four digits, and that
        # stays the rule. Only when a directory plainly holds P1 files but not
        # one of them starts with four digits do we fall back to "first run of
        # digits anywhere in the name" - and then for BOTH sides at once, so
        # the two directories can never be keyed differently and report
        # phantom mismatches.
        sides = [names for names in (nav_names, obp_names) if names]
        relaxed = bool(sides) and all(
            not self.group_by_sequence(names, False) for names in sides)
        if relaxed:
            log.warning("No filename starts with a 4-digit sequence; grouping on "
                        "the first digits found in each name instead.")
        nav_files = self.group_by_sequence(nav_names, relaxed)
        obp_files = self.group_by_sequence(obp_names, relaxed)

        selected = parse_sequence_ranges(cfg.get("sequence_ranges"))
        with_files = set()
        for key in list(nav_files.keys()) + list(obp_files.keys()):
            try:
                with_files.add(int(key))
            except ValueError:
                continue

        if selected is not None:
            # User-defined mode: cover the requested numbers, but stop each
            # segment at its last sequence that actually has a file, so a
            # 3001-3500 range does not print 400 phantom MISSING rows.
            report = set()
            for start, end in parsed_segments(cfg.get("sequence_ranges")):
                present = [n for n in with_files if start <= n <= end]
                limit = max(present) if present else end
                report.update(range(start, limit + 1))
            report &= selected
            sequences = sorted(report)
            mode = "ranges"
        elif with_files:
            # Fill the gaps BETWEEN acquired sequences so a missing sequence is
            # visible, but never bridge an implausible jump: a single stray
            # file (a preplot named 3190_... sitting next to sequence 0001)
            # would otherwise manufacture thousands of phantom MISSING rows.
            ordered = sorted(with_files)
            sequences = [ordered[0]]
            for prev, cur in zip(ordered, ordered[1:]):
                if cur - prev <= AUTO_MAX_GAP:
                    sequences.extend(range(prev + 1, cur))
                else:
                    log.warning("Sequence %04d is %d beyond %04d; not filling "
                                "the gap (check for a stray file)",
                                cur, cur - prev, prev)
                sequences.append(cur)
            mode = "auto"
        else:
            sequences = []
            mode = "auto"

        rows, hashed = [], 0
        for num in sequences:
            key = str(num).zfill(4)
            nav_list = nav_files.get(key, [])
            obp_list = obp_files.get(key, [])

            nav_md5, nav_meta, h1 = self.file_state(nav_dir, nav_list)
            obp_md5, obp_meta, h2 = self.file_state(obp_dir, obp_list)
            hashed += int(h1) + int(h2)

            # P1 Final keeps md5check.py's meaning: the NAV filename when the
            # NAV side is clean, otherwise the OBP one, otherwise a flag.
            if len(nav_list) > 1:
                p1_final = "CHECK NAV DIR!"
            elif len(obp_list) > 1:
                p1_final = "CHECK OBP DIR!"
            elif nav_list:
                p1_final = nav_list[0]
            elif obp_list:
                p1_final = obp_list[0]
            else:
                p1_final = M_MISSING

            # Identity fields come from whichever side parsed; NAV wins because
            # it is the navigation system's own output.
            meta = nav_meta or obp_meta or {}
            hints = {}
            if not meta:
                source_name = (nav_list or obp_list or [""])[0]
                hints = filename_hints(source_name) if source_name else {}

            verdict = classify(nav_md5, obp_md5)
            rows.append({
                "seq": key,
                "linename": meta.get("linename") or hints.get("linename", ""),
                "subline": meta.get("subline") or hints.get("subline", ""),
                "fsp": meta.get("fsp"),
                "lsp": meta.get("lsp"),
                "p1_final": p1_final,
                "nav_md5": nav_md5,
                "obp_md5": obp_md5,
                "xcheck": verdict,
                "attention": needs_attention(verdict),
            })

        elapsed = time_mod.time() - started
        with self.store.lock:
            self.store.listing_error = " / ".join(e for e in (nav_err, obp_err) if e)
            self.store.rows = rows
            self.store.last_scan = utcnow()
            self.store.last_scan_secs = elapsed
            self.store.last_scan_hashed = hashed
            self.store.scan_count += 1
            self.store.last_error = " / ".join(e for e in (nav_err, obp_err) if e)
        refreshed = self.store.meta_refreshed
        self.store.meta_refreshed = 0
        pruned = self.store.prune()
        # Persist after a re-parse sweep too, or every restart would repeat it.
        if hashed or refreshed or pruned:
            self.store.save_cache()
        log.info("Scan #%d: %d sequence(s), %d file(s) hashed, %.2fs (mode=%s)",
                 self.store.scan_count, len(rows), hashed, elapsed, mode)
        if refreshed:
            log.info("Metadata extractor v%d superseded the cache: %d file(s) "
                     "re-read (no re-hashing)", META_VERSION, refreshed)
        return rows


# ------------------------------------------------------------------ service --

class Service(object):
    def __init__(self, config_path):
        self.config = Config(config_path)
        here = os.path.dirname(os.path.abspath(config_path))
        self.state_dir = str(self.config.get("journal_dir") or "") or \
            os.path.join(here, "state")
        if not os.path.isdir(self.state_dir):
            os.makedirs(self.state_dir)
        self.journal = Journal(os.path.join(self.state_dir, "journal.jsonl"))
        self.store = Store(os.path.join(self.state_dir, "md5cache.json"))
        self.scanner = Scanner(self.config, self.store)
        self.started = time_mod.time()
        self.stop_flag = threading.Event()
        self.wake = threading.Event()
        self.lockfile = None
        self.last_loop = 0.0
        self.scan_lock = threading.Lock()

    # -- single instance -----------------------------------------------------

    def acquire_lock(self):
        """One instance per state dir - POSIX (flock) and Windows (msvcrt).

        Two instances would interleave journal hash chains and fight over the
        same CSV; the chain would detect it, this prevents it.
        """
        path = os.path.join(self.state_dir, "lock")
        self.lockfile = open(path, "a+")
        if fcntl is not None:
            try:
                fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                print("Another md5check_live instance is already running (lock held). Exiting.")
                sys.exit(1)
        elif msvcrt is not None:
            try:
                self.lockfile.seek(0)
                msvcrt.locking(self.lockfile.fileno(), msvcrt.LK_NBLCK, 1)
            except (IOError, OSError):
                print("Another md5check_live instance is already running (lock held). Exiting.")
                sys.exit(1)

    # -- output --------------------------------------------------------------

    def csv_path(self):
        name = str(self.config.get("csv_name") or "md5check.csv")
        return os.path.join(str(self.config.get("output_dir") or "."), name)

    def emit_csv(self):
        """Write the CSV atomically. Returns (path, rows, md5) or ('', 0, '')."""
        rows = self.store.snapshot()
        table = [[r["seq"], r["linename"], r["subline"],
                  "" if r["fsp"] is None else r["fsp"],
                  "" if r["lsp"] is None else r["lsp"],
                  r["p1_final"], r["nav_md5"], r["obp_md5"], r["xcheck"]]
                 for r in rows]
        data = csv_bytes(CSV_COLUMNS, table)
        digest = hashlib.md5(data).hexdigest()
        path = self.csv_path()
        if (digest == self.store.csv_md5 and path == self.store.csv_path_written
                and os.path.exists(path)):
            return path, len(table), digest     # same content, same file: leave it
        try:
            atomic_write(path, data)
        except (IOError, OSError) as exc:
            log.error("Cannot write CSV %s: %s", path, exc)
            with self.store.lock:
                self.store.last_error = "CSV write failed: %s" % exc
            return "", 0, ""
        self.store.csv_md5 = digest
        self.store.csv_rows = len(table)
        self.store.csv_path_written = path
        log.info("CSV written: %s (%d rows)", path, len(table))
        return path, len(table), digest

    # -- worker --------------------------------------------------------------

    def scan_once(self):
        """One guarded scan + emit. Safe to call from the loop or an endpoint."""
        with self.scan_lock:
            started = time_mod.time()
            try:
                rows = self.scanner.scan()
            except Exception as exc:                # a bad file must not kill the loop
                log.exception("Scan failed: %s", exc)
                with self.store.lock:
                    self.store.last_error = "scan failed: %s" % exc
                return False
            self.last_loop = time_mod.time() - started

            # A vanished mount, an unmounted share or a permissions change
            # makes both directories list as empty. Emitting then would replace
            # a good delivered CSV with a header-only one - the single most
            # destructive thing this tool could do. Refuse, and say so.
            with self.store.lock:
                listing_error = self.store.listing_error
            if not rows and (listing_error or self.store.csv_rows):
                msg = ("source directories produced no files (%s) - the "
                       "existing CSV was NOT overwritten"
                       % (listing_error or "both directories are empty"))
                log.error("%s", msg)
                with self.store.lock:
                    self.store.last_error = msg
                return False
            try:
                self.emit_csv()
            except Exception as exc:            # an odd filename must not kill the loop
                log.exception("CSV emit failed: %s", exc)
                with self.store.lock:
                    self.store.last_error = "CSV emit failed: %s" % exc
                return False
            return True

    def monitor_loop(self):
        heartbeat = os.path.join(self.state_dir, "heartbeat")
        while not self.stop_flag.is_set():
            interval = self.interval_seconds()
            if self.config.get("running"):
                try:
                    self.scan_once()
                except Exception as exc:
                    # scan_once guards its own internals; this is the last
                    # resort. The monitor thread must outlive every input.
                    log.exception("Monitor tick failed: %s", exc)
                sd_notify("WATCHDOG=1")
            else:
                # A deliberately stopped service is still healthy, so the
                # heartbeat keeps ticking - otherwise the cron watchdog would
                # "revive" a service the operator stopped on purpose. Poll
                # fast enough that Start feels immediate.
                interval = min(interval, 2.0)
            try:
                with open(heartbeat, "w") as f:
                    f.write(str(int(time_mod.time())))
            except (IOError, OSError):
                pass
            self.wake.wait(interval)
            self.wake.clear()

    def interval_seconds(self):
        try:
            value = float(self.config.get("check_interval_seconds"))
        except (TypeError, ValueError):
            value = 60.0
        return max(5.0, min(value, 86400.0))

    # -- health --------------------------------------------------------------

    def health(self):
        with self.store.lock:
            rows = list(self.store.rows)
            last_scan = self.store.last_scan
            last_secs = self.store.last_scan_secs
            hashed = self.store.last_scan_hashed
            scans = self.store.scan_count
            last_error = self.store.last_error
        attention = [r["seq"] for r in rows if r["attention"]]
        matching = sum(1 for r in rows if r["xcheck"] == XCHECK_MATCH)
        return {
            "app": "md5check_live", "version": APP_VERSION, "mode": "live",
            "running": bool(self.config.get("running")),
            "uptime_s": int(time_mod.time() - self.started),
            "last_loop_ms": int(self.last_loop * 1000),
            "last_scan": iso(last_scan) if last_scan else None,
            "last_scan_secs": round(last_secs, 3),
            "last_scan_hashed": hashed,
            "scans": scans,
            "sequences": len(rows),
            "matching": matching,
            "attention": attention,
            "check_interval_seconds": self.interval_seconds(),
            "nav_p1_dir": self.config.get("nav_p1_dir"),
            "obp_p1_dir": self.config.get("obp_p1_dir"),
            "output_dir": self.config.get("output_dir"),
            "csv_path": self.csv_path(),
            "csv_rows": self.store.csv_rows,
            "cached_files": len(self.store.cache),
            "journal_entries": self.journal.count(),
            "journal_path": self.journal.path,
            "error": last_error,
        }


# ------------------------------------------------------------------ handler --

class Handler(BaseHTTPRequestHandler):
    svc = None
    protocol_version = "HTTP/1.1"
    server_version = "md5check_live/" + APP_VERSION

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.client_address[0], fmt % args)

    # -- plumbing ------------------------------------------------------------

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (IOError, OSError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _body(self):
        """Parse the JSON request body, or {}.

        Every path that does NOT consume the announced body closes the
        connection: leaving unread bytes in the stream would make the next
        keep-alive request start mid-body, and the server would parse the
        leftovers as a fresh request line.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            self.close_connection = True
            return {}
        if length <= 0 or length > 1024 * 1024:
            if length > 0:
                self.close_connection = True
            return {}
        try:
            raw = self.rfile.read(length)
        except (IOError, OSError):
            self.close_connection = True
            return {}
        if len(raw) != length:
            self.close_connection = True
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- GET -----------------------------------------------------------------

    def do_GET(self):
        svc = self.svc
        url = urlparse(self.path)
        q = parse_qs(url.query)
        path = url.path

        if path in ("/", "/index.html", "/md5check_live.html"):
            page = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "md5check_live.html")
            if os.path.exists(page):
                with open(page, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            else:
                self._send(200, "<h1>md5check_live %s</h1>"
                                "<p>md5check_live.html not found next to the script.</p>"
                           % APP_VERSION, "text/html; charset=utf-8")
        elif path == "/api/health":
            self._json(svc.health())
        elif path == "/api/rows":
            rows = svc.store.snapshot()
            self._json({"rows": rows, "count": len(rows),
                        "csv": os.path.basename(svc.csv_path())})
        elif path == "/api/config":
            self._json({"nav_p1_dir": svc.config.get("nav_p1_dir"),
                        "obp_p1_dir": svc.config.get("obp_p1_dir"),
                        "output_dir": svc.config.get("output_dir"),
                        "csv_name": svc.config.get("csv_name"),
                        "check_interval_seconds": svc.interval_seconds(),
                        "sequence_ranges": svc.config.get("sequence_ranges"),
                        "journal_dir": os.path.dirname(svc.journal.path),
                        "port": svc.config.get("port")})
        elif path == "/api/browse":
            p = unquote(q.get("path", ["/"])[0]) or "/"
            roots = browse_roots(svc.config)
            if not within_roots(p, roots):
                self._json({"path": roots[0], "parent": roots[0],
                            "dirs": [], "roots": roots,
                            "error": "Outside the permitted folders."}, 200)
                return
            try:
                entries = sorted(e for e in os.listdir(p)
                                 if os.path.isdir(os.path.join(p, e)))
                parent = os.path.dirname(p.rstrip("/\\")) or p
                if not within_roots(parent, roots):
                    parent = p
                self._json({"path": p, "parent": parent,
                            "dirs": entries[:400], "roots": roots})
            except (OSError, ValueError, TypeError, UnicodeError) as exc:
                # A NUL byte or an undecodable path raises ValueError, not
                # OSError, and an escaping exception kills the request thread.
                log.debug("browse %r failed: %s", p, exc)
                self._json({"path": p, "roots": roots,
                            "error": "Cannot list this folder."}, 200)
        elif path == "/api/csv":
            fp = svc.csv_path()
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition",
                                 'attachment; filename="%s"' % os.path.basename(fp))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"error": "CSV not written yet"}, 404)
        else:
            self._json({"error": "not found"}, 404)

    # -- POST ----------------------------------------------------------------

    def do_POST(self):
        svc = self.svc
        path = urlparse(self.path).path
        # The console always sends application/json. Requiring it means a form
        # POST from another page in the operator's browser cannot reach these
        # endpoints, which is the whole of the cross-site risk on a vessel LAN.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._body()
            self._json({"error": "Content-Type must be application/json"}, 415)
            return
        body = self._body()
        ip = self.client_address[0]

        if path == "/api/config":
            self._post_config(svc, body, ip)
        elif path == "/api/control":
            self._post_control(svc, body, ip)
        elif path == "/api/rescan":
            if not svc.config.get("running"):
                self._json({"error": "Monitoring is stopped - press Start first."}, 409)
                return
            svc.wake.set()
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)

    def _post_config(self, svc, body, ip):
        """Setup save. Every path is validated on the server before it sticks."""
        nav = str(body.get("nav_p1_dir", "")).strip()
        obp = str(body.get("obp_p1_dir", "")).strip()
        out = str(body.get("output_dir", "")).strip()
        errs = []

        if not nav:
            errs.append("Nav P1 directory is required")
        elif not os.path.isdir(nav):
            errs.append("Nav P1 directory does not exist: %s" % nav)
        if not obp:
            errs.append("OBP P1 directory is required")
        elif not os.path.isdir(obp):
            errs.append("OBP P1 directory does not exist: %s" % obp)
        if not out:
            errs.append("Output CSV directory is required")
        elif not os.path.isdir(out):
            try:
                os.makedirs(out)
            except OSError as exc:
                errs.append("Cannot create output directory: %s" % exc)
        if not errs:
            probe = os.path.join(out, ".md5check_write_test")
            try:
                with open(probe, "w") as f:
                    f.write("ok")
                os.remove(probe)
            except OSError as exc:
                errs.append("Output directory not writable: %s" % exc)

        interval = body.get("check_interval_seconds",
                            svc.config.get("check_interval_seconds"))
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            errs.append("Check interval must be a number")
            interval = None
        if interval is not None and not (5 <= interval <= 86400):
            errs.append("Check interval must be between 5 and 86400 seconds")

        ranges = str(body.get("sequence_ranges",
                              svc.config.get("sequence_ranges") or "")).strip()
        bad = sequence_range_problems(ranges)
        if bad:
            # Reject the WHOLE string when any segment is unusable. Accepting
            # "3001-3500, 4005 4006" and silently dropping the malformed half
            # would quietly narrow the job's scope.
            errs.append("Sequence ranges not understood: %s" % "; ".join(bad))

        if errs:
            self._json({"error": " / ".join(errs)}, 400)
            return

        changed_inputs = (nav != svc.config.get("nav_p1_dir") or
                          obp != svc.config.get("obp_p1_dir"))
        svc.config.update({"nav_p1_dir": nav, "obp_p1_dir": obp,
                           "output_dir": out,
                           "check_interval_seconds": interval,
                           "sequence_ranges": ranges})
        n = svc.journal.append({"kind": "config", "ip": ip, "nav_p1_dir": nav,
                                "obp_p1_dir": obp, "output_dir": out,
                                "check_interval_seconds": interval,
                                "sequence_ranges": ranges})
        if changed_inputs:
            # The cache is keyed by absolute path, so it stays valid for any
            # file still in place; only the CSV fingerprint has to be dropped
            # so the next scan definitely rewrites the output.
            svc.store.csv_md5 = ""
            log.info("Input directories changed by %s - next scan is a full pass", ip)
        svc.wake.set()
        log.info("Setup saved by %s (journal #%d)", ip, n)
        self._json({"ok": True, "journal": n, "rescan": changed_inputs})

    def _post_control(self, svc, body, ip):
        action = body.get("action")
        if action not in ("start", "stop"):
            self._json({"error": "action must be start or stop"}, 400)
            return
        if action == "stop":
            expected = str(svc.config.get("control_password") or "")
            if expected and str(body.get("password", "")) != expected:
                log.warning("Control: stop REFUSED for %s (wrong password)", ip)
                self._json({"error": "Wrong password - monitoring keeps running."}, 403)
                return
        if action == "start":
            missing = [label for label, key in
                       (("Nav P1", "nav_p1_dir"), ("OBP P1", "obp_p1_dir"))
                       if not os.path.isdir(str(svc.config.get(key) or ""))]
            if missing:
                self._json({"error": "%s directory does not exist - open Setup first."
                            % " and ".join(missing)}, 400)
                return
        svc.config.update({"running": action == "start"})
        n = svc.journal.append({"kind": "control", "action": action, "ip": ip})
        log.info("Control: %s by %s (journal #%d)", action, ip, n)
        if action == "start":
            svc.wake.set()
        self._json({"ok": True, "running": action == "start", "journal": n})


class ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64


# --------------------------------------------------------------------- main --

def setup_logging(state_dir, verbose):
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    logdir = os.path.join(state_dir, "logs")
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(logdir, "md5check_live.log"), maxBytes=5 * 1024 * 1024, backupCount=5)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description="P1 MD5SUM cross-check service + web console")
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "validate", "rebuild", "verify"],
                    help="run (default) | validate config | rebuild: one scan + CSV "
                         "then exit | verify: journal chain + CSV vs a fresh scan")
    ap.add_argument("--config", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"))
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=APP_VERSION)
    args = ap.parse_args(argv)

    svc = Service(args.config)
    setup_logging(svc.state_dir, args.verbose)

    if args.command == "validate":
        ok = True
        for label, key in (("nav_p1_dir", "nav_p1_dir"), ("obp_p1_dir", "obp_p1_dir")):
            p = str(svc.config.get(key))
            exists = os.path.isdir(p)
            print("%-24s %s  [%s]" % (label, p, "OK" if exists else "MISSING"))
            ok = ok and exists
        out = str(svc.config.get("output_dir"))
        print("%-24s %s  [%s]" % ("output_dir", out,
                                  "OK" if os.path.isdir(out) else "will be created"))
        print("%-24s %s" % ("csv", svc.csv_path()))
        print("%-24s %s s" % ("check_interval_seconds", svc.interval_seconds()))
        print("%-24s %s" % ("port", svc.config.get("port")))
        print("%-24s %s" % ("sequence_ranges",
                            svc.config.get("sequence_ranges") or "(auto-detect)"))
        print("%-24s %s" % ("running", svc.config.get("running")))
        print("Config %s" % ("is valid" if ok else "has problems"))
        return 0 if ok else 1

    if args.command == "verify":
        # Deliberately does NOT take the single-instance lock and never
        # persists the cache: verify exists to audit a DELIVERED CSV, so it
        # has to be runnable while the service is up.
        chain_ok, entries, bad = svc.journal.verify()
        print("JOURNAL: %d entries, chain %s%s"
              % (entries, "OK" if chain_ok else "BROKEN",
                 "" if chain_ok else " at line %s" % bad))
        svc.store.read_only = True
        svc.scanner.scan()
        rows = svc.store.snapshot()
        table = [[r["seq"], r["linename"], r["subline"],
                  "" if r["fsp"] is None else r["fsp"],
                  "" if r["lsp"] is None else r["lsp"],
                  r["p1_final"], r["nav_md5"], r["obp_md5"], r["xcheck"]]
                 for r in rows]
        fresh = csv_bytes(CSV_COLUMNS, table)
        path = svc.csv_path()
        if not os.path.exists(path):
            print("CSV: %s does not exist yet." % path)
            return 1
        with open(path, "rb") as f:
            on_disk = f.read()
        same = (hashlib.md5(fresh).hexdigest() == hashlib.md5(on_disk).hexdigest())
        print("CSV: %s (%d rows) %s a fresh scan"
              % (path, len(table), "matches" if same else "DIFFERS from"))
        if not same:
            print("NOTE: a difference is expected if files changed since the last emit;")
            print("      re-run while the directories are quiet before treating it as real.")
        return 0 if (chain_ok and same) else 1

    svc.acquire_lock()

    if args.command == "rebuild":
        print("Scanning %s and %s ..." % (svc.config.get("nav_p1_dir"),
                                          svc.config.get("obp_p1_dir")))
        svc.scanner.scan()
        path, n, _ = svc.emit_csv()
        print("Done: %d sequence(s) -> %s" % (n, path or "(not written)"))
        return 0

    t = threading.Thread(target=svc.monitor_loop, name="monitor")
    t.daemon = True
    t.start()

    Handler.svc = svc
    addr = (str(svc.config.get("bind")), int(svc.config.get("port")))
    httpd = ThreadedServer(addr, Handler)
    log.info("md5check_live %s serving on http://%s:%d/  (config: %s)",
             APP_VERSION, addr[0], addr[1], args.config)
    log.info("Monitoring is %s", "RUNNING" if svc.config.get("running") else "STOPPED")
    sd_notify("READY=1")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down")
        svc.stop_flag.set()
        svc.wake.set()
        svc.store.save_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
