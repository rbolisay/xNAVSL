#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# xNavSL / xNAVSL — Python 2.7 only (match site_scripts interpreters).
# Embed order: Tk subclass shim (class App(tk.Tk) + __main__) -> Tk-root redirect (module-level Tk/mainloop) ->
# recommended app class (x4D/xdbRead) -> xnavsl_embed(master) hook -> embed_overrides.json ->
# wrappers/ (auto when a slot path is set or config loaded; thin xnavsl_embed + run_path) ->
# auto: tk.Frame subclass + ctor heuristics.
# Otherwise the script runs as subprocess (own window). Overrides file: see EMBED_OVERRIDES_FILE.
# Separate-window tools use the same interpreter as xNAVSL — most site_scripts are Python 2.7; run xNAVSL
# with python2.7 so embed + fallback match. Optional: XNAVSL_TOOL_PYTHON=/path/to/python2.7
import Tkinter as tk
import tkFont
import tkFileDialog
import tkMessageBox
import tkSimpleDialog
import ScrolledText
import ttk
import os
import sys
import imp
import marshal
import struct
import hashlib
import subprocess
import json
import re
import inspect
import threading
import time
import ast

# Do not write .pyc next to arbitrary slot scripts (e.g. site_scripts). Embedded bytecode goes to
# DEFAULT_CONFIG_DIR/embed_pycache/ via _imp_load_source_module only.
if hasattr(sys, "dont_write_bytecode"):
    sys.dont_write_bytecode = True


def _python_for_tool_subprocess():
    """
    Interpreter used for subprocess fallback (separate window). Site tools are almost always Python 2.7;
    this defaults to sys.executable — run xNAVSL itself with python2.7 so child processes match.
    Set XNAVSL_TOOL_PYTHON to an absolute path to override (e.g. nonstandard layout).
    """
    override = (os.environ.get("XNAVSL_TOOL_PYTHON") or "").strip()
    if override and os.path.isfile(override):
        return override
    return sys.executable


def _terminate_tool_subprocess(proc):
    """
    Stop a separate-window tool started via subprocess.Popen (fallback when embed fails).
    Called when its tab closes or xNAVSL exits.
    """
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
    except Exception:
        return
    try:
        proc.terminate()
    except Exception:
        pass
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            if proc.poll() is not None:
                return
        except Exception:
            return
        time.sleep(0.05)
    try:
        proc.kill()
    except Exception:
        pass


def _xscr_embed_runtime_begin(script_path):
    """
    xSCR locates ffmpeg via `which` and via a path next to the script (see xSCR.py find_executable).
    When embedded, PATH is often trimmed and sys.argv[0] points at xNAVSL — fix both for the duration
    of the embed attempt only (do not edit xSCR).
    """
    if os.path.basename(script_path).lower() != "xscr.py":
        return None
    abs_sp = os.path.abspath(script_path)
    d = os.path.dirname(abs_sp)
    tok = {"argv0": sys.argv[0], "path": os.environ.get("PATH", "")}
    sys.argv[0] = abs_sp
    if d:
        sep = os.pathsep
        prev = tok["path"]
        os.environ["PATH"] = (d + sep + prev) if prev else d
    return tok


def _xscr_embed_runtime_end(tok):
    if tok is None:
        return
    sys.argv[0] = tok["argv0"]
    os.environ["PATH"] = tok["path"]


def _as_unicode(s):
    """Paths/strings safe for Py2 unicode formatting (avoids str % (unicode,) ascii decode errors)."""
    if s is None:
        return u""
    if isinstance(s, unicode):
        return s
    if isinstance(s, str):
        enc = sys.getfilesystemencoding() or "utf-8"
        try:
            return s.decode(enc, "replace")
        except Exception:
            return s.decode("utf-8", "replace")
    return unicode(s)


# --- Color Palette ---
color_blue_aura_bg = "#aec6dd"
color_text_dark = "#000000"
color_button_bg = "#9cb6cf"
color_button_active_bg = "#8cabc2"
color_text_on_button = "#000000"
color_header_text = "#000033"
color_goal_text_fg = "#404040"

# Shell notebook uses named ttk styles so embedded tools (e.g. xNavlineQC) cannot override them by
# configuring the global "TNotebook" / "TNotebook.Tab" styles.
_NAVSL_SHELL_NB_STYLE = "NavSL.TNotebook"
_NAVSL_SHELL_TAB_STYLE = "NavSL.TNotebook.Tab"


def _coerce_geometry_string(geom):
    """Session/config may store null, numbers, or non-strings; Tk expects a single string."""
    if geom is None:
        return ""
    try:
        if isinstance(geom, basestring):
            return geom.strip()
    except NameError:
        pass
    try:
        if isinstance(geom, str):
            return geom.strip()
    except Exception:
        pass
    try:
        return str(geom).strip()
    except Exception:
        return ""


def _normalize_geometry_for_wm(geom_str):
    """
    Some Python/Tk builds fault internally ('NoneType' is not iterable) when applying WxH-only
    geometry; appending +0+0 matches winfo_geometry() form and avoids that path.
    """
    if not geom_str:
        return geom_str
    if "+" in geom_str:
        return geom_str
    if re.match(r"^\d+x\d+$", geom_str):
        return geom_str + "+0+0"
    return geom_str


def _apply_navsl_shell_notebook_theme(style, btn_font):
    """Apply blue-aura tab colors to NavSL.TNotebook only (not global TNotebook)."""
    try:
        style.layout(_NAVSL_SHELL_NB_STYLE, style.layout("TNotebook"))
    except tk.TclError:
        pass
    try:
        style.configure(
            _NAVSL_SHELL_NB_STYLE,
            background=color_blue_aura_bg,
            borderwidth=0,
        )
        style.configure(
            _NAVSL_SHELL_TAB_STYLE,
            background=color_button_bg,
            foreground=color_text_dark,
            padding=[12, 5],
        )
        try:
            style.configure(_NAVSL_SHELL_TAB_STYLE, font=btn_font)
        except tk.TclError:
            pass
        style.map(
            _NAVSL_SHELL_TAB_STYLE,
            background=[
                ("selected", color_blue_aura_bg),
                ("active", color_button_active_bg),
            ],
            foreground=[("selected", color_header_text)],
        )
    except tk.TclError:
        pass


DEFAULT_SITE_SCRIPTS = "/usr/local/trinop/site_scripts"
MAX_SLOTS = 40

# Default site layout (Unix); overwritten by _init_config_paths() at import time.
_SITE_DEFAULT_CONFIG_DIR = "/usr/local/trinop/qcfiles/Misc/xNAVSL"
DEFAULT_CONFIG_DIR = _SITE_DEFAULT_CONFIG_DIR
WRAPPERS_DIR = os.path.join(DEFAULT_CONFIG_DIR, "wrappers")
SESSION_FILE = os.path.join(DEFAULT_CONFIG_DIR, "session.json")
EMBED_OVERRIDES_FILE = os.path.join(DEFAULT_CONFIG_DIR, "embed_overrides.json")
CONFIG_VERSION = 1

_EMBED_OVERRIDES_CACHE = None
_CONFIG_PATHS_INITIALIZED = False


def _invalidate_embed_overrides_cache():
    global _EMBED_OVERRIDES_CACHE
    _EMBED_OVERRIDES_CACHE = None


def _init_config_paths():
    """
    Set DEFAULT_CONFIG_DIR / WRAPPERS_DIR / SESSION_FILE / EMBED_OVERRIDES_FILE once.
    - XNAVSL_CONFIG_DIR: absolute path to config folder (optional).
    - Windows: use a folder beside xNAVSL.py (not /usr/local/...) so JSON + wrappers match what Launch reads.
    - Unix: default /usr/local/trinop/qcfiles/Misc/xNAVSL.
    """
    global DEFAULT_CONFIG_DIR, WRAPPERS_DIR, SESSION_FILE, EMBED_OVERRIDES_FILE
    global _EMBED_OVERRIDES_CACHE, _CONFIG_PATHS_INITIALIZED
    if _CONFIG_PATHS_INITIALIZED:
        return
    _CONFIG_PATHS_INITIALIZED = True
    _EMBED_OVERRIDES_CACHE = None
    env = (os.environ.get("XNAVSL_CONFIG_DIR") or "").strip()
    if env:
        base = os.path.abspath(env)
    elif os.name == "nt":
        try:
            here = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            here = ""
        base = os.path.join(here, "xNAVSL_data") if here else os.path.abspath(os.path.join(os.getcwd(), "xNAVSL_data"))
    else:
        base = _SITE_DEFAULT_CONFIG_DIR
    DEFAULT_CONFIG_DIR = base
    WRAPPERS_DIR = os.path.join(DEFAULT_CONFIG_DIR, "wrappers")
    SESSION_FILE = os.path.join(DEFAULT_CONFIG_DIR, "session.json")
    EMBED_OVERRIDES_FILE = os.path.join(DEFAULT_CONFIG_DIR, "embed_overrides.json")


def _embed_pycache_dir():
    """Directory for .pyc mirrors of embedded slot scripts (not beside site_scripts)."""
    _init_config_paths()
    return os.path.join(DEFAULT_CONFIG_DIR, "embed_pycache")


def _embed_pycache_path(script_path):
    """Deterministic cache filename under embed_pycache/."""
    abs_path = os.path.abspath(script_path)
    digest = hashlib.md5(abs_path).hexdigest()[:16]
    base = os.path.basename(abs_path)
    safe = re.sub(r'[^\w\.\-]', "_", base)[:100]
    if not safe.lower().endswith(".py"):
        safe = (safe or "script") + ".py"
    stem = safe[:-3] if safe.lower().endswith(".py") else safe
    return os.path.join(_embed_pycache_dir(), "%s_%s.pyc" % (stem, digest))


def _write_embed_pycache(script_path, code_obj):
    """Write Python 2.7 .pyc next to nothing in site_scripts — only under xNAVSL embed_pycache."""
    try:
        d = _embed_pycache_dir()
        if not os.path.isdir(d):
            os.makedirs(d)
        out = _embed_pycache_path(script_path)
        mtime = int(os.path.getmtime(script_path)) & 0xFFFFFFFF
        with open(out, "wb") as f:
            f.write(imp.get_magic())
            f.write(struct.pack("<I", mtime))
            marshal.dump(code_obj, f)
    except Exception:
        pass


