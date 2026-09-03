# Deploying md5check_live on navoff1

The copy-paste procedure. Nothing is installed on the server: the service is
one Python file plus one HTML file, using only the standard library, served on
its own port. Nginx is not involved and is never touched.

This replaces the old `md5check.py` + `install_md5check.sh` pair. **Read §1
before anything else** — the old per-minute cron job must be removed, or two
things will write the same CSV.

---

## 0. Pre-install checks

Run these on navoff1 first. All three must pass.

```bash
# a Python exists (either is fine - the service runs on 2.7 and 3.6+)
for p in python3 /usr/libexec/platform-python python2.7 python2 python; do command -v $p; done

# port 6770 is free
ss -ltn | grep :6770 || echo "6770 is free"

# the two P1 directories exist, and you know which is which
ls -d /usr/local/trinop/dbase/links/P111/*SSREG*
ls -d /usr/local/trinop/dbase/links/nav2dp/*/P111*
```

> **Note on the NAV path.** `md5check.py` hardcoded
> `/usr/local/trinop/dbase/links/P111/P111-SSREG` (hyphen) while
> `install_md5check.sh` prompted for `.../P111_SSREG` (underscore). At most one
> is right and nobody noticed, because the installer's `sed` always overwrote
> the hardcoded value. Confirm the real path with the `ls -d` above. It does not
> matter much any more: Setup refuses to save a directory that does not exist.

---

## 1. Remove the old cron job

The legacy installer put `md5check.py` on a per-minute cron. It writes the same
CSV this service writes. Remove it **before** starting the service:

```bash
crontab -l | grep md5check
crontab -l | grep -v 'md5check\.py' | crontab -
crontab -l | grep md5check || echo "old cron job gone"
```

`run_md5check.sh install` refuses to run while that line still exists, so this
step cannot be skipped by accident.

The old `md5check.py` itself can stay on disk; nothing calls it any more.
Its `md5cache.json` is not reused — the new service keeps its own cache in
`state/` and will rebuild it on the first pass.

---

## 2. Bundle and copy

On your workstation, from the repo:

```bash
cd xNAVSL
tar czf md5check_live_v1.0.0.tar.gz --transform 's,^md5check,md5check_live,' md5check
scp md5check_live_v1.0.0.tar.gz <you>@navoff1:/tmp/
```

On navoff1:

```bash
cd /usr/local/trinop/site_scripts
tar xzf /tmp/md5check_live_v1.0.0.tar.gz
cd md5check_live
chmod +x run_md5check.sh watchdog_md5check.sh md5check_live.py
ls -la
```

You should have: `md5check_live.py`, `md5check_live.html`, `config.json`,
`run_md5check.sh`, `watchdog_md5check.sh`, `md5check-live.service`, `DEPLOY.md`.

---

## 3. Validate the config

```bash
./run_md5check.sh validate
```

Prints each path with `OK` / `MISSING`, the CSV target, the interval and the
port. Fix anything that says `MISSING` — either edit `config.json` now, or
leave it and use the web Setup in §5 (Setup is the intended way; `config.json`
is only a starting point).

---

## 4. First foreground run

Run it in the foreground once and watch the log:

```bash
./run_md5check.sh run --verbose
```

Expected:

```
md5check_live 1.0.0 serving on http://0.0.0.0:6770/  (config: .../config.json)
Monitoring is STOPPED
```

It starts **stopped** on purpose — nothing is read until you press Start.
Leave it running and open the console from any machine on the network:

```
http://<navoff1-ip>:6770/
```

If the page does not load but `curl http://127.0.0.1:6770/api/health` works on
navoff1 itself, the firewall is blocking the port:

```bash
sudo firewall-cmd --permanent --add-port=6770/tcp
sudo firewall-cmd --reload
```

Stop the foreground run with Ctrl-C when you are done looking.

---

## 5. Setup — this is what replaces the installer

In the page, press **⚙ Setup** and fill in:

| Field | What it is |
| --- | --- |
| **Nav P1 Directory** | the navigation system's P1 output (read-only) |
| **OBP P1 Directory** | the onboard-processing copy (read-only) |
| **Output CSV Directory** | where `md5check.csv` is written — default `/usr/local/trinop/qcfiles/md5sum` |
| **Check Interval (sec)** | how often the cross-check runs |
| **Sequence ranges** | leave blank to auto-detect every sequence that has a file |

