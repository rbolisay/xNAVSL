#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
"""
xQfinDB  -  Qfin serial-number editor for Qfin ConfigDB scenario files.

Python 2.7 + Tkinter. Embeddable in xNAVSL via xnavsl_embed(master).

A Qfin scenario file holds one <streamer> block per streamer, each containing a
run of <qfin sn="NNNN" inline-offset="..."/> elements. This tool shows one
table column per streamer and one row per in-line qfin position, so the serial
numbers can be edited in place instead of hand-editing the file in nano.

Saving is BYTE-EXACT. Only the characters between the quotes of a changed
sn="..." attribute are replaced; every other byte of the file - indentation,
attribute order, comments, blank lines, line endings, the XML declaration - is
written back unchanged, so the qfin software still reads the file.

Files open locally or over SSH. Remote listing/fetch/save use, for example:
  ssh -x qfinop@navsolve1 "cd '/home/qfinop/data/ConfigDB/ConfigStorage' && ls -1Ap"
Ai assisted code by RBolisay
"""
from __future__ import print_function

import os
import re
import sys
import json
import stat
import time
import shutil
import tempfile
import threading
import subprocess

import Queue

import Tkinter as tk
import ttk
import tkFileDialog as filedialog
import tkMessageBox as messagebox

# ---------------------------------------------------------------------------
# NAVSL Blue Aura theme (same palette as xSpace / xNAVSL)
# ---------------------------------------------------------------------------
GUI_BG = "#B4C8E1"
BTN_BG = "#8DA9CC"
BTN_ACTIVE = "#7C9BCD"
HEADER_FG = "#000033"
TEXT_FG = "#000000"
CANVAS_BG = "#E0EBF5"
ENTRY_BG = "#FFFFFF"
STATUS_FG = "#404040"
CHANGED_BG = "#FFE9A8"
EDIT_BG = "#FFF9D6"
WARN_FG = "#8B0000"
OK_FG = "#14561E"
GRID_LINE = "#9FB6D0"
BLANK_BG = "#E4EAF2"
SEL_OUTLINE = "#0A3D91"
HDR_SEL_BG = "#4F76AE"
HDR_SEL_FG = "#FFFFFF"
FOUND_BG = "#BFE7B0"

CELL_W = 86            # one streamer column
CELL_H = 20            # one qfin row
ROWHDR_W = 54          # frozen "Qfin" number column

FONT_MAIN = ("TkDefaultFont", 10)
FONT_BOLD = ("TkDefaultFont", 10, "bold")
FONT_TITLE = ("TkDefaultFont", 12, "bold")
FONT_SMALL = ("TkDefaultFont", 9)
FONT_CELL = ("TkFixedFont", 9)

# ---------------------------------------------------------------------------
# SSH / remote settings
# ---------------------------------------------------------------------------
SSH_USER = "qfinop"
SSH_TIMEOUT = 20
SSH_SERVERS = ["navsolve1", "navsolve2"]
LOCAL_LABEL = "Local (this machine)"
REMOTE_DEFAULT_DIR = "/home/qfinop/data/ConfigDB/ConfigStorage"
MAX_FETCH_BYTES = 20 * 1024 * 1024

# Remembers the last file opened, the server it came from, and the folders the
# two Browse dialogs last landed in. Site default is the shared QC config tree;
# $HOME is the fallback when that tree is missing or read-only.
DEFAULT_CONFIG_DIR = "/usr/local/trinop/qcfiles/Misc/qfindb"
CONFIG_NAME = "xqfindb.json"
HOME_CONFIG = os.path.join(os.path.expanduser("~"), "." + CONFIG_NAME)


def default_settings_file():
    """Site config path, creating the folder if it is missing."""
    try:
        if not os.path.isdir(DEFAULT_CONFIG_DIR):
            os.makedirs(DEFAULT_CONFIG_DIR)
        if os.access(DEFAULT_CONFIG_DIR, os.W_OK | os.X_OK):
            return os.path.join(DEFAULT_CONFIG_DIR, CONFIG_NAME)
    except (IOError, OSError):
        pass
    return HOME_CONFIG

# Any extension is accepted; these only order the file-dialog filter.
FILE_TYPES = [
    ("Qfin config files", "*.xml"),
    ("All files", "*"),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def load_settings(path):
    """Remembered state from path, or an empty dict. Never raises."""
    try:
        with open(path) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def save_settings(path, data):
    """Best effort - remembering is a convenience, never a reason to fail."""
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        return None
    except (IOError, OSError, TypeError, ValueError) as exc:
        return str(exc)


def shq(text):
    """Single-quote a string for a POSIX shell."""
    return "'" + str(text).replace("'", "'\\''") + "'"


def to_text(data):
    """Bytes -> unicode for display, never raising."""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data


def _ensure_display():
    """
    Tkinter needs $DISPLAY. SSH shells often unset it even when the host has a
    local X session at :0 (common on QC workstations / nav consoles).
    """
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    if sys.platform.startswith("linux"):
        try:
            test_env = os.environ.copy()
            test_env["DISPLAY"] = ":0"
            subprocess.check_output(
                ["xdpyinfo"], env=test_env, stderr=subprocess.STDOUT)
            os.environ["DISPLAY"] = ":0"
            return True
        except Exception:
            pass
    return False


class BgRunner(object):
    """Run blocking work (ssh) off the Tk thread, deliver results on it."""

    def __init__(self, widget, interval=120):
        self.widget = widget
        self.interval = interval
        self.queue = Queue.Queue()
        self._after_id = None
        self._alive = True
        self._tick()

    def submit(self, fn, done):
        def worker():
            try:
                self.queue.put((done, fn(), None))
            except Exception as exc:                      # worker thread only
                self.queue.put((done, None, exc))
        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()

    def _tick(self):
        if not self._alive:
            return
        while True:
            try:
                done, result, err = self.queue.get_nowait()
            except Queue.Empty:
                break
            try:
                done(result, err)
            except Exception:
                pass
        try:
            self._after_id = self.widget.after(self.interval, self._tick)
        except tk.TclError:
            self._alive = False

    def stop(self):
        self._alive = False
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None


# ---------------------------------------------------------------------------
# SSH transport
# ---------------------------------------------------------------------------
def _make_askpass_script(password):
    """Temp helper so ssh can take a password without a terminal."""
    safe = password.replace("\\", "\\\\").replace("'", "'\\''")
    script = "#!/bin/sh\nexec printf '%s' '" + safe + "'\n"
    fd, path = tempfile.mkstemp(suffix=".sh", prefix="xqfindb_")
    try:
        os.write(fd, script.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRWXU)
    return path


def ssh_display(host, command):
    """Human-readable equivalent of what the tool runs."""
    one_line = " ".join(command.split())
    if len(one_line) > 110:
        one_line = one_line[:107] + "..."
    return 'ssh -x %s@%s "%s"' % (SSH_USER, host, one_line)


def run_ssh(host, command, password="", stdin_data=None):
    """
    Run command on host as SSH_USER. Returns (stdout_bytes, stderr_text, rc).

    With no password, key auth only (BatchMode) so a missing key fails fast
    instead of hanging on an invisible prompt. With a password, ssh is given a
    temporary SSH_ASKPASS helper - no third-party tool is required.
    """
    cmd = [
        "ssh", "-x",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=%d" % SSH_TIMEOUT,
        "-o", "LogLevel=ERROR",
    ]
    env = os.environ.copy()
    askpass_path = None
    devnull = None
    try:
        if password:
            askpass_path = _make_askpass_script(password)
            env["SSH_ASKPASS"] = askpass_path
            env["SSH_ASKPASS_REQUIRE"] = "force"   # OpenSSH >= 8.4; older ignore
            env["DISPLAY"] = env.get("DISPLAY") or ":0"
            cmd += [
                "-o", "PubkeyAuthentication=no",
                "-o", "PreferredAuthentications=keyboard-interactive,password",
                "-o", "PasswordAuthentication=yes",
                "-o", "BatchMode=no",
                "-o", "NumberOfPasswordPrompts=1",
            ]
        else:
            cmd += ["-o", "BatchMode=yes"]
        cmd += ["%s@%s" % (SSH_USER, host), command]

        popen_kw = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
        }
        if stdin_data is None:
            devnull = open(os.devnull, "rb")
            popen_kw["stdin"] = devnull
        else:
            popen_kw["stdin"] = subprocess.PIPE
        if hasattr(os, "setsid"):
            # No controlling terminal -> ssh uses SSH_ASKPASS for the password.
            popen_kw["preexec_fn"] = os.setsid

        proc = subprocess.Popen(cmd, **popen_kw)
        out, err = proc.communicate(stdin_data)
        return out or b"", to_text(err or b""), proc.returncode
    except Exception as exc:
        return b"", to_text(str(exc)), 1
    finally:
        if devnull is not None:
            try:
                devnull.close()
            except Exception:
                pass
        if askpass_path and os.path.exists(askpass_path):
            try:
                os.unlink(askpass_path)
            except Exception:
                pass


