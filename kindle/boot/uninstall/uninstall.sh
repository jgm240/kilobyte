#!/bin/sh
# KilobytEink boot: remove the start-up job; the Kindle starts as before.
# KilobytEink itself (documents/KilobytEink.sh, the kilobyteink folder) stays.
mntroot rw
rm -f /etc/upstart/kilobyteink-boot.conf /etc/upstart/kinlobyte-boot.conf
sync
mntroot ro
exit 0
