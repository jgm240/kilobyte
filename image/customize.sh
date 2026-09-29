#!/bin/bash
# Runs inside the new root file system (chroot) after the packages are in.
#   customize.sh live   PC live medium: live user with automatic login
#   customize.sh pi     Raspberry Pi SD card: first-start wizard, grows the card
set -euo pipefail
VARIANT=${1:-live}

# Everything Kilobyte ships must be owned by root.
chown -R root:root /usr/bin/kilobyte /usr/sbin/kilobyte-install /usr/sbin/kilobyte-firstboot \
    /usr/lib/kilobyte /usr/share/kilobyte /usr/share/consolefonts/Kilobyte-*
chmod 0440 /etc/sudoers.d/kilobyte
groupadd -f netdev
mkdir -p /etc/kilobyte
. /usr/lib/kilobyte/setup-questions.sh     # user_groups, write_autologin

case $VARIANT in
live)
    # The live user: logs in automatically on tty1, sudo without password.
    # kilobyte-install removes all of this from an installed system.
    useradd -m -s /bin/bash -c "Kilobyte Live" -G "$(user_groups /etc/group)" user
    echo user:live | chpasswd
    echo 'user ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/live
    chmod 0440 /etc/sudoers.d/live
    write_autologin "" user
    ;;
pi)
    # The first start asks for keyboard, time zone, name and account.
    mkdir -p /etc/systemd/system/getty@tty1.service.d
    cat > /etc/systemd/system/getty@tty1.service.d/firstboot.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=-/usr/sbin/kilobyte-firstboot
Environment=TERM=linux
UNIT
    : > /etc/kilobyte/resize-root
    systemctl enable kilobyte-resize
    cat > /etc/fstab <<'FSTAB'
# <file system>  <mount point>    <type>  <options>          <dump>  <pass>
LABEL=KBROOT     /                ext4    errors=remount-ro  0       1
LABEL=KBBOOT     /boot/firmware   vfat    umask=0077         0       2
FSTAB
    # raspi-firmware writes cmdline.txt and config.txt from these settings.
    sed -i -e 's/^#\?ROOTPART=.*/ROOTPART=LABEL=KBROOT/' -e 's/^#\?CONSOLES=.*/CONSOLES="tty1"/' \
        /etc/default/raspi-firmware
    grep -q '^ROOTPART=' /etc/default/raspi-firmware || echo 'ROOTPART=LABEL=KBROOT' >> /etc/default/raspi-firmware
    ;;
esac

# --- optical drives: any user may read discs and mount data discs
mkdir -p /media/cdrom
grep -q /media/cdrom /etc/fstab 2>/dev/null ||
    echo '/dev/sr0  /media/cdrom  udf,iso9660  ro,user,noauto  0  0' >> /etc/fstab

# --- Windows programs: X only for Wine, startable from anywhere (kb-x)
echo "xserver-xorg-legacy xserver-xorg-legacy/xwrapper/allowed_users select Anybody" | debconf-set-selections
chmod 644 /etc/X11/Xwrapper.config 2>/dev/null || true

# --- services
systemctl enable systemd-networkd systemd-resolved systemd-timesyncd gpm kilobyte-wifi kilobyte-post kilobyte-bootlogo
systemctl disable wpa_supplicant.service hostapd.service 2>/dev/null || true   # started on demand
systemctl mask systemd-networkd-wait-online.service
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
passwd -l root

# --- console font and keyboard: console-setup applies a cache made when the
# package was installed, before Kilobyte's settings were in place; renew it.
setupcon --save-only --force

# --- slim down (on a Pi, the initramfs hook also fills the boot partition)
update-initramfs -u -k all
apt-get clean
rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin /var/log/*.log /tmp/* /root/.bash_history
: > /etc/machine-id