def ssh_error_text(host, err, rc):
    """Turn an ssh failure into something actionable."""
    err = (err or "").strip()
    low = err.lower()
    hint = ""
    if ("permission denied" in low or "publickey" in low
            or "batch mode" in low or "authentication" in low):
        hint = (
            "\n\nssh could not authenticate as %s@%s.\n"
            "Either type the account password in the Password box above, "
            "or install a key once with:\n    ssh-copy-id %s@%s"
            % (SSH_USER, host, SSH_USER, host))
    elif "could not resolve" in low or "name or service not known" in low:
        hint = "\n\n%s did not resolve from this machine." % host
    elif "connection timed out" in low or "timed out" in low:
        hint = "\n\n%s did not answer within %ds." % (host, SSH_TIMEOUT)
    return (err or ("ssh exited with status %s" % rc)) + hint


# ---------------------------------------------------------------------------
# Remote file operations
# ---------------------------------------------------------------------------
def remote_listdir(host, path, password=""):
    """Return (dirs, files) for a remote directory. Raises IOError on failure."""
    command = (
        "d=" + shq(path) + "; "
        'if [ ! -d "$d" ]; then echo __XQFINDB_NOTDIR__ >&2; exit 3; fi; '
        'cd "$d" && LC_ALL=C ls -1Ap'
    )
    out, err, rc = run_ssh(host, command, password)
    if rc != 0:
        if "__XQFINDB_NOTDIR__" in err:
            raise IOError("Not a directory on %s:\n%s" % (host, path))
        raise IOError(ssh_error_text(host, err, rc))
    dirs, files = [], []
    for name in to_text(out).splitlines():
        if not name or name in ("./", "../"):
            continue
        if name.endswith("/"):
            dirs.append(name[:-1])
        elif name.endswith(("*", "@", "=", "|")) and len(name) > 1:
            files.append(name[:-1])           # ls -F type suffixes
        else:
            files.append(name)
    dirs.sort(key=lambda s: s.lower())
    files.sort(key=lambda s: s.lower())
    return dirs, files


def remote_read(host, path, password=""):
    """Fetch a remote file as bytes. Raises IOError on failure."""
    out, err, rc = run_ssh(
        host, "LC_ALL=C stat -c %s -- " + shq(path), password)
    if rc != 0:
        raise IOError(ssh_error_text(host, err, rc))
    try:
        size = int(to_text(out).strip())
    except ValueError:
        raise IOError("Could not stat %s on %s." % (path, host))
    if size > MAX_FETCH_BYTES:
        raise IOError(
            "%s is %d bytes; xQfinDB refuses to load more than %d."
            % (path, size, MAX_FETCH_BYTES))
    out, err, rc = run_ssh(host, "cat -- " + shq(path), password)
    if rc != 0:
        raise IOError(ssh_error_text(host, err, rc))
    if len(out) != size:
        raise IOError(
            "Short read of %s: expected %d bytes, got %d."
            % (path, size, len(out)))
    return out


