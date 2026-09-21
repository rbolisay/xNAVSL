#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
"""
CCSQC - vessel records vs TRINAV CCS configuration check.

Two checks against one CCS printout (HTML/XML "CCS Report"):

  Streamer Order   the as-deployed streamer arrangement recorded in an Excel
                   workbook, one tab per streamer, top to bottom = head to
                   tail, against the equipment TRINAV holds.
  NFH Positions    near field hydrophone offsets from the offsets workbook
                   against the offsets TRINAV holds, matched on connector,
                   sub array and position.

Three independent checks per streamer:

  1. Counts   - equipment type totals from the CCS "Streamer Summary" table
                against the tally of the sheet.
  2. Order    - the sequence of individually positioned devices (Q-Fins, ITXs)
                read off the CCS offsets, against the sheet order, plus Q-Fin
                serial numbers.
  3. Offsets  - section lengths are solved from the CCS offsets themselves
                (least squares over every streamer at once), then each device
                offset is predicted from the sheet order. A section that is
                missing, extra or out of place puts a large residual on every
                device behind it.

Nothing about the survey is hard coded: streamer count, streamer numbering,
vessel prefix, section lengths and equipment types are all read from the files.

Python 2.7 + Tkinter standard library only - no third party modules.
Embeds in xNAVSL via xnavsl_embed(master); also runs standalone.

Ai assisted Code by RBolisay
"""

import os
import re
import sys
import csv
import json
import glob
import time
import zipfile
import xml.etree.ElementTree as ET

import Tkinter as tk
import ttk
import tkFileDialog
import tkMessageBox
import tkSimpleDialog


# --- NavSL Blue Aura palette (matches xNAVSL.py) ---------------------------
BG = "#aec6dd"
BTN = "#9cb6cf"
BTN_ACTIVE = "#8cabc2"
TEXT = "#000000"
HEADER_TEXT = "#000033"
PANEL = "#f5f8fc"

ROW_OK = "#e4f1e4"
ROW_WARN = "#fff4c2"
ROW_BAD = "#f8cdc8"
ROW_SKIP = "#e8edf3"
FG_MUTED = "#5a6570"

APP_TITLE = "CCSQC"
STATE_FILE = os.path.join(os.path.expanduser("~"), ".ccsqc_p27.json")
# Settings written before the rename, read once so saved paths survive it.
LEGACY_STATE_FILE = os.path.join(os.path.expanduser("~"),
                                 ".xstreamerqc_p27.json")

DEFAULT_TOLERANCE = 0.05  # metres; offset residual allowed before flagging


# ===========================================================================
# Small helpers
# ===========================================================================

_ENTITY = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " "}


def unescape(text):
    """Decode HTML entities. The CCS writer emits '&#x2713' with no semicolon."""
    if not text:
        return u""

    def sub(m):
        body = m.group(1)
        if body.startswith("#"):
            try:
                if body[1:2] in ("x", "X"):
                    return unichr(int(body[2:], 16))
                return unichr(int(body[1:]))
            except (ValueError, OverflowError):
                return m.group(0)
        return _ENTITY.get(body.lower(), m.group(0))

    return re.sub(r"&(#[xX]?[0-9a-fA-F]+|[a-zA-Z]+);?", sub, text)


def strip_tags(chunk):
    """Visible text of an HTML fragment, whitespace collapsed."""
    txt = re.sub(r"<[^>]*>", " ", chunk or "")
    return re.sub(r"\s+", " ", unescape(txt)).strip()


def to_text(value):
    """Anything -> unicode, never raising on odd encodings."""
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    if isinstance(value, str):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", "replace")
    return unicode(value)


def norm_key(text):
    """Lowercase, alphanumeric only - for matching header and type labels."""
    return re.sub(r"[^a-z0-9]+", "", to_text(text).lower())


def norm_serial(text):
    """Serials are compared without case, padding, spaces or leading zeros."""
    s = re.sub(r"[\s_]+", "", to_text(text).upper())
    s = s.lstrip("0")
    return s