Each path field has a **📁** button that browses the server's own filesystem —
no need to know or type the path. Paths are validated on the server before the
save sticks, and every save is a journal entry.

Then press **▶ Start P1 md5sum Monitoring**.

**A new job needs nothing but this dialog.** There is no installer to re-run.

### Choosing the interval

The first pass hashes every P1 file once. On the staging VM that was **13 s for
132 files / 7.4 GB**. After that, a file is only re-hashed when its size or
mtime changes, so a steady-state tick costs **~0 s** (measured: 0.00 s with no
changes, 0.03 s when one file changed). 60 s is a sensible default; there is no
benefit to going below ~15 s.

### Stopping

**■ Stop P1 md5sum Monitoring** asks for the control password
(`control_password` in `config.json`). A wrong password is refused with
"Wrong password - monitoring keeps running." and the check carries on.
Stopping deletes nothing: the MD5 cache is kept, so Start picks up where it
left off and only re-hashes what changed meanwhile.

---

## 6. Pick ONE supervisor

Never install both. Either is fine; systemd is preferred where you have root.

### Option A - systemd (preferred)

```bash
sudo ./run_md5check.sh install
```

Fills `User=`, `Group=` and the paths from the current folder, enables and
starts the unit. Survives reboots, restarts within 5 s if it dies. Manage with:

```bash
sudo systemctl status md5check-live
sudo systemctl restart md5check-live
journalctl -u md5check-live -f
```

### Option B - cron watchdog (no root)

```bash
crontab -e
```

Add one line:

```
* * * * * /usr/local/trinop/site_scripts/md5check_live/watchdog_md5check.sh >> /usr/local/trinop/site_scripts/md5check_live/state/watchdog.log 2>&1
```

Then start it once by hand:

```bash
nohup ./run_md5check.sh run >/dev/null 2>&1 &
```

The watchdog restarts the service if it is not listening on the port, or if its
heartbeat is older than 120 s. It identifies the service by **which process
holds the port**, not by process name, so a `verify` running at the same time is
never killed by mistake. The heartbeat ticks whether monitoring is started or
stopped, so a service you deliberately stopped is never "revived" into running.

---

## 7. Checking it afterwards

```bash
./run_md5check.sh verify
```

Re-walks the journal hash chain and compares the delivered CSV against a fresh
scan. Safe to run while the service is up — it takes no lock and never writes
to the cache.

A weekly cron is a reasonable habit:

```
17 3 * * 1 /usr/local/trinop/site_scripts/md5check_live/run_md5check.sh verify >> /usr/local/trinop/site_scripts/md5check_live/state/verify.log 2>&1
```

Other useful commands:

```bash
./run_md5check.sh rebuild     # one scan + CSV, then exit
curl -s http://127.0.0.1:6770/api/health   # machine-readable status
```

---

## 8. Upgrading

```bash
sudo ./run_md5check.sh update /tmp/md5check_live_v1.1.0.tar.gz
```

Syntax-checks the new code **before** touching anything, then atomically swaps
each file (old ones kept as `.prev` for rollback) and restarts whichever
supervisor is running. `config.json`, the journal, the MD5 cache and every CSV
are never touched — the bundle's own `config.json` is ignored.

Rollback: copy the `.prev` files back and restart.

## 9. Removing it

```bash
sudo ./run_md5check.sh uninstall
```

Removes whichever supervisor exists and stops the service. The app folder,
config, journal, cache and CSVs are all left alone; it prints what is still
there.

---

## What lives where

| Path | Contents |
| --- | --- |
| `<app>/config.json` | every setting; written by Setup, never by an upgrade |
| `<app>/state/journal.jsonl` | append-only, hash-chained: every Setup save and every start/stop |
| `<app>/state/md5cache.json` | MD5 + parsed P1 metadata keyed by path, mtime and size |
| `<app>/state/heartbeat` | epoch seconds, for the cron watchdog |
| `<app>/state/logs/` | rotating service log, 5 MB x 5 |
| `<output_dir>/md5check.csv` | the deliverable |

Source P1 files are opened **read-only**. Nothing is ever written into the NAV
or OBP directories.
