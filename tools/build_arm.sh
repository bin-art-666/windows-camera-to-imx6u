#!/bin/bash
# ARM Qt5 SDK layout used by the ATK-IMX6U course environment.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
sdk=${CAMERA_QT_SDK:-$HOME/lab7-sdk}
qmake=${CAMERA_QMAKE:-$sdk/configure-build/bin/qmake}
sysroot=${CAMERA_SYSROOT:-$sdk/board-sysroot}
cross_bin=${CAMERA_CROSS_BIN:-$sdk/gcc-linaro-5.5.0-2017.10-x86_64_arm-linux-gnueabihf/bin}
network=${CAMERA_NETWORK_LIBDIR:-$root/toolchain-libs}
sdk_lib="$sdk/configure-build/lib"
export PATH="$cross_bin:$PATH"
test -x "$qmake" || { echo "Qt ARM qmake not found: $qmake" >&2; exit 1; }
test -d "$sysroot/usr/lib" || { echo "Board sysroot not found: $sysroot" >&2; exit 1; }
command -v arm-linux-gnueabihf-g++ >/dev/null
if [ -f "$sdk_lib/libQt5Network.so" ]; then
    network="$sdk_lib"
else
    test -f "$network/libQt5Network.so.5.12.9" || {
        echo 'Missing QtNetwork link library. See README: prepare your matching board SDK.' >&2
        exit 1
    }
    ln -sf libQt5Network.so.5.12.9 "$network/libQt5Network.so"
    # qmake's module metadata uses this exact SDK library path.
    if [ -e "$sdk_lib/libQt5Network.so" ] || [ -L "$sdk_lib/libQt5Network.so" ]; then
        echo "Broken existing SDK link: $sdk_lib/libQt5Network.so; repair it before building." >&2
        exit 1
    fi
    ln -s "$network/libQt5Network.so.5.12.9" "$sdk_lib/libQt5Network.so"
fi
mkdir -p "$root/build/arm" "$root/bin"
cd "$root/build/arm"
"$qmake" "$root/board/camera_viewer.pro" \
    "BOARD_NETWORK_LIBDIR=$network" \
    "QMAKE_LIBDIR+=$network $sysroot/usr/lib $sysroot/lib" \
    "QMAKE_LFLAGS+=-Wl,--sysroot=$sysroot -Wl,-rpath-link,$network -Wl,-rpath-link,$sysroot/usr/lib -Wl,-rpath-link,$sysroot/lib"
make -j4 > build.log 2>&1 || { tail -60 build.log; exit 1; }
cp camera_viewer_arm "$root/bin/camera_viewer_arm"
arm-linux-gnueabihf-strip "$root/bin/camera_viewer_arm"
file "$root/bin/camera_viewer_arm"
arm-linux-gnueabihf-readelf -d "$root/bin/camera_viewer_arm" > "$root/build/arm/dependencies.txt"
sha256sum "$root/bin/camera_viewer_arm"
