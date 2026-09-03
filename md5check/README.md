# md5check_live

Web-based P1 MD5SUM cross-check for xNAVSL. One stdlib-Python service
(`md5check_live.py`) walks the NAV and OBP P1 directories, compares each
sequence's file by MD5, reads the sequence's identity straight out of the P1
file, and emits one CSV. Served on port **6770** with a live console
(`md5check_live.html`). Same shape as [Ibama](https://github.com/rbolisay/Ibama):
no packages are ever installed on the server, python 2.7 **and** 3.6+, self-served,
nginx untouched.

Replaces the cron-driven `md5check.py` + `install_md5check.sh` pair one
directory up. **A new job needs nothing but the Setup dialog** — there is no
installer to re-run.

## What changed vs. md5check.py

| | old | new |
| --- | --- | --- |
| Configuration | `install_md5check.sh` rewrote the script with `sed`, per job | **⚙ Setup** in the browser, with server-side folder pickers |
| Scheduling | `*/1 * * * *` cron | one long-lived service, **Check Interval (sec)** in Setup |
| Start / stop | edit crontab | **Start / Stop P1 md5sum Monitoring** button; stopping needs a password |
| Output | HTML page via nginx + CSV | self-served live console + CSV |
| CSV columns | Sequence Number, P1 Final, NAV MD5SUM, OBP MD5SUM, MD5SUM XCHECK | **Sequence No., Linename, Subline, FSP, LSP**, P1 Final, NAV MD5SUM, OBP MD5SUM, MD5SUM XCHECK |
| Re-hashing | mtime+size cache | same cache, plus the parsed P1 metadata beside it |

The five per-side markers (`MISSING`, `MISSING_AT_SOURCE`,
`MULTIPLE_FILES_DETECTED`, `COMPUTATION_FAILED`, `METADATA_ERROR`) and every
`MD5SUM XCHECK` verdict keep their old spelling, so anything already reading
the CSV keeps working.

## Where the five new columns come from

Read out of the P1 file itself, never guessed:

**`.p111`** (OGP P1/11, comma-delimited) — the header carries them explicitly:

```
CC,1,0,0,LINENAME/SUBLINE = /3682A001/c0001
CC,1,0,0,LINE SEQUENCE NUMBER = 0001
```

FSP and LSP are the point numbers of the **first and last `S1` (source)
records** — field index 4. They are the first and last shot *acquired*, so on a
line shot in decreasing order FSP is greater than LSP (`5471 → 737`), which is
correct and expected.

**`.p190`** (UKOOA P1/90, fixed width) — 1-based columns: 1 record id,
2-13 line name, 20-25 point number. FSP/LSP come from the first and last record
of the same identifier (`S` preferred, then `V`).

Anything still missing falls back to the filename convention
(`0001.T26A.3682A001.c0001.GFUNREG.VES.p111` = seq.prefix.linename.subline…),
and the leading four digits stay the authority for grouping, exactly as
`md5check.py` always did.

**It never reads a whole file for this.** A 256 KB head window and a 512 KB
tail window are enough, and the result is cached beside the MD5. Parsing the
identity of all 68 files of a real 3.7 GB job takes **0.3 s**.

## Feature parity with md5check.py

**No regressions.** `tools/regression_vs_legacy.py` runs the ORIGINAL
`md5check.py` and this service over byte-identical inputs and compares the five
columns they share, and `tools/regression_real_data.py` does the same against
real P1 directories plus the "Please CHECK Sequence(s)" set and the static HTML
report. Both are in the repo; run them after any change.

```bash
python2.7 tools/regression_vs_legacy.py --legacy ../md5check.py
python2.7 tools/regression_real_data.py --legacy ../md5check.py           --nav /path/to/NAV --obp /path/to/OBP
```

Current result — 30 synthetic scenarios (P111, P190, mixed, every fault state,
every range form) with the new tool run under **both** interpreters, plus six
real-data comparisons:

| | result |
| --- | --- |
| 30 synthetic scenarios, new tool on python3 | all byte-match |
| 30 synthetic scenarios, new tool on python2.7 | all byte-match |
| Real P111, 68 sequences / 3.7 GB, auto-detect | match, incl. attention set and HTML report |
| Real P111 with `1-40` and with `1-20, 60-99` | match |
| Real P111, identical directories | match |
| Real P190 preplots, and preplots vs an empty dir | match |

Every legacy behaviour is carried forward:

| md5check.py / install_md5check.sh | here |
| --- | --- |
| `NAV_P1_DIR`, `OBP_P1_DIR`, `OUTPUT_CSV` rewritten by `sed` per job | Setup dialog, validated server-side |
| `SEQUENCE_RANGES_STR` incl. multi-segment, bare numbers, per-segment truncation at the last sequence with data | identical, same parser semantics |
| Auto-detect: every sequence from the lowest file to the highest | identical (a jump > 100 is now *reported* as a likely stray file — the rows are still produced) |
| Sequence grouping on the first 4 filename characters | identical (a longer digit run is now *reported*, still grouped the legacy way) |
| MD5 cache keyed on mtime + size | identical, plus the parsed P1 metadata beside it |
| `MISSING`, `MISSING_AT_SOURCE`, `MULTIPLE_FILES_DETECTED`, `COMPUTATION_FAILED`, `METADATA_ERROR` | identical spelling |
| `P1 Final` incl. `CHECK NAV DIR!` / `CHECK OBP DIR!` | identical |
| The `MD5SUM XCHECK` verdict ladder, in order | identical |
| "Please CHECK Sequence(s)" rule — including **not** alarming when a sequence is missing from *both* sides | identical (this one was a real bug found by the harness and fixed) |
| Static HTML report, 30 s refresh, same CSS classes and colours | still written to `html_report_path` (default `/usr/share/nginx/html/md5check_report.html`), so existing bookmarks keep working; set to `""` to stop. Best-effort — an unwritable path logs once and never blocks the CSV |
| `*/1 * * * *` cron | one service, **Check Interval (sec)** in Setup |
| nginx location block, crond checks, `chmod +x` in the installer | not needed — self-served, with a systemd unit or cron watchdog |

The only deliberate difference is an addition: the legacy `endswith()` test is
case-sensitive and skips a file named `.P111`, where this accepts it. That is
declared in the harness and checked to be *exactly* that difference.

## Robustness

Vessel deliveries are not clean. The extractor is built so that a field it cannot
read comes out **empty** — never an exception, and never a plausible-but-wrong
value. A wrong shot point in a QC deliverable is worse than a blank one.

Tolerated, each with a regression test in `test_md5check.py`:

| Dirt | Handling |
| --- | --- |
| Upper/lower case record tags, keys, extensions | everything compared case-folded; `.P111` == `.p111` |
| Leading/trailing/inner whitespace, padded fields | trimmed at every level |
| Byte-order mark | stripped |
| CRLF, bare-CR, mixed line endings | normalised |
| Tabs | expanded to 8 before fixed-width columns are read |
| Latin-1 / undecodable bytes / NUL bytes | decoded with replacement; never fatal |
| `=` or `:` as the key separator | both accepted |
| Key spelled `LINENAME/SUBLINE`, `Line Name / Sub-Line`, `Seq No`, `Line_Prefix` | keys are folded to alphanumerics before matching, so punctuation and spacing are irrelevant |
| `/` or `\` in the linename/subline value, missing leading separator, missing half | all accepted; a missing half stays blank |
| Quoted fields containing commas | a quote-aware splitter, not a naive `split(",")` |
| Filename separators `.` `_` `-`, padded filenames | all parsed for hints |
| **P1/11 columns re-ordered** | the line name anchors the search and the first integer after it is the shot point |
| **P1/90 columns shifted** | the layout is re-anchored on latitude's decimal point, which is positionally exact |
| P1/90 records shifted by stray leading whitespace | trimmed when column 1 is not a valid record identifier |
| Preplot with no shot records, header-only, empty, truncated, binary garbage | FSP/LSP blank, no crash |
| A single 300 KB junk line at the top of a file | the head window grows until the header is found |
| Filenames that do not start with 4 digits | falls back to the first digit run — and only ever for **both** directories at once, so the two sides can never be keyed differently |

Also fixed by an adversarial audit of this code (38 confirmed findings, all
re-tested):

| Defect | Handling now |
| --- | --- |
| A P1/90 whose columns sit 1–3 places off the standard slot silently reported **truncated** shot points (2113 → 211) — the misaligned slice is still a clean digit run, so "it parsed" proved nothing | latitude's decimal point is the primary anchor; the standard slot is a fallback that refuses when a digit is hard against either edge |
| `10001.p111` was grouped as sequence `1000` — two sequences compared against each other | a leading digit run longer than the key width is refused, not truncated |
| The relaxed filename fallback picked the `26` out of a vessel code `T26A` | only whole tokens, or a trailing digit run, and only when every candidate agrees |
| One oddly named file in one directory re-keyed the **whole job** | the fallback needs *every* side to lack strict keys |
| One stray far-off filename (a preplot `3190_…` beside sequence `0001`) manufactured ~3000 phantom `MISSING` rows | auto mode fills gaps but never bridges a jump wider than `AUTO_MAX_GAP` |
| `LINE SEQUENCE NUMBER = 0001 (RESHOOT 2)` became sequence `00012`; a unicode digit crashed the scan | the value is parsed, not scraped; anything not a plain number falls back to the filename |
| `SUB LINE NAME` matched both `SUBLINE` and `LINENAME`, resolved by table order | an ambiguous key reports nothing |
| A filename missing its prefix shifted linename and subline one slot | the slots must match the convention's shape |
| A head window ending mid-record parsed the fragment as a whole record | a window that did not reach EOF drops its trailing fragment |
| `float("inf")` in a numeric field raised `OverflowError` out of a "never raises" helper | caught |
| A NUL byte in `/api/browse?path=` raised `ValueError` and killed the request thread | any bad path is an answer, not a crash |
| A torn byte in `journal.jsonl` raised out of the loader | decoded leniently, so it becomes a chain-check finding |
| A filename carrying surrogates (latin-1 over a share) crashed the CSV writer and **killed the monitor thread** | encoded with `backslashreplace`; the loop has a last-resort guard |
| A vanished mount made both directories list empty, and the good CSV was replaced with a header-only file | a scan that lists nothing where something existed **refuses to emit** and says why |
| Two threads shared one `.tmp` name | the temp name carries pid and thread id, and is cleaned up on failure |
| A P1 still being written was hashed half-complete and that hash **cached** | re-stat after hashing; if anything moved, no hash is recorded |
| Changing the output directory did not rewrite the CSV there | the short-circuit compares destination as well as content |
| The cache grew for ever across a year-long job | entries untouched for `CACHE_RETENTION_SCANS` are aged out |
| `"3001-3500, 4005 4006"` was accepted and the malformed half silently dropped | any unusable segment rejects the whole string, naming it |
| The **served page contained the real stop password** in its demo branch | removed — the password only ever lives in `config.json` and is only ever checked server-side |
| `/api/browse` could walk the entire filesystem and echoed raw OS errors | confined to `browse_roots` plus the configured directories |
| A form POST from another page could reach the control endpoint | `Content-Type: application/json` is required |
| An unread request body desynchronised the next keep-alive request | any path that does not consume the body closes the connection |

Two deliberate non-features, because guessing would be worse than declining:

- **P1/90 is not tokenised.** In a fixed-width record `2113` followed by latitude
  `110744.92N` reads as the single run `2113110744`. Column detection anchors on
  latitude's decimal point instead; if that anchor is absent, the standard
  columns are used and an unreadable field stays blank.
- **`3300A040` is a line name, not the number 3300.** Integer parsing is strict;
  digits are never dug out of alphanumeric text.

Bumping `META_VERSION` re-parses cached metadata on the next scan **without
re-hashing** — a version upgrade costs two small window reads per file, not a
re-read of the whole job.

## Tests

```bash
python3 test_md5check.py     # 184 checks, no arguments, no network
python2.7 test_md5check.py   # same suite, same result
```

Run it after any change to the parser or the scanner.

## Speed

Measured on the Rocky 8.10 staging VM against 68 real sequences
(132 files, ~7.4 GB, NAV + OBP):

| | time | files hashed |
| --- | --- | --- |
| First (cold) pass | 12.9 s | 132 |
| Steady-state tick | 0.00 s | 0 |
| Tick after one file changed | 0.03 s | 1 |

## Run it anywhere

```bash
cd md5check
# point config.json at some sample directories, then:
python3 md5check_live.py run --config config.json
# open http://localhost:6770/
```

The page auto-detects the API; opened as a bare file it runs in demo mode.
Stop-button password: `control_password` in `config.json`.

## Deploy

`DEPLOY.md` is the copy-paste navoff1 procedure — **including removing the old
per-minute `md5check.py` cron job**, which writes the same CSV. Exactly one
supervisor: the systemd unit **or** the cron watchdog, never both.

## Files

| File | Purpose |
| --- | --- |
| `md5check_live.py` | the service: scanner, P1 parser, HTTP API, CSV writer |
| `md5check_live.html` | the console: live table, Setup dialog, Start/Stop |
| `config.json` | settings; written by Setup, never by an upgrade |
| `run_md5check.sh` | run / validate / rebuild / verify / install / uninstall / update |
| `md5check-live.service` | systemd unit (resource-capped, idle I/O) |
| `watchdog_md5check.sh` | cron alternative to systemd |
| `test_md5check.py` | standing unit suite (184 checks, 2.7 and 3.6) |
| `tools/regression_vs_legacy.py` | differential vs the original md5check.py, 30 scenarios |
| `tools/regression_real_data.py` | the same, against real P1 directories |
| `DEPLOY.md` | the navoff1 procedure |
