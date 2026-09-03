#!/bin/bash
# Runs md5check_live.py with whichever Python the server already has (no
# installs), and installs/removes/updates the software and its supervisor.
#
#   ./run_md5check.sh [run|validate|rebuild|verify] [--verbose]
#   sudo ./run_md5check.sh install    copy the systemd unit into
#                                     /etc/systemd/system/ with User= and paths
#                                     filled in from THIS folder, then enable +
#                                     start it (survives reboots; restart 5 s)
#   sudo ./run_md5check.sh uninstall  remove WHICHEVER supervisor exists
#                                     (systemd unit and/or cron watchdog line)
#                                     and stop the service. The app folder,
#                                     config, journal, MD5 cache and CSV are
#                                     NEVER touched.
#   sudo ./run_md5check.sh update <bundle.tar.gz>
#                                     upgrade the SOFTWARE from a new bundle:
#                                     syntax-checks it first, atomically
#                                     replaces py/html/scripts/unit (keeps
#                                     .prev copies for rollback), NEVER touches
#                                     config.json or any data, then restarts
#                                     whichever supervisor is running.
#                                     (sudo only needed under systemd.)
DIR="$(cd "$(dirname "$0")" && pwd)"

find_python() {
    for PY in python3 /usr/libexec/platform-python python2.7 python2 python; do
        if command -v "$PY" >/dev/null 2>&1; then
            echo "$PY"
            return 0
        fi
    done
    return 1
}

port_from_config() {
    grep -o '"port"[^,}]*' "$DIR/config.json" 2>/dev/null \
        | grep -o '[0-9]*' || echo 6770
}

if [ "$1" = "update" ]; then
    BUNDLE="${2:-}"
    if [ -z "$BUNDLE" ] || [ ! -f "$BUNDLE" ]; then
        echo "Usage: $0 update /path/to/md5check_live_vX.Y.Z.tar.gz" >&2
        exit 1
    fi
    HAVE_UNIT=0
    # systemd governs THIS folder only if the installed unit points here
    # (a second sandbox/test copy of the app must not demand root)
    if [ -f /etc/systemd/system/md5check-live.service ] \
            && grep -q "^WorkingDirectory=$DIR\$" /etc/systemd/system/md5check-live.service; then
        HAVE_UNIT=1
        if [ "$(id -u)" -ne 0 ]; then
            echo "systemd manages the service - the restart needs root:" >&2
            echo "  sudo $0 update $BUNDLE" >&2
            exit 1
        fi
    fi
    PY="$(find_python)" || { echo "No Python interpreter found." >&2; exit 1; }
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    tar xzf "$BUNDLE" -C "$TMP" || { echo "Cannot extract $BUNDLE" >&2; exit 1; }
    SRC="$TMP/md5check_live"
    [ -d "$SRC" ] || SRC="$TMP"
    if [ ! -f "$SRC/md5check_live.py" ]; then
        echo "$BUNDLE does not contain md5check_live.py - not an md5check bundle" >&2
        exit 1
    fi
    "$PY" -m py_compile "$SRC/md5check_live.py" || {
        echo "New md5check_live.py FAILS to compile - update aborted," >&2
        echo "nothing was changed." >&2
        exit 1
    }
    OLDV="$(grep -m1 '^APP_VERSION' "$DIR/md5check_live.py" | grep -o '[0-9.]*' || echo '?')"
    NEWV="$(grep -m1 '^APP_VERSION' "$SRC/md5check_live.py" | grep -o '[0-9.]*' || echo '?')"
    echo "Updating software v$OLDV -> v$NEWV (config.json and all data kept)"
    if [ -f "$SRC/config.json" ]; then
        echo "  (config.json inside the bundle is IGNORED - your settings win)"
    fi
    # atomic per-file swap (.new then mv): safe even while the service runs
    # and safe for THIS script replacing itself; old versions kept as .prev
    for f in md5check_live.py md5check_live.html watchdog_md5check.sh \
             md5check-live.service DEPLOY.md run_md5check.sh; do
        [ -f "$SRC/$f" ] || continue
        [ -f "$DIR/$f" ] && cp -f "$DIR/$f" "$DIR/$f.prev"
        cp -f "$SRC/$f" "$DIR/.$f.new"
        mv -f "$DIR/.$f.new" "$DIR/$f"
    done
    chmod +x "$DIR/run_md5check.sh" "$DIR/watchdog_md5check.sh" \
             "$DIR/md5check_live.py" 2>/dev/null
    if [ "$HAVE_UNIT" -eq 1 ]; then
        if [ -f "$SRC/md5check-live.service" ]; then
            # the bundle carries a new unit (e.g. resized resource cage):
            # regenerate the INSTALLED copy too, else /etc/systemd keeps
            # serving the old caps forever
            RUNUSER="${SUDO_USER:-root}"
            GRP="$(id -gn "$RUNUSER")"
            sed -e "s|^User=.*|User=$RUNUSER|" \
                -e "s|^Group=.*|Group=$GRP|" \
                -e "s|^WorkingDirectory=.*|WorkingDirectory=$DIR|" \
                -e "s|^ExecStart=.*|ExecStart=$DIR/run_md5check.sh run|" \
                "$DIR/md5check-live.service" \
                > /etc/systemd/system/md5check-live.service
            systemctl daemon-reload
            echo "Installed unit refreshed (daemon reloaded)."
        fi
        echo "Restarting via systemd..."
        systemctl restart md5check-live
        sleep 2
        systemctl --no-pager --lines=0 status md5check-live | head -3
    else
        PORT="$(port_from_config)"
        OLDPID="$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | head -1)"
        if [ -n "$OLDPID" ]; then
            kill "$OLDPID" 2>/dev/null
            echo "Stopped PID $OLDPID."
            if crontab -l 2>/dev/null | grep -q watchdog_md5check; then
                echo "The cron watchdog restarts it within a minute."
            else
                echo "Manual mode: start again with  nohup $DIR/run_md5check.sh run &"
            fi
        else
            echo "No instance was running."
        fi
    fi
    echo "Update done. Rollback = copy the .prev file(s) back and restart."
    exit 0
