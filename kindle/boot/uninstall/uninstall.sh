#!/bin/sh
# Kinlobyte boot: remove the start-up job; the Kindle starts as before.
# Kinlobyte itself (documents/Kinlobyte.sh, the kinlobyte folder) stays.
mntroot rw
rm -f /etc/upstart/kinlobyte-boot.conf
sync
mntroot ro
exit 0