def remote_write(host, path, data, password="", backup=True):
    """
    Replace a remote file's contents, keeping its mode/owner.

    Content is staged next to the target and moved into place, so the original
    is never left half-written if the transfer dies.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_line = ""
    if backup:
        backup_line = 'cp -p -- "$src" "$src.bak-%s"\n' % stamp
    script = (
        "set -e\n"
        "orig=" + shq(path) + "\n"
        'src=$(readlink -f -- "$orig" 2>/dev/null || echo "$orig")\n'
        'if [ ! -f "$src" ]; then echo __XQFINDB_MISSING__ >&2; exit 4; fi\n'
        'new="$src.xqfindb-new.$$"\n'
        'cat > "$new"\n'
        'if [ ! -s "$new" ]; then rm -f -- "$new"; '
        'echo __XQFINDB_EMPTY__ >&2; exit 5; fi\n'
        + backup_line +
        'chmod --reference="$src" "$new" 2>/dev/null || true\n'
        'chown --reference="$src" "$new" 2>/dev/null || true\n'
        'mv -f -- "$new" "$src"\n'
        'LC_ALL=C wc -c < "$src"\n'
    )
    out, err, rc = run_ssh(host, script, password, stdin_data=data)
    if rc != 0:
        if "__XQFINDB_MISSING__" in err:
            raise IOError("%s is gone on %s - nothing was written." % (path, host))
        if "__XQFINDB_EMPTY__" in err:
            raise IOError("Transfer to %s arrived empty - nothing was written."
                          % host)
        raise IOError(ssh_error_text(host, err, rc))
    try:
        written = int(to_text(out).strip())
    except ValueError:
        written = -1
    if written != len(data):
        raise IOError(
            "Wrote %s but it is %s bytes on %s, expected %d."
            % (path, written if written >= 0 else "?", host, len(data)))
    return stamp if backup else ""


# ---------------------------------------------------------------------------
# Local file operations
# ---------------------------------------------------------------------------
def local_read(path):
    handle = open(path, "rb")
    try:
        return handle.read()
    finally:
        handle.close()


def local_write(path, data, backup=True):
    """Same guarantees as remote_write: staged write, mode kept, atomic move."""
    real = os.path.realpath(path)
    folder = os.path.dirname(real) or "."
    fd, tmp = tempfile.mkstemp(prefix=".xqfindb-", dir=folder)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    try:
        info = os.stat(real)
        os.chmod(tmp, stat.S_IMODE(info.st_mode))
        try:
            os.chown(tmp, info.st_uid, info.st_gid)
        except OSError:
            pass                                   # not owner; mode still kept
    except OSError:
        pass
    stamp = ""
    try:
        if backup:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(real, real + ".bak-" + stamp)
        os.rename(tmp, real)
    except (IOError, OSError):
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return stamp


# ---------------------------------------------------------------------------
# Byte-exact XML scanning
#
# No XML writer is used anywhere. The file is scanned for element spans, the
# exact offsets of every sn="..." value are recorded, and saving splices new
# text into those offsets only.
# ---------------------------------------------------------------------------
_ATTR_RE = re.compile(r'([A-Za-z_:][-\w:.]*)\s*=\s*(["\'])(.*?)\2', re.S)


_INERT_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>", re.S)


def mask_inert(text):
    """
    Copy of the document with comments, CDATA and processing instructions
    blanked to spaces, keeping the exact same length so every offset still
    lines up with the original.

    Element scanning runs on this copy, so a commented-out or quoted-in-CDATA
    <qfin> is never mistaken for a real one. Attribute values are still read
    from the untouched original at the offsets found here.
    """
    if "<!--" not in text and "<![CDATA[" not in text and "<?" not in text:
        return text
    parts = []
    last = 0
    for match in _INERT_RE.finditer(text):
        parts.append(text[last:match.start()])
        parts.append(" " * (match.end() - match.start()))
        last = match.end()
    parts.append(text[last:])
    return "".join(parts)


def _open_re(name):
    # '<streamer' cannot match '<hlm-streamer'; the lookahead stops '<qfinfoo'.
    return re.compile("<" + re.escape(name) + r"(?=[\s/>])")


def _close_re(name):
    return re.compile("</\\s*" + re.escape(name) + r"\s*>")


def _tag_end(text, start):
    """Offset just past the '>' closing the tag that opens at text[start]."""
    i = start + 1
    n = len(text)
    quote = None
    while i < n:
        char = text[i]
        if quote is not None:
            if char == quote:
                quote = None
        elif char == '"' or char == "'":
            quote = char
        elif char == ">":
            return i + 1
        i += 1
    return -1


def find_elements(text, name, lo=0, hi=None):
    """
    Spans of every <name> element between lo and hi, nesting-aware.

    Returns a list of (start, open_end, body_start, body_end, end).
    Self-closing elements get body_start == body_end == open_end == end.
    """
    if hi is None:
        hi = len(text)
    opener = _open_re(name)
    closer = _close_re(name)
    found = []
    pos = lo
    while pos < hi:
        match = opener.search(text, pos, hi)
        if not match:
            break
        start = match.start()
        open_end = _tag_end(text, start)
        if open_end < 0 or open_end > hi:
            break
        if text[open_end - 2:open_end - 1] == "/":
            found.append((start, open_end, open_end, open_end, open_end))
            pos = open_end
            continue
        depth = 1
        scan = open_end
        body_end = elem_end = -1
        while depth > 0 and scan < hi:
            nxt_open = opener.search(text, scan, hi)
            nxt_close = closer.search(text, scan, hi)
            if nxt_close is None:
                break
            if nxt_open is not None and nxt_open.start() < nxt_close.start():
                inner_end = _tag_end(text, nxt_open.start())
                if inner_end < 0:
                    break
                if text[inner_end - 2:inner_end - 1] != "/":
                    depth += 1
                scan = inner_end
                continue
            depth -= 1
            if depth == 0:
                body_end = nxt_close.start()
                elem_end = nxt_close.end()
            scan = nxt_close.end()
        if elem_end < 0:
            break
        found.append((start, open_end, open_end, body_end, elem_end))
        pos = elem_end
    return found


def tag_attrs(text, start, open_end):
    """name -> (value, quote, value_start, value_end) for one opening tag."""
    inner = text[start:open_end]
    attrs = {}
    for match in _ATTR_RE.finditer(inner):
        key = match.group(1)
        if key in attrs:
            continue
        attrs[key] = (match.group(3), match.group(2),
                      start + match.start(3), start + match.end(3))
    return attrs


_ENTITY_RE = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|amp|lt|gt|quot|apos);")
_ENTITY_MAP = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def decode_attr(value):
    """
    Attribute text as the qfin software sees it.

    The scanner reads raw file bytes, so an sn written as "A&amp;B" arrives
    here escaped. Decoding keeps the displayed serial identical to the parsed
    one; escape_attr puts it back when the cell is edited. Plain digits - every
    real serial - pass through untouched.
    """
    if "&" not in value:
        return value

    def sub(match):
        body = match.group(1)
        if body[0] != "#":
            return _ENTITY_MAP[body]
        try:
            code = int(body[2:], 16) if body[1] in "xX" else int(body[1:])
        except ValueError:
            return match.group(0)
        if 0 < code < 0x110000:
            try:
                return unichr(code).encode("utf-8")
            except (ValueError, UnicodeEncodeError):
                return match.group(0)
        return match.group(0)

    return _ENTITY_RE.sub(sub, value)


def escape_attr(value, quote):
    """Keep the document well-formed whatever gets typed into a cell."""
    out = value.replace("&", "&amp;").replace("<", "&lt;")
    if quote == '"':
        out = out.replace('"', "&quot;")
    else:
        out = out.replace("'", "&apos;")
    return out


class QfinCell(object):
    """One editable sn="..." value, pinned to its byte range in the file."""

    __slots__ = ("start", "end", "quote", "original", "value", "attrs")

    def __init__(self, start, end, quote, original, attrs):
        self.start = start
        self.end = end
        self.quote = quote
        self.original = original
        self.value = original
        self.attrs = attrs

    @property
    def changed(self):
        return self.value != self.original


class QfinStreamer(object):
    def __init__(self, number, vessel, attrs):
        self.number = number
        self.vessel = vessel
        self.attrs = attrs
        self.cells = []

    def heading(self):
        return "S%d" % self.number

    def describe(self):
        bits = []
        if self.vessel:
            bits.append(self.vessel)
        if "crossline-offset" in self.attrs:
            bits.append("crossline %s" % self.attrs["crossline-offset"])
        return "  ".join(bits)


class QfinDocument(object):
    """Parsed view of one scenario file. Holds the original bytes verbatim."""

    def __init__(self, raw, display_path, source):
        self.raw = raw
        self.scan = mask_inert(raw)      # same length; inert regions blanked
        self.display_path = display_path
        self.source = source              # LOCAL_LABEL or a server name
        self.scenario = ""
        self.vessels = []
        self.streamers = []
        self.notes = []
        self.skipped = 0            # <qfin> elements carrying no sn attribute
        self._parse()

    # -- parsing ----------------------------------------------------------
    def _parse(self):
        raw, scan = self.raw, self.scan
        for span in find_elements(scan, "scenario")[:1]:
            name = tag_attrs(raw, span[0], span[1]).get("name")
            if name:
                self.scenario = decode_attr(name[0])

        lo, hi = 0, len(raw)
        equipment = find_elements(scan, "equipment")
        if equipment:
            lo, hi = equipment[0][2], equipment[0][3]
        else:
            self.notes.append("No <equipment> block; scanned the whole file.")

        scopes = []
        for span in find_elements(scan, "vessel", lo, hi):
            name = tag_attrs(raw, span[0], span[1]).get("name")
            name = decode_attr(name[0]) if name else ""
            self.vessels.append(name)
            scopes.append((name, span[2], span[3]))
        if not scopes:
            scopes = [("", lo, hi)]

        for vessel, s_lo, s_hi in scopes:
            for span in find_elements(scan, "streamer", s_lo, s_hi):
                self._add_streamer(vessel, span)

        if not self.streamers and (lo, hi) != (0, len(raw)):
            # Streamers sit outside <equipment> in this file - widen and retry.
            for span in find_elements(scan, "streamer", 0, len(scan)):
                self._add_streamer("", span)
            if self.streamers:
                self.notes.append(
                    "Streamers found outside <equipment>; scanned whole file.")

        if self.skipped:
            self.notes.append(
                "%d <qfin> element(s) have no sn attribute and are not shown."
                % self.skipped)

        if not self.streamers:
            # No streamer grouping at all: show every qfin in one column.
            loose = find_elements(scan, "qfin", 0, len(scan))
            if loose:
                self.notes.append(
                    "No <streamer> elements found; all qfins shown in one column.")
                streamer = QfinStreamer(1, "", {})
                for span in loose:
                    cell = self._make_cell(span)
                    if cell is not None:
                        streamer.cells.append(cell)
                if streamer.cells:
                    self.streamers.append(streamer)

    def _add_streamer(self, vessel, span):
        raw = self.raw
        attrs = dict((k, decode_attr(v[0]))
                     for k, v in tag_attrs(raw, span[0], span[1]).items())
        streamer = QfinStreamer(len(self.streamers) + 1, vessel, attrs)
        for qspan in find_elements(self.scan, "qfin", span[2], span[3]):
            cell = self._make_cell(qspan)
            if cell is not None:
                streamer.cells.append(cell)
        self.streamers.append(streamer)

    def _make_cell(self, span):
        attrs = tag_attrs(self.raw, span[0], span[1])
        if "sn" not in attrs:
            self.skipped += 1       # nothing to edit; counted so it is not silent
            return None
        value, quote, start, end = attrs["sn"]
        plain = dict((k, decode_attr(v[0])) for k, v in attrs.items())
        return QfinCell(start, end, quote, decode_attr(value), plain)

    # -- queries ----------------------------------------------------------
    def row_count(self):
        return max([len(s.cells) for s in self.streamers] or [0])

    def qfin_count(self):
        return sum(len(s.cells) for s in self.streamers)

    def changes(self):
        """[(streamer, row_index, cell)] for every edited cell, in table order."""
        out = []
        for streamer in self.streamers:
            for row, cell in enumerate(streamer.cells):
                if cell.changed:
                    out.append((streamer, row, cell))
        return out

    def revert(self):
        for streamer in self.streamers:
            for cell in streamer.cells:
                cell.value = cell.original

    def commit(self):
        """Edited values become the new baseline after a successful save."""
        for streamer in self.streamers:
            for cell in streamer.cells:
                cell.original = cell.value

    # -- output -----------------------------------------------------------
    def build_bytes(self):
        """
        Original bytes with only the changed sn values spliced in.

        Edits are applied back-to-front so earlier offsets stay valid.
        """
        edits = [(c.start, c.end, escape_attr(c.value, c.quote))
                 for _, _, c in self.changes()]
        if not edits:
            return self.raw, 0
        edits.sort(key=lambda item: item[0], reverse=True)
        out = self.raw
        for start, end, text in edits:
            out = out[:start] + text + out[end:]
        return out, len(edits)

    def problems(self):
        """Sanity checks reported before saving; none of them block the save."""
        issues = []
        blanks = []
        odd = []
        seen = {}
        for streamer in self.streamers:
            for row, cell in enumerate(streamer.cells):
                value = cell.value
                where = "%s qfin %d" % (streamer.heading(), row + 1)
                if not value.strip():
                    blanks.append(where)
                    continue
                if not re.match(r"^[A-Za-z0-9._-]+$", value):
                    odd.append("%s = %s" % (where, value))
                if value.strip("0") == "":
                    continue                       # 0 marks "no fin fitted"
                seen.setdefault(value, []).append(where)
        if blanks:
            issues.append("Empty serial number: " + ", ".join(blanks[:8])
                          + (" ..." if len(blanks) > 8 else ""))
        if odd:
            issues.append("Unusual characters: " + "; ".join(odd[:8])
                          + (" ..." if len(odd) > 8 else ""))
        dupes = [(v, w) for v, w in seen.items() if len(w) > 1]
        dupes.sort()
        for value, where in dupes[:8]:
            issues.append("Serial %s used %d times: %s"
                          % (value, len(where), ", ".join(where)))
        if len(dupes) > 8:
            issues.append("... and %d more repeated serials." % (len(dupes) - 8))
        return issues


# ---------------------------------------------------------------------------
# Remote file browser
# ---------------------------------------------------------------------------
class RemoteBrowser(object):
    """Pick a file on navsolve1/navsolve2 over ssh. Any extension is listed."""

    def __init__(self, parent, host, password="", start_dir=REMOTE_DEFAULT_DIR):
        self.host = host
        self.password = password
        self.path = start_dir or "/"
        self.result = None
        self.dirs = []
        self.files = []
        self._busy = False

        self.win = tk.Toplevel(parent)
        self.win.title("xQfinDB - browse %s@%s" % (SSH_USER, host))
        self.win.configure(bg=GUI_BG)
        self.win.geometry("720x460")
        self.win.minsize(520, 340)
        self.win.transient(parent.winfo_toplevel())
        self.runner = BgRunner(self.win)

        head = tk.Frame(self.win, bg=GUI_BG)
        head.pack(fill=tk.X, padx=8, pady=(8, 2))
        tk.Label(head, text="Path:", bg=GUI_BG, fg=TEXT_FG,
                 font=FONT_MAIN).pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value=self.path)
        entry = tk.Entry(head, textvariable=self.path_var, bg=ENTRY_BG,
                         fg=TEXT_FG, font=FONT_MAIN, relief=tk.SUNKEN, bd=1)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        entry.bind("<Return>", lambda e: self._goto(self.path_var.get().strip()))
        tk.Button(head, text="Go", bg=BTN_BG, activebackground=BTN_ACTIVE,
                  fg=HEADER_FG, font=FONT_MAIN, relief=tk.RAISED, bd=2,
                  command=lambda: self._goto(self.path_var.get().strip())
                  ).pack(side=tk.LEFT, padx=2)
        tk.Button(head, text="Up", bg=BTN_BG, activebackground=BTN_ACTIVE,
                  fg=HEADER_FG, font=FONT_MAIN, relief=tk.RAISED, bd=2,
                  command=self._up).pack(side=tk.LEFT, padx=2)

        body = tk.Frame(self.win, bg=GUI_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.listbox = tk.Listbox(
            body, bg=ENTRY_BG, fg=TEXT_FG, font=FONT_CELL,
            selectmode=tk.BROWSE, activestyle="none",
            highlightthickness=1, relief=tk.SUNKEN, bd=1)
        scroll = ttk.Scrollbar(body, orient=tk.VERTICAL,
                               command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind("<Double-Button-1>", lambda e: self._activate())
        self.listbox.bind("<Return>", lambda e: self._activate())

        foot = tk.Frame(self.win, bg=GUI_BG)
        foot.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.status = tk.Label(foot, text="", bg=GUI_BG, fg=STATUS_FG,
                               font=FONT_SMALL, anchor="w")
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(foot, text="Cancel", bg=BTN_BG, activebackground=BTN_ACTIVE,
                  fg=HEADER_FG, font=FONT_MAIN, relief=tk.RAISED, bd=2,
                  command=self._cancel).pack(side=tk.RIGHT, padx=2)
        tk.Button(foot, text="Open", bg=BTN_BG, activebackground=BTN_ACTIVE,
                  fg=HEADER_FG, font=FONT_BOLD, relief=tk.RAISED, bd=2,
                  command=self._activate).pack(side=tk.RIGHT, padx=2)

        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self.win.bind("<Escape>", lambda e: self._cancel())
        self._goto(self.path)

    # -- navigation -------------------------------------------------------
    def _goto(self, path):
        if self._busy:
            return
        path = path or "/"
        if not path.startswith("/"):
            path = "/" + path
        path = os.path.normpath(path)
        self._busy = True
        self.path_var.set(path)
        self.status.configure(fg=STATUS_FG, text="Listing ... %s"
                              % ssh_display(self.host, "cd %s && ls -1Ap"
                                            % shq(path)))
        self.listbox.delete(0, tk.END)
        self.listbox.insert(tk.END, "  working ...")
        host, password = self.host, self.password

        def work():
            return remote_listdir(host, path, password)

        def done(result, err):
            self._busy = False
            self.listbox.delete(0, tk.END)
            if err is not None:
                self.status.configure(fg=WARN_FG, text=str(err).splitlines()[0])
                messagebox.showerror("xQfinDB - SSH", str(err), parent=self.win)
                return
            self.path = path
            self.dirs, self.files = result
            for name in self.dirs:
                self.listbox.insert(tk.END, "[DIR]  " + name)
            for name in self.files:
                self.listbox.insert(tk.END, "       " + name)
            if not self.dirs and not self.files:
                self.status.configure(fg=STATUS_FG, text="%s is empty." % path)
            else:
                self.status.configure(
                    fg=STATUS_FG,
                    text="%d folders, %d files in %s"
                         % (len(self.dirs), len(self.files), path))
                self.listbox.selection_set(0)

        self.runner.submit(work, done)

    def _up(self):
        parent = os.path.dirname(self.path.rstrip("/")) or "/"
        self._goto(parent)

    def _activate(self):
        if self._busy:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        index = int(sel[0])
        if index < len(self.dirs):
            self._goto(os.path.join(self.path, self.dirs[index]))
            return
        index -= len(self.dirs)
        if index >= len(self.files):
            return
        self.result = os.path.join(self.path, self.files[index])
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        self.runner.stop()
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    def show(self):
        self.win.grab_set()
        self.win.wait_window()
        return self.result


# ---------------------------------------------------------------------------
# Ruled grid with a single-cell cursor
#
# ttk.Treeview on Tk 8.6 selects whole rows and cannot tag individual cells or
# draw rules, so the table is a Canvas: one text item per serial, ruled lines,
# and frozen header/row-number strips that scroll with the body.
# ---------------------------------------------------------------------------
class QfinGrid(tk.Frame):
    """Spreadsheet-style grid of qfin serial numbers, one column per streamer."""

    def __init__(self, master, on_select=None, on_change=None, on_status=None):
        tk.Frame.__init__(self, master, bg=GUI_BG, relief=tk.SUNKEN, bd=1)
        self.on_select = on_select
        self.on_change = on_change
        self.on_status = on_status
        self.doc = None
        self.rows = 0
        self.cols = 0
        self.sel = None                 # (row, col) - exactly one cell, or None
        self._text = {}                 # (row, col) -> canvas text id
        self._mark = {}                 # (row, col) -> edited-cell backing rect
        self._hdr_bg = {}
        self._hdr_tx = {}
        self._rh_bg = {}
        self._rh_tx = {}
        self._hdr_cur = None
        self._rh_cur = None
        self._sel_item = None
        self._found_item = None
        self._editor = None
        self._edit_win = None
        self._edit_cell = None
        self._build()

    # -- widgets ----------------------------------------------------------
    def _build(self):
        canvas_kw = {"highlightthickness": 0, "bd": 0}
        self.corner = tk.Canvas(self, width=ROWHDR_W, height=CELL_H,
                                bg=BTN_BG, **canvas_kw)
        self.hdr = tk.Canvas(self, height=CELL_H, bg=GUI_BG, **canvas_kw)
        self.rowhdr = tk.Canvas(self, width=ROWHDR_W, bg=GUI_BG, **canvas_kw)
        self.body = tk.Canvas(self, bg=ENTRY_BG, takefocus=1, **canvas_kw)
        self.vsb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._yview)
        self.hsb = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self._xview)
        self.body.configure(xscrollcommand=self._xscrolled,
                            yscrollcommand=self._yscrolled)

        self.corner.grid(row=0, column=0, sticky="nsew")
        self.hdr.grid(row=0, column=1, sticky="ew")
        self.rowhdr.grid(row=1, column=0, sticky="ns")
        self.body.grid(row=1, column=1, sticky="nsew")
        self.vsb.grid(row=1, column=2, sticky="ns")
        self.hsb.grid(row=2, column=1, sticky="ew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(1, weight=1)

        self.body.bind("<Button-1>", self._on_click)
        self.body.bind("<Double-Button-1>", self._on_double)
        self.body.bind("<Key>", self._on_key)
        wheel = [("<Button-4>", (0, -3)), ("<Button-5>", (0, 3)),
                 ("<Button-6>", (-3, 0)), ("<Button-7>", (3, 0))]
        for widget in (self.body, self.rowhdr, self.hdr):
            for sequence, (dx, dy) in wheel:
                try:
                    widget.bind(sequence,
                                lambda e, a=dx, b=dy: self._wheel(a, b))
                except tk.TclError:
                    pass       # tilt-wheel buttons 6/7 are not on every Tk build
            widget.bind("<MouseWheel>", self._on_wheel_win)

    # -- scrolling --------------------------------------------------------
    def _xview(self, *args):
        self.body.xview(*args)

    def _yview(self, *args):
        self.body.yview(*args)

    def _xscrolled(self, lo, hi):
        self.hsb.set(lo, hi)
        self.hdr.xview_moveto(lo)

    def _yscrolled(self, lo, hi):
        self.vsb.set(lo, hi)
        self.rowhdr.yview_moveto(lo)

    def _wheel(self, dx, dy):
        if dy:
            self.body.yview_scroll(dy, "units")
        if dx:
            self.body.xview_scroll(dx, "units")
        return "break"

    def _on_wheel_win(self, event):
        step = -3 if event.delta > 0 else 3
        return self._wheel(0, step)

    def _page(self):
        return max(1, int(self.body.winfo_height() // CELL_H) - 1)

    def _status(self, text, warn=False):
        if self.on_status:
            self.on_status(text, warn)

    # -- building ---------------------------------------------------------
    def set_document(self, doc):
        self.end_edit(commit=False)
        self.doc = doc
        for canvas in (self.body, self.hdr, self.rowhdr, self.corner):
            canvas.delete("all")
        self._text = {}
        self._mark = {}
        self._hdr_bg = {}
        self._hdr_tx = {}
        self._rh_bg = {}
        self._rh_tx = {}
        self._hdr_cur = self._rh_cur = None
        self._sel_item = self._found_item = None
        self.sel = None
        self.rows = doc.row_count() if doc is not None else 0
        self.cols = len(doc.streamers) if doc is not None else 0
        if not self.rows or not self.cols:
            self._set_scrollregions()
            return

        width = self.cols * CELL_W
        height = self.rows * CELL_H

        # Streamers with fewer qfins get a shaded, uneditable tail.
        for col, streamer in enumerate(doc.streamers):
            if len(streamer.cells) < self.rows:
                self.body.create_rectangle(
                    col * CELL_W, len(streamer.cells) * CELL_H,
                    (col + 1) * CELL_W, height,
                    fill=BLANK_BG, outline="", tags=("bg",))

        for col in range(self.cols + 1):
            x = col * CELL_W
            self.body.create_line(x, 0, x, height, fill=GRID_LINE, tags=("grid",))
        for row in range(self.rows + 1):
            y = row * CELL_H
            self.body.create_line(0, y, width, y, fill=GRID_LINE, tags=("grid",))

        for col, streamer in enumerate(doc.streamers):
            for row, cell in enumerate(streamer.cells):
                self._text[(row, col)] = self.body.create_text(
                    col * CELL_W + CELL_W // 2, row * CELL_H + CELL_H // 2,
                    text=cell.value, font=FONT_CELL, fill=TEXT_FG,
                    tags=("celltext",))

        for col, streamer in enumerate(doc.streamers):
            self._hdr_bg[col] = self.hdr.create_rectangle(
                col * CELL_W, 0, (col + 1) * CELL_W, CELL_H,
                fill=BTN_BG, outline=GRID_LINE)
            self._hdr_tx[col] = self.hdr.create_text(
                col * CELL_W + CELL_W // 2, CELL_H // 2,
                text=streamer.heading(), font=FONT_BOLD, fill=HEADER_FG)

        for row in range(self.rows):
            self._rh_bg[row] = self.rowhdr.create_rectangle(
                0, row * CELL_H, ROWHDR_W, (row + 1) * CELL_H,
                fill=BTN_BG, outline=GRID_LINE)
            self._rh_tx[row] = self.rowhdr.create_text(
                ROWHDR_W // 2, row * CELL_H + CELL_H // 2,
                text=str(row + 1), font=FONT_SMALL, fill=HEADER_FG)

        self.corner.create_rectangle(0, 0, ROWHDR_W, CELL_H, fill=BTN_BG,
                                     outline=GRID_LINE)
        self.corner.create_text(ROWHDR_W // 2, CELL_H // 2, text="Qfin",
                                font=FONT_BOLD, fill=HEADER_FG)

        for col, streamer in enumerate(doc.streamers):
            for row, cell in enumerate(streamer.cells):
                if cell.changed:
                    self._mark_changed(row, col, True)

        self._set_scrollregions()
        self.select(0, 0)

    def _set_scrollregions(self):
        width = self.cols * CELL_W
        height = self.rows * CELL_H
        self.body.configure(scrollregion=(0, 0, width, height))
        self.hdr.configure(scrollregion=(0, 0, width, CELL_H))
        self.rowhdr.configure(scrollregion=(0, 0, ROWHDR_W, height))

    # -- selection --------------------------------------------------------
    def select(self, row, col, notify=True, center=False):
        """Move the one-cell cursor. Returns False if the cell does not exist."""
        if self.doc is None or not (0 <= row < self.rows):
            return False
        if not (0 <= col < self.cols):
            return False
        self.sel = (row, col)
        x0, y0 = col * CELL_W, row * CELL_H
        box = (x0 + 1, y0 + 1, x0 + CELL_W, y0 + CELL_H)
        if self._sel_item is None:
            self._sel_item = self.body.create_rectangle(
                *box, outline=SEL_OUTLINE, width=2, fill="", tags=("sel",))
        else:
            self.body.coords(self._sel_item, *box)
        self.body.tag_raise(self._sel_item)
        self._highlight_headers(row, col)
        self._see(row, col, center)
        if notify and self.on_select:
            self.on_select(row, col)
        return True

    def _highlight_headers(self, row, col):
        if self._hdr_cur is not None and self._hdr_cur in self._hdr_bg:
            self.hdr.itemconfigure(self._hdr_bg[self._hdr_cur], fill=BTN_BG)
            self.hdr.itemconfigure(self._hdr_tx[self._hdr_cur], fill=HEADER_FG)
        if col in self._hdr_bg:
            self.hdr.itemconfigure(self._hdr_bg[col], fill=HDR_SEL_BG)
            self.hdr.itemconfigure(self._hdr_tx[col], fill=HDR_SEL_FG)
        self._hdr_cur = col
        if self._rh_cur is not None and self._rh_cur in self._rh_bg:
            self.rowhdr.itemconfigure(self._rh_bg[self._rh_cur], fill=BTN_BG)
            self.rowhdr.itemconfigure(self._rh_tx[self._rh_cur], fill=HEADER_FG)
        if row in self._rh_bg:
            self.rowhdr.itemconfigure(self._rh_bg[row], fill=HDR_SEL_BG)
            self.rowhdr.itemconfigure(self._rh_tx[row], fill=HDR_SEL_FG)
        self._rh_cur = row

    def _see(self, row, col, center=False):
        try:
            self.update_idletasks()
        except tk.TclError:
            return
        view_w = self.body.winfo_width()
        view_h = self.body.winfo_height()
        total_w = float(max(self.cols * CELL_W, 1))
        total_h = float(max(self.rows * CELL_H, 1))
        if view_w <= 1 or view_h <= 1:
            return
        x0, x1 = col * CELL_W, (col + 1) * CELL_W
        y0, y1 = row * CELL_H, (row + 1) * CELL_H
        left = self.body.canvasx(0)
        top = self.body.canvasy(0)
        if center:
            self.body.xview_moveto(_clamp((x0 - view_w / 2.0) / total_w))
            self.body.yview_moveto(_clamp((y0 - view_h / 2.0) / total_h))
            return
        if x0 < left:
            self.body.xview_moveto(_clamp(x0 / total_w))
        elif x1 > left + view_w:
            self.body.xview_moveto(_clamp((x1 - view_w) / total_w))
        if y0 < top:
            self.body.yview_moveto(_clamp(y0 / total_h))
        elif y1 > top + view_h:
            self.body.yview_moveto(_clamp((y1 - view_h) / total_h))

    def flash(self, row, col):
        """Green backing behind a search hit, cleared on the next search."""
        self.clear_flash()
        x0, y0 = col * CELL_W, row * CELL_H
        self._found_item = self.body.create_rectangle(
            x0 + 1, y0 + 1, x0 + CELL_W, y0 + CELL_H,
            fill=FOUND_BG, outline="", tags=("bg",))
        try:
            self.body.tag_lower(self._found_item, "grid")
        except tk.TclError:
            pass

    def clear_flash(self):
        if self._found_item is not None:
            try:
                self.body.delete(self._found_item)
            except tk.TclError:
                pass
            self._found_item = None

    # -- values -----------------------------------------------------------
    def cell(self, row, col):
        if self.doc is None or not (0 <= col < self.cols):
            return None
        cells = self.doc.streamers[col].cells
        return cells[row] if 0 <= row < len(cells) else None

    def set_value(self, row, col, value):
        cell = self.cell(row, col)
        if cell is None or cell.value == value:
            return False
        cell.value = value
        self.body.itemconfigure(self._text[(row, col)], text=value)
        self._mark_changed(row, col, cell.changed)
        if self.on_change:
            self.on_change(row, col)
        return True

    def _mark_changed(self, row, col, on):
        item = self._mark.pop((row, col), None)
        if item is not None:
            try:
                self.body.delete(item)
            except tk.TclError:
                pass
        if not on:
            return
        x0, y0 = col * CELL_W, row * CELL_H
        item = self.body.create_rectangle(
            x0 + 1, y0 + 1, x0 + CELL_W, y0 + CELL_H,
            fill=CHANGED_BG, outline="", tags=("bg",))
        self._mark[(row, col)] = item
        try:
            self.body.tag_lower(item, "grid")
        except tk.TclError:
            pass

    def clear_changed_marks(self):
        for item in self._mark.values():
            try:
                self.body.delete(item)
            except tk.TclError:
                pass
        self._mark = {}

    # -- editing ----------------------------------------------------------
    def begin_edit(self, row=None, col=None):
        self.end_edit(commit=True)
        if self.doc is None:
            return
        if row is None or col is None:
            if self.sel is None:
                return
            row, col = self.sel
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return
        streamer = self.doc.streamers[col]
        if row >= len(streamer.cells):
            self._status("%s has no qfin at position %d - nothing to edit."
                         % (streamer.heading(), row + 1), True)
            return
        self.select(row, col)
        entry = tk.Entry(self.body, bg=EDIT_BG, fg=TEXT_FG, justify="center",
                         font=FONT_CELL, relief=tk.SOLID, bd=1,
                         highlightthickness=0)
        entry.insert(0, streamer.cells[row].value)
        entry.select_range(0, tk.END)
        window = self.body.create_window(
            col * CELL_W, row * CELL_H, window=entry, anchor="nw",
            width=CELL_W, height=CELL_H)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self.move_edit(0, 1))
        entry.bind("<KP_Enter>", lambda e: self.move_edit(0, 1))
        entry.bind("<Tab>", lambda e: self.move_edit(1, 0))
        entry.bind("<ISO_Left_Tab>", lambda e: self.move_edit(-1, 0))
        entry.bind("<Down>", lambda e: self.move_edit(0, 1))
        entry.bind("<Up>", lambda e: self.move_edit(0, -1))
        entry.bind("<Escape>", lambda e: self.end_edit(commit=False))
        entry.bind("<FocusOut>", lambda e: self.end_edit(commit=True))
        self._editor = entry
        self._edit_win = window
        self._edit_cell = (row, col)

    def end_edit(self, commit=True):
        entry = self._editor
        if entry is None:
            return "break"
        self._editor = None                 # guard against FocusOut re-entry
        cell = self._edit_cell
        window = self._edit_win
        self._edit_cell = None
        self._edit_win = None
        try:
            typed = entry.get()
        except tk.TclError:
            typed = None
        for drop in (lambda: self.body.delete(window), entry.destroy):
            try:
                drop()
            except tk.TclError:
                pass
        try:
            self.body.focus_set()
        except tk.TclError:
            pass
        if commit and cell is not None and typed is not None:
            self.set_value(cell[0], cell[1], typed.strip())
        return "break"

    def move_edit(self, dx, dy):
        cell = self._edit_cell
        self.end_edit(commit=True)
        if cell is None:
            return "break"
        row, col = cell[0] + dy, cell[1] + dx
        if col >= self.cols:
            col, row = 0, row + 1
        elif col < 0:
            col, row = self.cols - 1, row - 1
        if 0 <= row < self.rows:
            self.begin_edit(row, col)
        return "break"

    # -- input ------------------------------------------------------------
    def _cell_at(self, event):
        x = self.body.canvasx(event.x)
        y = self.body.canvasy(event.y)
        if x < 0 or y < 0:
            return None
        row, col = int(y // CELL_H), int(x // CELL_W)
        if row >= self.rows or col >= self.cols:
            return None
        return row, col

    def _on_click(self, event):
        self.end_edit(commit=True)
        self.body.focus_set()
        where = self._cell_at(event)
        if where is not None:
            self.select(where[0], where[1])
        return "break"

    def _on_double(self, event):
        where = self._cell_at(event)
        if where is not None:
            self.begin_edit(where[0], where[1])
        return "break"

    def _on_key(self, event):
        if self._editor is not None or self.sel is None:
            return None
        row, col = self.sel
        keysym = event.keysym
        moves = {
            "Up": (row - 1, col), "Down": (row + 1, col),
            "Left": (row, col - 1), "Right": (row, col + 1),
            "Home": (row, 0), "End": (row, self.cols - 1),
            "Prior": (max(0, row - self._page()), col),
            "Next": (min(self.rows - 1, row + self._page()), col),
        }
        if keysym in moves:
            self.select(*moves[keysym])
            return "break"
        if keysym in ("Return", "KP_Enter", "F2"):
            self.begin_edit()
            return "break"
        char = event.char
        if char and len(char) == 1 and 32 <= ord(char) < 127:
            self.begin_edit()
            if self._editor is not None:
                self._editor.delete(0, tk.END)
                self._editor.insert(0, char)
            return "break"
        return None


def _clamp(value):
    return max(0.0, min(1.0, value))


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------
class XQfinDBPanel(tk.Frame):
    """Embeddable panel: the whole tool lives here, no Tk root of its own."""

    def __init__(self, master):
        tk.Frame.__init__(self, master, bg=GUI_BG)
        self.doc = None
        self.file_path = ""
        self.runner = BgRunner(self)
        self._busy = False
        self._loaded_host = ""
        self._find_query = None
        self._find_hits = []
        self._find_exact = False
        self._find_index = -1
        self.settings_path = default_settings_file()
        self._settings = load_settings(self.settings_path)
        self._local_dir = self._settings.get("local_dir") or (
            REMOTE_DEFAULT_DIR if os.path.isdir(REMOTE_DEFAULT_DIR)
            else os.path.expanduser("~"))
        self._remote_dir = self._settings.get("remote_dir") or REMOTE_DEFAULT_DIR

        self._build_header()
        self._build_table()
        self._build_footer()

        remembered = self._settings.get("last_server")
        if remembered in ([LOCAL_LABEL] + SSH_SERVERS):
            self.server_var.set(remembered)
        self.backup_var.set(1 if self._settings.get("backup", 1) else 0)
        self._on_server_change()
        self._set_status("Pick a server, then Browse to a Qfin config file.")
        self.bind("<Destroy>", self._on_destroy)
        # Let the panel map before reopening, so the grid can size itself.
        self.after(120, self._restore_last)

    # -- construction -----------------------------------------------------
    def _button(self, parent, text, command, bold=False):
        return tk.Button(
            parent, text=text, command=command, bg=BTN_BG,
            activebackground=BTN_ACTIVE, fg=HEADER_FG,
            font=FONT_BOLD if bold else FONT_MAIN,
            relief=tk.RAISED, bd=2, padx=8)

    def _build_header(self):
        title_row = tk.Frame(self, bg=GUI_BG)
        title_row.pack(fill=tk.X, padx=8, pady=(8, 2))
        tk.Label(title_row, text="xQfinDB  -  Qfin Serial Number Editor",
                 bg=GUI_BG, fg=HEADER_FG, font=FONT_TITLE).pack(side=tk.LEFT)

        ctrl = tk.Frame(self, bg=GUI_BG)
        ctrl.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(ctrl, text="SSH Server:", bg=GUI_BG, fg=TEXT_FG,
                 font=FONT_MAIN).pack(side=tk.LEFT)
        self.server_var = tk.StringVar(value=LOCAL_LABEL)
        self.server_box = ttk.Combobox(
            ctrl, textvariable=self.server_var, state="readonly", width=20,
            values=[LOCAL_LABEL] + SSH_SERVERS)
        self.server_box.pack(side=tk.LEFT, padx=(4, 10))
        self.server_box.bind("<<ComboboxSelected>>",
                             lambda e: self._on_server_change())

        self.pw_label = tk.Label(ctrl, text="Password:", bg=GUI_BG, fg=TEXT_FG,
                                 font=FONT_MAIN)
        self.pw_var = tk.StringVar()
        self.pw_entry = tk.Entry(ctrl, textvariable=self.pw_var, show="*",
                                 width=14, bg=ENTRY_BG, fg=TEXT_FG,
                                 font=FONT_MAIN, relief=tk.SUNKEN, bd=1)
        self.pw_hint = tk.Label(ctrl, text="(blank = use ssh key)", bg=GUI_BG,
                                fg=STATUS_FG, font=FONT_SMALL)

        self._button(ctrl, "Browse...", self._on_browse, bold=True).pack(
            side=tk.RIGHT, padx=2)
        self.reload_btn = self._button(ctrl, "Reload", self._on_reload)
        self.reload_btn.pack(side=tk.RIGHT, padx=2)

        cfg = tk.Frame(self, bg=GUI_BG)
        cfg.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(cfg, text="Config:", bg=GUI_BG, fg=TEXT_FG,
                 font=FONT_MAIN).pack(side=tk.LEFT)
        self.config_var = tk.StringVar(value=self.settings_path)
        self._button(cfg, "Browse/Select", self._on_config_browse).pack(
            side=tk.RIGHT, padx=2)
        config_entry = tk.Entry(cfg, textvariable=self.config_var, bg=ENTRY_BG,
                                fg=TEXT_FG, font=FONT_SMALL, relief=tk.SUNKEN,
                                bd=1)
        config_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        config_entry.bind("<Return>",
                          lambda e: self._apply_config_path(self.config_var.get()))
        config_entry.bind("<KP_Enter>",
                          lambda e: self._apply_config_path(self.config_var.get()))
        self.config_entry = config_entry

        info = tk.Frame(self, bg=GUI_BG)
        info.pack(fill=tk.X, padx=8, pady=(2, 4))
        self.file_label = tk.Label(info, text="File:  (none loaded)", bg=GUI_BG,
                                   fg=HEADER_FG, font=FONT_BOLD, anchor="w")
        self.file_label.pack(fill=tk.X)
        self.meta_label = tk.Label(info, text="", bg=GUI_BG, fg=STATUS_FG,
                                   font=FONT_SMALL, anchor="w")
        self.meta_label.pack(fill=tk.X)

    def _build_table(self):
        find = tk.Frame(self, bg=GUI_BG)
        find.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Label(find, text="Find serial:", bg=GUI_BG, fg=TEXT_FG,
                 font=FONT_MAIN).pack(side=tk.LEFT)
        self.find_var = tk.StringVar()
        entry = tk.Entry(find, textvariable=self.find_var, width=14,
                         bg=ENTRY_BG, fg=TEXT_FG, font=FONT_MAIN,
                         relief=tk.SUNKEN, bd=1)
        entry.pack(side=tk.LEFT, padx=4)
        entry.bind("<Return>", lambda e: self._on_find())
        entry.bind("<KP_Enter>", lambda e: self._on_find())
        self.find_entry = entry
        self._button(find, "Find", self._on_find).pack(side=tk.LEFT, padx=2)
        tk.Label(find, text="press again for the next match", bg=GUI_BG,
                 fg=STATUS_FG, font=FONT_SMALL).pack(side=tk.LEFT, padx=6)

        self.grid_view = QfinGrid(
            self, on_select=self._on_cell_select,
            on_change=self._on_cell_change,
            on_status=lambda text, warn: self._set_status(text, warn=warn))
        self.grid_view.pack(fill=tk.BOTH, expand=True, padx=8, pady=2)

    def _build_footer(self):
        # Status gets its own full-width row so long cell details are not
        # clipped by the buttons.
        self.status_label = tk.Label(self, text="", bg=GUI_BG, fg=STATUS_FG,
                                     font=FONT_SMALL, anchor="w")
        self.status_label.pack(fill=tk.X, padx=8, pady=(4, 0))

        foot = tk.Frame(self, bg=GUI_BG)
        foot.pack(fill=tk.X, padx=8, pady=(2, 8))

        self._button(foot, "Save", self._on_save, bold=True).pack(
            side=tk.RIGHT, padx=2)
        self._button(foot, "Revert All", self._on_revert).pack(
            side=tk.RIGHT, padx=2)
        self.backup_var = tk.IntVar(value=1)
        tk.Checkbutton(
            foot, text="Backup original", variable=self.backup_var,
            bg=GUI_BG, fg=TEXT_FG, activebackground=GUI_BG,
            selectcolor=ENTRY_BG, font=FONT_SMALL).pack(side=tk.RIGHT, padx=8)
        self.changed_label = tk.Label(foot, text="", bg=GUI_BG, fg=HEADER_FG,
                                      font=FONT_BOLD, anchor="w")
        self.changed_label.pack(side=tk.LEFT, padx=2)

    def _on_destroy(self, event):
        if event.widget is self:
            self.runner.stop()

    # -- status -----------------------------------------------------------
    def _set_status(self, text, warn=False, ok=False):
        colour = WARN_FG if warn else (OK_FG if ok else STATUS_FG)
        self.status_label.configure(text=text, fg=colour)

    def _refresh_counts(self):
        if self.doc is None:
            self.changed_label.configure(text="")
            return
        count = len(self.doc.changes())
        self.changed_label.configure(
            text="" if not count else
            ("%d change%s pending" % (count, "" if count == 1 else "s")))

    def _on_server_change(self):
        remote = self.server_var.get() != LOCAL_LABEL
        if remote:
            self.pw_label.pack(side=tk.LEFT)
            self.pw_entry.pack(side=tk.LEFT, padx=4)
            self.pw_hint.pack(side=tk.LEFT)
        else:
            self.pw_label.pack_forget()
            self.pw_entry.pack_forget()
            self.pw_hint.pack_forget()

    def _host(self):
        name = self.server_var.get()
        return "" if name == LOCAL_LABEL else name

    # -- config file -------------------------------------------------------
    def _on_config_browse(self):
        """
        One dialog that covers both asks: navigate to any folder and either
        pick an existing config or type a new name for one.
        """
        current = self.config_var.get().strip() or self.settings_path
        folder = os.path.dirname(current) or DEFAULT_CONFIG_DIR
        if not os.path.isdir(folder):
            folder = DEFAULT_CONFIG_DIR if os.path.isdir(DEFAULT_CONFIG_DIR) \
                else os.path.expanduser("~")
        kwargs = {
            "parent": self,
            "title": "xQfinDB - config file (pick a folder, or an existing .json)",
            "initialdir": folder,
            "initialfile": os.path.basename(current) or CONFIG_NAME,
            "filetypes": [("Config files", "*.json"), ("All files", "*")],
        }
        try:
            chosen = filedialog.asksaveasfilename(confirmoverwrite=False, **kwargs)
        except tk.TclError:
            chosen = filedialog.asksaveasfilename(**kwargs)   # older Tk
        if chosen:
            self._apply_config_path(chosen)

    def _apply_config_path(self, path):
        """Point at another config; a folder means <folder>/xqfindb.json."""
        path = os.path.expanduser((path or "").strip())
        if not path:
            self.config_var.set(self.settings_path)
            return
        if os.path.isfile(path):
            pass                        # an existing file is the config itself
        elif os.path.isdir(path) or not path.lower().endswith(".json"):
            # A folder, or a name that is not yet a .json file, means "put the
            # default config in here".
            path = os.path.join(path, CONFIG_NAME)
        path = os.path.abspath(path)
        self.settings_path = path
        self.config_var.set(path)
        self._settings = load_settings(path)

        remembered = self._settings.get("last_server")
        if remembered in ([LOCAL_LABEL] + SSH_SERVERS):
            self.server_var.set(remembered)
        self.backup_var.set(1 if self._settings.get("backup", 1) else 0)
        self._on_server_change()
        self._local_dir = self._settings.get("local_dir") or self._local_dir
        self._remote_dir = self._settings.get("remote_dir") or self._remote_dir

        if self.doc is None:
            self._restore_last()
            if self.doc is None and not self._settings:
                self._set_status("New config: %s" % path, ok=True)
        else:
            self._set_status(
                "Config is now %s (the open file was left as it is)." % path,
                ok=True)

    # -- remembering the last file ----------------------------------------
    def _remember(self):
        # The folder the file came from is where the next Browse should start,
        # however it was opened (Browse, Reload, or restored at start-up).
        if self.file_path:
            folder = os.path.dirname(self.file_path)
            if folder:
                if self._loaded_host:
                    self._remote_dir = folder
                else:
                    self._local_dir = folder
        self._settings = {
            "last_path": self.file_path,
            "last_server": self.server_var.get(),
            "local_dir": self._local_dir,
            "remote_dir": self._remote_dir,
            "backup": int(self.backup_var.get()),
        }
        problem = save_settings(self.settings_path, self._settings)
        if problem:
            self._set_status("Config not saved to %s: %s"
                             % (self.settings_path, problem), warn=True)

    def _restore_last(self):
        """
        Reopen the file from last time.

        A local file is loaded straight away. A remote one is only remembered,
        not fetched: an ssh attempt at start-up could sit there for the whole
        connect timeout inside an xNAVSL tab, so Reload stays the trigger.
        """
        path = self._settings.get("last_path") or ""
        if not path or self.doc is not None:
            return
        # _host() reflects the dropdown, which only accepts a known server, so
        # a stale or unknown name in the settings file can never arm an ssh.
        host = self._host()
        if host:
            self.file_path = path
            self._loaded_host = host
            self.file_label.configure(
                text="File:  %s        [%s@%s - not loaded yet]"
                     % (path, SSH_USER, host))
            self._set_status(
                "Last file was %s@%s:%s - press Reload to open it."
                % (SSH_USER, host, path))
            return
        if os.path.isfile(path):
            self._load(path, "")
        else:
            self._set_status("Last file is no longer there: %s" % path,
                             warn=True)

    # -- loading ----------------------------------------------------------
    def _confirm_discard(self):
        if self.doc is None or not self.doc.changes():
            return True
        return messagebox.askyesno(
            "xQfinDB - unsaved changes",
            "%d edited serial number(s) have not been saved.\n\nDiscard them?"
            % len(self.doc.changes()), parent=self)

    def _on_browse(self):
        if self._busy or not self._confirm_discard():
            return
        host = self._host()
        if not host:
            path = filedialog.askopenfilename(
                parent=self, title="xQfinDB - select Qfin config file",
                initialdir=self._local_dir, filetypes=FILE_TYPES)
            if not path:
                return
            self._local_dir = os.path.dirname(path) or self._local_dir
            self._load(path, "")
            return
        browser = RemoteBrowser(self, host, self.pw_var.get(), self._remote_dir)
        path = browser.show()
        if not path:
            return
        self._remote_dir = os.path.dirname(path) or self._remote_dir
        self._load(path, host)

    def _on_reload(self):
        if self._busy:
            return
        if not self.file_path:
            self._set_status("Nothing loaded yet - use Browse first.", warn=True)
            return
        if not self._confirm_discard():
            return
        self._load(self.file_path, self._loaded_host)

    def _load(self, path, host):
        self.grid_view.end_edit(commit=False)
        self._busy = True
        source = host or LOCAL_LABEL
        self._set_status("Reading %s from %s ..." % (path, source))
        password = self.pw_var.get()

        def work():
            if host:
                return remote_read(host, path, password)
            return local_read(path)

        def done(raw, err):
            self._busy = False
            if err is not None:
                self._set_status("Could not read %s" % path, warn=True)
                messagebox.showerror("xQfinDB - open failed",
                                     "%s\n\n%s" % (path, err), parent=self)
                return
            doc = QfinDocument(raw, path, source)
            if not doc.streamers:
                self._set_status("No <qfin> elements found in %s" % path,
                                 warn=True)
                messagebox.showwarning(
                    "xQfinDB - nothing to edit",
                    "%s was read (%d bytes) but holds no <qfin sn=\"...\"/> "
                    "elements.\n\nIs this a Qfin scenario / ConfigDB file?"
                    % (path, len(raw)), parent=self)
                return
            self.doc = doc
            self.file_path = path
            self._loaded_host = host
            self._populate()
            self._remember()

        self.runner.submit(work, done)

    # -- table ------------------------------------------------------------
    def _populate(self):
        doc = self.doc
        self.grid_view.set_document(doc)
        self._find_query = None
        self._find_hits = []
        self._find_index = -1

        self.file_label.configure(
            text="File:  %s        [%s]" % (doc.display_path, doc.source))
        meta = []
        if doc.scenario:
            meta.append("scenario: %s" % doc.scenario)
        if doc.vessels:
            meta.append("vessel: %s" % ", ".join(v for v in doc.vessels if v))
        meta.append("%d streamers" % len(doc.streamers))
        meta.append("%d qfins" % doc.qfin_count())
        counts = sorted(set(len(s.cells) for s in doc.streamers))
        meta.append("qfins per streamer: %s"
                    % ("-".join(str(c) for c in (counts[0], counts[-1]))
                       if len(counts) > 1 else str(counts[0])))
        meta.append("%d bytes" % len(doc.raw))
        self.meta_label.configure(text="   ".join(meta + doc.notes))

        self._refresh_counts()
        self._set_status(
            "Click a cell to select it. Double-click or type to edit; "
            "arrows move, Enter/Tab move on, Esc cancels.", ok=True)

    def _on_cell_select(self, row, col):
        doc = self.doc
        if doc is None:
            return
        streamer = doc.streamers[col]
        cell = self.grid_view.cell(row, col)
        if cell is None:
            self._set_status("%s has no qfin at position %d."
                             % (streamer.heading(), row + 1))
            return
        extra = "  ".join("%s=%s" % (k, v) for k, v in sorted(cell.attrs.items())
                          if k != "sn")
        note = "  (edited, was %s)" % cell.original if cell.changed else ""
        self._set_status("%s  qfin %d  sn=%s%s   %s   |   %s"
                         % (streamer.heading(), row + 1, cell.value, note,
                            extra, streamer.describe()))

    def _on_cell_change(self, row, col):
        self._refresh_counts()
        self._on_cell_select(row, col)

    # -- search -----------------------------------------------------------
    def _collect_hits(self, query):
        """Exact serial matches if there are any, else partial ones."""
        needle = query.lower()
        exact, partial = [], []
        for col, streamer in enumerate(self.doc.streamers):
            for row, cell in enumerate(streamer.cells):
                value = cell.value.lower()
                if value == needle:
                    exact.append((row, col))
                elif needle and needle in value:
                    partial.append((row, col))
        hits = exact or partial
        hits.sort()                       # top-to-bottom, left-to-right
        return hits, bool(exact)

    def _on_find(self):
        if self.doc is None:
            self._set_status("Nothing loaded - use Browse first.", warn=True)
            return
        query = self.find_var.get().strip()
        if not query:
            self._set_status("Type a serial number to find.", warn=True)
            self.find_entry.focus_set()
            return
        self.grid_view.end_edit(commit=True)
        if query != self._find_query:
            self._find_query = query
            self._find_hits, self._find_exact = self._collect_hits(query)
            self._find_index = -1
        if not self._find_hits:
            self.grid_view.clear_flash()
            self._set_status("No qfin serial matches %s." % query, warn=True)
            return
        self._find_index = (self._find_index + 1) % len(self._find_hits)
        row, col = self._find_hits[self._find_index]
        self.grid_view.flash(row, col)
        self.grid_view.select(row, col, notify=False, center=True)
        self.find_entry.focus_set()     # Enter keeps cycling through matches
        streamer = self.doc.streamers[col]
        self._set_status(
            "%s %s  -  match %d of %d:  %s qfin %d  (sn=%s)"
            % ("Serial" if self._find_exact else "Contains",
               query, self._find_index + 1, len(self._find_hits),
               streamer.heading(), row + 1, streamer.cells[row].value),
            ok=True)

    # -- saving -----------------------------------------------------------
    def _on_revert(self):
        if self.doc is None:
            return
        self.grid_view.end_edit(commit=False)
        count = len(self.doc.changes())
        if not count:
            self._set_status("Nothing to revert.")
            return
        if not messagebox.askyesno(
                "xQfinDB - revert",
                "Undo %d edited serial number(s) and go back to the values in "
                "the file?" % count, parent=self):
            return
        self.doc.revert()
        self._populate()
        self._set_status("Reverted %d edit(s)." % count, ok=True)

    def _on_save(self):
        if self._busy:
            return
        self.grid_view.end_edit(commit=True)
        if self.doc is None:
            self._set_status("Nothing loaded - use Browse first.", warn=True)
            return
        data, count = self.doc.build_bytes()
        if not count:
            self._set_status("No changes to save.")
            messagebox.showinfo("xQfinDB - save",
                                "No serial numbers were changed.", parent=self)
            return

        lines = []
        for streamer, row, cell in self.doc.changes()[:25]:
            lines.append("    %-4s qfin %-3d   %s  ->  %s"
                         % (streamer.heading(), row + 1,
                            cell.original or "(empty)", cell.value or "(empty)"))
        if count > 25:
            lines.append("    ... and %d more" % (count - 25))

        issues = self.doc.problems()
        warning = ""
        if issues:
            warning = ("\n\nCheck these before saving:\n  - "
                       + "\n  - ".join(issues))

        host = self._loaded_host
        target = ("%s@%s:%s" % (SSH_USER, host, self.file_path)
                  if host else self.file_path)
        backup = bool(self.backup_var.get())
        prompt = (
            "Write %d serial number change(s) to:\n    %s\n\n%s\n\n"
            "Only the characters inside sn=\"...\" are replaced; the rest of "
            "the file is written back byte for byte.%s\n\n%s"
            % (count, target, "\n".join(lines),
               warning,
               "A .bak-<timestamp> copy is kept next to it."
               if backup else "No backup will be kept."))
        if not messagebox.askyesno("xQfinDB - confirm save", prompt, parent=self):
            self._set_status("Save cancelled.")
            return

        self._busy = True
        self._set_status("Saving %d change(s) to %s ..." % (count, target))
        path = self.file_path
        password = self.pw_var.get()

        def work():
            if host:
                return remote_write(host, path, data, password, backup)
            return local_write(path, data, backup)

        def done(stamp, err):
            self._busy = False
            if err is not None:
                self._set_status("Save failed - the file was not changed.",
                                 warn=True)
                messagebox.showerror("xQfinDB - save failed",
                                     "%s\n\n%s" % (target, err), parent=self)
                return
            self.doc.commit()
            self.grid_view.clear_changed_marks()
            self._refresh_counts()
            self._remember()
            note = (" Backup: %s.bak-%s" % (os.path.basename(path), stamp)
                    if stamp else "")
            self._set_status("Saved %d change(s) to %s.%s"
                             % (count, target, note), ok=True)
            messagebox.showinfo(
                "xQfinDB - saved",
                "%d serial number(s) written to:\n%s%s"
                % (count, target, ("\n\nBackup kept as:\n%s.bak-%s"
                                   % (path, stamp)) if stamp else ""),
                parent=self)

        self.runner.submit(work, done)


class XQfinDBApp(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("xQfinDB - Qfin Serial Number Editor")
        self.configure(bg=GUI_BG)
        self.geometry("1120x680")
        self.minsize(720, 460)
        panel = XQfinDBPanel(self)
        panel.pack(fill=tk.BOTH, expand=True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)


def xnavsl_embed(master):
    """Called by xNAVSL to show this tool inside a tab (no second Tk)."""
    panel = XQfinDBPanel(master)
    panel.pack(fill=tk.BOTH, expand=True)
    return panel


if __name__ == "__main__":
    if not _ensure_display():
        sys.stderr.write(
            "\n--- xQfinDB ---\n"
            "Tkinter could not find a display.\n"
            "\n"
            "This is NOT a bug in xQfinDB.py - the GUI has nowhere to draw.\n"
            "\n"
            "Fix:\n"
            "  - Run on your QC workstation (with monitor), or from xNAVSL there\n"
            "  - Or SSH with X forwarding:  ssh -X user@host\n"
            "  - Or on the server console:  export DISPLAY=:0\n"
            "\n")
        sys.exit(1)
    try:
        XQfinDBApp().mainloop()
    except tk.TclError as exc:
        sys.stderr.write(
            "\nTkinter display error: %s\n"
            "(set DISPLAY or use ssh -X)\n" % exc)
        sys.exit(1)
