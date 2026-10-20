#!/bin/sh
# KilobytEink boot: install the Upstart job that starts KilobytEink at boot.
# Changes one file on the Kindle's system: /etc/upstart/kilobyteink-boot.conf.
mntroot rw
cp -f kilobyteink-boot.conf /etc/upstart/kilobyteink-boot.conf
# The same job from before the name change (Kinlobyte), if it is there.
rm -f /etc/upstart/kinlobyte-boot.conf
chmod 644 /etc/upstart/kilobyteink-boot.conf
sync
mntroot ro
# A previous "off" switch would keep it from starting: it was installed to start.
rm -f /mnt/us/DONT_START_KILOBYTEINK /mnt/us/DONT_START_KINLOBYTE 2>/dev/null
exit 0
