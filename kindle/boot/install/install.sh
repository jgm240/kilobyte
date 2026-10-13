#!/bin/sh
# Kinlobyte boot: install the Upstart job that starts Kinlobyte at boot.
# Changes one file on the Kindle's system: /etc/upstart/kinlobyte-boot.conf.
mntroot rw
cp -f kinlobyte-boot.conf /etc/upstart/kinlobyte-boot.conf
chmod 644 /etc/upstart/kinlobyte-boot.conf
sync
mntroot ro
# A previous "off" switch would keep it from starting: it was installed to start.
rm -f /mnt/us/DONT_START_KINLOBYTE 2>/dev/null
exit 0
