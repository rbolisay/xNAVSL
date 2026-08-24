# xNAVSL

## Rules

**Read [RULES.md](RULES.md) and follow every rule in it.** It is the standing
rules ledger for this repo. R1 in particular: verify before recommending —
never flag, suggest, or assert anything not checked first, and label anything
unverifiable in the current environment as unverified.

## Environment

- All scripts are **Python 2.7 only** (`Tkinter`, `tkFileDialog`, `imp`,
  `exec code in ...`). They do not run under Python 3.
- Scripts are committed executable (mode 100755) and rely on their
  `#!/usr/bin/env python2.7` shebang.
- xNAVSL launches embedded tools via `sys.executable`, so start it with
  python2.7 to keep child processes on the same interpreter.
