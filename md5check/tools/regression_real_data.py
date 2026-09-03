#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Runs the legacy md5check.py and md5check_live.py over REAL P1 directories and
compares everything they both produce:

  * the five shared CSV columns, row for row
  * the "Please CHECK Sequence(s)" set - legacy renders it into its HTML
    report, the new service exposes it as health["attention"] and as the
    banner on the page. They must name the same sequences.

    python2.7 tools/regression_real_data.py --nav DIR --obp DIR [--ranges STR]

Python 2.7 only, because the legacy script is.
"""
from __future__ import print_function

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
LEGACY_COLS = ["Sequence Number", "P1 Final", "NAV MD5SUM", "OBP MD5SUM",
               "MD5SUM XCHECK"]
NEW_IDX = [0, 5, 6, 7, 8]

WARN_RE = re.compile(r'<span class="warning">([^<]+)</span>')


def write(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    f = open(path, "wb")
    try:
        f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
    finally:
        f.close()


def read_rows(path, idx):
    if not os.path.exists(path):
        return {}
    f = open(path, "rb")
    try:
        text = f.read().decode("utf-8", "replace")
    finally:
        f.close()
    rows = list(csv.reader(text.replace("\r\n", "\n").strip("\n").split("\n")))
    out = {}
    for r in rows[1:]:
        if r:
            out[r[0]] = [r[i] for i in idx]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", default=os.path.join(os.path.dirname(APP),
                                                     "md5check.py"))
    ap.add_argument("--nav", required=True)
    ap.add_argument("--obp", required=True)
    ap.add_argument("--ranges", default="")
    ap.add_argument("--new-python", default="python3")
    args = ap.parse_args()

    if sys.version_info[0] != 2:
        print("run this with python2.7 - the legacy script is Python 2 only")
        return 2

    work = tempfile.mkdtemp(prefix="md5real_")
    try:
        print("NAV    : %s" % args.nav)
        print("OBP    : %s" % args.obp)
        print("ranges : %r" % args.ranges)
        print("")

        # ---- legacy ----
        src = open(args.legacy, "rb").read().decode("utf-8", "replace")
        patched = []
        legacy_csv = os.path.join(work, "legacy.csv")
        legacy_html = os.path.join(work, "legacy.html")
        for line in src.split("\n"):
            for key, val in (("NAV_P1_DIR", args.nav), ("OBP_P1_DIR", args.obp),
                             ("CACHE_FILE", os.path.join(work, "legacy_cache.json")),
                             ("OUTPUT_HTML", legacy_html),
                             ("OUTPUT_CSV", legacy_csv),
                             ("SEQUENCE_RANGES_STR", args.ranges)):
                if line.startswith(key + " = "):
                    line = '%s = "%s"' % (key, val)
                    break
            patched.append(line)
        script = os.path.join(work, "legacy.py")
        write(script, "\n".join(patched))
        t0 = os.times()
        p = subprocess.Popen([sys.executable, script],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, _ = p.communicate()
        print("legacy exit=%d" % p.returncode)
        if p.returncode:
            print(out.decode("utf-8", "replace")[-800:])
            return 1

        # ---- new ----
        cfg = {"bind": "127.0.0.1", "port": 6798, "check_interval_seconds": 60,
               "control_password": "x", "csv_name": "new.csv",
               "journal_dir": os.path.join(work, "state"),
               "nav_p1_dir": args.nav, "obp_p1_dir": args.obp,
               "output_dir": os.path.join(work, "newout"),
               "html_report_path": os.path.join(work, "new.html"),
               "running": False, "sequence_ranges": args.ranges}
        cfg_path = os.path.join(work, "config.json")
        write(cfg_path, json.dumps(cfg, indent=2, sort_keys=True))
        p = subprocess.Popen([args.new_python,
                              os.path.join(APP, "md5check_live.py"),
                              "rebuild", "--config", cfg_path],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out_new, _ = p.communicate()
        print("new    exit=%d" % p.returncode)
        if p.returncode:
            print(out_new.decode("utf-8", "replace")[-800:])
            return 1

        legacy = read_rows(legacy_csv, [0, 1, 2, 3, 4])
        new = read_rows(os.path.join(work, "newout", "new.csv"), NEW_IDX)

        print("")
        print("rows: legacy=%d new=%d" % (len(legacy), len(new)))

        problems = []
        for seq in sorted(set(legacy) - set(new)):
            problems.append("REGRESSION: legacy reported %s, new did not" % seq)
        for seq in sorted(set(new) - set(legacy)):
            problems.append("EXTRA: new reported %s, legacy did not" % seq)
        for seq in sorted(set(legacy) & set(new)):
            for i, col in enumerate(LEGACY_COLS):
                if legacy[seq][i] != new[seq][i]:
                    problems.append("REGRESSION: %s %r legacy=%r new=%r"
                                    % (seq, col, legacy[seq][i], new[seq][i]))

        # ---- the "Please CHECK Sequence(s)" set ----
        legacy_warn = set()
        if os.path.exists(legacy_html):
            f = open(legacy_html, "rb")
            try:
                html = f.read().decode("utf-8", "replace")
            finally:
                f.close()
            legacy_warn = set(WARN_RE.findall(html))

        # Ask the NEW service what IT flags - do not re-derive it here, or the
        # harness would be testing its own opinion instead of the tool's.
        new_warn = set()
        for line in out_new.decode("utf-8", "replace").splitlines():
            if line.startswith("ATTENTION:"):
                body = line.split(":", 1)[1].strip()
                if body and body != "none":
                    new_warn = set(x.strip() for x in body.split(","))
        legacy_warn_from_csv = set(seq for seq, vals in legacy.items()
                                   if vals[4] != "MD5SUM_MATCHING")

        print("attention set: legacy HTML=%d, legacy CSV-derived=%d, new=%d"
              % (len(legacy_warn), len(legacy_warn_from_csv), len(new_warn)))
        if legacy_warn and legacy_warn != new_warn:
            only_l = sorted(legacy_warn - new_warn)
            only_n = sorted(new_warn - legacy_warn)
            if only_l:
                problems.append("REGRESSION: legacy flagged %s, new did not"
                                % ", ".join(only_l[:20]))
            if only_n:
                problems.append("EXTRA: new flagged %s, legacy did not"
                                % ", ".join(only_n[:20]))

        # ---- the static HTML report ----
        new_html_path = os.path.join(work, "new.html")
        if os.path.exists(legacy_html) and os.path.exists(new_html_path):
            def cells(path):
                f = open(path, "rb")
                try:
                    h = f.read().decode("utf-8", "replace")
                finally:
                    f.close()
                return (re.findall(r"<tr><td>(.*?)</tr>", h),
                        set(WARN_RE.findall(h)))
            lrowsh, lwarn = cells(legacy_html)
            nrowsh, nwarn = cells(new_html_path)
            print("html report: legacy rows=%d new rows=%d; warning spans "
                  "legacy=%d new=%d" % (len(lrowsh), len(nrowsh),
                                        len(lwarn), len(nwarn)))
            if len(lrowsh) != len(nrowsh):
                problems.append("REGRESSION: html report row count differs "
                                "(legacy %d, new %d)" % (len(lrowsh), len(nrowsh)))
            else:
                for i, (a, b) in enumerate(zip(lrowsh, nrowsh)):
                    if a != b:
                        problems.append(
                            "REGRESSION: html row %d differs:"
                            "\n      legacy %s\n      new    %s"
                            % (i, a[:150], b[:150]))
                        break
            if lwarn != nwarn:
                problems.append("REGRESSION: html warning spans differ: "
                                "legacy=%s new=%s"
                                % (sorted(lwarn)[:10], sorted(nwarn)[:10]))
        elif os.path.exists(legacy_html) and not os.path.exists(new_html_path):
            problems.append("REGRESSION: legacy wrote an HTML report, new did not")

        print("")
        if problems:
            print("FAILED (%d):" % len(problems))
            for x in problems[:40]:
                print("  %s" % x)
            if len(problems) > 40:
                print("  ... and %d more" % (len(problems) - 40))
            return 1
        print("OK: legacy and md5check_live agree on every row, every shared")
        print("    column, and the same set of sequences needing attention.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
