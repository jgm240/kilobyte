#!/bin/sh
# Build Kilobyte images with Docker.
#
#   ./build.sh                  64-bit PC ISO and USB stick image (amd64)
#   ./build.sh --arch i386      32-bit PC ISO (Debian 13, Debian 12's kernel; old computers)
#   ./build.sh --arch arm64     Raspberry Pi 3 / 4 / 400 SD card image
#   ./build.sh --arch armhf     Raspberry Pi 2 / 3 SD card image (32-bit)
#   ./build.sh --arch armel     Raspberry Pi 1 / Zero / Zero W SD card image
#   ./build.sh --arch all       all five
#   ./build.sh --lite ...       leave the big Wi-Fi firmware out
#   ./build.sh --cd ...         CD version: DOSBox instead of Wine, so the
#                               32-bit PC ISO fits on a 650 MB CD
#   ./build.sh --fresh ...      build the Debian base system anew (it is
#                               otherwise reused for two weeks, unless the
#                               package lists change)
#   ./build.sh --fast ...       quick compression, for test images
#
# Debian is installed in a container of the target architecture (emulated if
# the computer has a different one); compression runs natively.
set -e
cd "$(dirname "$0")"

ARCHES=amd64
LITE=
CD=
FRESH=
FAST=
while [ $# -gt 0 ]; do
    case $1 in
        --lite) LITE=1 ;;
        --cd) CD=1 ;;
        --fresh) FRESH=1 ;;
        --fast) FAST=1 ;;
        --arch) shift; ARCHES=$1 ;;
        --arch=*) ARCHES=${1#--arch=} ;;
        *) echo "usage: $0 [--arch amd64|i386|arm64|armhf|armel|all] [--lite] [--cd] [--fresh] [--fast]" >&2; exit 2 ;;
    esac
    shift
done
[ "$ARCHES" = all ] && ARCHES="amd64 i386 arm64 armhf armel"
mkdir -p out

# The image remembers which commit it was built from, for Kilobyte Update.
KB_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo unknown)
git diff --quiet HEAD 2>/dev/null || echo "Note: uncommitted changes; the image will still say $KB_COMMIT"

case $(docker info -f '{{.Architecture}}') in
    aarch64 | arm64) NATIVE=linux/arm64 ;;
    *)               NATIVE=linux/amd64 ;;
esac

for ARCH in $ARCHES; do
    case $ARCH in
        amd64) PLATFORM=linux/amd64  SUITE=trixie ;;
        i386)  PLATFORM=linux/386    SUITE=trixie ;;
        arm64) PLATFORM=linux/arm64  SUITE=trixie ;;
        armhf) PLATFORM=linux/arm/v7 SUITE=trixie ;;
        armel) PLATFORM=linux/arm/v5 SUITE=trixie ;;
        *) echo "unknown architecture: $ARCH" >&2; exit 2 ;;
    esac
    echo "######## Kilobyte for $ARCH"
    # A variant has a work area of its own (its base system differs); the
    # first time, it starts with the downloads and packages of the usual one.
    VOL="kilobyte-work-$ARCH${CD:+-cd}"
    if ! docker volume inspect "$VOL" >/dev/null 2>&1; then
        docker volume create "$VOL" >/dev/null
        if [ "$VOL" != "kilobyte-work-$ARCH" ] && docker volume inspect "kilobyte-work-$ARCH" >/dev/null 2>&1; then
            docker run --rm -v "kilobyte-work-$ARCH:/from:ro" -v "$VOL:/to" "debian:$SUITE" \
                sh -c 'for d in apt-cache debs ccache; do [ -d /from/$d ] && cp -a /from/$d /to/; done; true'
        fi
    fi

    stage() { # stage NAME [docker options...]
        name=$1
        shift
        docker run --rm "$@" -e ARCH="$ARCH" -e LITE="$LITE" -e CD="$CD" -e KB_COMMIT="$KB_COMMIT" \
            -e FRESH="$FRESH" -e FAST="$FAST" \
            -v "$PWD:/src:ro" -v "$VOL:/work" -v "$PWD/out:/out" \
            "debian:$SUITE" bash /src/image/build-in-container.sh "$name"
    }

    stage debs --platform "$PLATFORM"
    [ "$ARCH" = armhf ] && stage box86 --platform "$NATIVE"
    stage base --privileged --platform "$PLATFORM"
    stage rootfs --privileged --platform "$PLATFORM"
    case $ARCH in
        amd64 | i386)
            stage squash --platform "$NATIVE"
            stage iso --platform "$PLATFORM"
            stage usbimg --platform "$PLATFORM" ;;
        *)
            stage piimage --platform "$NATIVE" ;;
    esac
    stage clean --platform "$NATIVE"
done
echo "Done:"
ls -1t out/kilobyte-* | head -n 8
