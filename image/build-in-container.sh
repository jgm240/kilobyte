#!/bin/bash
# Builds the Kilobyte ISO in three stages, each in its own container started
# by ../build.sh. The project is mounted at /src, the work area (a Docker
# volume) at /work and the output directory at /out.
#
#   rootfs  x86-64 container: Debian root file system with mmdebstrap
#   squash  any architecture: compress it (the slow part, so run natively)
#   iso     x86-64 container: kernel, initrd, GRUB for BIOS and UEFI
set -euo pipefail

SUITE=trixie
MIRROR=http://deb.debian.org/debian
VERSION=$(sed -n 's/^KB_VERSION="\(.*\)"/\1/p' /src/rootfs/usr/lib/kilobyte/lib.sh)
WORK=/work
ISO="/out/kilobyte-$VERSION-amd64${LITE:+-lite}.iso"

tools() {
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "$@" >/dev/null
}

pkgs() { sed 's/#.*//' "$@" | xargs | tr ' ' ','; }

stage_rootfs() {
    local packages
    packages=$(pkgs /src/image/packages.txt)
    [ -n "${LITE:-}" ] || packages="$packages,$(pkgs /src/image/packages-wifi.txt)"

    echo "==> Installing build tools"
    tools mmdebstrap ca-certificates curl
    rm -rf "$WORK/rootfs"

    echo "==> Building the Debian $SUITE root file system"
    export KB_PACKAGES="$packages"   # recorded in the image for Kilobyte Update
    mmdebstrap --variant=minbase --mode=root \
        --components="main non-free-firmware" \
        --include="$packages" \
        --aptopt='APT::Install-Recommends "false"' \
        --dpkgopt='path-exclude=/usr/share/man/*' \
        --dpkgopt='path-exclude=/usr/share/info/*' \
        --dpkgopt='path-exclude=/usr/share/doc/*' \
        --dpkgopt='path-include=/usr/share/doc/*/copyright' \
        --dpkgopt='path-exclude=/usr/share/locale/*' \
        --dpkgopt='path-include=/usr/share/locale/locale.alias' \
        --dpkgopt='path-exclude=/usr/games/tetris-bsd' \
        --dpkgopt='path-exclude=/var/games/bsdgames/tetris-bsd.scores' \
        --dpkgopt='path-exclude=/usr/games/snake' \
        --dpkgopt='path-exclude=/usr/games/snscore' \
        --essential-hook='echo "debconf debconf/frontend select Noninteractive" | chroot "$1" debconf-set-selections' \
        --customize-hook='tar -C /src/rootfs --owner=0 --group=0 -cf - . | tar -C "$1" -xf -' \
        --customize-hook='curl -fsSL -o "$1/usr/local/bin/yt-dlp" https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp && chmod 755 "$1/usr/local/bin/yt-dlp"' \
        --customize-hook='echo "${KB_COMMIT:-unknown}" > "$1/usr/share/kilobyte/commit"' \
        --customize-hook='echo "$KB_PACKAGES" | tr , "\n" | sort -u > "$1/usr/share/kilobyte/packages.txt"' \
        --customize-hook='cp /src/image/customize.sh "$1/tmp/customize.sh"' \
        --customize-hook='chroot "$1" bash /tmp/customize.sh' \
        "$SUITE" "$WORK/rootfs" \
        "deb $MIRROR $SUITE main non-free-firmware" \
        "deb $MIRROR $SUITE-updates main non-free-firmware" \
        "deb http://security.debian.org/debian-security $SUITE-security main non-free-firmware"
    du -sh "$WORK/rootfs"
}

stage_squash() {
    echo "==> Compressing the root file system"
    tools squashfs-tools
    mkdir -p "$WORK/iso/live"
    mksquashfs "$WORK/rootfs" "$WORK/iso/live/filesystem.squashfs" \
        -noappend -comp xz -Xbcj x86 -b 1M -quiet -progress
    du -sh "$WORK/iso/live/filesystem.squashfs"
}

stage_iso() {
    echo "==> Writing $ISO (boots with BIOS and UEFI)"
    tools xorriso grub-pc-bin grub-efi-amd64-bin grub-common mtools dosfstools
    mkdir -p "$WORK/iso/boot/grub" /out
    cp "$WORK"/rootfs/boot/vmlinuz-* "$WORK/iso/live/vmlinuz"
    cp "$WORK"/rootfs/boot/initrd.img-* "$WORK/iso/live/initrd.img"
    cp /src/image/grub.cfg "$WORK/iso/boot/grub/grub.cfg"
    grub-mkrescue -o "$ISO.tmp" "$WORK/iso" -- -volid KILOBYTE 2>&1 | grep -v '^xorriso : UPDATE' || true
    mv "$ISO.tmp" "$ISO"
    ls -lh "$ISO"
}

case "${1:-}" in
    rootfs) stage_rootfs ;;
    squash) stage_squash ;;
    iso)    stage_iso ;;
    *) echo "usage: $0 rootfs|squash|iso" >&2; exit 2 ;;
esac
