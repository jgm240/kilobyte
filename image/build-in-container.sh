#!/bin/bash
# Builds a Kilobyte image in stages, each in its own container started by
# ../build.sh. The project is mounted at /src, the work area (a Docker volume
# per architecture) at /work and the output directory at /out.
#
#   rootfs   container of the target architecture: Debian with mmdebstrap
#   squash   any architecture: compress it for the live ISO (the slow part)
#   iso      container of the target architecture: kernel, initrd, GRUB
#   piimage  any architecture: Raspberry Pi SD card image (.img.xz)
#
# ARCH picks the image: amd64 and i386 are PC ISOs, arm64 and armhf are
# Raspberry Pi images. LITE=1 leaves the big Wi-Fi firmware out.
set -euo pipefail

ARCH=${ARCH:-amd64}
MIRROR=http://deb.debian.org/debian
VERSION=$(sed -n 's/^KB_VERSION="\(.*\)"/\1/p' /src/rootfs/usr/lib/kilobyte/lib.sh)
WORK=/work

case $ARCH in
    amd64) SUITE=trixie   KERNEL=linux-image-amd64 KIND=pc EFI=grub-efi-amd64-bin ;;
    i386)  SUITE=bookworm KERNEL=linux-image-686   KIND=pc EFI=grub-efi-ia32-bin ;;   # Debian 13 has no 32-bit PC kernel
    arm64) SUITE=trixie   KERNEL=linux-image-arm64 KIND=pi EFI= ;;
    armhf) SUITE=trixie   KERNEL=linux-image-armmp KIND=pi EFI= ;;
    *) echo "unknown ARCH $ARCH" >&2; exit 2 ;;
esac
if [ $KIND = pc ]; then
    NAME="kilobyte-$VERSION-$ARCH${LITE:+-lite}"
else
    NAME="kilobyte-$VERSION-raspberrypi-$ARCH${LITE:+-lite}"
fi

tools() {
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "$@" >/dev/null
}

pkgs() { sed 's/#.*//' "$@" | xargs | tr ' ' ','; }

stage_rootfs() {
    local packages
    packages="$(pkgs /src/image/packages.txt /src/image/packages-$KIND.txt),$KERNEL${EFI:+,$EFI}"
    [ -n "${LITE:-}" ] || packages="$packages,$(pkgs /src/image/packages-wifi.txt)"

    echo "==> Installing build tools"
    tools mmdebstrap ca-certificates curl
    rm -rf "$WORK/rootfs" "$WORK/iso"

    echo "==> Building the Debian $SUITE root file system for $ARCH"
    export KB_PACKAGES="$packages"   # recorded in the image for Kilobyte Update
    KB_VARIANT=$([ $KIND = pc ] && echo live || echo pi)
    export KB_VARIANT
    mmdebstrap --variant=minbase --mode=root --architectures="$ARCH" \
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
        --customize-hook='chroot "$1" bash /tmp/customize.sh "$KB_VARIANT"' \
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
    local iso="/out/$NAME.iso"
    echo "==> Writing $iso (boots with BIOS and UEFI)"
    tools xorriso grub-pc-bin "$EFI" grub-common mtools dosfstools
    mkdir -p "$WORK/iso/boot/grub" /out
    cp "$WORK"/rootfs/boot/vmlinuz-* "$WORK/iso/live/vmlinuz"
    cp "$WORK"/rootfs/boot/initrd.img-* "$WORK/iso/live/initrd.img"
    cp /src/image/grub.cfg "$WORK/iso/boot/grub/grub.cfg"
    grub-mkrescue -o "$iso.tmp" "$WORK/iso" -- -volid KILOBYTE 2>&1 | grep -v '^xorriso : UPDATE' || true
    mv "$iso.tmp" "$iso"
    ls -lh "$iso"
}

stage_piimage() {
    local r="$WORK/rootfs" boot="$WORK/boot.img" root="$WORK/root.img" img="$WORK/$NAME.img"
    local boot_mb=256 used_mb root_mb
    echo "==> Writing /out/$NAME.img.xz (Raspberry Pi SD card)"
    tools dosfstools mtools e2fsprogs fdisk xz-utils
    rm -f "$boot" "$root" "$img"

    # Boot partition: firmware, kernel, initrd, device trees, cmdline.txt.
    mkfs.vfat -C -F 32 -n KBBOOT "$boot" $(( boot_mb * 1024 )) >/dev/null
    mcopy -s -i "$boot" "$r"/boot/firmware/* ::

    # Root partition, filled straight from the directory (no mounting).
    mkdir -p "$WORK/firmware-aside"
    mv "$r"/boot/firmware/* "$WORK/firmware-aside/"
    used_mb=$(du -sm "$r" | cut -f1)
    root_mb=$(( used_mb * 13 / 10 + 256 ))
    mke2fs -q -t ext4 -L KBROOT -d "$r" "$root" "${root_mb}M"
    mv "$WORK"/firmware-aside/* "$r/boot/firmware/"

    # MBR disk: 8 MiB gap, boot (FAT32, LBA), root; grown on first start.
    truncate -s $(( 8 + boot_mb + root_mb + 1 ))M "$img"
    sfdisk -q "$img" <<EOF
label: dos
start=8MiB, size=${boot_mb}MiB, type=c, bootable
start=$(( 8 + boot_mb ))MiB, type=83
EOF
    dd if="$boot" of="$img" bs=1M seek=8 conv=notrunc status=none
    dd if="$root" of="$img" bs=1M seek=$(( 8 + boot_mb )) conv=notrunc status=none
    rm -f "$boot" "$root"
    mkdir -p /out
    xz -T0 -6 -c "$img" > "/out/$NAME.img.xz.tmp"
    mv "/out/$NAME.img.xz.tmp" "/out/$NAME.img.xz"
    rm -f "$img"
    ls -lh "/out/$NAME.img.xz"
}

case "${1:-}" in
    rootfs)  stage_rootfs ;;
    squash)  stage_squash ;;
    iso)     stage_iso ;;
    piimage) stage_piimage ;;
    *) echo "usage: $0 rootfs|squash|iso|piimage" >&2; exit 2 ;;
esac
