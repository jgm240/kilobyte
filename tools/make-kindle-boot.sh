#!/bin/sh
# Build Kinlobyte's boot packages for jailbroken Kindles (Paperwhite 2):
#   out/Update_kinlobyte_boot_install.bin     the Kindle starts Kinlobyte
#   out/Update_kinlobyte_boot_uninstall.bin   back to the Kindle's home screen
# OTA V2 packages signed with the jailbreak key (KindleTool's default), for
# MRPI or Settings > Update Your Kindle. Needs Docker.
set -e
cd "$(dirname "$0")/.."
mkdir -p out
docker run --rm -v "$PWD/kindle/boot:/boot:ro" -v "$PWD/out:/out" debian:trixie sh -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null
    apt-get install -y -qq --no-install-recommends git ca-certificates build-essential pkg-config \
        libarchive-dev nettle-dev zlib1g-dev libssl-dev >/dev/null 2>&1
    git clone -q --depth 1 https://github.com/NiLuJe/KindleTool /kt
    make -C /kt -j4 >/tmp/make.log 2>&1
    KT=/kt/KindleTool/Release/kindletool
    mkdir -p /w/install /w/uninstall
    cp /boot/install/install.sh /boot/kinlobyte-boot.conf /w/install/
    cp /boot/uninstall/uninstall.sh /w/uninstall/
    cd /w/install && $KT create ota2 -d paperwhite2 -X install.sh kinlobyte-boot.conf /out/Update_kinlobyte_boot_install.bin
    cd /w/uninstall && $KT create ota2 -d paperwhite2 -X uninstall.sh /out/Update_kinlobyte_boot_uninstall.bin
    for f in /out/Update_kinlobyte_boot_*.bin; do echo "== $f"; $KT convert -i "$f" | grep -E "Bundle|Cert|Devices|Metadata|PackagedWith" | head -8; $KT convert -c "$f" | tar -tzvf -; done
'
ls -l out/Update_kinlobyte_boot_*.bin
