#!/bin/bash
# Builds a Kilobyte image in stages, each in its own container started by
# ../build.sh. The project is mounted at /src, the work area (a Docker volume
# per architecture) at /work and the output directory at /out.
#
#   debs     container of the target architecture: Kilobyte's patched packages
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
    amd64) SUITE=trixie   KERNEL=linux-image-amd64 KIND=pc EFI=grub-efi-amd64-bin EFI32=grub-efi-ia32-bin FOREIGN=i386 ;;
    i386)  SUITE=bookworm KERNEL=linux-image-686   KIND=pc EFI=grub-efi-ia32-bin ;;   # Debian 13 has no 32-bit PC kernel
    arm64) SUITE=trixie   KERNEL=linux-image-arm64 KIND=pi EFI= ;;
    armhf) SUITE=trixie   KERNEL=linux-image-armmp KIND=pi EFI= ;;
    *) echo "unknown ARCH $ARCH" >&2; exit 2 ;;
esac
EFI32=${EFI32:-} FOREIGN=${FOREIGN:-}
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

# Debian packages Kilobyte rebuilds (image/debs/PACKAGE/): Debian's source,
# with the *.patch files applied and prepare.sh run in it, gets a "+kilobyte1"
# version and is installed over the original. A package that fails to build
# is left out (the image keeps Debian's version).
stage_debs() {
    local pkg dir p v
    echo "==> Building Kilobyte's versions of Debian packages"
    # Reuse the packages from the last build when their recipes are unchanged.
    local stamp
    stamp=$(cd /src/image/debs && find . -type f | sort | xargs sha256sum | sha256sum | cut -c1-16)-$SUITE
    if [ "$(cat "$WORK/debs/.recipes" 2>/dev/null)" = "$stamp" ]; then
        echo "(unchanged, reusing:)"
        ls -1 "$WORK/debs"
        return 0
    fi
    # Source packages too: in the image's own list when it is a deb822 file
    # (its Signed-By must match), otherwise as a list of our own.
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then
        sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/debian.sources
    else
        echo "deb-src $MIRROR $SUITE main" > /etc/apt/sources.list.d/kilobyte-src.list
    fi
    tools dpkg-dev build-essential fakeroot patch
    rm -rf "$WORK/debs" "$WORK/src" && mkdir -p "$WORK/debs" "$WORK/src"
    export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig
    for pkg in $(ls /src/image/debs); do
        (
            set -e
            cd "$WORK/src" && apt-get source -qq "$pkg" >/dev/null
            dir=$(find "$WORK/src" -mindepth 1 -maxdepth 1 -type d -name "$pkg-*" | head -n 1)
            cd "$dir"
            for p in /src/image/debs/"$pkg"/*.patch; do
                [ -e "$p" ] && patch -p1 < "$p"
            done
            if [ -x "/src/image/debs/$pkg/prepare.sh" ]; then "/src/image/debs/$pkg/prepare.sh"; fi
            # Build dependencies of the prepared source (prepare.sh may drop some).
            DEBIAN_FRONTEND=noninteractive apt-get build-dep -y -qq . >/dev/null
            v=$(dpkg-parsechangelog -S Version)
            { printf '%s (%s+kilobyte1) %s; urgency=medium\n\n  * Kilobyte build (image/debs/%s).\n\n -- Kilobyte <kilobyte@users.noreply.github.com>  %s\n\n' \
                  "$pkg" "$v" "$SUITE" "$pkg" "$(date -R)"
              cat debian/changelog; } > debian/changelog.new
            mv debian/changelog.new debian/changelog
            DEB_BUILD_OPTIONS="nocheck parallel=$(nproc)" dpkg-buildpackage -b -us -uc > "$WORK/src/$pkg.log" 2>&1 ||
                { tail -n 20 "$WORK/src/$pkg.log"; exit 1; }
            # Only the packages Debian also installs (no -doc, -dbgsym).
            for deb in "$WORK"/src/*+kilobyte1_*.deb; do
                case $deb in *-dbgsym_* | *-doc_* | *-dev_*) continue ;; esac
                cp "$deb" "$WORK/debs/"
            done
        ) || echo "WARNING: $pkg could not be rebuilt; the image keeps Debian's version"
    done
    echo "$stamp" > "$WORK/debs/.recipes"
    ls -1 "$WORK/debs"
}

# box86 (armhf only): not in Debian, so it is built from its source here,
# cross-compiled in a native container (fast) instead of an emulated one.
BOX86_VERSION=v0.3.8
stage_box86() {
    local b="$WORK/box86" v=${BOX86_VERSION#v}
    mkdir -p "$WORK/debs"
    if ls "$WORK/debs/box86_$v-"*.deb >/dev/null 2>&1; then
        echo "(box86 $v already built)"
        return 0
    fi
    echo "==> Building box86 $v for armhf"
    tools ca-certificates curl cmake make python3 gcc-arm-linux-gnueabihf libc6-dev-armhf-cross dpkg-dev
    rm -rf "$b" && mkdir -p "$b/src" && cd "$b/src"
    curl -fsSL "https://github.com/ptitSeb/box86/archive/refs/tags/$BOX86_VERSION.tar.gz" | tar -xz --strip-components=1
    mkdir build && cd build
    cmake .. -DRPI2=1 -DNOGIT=1 -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr \
        -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=armv7l \
        -DCMAKE_C_COMPILER=arm-linux-gnueabihf-gcc -DCMAKE_ASM_COMPILER=arm-linux-gnueabihf-gcc > "$b/cmake.log" 2>&1 ||
        { tail -n 30 "$b/cmake.log"; return 1; }
    make -j"$(nproc)" > "$b/make.log" 2>&1 || { tail -n 30 "$b/make.log"; return 1; }
    make install DESTDIR="$b/pkg" > "$b/install.log" 2>&1 || true
    [ -x "$b/pkg/usr/bin/box86" ] || { tail -n 30 "$b/install.log"; return 1; }
    arm-linux-gnueabihf-strip "$b/pkg/usr/bin/box86"
    mkdir -p "$b/pkg/DEBIAN" "$b/pkg/usr/lib/binfmt.d"
    # Registered for i386 programs at boot by systemd-binfmt.
    [ -f "$b/pkg/etc/binfmt.d/box86.conf" ] && mv "$b/pkg/etc/binfmt.d/box86.conf" "$b/pkg/usr/lib/binfmt.d/"
    rmdir "$b/pkg/etc/binfmt.d" 2>/dev/null || true
    cat > "$b/pkg/DEBIAN/control" <<CONTROL
Package: box86
Version: $v-1+kilobyte1
Architecture: armhf
Maintainer: Kilobyte <kilobyte@users.noreply.github.com>
Depends: libc6
Section: otherosfs
Priority: optional
Homepage: https://github.com/ptitSeb/box86
Description: Linux userspace x86 emulator with a twist
 Runs x86 (i386) Linux programs on 32-bit ARM, translating the code as it
 runs and handing common libraries to their native ARM versions.
 Built for Kilobyte from box86 $v (MIT licence).
CONTROL
    [ -f "$b/pkg/etc/box86.box86rc" ] && echo /etc/box86.box86rc > "$b/pkg/DEBIAN/conffiles"
    dpkg-deb --root-owner-group -b "$b/pkg" "$WORK/debs/box86_$v-1+kilobyte1_armhf.deb"
    ls -l "$WORK/debs/"
}

stage_rootfs() {
    local packages
    local lists=(/src/image/packages.txt "/src/image/packages-$KIND.txt")
    [ -f "/src/image/packages-$ARCH.txt" ] && lists+=("/src/image/packages-$ARCH.txt")
    packages="$(pkgs "${lists[@]}"),$KERNEL${EFI:+,$EFI}${EFI32:+,$EFI32}"
    [ -n "${LITE:-}" ] || packages="$packages,$(pkgs /src/image/packages-wifi.txt)"

    echo "==> Installing build tools"
    # The firmware is in non-free-firmware: the check below must see it.
    [ -f /etc/apt/sources.list.d/debian.sources ] &&
        sed -i 's/^Components: main$/Components: main non-free-firmware/' /etc/apt/sources.list.d/debian.sources
    tools mmdebstrap ca-certificates curl

    # Leave out what this Debian release does not have (the 32-bit PC image
    # is Debian 12, which lacks a few newer packages), with a warning.
    local p kept=() missing=()
    for p in ${packages//,/ }; do
        if [[ $p == *:* ]] || apt-cache show "$p" >/dev/null 2>&1; then
            kept+=("$p")
        else
            missing+=("$p")
        fi
    done
    [ ${#missing[@]} -eq 0 ] || echo "WARNING: not in Debian $SUITE, left out: ${missing[*]}"
    packages=$(IFS=,; echo "${kept[*]}")
    rm -rf "$WORK/rootfs" "$WORK/iso"   # (the patched packages in $WORK/debs stay)

    echo "==> Building the Debian $SUITE root file system for $ARCH"
    export KB_PACKAGES="$packages"   # recorded in the image for Kilobyte Update
    KB_VARIANT=$([ $KIND = pc ] && echo live || echo pi)
    export KB_VARIANT
    mmdebstrap --variant=minbase --mode=root --architectures="$ARCH${FOREIGN:+,$FOREIGN}" \
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
        --customize-hook='if ls /work/debs/*.deb >/dev/null 2>&1; then mkdir -p "$1/tmp/kb-debs" && cp /work/debs/*.deb "$1/tmp/kb-debs/" && chroot "$1" sh -c "DEBIAN_FRONTEND=noninteractive apt-get install -y -q --allow-downgrades /tmp/kb-debs/*.deb && for d in /tmp/kb-debs/*.deb; do apt-mark hold \$(dpkg-deb -f \$d Package); done && rm -r /tmp/kb-debs"; fi' \
        --customize-hook='bash /src/image/wine-x86.sh "$1"' \
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
    # 64-bit ISOs also carry 32-bit EFI GRUB: old EFI 1.x PCs and early Intel
    # Macs have 32-bit firmware on a 64-bit processor (the kernel runs there).
    tools xorriso grub-pc-bin "$EFI" ${EFI32:+"$EFI32"} grub-common mtools dosfstools
    mkdir -p "$WORK/iso/boot/grub" /out
    cp "$WORK"/rootfs/boot/vmlinuz-* "$WORK/iso/live/vmlinuz"
    cp "$WORK"/rootfs/boot/initrd.img-* "$WORK/iso/live/initrd.img"
    cp /src/image/grub.cfg "$WORK/iso/boot/grub/grub.cfg"
    mkdir -p "$WORK/iso/boot/grub/themes"
    cp -r /src/rootfs/usr/share/kilobyte/grub "$WORK/iso/boot/grub/themes/kilobyte"
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
    debs)    stage_debs ;;
    box86)   stage_box86 ;;
    rootfs)  stage_rootfs ;;
    squash)  stage_squash ;;
    iso)     stage_iso ;;
    piimage) stage_piimage ;;
    *) echo "usage: $0 debs|box86|rootfs|squash|iso|piimage" >&2; exit 2 ;;
esac
