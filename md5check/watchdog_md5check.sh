#!/bin/bash
# Cron watchdog - ONLY for installs WITHOUT the systemd unit (never run both).
#   * * * * * /usr/local/trinop/site_scripts/md5check_live/watchdog_md5check.sh >> /usr/local/trinop/site_scripts/md5check_live/state/watchdog.log 2>&1
#
# Restarts md5check_live if the process is gone OR its heartbeat is older than
# 120 s. The heartbeat ticks whether or not monitoring is started, so a service
# the operator deliberately STOPPED is never "revived" into running again.
#
# Writes to the log ONLY on restart events (silent when healthy), and
# self-rotates it at 1 MB so even a year-long restart loop cannot grow it.
DIR="$(cd "$(dirname "$0")" && pwd)"
HB="$DIR/state/heartbeat"
PORT="$(grep -o '"port"[^,}]*' "$DIR/config.json" 2>/dev/null | grep -o '[0-9]*' || echo 6770)"

WLOG="$DIR/state/watchdog.log"
if [ -f "$WLOG" ] && [ "$(stat -c%s "$WLOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
    tail -n 500 "$WLOG" > "$WLOG.tmp" && mv "$WLOG.tmp" "$WLOG"
    echo "$(date '+%F %T') watchdog.log rotated (kept last 500 lines)"
fi

# The SERVICE is whatever holds the configured port. Identifying it that way
# (rather than by process-name pattern) means a concurrently running
# `run_md5check.sh verify` - same script name, no listening socket - is never
# mistaken for the service and never killed.
SVCPID="$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+' | head -1)"

alive=0
if [ -n "$SVCPID" ] && [ -f "$HB" ]; then
    now=$(date +%s); hb=$(cat "$HB" 2>/dev/null || echo 0)
    [ $((now - hb)) -lt 120 ] && alive=1
fi

if [ "$alive" -eq 0 ]; then
    if [ -n "$SVCPID" ]; then
        echo "$(date '+%F %T') md5check_live hung (heartbeat stale) - restarting PID $SVCPID"
        kill "$SVCPID" 2>/dev/null
        sleep 2
        kill -9 "$SVCPID" 2>/dev/null
    else
        echo "$(date '+%F %T') md5check_live not listening on $PORT - starting"
    fi
    nohup "$DIR/run_md5check.sh" run >/dev/null 2>&1 &
    echo "$(date '+%F %T') restart issued (port $PORT)"
fi
