#!/bin/bash
# Runs inside the new root file system (chroot) after the packages are in.
set -euo pipefail

# Everything Kilobyte ships must be owned by root.
chown -R root:root /usr/bin/kilobyte /usr/sbin/kilobyte-install /usr/lib/kilobyte /usr/share/kilobyte
chmod 0440 /etc/sudoers.d/kilobyte

# --- the live user: logs in automatically on tty1, sudo without password.
# kilobyte-install removes all of this from an installed system.
groupadd -f netdev
useradd -m -s /bin/bash -c "Kilobyte Live" -G sudo,users,netdev,audio,video,plugdev,cdrom user
echo user:live | chpasswd
echo 'user ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/live
chmod 0440 /etc/sudoers.d/live
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin user --noclear %I $TERM
UNIT

# --- optical drives: any user may read discs and mount data discs
mkdir -p /media/cdrom
grep -q /media/cdrom /etc/fstab 2>/dev/null ||
    echo '/dev/sr0  /media/cdrom  udf,iso9660  ro,user,noauto  0  0' >> /etc/fstab

# --- services
systemctl enable systemd-networkd systemd-resolved systemd-timesyncd gpm kilobyte-wifi
systemctl disable wpa_supplicant.service 2>/dev/null || true   # per-adapter units are used instead
systemctl mask systemd-networkd-wait-online.service
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
passwd -l root

# --- console font and keyboard: console-setup applies a cache made when the
# package was installed, before Kilobyte's settings were in place; renew it.
setupcon --save-only --force

# --- slim down
update-initramfs -u -k all
apt-get clean
rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin /var/log/*.log /tmp/* /root/.bash_history
: > /etc/machine-id