def to_float(text):
    try:
        return float(to_text(text).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def fmt(value, places=3):
    if value is None:
        return u"-"
    return (u"%%.%df" % places) % value


# ===========================================================================
# XLSX reader (zipfile + ElementTree; no openpyxl on the deployment box)
# ===========================================================================

class XlsxError(Exception):
    pass


def _localname(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _cell_text(cell, shared):
    """Value of one <c> element as text, covering every common cell type."""
    ctype = cell.get("t")
    if ctype == "inlineStr":
        parts = [n.text or u"" for n in cell.iter() if _localname(n.tag) == "t"]
        return u"".join(parts)
    value = None
    for child in cell:
        name = _localname(child.tag)
        if name == "v":
            value = child.text
            break
        if name == "is":
            parts = [n.text or u"" for n in child.iter() if _localname(n.tag) == "t"]
            return u"".join(parts)
    if value is None:
        return u""
    if ctype == "s":
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return u""
    if ctype == "b":
        return u"TRUE" if value.strip() == "1" else u"FALSE"
    return to_text(value)


def read_xlsx(path):
    """
    Read an .xlsx / .xlsm workbook.

    Returns [(sheet_name, {row_number: {column_letter: text}}), ...] in the
    order the sheets appear in the workbook.
    """
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipfile, IOError) as exc:
        raise XlsxError("cannot open workbook: %s" % exc)

    try:
        names = zf.namelist()

        shared = []
        for candidate in ("xl/sharedStrings.xml", "xl/SharedStrings.xml"):
            if candidate in names:
                root = ET.fromstring(zf.read(candidate))
                for si in root:
                    if _localname(si.tag) != "si":
                        continue
                    parts = [n.text or u"" for n in si.iter()
                             if _localname(n.tag) == "t"]
                    shared.append(u"".join(parts))
                break

        wb_path = None
        for candidate in ("xl/workbook.xml", "xl/Workbook.xml"):
            if candidate in names:
                wb_path = candidate
                break
        if wb_path is None:
            raise XlsxError("no xl/workbook.xml - not an xlsx workbook")

        rel_path = wb_path.rsplit("/", 1)[0] + "/_rels/" + wb_path.rsplit("/", 1)[1] + ".rels"
        rels = {}
        if rel_path in names:
            for rel in ET.fromstring(zf.read(rel_path)):
                rid = rel.get("Id")
                target = rel.get("Target") or ""
                if not rid or not target:
                    continue
                if target.startswith("/"):
                    target = target[1:]
                elif not target.startswith("xl/"):
                    target = "xl/" + target
                rels[rid] = target.replace("/./", "/")

        sheets = []
        wb_root = ET.fromstring(zf.read(wb_path))
        for node in wb_root.iter():
            if _localname(node.tag) != "sheet":
                continue
            name = node.get("name") or ""
            rid = None
            for attr, value in node.attrib.items():
                if _localname(attr) == "id":
                    rid = value
                    break
            target = rels.get(rid)
            if target is None or target not in names:
                # Fall back to positional worksheet naming.
                guess = "xl/worksheets/sheet%d.xml" % (len(sheets) + 1)
                target = guess if guess in names else None
            if target is None:
                continue
            sheets.append((name, target))

        out = []
        for name, target in sheets:
            rows = {}
            try:
                sheet_root = ET.fromstring(zf.read(target))
            except (KeyError, ET.ParseError):
                out.append((name, rows))
                continue
            for cell in sheet_root.iter():
                if _localname(cell.tag) != "c":
                    continue
                ref = cell.get("r") or ""
                m = re.match(r"([A-Za-z]+)(\d+)$", ref)
                if not m:
                    continue
                text = _cell_text(cell, shared)
                if text is None or text == u"":
                    continue
                rows.setdefault(int(m.group(2)), {})[m.group(1).upper()] = text.strip()
            out.append((name, rows))
        return out
    finally:
        try:
            zf.close()
        except Exception:
            pass


# ===========================================================================
# CCS report reader (HTML / XML printout)
# ===========================================================================

class CcsError(Exception):
    pass


class CcsReport(object):
    """
    Parses the tables out of a TRINAV CCS printout.

    Tables are located by their visible heading (class="tableName"), never by
    file offset, so section order and report length do not matter.
    """

    def __init__(self, path):
        self.path = path
        raw = open(path, "rb").read()
        self.text = to_text(raw)
        self.tables = self._split_tables()
        self.summary, self.summary_streamers = self._read_summary()
        self.devices = self._read_devices()
        self.nfh = self._read_nfh()

    # -- structure ---------------------------------------------------------

    def _split_tables(self):
        """{heading: [rows of cells]} for every labelled table in the report."""
        # Tolerant of double quoted, single quoted and unquoted attributes, and
        # of a class list carrying more than one name - writers differ on all
        # three, and a missed heading loses the whole table.
        pattern = (r'<t[dh]\b[^>]*\bclass\s*=\s*'
                   r'["\']?[^>"\']*tableName[^>"\']*["\']?[^>]*>(.*?)</t[dh]>')
        marks = []
        for m in re.finditer(pattern, self.text, re.S | re.I):
            marks.append((m.start(), m.end(), strip_tags(m.group(1))))
        if not marks:
            raise CcsError("no CCS tables found - is this a CCS Report printout?")

        tables = {}
        for i, (start, end, label) in enumerate(marks):
            stop = marks[i + 1][0] if i + 1 < len(marks) else len(self.text)
            rows = self._rows(self.text[end:stop])
            if label in tables:
                tables[label].extend(rows)
            else:
                tables[label] = rows
        return tables

    @staticmethod
    def _rows(chunk):
        out = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", chunk, re.S | re.I):
            cells = [strip_tags(c) for c in
                     re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
            if cells:
                out.append(cells)
        return out

    def table(self, *labels):
        """First table whose heading matches any of the given names."""
        wanted = [norm_key(l) for l in labels]
        for label, rows in self.tables.items():
            if norm_key(label) in wanted:
                return rows
        return []

    # -- streamer summary --------------------------------------------------

    def _read_summary(self):
        """
        {equipment type: {streamer number: count}} from "Streamer Summary".

        Column positions are taken from the header text, so the report may list
        streamers in any order and any quantity.
        """
        rows = self.table("Streamer Summary")
        if not rows:
            return {}, []

        header = None
        for row in rows[:6]:
            if any(norm_key(c).startswith("equipmenttype") for c in row):
                header = row
                break
        if header is None:
            return {}, []

        columns = []          # (cell index, streamer number)
        for idx, cell in enumerate(header):
            m = re.search(r"streamer\s*0*(\d+)", to_text(cell), re.I)
            if m:
                columns.append((idx, int(m.group(1))))
        if not columns:
            return {}, []

        numbers = sorted(set(n for _, n in columns))
        summary = {}
        width = len(header)
        for row in rows:
            if row is header or not row:
                continue
            label = to_text(row[0]).strip()
            if not label or norm_key(label).startswith("equipmenttype"):
                continue
            # Count rows carry one value per streamer plus a total.
            if len(row) < width:
                continue
            per = {}
            usable = True
            for idx, number in columns:
                if idx >= len(row):
                    usable = False
                    break
                value = to_text(row[idx]).strip()
                if not re.match(r"^-?\d+$", value):
                    usable = False
                    break
                per[number] = int(value)
            if usable and per:
                summary[label] = per
        return summary, numbers

    # -- positioned devices ------------------------------------------------

    @staticmethod
    def parse_device_name(name):
        """
        'AWA.S01.YP-01.QF-01' -> (1, 'QF', 1, ('YP-01',))

        Vessel prefix is optional, the streamer field may be any width, and any
        number of intermediate nodes (a Y-piece leg, for instance) is allowed.
        Returns None when the name is not a streamer device.
        """
        parts = to_text(name).split(".")
        streamer = None
        start = None
        for i, part in enumerate(parts):
            m = re.match(r"^S0*(\d+)$", part, re.I)
            if m:
                streamer = int(m.group(1))
                start = i
                break
        if streamer is None or start is None or start + 1 >= len(parts):
            return None
        tail = parts[start + 1:]
        m = re.match(r"^([A-Za-z]+)-0*(\d+)$", tail[-1])
        if not m:
            return None
        kind = m.group(1).upper()
        index = int(m.group(2))
        return streamer, kind, index, tuple(tail[:-1])

    def _read_devices(self):
        """{streamer number: [device dicts sorted head to tail]}"""
        devices = {}

        def add(rows, default_kind):
            if not rows:
                return
            header = None
            for row in rows[:5]:
                keys = [norm_key(c) for c in row]
                if "name" in keys and any(k.startswith("along") for k in keys):
                    header = keys
                    break
            if header is None:
                return

            def col(*wanted):
                for want in wanted:
                    for idx, key in enumerate(header):
                        if key == want or key.startswith(want):
                            return idx
                return None

            i_name = col("name")
            i_along = col("along")
            i_above = col("above")
            i_serial = col("serialnumber", "serial")
            i_active = col("active")
            i_wing = col("wingtype")

            for row in rows:
                if not row or len(row) <= i_name:
                    continue
                parsed = self.parse_device_name(row[i_name])
                if parsed is None:
                    continue
                number, kind, index, chain = parsed
                along = to_float(row[i_along]) if i_along is not None and i_along < len(row) else None
                if along is None:
                    continue
                above = to_float(row[i_above]) if i_above is not None and i_above < len(row) else None
                serial = row[i_serial] if i_serial is not None and i_serial < len(row) else u""
                active = None
                if i_active is not None and i_active < len(row):
                    active = bool(to_text(row[i_active]).strip())
                wing = row[i_wing] if i_wing is not None and i_wing < len(row) else u""
                devices.setdefault(number, []).append({
                    "name": to_text(row[i_name]),
                    "short": to_text(row[i_name]).split(".", 1)[-1]
                             if to_text(row[i_name]).count(".") > 1 else to_text(row[i_name]),
                    "kind": kind or default_kind,
                    "index": index,
                    "chain": chain,
                    "branch": bool(chain),
                    "along": along,
                    "above": above if above is not None else 0.0,
                    "serial": serial,
                    "active": active,
                    "wing": wing,
                })

        add(self.table("Q-Fins", "QFins", "Q Fins"), "QF")
        add(self.table("ITXs", "ITX"), "ITX")
        add(self.table("Buoys", "Buoy"), "BUOY")
        add(self.table("PP Paravanes", "Paravanes"), "PP")

        for number in devices:
            devices[number].sort(key=lambda d: (-d["along"], d["kind"], d["index"]))
        self.has_buoys = any(d["kind"] in ("FF", "TB", "BUOY")
                             for row in devices.values() for d in row)
        return devices

    def streamer_numbers(self):
        numbers = set(self.devices.keys()) | set(self.summary_streamers)
        return sorted(numbers)

    # -- near field hydrophones --------------------------------------------

    @staticmethod
    def parse_nfh_name(name):
        """
        'AWA.G01.GS01.UB01.Near Field Hydrophone' -> (1, 1, 1)
              array ----^     ^-- sub array  ^-- position

        Reads the gun-string and gun-bundle nodes by their prefix where the
        usual GS / UB names are used, and falls back on position in the chain
        otherwise, so a differently named hierarchy still resolves.
        """
        tokens = []
        for part in to_text(name).split("."):
            t = re.match(r"^([A-Za-z]+)0*(\d+)$", part.strip())
            if t:
                tokens.append((t.group(1).upper(), int(t.group(2))))
        if not tokens:
            return None
        byprefix = {}
        for prefix, value in tokens:
            byprefix.setdefault(prefix, value)
        array = byprefix.get("G")
        sub = byprefix.get("GS")
        pos = byprefix.get("UB")
        if sub is None or pos is None:
            # Unknown naming: the last numbered node is the position and the
            # one before it the sub array.
            if len(tokens) < 2:
                return None
            sub = tokens[-2][1] if sub is None else sub
            pos = tokens[-1][1] if pos is None else pos
        return array, sub, pos

    def _read_nfh(self):
        """Near field hydrophones with their offsets, keyed by connector."""
        rows = self.table("Near Field Hydrophones", "Near Field Hydrophone",
                          "NFHs", "NFH")
        if not rows:
            return []
        header = None
        for row in rows[:5]:
            keys = [norm_key(c) for c in row]
            if "name" in keys and any("across" in k for k in keys):
                header = keys
                break
        if header is None:
            return []

        def col(*wanted):
            for want in wanted:
                for i, key in enumerate(header):
                    if want in key:
                        return i
            return None

        i_name = col("name")
        i_across = col("offsetacross", "across")
        i_along = col("offsetalong", "along")
        i_above = col("offsetabove", "above")
        i_active = col("active")
        i_conn = col("nfhconnector", "connector")

        out = []
        for row in rows:
            if not row or i_name is None or len(row) <= i_name:
                continue
            parsed = self.parse_nfh_name(row[i_name])
            if parsed is None:
                continue
            array, sub, pos = parsed

            def raw(i):
                return to_text(row[i]).strip() if (i is not None and i < len(row)) else u""

            conn = None
            if i_conn is not None and i_conn < len(row):
                digits = re.search(r"\d+", to_text(row[i_conn]))
                if digits:
                    conn = int(digits.group(0))
            out.append({
                "name": to_text(row[i_name]).strip(),
                "array": array, "sub": sub, "pos": pos, "connector": conn,
                "across": to_float(raw(i_across)), "across_raw": raw(i_across),
                "along": to_float(raw(i_along)), "along_raw": raw(i_along),
                "above": to_float(raw(i_above)), "above_raw": raw(i_above),
                "active": bool(raw(i_active)) if i_active is not None else None,
            })
        return out


# ===========================================================================
# Equipment families - how a sheet code maps onto a CCS equipment type
# ===========================================================================

# Fixed sheet codes.  Codes shaped like a letter plus a length (S25, O50, T75)
# are handled generically by classify_code() so other surveys work unchanged.
CODE_NAMES = {
    "DCK": "Deck cable",
    "SRU": "Slip ring",
    "SRA": "Slip ring adapter",
    "SOL": "Lead-in",
    "COL": "Lead-in",
    "LOL": "Lead-in",
    "LIN": "Lead-in",
    "MWA": "Monowing adapter",
    "MIA": "Miniwing adapter",
    "TOW": "Tow adapter",
    "FLX": "Flex adapter",
    "YTA": "Y-piece",
    "ICP": "ICP",
    "ITX": "ITX",
    "PITX": "PITX",
    "FIN": "Q-Fin",
    "ACT": "Active section",
    "TBA": "Tailbuoy adapter",
}

LEADIN_CODES = ("SOL", "COL", "LOL", "LIN")
PRE_LEADIN_CODES = ("DCK", "SRU", "SRA")

# Sheet code -> keywords that identify the matching CCS summary row.  Every
# rule is tried against the lowercase CCS type label.
FAMILY_RULES = [
    ("LEADIN", ("leadin", "lead-in", "lead in")),
    ("PITX", ("pitx",)),
    ("ITX", ("itx",)),
    ("ICP", ("icp",)),
    ("FIN", ("q-fin", "qfin")),
    ("ACT", ("active section",)),
    ("FLX", ("flex adapter",)),
    ("MWA", ("mono wing", "monowing")),
    ("MIA", ("mini wing", "miniwing")),
    ("YTA", ("y-piece", "ypiece", "y piece")),
    ("TOW", ("tow adapter",)),
    ("TBA", ("tailbuoy adapter", "tail buoy adapter")),
]

# CCS type labels that are never a sheet line item: survey furniture rather
# than streamer sections, or hardware the sheet does not itemise.
IGNORED_CCS_TYPES = (
    "baseline", "cmgdirectionline", "trinav insea gps", "irma hydrophone",
    "tail buoy", "front float", "streamer gps", "paravane",
)


# Codes whose CCS type depends on a mark number ("Tow Adapter" vs
# "Tow Adapter II 1.4m"). The mark is read from the sheet comment on one side
# and from the CCS type label on the other, so both resolve to TOW-I / TOW-II.
VARIANT_FAMILIES = ("TOW",)
DEFAULT_VARIANT = "I"


def variant_of(text):
    """Mark number in a description: 'Tow Adapter II 1.4m' -> 'II'."""
    for token in re.findall(r"\b([IVX]{1,4}|[1-4])\b", to_text(text).upper()):
        if token in ("1", "2", "3", "4"):
            return {"1": "I", "2": "II", "3": "III", "4": "IV"}[token]
        if token in ("I", "II", "III", "IV", "V"):
            return token
    return None


def classify_code(code):
    """Sheet code -> (family, description). Length coded codes stay generic."""
    code = to_text(code).upper()
    if code in CODE_NAMES:
        family = "LEADIN" if code in LEADIN_CODES else code
        return family, CODE_NAMES[code]
    m = re.match(r"^([A-Z])(\d+)$", code)
    if m:
        letter, length = m.group(1), m.group(2)
        if letter == "S":
            return code, "Stretch %s m" % length
        if letter == "O":
            return code, "Offset %s m" % length
        if letter == "T":
            return code, "Tail stretch %s m" % length
    return code, code


def ccs_type_family(label, aliases):
    """CCS summary row label -> sheet family, or None when it is not equipment."""
    text = to_text(label).strip()
    if text.startswith("-"):
        return None              # '- ITX Active' style breakdown of the row above
    key = norm_key(text)
    if key in aliases:
        return aliases[key]
    low = text.lower()
    for ignore in IGNORED_CCS_TYPES:
        if ignore in low:
            return None
    for family, keywords in FAMILY_RULES:
        for word in keywords:
            if word in low:
                if family in VARIANT_FAMILIES:
                    return "%s-%s" % (family, variant_of(text) or DEFAULT_VARIANT)
                return family
    # 'Front Stretch 25m' / 'Offset Section 50m' / 'Tail Stretch 75m' / 'Spacing'
    m = re.search(r"(\d+)\s*m\b", low)
    if m:
        length = str(int(m.group(1)))
        if "tail" in low and "stretch" in low:
            return "T" + length
        if "stretch" in low:
            return "S" + length
        if "offset" in low or "spacing" in low:
            return "O" + length
    return None


# ===========================================================================
# Streamer sheet reader
# ===========================================================================

class SheetItem(object):
    __slots__ = ("row", "code", "instance", "family", "desc", "serial",
                 "comment", "action", "leg")

    def __init__(self, row, code, instance, family, desc, serial, comment, action):
        self.row = row
        self.code = code
        self.instance = instance
        self.family = family
        self.desc = desc
        self.serial = serial
        self.comment = comment
        self.action = action
        self.leg = "main"

    @property
    def label(self):
        return ("%s %s" % (self.code, self.instance)).strip()


def read_sheets(path):
    """
    Parse a streamer workbook.

    Returns (streamers, problems) where streamers is
    {number: {"sheet":name, "items":[SheetItem, ...]}}.
    """
    book = read_xlsx(path)
    streamers = {}
    problems = []

    for order, (name, rows) in enumerate(book, start=1):
        if not rows:
            continue

        header_row = None
        cols = {}
        for rownum in sorted(rows)[:25]:
            cells = rows[rownum]
            found = {}
            for letter, value in cells.items():
                key = norm_key(value)
                if key == "type":
                    found["type"] = letter
                elif key in ("serialnumber", "serialno", "serial"):
                    found["serial"] = letter
                elif key == "comment":
                    found["comment"] = letter
                elif key == "action":
                    found["action"] = letter
            if "type" in found:
                header_row = rownum
                cols = found
                break
        if header_row is None:
            continue

        items = []
        for rownum in sorted(rows):
            if rownum <= header_row:
                continue
            cells = rows[rownum]
            raw = to_text(cells.get(cols["type"], u"")).strip()
            if not raw:
                continue
            if norm_key(raw) == "type":
                continue
            parts = raw.split()
            code = parts[0].upper()
            instance = parts[1] if len(parts) > 1 else u""
            serial = to_text(cells.get(cols.get("serial"), u"")).strip()
            comment = to_text(cells.get(cols.get("comment"), u"")).strip()
            action = to_text(cells.get(cols.get("action"), u"")).strip()
            # A PITX is written as an ITX whose serial says so.
            if code == "ITX" and norm_key(serial) == "pitx":
                code = "PITX"
            family, desc = classify_code(code)
            if family in VARIANT_FAMILIES:
                mark = variant_of(comment) or DEFAULT_VARIANT
                family = "%s-%s" % (family, mark)
                desc = "%s %s" % (desc, mark)
            items.append(SheetItem(rownum, code, instance, family, desc,
                                   serial, comment, action))
        if not items:
            continue

        number = streamer_number(name, order)
        if number is None:
            problems.append(u"'%s': no streamer number in the tab name - skipped" % name)
            continue
        if number in streamers:
            problems.append(u"'%s': streamer %d already read from '%s' - skipped"
                            % (name, number, streamers[number]["sheet"]))
            continue
        streamers[number] = {"sheet": name, "items": items}

    if not streamers:
        raise XlsxError("no streamer tabs found (need a 'Type' column header)")
    return streamers, problems


def streamer_number(sheet_name, fallback):
    """'Str1 - Reel LIWS' -> 1. Tolerates Streamer 1 / STR-01 / S01 / Cable 1."""
    name = to_text(sheet_name)
    for pattern in (r"(?:streamer|str|stmr|cable|cbl)\s*[-_#]?\s*0*(\d+)",
                    r"\bS\s*0*(\d+)\b"):
        m = re.search(pattern, name, re.I)
        if m:
            return int(m.group(1))
    m = re.search(r"(\d+)", name)
    if m:
        return int(m.group(1))
    return fallback


# ===========================================================================
# NFH position sheet (offsets workbook)
# ===========================================================================

AXES = ("across", "along", "above")


def _group_connector(label, fallback):
    """'NFH 1 - FRONT' -> 1, 'NFH 2 - AFT' -> 2, else FRONT/AFT by name."""
    text = to_text(label)
    m = re.search(r"\b(\d+)\b", text)
    if m:
        return int(m.group(1))
    low = text.lower()
    if "front" in low or "fwd" in low or "forward" in low:
        return 1
    if "aft" in low or "rear" in low or "back" in low:
        return 2
    return fallback


def read_nfh_sheet(path):
    """
    Read an NFH position table out of an offsets workbook.

    Looks for a sheet carrying Across / Along / Above headers repeated in
    side-by-side blocks, one block per NFH connector. Block extent, block
    order, the number of blocks, the number of sub arrays and positions, and
    the presence of a Config column are all read from the sheet rather than
    assumed. Returns (entries, sheet name, notes).
    """
    book = read_xlsx(path)
    best = None
    for name, rows in book:
        parsed = _parse_nfh_sheet(rows)
        if parsed and (best is None or len(parsed[0]) > len(best[0])):
            best = (parsed[0], name, parsed[1])
    if best is None:
        raise XlsxError("no NFH position table found (need Across / Along / "
                        "Above columns under an NFH heading)")
    return best


def _parse_nfh_sheet(rows):
    if not rows:
        return None
    letters = sorted(set(c for r in rows.values() for c in r), key=col_index)

    # The axis row is the one carrying Across/Along/Above; the row above it
    # carries the block names, and the row above that may carry a title.
    axis_row = None
    for rownum in sorted(rows):
        found = set()
        for letter, value in rows[rownum].items():
            k = norm_key(value)
            for axis in AXES:
                if k.startswith(axis):
                    found.add(axis)
        if len(found) == 3:
            axis_row = rownum
            break
    if axis_row is None:
        return None

    # columns of each axis, in sheet order
    axis_cols = []
    for letter in letters:
        value = rows[axis_row].get(letter)
        if not value:
            continue
        k = norm_key(value)
        for axis in AXES:
            if k.startswith(axis):
                axis_cols.append((col_index(letter), letter, axis))
                break
    axis_cols.sort()

    # group them into blocks: a new block starts whenever an axis repeats
    blocks, current, seen = [], [], set()
    for entry in axis_cols:
        if entry[2] in seen:
            blocks.append(current)
            current, seen = [], set()
        current.append(entry)
        seen.add(entry[2])
    if current:
        blocks.append(current)
    blocks = [b for b in blocks if len(b) >= 3]
    if not blocks:
        return None

    label_row = axis_row - 1
    labels = rows.get(label_row, {})

    def block_label(block):
        """Nearest non-empty label at or left of the block's first column."""
        start = block[0][0]
        best, best_col = u"", None
        for letter, value in labels.items():
            c = col_index(letter)
            if c <= start and to_text(value).strip():
                if best_col is None or c > best_col:
                    best, best_col = to_text(value).strip(), c
        return best

    # key columns: look in the label row and the rows above it
    key_sub = key_pos = None
    for rownum in (label_row, label_row - 1, axis_row):
        for letter, value in rows.get(rownum, {}).items():
            k = norm_key(value)
            if key_sub is None and ("subarray" in k or k == "array" or "string" in k):
                key_sub = letter
            if key_pos is None and ("position" in k or k == "pos" or "bundle" in k):
                key_pos = letter
    if key_pos is None:
        return None

    notes = []
    entries, last_sub = [], None
    fallback = 1
    block_info = []
    for i, block in enumerate(blocks):
        label = block_label(block)
        block_info.append((label, _group_connector(label, i + 1)))

    for rownum in sorted(rows):
        if rownum <= axis_row:
            continue
        cells = rows[rownum]
        pos_text = to_text(cells.get(key_pos, u"")).strip()
        sub_text = to_text(cells.get(key_sub, u"")).strip() if key_sub else u""
        if sub_text:
            n = re.search(r"(\d+)", sub_text)
            if n:
                last_sub = int(n.group(1))
        if not pos_text:
            continue
        n = re.search(r"(\d+)", pos_text)
        if not n:
            continue
        pos = int(n.group(1))
        for (label, connector), block in zip(block_info, blocks):
            values = {}
            for _, letter, axis in block:
                values[axis] = to_float(cells.get(letter))
            if all(values.get(a) is None for a in AXES):
                continue
            entries.append({
                "row": rownum, "sub": last_sub, "pos": pos,
                "block": label, "connector": connector,
                "across": values.get("across"), "along": values.get("along"),
                "above": values.get("above"),
            })
    if not entries:
        return None
    if key_sub is None:
        notes.append("no Sub Array column found - matched on position only")
    return entries, notes


def col_index(letter):
    """'A' -> 0, 'Z' -> 25, 'AA' -> 26."""
    value = 0
    for ch in to_text(letter).upper():
        if "A" <= ch <= "Z":
            value = value * 26 + (ord(ch) - 64)
    return value - 1


# ===========================================================================
# Least squares - solve section lengths from the CCS offsets
# ===========================================================================

def solve(matrix, rhs):
    """
    Least squares by normal equations, pure Python.

    Streamer configurations are routinely rank deficient - a monowing adapter
    and a Y-piece always appear together, so their individual lengths cannot be
    separated. Those directions are detected during elimination and pinned to
    zero; the remaining parameters absorb them, which leaves the predicted
    offsets (the only thing used downstream) exact.
    """
    if not matrix or not matrix[0]:
        return []
    n = len(matrix[0])
    ata = [[0.0] * (n + 1) for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            total = 0.0
            for k in range(len(matrix)):
                a = matrix[k][i]
                if a and matrix[k][j]:
                    total += a * matrix[k][j]
            ata[i][j] = total
            ata[j][i] = total
        total = 0.0
        for k in range(len(matrix)):
            if matrix[k][i]:
                total += matrix[k][i] * rhs[k]
        ata[i][n] = total

    scale = max([abs(ata[i][i]) for i in range(n)] or [0.0])
    eps = max(scale * 1e-9, 1e-12)

    pivot_of_column = {}
    row = 0
    for col in range(n):
        if row >= n:
            break
        best = max(range(row, n), key=lambda r: abs(ata[r][col]))
        if abs(ata[best][col]) <= eps:
            continue                       # dependent column - parameter := 0
        ata[row], ata[best] = ata[best], ata[row]
        for r in range(n):
            if r == row or not ata[r][col]:
                continue
            factor = ata[r][col] / ata[row][col]
            for c in range(col, n + 1):
                ata[r][c] -= factor * ata[row][c]
        pivot_of_column[col] = row
        row += 1

    out = [0.0] * n
    for col, r in pivot_of_column.items():
        out[col] = ata[r][n] / ata[r][col]
    return out


# ===========================================================================
# Comparison engine
# ===========================================================================

POSITIONED = ("FIN", "ITX")

# Sheet families that TRINAV positions individually, and the CCS device kind
# they appear as. A PITX is deliberately absent: the CCS counts it in the
# summary but gives it no offset, so it must not claim an ITX device.
DEVICE_KIND = {"FIN": "QF", "ITX": "ITX"}


class Result(object):
    """Everything the GUI shows for one streamer."""

    def __init__(self, number):
        self.number = number
        self.sheet = u""
        self.rows = []            # detail table rows
        self.counts = []          # (family, ccs label, sheet n, ccs n, ok)
        self.notes = []
        self.verdict = "OK"
        self.worst = 0.0
        self.order_ok = True
        self.serials_ok = True
        self.counts_ok = True
        self.fins_checked = 0
        self.fins_ok = 0
        self.n_items = 0
        self.n_devices = 0

    def flag(self, level):
        rank = {"OK": 0, "CHECK": 1, "MISMATCH": 2}
        if rank.get(level, 0) > rank.get(self.verdict, 0):
            self.verdict = level


def split_legs(items):
    """
    Mark the front float leg of a Y-piece.

    A Y-piece splits the streamer: one leg carries the front float (ending at
    its tailbuoy adapter), the other continues into the offsets and the active
    body. Items on the float leg are tagged leg='float'.
    """
    i = 0
    while i < len(items):
        if items[i].family == "YTA":
            end = None
            for j in range(i + 1, min(i + 12, len(items))):
                if items[j].family == "TBA":
                    end = j
                    break
            if end is not None:
                for j in range(i + 1, end + 1):
                    items[j].leg = "float"
                i = end + 1
                continue
        i += 1
    return items


def compare(sheets, ccs, tolerance=DEFAULT_TOLERANCE, start_at_leadin=True,
            aliases=None):
    """Run all three checks over every streamer present in both files."""
    aliases = aliases or {}
    results = {}
    shared = sorted(set(sheets.keys()) & set(ccs.streamer_numbers()))

    prepared = {}
    for number in shared:
        items = split_legs(list(sheets[number]["items"]))
        first = 0
        if start_at_leadin:
            for i, item in enumerate(items):
                if item.family == "LEADIN":
                    first = i
                    break
            else:
                first = 0
                for i, item in enumerate(items):
                    if item.code not in PRE_LEADIN_CODES:
                        first = i
                        break
        prepared[number] = {"skipped": items[:first], "items": items[first:],
                            "sheet": sheets[number]["sheet"]}

    # -- type totals first --------------------------------------------------
    # The count check needs no geometry, so it runs first and tells the length
    # solution which streamers are already known to differ. That matters when
    # two streamers are built alike: if one loses a section the offsets alone
    # cannot say which of the pair is wrong, but the totals can.
    results = {}
    counts_by_family = {}
    for number in shared:
        res = Result(number)
        res.sheet = prepared[number]["sheet"]
        results[number] = res
        counts_by_family[number] = count_check(prepared[number]["items"],
                                               ccs, number, aliases, res)

    # -- solve section lengths from the CCS offsets themselves --------------
    known_bad = set(n for n in shared if not results[n].counts_ok)
    seed = known_bad if len(known_bad) < len(shared) else set()
    lengths, support, per_streamer = fit_sections(prepared, ccs, shared,
                                                  exclude=seed)
    excluded = set(seed)

    # A streamer that really is built differently drags the shared lengths off
    # and would flag the others with it. Drop the worst offender, refit, repeat
    # while it keeps helping, then score every streamer against the clean
    # lengths. Least squares spreads a front-end error across the fleet, so the
    # offenders have to come out one at a time rather than by a single
    # threshold on the contaminated solution.
    floor = max(2, (len(shared) + 1) // 2)
    while len(shared) - len(excluded) > floor:
        inliers = [n for n in shared if n not in excluded]
        offender = max(inliers, key=lambda n: per_streamer.get(n, 0.0))
        before = max(per_streamer.get(n, 0.0) for n in inliers)
        if before <= tolerance:
            break
        trial = excluded | set([offender])
        rest = [n for n in shared if n not in trial]
        if not rest:
            break
        lengths2, support2, per2 = fit_sections(prepared, ccs, shared, exclude=trial)
        if max(per2.get(n, 0.0) for n in rest) >= before:
            break                              # removing it did not help
        excluded, lengths, support, per_streamer = trial, lengths2, support2, per2

    # -- per streamer -------------------------------------------------------
    for number in shared:
        res = results[number]
        data = prepared[number]
        res.n_items = len(data["items"])

        devices = ccs.devices.get(number, [])
        res.n_devices = len([d for d in devices if d["kind"] in ("QF", "ITX")])

        main = [d for d in devices if not d["branch"] and d["kind"] in ("QF", "ITX")]
        main.sort(key=lambda d: -d["along"])
        branch = [d for d in devices if d["branch"] and d["kind"] in ("QF", "ITX")]
        branch.sort(key=lambda d: -d["along"])
        floats = [d for d in devices if d["kind"] == "FF"]
        tails = [d for d in devices if d["kind"] == "TB"]

        families_ok = counts_by_family[number]

        pools = {"main": pool(main), "float": pool(branch)}
        cursors = {"main": {}, "float": {}}
        position = lengths.get("__origin__", 0.0)

        for item in data["skipped"]:
            res.rows.append(row_for(item, None, None, None, "skipped",
                                    "before lead-in"))

        for item in data["items"]:
            kind = DEVICE_KIND.get(item.family)
            dev = None
            if kind:
                bucket = pools[item.leg].get(kind, [])
                used = cursors[item.leg].setdefault(kind, 0)
                if used < len(bucket):
                    dev = bucket[used]
                    cursors[item.leg][kind] = used + 1

            # A tailbuoy adapter is the last link of its leg: on the float leg
            # it carries the front float, on the main line the tailbuoy.
            carried = ""
            if dev is None and item.family == "TBA":
                buoy = None
                if item.leg == "float" and floats:
                    buoy = floats[0]
                elif item.leg == "main" and tails:
                    buoy = tails[-1]
                if buoy is not None:
                    dev = buoy
                    carried = "front float" if buoy["kind"] == "FF" else "tailbuoy"

            status, note = "", ""
            residual = None
            if dev is not None:
                inclined = abs(dev["above"]) > 0.5 or item.leg != "main"
                if item.leg == "main" and not inclined:
                    residual = abs(-dev["along"] - position)
                    res.worst = max(res.worst, residual)
                if dev["kind"] == "QF" and dev["serial"] and item.serial:
                    res.fins_checked += 1
                    if norm_serial(dev["serial"]) == norm_serial(item.serial):
                        res.fins_ok += 1
                    else:
                        res.serials_ok = False
                        status = "SERIAL"
                        note = "CCS serial %s" % dev["serial"]
                        res.flag("MISMATCH")
                if not status and residual is not None and residual > tolerance:
                    status = "OFFSET"
                    note = "off by %.3f m" % residual
                    res.order_ok = False
                    res.flag("MISMATCH")
                if not status:
                    status = "OK"
                    if carried:
                        note = "carries the %s" % carried
                    elif inclined:
                        note = "order checked; offset is a projection"
            else:
                if kind:
                    status = "MISSING"
                    note = "no matching device in CCS"
                    res.order_ok = False
                    res.flag("MISMATCH")
                elif item.family in families_ok:
                    ok = families_ok[item.family]
                    status = "OK" if ok else "COUNT"
                    note = "" if ok else "type total differs"
                else:
                    status = "NOT IN CCS"
                    note = "not modelled in the CCS"

            res.rows.append(row_for(item, dev, residual, position, status, note))
            if item.leg == "main":
                position += lengths.get(item.family, 0.0)

        # devices the sheet never accounted for
        for leg in ("main", "float"):
            for kind, bucket in pools[leg].items():
                used = cursors[leg].get(kind, 0)
                for dev in bucket[used:]:
                    res.rows.append({
                        "row": "", "item": "", "serial": "",
                        "device": dev["short"], "along": fmt(dev["along"]),
                        "delta": "-", "status": "EXTRA",
                        "note": "in CCS, not on the sheet", "tag": "bad",
                    })
                    res.order_ok = False
                    res.flag("MISMATCH")

        # Only worth comparing when the report carries buoy data at all: some
        # printouts leave the Buoys table out entirely, and that is a property
        # of the report, not a fault in any one streamer.
        if ccs.has_buoys:
            if floats and not any(i.leg == "float" for i in data["items"]):
                res.notes.append("CCS has a front float; the sheet has no Y-piece leg")
                res.flag("CHECK")
            if any(i.leg == "float" for i in data["items"]) and not floats:
                res.notes.append("sheet has a front float leg; none in the CCS")
                res.flag("CHECK")
            if not tails:
                res.notes.append("no tailbuoy in the CCS for this streamer")
                res.flag("CHECK")
        paravanes = [d for d in devices if d["kind"] == "PP"]
        if paravanes:
            res.notes.append("CCS lead-in paravane: %s"
                             % ", ".join(d["short"] for d in paravanes))

        if res.worst > tolerance:
            res.flag("MISMATCH")
        results[number] = res

    # streamers present in only one of the two files
    extras = []
    for number in sorted(set(sheets.keys()) - set(ccs.streamer_numbers())):
        extras.append((number, sheets[number]["sheet"], "sheet only (spare / on reel)"))
    for number in sorted(set(ccs.streamer_numbers()) - set(sheets.keys())):
        extras.append((number, u"", "CCS only - no tab in the workbook"))

    return results, extras, lengths, support


def walk_main(items, devices):
    """
    Yield (sheet item, CCS device or None) along the main line.

    Positioned items take the next CCS device of their kind, in order. Devices
    lifted out of the towed plane - the float leg, the tail riser - carry an
    'above' offset that makes their along a projection, so they are left out
    here and checked for order and serial only.
    """
    main = [d for d in devices if not d["branch"] and d["kind"] in ("QF", "ITX")]
    main.sort(key=lambda d: -d["along"])
    flat = [d for d in main if abs(d["above"]) <= 0.5]
    by_kind = {}
    for dev in flat:
        by_kind.setdefault(dev["kind"], []).append(dev)
    cursor = {}
    for item in items:
        if item.leg != "main":
            continue
        dev = None
        kind = DEVICE_KIND.get(item.family)
        if kind:
            bucket = by_kind.get(kind, [])
            used = cursor.get(kind, 0)
            if used < len(bucket):
                dev = bucket[used]
                cursor[kind] = used + 1
        yield item, dev


def fit_sections(prepared, ccs, shared, exclude=()):
    """
    Solve one section length per equipment family from the CCS offsets.

    Every streamer contributes to the same solution, so a section that is
    missing, extra or in the wrong place cannot be absorbed by adjusting a
    length - it shows up as a residual on every device behind it.

    Returns (lengths, streamers backing each length, worst residual per
    streamer). Streamers named in 'exclude' are scored but not fitted.
    """
    families, seen = [], set()
    for number in shared:
        for item in prepared[number]["items"]:
            if item.leg == "main" and item.family not in seen:
                seen.add(item.family)
                families.append(item.family)
    index = dict((f, i) for i, f in enumerate(families))
    n_par = len(families) + 1                     # + one shared origin offset

    matrix, rhs, tags = [], [], []
    for number in shared:
        if number in exclude:
            continue
        row = [0.0] * n_par
        row[-1] = 1.0
        for item, dev in walk_main(prepared[number]["items"],
                                   ccs.devices.get(number, [])):
            if dev is not None:
                matrix.append(list(row))
                rhs.append(-dev["along"])
                tags.append(number)
            if item.family in index:
                row[index[item.family]] += 1.0

    lengths, support = {}, {}
    if matrix:
        solution = solve(matrix, rhs)
        for family, i in index.items():
            lengths[family] = solution[i]
        lengths["__origin__"] = solution[-1]
        for i, family in enumerate(families):
            support[family] = len(set(tags[k] for k in range(len(matrix))
                                      if matrix[k][i]))

    worst = {}
    for number in shared:
        position = lengths.get("__origin__", 0.0)
        top = 0.0
        for item, dev in walk_main(prepared[number]["items"],
                                   ccs.devices.get(number, [])):
            if dev is not None:
                top = max(top, abs(-dev["along"] - position))
            position += lengths.get(item.family, 0.0)
        worst[number] = top
    return lengths, support, worst


def pool(devices):
    out = {}
    for dev in devices:
        out.setdefault(dev["kind"], []).append(dev)
    return out


def row_for(item, dev, residual, position, status, note):
    tag = {"OK": "ok", "skipped": "skip", "NOT IN CCS": "skip"}.get(status)
    if tag is None:
        tag = "warn" if status == "COUNT" else "bad"
    return {
        "row": item.row,
        "item": item.label,
        "serial": item.serial,
        "device": dev["short"] if dev else "",
        "along": fmt(dev["along"]) if dev else "",
        "delta": fmt(residual) if residual is not None else ("-" if dev else ""),
        "status": status,
        "note": note or item.action or item.comment,
        "tag": tag,
    }


def count_check(items, ccs, number, aliases, res):
    """Sheet type totals against the CCS Streamer Summary for this streamer."""
    sheet_counts = {}
    for item in items:
        sheet_counts[item.family] = sheet_counts.get(item.family, 0) + 1

    ccs_counts = {}
    ccs_labels = {}
    for label, per in ccs.summary.items():
        if number not in per:
            continue
        family = ccs_type_family(label, aliases)
        if family is None:
            continue
        ccs_counts[family] = ccs_counts.get(family, 0) + per[number]
        ccs_labels.setdefault(family, []).append(label)

    ok_by_family = {}
    for family in sorted(set(sheet_counts) | set(ccs_counts)):
        sheet_n = sheet_counts.get(family, 0)
        ccs_n = ccs_counts.get(family)
        label = " / ".join(ccs_labels.get(family, []))
        if ccs_n is None:
            if family in ("DCK", "SRU", "SRA"):
                continue
            res.counts.append((family, u"(not in CCS)", sheet_n, u"-", True))
            ok_by_family[family] = True
            continue
        ok = (sheet_n == ccs_n)
        ok_by_family[family] = ok
        res.counts.append((family, label, sheet_n, ccs_n, ok))
        if not ok:
            res.counts_ok = False
            res.flag("MISMATCH")
    return ok_by_family


# ===========================================================================
# NFH cross check
# ===========================================================================

def printed_decimals(text):
    """How many decimals the CCS printed for a value: '-0.03' -> 2."""
    t = to_text(text).strip()
    if "." in t:
        return len(t.rsplit(".", 1)[-1].strip())
    return 0


def axis_agrees(sheet_value, ccs_value, ccs_raw, extra=0.0):
    """
    The CCS prints offsets rounded for display, so a sheet value agrees when
    it rounds to what the CCS shows. Returns (ok, difference, tolerance).
    """
    if sheet_value is None or ccs_value is None:
        return False, None, None
    tol = 0.5 * (10.0 ** -printed_decimals(ccs_raw)) + 1e-9 + extra
    diff = sheet_value - ccs_value
    return abs(diff) <= tol, diff, tol


def compare_nfh(entries, ccs, extra_tolerance=0.0):
    """
    Cross check NFH offsets: workbook against CCS, per connector.

    Matches on (connector, sub array, position). Returns (rows, stats, notes).
    """
    by_key = {}
    for e in entries:
        by_key.setdefault((e["connector"], e["sub"], e["pos"]), []).append(e)

    ccs_by_key = {}
    conns = set(d["connector"] for d in ccs.nfh if d["connector"] is not None)
    for d in ccs.nfh:
        conn = d["connector"]
        if conn is None:
            # No connector column: only unambiguous when the sheet has one block
            blocks = set(e["connector"] for e in entries)
            conn = list(blocks)[0] if len(blocks) == 1 else None
        ccs_by_key.setdefault((conn, d["sub"], d["pos"]), []).append(d)

    rows, notes = [], []
    stats = {"checked": 0, "ok": 0, "bad": 0, "sheet_only": 0, "ccs_only": 0}

    for key in sorted(set(by_key) | set(ccs_by_key),
                      key=lambda k: tuple((x is None, x) for x in k)):
        conn, sub, pos = key
        sheet = by_key.get(key, [None])[0]
        dev = ccs_by_key.get(key, [None])[0]
        row = {"connector": conn, "sub": sub, "pos": pos,
               "block": sheet["block"] if sheet else u"",
               "device": dev["name"].rsplit(".", 1)[0] if dev else u"",
               "row": sheet["row"] if sheet else u""}

        if sheet is not None and dev is None:
            row.update(status="not in CCS", tag="skip",
                       note="connector %s not configured in this CCS"
                            % (conn if conn is not None else "?"))
            for axis in AXES:
                row[axis + "_sheet"] = fmt(sheet[axis], 4)
                row[axis + "_ccs"] = u""
                row[axis + "_diff"] = u""
            stats["sheet_only"] += 1
        elif sheet is None and dev is not None:
            row.update(status="EXTRA", tag="bad",
                       note="in CCS, not on the NFH sheet")
            for axis in AXES:
                row[axis + "_sheet"] = u""
                row[axis + "_ccs"] = fmt(dev[axis], 4)
                row[axis + "_diff"] = u""
            stats["ccs_only"] += 1
        else:
            bad_axes, worst = [], 0.0
            for axis in AXES:
                ok, diff, tol = axis_agrees(sheet[axis], dev[axis],
                                            dev[axis + "_raw"], extra_tolerance)
                row[axis + "_sheet"] = fmt(sheet[axis], 4)
                row[axis + "_ccs"] = dev[axis + "_raw"] or fmt(dev[axis], 4)
                row[axis + "_diff"] = fmt(diff, 4) if diff is not None else u"-"
                if not ok:
                    bad_axes.append(axis)
                if diff is not None:
                    worst = max(worst, abs(diff))
            stats["checked"] += 1
            if bad_axes:
                stats["bad"] += 1
                row.update(status="MISMATCH", tag="bad",
                           note="%s differ beyond the printed precision"
                                % ", ".join(a.capitalize() for a in bad_axes))
            else:
                stats["ok"] += 1
                row.update(status="OK", tag="ok", note="")
        rows.append(row)

    places = set()
    for d in ccs.nfh:
        for axis in AXES:
            if d[axis + "_raw"]:
                places.add(printed_decimals(d[axis + "_raw"]))
    if places:
        worst = min(places)
        unit = 10.0 ** -worst
        notes.append("CCS prints offsets to %d decimal(s): a difference of "
                     "%.*f m or more is always caught, anything smaller may "
                     "round to the same printed value"
                     % (worst, max(worst, 1), unit))
    if conns:
        notes.append("connector(s) present in this CCS: %s"
                     % ", ".join(str(c) for c in sorted(conns)))
    return rows, stats, notes


# ===========================================================================
# GUI
# ===========================================================================

class StreamerQCPanel(tk.Frame):
    """Docked panel: pick the two files, compare, read the tables."""

    def __init__(self, master=None, **kw):
        tk.Frame.__init__(self, master, bg=BG, **kw)
        try:
            master.configure(bg=BG)
        except Exception:
            pass

        self.ccs_path = tk.StringVar()
        self.sheet_path = tk.StringVar()
        self.nfh_path = tk.StringVar()
        self.tolerance = tk.StringVar(value="%.2f" % DEFAULT_TOLERANCE)
        self.nfh_tolerance = tk.StringVar(value="0.000")
        self.start_leadin = tk.IntVar(value=1)
        self.status = tk.StringVar(value="Pick a CCS printout and a streamer workbook, then Compare.")

        self.results = {}
        self.extras = []
        self.lengths = {}
        self.support = {}
        self.aliases = {}
        self.ccs = None
        self.sheets = None
        self.nfh_rows = []
        self.nfh_stats = {}
        self.nfh_notes = []
        self.nfh_sheet_name = u""

        self._load_state()
        self._styles()
        self._build()
        self._restore_paths()

    # -- look --------------------------------------------------------------

    def _styles(self):
        """Named styles only - never theme_use(), which would repaint xNAVSL."""
        style = ttk.Style()
        for name in ("SQC.Treeview", "SQC.Summary.Treeview"):
            try:
                style.configure(name, background=PANEL, fieldbackground=PANEL,
                                foreground=TEXT, rowheight=20)
                style.configure(name + ".Heading", background=BTN, foreground=TEXT,
                                relief="groove", font=("Helvetica", 9, "bold"))
                style.map(name + ".Heading", background=[("active", BTN_ACTIVE)])
            except tk.TclError:
                pass
        try:
            # Own notebook style so the shell's tab colours are untouched.
            style.configure("SQC.TNotebook", background=BG, borderwidth=0)
            style.configure("SQC.TNotebook.Tab", background=BTN, foreground=TEXT,
                            padding=[14, 5], font=("Helvetica", 9, "bold"))
            style.map("SQC.TNotebook.Tab",
                      background=[("selected", BG), ("active", BTN_ACTIVE)],
                      foreground=[("selected", HEADER_TEXT)])
        except tk.TclError:
            pass
        try:
            style.configure("SQC.TCombobox", fieldbackground=PANEL, background=BTN)
            style.configure("SQC.Vertical.TScrollbar", background=BTN)
            style.configure("SQC.Horizontal.TScrollbar", background=BTN)
        except tk.TclError:
            pass

    def _label(self, parent, text, bold=False, fg=None):
        font = ("Helvetica", 9, "bold") if bold else ("Helvetica", 9)
        return tk.Label(parent, text=text, bg=BG, fg=fg or TEXT, font=font)

    def _button(self, parent, text, command, width=None):
        return tk.Button(parent, text=text, command=command, bg=BTN, fg=TEXT,
                         activebackground=BTN_ACTIVE, activeforeground=TEXT,
                         relief="raised", bd=2, width=width,
                         font=("Helvetica", 9))

    # -- layout ------------------------------------------------------------

    def _build(self):
        self.pack(fill="both", expand=True)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        head = tk.Frame(self, bg=BG)
        head.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        head.grid_columnconfigure(1, weight=1)
        tk.Label(head, text=APP_TITLE, bg=BG, fg=HEADER_TEXT,
                 font=("Helvetica", 13, "bold")).grid(row=0, column=0, sticky="w")
        self._label(head, u"Vessel records  vs  TRINAV CCS configuration",
                    fg=HEADER_TEXT).grid(row=0, column=1, sticky="w", padx=(10, 0))

        # The CCS printout feeds both checks, so it sits above the tabs.
        inputs = tk.Frame(self, bg=BG)
        inputs.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        inputs.grid_columnconfigure(1, weight=1)

        self._label(inputs, "CCS printout:").grid(row=0, column=0, sticky="w", pady=2)
        self.ccs_box = ttk.Combobox(inputs, textvariable=self.ccs_path,
                                    style="SQC.TCombobox")
        self.ccs_box.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self._button(inputs, "Folder...", self.pick_ccs_dir, 9).grid(row=0, column=2, padx=2)
        self._button(inputs, "File...", self.pick_ccs_file, 8).grid(row=0, column=3, padx=2)

        self.tabs = ttk.Notebook(self, style="SQC.TNotebook")
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 2))
        streamer_tab = tk.Frame(self.tabs, bg=BG)
        nfh_tab = tk.Frame(self.tabs, bg=BG)
        self.tabs.add(streamer_tab, text="  Streamer Order  ")
        self.tabs.add(nfh_tab, text="  NFH Positions  ")
        self._build_streamer_tab(streamer_tab)
        self._build_nfh_tab(nfh_tab)

        bar = tk.Frame(self, bg=BG)
        bar.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 6))
        tk.Label(bar, textvariable=self.status, bg=BG, fg=HEADER_TEXT,
                 anchor="w", font=("Helvetica", 9, "bold")).pack(fill="x")
        tk.Label(bar, bg=BG, fg=FG_MUTED, anchor="w", justify="left",
                 font=("Helvetica", 8), text=(
                     u"OK = matches   SERIAL = Q-Fin serial differs   "
                     u"OFFSET = section out of place   MISSING / EXTRA = on "
                     u"one side only   COUNT = type total differs.   "
                     u"TRINAV positions Q-Fins and ITXs only, so two sections "
                     u"between the same pair of them can be swapped without "
                     u"changing any offset - that case is not detectable.")
                 ).pack(fill="x")

    # -- tab 1: streamer order ---------------------------------------------

    def _build_streamer_tab(self, parent):
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        inputs = tk.Frame(parent, bg=BG)
        inputs.grid(row=0, column=0, sticky="ew", pady=(6, 2))
        inputs.grid_columnconfigure(1, weight=1)
        self._label(inputs, "Streamer sheet:").grid(row=0, column=0, sticky="w", pady=2)
        self.sheet_box = ttk.Combobox(inputs, textvariable=self.sheet_path,
                                      style="SQC.TCombobox")
        self.sheet_box.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self._button(inputs, "Folder...", self.pick_sheet_dir, 9).grid(row=0, column=2, padx=2)
        self._button(inputs, "File...", self.pick_sheet_file, 8).grid(row=0, column=3, padx=2)

        opts = tk.Frame(inputs, bg=BG)
        opts.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self._button(opts, "Compare", self.run, 10).pack(side="left")
        tk.Checkbutton(opts, text="Start at lead-in (ignore DCK / SRU / SRA)",
                       variable=self.start_leadin, bg=BG, fg=TEXT,
                       activebackground=BG, selectcolor=PANEL,
                       font=("Helvetica", 9)).pack(side="left", padx=(12, 6))
        self._label(opts, "Offset tolerance (m):").pack(side="left", padx=(6, 3))
        tk.Entry(opts, textvariable=self.tolerance, width=6,
                 bg=PANEL, fg=TEXT).pack(side="left")
        self._button(opts, "Export...", self.export, 10).pack(side="right")
        self._button(opts, "Type map...", self.show_typemap, 11).pack(side="right", padx=6)

        panes = tk.PanedWindow(parent, orient="vertical", bg=BG, sashwidth=6,
                               sashrelief="raised", bd=0)
        panes.grid(row=1, column=0, sticky="nsew", pady=(4, 2))

        top = tk.Frame(panes, bg=BG)
        self._label(top, "Streamers", bold=True, fg=HEADER_TEXT).pack(anchor="w")
        self.summary = self._tree(
            top,
            columns=[("streamer", "Streamer", 70, "center"),
                     ("sheet", "Sheet tab", 150, "w"),
                     ("items", "Sheet items", 80, "center"),
                     ("devices", "CCS devices", 85, "center"),
                     ("counts", "Counts", 70, "center"),
                     ("order", "Order", 70, "center"),
                     ("serials", "Q-Fin serials", 95, "center"),
                     ("worst", "Max offset diff (m)", 120, "center"),
                     ("verdict", "Result", 90, "center")],
            style="SQC.Summary.Treeview", height=9)
        self.summary.bind("<<TreeviewSelect>>", self.on_select)
        panes.add(top, minsize=150)

        bottom = tk.Frame(panes, bg=BG)
        self.detail_title = self._label(bottom, "Detail", bold=True, fg=HEADER_TEXT)
        self.detail_title.pack(anchor="w")
        self.detail = self._tree(
            bottom,
            columns=[("row", "Row", 50, "center"),
                     ("item", "Sheet item", 95, "w"),
                     ("serial", "Serial", 130, "w"),
                     ("device", "CCS device", 150, "w"),
                     ("along", "CCS along (m)", 105, "e"),
                     ("delta", "Diff (m)", 80, "e"),
                     ("status", "Status", 90, "center"),
                     ("note", "Note", 260, "w")],
            style="SQC.Treeview", height=14)
        panes.add(bottom, minsize=160)

    # -- tab 2: NFH positions ----------------------------------------------

    def _build_nfh_tab(self, parent):
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        inputs = tk.Frame(parent, bg=BG)
        inputs.grid(row=0, column=0, sticky="ew", pady=(6, 2))
        inputs.grid_columnconfigure(1, weight=1)
        self._label(inputs, "Offsets workbook:").grid(row=0, column=0, sticky="w", pady=2)
        self.nfh_box = ttk.Combobox(inputs, textvariable=self.nfh_path,
                                    style="SQC.TCombobox")
        self.nfh_box.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        self._button(inputs, "Folder...", self.pick_nfh_dir, 9).grid(row=0, column=2, padx=2)
        self._button(inputs, "File...", self.pick_nfh_file, 8).grid(row=0, column=3, padx=2)

        opts = tk.Frame(inputs, bg=BG)
        opts.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self._button(opts, "Cross check", self.run_nfh, 12).pack(side="left")
        self._label(opts, "Extra tolerance (m):").pack(side="left", padx=(12, 3))
        tk.Entry(opts, textvariable=self.nfh_tolerance, width=7,
                 bg=PANEL, fg=TEXT).pack(side="left")
        self._label(opts, "(added to the CCS printed precision)",
                    fg=FG_MUTED).pack(side="left", padx=(4, 0))
        self._button(opts, "Export...", self.export_nfh, 10).pack(side="right")

        self.nfh_title = self._label(parent, "NFH offsets - workbook vs CCS",
                                     bold=True, fg=HEADER_TEXT)
        self.nfh_title.grid(row=1, column=0, sticky="w", pady=(6, 0))

        holder = tk.Frame(parent, bg=BG)
        holder.grid(row=2, column=0, sticky="nsew")
        self.nfh_tree = self._tree(
            holder,
            columns=[("conn", "NFH", 110, "w"),
                     ("sub", "Sub array", 70, "center"),
                     ("pos", "Position", 65, "center"),
                     ("device", "CCS device", 175, "w"),
                     ("across_sheet", "Across sheet", 90, "e"),
                     ("across_ccs", "Across CCS", 85, "e"),
                     ("across_diff", "d Across", 80, "e"),
                     ("along_sheet", "Along sheet", 90, "e"),
                     ("along_ccs", "Along CCS", 85, "e"),
                     ("along_diff", "d Along", 80, "e"),
                     ("above_sheet", "Above sheet", 90, "e"),
                     ("above_ccs", "Above CCS", 85, "e"),
                     ("above_diff", "d Above", 80, "e"),
                     ("status", "Status", 95, "center"),
                     ("note", "Note", 230, "w")],
            style="SQC.Treeview", height=20)

    def _tree(self, parent, columns, style, height):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        names = [c[0] for c in columns]
        tree = ttk.Treeview(wrap, columns=names, show="headings",
                            style=style, height=height, selectmode="browse")
        for key, title, width, anchor in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor=anchor, stretch=(key == "note"))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview,
                            style="SQC.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview,
                            style="SQC.Horizontal.TScrollbar")
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree.tag_configure("ok", background=ROW_OK)
        tree.tag_configure("warn", background=ROW_WARN)
        tree.tag_configure("bad", background=ROW_BAD)
        tree.tag_configure("skip", background=ROW_SKIP, foreground=FG_MUTED)
        return tree

    # -- file pickers ------------------------------------------------------

    def _fill_box(self, box, var, folder, patterns, validator=None):
        found = []
        for pattern in patterns:
            found.extend(glob.glob(os.path.join(folder, pattern)))
        found = [f for f in found if os.path.isfile(f)]
        if validator:
            found = [f for f in found if validator(f)]
        found.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        box["values"] = found
        if found:
            var.set(found[0])
            self.status.set("%d file(s) found in %s - newest selected."
                            % (len(found), folder))
        else:
            self.status.set("No matching files in %s" % folder)

    @staticmethod
    def _looks_like_ccs(path):
        try:
            head = open(path, "rb").read(200000)
        except IOError:
            return False
        return ("tableName" in head) or ("CCS Report" in head)

    def pick_ccs_dir(self):
        folder = tkFileDialog.askdirectory(title="Folder holding the CCS printout")
        if folder:
            self._fill_box(self.ccs_box, self.ccs_path, folder,
                           ("*.html", "*.htm", "*.xml"), self._looks_like_ccs)

    def pick_ccs_file(self):
        path = tkFileDialog.askopenfilename(
            title="CCS printout",
            filetypes=[("CCS report", "*.html *.htm *.xml"), ("All files", "*")])
        if path:
            self.ccs_path.set(path)

    def pick_sheet_dir(self):
        folder = tkFileDialog.askdirectory(title="Folder holding the streamer workbook")
        if folder:
            self._fill_box(self.sheet_box, self.sheet_path, folder,
                           ("*.xlsx", "*.xlsm"))

    def pick_sheet_file(self):
        path = tkFileDialog.askopenfilename(
            title="Streamer workbook",
            filetypes=[("Excel workbook", "*.xlsx *.xlsm"), ("All files", "*")])
        if path:
            self.sheet_path.set(path)

    def pick_nfh_dir(self):
        folder = tkFileDialog.askdirectory(title="Folder holding the offsets workbook")
        if folder:
            self._fill_box(self.nfh_box, self.nfh_path, folder, ("*.xlsx", "*.xlsm"))

    def pick_nfh_file(self):
        path = tkFileDialog.askopenfilename(
            title="Offsets workbook (NFH positions)",
            filetypes=[("Excel workbook", "*.xlsx *.xlsm"), ("All files", "*")])
        if path:
            self.nfh_path.set(path)

    # -- run ---------------------------------------------------------------

    def run(self):
        sheet_path = self.sheet_path.get().strip()
        if os.path.isdir(sheet_path):
            self._fill_box(self.sheet_box, self.sheet_path, sheet_path,
                           ("*.xlsx", "*.xlsm"))
            sheet_path = self.sheet_path.get().strip()
        if not os.path.isfile(sheet_path):
            tkMessageBox.showwarning(APP_TITLE, "Pick a streamer workbook first.")
            return
        try:
            tolerance = float(self.tolerance.get())
        except ValueError:
            tolerance = DEFAULT_TOLERANCE
            self.tolerance.set("%.2f" % tolerance)

        self.status.set("Reading...")
        self.update_idletasks()
        if self._load_ccs() is None:
            return
        try:
            self.sheets, problems = read_sheets(sheet_path)
        except (XlsxError, IOError) as exc:
            tkMessageBox.showerror(APP_TITLE, "Streamer workbook:\n%s" % exc)
            self.status.set("Workbook could not be read.")
            return

        self.results, self.extras, self.lengths, self.support = compare(
            self.sheets, self.ccs, tolerance,
            bool(self.start_leadin.get()), self.aliases)

        self._fill_summary(problems)
        self._save_state()

    def _load_ccs(self):
        """Read the CCS printout shared by both checks; None on failure."""
        path = self.ccs_path.get().strip()
        if os.path.isdir(path):
            self._fill_box(self.ccs_box, self.ccs_path, path,
                           ("*.html", "*.htm", "*.xml"), self._looks_like_ccs)
            path = self.ccs_path.get().strip()
        if not os.path.isfile(path):
            tkMessageBox.showwarning(APP_TITLE, "Pick a CCS printout first.")
            return None
        try:
            self.ccs = CcsReport(path)
        except (CcsError, IOError) as exc:
            tkMessageBox.showerror(APP_TITLE, "CCS printout:\n%s" % exc)
            self.status.set("CCS printout could not be read.")
            return None
        return self.ccs

    def run_nfh(self):
        """Cross check NFH offsets: offsets workbook against the CCS."""
        if self._load_ccs() is None:
            return
        path = self.nfh_path.get().strip()
        if os.path.isdir(path):
            self._fill_box(self.nfh_box, self.nfh_path, path, ("*.xlsx", "*.xlsm"))
            path = self.nfh_path.get().strip()
        if not os.path.isfile(path):
            tkMessageBox.showwarning(APP_TITLE, "Pick the offsets workbook first.")
            return
        try:
            extra = abs(float(self.nfh_tolerance.get()))
        except ValueError:
            extra = 0.0
            self.nfh_tolerance.set("0.000")

        self.status.set("Reading NFH positions...")
        self.update_idletasks()
        try:
            entries, sheet_name, notes = read_nfh_sheet(path)
        except (XlsxError, IOError) as exc:
            tkMessageBox.showerror(APP_TITLE, "Offsets workbook:\n%s" % exc)
            self.status.set("NFH positions could not be read.")
            return
        if not self.ccs.nfh:
            tkMessageBox.showwarning(
                APP_TITLE, "This CCS printout has no Near Field Hydrophone "
                           "table, so there is nothing to cross check against.")
            self.status.set("No NFH table in the CCS printout.")
            return

        self.nfh_sheet_name = sheet_name
        self.nfh_rows, self.nfh_stats, self.nfh_notes = compare_nfh(
            entries, self.ccs, extra)
        self.nfh_notes = list(notes) + list(self.nfh_notes)

        for iid in self.nfh_tree.get_children():
            self.nfh_tree.delete(iid)
        for row in self.nfh_rows:
            conn = row["block"] or (u"NFH %s" % row["connector"])
            self.nfh_tree.insert("", "end", tags=(row["tag"],), values=(
                conn, row["sub"], row["pos"], row["device"],
                row["across_sheet"], row["across_ccs"], row["across_diff"],
                row["along_sheet"], row["along_ccs"], row["along_diff"],
                row["above_sheet"], row["above_ccs"], row["above_diff"],
                row["status"], row["note"]))

        s = self.nfh_stats
        parts = ["%d NFH cross checked" % s["checked"]]
        parts.append("%d match" % s["ok"] if not s["bad"]
                     else "%d match, %d MISMATCH" % (s["ok"], s["bad"]))
        if s["sheet_only"]:
            parts.append("%d on the sheet not configured in this CCS" % s["sheet_only"])
        if s["ccs_only"]:
            parts.append("%d in CCS with no sheet row" % s["ccs_only"])
        self.status.set("  |  ".join(parts))
        self.nfh_title.config(
            text="NFH offsets - '%s' vs CCS   [%s]"
                 % (sheet_name, "; ".join(self.nfh_notes)))
        self._save_state()

    def export_nfh(self):
        if not self.nfh_rows:
            tkMessageBox.showinfo(APP_TITLE, "Run the NFH cross check first.")
            return
        path = tkFileDialog.asksaveasfilename(
            title="Export NFH cross check",
            defaultextension=".csv",
            initialfile="nfh_vs_ccs_%s.csv" % time.strftime("%Y%m%d_%H%M"),
            filetypes=[("CSV", "*.csv"), ("HTML report", "*.html")])
        if not path:
            return
        try:
            if path.lower().endswith((".html", ".htm")):
                self._export_nfh_html(path)
            else:
                with open(path, "wb") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(
                        ["NFH", "Sub array", "Position", "CCS device",
                         "Across sheet", "Across CCS", "d Across",
                         "Along sheet", "Along CCS", "d Along",
                         "Above sheet", "Above CCS", "d Above",
                         "Status", "Note"])
                    for r in self.nfh_rows:
                        writer.writerow([
                            to_text(r["block"]).encode("utf-8"), r["sub"], r["pos"],
                            to_text(r["device"]).encode("utf-8"),
                            r["across_sheet"], r["across_ccs"], r["across_diff"],
                            r["along_sheet"], r["along_ccs"], r["along_diff"],
                            r["above_sheet"], r["above_ccs"], r["above_diff"],
                            r["status"], to_text(r["note"]).encode("utf-8")])
        except IOError as exc:
            tkMessageBox.showerror(APP_TITLE, "Could not write:\n%s" % exc)
            return
        self.status.set("Exported to %s" % path)

    def _export_nfh_html(self, path):
        def esc(v):
            return (to_text(v).replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))
        s = self.nfh_stats
        out = [u"<!DOCTYPE html><html><head><meta charset='utf-8'>",
               u"<title>NFH offsets vs CCS</title><style>",
               u"body{font-family:Arial,Helvetica,sans-serif;font-size:12px;"
               u"margin:18px;background:#fff;color:#000}"
               u"h1{font-size:18px;color:%s;margin:0 0 4px}"
               u"table{border-collapse:collapse;width:100%%;margin-top:8px}"
               u"th{background:%s;border:1px solid #7d95ad;padding:4px 7px;"
               u"text-align:left;font-size:11px}"
               u"td{border:1px solid #cfd8e3;padding:3px 7px;"
               u"font-variant-numeric:tabular-nums}"
               u".num{text-align:right}.ok{background:%s}.bad{background:%s}"
               u".skip{background:%s;color:#5a6570}.meta{color:#41505e}"
               % (HEADER_TEXT, BTN, ROW_OK, ROW_BAD, ROW_SKIP),
               u"</style></head><body>",
               u"<h1>NFH position cross check</h1>",
               u"<p class='meta'>CCS printout: %s<br>Offsets workbook: %s (sheet "
               u"'%s')<br>Checked: %s<br><b>%d of %d match</b></p>"
               % (esc(self.ccs_path.get()), esc(self.nfh_path.get()),
                  esc(self.nfh_sheet_name), time.strftime("%Y-%m-%d %H:%M:%S"),
                  s["ok"], s["checked"]),
               u"<p class='meta'>%s</p>" % esc("; ".join(self.nfh_notes)),
               u"<table><tr><th>NFH</th><th>Sub array</th><th>Position</th>"
               u"<th>CCS device</th><th>Across sheet</th><th>Across CCS</th>"
               u"<th>d Across</th><th>Along sheet</th><th>Along CCS</th>"
               u"<th>d Along</th><th>Above sheet</th><th>Above CCS</th>"
               u"<th>d Above</th><th>Status</th><th>Note</th></tr>"]
        for r in self.nfh_rows:
            out.append(
                u"<tr class='%s'><td>%s</td><td class='num'>%s</td>"
                u"<td class='num'>%s</td><td>%s</td>"
                u"<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                u"<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                u"<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                u"<td><b>%s</b></td><td>%s</td></tr>"
                % (r["tag"], esc(r["block"]), r["sub"], r["pos"], esc(r["device"]),
                   r["across_sheet"], r["across_ccs"], r["across_diff"],
                   r["along_sheet"], r["along_ccs"], r["along_diff"],
                   r["above_sheet"], r["above_ccs"], r["above_diff"],
                   esc(r["status"]), esc(r["note"])))
        out.append(u"</table></body></html>")
        with open(path, "wb") as fh:
            fh.write(u"\n".join(out).encode("utf-8"))

    def _fill_summary(self, problems=None):
        for iid in self.summary.get_children():
            self.summary.delete(iid)
        for iid in self.detail.get_children():
            self.detail.delete(iid)

        bad = 0
        for number in sorted(self.results):
            res = self.results[number]
            tag = {"OK": "ok", "CHECK": "warn", "MISMATCH": "bad"}[res.verdict]
            if res.verdict != "OK":
                bad += 1
            self.summary.insert("", "end", iid="S%d" % number, tags=(tag,), values=(
                number, res.sheet, res.n_items, res.n_devices,
                "OK" if res.counts_ok else "DIFF",
                "OK" if res.order_ok else "DIFF",
                "%d/%d" % (res.fins_ok, res.fins_checked) if res.fins_checked else "-",
                fmt(res.worst),
                res.verdict))
        for number, sheet, why in self.extras:
            self.summary.insert("", "end", tags=("skip",),
                                values=(number, sheet, "", "", "", "", "", "", why))

        parts = ["%d streamer(s) compared" % len(self.results)]
        parts.append("all match" if not bad else "%d need attention" % bad)
        if self.extras:
            parts.append("%d not in both files" % len(self.extras))
        for note in (problems or []):
            parts.append(note)
        self.status.set("  |  ".join(parts))

        children = self.summary.get_children()
        if children:
            self.summary.selection_set(children[0])
            self.summary.focus(children[0])

    def on_select(self, _event=None):
        selection = self.summary.selection()
        if not selection:
            return
        iid = selection[0]
        if not iid.startswith("S"):
            return
        res = self.results.get(int(iid[1:]))
        if res is None:
            return
        for item in self.detail.get_children():
            self.detail.delete(item)
        for row in res.rows:
            self.detail.insert("", "end", tags=(row["tag"],), values=(
                row["row"], row["item"], row["serial"], row["device"],
                row["along"], row["delta"], row["status"], row["note"]))
        title = "Streamer %d  -  %s  -  %d rows" % (res.number, res.sheet, len(res.rows))
        if res.notes:
            title += "   [" + "; ".join(res.notes) + "]"
        self.detail_title.config(text=title)

    # -- type map ----------------------------------------------------------

    def show_typemap(self):
        if not self.ccs:
            tkMessageBox.showinfo(APP_TITLE, "Run a comparison first.")
            return
        win = tk.Toplevel(self)
        win.title("%s - equipment type map" % APP_TITLE)
        win.configure(bg=BG)
        tk.Label(win, bg=BG, fg=HEADER_TEXT, font=("Helvetica", 9),
                 justify="left", wraplength=560,
                 text=("How each CCS equipment type was matched to a sheet code.\n"
                       "Double-click an unmapped row to assign it a code; the "
                       "mapping is remembered.")
                 ).pack(anchor="w", padx=8, pady=(8, 4))
        tree = ttk.Treeview(win, columns=("ccs", "family", "total"),
                            show="headings", style="SQC.Treeview", height=18)
        for key, title, width in (("ccs", "CCS equipment type", 260),
                                  ("family", "Sheet code", 120),
                                  ("total", "Total in CCS", 100)):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        tree.tag_configure("ok", background=ROW_OK)
        tree.tag_configure("warn", background=ROW_WARN)
        tree.pack(fill="both", expand=True, padx=8, pady=4)

        for label in sorted(self.ccs.summary):
            family = ccs_type_family(label, self.aliases)
            total = sum(self.ccs.summary[label].values())
            if family is None and label.strip().startswith("-"):
                continue
            tree.insert("", "end", tags=("ok" if family else "warn",),
                        values=(label, family or "(unmapped)", total))

        def assign(_event=None):
            selection = tree.selection()
            if not selection:
                return
            label = tree.item(selection[0], "values")[0]
            code = tkSimpleDialog.askstring(
                APP_TITLE, "Sheet code for CCS type:\n%s" % label, parent=win)
            if not code:
                return
            self.aliases[norm_key(label)] = code.strip().upper()
            self._save_state()
            tree.item(selection[0], values=(label, code.strip().upper(),
                                            tree.item(selection[0], "values")[2]),
                      tags=("ok",))
            self.status.set("Mapped '%s' to %s - press Compare to apply."
                            % (label, code.strip().upper()))

        tree.bind("<Double-1>", assign)
        self._button(win, "Close", win.destroy, 10).pack(pady=(0, 8))

    # -- export ------------------------------------------------------------

    def export(self):
        if not self.results:
            tkMessageBox.showinfo(APP_TITLE, "Run a comparison first.")
            return
        path = tkFileDialog.asksaveasfilename(
            title="Export result",
            defaultextension=".csv",
            initialfile="streamer_vs_ccs_%s.csv" % time.strftime("%Y%m%d_%H%M"),
            filetypes=[("CSV", "*.csv"), ("HTML report", "*.html"),
                       ("Text report", "*.txt")])
        if not path:
            return
        try:
            if path.lower().endswith(".txt"):
                self._export_txt(path)
            elif path.lower().endswith((".html", ".htm")):
                self._export_html(path)
            else:
                self._export_csv(path)
        except IOError as exc:
            tkMessageBox.showerror(APP_TITLE, "Could not write:\n%s" % exc)
            return
        self.status.set("Exported to %s" % path)

    def _export_csv(self, path):
        with open(path, "wb") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Streamer", "Sheet", "Row", "Sheet item", "Serial",
                             "CCS device", "CCS along (m)", "Diff (m)",
                             "Status", "Note"])
            for number in sorted(self.results):
                res = self.results[number]
                for row in res.rows:
                    writer.writerow([number, res.sheet.encode("utf-8"), row["row"],
                                     row["item"].encode("utf-8"),
                                     row["serial"].encode("utf-8"),
                                     row["device"].encode("utf-8"),
                                     row["along"], row["delta"], row["status"],
                                     to_text(row["note"]).encode("utf-8")])

    def _export_txt(self, path):
        lines = []
        lines.append("%s - streamer build sheet vs CCS" % APP_TITLE)
        lines.append("CCS sheet : %s" % self.ccs_path.get())
        lines.append("Workbook  : %s" % self.sheet_path.get())
        lines.append("Run       : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        lines.append("")
        for number in sorted(self.results):
            res = self.results[number]
            lines.append("Streamer %-3d %-22s %s" % (number, res.sheet, res.verdict))
            lines.append("    counts %s   order %s   Q-Fin serials %d/%d   max offset diff %s m"
                         % ("OK" if res.counts_ok else "DIFF",
                            "OK" if res.order_ok else "DIFF",
                            res.fins_ok, res.fins_checked, fmt(res.worst)))
            for family, label, sheet_n, ccs_n, ok in res.counts:
                if not ok:
                    lines.append("      COUNT  %-8s sheet %-4s CCS %-4s  (%s)"
                                 % (family, sheet_n, ccs_n, label))
            for row in res.rows:
                if row["status"] in ("OK", "skipped", "NOT IN CCS"):
                    continue
                lines.append("      %-10s row %-5s %-10s %-16s %s"
                             % (row["status"], row["row"], row["item"],
                                row["device"], row["note"]))
            for note in res.notes:
                lines.append("      NOTE   %s" % note)
            lines.append("")
        for number, sheet, why in self.extras:
            lines.append("Streamer %-3d %-22s %s" % (number, sheet, why))
        with open(path, "wb") as fh:
            fh.write(u"\n".join(to_text(l) for l in lines).encode("utf-8"))

    def _export_html(self, path):
        """Self contained QC record - opens in any browser, prints cleanly."""
        def esc(value):
            return (to_text(value).replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))

        clean = sum(1 for r in self.results.values() if r.verdict == "OK")
        out = []
        out.append(u"<!DOCTYPE html><html><head><meta charset='utf-8'>")
        out.append(u"<title>Streamer sheet vs CCS</title><style>")
        out.append(u"body{font-family:Arial,Helvetica,sans-serif;font-size:12px;"
                   u"margin:18px;color:#000;background:#fff}"
                   u"h1{font-size:19px;color:%s;margin:0 0 2px}"
                   u"h2{font-size:14px;color:%s;margin:22px 0 4px;"
                   u"border-bottom:2px solid %s;padding-bottom:3px}"
                   u"table{border-collapse:collapse;margin:6px 0;width:100%%}"
                   u"th{background:%s;text-align:left;padding:4px 7px;"
                   u"border:1px solid #7d95ad;font-size:11px}"
                   u"td{padding:3px 7px;border:1px solid #cfd8e3;"
                   u"font-variant-numeric:tabular-nums}"
                   u".num{text-align:right}.ok{background:%s}.warn{background:%s}"
                   u".bad{background:%s}.skip{background:%s;color:#5a6570}"
                   u".meta{color:#41505e;margin:1px 0}"
                   u".tag{font-weight:bold}"
                   % (HEADER_TEXT, HEADER_TEXT, BTN, BTN,
                      ROW_OK, ROW_WARN, ROW_BAD, ROW_SKIP))
        out.append(u"</style></head><body>")
        out.append(u"<h1>Streamer build sheet vs CCS configuration</h1>")
        out.append(u"<p class='meta'>CCS printout: %s<br>Streamer workbook: %s<br>"
                   u"Checked: %s<br><b>%d of %d streamers match</b></p>"
                   % (esc(self.ccs_path.get()), esc(self.sheet_path.get()),
                      time.strftime("%Y-%m-%d %H:%M:%S"), clean, len(self.results)))

        out.append(u"<h2>Summary</h2><table><tr>"
                   u"<th>Streamer</th><th>Sheet tab</th><th>Sheet items</th>"
                   u"<th>CCS devices</th><th>Counts</th><th>Order</th>"
                   u"<th>Q-Fin serials</th><th>Max offset diff (m)</th>"
                   u"<th>Result</th></tr>")
        for number in sorted(self.results):
            res = self.results[number]
            css = {"OK": "ok", "CHECK": "warn", "MISMATCH": "bad"}[res.verdict]
            out.append(u"<tr class='%s'><td>%d</td><td>%s</td><td class='num'>%d</td>"
                       u"<td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td>"
                       u"<td class='num'>%s</td><td class='tag'>%s</td></tr>"
                       % (css, number, esc(res.sheet), res.n_items, res.n_devices,
                          "OK" if res.counts_ok else "DIFF",
                          "OK" if res.order_ok else "DIFF",
                          "%d/%d" % (res.fins_ok, res.fins_checked)
                          if res.fins_checked else "-",
                          fmt(res.worst), res.verdict))
        for number, sheet, why in self.extras:
            out.append(u"<tr class='skip'><td>%d</td><td>%s</td>"
                       u"<td colspan='7'>%s</td></tr>" % (number, esc(sheet), esc(why)))
        out.append(u"</table>")

        for number in sorted(self.results):
            res = self.results[number]
            out.append(u"<h2>Streamer %d &ndash; %s &ndash; %s</h2>"
                       % (number, esc(res.sheet), res.verdict))
            if res.notes:
                out.append(u"<p class='meta'>%s</p>"
                           % esc("; ".join(res.notes)))
            bad_counts = [c for c in res.counts if not c[4]]
            if bad_counts:
                out.append(u"<table><tr><th>Equipment</th><th>CCS type</th>"
                           u"<th>Sheet</th><th>CCS</th></tr>")
                for family, label, sheet_n, ccs_n, _ in bad_counts:
                    out.append(u"<tr class='bad'><td>%s</td><td>%s</td>"
                               u"<td class='num'>%s</td><td class='num'>%s</td></tr>"
                               % (esc(family), esc(label), sheet_n, ccs_n))
                out.append(u"</table>")
            out.append(u"<table><tr><th>Row</th><th>Sheet item</th><th>Serial</th>"
                       u"<th>CCS device</th><th>CCS along (m)</th><th>Diff (m)</th>"
                       u"<th>Status</th><th>Note</th></tr>")
            for row in res.rows:
                out.append(u"<tr class='%s'><td class='num'>%s</td><td>%s</td>"
                           u"<td>%s</td><td>%s</td><td class='num'>%s</td>"
                           u"<td class='num'>%s</td><td class='tag'>%s</td>"
                           u"<td>%s</td></tr>"
                           % (row["tag"], row["row"], esc(row["item"]),
                              esc(row["serial"]), esc(row["device"]),
                              row["along"], row["delta"], esc(row["status"]),
                              esc(row["note"])))
            out.append(u"</table>")

        out.append(u"<p class='meta'>TRINAV positions Q-Fins and ITXs only. "
                   u"Sections between the same pair of them are checked by total "
                   u"length and by type count, so swapping two of them does not "
                   u"change any offset and is not detectable from the printout.</p>")
        out.append(u"</body></html>")
        with open(path, "wb") as fh:
            fh.write(u"\n".join(out).encode("utf-8"))

    # -- state -------------------------------------------------------------

    def _load_state(self):
        state = None
        for path in (STATE_FILE, LEGACY_STATE_FILE):
            try:
                with open(path) as fh:
                    state = json.load(fh)
                break
            except (IOError, ValueError):
                continue
        if state is None:
            return
        if isinstance(state, dict):
            self._state = state
            aliases = state.get("aliases")
            if isinstance(aliases, dict):
                self.aliases = dict((to_text(k), to_text(v))
                                    for k, v in aliases.items())
        else:
            self._state = {}

    def _restore_paths(self):
        state = getattr(self, "_state", {}) or {}
        for key, var in (("ccs", self.ccs_path), ("sheet", self.sheet_path),
                         ("nfh", self.nfh_path)):
            value = state.get(key)
            if isinstance(value, basestring) and os.path.exists(value):
                var.set(value)
        tol = state.get("tolerance")
        if isinstance(tol, (int, float)):
            self.tolerance.set("%.2f" % tol)
        if "start_leadin" in state:
            self.start_leadin.set(1 if state.get("start_leadin") else 0)

    def _save_state(self):
        try:
            tol = float(self.tolerance.get())
        except ValueError:
            tol = DEFAULT_TOLERANCE
        state = {
            "ccs": self.ccs_path.get(),
            "sheet": self.sheet_path.get(),
            "nfh": self.nfh_path.get(),
            "tolerance": tol,
            "start_leadin": bool(self.start_leadin.get()),
            "aliases": self.aliases,
        }
        try:
            with open(STATE_FILE, "w") as fh:
                json.dump(state, fh, indent=1)
        except IOError:
            pass


# ===========================================================================
# xNAVSL embed hook / standalone
# ===========================================================================

def xnavsl_embed(master):
    """Host inside xNAVSL (or any parent frame); does not create a new Tk."""
    panel = StreamerQCPanel(master)
    panel.pack(fill=tk.BOTH, expand=True)
    return panel


def main():
    root = tk.Tk()
    root.title("%s - vessel records vs TRINAV CCS (Python 2.7)" % APP_TITLE)
    root.configure(bg=BG)
    root.geometry("1180x760")
    StreamerQCPanel(master=root)
    root.mainloop()


if __name__ == "__main__":
    main()
