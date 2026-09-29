#!/bin/bash
# wine-x86.sh ROOT: put WineHQ's Wine for PCs into a Raspberry Pi image, for
# box64 (arm64: x86-64 Wine) or box86 (armhf: i386 Wine) to run. Debian has
# no x86 Wine for ARM systems, so a stable build from WineHQ's Debian
# repository is unpacked to /opt/wine: the newest of the 9.x series, the one
# Debian's box64 0.3 and box86 0.3 run (Wine 11's loader is too new for them).
WINE_SERIES=${WINE_SERIES:-9.}
set -euo pipefail
root=$1
case $(chroot "$root" dpkg --print-architecture) in
    arm64) warch=amd64 main=wine64 ;;
    armhf) warch=i386  main=wine ;;
    *) exit 0 ;;
esac
repo=https://dl.winehq.org/wine-builds/debian
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "$repo/dists/trixie/main/binary-$warch/Packages" -o "$tmp/Packages"
# Newest version of a package: its Filename line.
newest() {
    awk -v p="$1" -v RS= '$0 ~ "(^|\n)Package: " p "\n" {
        v = ""; f = ""
        n = split($0, l, "\n")
        for (i = 1; i <= n; i++) {
            if (l[i] ~ /^Version: /) v = substr(l[i], 10)
            if (l[i] ~ /^Filename: /) f = substr(l[i], 11)
        }
        print v " " f
    }' "$tmp/Packages" | grep "^$WINE_SERIES" | sort -V | tail -n 1 | cut -d" " -f2
}
for p in "wine-stable-$warch" wine-stable; do
    f=$(newest "$p")
    [ -n "$f" ] || { echo "wine-x86: $p not found at WineHQ" >&2; exit 1; }
    echo "wine-x86: $f"
    curl -fsSL "$repo/$f" -o "$tmp/$p.deb"
    dpkg-deb -x "$tmp/$p.deb" "$tmp/x"
done
rm -rf "$root/opt/wine"
mv "$tmp/x/opt/wine-stable" "$root/opt/wine"
# 64-bit only Wine has no "wine" loader of its own.
[ -e "$root/opt/wine/bin/wine" ] || ln -s "$main" "$root/opt/wine/bin/wine"
for b in wine wine64 wineserver wineboot winecfg msiexec regedit winepath winefile notepad; do
    [ -e "$root/opt/wine/bin/$b" ] && ln -sf "/opt/wine/bin/$b" "$root/usr/local/bin/$b"
done
# box64 hands most of Wine's libraries to their ARM versions, but not
# libunwind, which ntdll.so needs: Debian's x86-64 build goes where box64
# looks for x86-64 libraries. (box86 brings its own i386 copy.)
if [ "$warch" = amd64 ]; then
    chroot "$root" dpkg --add-architecture amd64
    chroot "$root" apt-get update -qq
    chroot "$root" sh -c 'cd /tmp && apt-get download -qq libunwind8:amd64 liblzma5:amd64'
    mkdir -p "$root/usr/lib/box64-x86_64-linux-gnu"
    for d in "$root"/tmp/libunwind8_*_amd64.deb "$root"/tmp/liblzma5_*_amd64.deb; do
        dpkg-deb -x "$d" "$tmp/x64"
        rm -f "$d"
    done
    cp -a "$tmp"/x64/usr/lib/x86_64-linux-gnu/*.so* "$root/usr/lib/box64-x86_64-linux-gnu/"
    chroot "$root" dpkg --remove-architecture amd64
    chroot "$root" apt-get update -qq || true
    ls "$root/usr/lib/box64-x86_64-linux-gnu"
fi
du -sh "$root/opt/wine"
