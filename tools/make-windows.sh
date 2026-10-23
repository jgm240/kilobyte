#!/bin/sh
# Kilobyte for Windows (the kilobyte-transition WinGet package):
#   out/windows/kilobyte-transition-VERSION-windows-x64.zip   kb.exe, README, COPYING
#   out/windows/...-arm64.zip                                  (with a WSL system for arm64)
#   winget/manifests/k/Kilobyte/Transition/VERSION/            the WinGet manifests
#
# kb.exe downloads the WSL system (./build.sh --wsl) from the GitHub release
# "windows-vVERSION", which gets these zips and the systems:
#   tools/make-windows.sh && gh release create windows-v1.5 ... (see the README)
# Needs Docker.
set -e
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^KB_VERSION="\(.*\)"/\1/p' rootfs/usr/lib/kilobyte/lib.sh)
# The package's version (kb.exe changes without a new Kilobyte system): PKGVER=1.5.1
PKGVER=${PKGVER:-$VERSION.0}
TAG=windows-v$VERSION
URL=https://github.com/jgm240/kilobyte/releases/download/$TAG
OUT=out/windows
mkdir -p "$OUT" windows/assets
cp site/fonts/kilobyte-vga16.ttf windows/assets/
cp site/favicon.ico windows/assets/kilobyte.ico

archs=""
for a in amd64 arm64; do
    [ -f "out/kilobyte-$VERSION-wsl-$a.tar.gz.sha256" ] && archs="$archs $a"
done
[ -n "$archs" ] || { echo "No WSL system in out/: build it with ./build.sh --wsl" >&2; exit 1; }

for a in $archs; do
    sum=$(cut -d' ' -f1 "out/kilobyte-$VERSION-wsl-$a.tar.gz.sha256")
    win=$([ $a = amd64 ] && echo x64 || echo arm64)
    echo "==> kb.exe for Windows $win"
    docker run --rm -v "$PWD/windows:/src" -v "$PWD/$OUT:/out" -w /src -e GOOS=windows -e GOARCH=$a -e CGO_ENABLED=0 \
        golang:1.23 go build -trimpath -o /out/kb-$a.exe \
        -ldflags "-s -w -X main.version=$PKGVER -X main.rootfsURL=$URL/kilobyte-$VERSION-wsl-$a.tar.gz -X main.rootfsSHA256=$sum" .
    z="$OUT/kilobyte-transition-$PKGVER-windows-$win.zip"
    rm -rf "$OUT/zip" && mkdir -p "$OUT/zip"
    cp "$OUT/kb-$a.exe" "$OUT/zip/kb.exe"
    cp windows/README.txt "$OUT/zip/README.txt"
    cp LICENSE "$OUT/zip/COPYING"
    rm -f "$z" && (cd "$OUT/zip" && zip -q -X "../$(basename "$z")" kb.exe README.txt COPYING)
    rm -rf "$OUT/zip"
    shasum -a 256 "$z" | cut -d' ' -f1 > "$z.sha256"
done

# The WinGet manifests (for a pull request to microsoft/winget-pkgs).
M=winget/manifests/k/Kilobyte/Transition/$PKGVER
mkdir -p "$M"
{
    echo "# Made by tools/make-windows.sh"
    echo "PackageIdentifier: Kilobyte.Transition"
    echo "PackageVersion: $PKGVER"
    echo "DefaultLocale: en-US"
    echo "ManifestType: version"
    echo "ManifestVersion: 1.12.0"
} > "$M/Kilobyte.Transition.yaml"
{
    echo "# Made by tools/make-windows.sh"
    echo "PackageIdentifier: Kilobyte.Transition"
    echo "PackageVersion: $PKGVER"
    echo "InstallerType: zip"
    echo "NestedInstallerType: portable"
    echo "NestedInstallerFiles:"
    echo "- RelativeFilePath: kb.exe"
    echo "  PortableCommandAlias: kb"
    # (No dependency on Microsoft.WSL: kb open turns WSL on itself, with
    # Windows' own "wsl --install", and WinGet's validation sandbox cannot
    # install WSL.)
    echo "ReleaseDate: $(date +%Y-%m-%d)"
    echo "Installers:"
    for a in $archs; do
        win=$([ $a = amd64 ] && echo x64 || echo arm64)
        z=kilobyte-transition-$PKGVER-windows-$win.zip
        echo "- Architecture: $win"
        echo "  InstallerUrl: $URL/$z"
        echo "  InstallerSha256: $(tr a-f A-F < "$OUT/$z.sha256")"
    done
    echo "ManifestType: installer"
    echo "ManifestVersion: 1.12.0"
} > "$M/Kilobyte.Transition.installer.yaml"
cat > "$M/Kilobyte.Transition.locale.en-US.yaml" <<YAML
# Made by tools/make-windows.sh
PackageIdentifier: Kilobyte.Transition
PackageVersion: $PKGVER
PackageLocale: en-US
Publisher: Kilobyte contributors
PublisherUrl: https://github.com/jgm240/kilobyte
PublisherSupportUrl: https://github.com/jgm240/kilobyte/issues
PackageName: Kilobyte Transition
PackageUrl: https://jgm240.github.io/kilobyte/
License: GPL-3.0-or-later
LicenseUrl: https://github.com/jgm240/kilobyte/blob/main/LICENSE
ShortDescription: Kilobyte, the text-mode desktop, in Windows (in WSL and Windows Terminal).
Description: |-
  Kilobyte is a desktop made of text: a Program Manager with an editor, spreadsheet, web browser,
  email, file manager, news feeds, games and more, drawn with coloured characters like the
  text-mode programs of the 1980s. This package adds the command kb, which runs Kilobyte as a
  Linux system of its own in WSL, in Windows Terminal with Kilobyte's colours and pixel font:
  kb open, kb close, kb autolaunch on|off. The first kb open turns WSL on if needed and sets
  Kilobyte up.
Moniker: kilobyte
Tags:
- desktop
- retro
- text-mode
- tui
- wsl
- linux
ReleaseNotesUrl: https://github.com/jgm240/kilobyte/releases/tag/$TAG
ManifestType: defaultLocale
ManifestVersion: 1.12.0
YAML
ls -l "$OUT"/*.zip; find "$M" -type f
