#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Standing regression suite for md5check_live's P1 parsing and scanning.

Runs anywhere, under Python 2.7 and 3.6+, with no arguments and no network:

    python  test_md5check.py
    python3 test_md5check.py

Every fixture is written to a temp directory and deleted afterwards. The point
of the nastier ones is that vessel deliveries are not clean: they arrive with
byte-order marks, CRLF or bare-CR endings, latin-1 bytes in a comment,
lowercase record tags, tabs, quoted fields, keys spelled a dozen ways, and
columns that have drifted. A field we cannot read must come out empty - never
an exception, and never a wrong value.
"""
from __future__ import print_function

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md5check_live as M   # noqa: E402


FAILURES = []
CHECKS = [0]


def check(name, got, want):
    CHECKS[0] += 1
    if got != want:
        FAILURES.append("%s\n     got:  %r\n     want: %r" % (name, got, want))
        print("  FAIL %s" % name)
        print("       got  %r" % (got,))
        print("       want %r" % (want,))
    return got == want


def section(title):
    print("\n== %s" % title)


# --------------------------------------------------------------- fixtures --

P111_HEADER = [
    "OGP,OGP P1,1,1.1,9,2026:03:07,05:28:39,0001.T26A.3682A001.c0001.GFUNREG.VES.p111,Shearwater",
    "HC,0,1,0,Project Name                                      ,NC21,TT Ultra-Deepwater-1 3D,2026:02:16,",
    "CC,1,0,0,LINENAME/SUBLINE = /3682A001/c0001",
    "CC,1,0,0,LINE-DIRECTION = 247.33",
    "CC,1,0,0,LINE PREFIX = T26A",
    "CC,1,0,0,LINE SEQUENCE NUMBER = 0001",
]


def s1(point, line="3682A001", extra=""):
    return ("S1,0,%s,3682,%s,%s,1,1455348700.084000,5,G03,4,,401892.31,"
            "1206127.02,7.82%s" % (line, point, point, extra))


def p1rec(point, line="3682A001"):
    return ("P1,0,%s,3682,%s,%s,1,1455348700.084000,1,AWA,2,,401177.17,"
            "1205745.94,,10.9,-57.9" % (line, point, point))


def p111_body(first=5471, last=737, n=6):
    """A shot block: one S1 then a few P1s, exactly like the real files."""
    out = []
    step = (last - first) // max(1, n - 1)
    for i in range(n):
        sp = first + step * i if i < n - 1 else last
        out.append(s1(sp))
        out.append(p1rec(sp))
        out.append(p1rec(sp))
    out.append("N1,0,1,1,3682,1042,5471")
    return out


def write(tmp, name, lines, sep="\n", encoding="utf-8", bom=False, raw=None):
    path = os.path.join(tmp, name)
    f = open(path, "wb")
    try:
        if bom:
            f.write(b"\xef\xbb\xbf")
        if raw is not None:
            f.write(raw)
        else:
            text = sep.join(lines) + sep
            f.write(text.encode(encoding, "replace"))
    finally:
        f.close()
    return path


def meta(path):
    return M.parse_p1_metadata(path)


# ------------------------------------------------------------- P1/11 tests --

def test_p111(tmp):
    section("P1/11 - baseline and dirt tolerance")

    p = write(tmp, "0001.T26A.3682A001.c0001.GFUNREG.VES.p111",
              P111_HEADER + p111_body())
    m = meta(p)
    check("baseline format", m["format"], "p111")
    check("baseline sequence", m["sequence"], "0001")
    check("baseline linename", m["linename"], "3682A001")
    check("baseline subline", m["subline"], "c0001")
    check("baseline prefix", m["prefix"], "T26A")
    check("baseline FSP", m["fsp"], 5471)
    check("baseline LSP", m["lsp"], 737)
    check("baseline no error", m["error"], "")

    # lower case everywhere - tags and keys
    lower = [ln.lower() for ln in P111_HEADER] + \
            [ln.lower() for ln in p111_body()]
    p = write(tmp, "0002.lower.p111", lower)
    m = meta(p)
    check("lowercase tags: format", m["format"], "p111")
    check("lowercase tags: linename", m["linename"], "3682a001")
    check("lowercase tags: subline", m["subline"], "c0001")
    check("lowercase tags: sequence", m["sequence"], "0001")
    check("lowercase tags: FSP", m["fsp"], 5471)
    check("lowercase tags: LSP", m["lsp"], 737)

    # padding whitespace around tags, keys and values
    spaced = [
        "  CC , 1,0,0,   LINENAME/SUBLINE   =   /3682A001/c0001   ",
        " CC ,1,0,0, LINE PREFIX  =  T26A  ",
        "CC ,1,0,0,  LINE SEQUENCE NUMBER =  0001 ",
    ] + [" " + ln for ln in p111_body()]
    p = write(tmp, "0003.spaced.p111", spaced)
    m = meta(p)
    check("padded whitespace: linename", m["linename"], "3682A001")
    check("padded whitespace: subline", m["subline"], "c0001")
    check("padded whitespace: sequence", m["sequence"], "0001")
    check("padded whitespace: FSP", m["fsp"], 5471)
    check("padded whitespace: LSP", m["lsp"], 737)

    # ':' instead of '=' as the key/value separator
    colon = [
        "CC,1,0,0,LINENAME/SUBLINE : /9001A007/d0007",
        "CC,1,0,0,LINE SEQUENCE NUMBER : 7",
    ] + p111_body(100, 200)
    p = write(tmp, "0007.colon.p111", colon)
    m = meta(p)
    check("colon separator: linename", m["linename"], "9001A007")
    check("colon separator: subline", m["subline"], "d0007")
    check("colon separator: sequence zero-padded", m["sequence"], "0007")

    # a vendor spelling the keys differently
    variant = [
        "CC,1,0,0,Line Name / Sub-Line = /4400A012/b0012",
        "CC,1,0,0,Seq No = 12",
        "CC,1,0,0,Line_Prefix = T26B",
    ] + p111_body(900, 100)
    p = write(tmp, "0012.variant.p111", variant)
    m = meta(p)
    check("key spelling variants: linename", m["linename"], "4400A012")
    check("key spelling variants: subline", m["subline"], "b0012")
    check("key spelling variants: sequence", m["sequence"], "0012")
    check("key spelling variants: prefix", m["prefix"], "T26B")

    # byte-order mark
    p = write(tmp, "0004.bom.p111", P111_HEADER + p111_body(), bom=True)
    m = meta(p)
    check("BOM: format", m["format"], "p111")
    check("BOM: linename", m["linename"], "3682A001")
    check("BOM: FSP", m["fsp"], 5471)

    # CRLF and bare-CR line endings
    for label, sep in (("CRLF", "\r\n"), ("bare CR", "\r")):
        p = write(tmp, "0005.%s.p111" % label.replace(" ", ""),
                  P111_HEADER + p111_body(), sep=sep)
        m = meta(p)
        check("%s: linename" % label, m["linename"], "3682A001")
        check("%s: FSP" % label, m["fsp"], 5471)
        check("%s: LSP" % label, m["lsp"], 737)

    # undecodable bytes in a comment must not derail the header scan
    raw = ("\n".join(P111_HEADER[:2]) + "\n").encode("utf-8") \
        + b"CC,1,0,0,VESSEL = Amaz\xf3n Warrior caf\xe9\n" \
        + ("\n".join(P111_HEADER[2:] + p111_body()) + "\n").encode("utf-8")
    p = write(tmp, "0006.latin1.p111", None, raw=raw)
    m = meta(p)
    check("latin-1 bytes: linename", m["linename"], "3682A001")
    check("latin-1 bytes: sequence", m["sequence"], "0001")
    check("latin-1 bytes: FSP", m["fsp"], 5471)
    check("latin-1 bytes: no error", m["error"], "")

    # a quoted comment body containing commas
    quoted = [
        'CC,1,0,0,"NOTE = a, b, c"',
        "CC,1,0,0,LINENAME/SUBLINE = /7100A020/a0020",
        'CC,1,0,0,LINE SEQUENCE NUMBER = "0020"',
    ] + p111_body(3000, 1500)
    p = write(tmp, "0020.quoted.p111", quoted)
    m = meta(p)
    check("quoted values: linename", m["linename"], "7100A020")
    check("quoted values: sequence", m["sequence"], "0020")
    check("quoted values: FSP", m["fsp"], 3000)
    check("quoted values: LSP", m["lsp"], 1500)

    # tabs inside the header block
    tabbed = ["CC,1,0,0,LINENAME/SUBLINE\t=\t/8100A030/c0030",
              "CC,1,0,0,LINE SEQUENCE NUMBER\t=\t30"] + p111_body(10, 90)
    p = write(tmp, "0030.tabs.p111", tabbed)
    m = meta(p)
    check("tabs: linename", m["linename"], "8100A030")
    check("tabs: subline", m["subline"], "c0030")
    check("tabs: sequence", m["sequence"], "0030")

    # backslash instead of forward slash in the linename/subline value
    p = write(tmp, "0031.backslash.p111",
              ["CC,1,0,0,LINENAME/SUBLINE = \\5500A031\\b0031"] + p111_body(1, 9))
    m = meta(p)
    check("backslash separator: linename", m["linename"], "5500A031")
    check("backslash separator: subline", m["subline"], "b0031")

    # only the linename half present
    p = write(tmp, "0032.halfonly.p111",
              ["CC,1,0,0,LINENAME/SUBLINE = /6600A032/"] + p111_body(2, 8))
    m = meta(p)
    check("missing subline half: linename", m["linename"], "6600A032")
    check("missing subline half: subline empty", m["subline"], "")

    section("P1/11 - re-ordered and degenerate files")

    # S1 columns shifted: the point number is no longer at field 4. The line
    # name anchors the search, so the first integer AFTER it must be taken.
    shifted = ["CC,1,0,0,LINENAME/SUBLINE = /3300A040/a0040"]
    for sp in (4100, 3000, 1200):
        shifted.append("S1,0,X,Y,Z,3300A040,%d,%d,1,1455348700.0,5,G03" % (sp, sp))
    p = write(tmp, "0040.shifted.p111", shifted)
    m = meta(p)
    check("shifted S1 columns: linename", m["linename"], "3300A040")
    check("shifted S1 columns: FSP", m["fsp"], 4100)
    check("shifted S1 columns: LSP", m["lsp"], 1200)

    # a preplot: header and N1/M1 records, no S1 at all
    preplot = P111_HEADER[:2] + ["N1,0,1,1,3682,1042,5471",
                                 "M1,0,1,1,1,1,388135.912,1207297.320,,10.9,-58.0,,"]
    p = write(tmp, "3190_preplot.WGS84.p111", preplot)
    m = meta(p)
    check("preplot: format", m["format"], "p111")
    check("preplot: FSP is empty not wrong", m["fsp"], None)
    check("preplot: LSP is empty not wrong", m["lsp"], None)
    check("preplot: no error", m["error"], "")

    # empty file
    p = write(tmp, "0050.empty.p111", [], raw=b"")
    m = meta(p)
    check("empty file: no crash", m["error"], "")
    check("empty file: format from extension", m["format"], "p111")
    check("empty file: FSP", m["fsp"], None)
    check("empty file: sequence from name", m["sequence"], "0050")

    # binary garbage that happens to carry a P1 extension
    p = write(tmp, "0051.garbage.p111", None,
              raw=b"\x00\x01\x02\xff\xfe" * 500)
    m = meta(p)
    check("binary garbage: no crash", m["error"], "")
    check("binary garbage: FSP", m["fsp"], None)

    # header only, truncated mid-record
    p = write(tmp, "0052.trunc.p111", None,
              raw=b"OGP,OGP P1,1,1.1\nCC,1,0,0,LINENAME/SUBLINE = /1")
    m = meta(p)
    check("truncated: no crash", m["error"], "")
    check("truncated: linename", m["linename"], "1")

    # one enormous line must not blow up the window logic
    p = write(tmp, "0053.longline.p111",
              ["CC,1,0,0,NOTE = " + ("x" * 300000),
               "CC,1,0,0,LINENAME/SUBLINE = /2200A053/a0053"] + p111_body(5, 50))
    m = meta(p)
    check("300 KB line: no crash", m["error"], "")
    check("300 KB line: LSP still found", m["lsp"], 50)


# ------------------------------------------------------------- P1/90 tests --

def v190(ident, line, point, tail="110744.92N0583249.78W 331037.21230699.6"):
    """A UKOOA P1/90 record: id, line name in 2-13, point right-aligned 20-25."""
    return "%s%-12s%s%6s%s" % (ident, line, " " * 6, point, tail)


def test_p190(tmp):
    section("P1/90 - baseline and dirt tolerance")

    header = [
        "H0100 SURVEY AREA               Trinidad and Tobago",
        "H0200 SURVEY DATE               Feb 1, 2026",
        "H0300 CLIENT                    ExxonMobil",
    ]
    body = [v190("S", "1018", 2113), v190("S", "1018", 3000),
            v190("R", "1018", 2113), v190("S", "1018", 7956)]
    p = write(tmp, "0060.main.p190", header + body)
    m = meta(p)
    check("baseline format", m["format"], "p190")
    check("baseline linename", m["linename"], "1018")
    check("baseline FSP (S records)", m["fsp"], 2113)
    check("baseline LSP (S records)", m["lsp"], 7956)

    # lowercase record identifiers
    p = write(tmp, "0061.lower.p190",
              header + [ln[0].lower() + ln[1:] for ln in body])
    m = meta(p)
    check("lowercase ids: format", m["format"], "p190")
    check("lowercase ids: FSP", m["fsp"], 2113)
    check("lowercase ids: LSP", m["lsp"], 7956)

    # only V records (a preplot) - the S preference must fall through to V
    p = write(tmp, "0062.preplot.p190",
              header + [v190("V", "6018", 1974), v190("V", "6018", 8015)])
    m = meta(p)
    check("V-only preplot: linename", m["linename"], "6018")
    check("V-only preplot: FSP", m["fsp"], 1974)
    check("V-only preplot: LSP", m["lsp"], 8015)

    # a line name containing spaces stays intact apart from the outer trim
    p = write(tmp, "0063.spacename.p190",
              header + [v190("S", "LINE 42 A", 100), v190("S", "LINE 42 A", 900)])
    m = meta(p)
    check("spaced line name", m["linename"], "LINE 42 A")
    check("spaced line name: FSP", m["fsp"], 100)

    # CRLF
    p = write(tmp, "0064.crlf.p190", header + body, sep="\r\n")
    m = meta(p)
    check("CRLF: FSP", m["fsp"], 2113)
    check("CRLF: LSP", m["lsp"], 7956)

    section("P1/90 - shifted columns and degenerate files")

    # the point number moved four columns right of the standard slot; the span
    # is inferred once and then used consistently for first AND last
    shifted = ["S%-12s%s%6s%s" % ("2020", " " * 10, sp,
                                  "110744.92N0583249.78W")
               for sp in (500, 1500, 2500)]
    p = write(tmp, "0065.shifted.p190", header + shifted)
    m = meta(p)
    check("shifted point column: linename", m["linename"], "2020")
    check("shifted point column: FSP", m["fsp"], 500)
    check("shifted point column: LSP", m["lsp"], 2500)

    # every record shifted right by stray leading whitespace
    p = write(tmp, "0068.leadspace.p190",
              header + ["   " + ln for ln in body])
    m = meta(p)
    check("leading whitespace: linename", m["linename"], "1018")
    check("leading whitespace: FSP", m["fsp"], 2113)
    check("leading whitespace: LSP", m["lsp"], 7956)

    # header-only file
    p = write(tmp, "0066.headeronly.p190", header)
    m = meta(p)
    check("header only: no crash", m["error"], "")
    check("header only: FSP", m["fsp"], None)

    # short/ragged records must be skipped, not crash
    p = write(tmp, "0067.short.p190",
              header + ["S1018", "S", "", v190("S", "1018", 4242)])
    m = meta(p)
    check("ragged records: FSP", m["fsp"], 4242)
    check("ragged records: no error", m["error"], "")


# ------------------------------------------------- filename / grouping tests --

def test_filenames():
    section("filename hints and sequence grouping")

    h = M.filename_hints("0001.T26A.3682A001.c0001.GFUNREG.VES.p111")
    check("dot-separated: sequence", h["sequence"], "0001")
    check("dot-separated: prefix", h["prefix"], "T26A")
    check("dot-separated: linename", h["linename"], "3682A001")
    check("dot-separated: subline", h["subline"], "c0001")

    h = M.filename_hints("0002_T26A_1702A002_b0002_GFUNREG.p111")
    check("underscore-separated: linename", h["linename"], "1702A002")
    check("underscore-separated: subline", h["subline"], "b0002")

    h = M.filename_hints("  0003-T26A-1018A003-c0003.P111  ")
    check("hyphen + padding: sequence", h["sequence"], "0003")
    check("hyphen + padding: subline", h["subline"], "c0003")

    check("strict key", M.sequence_key_from_name("0042.foo.p111"), "0042")
    check("strict key rejects letters", M.sequence_key_from_name("SEQ42.p111"), "")
    check("relaxed key", M.relaxed_sequence_key("SEQ42_line.p111"), "0042")
    check("relaxed key: none", M.relaxed_sequence_key("nodigits.p111"), "")

    check("uppercase extension accepted",
          "FILE.P111".strip().lower().endswith(M.P1_EXTENSIONS), True)


def test_scanner(tmp):
    section("scanner: verdicts, case, and consistent grouping")

    nav = os.path.join(tmp, "nav")
    obp = os.path.join(tmp, "obp")
    os.makedirs(nav)
    os.makedirs(obp)

    def put(d, name, first=100, last=900, line="1000A001", sub="a0001", seq="1"):
        return write(d, name,
                     ["CC,1,0,0,LINENAME/SUBLINE = /%s/%s" % (line, sub),
                      "CC,1,0,0,LINE SEQUENCE NUMBER = %s" % seq] +
                     p111_body(first, last))

    # 0001 matches on both sides, with a MIXED-CASE extension on one side
    put(nav, "0001.T26A.1000A001.a0001.VES.p111")
    put(obp, "0001.T26A.1000A001.a0001.VES.P111")
    # 0002 differs
    put(nav, "0002.T26A.2000A002.b0002.VES.p111", 10, 20, "2000A002", "b0002", "2")
    put(obp, "0002.T26A.2000A002.b0002.VES.p111", 10, 21, "2000A002", "b0002", "2")
    # 0003 only on NAV
    put(nav, "0003.T26A.3000A003.c0003.VES.p111", 30, 40, "3000A003", "c0003", "3")
    # 0004 duplicated on OBP
    put(nav, "0004.T26A.4000A004.d0004.VES.p111", 50, 60, "4000A004", "d0004", "4")
    put(obp, "0004.T26A.4000A004.d0004.VES.p111", 50, 60, "4000A004", "d0004", "4")
    put(obp, "0004.T26A.4000A004.d0004.COPY.p111", 50, 60, "4000A004", "d0004", "4")
    # a non-P1 file that must be ignored entirely
    write(nav, "readme.txt", ["not a p1 file"])
    write(obp, "0009.notes.log", ["also not a p1 file"])

    cfg = FakeConfig({"nav_p1_dir": nav, "obp_p1_dir": obp,
                      "sequence_ranges": ""})
    store = M.Store(os.path.join(tmp, "cache.json"))
    store.read_only = True
    rows = M.Scanner(cfg, store).scan()
    by_seq = dict((r["seq"], r) for r in rows)

    check("scanner: sequences found", sorted(by_seq.keys()),
          ["0001", "0002", "0003", "0004"])
    check("0001 matches despite .P111 vs .p111",
          by_seq["0001"]["xcheck"], M.XCHECK_MATCH)
    check("0001 linename", by_seq["0001"]["linename"], "1000A001")
    check("0001 subline", by_seq["0001"]["subline"], "a0001")
    check("0001 FSP", by_seq["0001"]["fsp"], 100)
    check("0001 LSP", by_seq["0001"]["lsp"], 900)
    check("0002 mismatch detected", by_seq["0002"]["xcheck"], M.XCHECK_MISMATCH)
    check("0003 missing on OBP", by_seq["0003"]["xcheck"], M.XCHECK_MISSING)
    check("0003 still reports its identity", by_seq["0003"]["linename"], "3000A003")
    check("0004 duplicate flagged", by_seq["0004"]["xcheck"], M.XCHECK_MULTIPLE)
    check("0004 P1 Final points at the OBP dir", by_seq["0004"]["p1_final"],
          "CHECK OBP DIR!")
    check("non-P1 files ignored", "0009" in by_seq, False)

    section("scanner: relaxed grouping when no name starts with 4 digits")

    nav2 = os.path.join(tmp, "nav2")
    obp2 = os.path.join(tmp, "obp2")
    os.makedirs(nav2)
    os.makedirs(obp2)
    put(nav2, "SEQ7_LINE.p111", 1, 5, "7000A007", "a0007", "7")
    put(obp2, "SEQ7_LINE.p111", 1, 5, "7000A007", "a0007", "7")
    cfg2 = FakeConfig({"nav_p1_dir": nav2, "obp_p1_dir": obp2,
                       "sequence_ranges": ""})
    store2 = M.Store(os.path.join(tmp, "cache2.json"))
    store2.read_only = True
    rows2 = M.Scanner(cfg2, store2).scan()
    check("relaxed grouping finds the pair", len(rows2), 1)
    if rows2:
        check("relaxed grouping key", rows2[0]["seq"], "0007")
        check("relaxed grouping verdict", rows2[0]["xcheck"], M.XCHECK_MATCH)

    section("sequence range parsing")

    check("blank means auto-detect", M.parse_sequence_ranges("  "), None)
    check("single range", sorted(M.parse_sequence_ranges("3-5")), [3, 4, 5])
    check("mixed list", sorted(M.parse_sequence_ranges("1, 3-4 ,9")), [1, 3, 4, 9])
    check("reversed range ignored", M.parse_sequence_ranges("9-2"), None)
    check("garbage ignored", M.parse_sequence_ranges("abc"), None)
    check("absurd range ignored", M.parse_sequence_ranges("1-999999"), None)


class FakeConfig(object):
    """Minimal stand-in for Config so the scanner can be tested in isolation."""

    def __init__(self, data):
        self.data = dict(M.DEFAULT_CONFIG)
        self.data.update(data)

    def get(self, key):
        return self.data.get(key)

    def snapshot(self):
        return dict(self.data)


def test_csv_and_classify():
    section("CSV rendering and verdict ladder")

    check("column order", M.CSV_COLUMNS,
          ["Sequence No.", "Linename", "Subline", "FSP", "LSP",
           "P1 Final", "NAV MD5SUM", "OBP MD5SUM", "MD5SUM XCHECK"])

    good = "a" * 32
    other = "b" * 32
    check("equal hashes match", M.classify(good, good), M.XCHECK_MATCH)
    check("different hashes mismatch", M.classify(good, other), M.XCHECK_MISMATCH)
    check("both missing", M.classify(M.M_MISSING, M.M_MISSING), M.XCHECK_MISSING)
    check("one missing", M.classify(good, M.M_MISSING), M.XCHECK_MISSING)
    check("duplicate beats everything",
          M.classify(M.M_MULTIPLE, M.M_MISSING), M.XCHECK_MULTIPLE)
    check("vanished mid-scan",
          M.classify(good, M.M_MISSING_AT_SOURCE), M.XCHECK_SOURCE_MISSING)
    check("hash failure", M.classify(good, M.M_FAILED), M.XCHECK_FAILED)
    check("stat failure", M.classify(good, M.M_META_ERROR), M.XCHECK_META_ERROR)

    data = M.csv_bytes(M.CSV_COLUMNS,
                       [["0001", "3682A001", "c0001", 5471, 737,
                         "f.p111", good, good, M.XCHECK_MATCH]])
    check("csv_bytes returns bytes", isinstance(data, bytes), True)
    text = data.decode("utf-8")
    check("csv header line", text.split("\n")[0],
          "Sequence No.,Linename,Subline,FSP,LSP,P1 Final,NAV MD5SUM,"
          "OBP MD5SUM,MD5SUM XCHECK")
    check("csv row line", text.split("\n")[1],
          "0001,3682A001,c0001,5471,737,f.p111,%s,%s,MD5SUM_MATCHING"
          % (good, good))

    # a value carrying a comma or a quote must be quoted, not corrupted
    data = M.csv_bytes(["a", "b"], [["x,y", 'he said "hi"']])
    check("csv quoting", data.decode("utf-8").split("\n")[1],
          '"x,y","he said ""hi"""')


