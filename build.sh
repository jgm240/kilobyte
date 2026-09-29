#!/bin/sh
# Build the Kilobyte live/installer ISO with Docker.
#   ./build.sh          full image, Wi-Fi firmware for most laptops included
#   ./build.sh --lite   leave the big Wi-Fi firmware out (about 70 MB smaller)
#
# Only the steps that must run x86-64 code (installing Debian, GRUB) use an
# x86-64 container; compression runs natively, which matters on ARM Macs.
set -e
cd "$(dirname "$0")"
LITE=
[ "${1:-}" = "--lite" ] && LITE=1
mkdir -p out
docker volume create kilobyte-work >/dev/null
# The image remembers which commit it was built from, for Kilobyte Update.
KB_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo unknown)
git diff --quiet HEAD 2>/dev/null || echo "Note: uncommitted changes; the image will still say $KB_COMMIT"

stage() { # stage NAME [docker options...]
    name=$1
    shift
    docker run --rm "$@" -e LITE="$LITE" -e KB_COMMIT="$KB_COMMIT" \
        -v "$PWD:/src:ro" -v kilobyte-work:/work -v "$PWD/out:/out" \
        debian:trixie bash /src/image/build-in-container.sh "$name"
}

case $(docker info -f '{{.Architecture}}') in
    aarch64 | arm64) NATIVE=linux/arm64 ;;
    *)               NATIVE=linux/amd64 ;;
esac

stage rootfs --privileged --platform linux/amd64
stage squash --platform "$NATIVE"
stage iso --platform linux/amd64
echo "Done: $(ls -t out/kilobyte-*.iso | head -n 1)"
