#!/bin/sh
# Build the kilobyte-parentalctl package (parental controls; not in the
# images: "kbutils dl parentalctl" installs it from Kilobyte's APT repository):
#   out/kilobyte-parentalctl_VERSION_all.deb
# Needs Docker.
set -e
cd "$(dirname "$0")/.."
mkdir -p out
docker run --rm -v "$PWD:/src:ro" -v "$PWD/out:/out" debian:trixie bash -c '
    set -e
    v=$(sed -n "s/^KB_VERSION=\"\(.*\)\"/\1/p" /src/rootfs/usr/lib/kilobyte/lib.sh)-$(cat /src/parentalctl/revision)
    p=/tmp/pkg
    install -d $p/DEBIAN $p/usr/lib/kilobyte-parentalctl $p/usr/lib/systemd/system $p/usr/share/doc/kilobyte-parentalctl
    install -m 755 /src/parentalctl/pctl /src/parentalctl/parentalctl-ui /src/parentalctl/pam-check $p/usr/lib/kilobyte-parentalctl/
    ln -s pctl $p/usr/lib/kilobyte-parentalctl/parentalctl
    install -m 644 /src/parentalctl/kilobyte-parentalctl.service /src/parentalctl/kilobyte-parentalctl.timer $p/usr/lib/systemd/system/
    install -m 644 /src/parentalctl/copyright $p/usr/share/doc/kilobyte-parentalctl/copyright
    install -m 755 /src/parentalctl/postinst /src/parentalctl/prerm /src/parentalctl/postrm $p/DEBIAN/
    sed "s/@VERSION@/$v/" /src/parentalctl/control.in > $p/DEBIAN/control
    echo "Installed-Size: $(du -sk --exclude=DEBIAN $p | cut -f1)" >> $p/DEBIAN/control
    dpkg-deb --root-owner-group -Zxz -b $p /out/kilobyte-parentalctl_${v}_all.deb
'
