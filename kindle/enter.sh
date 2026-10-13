#!/bin/sh
# Inside kterm: Kinlobyte's own system (mounted by documents/Kinlobyte.sh),
# as root, with a clean environment. Ends when the Program Manager ends.
MNT=/tmp/kinlobyte
exec chroot "$MNT" /usr/bin/env -i HOME=/root USER=root LOGNAME=root SHELL=/bin/bash \
    TERM=xterm LANG=C.UTF-8 PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games \
    /bin/bash -c 'cd /root && exec /usr/bin/kilobyte'
