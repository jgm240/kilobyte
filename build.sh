#!/bin/sh
# Build Kilobyte images with Docker.
#
#   ./build.sh                  64-bit PC ISO (amd64)
#   ./build.sh --arch i386      32-bit PC ISO (Debian 12, for old computers)
#   ./build.sh --arch arm64     Raspberry Pi 3 / 4 / 400 SD card image
#   ./build.sh --arch armhf     Raspberry Pi 2 / 3 SD card image (32-bit)
#   ./build.sh --arch all       all four
#   ./build.sh --lite ...       leave the big Wi-Fi firmware out
#
# Debian is installed in a container of the target architecture (emulated if
# the computer has a different one); compression runs natively.
set -e
cd "$(dirname "$0")"

ARCHES=amd64
LITE=
while [ $# -gt 0 ]; do
    case $1 in
        --lite) LITE=1 ;;
        --arch) shift; ARCHES=$1 ;;
        --arch=*) ARCHES=${1#--arch=} ;;
        *) echo "usage: $0 [--arch amd64|i386|arm64|armhf|all] [--lite]" >&2; exit 2 ;;
    esac
    shift
done
[ "$ARCHES" = all ] && ARCHES="amd64 i386 arm64 armhf"
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
        i386)  PLATFORM=linux/386    SUITE=bookworm ;;
        arm64) PLATFORM=linux/arm64  SUITE=trixie ;;
        armhf) PLATFORM=linux/arm/v7 SUITE=trixie ;;
        *) echo "unknown architecture: $ARCH" >&2; exit 2 ;;
    esac
    echo "######## Kilobyte for $ARCH"
    docker volume create "kilobyte-work-$ARCH" >/dev/null

    stage() { # stage NAME [docker options...]
        name=$1
        shift
        docker run --rm "$@" -e ARCH="$ARCH" -e LITE="$LITE" -e KB_COMMIT="$KB_COMMIT" \
            -v "$PWD:/src:ro" -v "kilobyte-work-$ARCH:/work" -v "$PWD/out:/out" \
            "debian:$SUITE" bash /src/image/build-in-container.sh "$name"
    }

    stage debs --platform "$PLATFORM"
    stage rootfs --privileged --platform "$PLATFORM"
    case $ARCH in
        amd64 | i386)
            stage squash --platform "$NATIVE"
            stage iso --platform "$PLATFORM" ;;
        *)
            stage piimage --platform "$NATIVE" ;;
    esac
done
echo "Done:"
ls -1t out/kilobyte-* | head -n 8