fi

if [ "$1" = "uninstall" ]; then
    if [ "$(id -u)" -ne 0 ]; then
        echo "Removing the supervisor needs root:  sudo $0 uninstall" >&2
        exit 1
    fi
    RUNUSER="${SUDO_USER:-root}"
    DID=0
    UNIT=/etc/systemd/system/md5check-live.service
    if [ -f "$UNIT" ] || systemctl list-unit-files 2>/dev/null \
            | grep -q '^md5check-live\.service'; then
        echo "Removing systemd unit (service stops now)..."
        systemctl disable --now md5check-live 2>/dev/null
        rm -f "$UNIT"
        systemctl daemon-reload
        DID=1
    fi
    if crontab -l -u "$RUNUSER" 2>/dev/null | grep -q "watchdog_md5check"; then
        echo "Removing the cron watchdog line for $RUNUSER..."
        crontab -l -u "$RUNUSER" 2>/dev/null \
            | grep -v "watchdog_md5check" | crontab -u "$RUNUSER" -
        DID=1
    fi
    PORT="$(port_from_config)"
    if [ "$DID" -eq 0 ]; then
        echo "No supervisor is installed (no systemd unit, no cron watchdog)."
        echo "A hand-started (manual) instance, if any, is left running:"
        ss -ltnp 2>/dev/null | grep ":$PORT " || echo "  (none listening)"
        exit 0
    fi
    echo ""
    echo "Supervisor removed. ONLY the software supervisor was cleaned -"
    echo "every byte of data is untouched. Present right now:"
    JDIR="$(grep -o '"journal_dir"[^,}]*' "$DIR/config.json" 2>/dev/null \
        | sed 's/.*: *"//;s/"$//')"
    [ -n "$JDIR" ] || JDIR="$DIR/state"
    echo "  config      : $(ls -la "$DIR/config.json" 2>/dev/null | awk '{print $5" bytes"}')"
    echo "  journal     : $( (wc -l < "$JDIR/journal.jsonl") 2>/dev/null || echo 0) entries ($JDIR)"
    echo "  md5 cache   : $( (wc -c < "$JDIR/md5cache.json") 2>/dev/null || echo 0) bytes"
    ODIR="$(grep -o '"output_dir"[^,}]*' "$DIR/config.json" 2>/dev/null \
        | sed 's/.*: *"//;s/"$//')"
    echo "  deliverable : $(ls "$ODIR"/*.csv 2>/dev/null | wc -l) CSV(s) in $ODIR"
    echo "Re-install any time with:  sudo $0 install"
    exit 0
fi

if [ "$1" = "install" ]; then
    if [ "$(id -u)" -ne 0 ]; then
        echo "The systemd folder needs root:  sudo $0 install" >&2
        exit 1
    fi
    RUNUSER="${SUDO_USER:-root}"
    GRP="$(id -gn "$RUNUSER")"
    # Exactly one supervisor - refuse while a cron watchdog exists
    if crontab -l -u "$RUNUSER" 2>/dev/null | grep -q "watchdog_md5check"; then
        echo "A cron watchdog line exists for $RUNUSER (crontab -e to remove it)." >&2
        echo "Exactly ONE supervisor may run - not installing systemd on top." >&2
        exit 1
    fi
    # The legacy install_md5check.sh put md5check.py on a per-minute cron.
    # Two things writing the same CSV is the one failure this tool must not
    # inherit, so refuse until that line is gone.
    if crontab -l -u "$RUNUSER" 2>/dev/null | grep -q "md5check\.py"; then
        echo "The OLD per-minute cron job for md5check.py is still installed:" >&2
        crontab -l -u "$RUNUSER" 2>/dev/null | grep "md5check\.py" >&2
        echo "" >&2
        echo "It writes the same CSV this service writes. Remove it first:" >&2
        echo "  crontab -l | grep -v 'md5check\.py' | crontab -" >&2
        exit 1
    fi
    # migrate a hand-started (nohup) instance: it holds the single-instance
    # lock, so stop it before systemd takes over
    PORT="$(port_from_config)"
    OLDPID="$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | head -1)"
    if [ -n "$OLDPID" ]; then
        echo "Stopping hand-started instance (PID $OLDPID) - systemd manages it from now on."
        kill "$OLDPID" 2>/dev/null
        sleep 2
    fi
    UNIT=/etc/systemd/system/md5check-live.service
    sed -e "s|^User=.*|User=$RUNUSER|" \
        -e "s|^Group=.*|Group=$GRP|" \
        -e "s|^WorkingDirectory=.*|WorkingDirectory=$DIR|" \
        -e "s|^ExecStart=.*|ExecStart=$DIR/run_md5check.sh run|" \
        "$DIR/md5check-live.service" > "$UNIT"
    systemctl daemon-reload
    systemctl enable --now md5check-live
    sleep 2
    systemctl --no-pager --lines=4 status md5check-live
    echo ""
    echo "Installed $UNIT  (User=$RUNUSER, folder=$DIR)"
    echo "Manage with:  sudo systemctl status|restart|stop md5check-live"
    echo "Open the console at http://<this-host>:$PORT/"
    exit $?
fi

PY="$(find_python)" || { echo "No Python interpreter found." >&2; exit 1; }
exec "$PY" "$DIR/md5check_live.py" "${@:-run}" --config "$DIR/config.json"
