#!/bin/sh
# Build the kilobyte-transition package (Kilobyte next to the desktop of a
# normal Debian, Ubuntu or Raspberry Pi OS; see transition/kb):
#   out/kilobyte-transition_VERSION-1_all.deb
# Needs Docker.
set -e
cd "$(dirname "$0")/.."
mkdir -p out
docker run --rm -v "$PWD:/src:ro" -v "$PWD/out:/out" debian:trixie bash -c '
    set -e
    # The Kilobyte version, then the package revision (transition/revision).
    v=$(sed -n "s/^KB_VERSION=\"\(.*\)\"/\1/p" /src/rootfs/usr/lib/kilobyte/lib.sh)-$(cat /src/transition/revision)
    p=/tmp/pkg
    install -d $p/DEBIAN $p/usr/bin $p/usr/lib/systemd/system $p/etc/profile.d $p/etc/sudoers.d \
        $p/etc/apt/sources.list.d $p/usr/share/keyrings \
        $p/usr/share/consolefonts $p/usr/share/doc/kilobyte-transition
    cp -a /src/rootfs/usr/lib/kilobyte $p/usr/lib/kilobyte
    cp -a /src/rootfs/usr/share/kilobyte $p/usr/share/kilobyte
    find $p -name .DS_Store -delete
    install -m 755 /src/rootfs/usr/bin/kilobyte /src/transition/kb $p/usr/bin/
    install -m 755 /src/transition/kb-transition $p/usr/lib/kilobyte/
    install -m 644 /src/rootfs/usr/share/consolefonts/Kilobyte-* $p/usr/share/consolefonts/
    install -m 644 /src/rootfs/etc/profile.d/kilobyte.sh $p/etc/profile.d/
    install -m 440 /src/transition/sudoers $p/etc/sudoers.d/kilobyte-transition
    install -m 644 /src/transition/kilobyte-autolaunch.service $p/usr/lib/systemd/system/
    install -m 644 /src/transition/copyright $p/usr/share/doc/kilobyte-transition/copyright
    # Its own APT repository: installing this one file also brings the updates.
    install -m 644 /src/transition/kilobyte-archive-keyring.gpg $p/usr/share/keyrings/
    install -m 644 /src/transition/kilobyte.sources $p/etc/apt/sources.list.d/
    install -m 755 /src/transition/preinst /src/transition/postinst /src/transition/prerm /src/transition/postrm $p/DEBIAN/
    printf "/etc/profile.d/kilobyte.sh\n/etc/sudoers.d/kilobyte-transition\n/etc/apt/sources.list.d/kilobyte.sources\n" > $p/DEBIAN/conffiles
    sed "s/@VERSION@/$v/" /src/transition/control.in > $p/DEBIAN/control
    echo "Installed-Size: $(du -sk --exclude=DEBIAN $p | cut -f1)" >> $p/DEBIAN/control
    chmod -R u+rwX,go+rX,go-w $p/usr $p/etc/profile.d
    chmod 755 $p/usr/lib/kilobyte/kb-* $p/usr/lib/kilobyte/apps/* $p/usr/lib/kilobyte/wifi-up \
        $p/usr/lib/kilobyte/post $p/usr/lib/kilobyte/resize-root
    visudo -cqf $p/etc/sudoers.d/kilobyte-transition 2>/dev/null || { apt-get update -qq >/dev/null && apt-get install -y -qq sudo >/dev/null 2>&1 && visudo -cf $p/etc/sudoers.d/kilobyte-transition; }
    dpkg-deb --root-owner-group -Zxz -b $p /out/kilobyte-transition_${v}_all.deb
'
ls -l out/kilobyte-transition_*_all.deb
