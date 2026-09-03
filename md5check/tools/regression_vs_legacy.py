#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Differential regression harness: legacy md5check.py vs md5check_live.py.

Runs the ORIGINAL script and the NEW service over byte-identical inputs and
compares the five columns they share, scenario by scenario:

    Sequence Number / P1 Final / NAV MD5SUM / OBP MD5SUM / MD5SUM XCHECK

A difference is a REGRESSION unless it is an explicitly declared enhancement,
in which case the scenario says so and the harness checks the difference is
exactly the declared one. Anything else fails.

    python2.7 tools/regression_vs_legacy.py --legacy /path/to/md5check.py

The legacy script is Python 2.7 only, so this harness runs under 2.7 and
invokes the new service with whichever interpreter is given (--new-python,
default python3) to also prove the two interpreters agree.
"""
from __future__ import print_function

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)

LEGACY_COLS = ["Sequence Number", "P1 Final", "NAV MD5SUM", "OBP MD5SUM",
               "MD5SUM XCHECK"]
# new CSV index -> legacy CSV index
NEW_TO_LEGACY = {0: 0, 5: 1, 6: 2, 7: 3, 8: 4}

RESULTS = []


# ------------------------------------------------------------- P1 builders --

def p111(seq, line, sub, first, last, shots=5, extra_header=()):
    """A minimal but realistic OGP P1/11 file."""
    out = ["OGP,OGP P1,1,1.1,9,2026:03:07,05:28:39,%04d.p111,Shearwater" % seq,
           "HC,0,1,0,Project Name                                      ,NC21,TT,2026:02:16,",
           "CC,1,0,0,LINENAME/SUBLINE = /%s/%s" % (line, sub),
           "CC,1,0,0,LINE PREFIX = T26A",
           "CC,1,0,0,LINE SEQUENCE NUMBER = %04d" % seq]
    out.extend(extra_header)
    step = (last - first) // max(1, shots - 1)
    for i in range(shots):
        sp = last if i == shots - 1 else first + step * i
        out.append("S1,0,%s,%d,%d,%d,1,145534870%d.084000,5,G03,4,,401892.31,"
                   "1206127.02,7.82" % (line, seq, sp, sp, i))
        out.append("P1,0,%s,%d,%d,%d,1,145534870%d.084000,1,AWA,2,,401177.17,"
                   "1205745.94,,10.9,-57.9" % (line, seq, sp, sp, i))
    out.append("N1,0,1,1,%d,%d,%d" % (seq, min(first, last), max(first, last)))
    return "\n".join(out) + "\n"


def p190(seq, line, first, last, shots=5):
    """A production-shaped UKOOA P1/90 file: H headers, S and R records.

    Columns, 1-based: 1 id, 2-13 line name, 20-25 point, 26-35 latitude
    DDMMSS.SS[N|S], 36-46 longitude, 47-55 easting, 56-64 northing.
    """
    out = ["H0100 SURVEY AREA               Trinidad and Tobago",
           "H0102 VESSEL DETAILS            AMAZON WARRIOR             1",
           "H0103 SOURCE DETAILS            AIRGUN SOURCE              1   1",
           "H0200 SURVEY DATE               Feb 1, 2026",
           "H0300 CLIENT                    ExxonMobil",
           "H2600 SEQUENCE NUMBER           %04d" % seq]
    step = (last - first) // max(1, shots - 1)
    for i in range(shots):
        sp = last if i == shots - 1 else first + step * i
        lat = "1107%02d.92N" % (44 + i)
        lon = "0583249.78W"
        out.append("S%-12s%s%6d%s%s%9.1f%9.1f" %
                   (line, " " * 6, sp, lat, lon, 331037.2 + i, 1230699.6 + i))
        out.append("R%-12s%s%6d%s%s%9.1f%9.1f" %
                   (line, " " * 6, sp, lat, lon, 331040.2 + i, 1230702.6 + i))
    return "\n".join(out) + "\n"


def write(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    f = open(path, "wb")
    try:
        f.write(text.encode("utf-8") if not isinstance(text, bytes) else text)
    finally:
        f.close()


# ----------------------------------------------------------------- runners --

def run_legacy(legacy_src, nav, obp, out_csv, ranges, work):
    """Patch the legacy script's config exactly as install_md5check.sh did."""
    src = open(legacy_src, "rb").read().decode("utf-8", "replace")
    patched = []
    for line in src.split("\n"):
        if line.startswith("NAV_P1_DIR = "):
            line = 'NAV_P1_DIR = "%s"' % nav
        elif line.startswith("OBP_P1_DIR = "):
            line = 'OBP_P1_DIR = "%s"' % obp
        elif line.startswith("CACHE_FILE = "):
            line = 'CACHE_FILE = "%s"' % os.path.join(work, "legacy_cache.json")
        elif line.startswith("OUTPUT_HTML = "):
            line = 'OUTPUT_HTML = "%s"' % os.path.join(work, "legacy_report.html")
        elif line.startswith("OUTPUT_CSV = "):
            line = 'OUTPUT_CSV = "%s"' % out_csv
        elif line.startswith("SEQUENCE_RANGES_STR = "):
            line = 'SEQUENCE_RANGES_STR = "%s"' % ranges
        patched.append(line)
    script = os.path.join(work, "legacy_md5check.py")
    write(script, "\n".join(patched))
    p = subprocess.Popen([sys.executable, script],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = p.communicate()
    return p.returncode, out.decode("utf-8", "replace")


def run_new(new_python, nav, obp, out_dir, ranges, work, csv_name):
    cfg = {"bind": "127.0.0.1", "port": 6799,
           "check_interval_seconds": 60, "control_password": "x",
           "csv_name": csv_name, "journal_dir": os.path.join(work, "state"),
           "nav_p1_dir": nav, "obp_p1_dir": obp, "output_dir": out_dir,
           "running": False, "sequence_ranges": ranges}
    cfg_path = os.path.join(work, "config.json")
    write(cfg_path, json.dumps(cfg, indent=2, sort_keys=True))
    p = subprocess.Popen([new_python, os.path.join(APP, "md5check_live.py"),
                          "rebuild", "--config", cfg_path],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = p.communicate()
    return p.returncode, out.decode("utf-8", "replace")


def read_csv(path):
    if not os.path.exists(path):
        return None, []
    f = open(path, "rb")
    try:
        text = f.read().decode("utf-8", "replace")
    finally:
        f.close()
    rows = list(csv.reader(text.replace("\r\n", "\n").strip("\n").split("\n")))
    return (rows[0] if rows else []), rows[1:]


def project(header, rows, mapping):
    """{sequence: [the five legacy values]} from a CSV."""
    out = {}
    for r in rows:
        if not r:
            continue
        try:
            vals = [r[i] for i in sorted(mapping, key=lambda k: mapping[k])]
        except IndexError:
            vals = list(r)
        out[r[0]] = vals
    return out


# --------------------------------------------------------------- scenarios --

class Scenario(object):
    def __init__(self, name, build, ranges="", expect_extra=(), expect_note=""):
        self.name = name
        self.build = build            # build(nav, obp) -> None
        self.ranges = ranges
        # sequences the NEW tool reports that the legacy one does not, declared
        # up front as enhancements. Anything undeclared is a regression.
        self.expect_extra = set(expect_extra)
        self.expect_note = expect_note


def s_basic(nav, obp):
    for seq, line, sub, a, b in ((1, "3682A001", "c0001", 5471, 737),
                                 (2, "1702A002", "b0002", 1786, 3313),
                                 (3, "1018A003", "c0003", 2714, 1812)):
        text = p111(seq, line, sub, a, b)
        write(os.path.join(nav, "%04d.T26A.%s.%s.GFUNREG.VES.p111" % (seq, line, sub)), text)
        write(os.path.join(obp, "%04d.T26A.%s.%s.GFUNREG.VES.p111" % (seq, line, sub)), text)


def s_mismatch(nav, obp):
    s_basic(nav, obp)
    p = os.path.join(obp, "0002.T26A.1702A002.b0002.GFUNREG.VES.p111")
    write(p, open(p, "rb").read() + b"CC,1,0,0,EXTRA = 1\n")


def s_missing_obp(nav, obp):
    s_basic(nav, obp)
    os.remove(os.path.join(obp, "0002.T26A.1702A002.b0002.GFUNREG.VES.p111"))


def s_missing_nav(nav, obp):
    s_basic(nav, obp)
    os.remove(os.path.join(nav, "0003.T26A.1018A003.c0003.GFUNREG.VES.p111"))


def s_multiple_nav(nav, obp):
    s_basic(nav, obp)
    write(os.path.join(nav, "0002.T26A.1702A002.b0002.DUPLICATE.VES.p111"),
          p111(2, "1702A002", "b0002", 1786, 3313))


def s_multiple_obp(nav, obp):
    s_basic(nav, obp)
    write(os.path.join(obp, "0003.T26A.1018A003.c0003.DUPLICATE.VES.p111"),
          p111(3, "1018A003", "c0003", 2714, 1812))


def s_multiple_both(nav, obp):
    s_multiple_nav(nav, obp)
    write(os.path.join(obp, "0002.T26A.1702A002.b0002.DUPLICATE.VES.p111"),
          p111(2, "1702A002", "b0002", 1786, 3313))


def s_gap(nav, obp):
    for seq in (1, 2, 6, 7):
        text = p111(seq, "L%04d" % seq, "a%04d" % seq, 100, 900)
        name = "%04d.T26A.L%04d.a%04d.VES.p111" % (seq, seq, seq)
        write(os.path.join(nav, name), text)
        write(os.path.join(obp, name), text)


def s_p190(nav, obp):
    for seq, line, a, b in ((1, "1018", 2113, 7956), (2, "1054", 1974, 8015),
                            (3, "1090", 1001, 9450)):
        text = p190(seq, line, a, b)
        name = "%04d.T26A.%s.VES.p190" % (seq, line)
        write(os.path.join(nav, name), text)
        write(os.path.join(obp, name), text)


def s_p190_faults(nav, obp):
    s_p190(nav, obp)
    p = os.path.join(obp, "0002.T26A.1054.VES.p190")
    write(p, open(p, "rb").read() + b"H9999 EXTRA\n")          # mismatch
    os.remove(os.path.join(obp, "0003.T26A.1090.VES.p190"))    # missing
    write(os.path.join(nav, "0001.T26A.1018.DUP.p190"),
          p190(1, "1018", 2113, 7956))                          # multiple NAV


def s_mixed(nav, obp):
    s_basic(nav, obp)
    for seq, line, a, b in ((10, "1018", 2113, 7956), (11, "1054", 1974, 8015)):
        text = p190(seq, line, a, b)
        name = "%04d.T26A.%s.VES.p190" % (seq, line)
        write(os.path.join(nav, name), text)
        write(os.path.join(obp, name), text)


def s_noise(nav, obp):
    s_basic(nav, obp)
    write(os.path.join(nav, "readme.txt"), "not a p1 file\n")
    write(os.path.join(obp, "notes.log"), "also not a p1 file\n")
    write(os.path.join(nav, "preplot.p111"), p111(0, "X", "y", 1, 2))
    write(os.path.join(obp, "preplot.p111"), p111(0, "X", "y", 1, 2))


def s_empty(nav, obp):
    pass


def s_upper_ext(nav, obp):
    s_basic(nav, obp)
    text = p111(4, "9999A004", "d0004", 10, 90)
    write(os.path.join(nav, "0004.T26A.9999A004.d0004.VES.P111"), text)
    write(os.path.join(obp, "0004.T26A.9999A004.d0004.VES.P111"), text)


def s_zero_byte(nav, obp):
    s_basic(nav, obp)
    write(os.path.join(nav, "0005.T26A.EMPTY.a0005.VES.p111"), "")
    write(os.path.join(obp, "0005.T26A.EMPTY.a0005.VES.p111"), "")


SCENARIOS = [
    Scenario("P111 all matching", s_basic),
    Scenario("P111 one mismatch", s_mismatch),
    Scenario("P111 missing on OBP", s_missing_obp),
    Scenario("P111 missing on NAV", s_missing_nav),
    Scenario("P111 multiple on NAV", s_multiple_nav),
    Scenario("P111 multiple on OBP", s_multiple_obp),
    Scenario("P111 multiple on BOTH", s_multiple_both),
    Scenario("P111 gap in the middle", s_gap),
    Scenario("P190 all matching", s_p190),
    Scenario("P190 mismatch + missing + multiple", s_p190_faults),
    Scenario("mixed P111 and P190", s_mixed),
    Scenario("non-P1 files and an unnumbered P1", s_noise),
    Scenario("both directories empty", s_empty),
    Scenario("zero-byte P1 file", s_zero_byte),
    Scenario("uppercase .P111 extension", s_upper_ext,
             expect_extra=["0004"],
             expect_note="legacy endswith() is case-sensitive and skips .P111"),

    Scenario("ranges: single segment", s_gap, ranges="1-7"),
    Scenario("ranges: segment past the data", s_gap, ranges="1-20"),
    Scenario("ranges: two segments", s_gap, ranges="1-2, 6-7"),
    Scenario("ranges: bare numbers", s_gap, ranges="1, 6"),
    Scenario("ranges: segment with no data at all", s_gap, ranges="1-2, 50-53"),
    Scenario("ranges: order reversed in the string", s_gap, ranges="6-7, 1-2"),
    Scenario("ranges: single number", s_gap, ranges="6"),
    Scenario("ranges over P190", s_p190_faults, ranges="1-3"),
]


def s_big_gap(nav, obp):
    """A gap far wider than AUTO_MAX_GAP. Legacy fills every integer between."""
    for seq in (1, 2, 3190):
        text = p111(seq, "L%04d" % seq, "a%04d" % seq, 100, 900)
        name = "%04d.T26A.L%04d.a%04d.VES.p111" % (seq, seq, seq)
        write(os.path.join(nav, name), text)
        write(os.path.join(obp, name), text)


def s_five_digit(nav, obp):
    """Legacy keys on base[:4], so 10001 and 10002 BOTH become '1000' and the
    two different files get compared against each other."""
    for seq, line in ((10001, "AAAA"), (10002, "BBBB")):
        text = p111(seq % 10000, line, "a0001", 100, 900)
        name = "%d.T26A.%s.a0001.VES.p111" % (seq, line)
        write(os.path.join(nav, name), text)
        write(os.path.join(obp, name), text)


def s_unreadable(nav, obp):
    s_basic(nav, obp)
    for d in (nav, obp):
        p = os.path.join(d, "0004.T26A.SECRET.a0004.VES.p111")
        write(p, p111(4, "SECRET", "a0004", 10, 90))
    os.chmod(os.path.join(nav, "0004.T26A.SECRET.a0004.VES.p111"), 0)


def s_symlinked_obp(nav, obp):
    s_basic(nav, obp)
    for name in sorted(os.listdir(obp)):
        os.remove(os.path.join(obp, name))
    for name in sorted(os.listdir(nav)):
        os.symlink(os.path.join(nav, name), os.path.join(obp, name))


def s_p190_preplot(nav, obp):
    """V records only - no S records at all."""
    for seq, line in ((1, "1018"), (2, "1054")):
        out = ["H0100 SURVEY AREA               Trinidad"]
        for sp in (2113, 7956):
            out.append("V%-12s%s%6d%s%s%9.1f%9.1f"
                       % (line, " " * 6, sp, "110744.92N", "0583249.78W",
                          331037.2, 1230699.6))
        text = chr(10).join(out) + chr(10)
        name = "%04d.T26A.%s.VES.p190" % (seq, line)
        write(os.path.join(nav, name), text)
        write(os.path.join(obp, name), text)


def s_boundary_seq(nav, obp):
    for seq in (9998, 9999):
        text = p111(seq, "L%04d" % seq, "a%04d" % seq, 100, 900)
        name = "%04d.T26A.L%04d.a%04d.VES.p111" % (seq, seq, seq)
        write(os.path.join(nav, name), text)
        write(os.path.join(obp, name), text)


SCENARIOS.extend([
    Scenario("gap wider than AUTO_MAX_GAP", s_big_gap),
    Scenario("5-digit sequence filenames", s_five_digit),
    Scenario("unreadable file (chmod 000) on NAV", s_unreadable),
    Scenario("OBP is symlinks to NAV", s_symlinked_obp),
    Scenario("P190 preplot, V records only", s_p190_preplot),
    Scenario("sequences at the 4-digit boundary", s_boundary_seq),
    Scenario("ranges over the big gap", s_big_gap, ranges="1-3190"),
])


# ------------------------------------------------------------------- main --

def compare(name, legacy_map, new_map, expect_extra, note):
    problems = []
    legacy_seqs = set(legacy_map)
    new_seqs = set(new_map)

    missing = sorted(legacy_seqs - new_seqs)
    if missing:
        problems.append("REGRESSION: sequences the legacy tool reported and the "
                        "new one does not: %s" % ", ".join(missing))

    extra = sorted(new_seqs - legacy_seqs)
    undeclared = [e for e in extra if e not in expect_extra]
    if undeclared:
        problems.append("REGRESSION: sequences the new tool invented: %s"
                        % ", ".join(undeclared))
    declared = [e for e in extra if e in expect_extra]
    if expect_extra and set(declared) != set(expect_extra):
        problems.append("declared enhancement did not appear: expected extra %s, got %s"
                        % (sorted(expect_extra), declared))

    for seq in sorted(legacy_seqs & new_seqs):
        lv, nv = legacy_map[seq], new_map[seq]
        for i, col in enumerate(LEGACY_COLS):
            if lv[i] != nv[i]:
                problems.append("REGRESSION: seq %s column %r: legacy %r, new %r"
                                % (seq, col, lv[i], nv[i]))
    return problems, extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", required=True, help="path to the original md5check.py")
    ap.add_argument("--new-python", default="python3")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    if sys.version_info[0] != 2:
        print("NOTE: the legacy script is Python 2 only; run this harness with "
              "python2.7 so it can execute it.")
        return 2

    root = tempfile.mkdtemp(prefix="md5regress_")
    failures = 0
    print("legacy    : %s" % args.legacy)
    print("new       : %s (%s)" % (os.path.join(APP, "md5check_live.py"),
                                   args.new_python))
    print("workdir   : %s" % root)
    print("")

    for idx, sc in enumerate(SCENARIOS):
        work = os.path.join(root, "sc%02d" % idx)
        nav = os.path.join(work, "nav")
        obp = os.path.join(work, "obp")
        os.makedirs(nav)
        os.makedirs(obp)
        sc.build(nav, obp)

        legacy_csv = os.path.join(work, "legacy.csv")
        new_dir = os.path.join(work, "newout")
        rc_l, out_l = run_legacy(args.legacy, nav, obp, legacy_csv, sc.ranges, work)
        rc_n, out_n = run_new(args.new_python, nav, obp, new_dir, sc.ranges,
                              work, "new.csv")

        lh, lrows = read_csv(legacy_csv)
        nh, nrows = read_csv(os.path.join(new_dir, "new.csv"))
        legacy_map = project(lh, lrows, dict((i, i) for i in range(5)))
        new_map = project(nh, nrows, NEW_TO_LEGACY)

        problems, extra = compare(sc.name, legacy_map, new_map,
                                  sc.expect_extra, sc.expect_note)
        if rc_l != 0:
            problems.append("legacy script exited %d:\n%s" % (rc_l, out_l[-400:]))
        if rc_n != 0:
            problems.append("new service exited %d:\n%s" % (rc_n, out_n[-400:]))

        label = "%-42s ranges=%-12r legacy=%-3d new=%-3d" % (
            sc.name, sc.ranges, len(legacy_map), len(new_map))
        if problems:
            failures += 1
            print("FAIL  %s" % label)
            for p in problems:
                print("        %s" % p)
        else:
            note = ""
            if extra:
                note = "  [+%s: %s]" % (",".join(extra), sc.expect_note)
            print("ok    %s%s" % (label, note))

    print("")
    print("-" * 78)
    if failures:
        print("FAILED: %d of %d scenarios differ from the legacy tool"
              % (failures, len(SCENARIOS)))
    else:
        print("OK: all %d scenarios byte-match the legacy tool on its five columns"
              % len(SCENARIOS))
    if args.keep:
        print("workdir kept: %s" % root)
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
