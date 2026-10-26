#!/bin/sh
set -u
cd "$(dirname "$0")" || exit 1
root=$(pwd)
runtime=/tmp/camera_transport
pidfile="$runtime/service.pid"
lock="$runtime/service.lock"
mkdir -p "$runtime" || exit 1
alive() {
    [ -f "$pidfile" ] || return 1
    pid=$(cat "$pidfile")
    case "$pid" in ''|*[!0-9]*) return 1;; esac
    kill -0 "$pid" 2>/dev/null || return 1
    # Avoid signalling an unrelated process after PID reuse.
    tr '\000' ' ' < "/proc/$pid/cmdline" | grep -F "$root/run_viewer.sh" >/dev/null
}
case "${1:-status}" in
    start)
        shift
        if ! mkdir "$lock" 2>/dev/null; then echo 'Service action already running'; exit 1; fi
        trap 'rmdir "$lock" 2>/dev/null || true' EXIT
        if alive; then echo "Already running PID $pid"; exit 0; fi
        nohup sh "$root/run_viewer.sh" "$@" > "$runtime/viewer.log" 2>&1 < /dev/null &
        echo $! > "$pidfile"
        sleep 1
        if ! alive; then cat "$runtime/viewer.log"; exit 1; fi
        echo "Started PID $pid"
        ;;
    stop)
        if ! mkdir "$lock" 2>/dev/null; then echo 'Service action already running'; exit 1; fi
        trap 'rmdir "$lock" 2>/dev/null || true' EXIT
        if alive; then
            kill -TERM "$pid"
            n=0
            while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 5 ]; do sleep 1; n=$((n+1)); done
            if kill -0 "$pid" 2>/dev/null; then echo 'Stop still pending; check process'; exit 1; fi
        fi
        rm -f "$pidfile"
        echo Stopped
        ;;
    status)
        if alive; then echo "Running PID $pid"; else echo 'Not running'; fi
        [ ! -f "$runtime/status.json" ] || cat "$runtime/status.json"
        echo
        ;;
    *) echo 'Usage: service.sh start [viewer options] | stop | status'; exit 2;;
esac
