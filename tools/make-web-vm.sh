#!/bin/sh
# Make the website's "Try it" virtual PC from the CD version's ISO:
#   out/web-vm/v86/    the emulator (v86, from npm) and its BIOS files
#   out/web-vm/disk/   the ISO in 1 MB pieces, each compressed (zstd), which
#                      the browser fetches as the system reads them;
#                      state.bin.zst, the PC after it has started Kilobyte
#                      (so the page opens at the Program Manager); manifest.json
#
#   tools/make-web-vm.sh [ISO]     default: out/kilobyte-VERSION-i386-cd.iso
#
# The state is made by starting the ISO in v86 under Node until the Program
# Manager shows. It only fits that exact ISO and v86 version: make both anew
# together. Needs Docker.
set -e
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^KB_VERSION="\(.*\)"/\1/p' rootfs/usr/lib/kilobyte/lib.sh)
ISO=${1:-out/kilobyte-$VERSION-i386-cd.iso}
V86_VERSION=0.5.472
MEMORY_MB=256
[ -f "$ISO" ] || { echo "No $ISO: build it with ./build.sh --arch i386 --cd" >&2; exit 1; }
mkdir -p out/web-vm
docker run --rm -v "$PWD/$ISO:/iso/kilobyte.iso:ro" -v "$PWD/out/web-vm:/out" -v "$PWD/tools:/tools:ro" \
    -e V86_VERSION=$V86_VERSION -e MEMORY_MB=$MEMORY_MB -e NAME="kilobyte-$VERSION-i386-cd" node:22-bookworm bash -c '
    set -e
    apt-get update -qq >/dev/null && apt-get install -y -qq zstd >/dev/null 2>&1
    rm -rf /out/v86 /out/disk && mkdir -p /out/v86 /out/disk /w && cd /w
    echo "==> v86 $V86_VERSION"
    npm pack -s v86@$V86_VERSION >/dev/null && tar -xzf v86-$V86_VERSION.tgz
    cp package/build/libv86.js package/build/v86.wasm package/LICENSE /out/v86/
    curl -fsSL -o /out/v86/seabios.bin https://raw.githubusercontent.com/copy/v86/master/bios/seabios.bin
    curl -fsSL -o /out/v86/vgabios.bin https://raw.githubusercontent.com/copy/v86/master/bios/vgabios.bin
    npm init -y >/dev/null && npm install -s ./v86-$V86_VERSION.tgz >/dev/null

    echo "==> The ISO in 1 MB pieces"
    CHUNK=1048576
    size=$(stat -c %s /iso/kilobyte.iso)
    split -b $CHUNK -d -a 6 /iso/kilobyte.iso /w/part-
    last=$(ls /w/part-* | tail -n 1)
    truncate -s $CHUNK "$last"                  # every piece is whole: the last one padded
    n=0
    for f in /w/part-*; do
        off=$(( n * CHUNK ))
        zstd -q -12 --rm "$f" -o "/out/disk/$NAME-$off-$(( off + CHUNK )).iso.zst"
        n=$(( n + 1 ))
    done
    padded=$(( n * CHUNK ))
    echo "$n pieces, $(du -sh /out/disk | cut -f1)"

    echo "==> Starting Kilobyte in v86 (some minutes)"
    # (The same size as the pieces: the saved PC knows how big its CD is.)
    cp /iso/kilobyte.iso /w/padded.iso && truncate -s $padded /w/padded.iso
    cp /tools/make-web-vm-state.mjs /w/          # (next to its node_modules)
    MEMORY_MB=$MEMORY_MB node /w/make-web-vm-state.mjs /w/padded.iso /out/v86 /w/state.bin
    zstd -q -19 -T0 /w/state.bin -o /out/disk/state.bin.zst
    echo "state: $(du -h /w/state.bin | cut -f1) -> $(du -h /out/disk/state.bin.zst | cut -f1)"
    printf "{\"iso\": \"%s.iso.zst\", \"size\": %d, \"chunk\": %d, \"state\": \"state.bin.zst\", \"memory\": %d, \"v86\": \"%s\"}\n" \
        "$NAME" $padded $CHUNK $(( MEMORY_MB * 1048576 )) "$V86_VERSION" > /out/disk/manifest.json
    cat /out/disk/manifest.json
'
du -sh out/web-vm/*
