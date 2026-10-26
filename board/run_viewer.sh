#!/bin/sh
# Wrapper owns display cleanup even when the viewer crashes or is terminated.
set -u
cd "$(dirname "$0")" || exit 1
runtime=/tmp/camera_transport
mkdir -p "$runtime" || exit 1
desktop_pids=$(pidof QDesktop 2>/dev/null || true)
child=
cleanup() {
    trap - EXIT INT TERM
    if [ -n "$child" ]; then kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
    if [ -n "$desktop_pids" ]; then kill -CONT $desktop_pids 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if [ -n "$desktop_pids" ]; then kill -STOP $desktop_pids || exit 1; fi
export QT_QPA_PLATFORM=linuxfb:fb=/dev/fb0
export QT_QPA_FONTDIR=/usr/share/fonts/ttf
export QT_PLUGIN_PATH=/usr/lib/plugins
./camera_viewer_arm --output="$runtime" "$@" &
child=$!
wait "$child"
result=$?
child=
exit "$result"
