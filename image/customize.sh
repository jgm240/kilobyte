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
    # Pi 1 and Zero: Debian's kernel for them (6.12.48 and later) hangs before
    # it shows anything when cmdline.txt sets a CMA size (Debian bug #1116251).
    # Without it the kernel takes the size from the device tree.
    if [ "$(dpkg --print-architecture)" = armel ]; then
        sed -i 's/^#\?CMA=.*/CMA=0/' /etc/default/raspi-firmware
        grep -q '^CMA=' /etc/default/raspi-firmware || echo 'CMA=0' >> /etc/default/raspi-firmware
    fi
    # 64-bit images run Raspberry Pi's own kernel. Its packages put the
    # kernel, the initramfs and the device trees on the boot partition and
    # leave these two files to whoever makes the image.
    if ls /boot/vmlinuz-*-rpi-v8 >/dev/null 2>&1; then
        mkdir -p /boot/firmware
        cat > /boot/firmware/config.txt <<'CONFIG'
# Kilobyte on the Raspberry Pi 3, 4, 400, 5, 500 and Zero 2 W.
# What can be set here:
# https://www.raspberrypi.com/documentation/computers/config_txt.html

arm_64bit=1
# The initramfs that goes with the kernel (it finds the root file system).
auto_initramfs=1
disable_overscan=1
arm_boost=1

# Sound, and the display driver of the kernel.
dtparam=audio=on
dtoverlay=vc4-kms-v3d
max_framebuffers=2
disable_fw_kms_setup=1

[cm4]
otg_mode=1

[cm5]
dtoverlay=dwc2,dr_mode=host

[all]
CONFIG
        echo 'console=tty1 root=LABEL=KBROOT rw rootwait fsck.repair=yes net.ifnames=0' > /boot/firmware/cmdline.txt
    fi
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
systemctl enable systemd-networkd systemd-resolved systemd-timesyncd gpm kilobyte-wifi kilobyte-post kilobyte-bootlogo kilobyte-swap kilobyte-undo
systemctl disable wpa_supplicant.service hostapd.service 2>/dev/null || true   # started on demand
# Remote login is off until Settings > Remote login switches it on; every
# computer makes its own host keys then (none are in the image).
systemctl disable ssh.service ssh.socket 2>/dev/null || true
rm -f /etc/ssh/ssh_host_*
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
