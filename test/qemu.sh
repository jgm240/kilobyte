#!/bin/sh
# Try Kilobyte in QEMU.
#   test/qemu.sh            boot the ISO (UEFI) with an empty 8 GB disk to install on
#   test/qemu.sh --bios     the same with a legacy BIOS
#   test/qemu.sh --disk     boot the installed disk (after running Setup)
# Extra arguments after these are passed to QEMU. KB_DISK picks another disk image.
set -e
cd "$(dirname "$0")/.."
ISO=$(ls -t out/kilobyte-*.iso | head -n 1)
DISK=${KB_DISK:-out/test-disk.qcow2}
[ -e "$DISK" ] || qemu-img create -f qcow2 "$DISK" 8G >/dev/null

FIRMWARE="-drive if=pflash,format=raw,readonly=on,file=$(dirname "$(command -v qemu-system-x86_64)")/../share/qemu/edk2-x86_64-code.fd"
BOOT="-cdrom $ISO -boot d"
case "${1:-}" in
    --bios) FIRMWARE=""; shift ;;
    --disk) BOOT="-boot c"; shift ;;
esac
case "${1:-}" in --bios) FIRMWARE=""; shift ;; esac

ACCEL=tcg
[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] && [ -w /dev/kvm ] && ACCEL=kvm

# shellcheck disable=SC2086
exec qemu-system-x86_64 -machine q35,accel=$ACCEL -m 2048 -smp 2 \
    $FIRMWARE -vga std \
    -drive file="$DISK",if=virtio,format=qcow2 $BOOT \
    -nic user,model=virtio-net-pci "$@"