# ------------------------------------------- regressions from the audit --

def test_audit_regressions(tmp):
    section("regressions: silently wrong values")

    # A P1/90 whose columns sit a few places off the standard slot. The slice
    # still parses as a clean digit run, because in a fixed-width record the
    # point number runs straight into the latitude - so "it parsed" must never
    # be taken as proof that the columns were located.
    for shift in (-1, 1, 2, 3, 4, 5):
        lines = []
        for sp in (2113, 3000, 7956):
            rec = v190("S", "1018", sp)
            if shift > 0:
                rec = rec[0] + " " * shift + rec[1:]
            else:
                rec = rec[0] + rec[1 - shift:]
            lines.append(rec)
        p = write(tmp, "0070.shift%d.p190" % shift,
                  ["H0100 SURVEY AREA               Trinidad"] + lines)
        m = meta(p)
        check("p190 shift %+d: FSP right or blank, never truncated" % shift,
              m["fsp"] in (2113, None), True)
        check("p190 shift %+d: LSP right or blank, never truncated" % shift,
              m["lsp"] in (7956, None), True)

    # a 5-digit leading run is not sequence 1000
    # md5check.py keys on the first four characters. That grouping is
    # preserved exactly - the CSV is a deliverable - but now reported.
    check("5-digit run keyed as legacy did",
          M.sequence_key_from_name("10001.line.p111"), "1000")
    check("oversized run is detected for reporting",
          M.oversized_sequence_run("10001.line.p111"), True)
    check("normal 4-digit name is not flagged",
          M.oversized_sequence_run("0001.line.p111"), False)
    check("4-digit leading run still accepted",
          M.sequence_key_from_name("1000.line.p111"), "1000")

    # digits buried inside a code must never become the sequence
    check("embedded digits in a vessel code ignored",
          M.relaxed_sequence_key("T26A_3682A001_c0001_seq0001.p111"), "0001")
    check("disagreeing candidates refused",
          M.relaxed_sequence_key("SEQ42_LINE77.p111"), "")

    # a sequence value with a suffix must not become 00012
    p = write(tmp, "0081.reshoot.p111",
              ["CC,1,0,0,LINENAME/SUBLINE = /5000A081/a0081",
               "CC,1,0,0,LINE SEQUENCE NUMBER = 0001 (RESHOOT 2)"] + p111_body(1, 9))
    m = meta(p)
    check("sequence with a suffix falls back to the filename",
          m["sequence"], "0081")

    # a unicode digit must not crash the scan
    p = write(tmp, "0082.unicode.p111",
              [u"CC,1,0,0,LINENAME/SUBLINE = /5000A082/a0082",
               u"CC,1,0,0,LINE SEQUENCE NUMBER = 000²"] + p111_body(1, 9))
    m = meta(p)
    check("unicode digit: no crash", m["error"], "")
    check("unicode digit: falls back to the filename", m["sequence"], "0082")

    # "inf" parses as a float but is not an integer field value
    check("inf is not a number here", M._int_or_none("inf"), None)
    check("nan is not a number here", M._int_or_none("nan"), None)

    # an ambiguous header key must yield nothing rather than a coin toss
    p = write(tmp, "0083.ambig.p111",
              ["CC,1,0,0,SUB LINE NAME = mystery",
               "CC,1,0,0,LINENAME/SUBLINE = /5000A083/a0083"] + p111_body(1, 9))
    m = meta(p)
    check("ambiguous key does not clobber linename", m["linename"], "5000A083")
    check("ambiguous key does not clobber subline", m["subline"], "a0083")

    # a filename missing the prefix component must not shift every field
    h = M.filename_hints("0001_3682A001_c0001_VES.p111")
    check("missing prefix: no shifted linename", h["linename"], "")
    check("missing prefix: no shifted subline", h["subline"], "")
    check("missing prefix: sequence still read", h["sequence"], "0001")

    # latin-1 bytes must not move fixed-width P1/90 columns
    lat1 = b"H0100 SURVEY AREA               Trinidad\n" \
        + b"H0300 CLIENT                    Petr\xf3leo\n" \
        + (v190("S", "1018", 2113) + "\n").encode("utf-8") \
        + (v190("S", "1018", 7956) + "\n").encode("utf-8")
    p = write(tmp, "0084.latin1.p190", None, raw=lat1)
    m = meta(p)
    check("latin-1 p190: columns not shifted, FSP", m["fsp"], 2113)
    check("latin-1 p190: columns not shifted, LSP", m["lsp"], 7956)

    # the P1/11 point number is the DUPLICATED pair, so a header line name that
    # disagrees with the records does not cost us FSP/LSP
    p = write(tmp, "0085.disagree.p111",
              ["CC,1,0,0,LINENAME/SUBLINE = /9999A085/z0085"] + p111_body(4000, 2000))
    m = meta(p)
    check("header/record linename disagreement: FSP", m["fsp"], 4000)
    check("header/record linename disagreement: LSP", m["lsp"], 2000)

    section("regressions: the attention rule matches md5check.py")

    good, other = "a" * 32, "b" * 32
    check("matching pair is not flagged", M.needs_attention(good, good), False)
    check("mismatch is flagged", M.needs_attention(good, other), True)
    check("missing on ONE side is flagged",
          M.needs_attention(good, M.M_MISSING), True)
    check("missing on ONE side (nav) is flagged",
          M.needs_attention(M.M_MISSING, good), True)
    # the one md5check.py deliberately stays quiet about: a numbering gap
    check("missing on BOTH sides is NOT flagged (numbering gap)",
          M.needs_attention(M.M_MISSING, M.M_MISSING), False)
    check("duplicate files are flagged",
          M.needs_attention(M.M_MULTIPLE, good), True)
    check("vanished source is flagged",
          M.needs_attention(good, M.M_MISSING_AT_SOURCE), True)
    check("hash failure is flagged",
          M.needs_attention(good, M.M_FAILED), True)
    check("stat failure is flagged",
          M.needs_attention(good, M.M_META_ERROR), True)

    section("regressions: scanner scope")

    body = ["CC,1,0,0,LINENAME/SUBLINE = /1000A001/a0001"] + p111_body(1, 9)

    nav = os.path.join(tmp, "gapnav")
    obp = os.path.join(tmp, "gapobp")
    os.makedirs(nav)
    os.makedirs(obp)
    for d in (nav, obp):
        write(d, "0001.T26A.1000A001.a0001.VES.p111", body)
        write(d, "0002.T26A.1000A002.a0002.VES.p111", body)
        # a preplot that happens to start with four digits, far away
        write(d, "3190_TTUD1_Main_v2.WGS84.p111", body)
    cfg = FakeConfig({"nav_p1_dir": nav, "obp_p1_dir": obp, "sequence_ranges": ""})
    store = M.Store(os.path.join(tmp, "gapcache.json"))
    store.read_only = True
    rows = M.Scanner(cfg, store).scan()
    # md5check.py fills every sequence from the lowest file to the highest, so
    # a stray far-off file inflates the range. That output is PRESERVED - the
    # CSV is a deliverable and must not change - but the scan now says why.
    check("legacy auto-fill preserved across a stray far-off file",
          len(rows), 3190)
    check("the real sequences are still reported",
          sorted(r["seq"] for r in rows)[:2], ["0001", "0002"])
    check("the stray file is reported as a warning",
          any("stray file" in w for w in store.warnings), True)

    # one oddly named file must not re-key the whole job
    nav2 = os.path.join(tmp, "mixnav")
    obp2 = os.path.join(tmp, "mixobp")
    os.makedirs(nav2)
    os.makedirs(obp2)
    for d in (nav2, obp2):
        write(d, "0001.T26A.1000A001.a0001.VES.p111", body)
    write(nav2, "P1_export.p111", body)      # no leading digits, NAV only
    cfg = FakeConfig({"nav_p1_dir": nav2, "obp_p1_dir": obp2, "sequence_ranges": ""})
    store = M.Store(os.path.join(tmp, "mixcache.json"))
    store.read_only = True
    rows = M.Scanner(cfg, store).scan()
    by = dict((r["seq"], r) for r in rows)
    check("one odd filename does not re-key the job", sorted(by.keys()), ["0001"])
    check("and 0001 still matches", by["0001"]["xcheck"], M.XCHECK_MATCH)


def main():
    print("md5check_live regression suite - interpreter %s"
          % sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix="md5check_test_")
    try:
        test_p111(tmp)
        test_p190(tmp)
        test_filenames()
        test_scanner(tmp)
        test_csv_and_classify()
        test_audit_regressions(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("-" * 62))
    if FAILURES:
        print("FAILED: %d of %d checks" % (len(FAILURES), CHECKS[0]))
        for f in FAILURES:
            print("  - %s" % f)
        return 1
    print("OK: all %d checks passed" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