def _merge_embed_overrides_json(basename_key, spec):
    """
    Merge one entry into embed_overrides.json (basename_key lowercased; preserves other keys).
    spec is a dict e.g. {\"run_path\": \"/path/to/wrapper.py\"}.
    """
    if not basename_key or not isinstance(spec, dict):
        return False
    key = basename_key.strip().lower()
    if not key:
        return False
    try:
        if not os.path.isdir(DEFAULT_CONFIG_DIR):
            os.makedirs(DEFAULT_CONFIG_DIR)
        data = {}
        if os.path.isfile(EMBED_OVERRIDES_FILE):
            try:
                with open(EMBED_OVERRIDES_FILE) as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        prev = data.get(key)
        if isinstance(prev, dict):
            merged = dict(prev)
            merged.update(spec)
            data[key] = merged
        else:
            data[key] = dict(spec)
        with open(EMBED_OVERRIDES_FILE, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        _invalidate_embed_overrides_cache()
        return True
    except Exception:
        return False


def _safe_wrapper_filename(original_basename):
    """Basename only; produce a stable .py name under wrappers/."""
    base = os.path.basename(original_basename or "").strip()
    if not base:
        base = "tool.py"
    elif not base.lower().endswith(".py"):
        base = base + ".py"
    safe = re.sub(r'[/\\:*?"<>|]+', "_", base)
    safe = safe.replace(" ", "_").strip("._") or "tool.py"
    if safe.lower().endswith(".py"):
        stem = safe[:-3]
    else:
        stem = safe
    return stem + "_xnavsl_wrap.py"


def _write_embed_wrapper_file(original_path, dest_py_path, navsl_dir):
    """Write a thin wrapper that calls xNAVSL.embed_into_host(master, original)."""
    orig = os.path.abspath(original_path)
    nd = os.path.abspath(navsl_dir) if navsl_dir else ""
    lines = [
        "# -*- coding: utf-8 -*-",
        "# xNAVSL embed wrapper — do not edit the original script. Regenerated when a slot path is set.",
        "_NAVSL_DIR = %s" % repr(nd),
        "_ORIGINAL = %s" % repr(orig),
        "",
        "def xnavsl_embed(master):",
        "    import sys",
        "    import os",
        "    d = _NAVSL_DIR",
        "    if d and os.path.isdir(d) and d not in sys.path:",
        "        sys.path.insert(0, d)",
        "    import xNAVSL as nav",
        "    return nav.embed_into_host(master, _ORIGINAL)",
        "",
    ]
    text = "\n".join(lines) + "\n"
    with open(dest_py_path, "w") as f:
        f.write(text)
    return True


def _read_embed_overrides():
    """
    Optional JSON: {\"scriptname.py\": {\"class\": \"MyApp\", \"ctor\": \"master_kw\"}, ...}
    Also: {\"xp1p2.py\": {\"run_path\": \"/full/path/to/embed-capable/xp1p2.py\"}} so the slot can
    still point at site_scripts while xNAVSL loads a different file for embed/subprocess.
    {\"tool.py\": {\"subprocess_only\": true}} — never imp.load_source (import-time mainloop, etc.).
    """
    global _EMBED_OVERRIDES_CACHE
    if _EMBED_OVERRIDES_CACHE is not None:
        return _EMBED_OVERRIDES_CACHE
    out = {}
    try:
        if os.path.isfile(EMBED_OVERRIDES_FILE):
            with open(EMBED_OVERRIDES_FILE) as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if k and isinstance(k, basestring):
                        out[k.strip().lower()] = v
    except Exception:
        pass
    _EMBED_OVERRIDES_CACHE = out
    return out


def _resolve_run_path(script_path):
    """If embed_overrides lists run_path/use_path/canonical_path for this basename, use that file."""
    ab = os.path.abspath(script_path)
    base = os.path.basename(script_path).lower()
    spec = _read_embed_overrides().get(base)
    if isinstance(spec, dict):
        for key in ("run_path", "use_path", "canonical_path"):
            alt = spec.get(key)
            if isinstance(alt, basestring):
                alt = alt.strip()
                if alt and os.path.isfile(alt):
                    return os.path.abspath(alt)
    return ab


def _is_navsl_embed_wrapper_script(path):
    """Thin auto-generated embed wrappers — never pass to python as the subprocess main script."""
    if not path:
        return False
    return os.path.basename(path).lower().endswith("_xnavsl_wrap.py")


def _extract_original_from_navsl_wrapper(wrapper_path):
    """Read _ORIGINAL = r'...' from a generated wrapper when JSON wrapper_for is missing."""
    try:
        with open(wrapper_path, "rb") as f:
            data = f.read(16384)
    except Exception:
        return None
    try:
        text = data.decode("utf-8-sig", "replace")
    except Exception:
        try:
            text = data.decode("utf-8", "replace")
        except Exception:
            text = data.decode("latin-1", "replace")
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("_ORIGINAL"):
            continue
        m = re.match(r'^_ORIGINAL\s*=\s*(?:u?r?)(["\'])(.*)\1\s*$', s)
        if not m:
            continue
        raw = m.group(2)
        if raw.strip() and os.path.isfile(raw.strip()):
            return raw.strip()
    return None


def _resolve_subprocess_script_path(slot_path, primary_embed_path):
    """
    Script to run when embed fails (standalone window). Never launch a thin xnavsl wrapper as main:
    it only defines xnavsl_embed. Prefer embed_overrides wrapper_for, else the slot path, else _ORIGINAL
    parsed from the wrapper file.
    """
    slot_path = (slot_path or "").strip()
    primary_embed_path = (primary_embed_path or "").strip()

    if slot_path:
        base = os.path.basename(slot_path).lower()
        spec = _read_embed_overrides().get(base)
        if isinstance(spec, dict):
            wf = spec.get("wrapper_for")
            if isinstance(wf, basestring) and wf.strip() and os.path.isfile(wf.strip()):
                return os.path.abspath(wf.strip())

    if slot_path and os.path.isfile(slot_path):
        ap = os.path.abspath(slot_path)
        if not _is_navsl_embed_wrapper_script(ap):
            return ap

    if primary_embed_path and os.path.isfile(primary_embed_path):
        ap = os.path.abspath(primary_embed_path)
        if not _is_navsl_embed_wrapper_script(ap):
            return ap
        orig = _extract_original_from_navsl_wrapper(ap)
        if orig:
            return os.path.abspath(orig)

    return None


# Optional: basenames that always use Tk-root redirection (see _script_needs_tk_root_redirect).
_TK_REDIRECT_HINT_BASENAMES = frozenset(
    (
        "3190_dither_qc_gui_v4.py",
        # xcompare.py: embeds via def xnavsl_embed(master) + XComparePanel (Option A hook).
        # xseiscal.py: embeds via def xnavsl_embed(master) + SeisCalPanel (Option A hook); not module-level Tk.
    )
)

# Scripts with class MyApp(tk.Tk) and if __name__ == "__main__" (no UI on plain import).
_TK_SUBCLASS_SHIM_HINT_BASENAMES = frozenset(
    (
        "df_disk_monitor_v1.py",
        "xtsdip_csv.py",
        "xjbcalc.py",
    )
)

# Prefer these classes after load when autodiscover would try helper Frames first (single-arg root apps).
_EMBED_RECOMMENDED_APP_CLASS = {
    "x4d.py": "X4DApp",
    "xdbread.py": "XdbReadApp",
}


def _must_skip_inprocess_embed(script_path):
    """
    If True, never imp.load_source this path. Only embed_overrides.json subprocess_only.
    Standalone scripts that call Tk()/mainloop() at import are loaded via Tk redirection instead.
    """
    base = os.path.basename(script_path).lower()
    spec = _read_embed_overrides().get(base)
    if isinstance(spec, dict) and spec.get("subprocess_only"):
        return True
    return False


def _ast_compare_is_name_main(test):
    """Python 2.7: True if test is __name__ == '__main__' or '__main__' == __name__."""
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    left, right = test.left, test.comparators[0]
    pairs = ((left, right), (right, left))
    for a, b in pairs:
        if isinstance(a, ast.Name) and a.id == "__name__":
            if isinstance(b, ast.Str) and b.s == "__main__":
                return True
        if isinstance(a, ast.Str) and a.s == "__main__":
            if isinstance(b, ast.Name) and b.id == "__name__":
                return True
    return False


def _ast_module_has_name_main_guard(tree):
    """True if module body has a top-level if __name__ == '__main__': ..."""
    for node in tree.body:
        if isinstance(node, ast.If) and _ast_compare_is_name_main(node.test):
            return True
    return False


def _ast_module_level_mainloop_call(tree):
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr == "mainloop":
                return True
            if isinstance(func, ast.Name) and func.id == "mainloop":
                return True
    return False


def _ast_module_level_tk_constructor_call(tree):
    """True for module-level root = tk.Tk() or root = Tk() (standalone scripts)."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            val = node.value
            if isinstance(val, ast.Call):
                func = val.func
                if isinstance(func, ast.Attribute) and func.attr == "Tk":
                    return True
                if isinstance(func, ast.Name) and func.id == "Tk":
                    return True
    return False


def _script_needs_tk_root_redirect(script_path):
    """
    True if importing the file would typically create a Tk root and block on mainloop() at module level.
    Uses AST (module-level mainloop, module-level Tk() assignment) when there is no top-level
    if __name__ == '__main__' guard, plus basename hints. Avoids substring false negatives from
    unrelated text containing 'if __name__'. Python 2.7 compatible.
    """
    base = os.path.basename(script_path).lower()
    if base in _TK_REDIRECT_HINT_BASENAMES:
        return True
    try:
        with open(script_path, "rb") as f:
            data = f.read()
    except Exception:
        return False
    try:
        text = data.decode("utf-8-sig", "replace")
    except Exception:
        try:
            text = data.decode("utf-8", "replace")
        except Exception:
            text = data.decode("latin-1", "replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    if _ast_module_has_name_main_guard(tree):
        return False
    if _ast_module_level_mainloop_call(tree):
        return True
    if _ast_module_level_tk_constructor_call(tree):
        return True
    return False


def _ast_module_class_inherits_tk(tree):
    """True if any module-level class inherits from Tk (e.g. class App(tk.Tk))."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Attribute) and base.attr == "Tk":
                    return True
                if isinstance(base, ast.Name) and base.id == "Tk":
                    return True
    return False


def _script_needs_tk_subclass_shim(script_path):
    """
    True for tools that subclass tk.Tk but only construct the app under if __name__ == '__main__'.
    Those classes must see a Tk replacement that is actually a Frame inside the embed tab.
    """
    base = os.path.basename(script_path).lower()
    if base in _TK_SUBCLASS_SHIM_HINT_BASENAMES:
        return True
    try:
        with open(script_path, "rb") as f:
            data = f.read()
    except Exception:
        return False
    try:
        text = data.decode("utf-8-sig", "replace")
    except Exception:
        try:
            text = data.decode("utf-8", "replace")
        except Exception:
            text = data.decode("latin-1", "replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    if not _ast_module_has_name_main_guard(tree):
        return False
    return _ast_module_class_inherits_tk(tree)


# Basenames that often exist both in site_scripts (old) and beside xNAVSL (embed-capable copy).
_EMBED_SIBLING_NAMES = frozenset(
    (
        "xp1p2.py",
        "xshotinfo.py",
    )
)


def _extra_embed_attempt_paths(slot_path, primary_resolved):
    """
    If the button points at site_scripts but a copy with xnavsl_embed sits next to xNAVSL.py,
    try that path without editing site_scripts.
    """
    base = os.path.basename(slot_path).lower()
    if _must_skip_inprocess_embed(slot_path):
        return []
    if base not in _EMBED_SIBLING_NAMES:
        return []
    tried = set(
        [os.path.abspath(slot_path), os.path.abspath(primary_resolved)]
    )
    out = []
    try:
        nav_dir = os.path.dirname(os.path.abspath(__file__))
        sibling = os.path.join(nav_dir, os.path.basename(slot_path))
        if os.path.isfile(sibling):
            a = os.path.abspath(sibling)
            if a not in tried:
                out.append(a)
    except NameError:
        pass
    return out


def _is_tk_shell_class(cls):
    try:
        if cls is tk.Tk or cls is tk.Toplevel:
            return True
        if issubclass(cls, tk.Tk) or issubclass(cls, tk.Toplevel):
            return True
    except TypeError:
        pass
    return False


def _class_cannot_receive_embed_parent(cls):
    """
    True for classes whose __init__ only accepts self (no master/root/parent) and that
    are not tk.Frame subclasses — e.g. object + self.root = tk.Tk() (many legacy tools).
    """
    try:
        if _is_tk_shell_class(cls):
            return True
    except TypeError:
        pass
    try:
        if issubclass(cls, threading.Thread):
            return True
    except TypeError:
        pass
    try:
        if issubclass(cls, tk.Frame) and cls is not tk.Frame:
            return False
    except TypeError:
        pass
    try:
        spec = inspect.getargspec(cls.__init__)
        args, varargs, keywords = spec[0], spec[1], spec[2]
    except (TypeError, AttributeError):
        return False
    if varargs or keywords:
        return False
    names = list(args)
    if names and names[0] == "self":
        names = names[1:]
    return len(names) == 0


def _collect_candidate_classes(mod):
    modname = getattr(mod, "__name__", "")
    found = []
    for name, cls in inspect.getmembers(mod, inspect.isclass):
        if getattr(cls, "__module__", None) != modname:
            continue
        if _is_tk_shell_class(cls):
            continue
        if _class_cannot_receive_embed_parent(cls):
            continue
        found.append((name, cls))

    def sort_key(item):
        n, c = item
        try:
            is_frame = issubclass(c, tk.Frame) and c is not tk.Frame
        except TypeError:
            is_frame = False
        pref_frame = 0 if is_frame else 1
        pref_app = 0 if n.lower().endswith("app") else 1
        return (pref_frame, pref_app, n.lower())

    found.sort(key=sort_key)
    return [c for _, c in found]


def _standalone_script_note(basename):
    """Known tools that create their own Tk root; explains separate window without editing those files."""
    if not basename:
        return u""
    b = basename.lower()
    lines = []
    if b == "xshotinfo.py":
        lines.append(
            u"xShotinfo embeds via def xnavsl_embed(master) and class XShotinfoPanel. "
            u"If you still see this, the launched file is an old copy — use run_path in embed_overrides.json, "
            u"a sibling xshotinfo.py next to xNAVSL.py, or update site_scripts."
        )
    if b == "3190_dither_qc_gui_v4.py":
        lines.append(
            u"This file uses tk.Tk() and root.mainloop() at module level. xNAVSL embeds it by redirecting "
            u"Tk() to the tab host and no-op mainloop. If you still see a separate window, Tk redirection "
            u"failed — check the script for a second Tk() or subprocess_only in embed_overrides.json."
        )
    elif b.endswith(".py") and "3190" in b and "dither" in b:
        lines.append(
            u"3190 dither GUIs are usually class Tk / tk.Tk() in __init__. Embed only after refactoring to a "
            u"tk.Frame panel plus def xnavsl_embed(master) (same pattern as xp1p2 / xShotinfo), or set run_path "
            u"in embed_overrides.json to a copy that already has that hook."
        )
    if b == "xp1p2.py":
        lines.append(
            u"The file that was loaded does not define xnavsl_embed / QCAppPanel (typical old site_scripts copy). "
            u"Options: copy the updated xp1p2.py into site_scripts; put xp1p2.py in the same folder as xNAVSL.py for auto-retry; "
            u"or add to embed_overrides.json: {\"xp1p2.py\": {\"run_path\": \"/full/path/to/updated/xp1p2.py\"}}."
        )
    if b == "xseiscal.py":
        lines.append(
            u"xSeisCal embeds via def xnavsl_embed(master) and class SeisCalPanel. "
            u"If you still see a separate window, the launched file may be an old copy without that hook — "
            u"use run_path in embed_overrides.json or a copy next to xNAVSL.py."
        )
    if b == "xcompare.py":
        lines.append(
            u"xCompare embeds via def xnavsl_embed(master) and class XComparePanel. "
            u"If you still see a separate window, the launched file may be an old copy without that hook — "
            u"use run_path in embed_overrides.json or a copy next to xNAVSL.py."
        )
    if not lines:
        return u""
    return u"\n\n--- Why this file opens outside the tab ---\n" + u"\n".join(
        u"- %s" % line for line in lines
    )


def _try_instantiate_class(cls, host):
    attempts = (
        lambda: cls(host),
        lambda: cls(master=host),
        lambda: cls(root=host),
        lambda: cls(parent=host),
    )
    for make in attempts:
        try:
            return make()
        except TypeError:
            continue
        except Exception:
            continue
    return None


def _maybe_pack_instance(inst):
    if inst is None or not isinstance(inst, tk.Widget):
        return
    try:
        if inst.winfo_manager():
            return
    except tk.TclError:
        pass
    try:
        inst.pack(fill=tk.BOTH, expand=True)
    except Exception:
        pass


def _try_embed_hooks(mod, host):
    for fname in ("xnavsl_embed", "navsl_embed", "build_ui", "create_app"):
        fn = getattr(mod, fname, None)
        if callable(fn):
            try:
                ret = fn(host)
                if ret is False:
                    continue
                return True
            except Exception:
                pass
    return False


def _try_embed_override(mod, host, spec):
    if not isinstance(spec, dict):
        return False
    cname = spec.get("class") or spec.get("entry")
    if not cname:
        return False
    ctor = (spec.get("ctor") or "positional").lower().replace("-", "_")
    cls = getattr(mod, cname, None)
    if not inspect.isclass(cls):
        return False
    try:
        if ctor in ("master_kw", "master"):
            inst = cls(master=host)
        elif ctor in ("root_kw", "root"):
            inst = cls(root=host)
        elif ctor in ("parent_kw", "parent"):
            inst = cls(parent=host)
        else:
            inst = cls(host)
        _maybe_pack_instance(inst)
        return True
    except Exception:
        return False


def _try_embed_autodiscover(mod, host, classes=None):
    """If classes is None, uses _collect_candidate_classes(mod). Pass a precomputed list to avoid double work."""
    for cls in classes if classes is not None else _collect_candidate_classes(mod):
        inst = _try_instantiate_class(cls, host)
        if inst is not None:
            _maybe_pack_instance(inst)
            return True
    return False


def _clear_host_children(host):
    for c in list(host.winfo_children()):
        try:
            c.destroy()
        except Exception:
            pass


def _widget_plausible_size(ch):
    """True if widget has or will soon have visible size (avoids false negatives before first map)."""
    try:
        wd = ch.winfo_width()
        ht = ch.winfo_height()
        if wd < 12 or ht < 8:
            wd = max(wd, ch.winfo_reqwidth())
            ht = max(ht, ch.winfo_reqheight())
        return wd >= 12 and ht >= 8
    except tk.TclError:
        return False


def _host_has_visible_ui(host, root_widget):
    """Require at least one descendant with plausible size (avoids false embed success)."""
    for _attempt in range(4):
        try:
            root_widget.update_idletasks()
            root_widget.update()
            host.update_idletasks()
        except Exception:
            pass
        if not host.winfo_children():
            return False

        def walk(w, depth):
            if depth > 40:
                return False
            for ch in w.winfo_children():
                if _widget_plausible_size(ch):
                    return True
                if walk(ch, depth + 1):
                    return True
            return False

        if walk(host, 0):
            return True
    return False


def _finalize_embed_visible(host, root_widget, trust_hook_nonempty=False):
    """
    After packing widgets, run a full update then measure. If a hook ran, trust non-empty host
    when sizes are still 0 (some Tk builds defer layout until after update).
    """
    try:
        root_widget.update_idletasks()
        root_widget.update()
        host.update_idletasks()
    except Exception:
        pass
    if _host_has_visible_ui(host, root_widget):
        return True
    if trust_hook_nonempty and host.winfo_children():
        return True
    return False


def _module_defines_only_tk_shell_ui(mod):
    """
    True if module defines Tk/Toplevel subclasses but no embeddable tk.Frame subclass.
    Typical standalone scripts (e.g. class App(tk.Tk)); skip autodiscover — it cannot succeed.
    """
    modname = getattr(mod, "__name__", "")
    has_frame_subclass = False
    has_tk_shell = False
    for _name, cls in inspect.getmembers(mod, inspect.isclass):
        if getattr(cls, "__module__", None) != modname:
            continue
        if _is_tk_shell_class(cls):
            has_tk_shell = True
            continue
        try:
            if issubclass(cls, tk.Frame) and cls is not tk.Frame:
                has_frame_subclass = True
                break
        except TypeError:
            pass
    return has_tk_shell and not has_frame_subclass


def _imp_load_source_module(script_path):
    """
    Load a slot script like imp.load_source but never write .pyc beside the source (e.g. site_scripts).
    Bytecode is written only under DEFAULT_CONFIG_DIR/embed_pycache/ (e.g. .../xNAVSL/embed_pycache/).
    """
    _init_config_paths()
    abs_path = os.path.abspath(script_path)
    script_dir = os.path.dirname(abs_path)
    if script_dir and script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    mod_key = "navsl_" + hashlib.md5(abs_path).hexdigest()
    if mod_key in sys.modules:
        try:
            del sys.modules[mod_key]
        except KeyError:
            pass
    try:
        with open(abs_path, "rb") as f:
            data = f.read()
    except Exception:
        return imp.load_source(mod_key, script_path)
    if data.startswith("\xef\xbb\xbf"):
        data = data[3:]
    try:
        src = data.decode("utf-8", "replace")
    except Exception:
        try:
            src = data.decode("latin-1", "replace")
        except Exception:
            src = data
    try:
        code = compile(src, abs_path, "exec")
    except Exception:
        return imp.load_source(mod_key, script_path)
    _write_embed_pycache(abs_path, code)
    mod = imp.new_module(mod_key)
    mod.__file__ = abs_path
    mod.__name__ = mod_key
    if "__builtins__" not in mod.__dict__:
        mod.__dict__["__builtins__"] = __builtins__
    sys.modules[mod_key] = mod
    exec code in mod.__dict__
    return mod


def _make_tk_shell_shim_class(tkmod, parent_host):
    """
    Replacement for Tkinter.Tk while loading scripts that define class App(tk.Tk).
    Instances are Frames packed into parent_host with WM-like methods forwarded to EmbedHost.
    """

    class _NavSLEmbeddedTkShell(tkmod.Frame):
        def __init__(self, *args, **kwargs):
            tkmod.Frame.__init__(self, parent_host)
            self._title_local = ""

        def title(self, title=None):
            if title is None:
                try:
                    if hasattr(parent_host, "title"):
                        t = parent_host.title()
                        if t:
                            return t
                except Exception:
                    pass
                return self._title_local
            self._title_local = title
            if hasattr(parent_host, "title"):
                parent_host.title(title)
            return None

        def wm_title(self, title=None):
            return self.title(title)

        def wm_iconname(self, *args, **kwargs):
            return ""

        def geometry(self, new_geo=None):
            if new_geo is None:
                try:
                    return self.winfo_geometry()
                except Exception:
                    return ""
            return ""

        def minsize(self, width=None, height=None):
            return

        def maxsize(self, width=None, height=None):
            return

        def resizable(self, width=None, height=None):
            return

        def protocol(self, name, func=None):
            if hasattr(parent_host, "protocol"):
                parent_host.protocol(name, func)

        def mainloop(self, n=0):
            try:
                self.update_idletasks()
            except Exception:
                pass

    return _NavSLEmbeddedTkShell


def _find_tk_shim_app_classes(mod, shim_cls):
    """Classes defined as subclassing tk.Tk while shim replaced Tk (shim appears in __bases__)."""
    modname = getattr(mod, "__name__", "")
    found = []
    for name, cls in inspect.getmembers(mod, inspect.isclass):
        if getattr(cls, "__module__", None) != modname:
            continue
        if cls is shim_cls:
            continue
        try:
            if shim_cls in getattr(cls, "__bases__", ()):
                found.append((name, cls))
        except Exception:
            pass

    def sort_key(item):
        n, _c = item
        pref = 0 if n.lower().endswith("app") else 1
        return (pref, n.lower())

    found.sort(key=sort_key)
    return [c for _, c in found]


def _load_script_module_with_tk_subclass_shim(script_path, embed_host):
    """
    Patch Tk -> Frame-based shell so class App(tk.Tk) builds inside embed_host; then instantiate().
    Must keep Tk patched until App() finishes: App.__init__ calls tk.Tk.__init__(self), which
    resolves Tkinter.Tk at runtime — if we restore real Tk too early, real Tk.__init__ runs and breaks embed.
    """
    import Tkinter as tkmod

    shim_cls = _make_tk_shell_shim_class(tkmod, embed_host)
    _orig_Tk = tkmod.Tk
    tkmod.Tk = shim_cls
    try:
        mod = _imp_load_source_module(script_path)
        candidates = _find_tk_shim_app_classes(mod, shim_cls)
        if not candidates:
            return None
        inst = candidates[0]()
        try:
            inst.pack(fill=tk.BOTH, expand=True)
        except Exception:
            pass
        setattr(mod, "_navsl_ui_built_in_host", True)
        setattr(mod, "_navsl_shim_app_instance", inst)
        return mod
    except Exception:
        return None
    finally:
        tkmod.Tk = _orig_Tk


def _try_embed_recommended_app_class(mod, host, basename):
    """Instantiate known root-app classes (X4DApp, XdbReadApp) before generic autodiscover."""
    cname = _EMBED_RECOMMENDED_APP_CLASS.get(basename)
    if not cname:
        return False
    cls = getattr(mod, cname, None)
    if not inspect.isclass(cls):
        return False
    try:
        inst = cls(host)
    except TypeError:
        try:
            inst = cls(master=host)
        except Exception:
            return False
    except Exception:
        return False
    _maybe_pack_instance(inst)
    return True


def _load_script_module_with_tk_root_redirect(script_path, embed_host):
    """
    While loading, Tk() with master=None returns embed_host so UI packs into the tab.
    Restores Tkinter.Tk after load. Sets mod._navsl_ui_built_in_host when load completes.
    """
    import Tkinter as tkmod

    _holder = [embed_host]

    # Tkinter.Tk(screenName=..., ...) has no parent; during this load every Tk() must map to the tab host.
    def _RedirectTk(*args, **kwargs):
        return _holder[0]

    _orig_Tk = tkmod.Tk
    tkmod.Tk = _RedirectTk
    try:
        mod = _imp_load_source_module(script_path)
        setattr(mod, "_navsl_ui_built_in_host", True)
        return mod
    except Exception:
        return None
    finally:
        tkmod.Tk = _orig_Tk


def _load_script_module(script_path, embed_host=None):
    """
    Load script for in-process embed. If the script needs Tk redirection (module-level mainloop, etc.),
    embed_host must be the EmbedHost frame; otherwise pass None (callers that only probe should not use redirect).
    """
    if _must_skip_inprocess_embed(script_path):
        return None
    if embed_host is not None and _script_needs_tk_subclass_shim(script_path):
        return _load_script_module_with_tk_subclass_shim(script_path, embed_host)
    need_redirect = _script_needs_tk_root_redirect(script_path)
    if need_redirect:
        if embed_host is None:
            return None
        return _load_script_module_with_tk_root_redirect(script_path, embed_host)
    try:
        return _imp_load_source_module(script_path)
    except Exception:
        return None


def run_config_browse_dialog(parent, btn_font):
    """Load file vs save-folder choice (works on all Tk / Python 2.7 builds)."""
    result = [None]
    dlg = tk.Toplevel(parent)
    dlg.title("Configuration")
    dlg.configure(bg=color_blue_aura_bg)
    dlg.transient(parent)
    dlg.grab_set()

    def finish(val):
        result[0] = val
        dlg.destroy()

    tk.Label(
        dlg,
        text="Choose an action:",
        bg=color_blue_aura_bg,
        fg=color_text_dark,
        font=btn_font,
    ).pack(padx=22, pady=(14, 10))
    for text, val in (
        ("Load configuration file...", "load"),
        ("Choose save folder...", "folder"),
        ("Cancel", None),
    ):
        tk.Button(
            dlg,
            text=text,
            command=lambda v=val: finish(v),
            bg=color_button_bg,
            fg=color_text_on_button,
            activebackground=color_button_active_bg,
            font=btn_font,
            padx=12,
            pady=4,
        ).pack(fill=tk.X, padx=20, pady=3)
    parent.wait_window(dlg)
    return result[0]


class EmbedHost(tk.Frame):
    """Frame that stubs common Tk Wm APIs so existing apps can run inside a notebook tab."""

    def __init__(self, parent, notebook, tab_id, **kw):
        tk.Frame.__init__(self, parent, **kw)
        self._notebook = notebook
        self._tab_id = tab_id
        self._title = ""
        self._wm_delete = None
        self._tool_subprocess = None

    def title(self, title=None):
        if title is None:
            return self._title
        self._title = title
        try:
            short = title[:60] if title else ""
            self._notebook.tab(self._tab_id, text=short)
        except tk.TclError:
            pass

    def geometry(self, new_geo=None):
        if new_geo is None:
            return self.winfo_geometry()
        return ""

    def minsize(self, width=None, height=None):
        return

    def maxsize(self, width=None, height=None):
        return

    def resizable(self, width=None, height=None):
        return

    def protocol(self, name, func=None):
        if name == "WM_DELETE_WINDOW" and func is not None:
            self._wm_delete = func

    def run_wm_delete(self):
        if self._wm_delete:
            try:
                self._wm_delete()
            except Exception:
                pass
            self._wm_delete = None

    def attach_tool_subprocess(self, proc):
        """Remember a Popen child for separate-window fallback so we can stop it with the tab."""
        self._tool_subprocess = proc

    def terminate_tool_subprocess(self):
        p = self._tool_subprocess
        self._tool_subprocess = None
        _terminate_tool_subprocess(p)

    def mainloop(self, n=0):
        """Scripts call root.mainloop(); outer xNAVSL already runs the real Tk mainloop."""
        try:
            self.update_idletasks()
        except Exception:
            pass


class NavSLMediator(object):
    """Coordinates slot rows, file picks, tab creation, embed vs subprocess launch, and tab close."""

    _instance = None

    def __init__(self, root):
        NavSLMediator._instance = self
        self.root = root
        self.notebook = None
        self.slots_container = None
        self.paned = None
        self.slots = []
        self.slot_rows = []
        self.count_var = tk.StringVar(value="5")
        self.add_count_var = tk.StringVar(value="1")
        self.config_name_var = tk.StringVar(value="Default")
        self._config_name_entry = None
        self.current_config_path = None
        self.default_save_dir = DEFAULT_CONFIG_DIR
        self.left_pane = None
        self.right_pane = None
        self.left_pane_visible = True
        self.hide_left_pane_btn_var = tk.StringVar(value="Hide Left Pane")

    def set_widgets(self, notebook, slots_container, paned=None, left_pane=None, right_pane=None):
        self.notebook = notebook
        self.slots_container = slots_container
        if paned is not None:
            self.paned = paned
        if left_pane is not None:
            self.left_pane = left_pane
        if right_pane is not None:
            self.right_pane = right_pane

    def toggle_left_pane(self):
        """Hide or show the configuration / slot buttons pane (right = Gui Display only)."""
        if self.paned is None or self.left_pane is None:
            return
        if self.left_pane_visible:
            try:
                self.paned.forget(self.left_pane)
            except tk.TclError:
                pass
            self.left_pane_visible = False
            self.hide_left_pane_btn_var.set("Show Left Pane")
        else:
            try:
                self.paned.insert(0, self.left_pane, minsize=260, stretch="never")
            except (tk.TclError, AttributeError, TypeError):
                try:
                    rp = self.right_pane
                    if rp is not None:
                        self.paned.forget(rp)
                    self.paned.add(self.left_pane, minsize=260, stretch="never")
                    if rp is not None:
                        self.paned.add(rp, minsize=380, stretch="always")
                except tk.TclError:
                    pass
            self.left_pane_visible = True
            self.hide_left_pane_btn_var.set("Hide Left Pane")
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def _stem_from_config_path(self, path):
        """Basename of a .json config path without extension (for the Configuration Name field)."""
        try:
            base = os.path.basename(path)
            if base.lower().endswith(".json"):
                base = base[:-5]
            return base.strip()
        except Exception:
            return ""

    def _set_config_name_display(self, text):
        """Update the configuration name StringVar and the Entry widget (Tk sometimes lags on textvariable)."""
        text = (text or "").strip()
        if not text:
            return
        self.config_name_var.set(text)
        w = self._config_name_entry
        if w is not None:
            try:
                w.delete(0, tk.END)
                w.insert(0, text)
            except Exception:
                pass
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def _safe_config_basename(self):
        raw = self.config_name_var.get().strip() or "config"
        safe = re.sub(r'[/\\:*?"<>|]+', "_", raw).strip("._ ") or "config"
        if len(safe) > 5 and safe.lower().endswith(".json"):
            safe = safe[:-5].strip("._ ") or "config"
        return safe[:120]

    def build_config_dict(self):
        sash_pos = None
        try:
            if self.paned is not None:
                c = self.paned.sash_coord(0)
                if c and len(c) >= 1:
                    sash_pos = int(c[0])
        except Exception:
            pass
        slots_data = []
        for s in self.slots:
            slots_data.append({"name": s["name"].get(), "path": s["path"].get()})
        return {
            "version": CONFIG_VERSION,
            "configuration_name": self.config_name_var.get().strip(),
            "geometry": self.root.winfo_geometry(),
            "sash_pos": sash_pos,
            "slot_count": len(self.slots),
            "slots": slots_data,
        }

    def _apply_geometry(self, geom):
        g = _normalize_geometry_for_wm(_coerce_geometry_string(geom))
        if not g:
            return
        try:
            self.root.update_idletasks()
            self.root.geometry(g)
        except Exception:
            pass

    def _apply_sash(self, sash_x):
        if self.paned is None or sash_x is None:
            return
        try:
            self.paned.sash_place(0, int(sash_x), 0)
        except Exception:
            pass

    def apply_config_dict(self, data, apply_window_layout=True, fallback_config_path=None):
        if not isinstance(data, dict):
            return
        name = (data.get("configuration_name") or "").strip()
        if not name and fallback_config_path:
            try:
                base = os.path.basename(fallback_config_path)
                if base.lower().endswith(".json"):
                    base = base[:-5]
                name = base.strip()
            except Exception:
                name = ""
        if name:
            self.config_name_var.set(name)
        try:
            n = int(data.get("slot_count", 5))
        except (ValueError, TypeError):
            n = 5
        if n < 1:
            n = 1
        if n > MAX_SLOTS:
            n = MAX_SLOTS
        self.count_var.set(str(n))
        slots_in = data.get("slots") or []
        self.slots = []
        for i in range(n):
            nm = ""
            pth = ""
            if i < len(slots_in) and isinstance(slots_in[i], dict):
                nm = (slots_in[i].get("name") or "").strip()
                pth = (slots_in[i].get("path") or "").strip()
            self.slots.append(
                {
                    "name": tk.StringVar(value=nm or ("Button %d" % (i + 1))),
                    "path": tk.StringVar(value=pth),
                }
            )
        self._rebuild_slot_rows()
        self._embed_layers_for_all_slots()
        if apply_window_layout:
            geom = _coerce_geometry_string(data.get("geometry"))
            sash = data.get("sash_pos")
            if geom:
                self.root.after(30, lambda g=geom: self._apply_geometry(g))
            if sash is not None:
                self.root.after(60, lambda sx=sash: self._apply_sash(sx))

    def _write_session(self, extra=None):
        try:
            if not os.path.isdir(DEFAULT_CONFIG_DIR):
                os.makedirs(DEFAULT_CONFIG_DIR)
            payload = {
                "last_config_path": self.current_config_path,
                "window_geometry": self.root.winfo_geometry(),
            }
            try:
                if self.paned is not None:
                    c = self.paned.sash_coord(0)
                    if c and len(c) >= 1:
                        payload["sash_pos"] = int(c[0])
            except Exception:
                pass
            if extra:
                payload.update(extra)
            with open(SESSION_FILE, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    def load_session_on_startup(self):
        if not os.path.isfile(SESSION_FILE):
            self._init_default_slots()
            return
        try:
            with open(SESSION_FILE) as f:
                sess = json.load(f)
        except Exception:
            self._init_default_slots()
            return
        path = sess.get("last_config_path")
        if path and os.path.isfile(path):
            try:
                with open(path) as cf:
                    data = json.load(cf)
                self.current_config_path = path
                self.default_save_dir = os.path.dirname(os.path.abspath(path))
                self.apply_config_dict(data, apply_window_layout=True, fallback_config_path=path)
                self._set_config_name_display(self._stem_from_config_path(path))
                return
            except Exception:
                pass
        self._init_default_slots()
        geom = _coerce_geometry_string(sess.get("window_geometry"))
        sash = sess.get("sash_pos")
        if geom:
            self.root.after(30, lambda g=geom: self._apply_geometry(g))
        if sash is not None:
            self.root.after(60, lambda sx=sash: self._apply_sash(sx))

    def load_config_file(self, path):
        path = os.path.abspath(path)
        with open(path) as f:
            data = json.load(f)
        self.current_config_path = path
        self.default_save_dir = os.path.dirname(path)
        self.apply_config_dict(data, apply_window_layout=True, fallback_config_path=path)
        self._set_config_name_display(self._stem_from_config_path(path))
        self._write_session()

    def save_config(self):
        safe = self._safe_config_basename()
        initialdir = self.default_save_dir
        if not initialdir or not os.path.isdir(initialdir):
            initialdir = DEFAULT_CONFIG_DIR
        if not os.path.isdir(initialdir):
            try:
                os.makedirs(initialdir)
            except Exception:
                initialdir = os.getcwd()

        # First save: file dialog. After a path exists, save uses default_save_dir + name from
        # the entry so typing a new name writes a different file (not always current_config_path).
        if self.current_config_path is None:
            path = tkFileDialog.asksaveasfilename(
                parent=self.root,
                title="Save configuration",
                initialdir=initialdir,
                initialfile=safe + ".json",
                defaultextension=".json",
                filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
            )
            if not path:
                return
            path = os.path.abspath(path)
        else:
            path = os.path.abspath(os.path.join(self.default_save_dir, safe + ".json"))

        dest_dir = os.path.dirname(path)
        try:
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir)
            with open(path, "w") as f:
                json.dump(self.build_config_dict(), f, indent=2)
            self.current_config_path = path
            self.default_save_dir = dest_dir
            self._write_session()
            tkMessageBox.showinfo("Saved", "Configuration saved:\n%s" % self.current_config_path)
        except Exception as ex:
            tkMessageBox.showerror("Save error", str(ex))

    def browse_config(self):
        choice = run_config_browse_dialog(self.root, self._btn_font)
        if choice == "load":
            initialdir = self.default_save_dir if os.path.isdir(self.default_save_dir) else (
                DEFAULT_CONFIG_DIR if os.path.isdir(DEFAULT_CONFIG_DIR) else os.getcwd()
            )
            path = tkFileDialog.askopenfilename(
                parent=self.root,
                title="Load configuration",
                initialdir=initialdir,
                filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
            )
            if path:
                try:
                    self.load_config_file(path)
                    tkMessageBox.showinfo("Loaded", "Configuration loaded:\n%s" % path)
                except Exception as ex:
                    tkMessageBox.showerror("Load error", str(ex))
        elif choice == "folder":
            d = tkFileDialog.askdirectory(
                parent=self.root,
                title="Choose folder for saving configurations",
                initialdir=self.default_save_dir if os.path.isdir(self.default_save_dir) else os.getcwd(),
            )
            if d:
                self.default_save_dir = os.path.abspath(d)
                tkMessageBox.showinfo("Save folder", "Save will default to this folder:\n%s" % self.default_save_dir)

    def _init_default_slots(self):
        """First run / no config: same as former default (5 buttons)."""
        n = 5
        self.slots = []
        for i in range(n):
            self.slots.append(
                {
                    "name": tk.StringVar(value="Button %d" % (i + 1)),
                    "path": tk.StringVar(value=""),
                }
            )
        self.count_var.set(str(n))
        self._rebuild_slot_rows()

    def add_slot_buttons(self):
        """Append the requested number of new button slots (up to MAX_SLOTS)."""
        try:
            k = int(self.add_count_var.get().strip())
        except ValueError:
            tkMessageBox.showerror("Invalid", "Enter a whole number for how many buttons to add.")
            return
        if k < 1:
            k = 1
        remaining = MAX_SLOTS - len(self.slots)
        if remaining <= 0:
            tkMessageBox.showwarning(
                "Limit",
                "Maximum number of buttons (%d) reached." % MAX_SLOTS,
                parent=self.root,
            )
            return
        if k > remaining:
            tkMessageBox.showinfo(
                "Limit",
                "Only %d more button(s) can be added (maximum %d total)." % (remaining, MAX_SLOTS),
                parent=self.root,
            )
            k = remaining
        for _ in range(k):
            self.slots.append(
                {
                    "name": tk.StringVar(value="Button %d" % (len(self.slots) + 1)),
                    "path": tk.StringVar(value=""),
                }
            )
        self.count_var.set(str(len(self.slots)))
        self._rebuild_slot_rows()

    def _rebuild_slot_rows(self):
        for w in self.slot_rows:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self.slot_rows = []
        parent = self.slots_container
        side_font = getattr(self, "_slot_side_font", self._btn_font)
        launch_pady = max(4, int(round(3 * 1.2)))
        launch_ipady = max(2, int(round(2 * 1.2)))
        for i, slot in enumerate(self.slots):
            row = tk.Frame(parent, bg=color_blue_aura_bg)
            self.slot_rows.append(row)
            launch = tk.Button(
                row,
                textvariable=slot["name"],
                command=lambda idx=i: self.launch_slot(idx),
                font=self._btn_font,
                bg=color_button_bg,
                fg=color_text_on_button,
                activebackground=color_button_active_bg,
                activeforeground=color_text_on_button,
                relief=tk.RAISED,
                borderwidth=2,
                padx=6,
                pady=launch_pady,
            )
            launch.bind("<Button-3>", lambda e, idx=i: self._show_slot_context_menu(e, idx))
            side_col = tk.Frame(row, bg=color_blue_aura_bg)
            browse_b = tk.Button(
                side_col,
                text="Browse/Select",
                command=lambda idx=i: self.browse_slot(idx),
                font=side_font,
                bg=color_button_bg,
                fg=color_text_on_button,
                activebackground=color_button_active_bg,
                padx=2,
                pady=1,
            )
            rename_b = tk.Button(
                side_col,
                text="Rename",
                command=lambda idx=i: self.rename_slot(idx),
                font=side_font,
                bg=color_button_bg,
                fg=color_text_on_button,
                activebackground=color_button_active_bg,
                padx=2,
                pady=1,
            )
            browse_b.pack(fill=tk.X, pady=(0, 2))
            rename_b.pack(fill=tk.X)
            launch.pack(
                side=tk.LEFT,
                fill=tk.BOTH,
                expand=True,
                padx=(0, 4),
                ipady=launch_ipady,
            )
            side_col.pack(side=tk.RIGHT, padx=(2, 0))
            row.pack(fill=tk.X, pady=3)

    def _dismiss_slot_context_menu(self):
        """Close the slot right-click menu and remove global click-to-dismiss bindings."""
        if getattr(self, "_slot_ctx_menu", None) is not None:
            try:
                self._slot_ctx_menu.unpost()
            except Exception:
                pass
            self._slot_ctx_menu = None
        try:
            self.root.unbind_all("<Button-1>")
            self.root.unbind_all("<Button-3>")
            self.root.unbind_all("<Escape>")
        except Exception:
            pass

    def _install_slot_context_dismiss_bindings(self):
        """After menu is shown, dismiss on click outside or Escape (deferred so open-click is not eaten)."""
        if getattr(self, "_slot_ctx_menu", None) is None:
            return

        def dismiss(event=None):
            m = getattr(self, "_slot_ctx_menu", None)
            if m is None:
                return
            # Do not unpost on clicks that target the menu itself — let the menu command run first.
            if event is not None:
                try:
                    if event.widget == m:
                        return
                except Exception:
                    pass
            self._dismiss_slot_context_menu()

        try:
            self.root.bind_all("<Button-1>", dismiss)
            self.root.bind_all("<Button-3>", dismiss)
            self.root.bind_all("<Escape>", dismiss)
        except Exception:
            pass

    def _show_slot_context_menu(self, event, index):
        """Right-click menu on launch button: delete, move up/down."""
        self._dismiss_slot_context_menu()
        menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=color_button_bg,
            fg=color_text_dark,
            activebackground=color_button_active_bg,
            activeforeground=color_text_on_button,
            relief=tk.FLAT,
        )
        self._slot_ctx_menu = menu
        try:
            menu.config(font=self._btn_font)
        except tk.TclError:
            pass
        n = len(self.slots)
        can_del = n > 1
        can_up = index > 0
        can_down = index < n - 1

        def cmd_delete():
            self._dismiss_slot_context_menu()
            self._confirm_delete_slot(index)

        def cmd_up():
            self._dismiss_slot_context_menu()
            self._move_slot(index, -1)

        def cmd_down():
            self._dismiss_slot_context_menu()
            self._move_slot(index, 1)

        menu.add_command(
            label="Delete Button",
            command=cmd_delete,
            state=tk.NORMAL if can_del else tk.DISABLED,
        )
        menu.add_command(
            label="Move Up",
            command=cmd_up,
            state=tk.NORMAL if can_up else tk.DISABLED,
        )
        menu.add_command(
            label="Move Down",
            command=cmd_down,
            state=tk.NORMAL if can_down else tk.DISABLED,
        )
        xr, yr = event.x_root, event.y_root

        def post_and_bind():
            if getattr(self, "_slot_ctx_menu", None) is not menu:
                return
            try:
                menu.post(xr, yr)
            except tk.TclError:
                self._slot_ctx_menu = None
                return
            try:
                self.root.after(10, self._install_slot_context_dismiss_bindings)
            except Exception:
                pass

        try:
            self.root.after_idle(post_and_bind)
        except Exception:
            try:
                menu.post(xr, yr)
                self.root.after(10, self._install_slot_context_dismiss_bindings)
            except Exception:
                self._slot_ctx_menu = None

    def _confirm_delete_slot(self, index):
        """Themed confirm before removing a slot (must keep at least one)."""
        if len(self.slots) <= 1:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Delete button")
        dlg.configure(bg=color_blue_aura_bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        outer = tk.Frame(dlg, bg=color_blue_aura_bg)
        outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        tk.Label(
            outer,
            text="Remove this button slot?",
            bg=color_blue_aura_bg,
            fg=color_text_dark,
            font=self._btn_font,
            anchor="w",
        ).pack(anchor="w")
        nm = self.slots[index]["name"].get()
        tk.Label(
            outer,
            text=nm,
            bg=color_blue_aura_bg,
            fg=color_header_text,
            font=self._btn_font,
            anchor="w",
        ).pack(anchor="w", pady=(4, 14))
        btn_row = tk.Frame(outer, bg=color_blue_aura_bg)
        btn_row.pack(fill=tk.X)

        def on_yes():
            dlg.destroy()
            self._delete_slot(index)

        def on_no():
            dlg.destroy()

        tk.Button(
            btn_row,
            text="Yes, delete",
            command=on_yes,
            font=self._btn_font,
            bg=color_button_bg,
            fg=color_text_on_button,
            activebackground=color_button_active_bg,
            activeforeground=color_text_on_button,
            padx=10,
            pady=4,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            btn_row,
            text="Cancel",
            command=on_no,
            font=self._btn_font,
            bg=color_button_bg,
            fg=color_text_on_button,
            activebackground=color_button_active_bg,
            activeforeground=color_text_on_button,
            padx=10,
            pady=4,
        ).pack(side=tk.LEFT)
        dlg.protocol("WM_DELETE_WINDOW", on_no)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        dlg.focus_set()

    def _confirm_delete_all_slots(self):
        """Themed confirm: collapse to one empty slot (must keep at least one)."""
        if len(self.slots) <= 1:
            tkMessageBox.showinfo(
                "Nothing to delete",
                "Only one button slot remains.",
                parent=self.root,
            )
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Delete all buttons")
        dlg.configure(bg=color_blue_aura_bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        outer = tk.Frame(dlg, bg=color_blue_aura_bg)
        outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        tk.Label(
            outer,
            text="Remove all button slots except one?",
            bg=color_blue_aura_bg,
            fg=color_text_dark,
            font=self._btn_font,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            outer,
            text="All names and script paths will be cleared. This cannot be undone.",
            bg=color_blue_aura_bg,
            fg=color_header_text,
            font=self._btn_font,
            anchor="w",
            wraplength=360,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(4, 14))
        btn_row = tk.Frame(outer, bg=color_blue_aura_bg)
        btn_row.pack(fill=tk.X)

        def on_yes():
            dlg.destroy()
            self._delete_all_slots()

        def on_no():
            dlg.destroy()

        tk.Button(
            btn_row,
            text="Yes, delete all",
            command=on_yes,
            font=self._btn_font,
            bg=color_button_bg,
            fg=color_text_on_button,
            activebackground=color_button_active_bg,
            activeforeground=color_text_on_button,
            padx=10,
            pady=4,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            btn_row,
            text="Cancel",
            command=on_no,
            font=self._btn_font,
            bg=color_button_bg,
            fg=color_text_on_button,
            activebackground=color_button_active_bg,
            activeforeground=color_text_on_button,
            padx=10,
            pady=4,
        ).pack(side=tk.LEFT)
        dlg.protocol("WM_DELETE_WINDOW", on_no)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        dlg.focus_set()

    def _delete_all_slots(self):
        """Leave a single default slot; at least one button is always required."""
        self.slots = [
            {
                "name": tk.StringVar(value="Button 1"),
                "path": tk.StringVar(value=""),
            }
        ]
        self.count_var.set("1")
        self._rebuild_slot_rows()

    def _delete_slot(self, index):
        if len(self.slots) <= 1:
            return
        self.slots.pop(index)
        self.count_var.set(str(len(self.slots)))
        self._rebuild_slot_rows()

    def _move_slot(self, index, delta):
        j = index + delta
        if j < 0 or j >= len(self.slots):
            return
        self.slots[index], self.slots[j] = self.slots[j], self.slots[index]
        self._rebuild_slot_rows()

    def rename_slot(self, index):
        slot = self.slots[index]
        cur = slot["name"].get()
        new = tkSimpleDialog.askstring("Rename", "Label for this button:", initialvalue=cur, parent=self.root)
        if new is not None and new.strip():
            slot["name"].set(new.strip())

    def browse_slot(self, index):
        slot = self.slots[index]
        initial = slot["path"].get().strip()
        initialdir = os.path.dirname(initial) if initial and os.path.isdir(os.path.dirname(initial)) else (
            DEFAULT_SITE_SCRIPTS if os.path.isdir(DEFAULT_SITE_SCRIPTS) else os.getcwd()
        )
        path = tkFileDialog.askopenfilename(
            parent=self.root,
            title="Select script to run",
            initialdir=initialdir,
            filetypes=[("Python", "*.py"), ("All files", "*.*")],
        )
        if path:
            slot["path"].set(path)
            self._ensure_embed_layer_for_path(path)

    def _embed_layers_for_all_slots(self):
        """After Browse or config load: wrapper + embed_overrides.json for each non-empty slot path."""
        for s in self.slots:
            p = (s["path"].get() or "").strip()
            if p:
                self._ensure_embed_layer_for_path(p)

    def _ensure_embed_layer_for_path(self, path):
        """
        Write wrappers/<name>_xnavsl_wrap.py and merge embed_overrides.json (run_path) for this basename.
        Does not modify the original script. Silent on success; messagebox only on failure.
        """
        path = (path or "").strip()
        if not path or not os.path.isfile(path):
            return
        try:
            if not os.path.isdir(DEFAULT_CONFIG_DIR):
                os.makedirs(DEFAULT_CONFIG_DIR)
            if not os.path.isdir(WRAPPERS_DIR):
                os.makedirs(WRAPPERS_DIR)
        except Exception as ex:
            tkMessageBox.showerror("Embed layer", "Could not create config/wrappers folder:\n%s" % ex, parent=self.root)
            return
        orig_abs = os.path.abspath(path)
        base = os.path.basename(orig_abs)
        wrap_name = _safe_wrapper_filename(base)
        dest = os.path.join(WRAPPERS_DIR, wrap_name)
        try:
            navsl_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            navsl_dir = ""
        try:
            _write_embed_wrapper_file(orig_abs, dest, navsl_dir)
        except Exception as ex:
            tkMessageBox.showerror("Embed layer", "Could not write wrapper:\n%s\n%s" % (dest, ex), parent=self.root)
            return
        spec = {
            "run_path": dest,
            "wrapper_for": orig_abs,
            "layer": "xnavsl_wrapper",
        }
        if not _merge_embed_overrides_json(base, spec):
            tkMessageBox.showerror(
                "Embed layer",
                "Wrapper was written but embed_overrides.json could not be updated:\n%s" % EMBED_OVERRIDES_FILE,
                parent=self.root,
            )

    def launch_slot(self, index):
        slot = self.slots[index]
        path = slot["path"].get().strip()
        if not path or not os.path.isfile(path):
            tkMessageBox.showwarning("No script", "Use Browse/Select to choose a .py file for this button.")
            return
        tab_title = slot["name"].get().strip() or os.path.basename(path)
        outer = tk.Frame(self.notebook, bg=color_blue_aura_bg)
        # ttk.Notebook default sticky does not expand the page — without nsew the tab stays ~0 size (looks empty).
        try:
            self.notebook.add(outer, text=tab_title[:48], sticky=tk.NSEW)
        except tk.TclError:
            self.notebook.add(outer, text=tab_title[:48])
        self.notebook.select(outer)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        host = EmbedHost(outer, self.notebook, outer, bg=color_blue_aura_bg)
        host.grid(row=0, column=0, sticky="nsew")
        primary = _resolve_run_path(path)
        ok = self._try_embed(host, primary, tab_title)
        if not ok:
            for alt in _extra_embed_attempt_paths(path, primary):
                ok = self._try_embed(host, alt, tab_title)
                if ok:
                    break
        if not ok:
            self._fallback_subprocess_tab(host, primary, slot_path=path)
        try:
            _apply_navsl_shell_notebook_theme(ttk.Style(), self._btn_font)
        except Exception:
            pass
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

    def _try_embed(self, host, script_path, tab_title):
        """Load script in-process: hooks, embed_overrides.json, autodiscover — each must yield visible UI."""
        _xscr_tok = _xscr_embed_runtime_begin(script_path)
        try:
            basename = os.path.basename(script_path).lower()
            mod = _load_script_module(script_path, embed_host=host)
            if mod is None:
                return False

            # Tk-root redirect: UI was built into host during imp.load_source (no xnavsl_embed).
            if getattr(mod, "_navsl_ui_built_in_host", False):
                try:
                    if _finalize_embed_visible(host, self.root, trust_hook_nonempty=True):
                        host.title(tab_title)
                        return True
                except Exception:
                    pass
                try:
                    if host.winfo_children():
                        host.title(tab_title)
                        return True
                except Exception:
                    pass
                # Do not run hooks/autodiscover here — they would clear the host and cannot re-import the module.
                return False

            # x4D / xdbRead: construct known app class(host) before hooks (autodiscover may try helper Frames first).
            try:
                if _try_embed_recommended_app_class(mod, host, basename):
                    if _finalize_embed_visible(host, self.root, trust_hook_nonempty=True):
                        host.title(tab_title)
                        return True
                    try:
                        if host.winfo_children():
                            host.title(tab_title)
                            return True
                    except Exception:
                        pass
                    _clear_host_children(host)
            except Exception:
                pass

            override_spec = _read_embed_overrides().get(basename)
            has_class_override = isinstance(override_spec, dict) and (
                override_spec.get("class") or override_spec.get("entry")
            )

            steps = []
            if has_class_override:
                steps.append(lambda: _try_embed_override(mod, host, override_spec))
            embed_candidates = None
            if not _module_defines_only_tk_shell_ui(mod):
                embed_candidates = _collect_candidate_classes(mod)
            if embed_candidates:
                cands = embed_candidates
                steps.append(lambda: _try_embed_autodiscover(mod, host, cands))

            # Hooks first: relaxed success if host has children (strict size check can false-negative early).
            try:
                if _try_embed_hooks(mod, host):
                    if _finalize_embed_visible(host, self.root, trust_hook_nonempty=True):
                        host.title(tab_title)
                        return True
            except Exception:
                pass
            _clear_host_children(host)

            for step in steps:
                try:
                    if not step():
                        continue
                    if _finalize_embed_visible(host, self.root, trust_hook_nonempty=False):
                        host.title(tab_title)
                        return True
                except Exception:
                    pass
                _clear_host_children(host)
            return False
        finally:
            _xscr_embed_runtime_end(_xscr_tok)

    def _fallback_subprocess_tab(self, host, primary_embed_path, slot_path=None):
        _clear_host_children(host)
        subprocess_path = _resolve_subprocess_script_path(slot_path, primary_embed_path)
        if not subprocess_path:
            msg = (
                u"Embedding failed and xNAVSL could not start a separate window.\n\n"
                u"Usually the slot pointed at a thin embed wrapper (no main program). Fix:\n"
                u"- Browse again and pick the real tool .py (not *_xnavsl_wrap.py), or\n"
                u"- In embed_overrides.json, set \"wrapper_for\" to the full path of the real script, or\n"
                u"- Open the wrapper file and check the _ORIGINAL = '...' line points to a valid file.\n\n"
                u"See OPTIONS A–C in the guide when embedding works but you want the tab UI.\n\n"
                u"Tried (embed path): %s\nSlot path: %s\n\nInterpreter:\n%s"
                % (
                    _as_unicode(primary_embed_path),
                    _as_unicode((slot_path or "").strip()),
                    _as_unicode(_python_for_tool_subprocess()),
                )
            )
        else:
            ex_base = os.path.basename(subprocess_path).lower()
            msg = (
                u"SEPARATE WINDOW (this is normal)\n"
                u"The tool did not draw inside this tab, so xNAVSL started it in its own window. "
                u"You can keep using it there.\n\n"
                u"WHY EMBED OFTEN FAILS\n"
                u"- The program builds its own main window (class ... Tk / tk.Tk()) instead of a panel "
                u"that can live inside a tab.\n"
                u"- Or nothing in the file tells xNAVSL how to build UI inside the tab.\n\n"
                u"---\n"
                u"OPTION A — HOOK IN THE TOOL SCRIPT (recommended)\n"
                u"Add def xnavsl_embed(master) in the same .py the slot opens (Python 2.7). This is the most "
                u"direct way to tell xNAVSL how to show the tool in the tab.\n\n"
                u"The tab area is passed as \"master\" — do not create a second tk.Tk() inside the hook.\n\n"
                u"If you are not editing Python yourself: give this to whoever maintains the script — they add "
                u"a function named exactly xnavsl_embed at the outer level of the file (same indentation as "
                u"other top-level def ...), and inside it they build your panel class that lives in a Frame, "
                u"not as a standalone root window.\n\n"
                u"MyPanel in the sample is a placeholder — replace it with the real class that builds the UI "
                u"in a Frame (e.g. xP1P2 uses QCAppPanel in the tab while QCApp(tk.Tk) is for running the file alone).\n\n"
                u"Sample for the programmer to adapt (Python 2.7, Tkinter):\n\n"
                u"def xnavsl_embed(master):\n"
                u"    import Tkinter as tk\n"
                u"    # Use your real panel class name here (must accept master= or one parent arg).\n"
                u"    app = MyPanel(master=master)\n"
                u"    app.pack(fill=tk.BOTH, expand=True)\n"
                u"    return app\n\n"
                u"Rules: the name xnavsl_embed must be exact; do not nest it inside def main; if the tool only "
                u"has a big tk.Tk app class, refactor so a frame-based panel exists first — the sample cannot be pasted alone.\n\n"
                u"OPTION B — Name the class in embed_overrides.json\n"
                u"Use when: the .py already has a class that builds its UI as a Tkinter Frame (or similar) "
                u"that can take the tab as parent, and you prefer JSON over editing the script hook.\n\n"
                u"Do this:\n"
                u"  1) Open this file in a text editor (create it empty if needed; name must be exact):\n"
                u"     embed_overrides.json\n"
                u"     Full path:\n"
                u"     %s\n"
                u"  2) The file must be one JSON object: start with { and end with }.\n"
                u"  3) Use this exact key (lowercase file name of the script):\n"
                u"     \"%s\"\n"
                u"  4) Under that key, set \"class\" to your Frame class name, and \"ctor\" to how the class\n"
                u"     is called (see below).\n\n"
                u"Copy-paste pattern (replace PutYourFrameClassNameHere with the real class name):\n"
                u"{\n"
                u"  \"%s\": {\n"
                u"    \"class\": \"PutYourFrameClassNameHere\",\n"
                u"    \"ctor\": \"master_kw\"\n"
                u"  }\n"
                u"}\n\n"
                u"If Browse already created an entry with \"run_path\" or \"wrapper_for\", do not delete those.\n"
                u"Add \"class\" and \"ctor\" next to them inside the same { } block for \"%s\".\n\n"
                u"ctor meaning:\n"
                u"  \"master_kw\"  -> the class is built like: YourClass(master=something)\n"
                u"  \"positional\" -> the class is built like: YourClass(something) with one parent argument only\n\n"
                u"OPTION C — Load a different .py than the slot path (run_path)\n"
                u"Use when: the button still points at an old path (e.g. site_scripts), but the code you want "
                u"lives in another file on disk (newer copy, different folder).\n\n"
                u"Do this:\n"
                u"  1) Same JSON file as Option B: embed_overrides.json at the path above.\n"
                u"  2) The key is still the script name the slot refers to (lowercase), here: \"%s\"\n"
                u"  3) Set \"run_path\" to the full path of the .py file xNAVSL should load instead.\n\n"
                u"Example (replace the path with your real file):\n"
                u"  \"%s\": {\n"
                u"    \"run_path\": \"/full/path/to/the/actual_script.py\"\n"
                u"  }\n\n"
                u"You can combine B and C: same key can have both \"run_path\" and \"class\"/\"ctor\" if needed.\n\n"
                u"If none of the above fixes embedding, you do not need another setting: xNAVSL already falls back "
                u"to starting the tool in its own window (what you see now).\n\n"
                u"AUTO WRAPPER\n"
                u"xNAVSL also writes a thin file under %s and merges embed_overrides.json when you "
                u"Browse or load a slot path (helps routing; it does not fix a pure Tk() app by itself).\n\n"
                u"Launched with:\n%s\n\nInterpreter:\n%s"
                % (
                    _as_unicode(EMBED_OVERRIDES_FILE),
                    _as_unicode(ex_base),
                    _as_unicode(ex_base),
                    _as_unicode(ex_base),
                    _as_unicode(ex_base),
                    _as_unicode(ex_base),
                    _as_unicode(WRAPPERS_DIR),
                    _as_unicode(subprocess_path),
                    _as_unicode(_python_for_tool_subprocess()),
                )
            )
        msg += _standalone_script_note(_as_unicode(os.path.basename(subprocess_path or primary_embed_path or "")))
        # ScrolledText + Font can fail on some Tk builds; always leave a visible Label as well.
        hdr = tk.Label(
            host,
            text="Running in separate window (see below)",
            bg=color_blue_aura_bg,
            fg=color_header_text,
            font=self._btn_font,
            anchor="w",
        )
        hdr.pack(fill=tk.X, padx=8, pady=(8, 4))
        txt = None
        try:
            txt = ScrolledText.ScrolledText(
                host,
                height=18,
                wrap=tk.WORD,
                bg="#f5f8fc",
                fg=color_text_dark,
                relief=tk.SUNKEN,
                borderwidth=1,
            )
            try:
                txt.config(font=self._btn_font)
            except Exception:
                pass
            txt.insert(tk.END, msg)
            txt.config(state=tk.DISABLED)
            txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        except Exception:
            if txt is not None:
                try:
                    txt.destroy()
                except Exception:
                    pass
            fb = tk.Label(
                host,
                text=msg,
                justify=tk.LEFT,
                anchor="nw",
                bg=color_blue_aura_bg,
                fg=color_text_dark,
            )
            fb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        if subprocess_path:
            try:
                proc = subprocess.Popen(
                    [_python_for_tool_subprocess(), subprocess_path],
                    cwd=os.path.dirname(os.path.abspath(subprocess_path)) or None,
                )
                host.attach_tool_subprocess(proc)
            except Exception as ex:
                tkMessageBox.showerror("Launch error", "Could not start process:\n%s" % ex)

    def _shutdown_embed_host(self, host):
        """In-process: WM_DELETE cleanup; separate-window: terminate Popen child."""
        if not isinstance(host, EmbedHost):
            return
        try:
            host.run_wm_delete()
        except Exception:
            pass
        try:
            host.terminate_tool_subprocess()
        except Exception:
            pass

    def close_current_tab(self):
        if self.notebook is None:
            return
        try:
            tab = self.notebook.select()
        except tk.TclError:
            return
        if not tab:
            return
        try:
            outer = self.root.nametowidget(tab)
        except tk.TclError:
            return
        for host in outer.winfo_children():
            if isinstance(host, EmbedHost):
                self._shutdown_embed_host(host)
                break
        try:
            self.notebook.forget(outer)
            outer.destroy()
        except tk.TclError:
            pass

    def on_root_close(self):
        if self.notebook is not None:
            try:
                for tab in list(self.notebook.tabs()):
                    outer = self.root.nametowidget(tab)
                    for host in outer.winfo_children():
                        if isinstance(host, EmbedHost):
                            self._shutdown_embed_host(host)
                            break
            except tk.TclError:
                pass
        if self.current_config_path:
            try:
                with open(self.current_config_path, "w") as f:
                    json.dump(self.build_config_dict(), f, indent=2)
            except Exception:
                pass
        self._write_session()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def embed_into_host(host, script_path, tab_title=None):
    """
    Public API for generated wrapper scripts: run the same embed pipeline as a slot Launch
    (heuristics, overrides, hooks, autodiscover). Requires xNAVSL main window already running.
    When the app is started as "python xNAVSL.py", the running module is __main__; a second
    "import xNAVSL" loads a duplicate module unless __main__ is aliased as xNAVSL. We resolve
    the mediator singleton from __main__ if needed.
    """
    m = getattr(NavSLMediator, "_instance", None)
    if m is None:
        main_mod = sys.modules.get("__main__")
        if main_mod is not None:
            nm = getattr(main_mod, "NavSLMediator", None)
            if nm is not None:
                m = getattr(nm, "_instance", None)
    if m is None:
        return False
    title = tab_title if tab_title else os.path.basename(script_path)
    return m._try_embed(host, script_path, title)


def main():
    _init_config_paths()
    try:
        if not os.path.isdir(DEFAULT_CONFIG_DIR):
            os.makedirs(DEFAULT_CONFIG_DIR)
    except Exception:
        pass
    try:
        sys.modules.setdefault("xNAVSL", sys.modules["__main__"])
    except Exception:
        pass

    root = tk.Tk()
    mediator = NavSLMediator(root)
    root.title("xNAVSL-PROMAX")
    root.configure(bg=color_blue_aura_bg)
    root.protocol("WM_DELETE_WINDOW", mediator.on_root_close)

    default_font = tkFont.nametofont("TkDefaultFont")
    italic_font_slant = tkFont.Font(
        family=default_font.actual("family"),
        size=default_font.actual("size"),
        slant="italic",
    )
    mediator._btn_font = tkFont.Font(
        family=default_font.actual("family"),
        size=default_font.actual("size"),
        weight="bold",
    )
    _bsz = mediator._btn_font.actual("size")
    mediator._slot_side_font = tkFont.Font(
        family=default_font.actual("family"),
        size=max(7, int(round(_bsz * 0.85))),
    )
    header_label_font = tkFont.Font(family="Helvetica", size=16, weight="bold")

    header_label = tk.Label(
        root,
        text="NAV SL xTools",
        font=header_label_font,
        bg=color_blue_aura_bg,
        fg=color_header_text,
    )
    header_label.pack(pady=10, padx=10, fill=tk.X)

    goal_text = "My GOAL is to create an Army of Me"
    goal_label = tk.Label(
        root,
        text=goal_text,
        font=italic_font_slant,
        bg=color_blue_aura_bg,
        fg=color_goal_text_fg,
    )
    goal_label.pack(pady=(5, 10), anchor="w", padx=10)

    paned = tk.PanedWindow(
        root,
        orient=tk.HORIZONTAL,
        sashwidth=5,
        bg=color_blue_aura_bg,
        relief=tk.FLAT,
    )
    paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    left = tk.Frame(paned, bg=color_blue_aura_bg, width=300)
    right = tk.Frame(paned, bg=color_blue_aura_bg)
    paned.add(left, minsize=260, stretch="never")
    paned.add(right, minsize=380, stretch="always")

    tk.Label(left, text="Configuration Name", bg=color_blue_aura_bg, fg=color_text_dark, font=mediator._btn_font).pack(
        anchor="w", padx=8, pady=(4, 2)
    )
    config_row = tk.Frame(left, bg=color_blue_aura_bg)
    config_row.pack(fill=tk.X, padx=8, pady=(0, 6))
    cfg_entry = tk.Entry(config_row, textvariable=mediator.config_name_var)
    mediator._config_name_entry = cfg_entry
    cfg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
    save_cfg_b = tk.Button(
        config_row,
        text="Save",
        command=mediator.save_config,
        bg=color_button_bg,
        fg=color_text_on_button,
        activebackground=color_button_active_bg,
        font=mediator._btn_font,
        padx=8,
        pady=2,
    )
    save_cfg_b.pack(side=tk.RIGHT, padx=(4, 0))
    browse_cfg_b = tk.Button(
        config_row,
        text="Browse/Select",
        command=mediator.browse_config,
        bg=color_button_bg,
        fg=color_text_on_button,
        activebackground=color_button_active_bg,
        font=mediator._btn_font,
        padx=6,
        pady=2,
    )
    browse_cfg_b.pack(side=tk.RIGHT, padx=(4, 0))

    tk.Label(left, text="Add Number of Buttons", bg=color_blue_aura_bg, fg=color_text_dark, font=mediator._btn_font).pack(
        anchor="w", padx=8, pady=(4, 2)
    )
    count_row = tk.Frame(left, bg=color_blue_aura_bg)
    count_row.pack(fill=tk.X, padx=8, pady=(0, 6))
    add_ent = tk.Entry(count_row, textvariable=mediator.add_count_var, width=8)
    add_ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
    add_b = tk.Button(
        count_row,
        text="Add",
        command=mediator.add_slot_buttons,
        bg=color_button_bg,
        fg=color_text_on_button,
        activebackground=color_button_active_bg,
        font=mediator._btn_font,
        padx=8,
        pady=2,
    )
    add_b.pack(side=tk.LEFT, padx=(8, 0))
    delete_all_b = tk.Button(
        count_row,
        text="Delete All",
        command=mediator._confirm_delete_all_slots,
        bg=color_button_bg,
        fg=color_text_on_button,
        activebackground=color_button_active_bg,
        font=mediator._btn_font,
        padx=8,
        pady=2,
    )
    delete_all_b.pack(side=tk.RIGHT)
    tk.Label(
        left,
        text="Note: Right Click to Sort/Delete Buttons",
        bg=color_blue_aura_bg,
        fg=color_goal_text_fg,
        font=getattr(mediator, "_slot_side_font", mediator._btn_font),
        anchor="w",
    ).pack(anchor="w", padx=8, pady=(0, 6))

    left_canvas_holder = tk.Frame(left, bg=color_blue_aura_bg)
    left_canvas_holder.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
    lc = tk.Canvas(left_canvas_holder, bg=color_blue_aura_bg, highlightthickness=0)
    lsb = tk.Scrollbar(left_canvas_holder, orient="vertical", command=lc.yview)
    slots_inner = tk.Frame(lc, bg=color_blue_aura_bg)

    def _on_inner_configure(event):
        lc.configure(scrollregion=lc.bbox("all"))

    slots_inner.bind("<Configure>", _on_inner_configure)
    win_inner = lc.create_window((0, 0), window=slots_inner, anchor="nw")

    def _on_canvas_configure(event):
        lc.itemconfig(win_inner, width=event.width)

    lc.bind("<Configure>", _on_canvas_configure)
    lc.configure(yscrollcommand=lsb.set)
    lc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    lsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_mousewheel_windows(event):
        if event.delta:
            lc.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux_up(_event):
        lc.yview_scroll(-1, "units")

    def _on_mousewheel_linux_down(_event):
        lc.yview_scroll(1, "units")

    lc.bind("<MouseWheel>", _on_mousewheel_windows)
    lc.bind("<Button-4>", _on_mousewheel_linux_up)
    lc.bind("<Button-5>", _on_mousewheel_linux_down)

    right.rowconfigure(0, weight=0)
    right.rowconfigure(1, weight=1)
    right.columnconfigure(0, weight=1)

    display_header = tk.Frame(right, bg=color_blue_aura_bg)
    display_header.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 4))
    tk.Label(
        display_header,
        text="Gui Display",
        bg=color_blue_aura_bg,
        fg=color_header_text,
        font=header_label_font,
    ).pack(side=tk.LEFT)
    close_tab_b = tk.Button(
        display_header,
        text="Close Tab",
        command=mediator.close_current_tab,
        bg=color_button_bg,
        fg=color_text_on_button,
        activebackground=color_button_active_bg,
        font=mediator._btn_font,
        padx=10,
        pady=2,
    )
    close_tab_b.pack(side=tk.RIGHT)
    hide_left_b = tk.Button(
        display_header,
        textvariable=mediator.hide_left_pane_btn_var,
        command=mediator.toggle_left_pane,
        bg=color_button_bg,
        fg=color_text_on_button,
        activebackground=color_button_active_bg,
        font=mediator._btn_font,
        padx=10,
        pady=2,
    )
    hide_left_b.pack(side=tk.RIGHT, padx=(0, 6))

    _nb_style = ttk.Style()
    try:
        _nb_style.theme_use("clam")
    except tk.TclError:
        try:
            _nb_style.theme_use("alt")
        except tk.TclError:
            pass
    _apply_navsl_shell_notebook_theme(_nb_style, mediator._btn_font)

    nb = ttk.Notebook(right, style=_NAVSL_SHELL_NB_STYLE)
    nb.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))

    mediator.set_widgets(nb, slots_inner, paned, left_pane=left, right_pane=right)
    mediator.load_session_on_startup()

    root.minsize(720, 480)
    root.mainloop()


_init_config_paths()


if __name__ == "__main__":
    main()
