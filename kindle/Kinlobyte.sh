#!/bin/sh
# Name: Kinlobyte
# Author: Kilobyte contributors
# Icon: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAHgAAACgCAAAAADiYvdMAAABqElEQVR42u3bvUvDQBzG8SdFal20o4jOoiCOvoH4hg7i5uAmgqCTggji3+EiuLiouLlqlV5rpIulQycHB8HuB0JE8W2osQqirV4phe8z5cjBJ/kd5MeFxHtVbRIRMDAwMDAwMDAwMDBw3cANnwdelbFX1hgYGBgYGPjXfvxT//wu3i/zPUoNDAwMDAz8735caf+l1MDAwMDAwO77scv+S6mBgYGBgYHdvK9mfwwMDAwMDFz7/XGl5yk1MDAwMDBwWfH4NxUYGLjuYEIIqWas1JFrtdJ9sjiykqSFbCY7LwUmlZvpzkeky1VjnoyZDYwxa27gmN8vK9nzkRI85ccV9ydkpd4bHcxp+rB4We/X5QTeXSyCY6kSfDogaTAhK3nX6spH/G7n8Mp2WOLU6AdciEmKFWSl8Rlpb2dfruHg6iiER9Jf4aZbBSbzdCJ1PneGcGCMGXAB3zUnlsMSJ8dCODEoaehYVuop3afjNW4vdL3Dw+chPOm3KO6Py0pt2T/AZX2Jert+0Fc8Sj82SlFfuthoTz5Et84UNS9a+jI7aqTMJo8hQkjV8gaOm4f5pENSUAAAAABJRU5ErkJggg==
# DontUseFBInk
#
# Kinlobyte: Kilobyte, the desktop that is not really one, on a jailbroken
# Kindle. Tap it in the Library: the Program Manager opens in kterm, with
# kterm's on-screen keyboard. Exit (Quit in the Program Manager) brings the
# Kindle back.
#
# Needs: the Universal Hotfix (scriptlets), kterm anywhere on the Kindle's
# storage (/mnt/us/kterm, /mnt/us/extensions/kterm, or set KTERM in
# kinlobyte.conf) and the folder /mnt/us/kinlobyte with kinlobyte.img. Settings (font size,
# screen orientation) are in /mnt/us/kinlobyte/kinlobyte.conf.
#
# Copyright (C) 2026 Kilobyte contributors. Free software: GNU GPL, version 3
# or later (/mnt/us/kinlobyte/COPYING).

# Stopping the Kindle's reading interface (below) may end whatever it
# started, this script included: carry on in a session of our own.
if [ -z "$KINLOBYTE_DETACHED" ]; then
    export KINLOBYTE_DETACHED=1
    if command -v setsid >/dev/null 2>&1; then
        setsid sh "$0" "$@" </dev/null >/dev/null 2>&1 &
    else
        nohup sh "$0" "$@" </dev/null >/dev/null 2>&1 &
    fi
    exit 0
fi

KB=/mnt/us/kinlobyte
IMG=$KB/kinlobyte.img
MNT=/tmp/kinlobyte
KTERM=""
LOG=$KB/kinlobyte.log

# A message on the e-ink screen, for when there is no terminal to show it in.
say() {
    eips -c >/dev/null 2>&1
    i=3
    for line in "$@"; do
        eips 2 $i "$line" >/dev/null 2>&1
        i=$((i + 2))
    done
    eips 2 $((i + 2)) "(Tap Home to go back.)" >/dev/null 2>&1
}

mounted() { grep -q " $1 " /proc/mounts; }

leave() {
    for d in mnt/us dev/pts dev sys proc; do
        mounted "$MNT/$d" && { umount "$MNT/$d" 2>/dev/null || umount -l "$MNT/$d" 2>/dev/null; }
    done
    mounted "$MNT" && { umount "$MNT" 2>/dev/null || umount -l "$MNT" 2>/dev/null; }
}

if [ ! -f "$IMG" ]; then
    say "Kinlobyte is not installed." "Copy the folder kinlobyte (with" "kinlobyte.img) to the Kindle's main" "folder over USB."
    exit 1
fi
# Settings: FONT_SIZE, ORIENTATION (U, R or L), KEYBOARD (1 on, 0 off),
# STOP_UI (1: stop the Kindle's reading interface while Kinlobyte runs),
# KTERM (kterm's folder, if it is not found by itself).
FONT_SIZE= ORIENTATION=U KEYBOARD=1 STOP_UI=1
[ -f "$KB/kinlobyte.conf" ] && . "$KB/kinlobyte.conf"

# kterm: its folder holds bin/kterm, its keyboard layouts and terminfo.
# Where it was unpacked differs: look in the usual places, then search.
if [ -z "$KTERM" ] || [ ! -f "$KTERM/bin/kterm" ]; then
    KTERM=""
    for d in /mnt/us/kmc/kpm/packages/kterm /mnt/us/kterm /mnt/us/extensions/kterm \
             /mnt/us/kterm-kindle-2.6/kterm /mnt/us/kterm-kindle-2.6; do
        [ -f "$d/bin/kterm" ] && { KTERM=$d; break; }
    done
fi
if [ -z "$KTERM" ]; then
    # (Package managers such as KMC's kpm keep it several folders deep.)
    k=$(find /mnt/us -maxdepth 7 -type f -path "*/bin/kterm" 2>/dev/null | head -n 1)
    [ -n "$k" ] && KTERM=${k%/bin/kterm}
fi
if [ -z "$KTERM" ]; then
    say "Kinlobyte needs kterm." "Unpack kterm-kindle-2.6.zip onto the" "Kindle, so that kterm/bin/kterm is" "in its main folder."
    exit 1
fi

{
    echo "--- $(date)"
    mkdir -p "$MNT" "$KB/Documents"
    if ! mounted "$MNT"; then
        mount -o loop,noatime -t ext3 "$IMG" "$MNT" || mount -o loop,noatime "$IMG" "$MNT"
    fi
} >> "$LOG" 2>&1
if ! mounted "$MNT"; then
    say "Kinlobyte could not open its system" "(kinlobyte.img). Details are in" "kinlobyte/kinlobyte.log."
    exit 1
fi
{
    for d in proc sys dev dev/pts; do
        mkdir -p "$MNT/$d"
        mounted "$MNT/$d" || mount -o bind "/$d" "$MNT/$d"
    done
    mkdir -p "$MNT/mnt/us"
    mounted "$MNT/mnt/us" || mount -o bind /mnt/us "$MNT/mnt/us"
    # The Kindle's own name server, for the Internet programs.
    cat /etc/resolv.conf > "$MNT/etc/resolv.conf" 2>/dev/null
} >> "$LOG" 2>&1

# The Kindle's reading interface (the Java "framework", about 100 MB of the
# 256 MB) is stopped while Kinlobyte runs; kterm only needs the X server,
# which stays. The screen saver stays off meanwhile: without the reading
# interface the Kindle would not come back from it properly.
UI_STOPPED=""
if [ "$STOP_UI" = 1 ]; then
    {
        lipc-set-prop com.lab126.powerd preventScreenSaver 1
        stop framework && UI_STOPPED=1
    } >> "$LOG" 2>&1
fi

# kterm, as its own launcher starts it: the keyboard layout for this screen.
DPI=$(sed -n 's/.*DPI.*(\([0-9]\+\), [0-9]\+).*/\1/p' /var/log/Xorg.0.log 2>/dev/null | head -n 1)
LAYOUT=""
if [ "${DPI:-0}" -gt 290 ] && [ -f "$KTERM/layouts/keyboard-300dpi.xml" ]; then
    LAYOUT="-l $KTERM/layouts/keyboard-300dpi.xml"
elif [ "${DPI:-0}" -gt 200 ] && [ -f "$KTERM/layouts/keyboard-200dpi.xml" ]; then
    LAYOUT="-l $KTERM/layouts/keyboard-200dpi.xml"
fi
export TERM=xterm DISPLAY="${DISPLAY:-:0}"
[ -d "$KTERM/vte/terminfo" ] && export TERMINFO="$KTERM/vte/terminfo"
echo "kterm: $KTERM" >> "$LOG"
# shellcheck disable=SC2086
[ -x "$KTERM/bin/kterm" ] || chmod 755 "$KTERM/bin/kterm" 2>/dev/null
"$KTERM/bin/kterm" $LAYOUT -c 0 -k "$KEYBOARD" -o "$ORIENTATION" ${FONT_SIZE:+-s "$FONT_SIZE"} \
    -e "/bin/sh $KB/enter.sh" >> "$LOG" 2>&1

leave >> "$LOG" 2>&1
if [ -n "$UI_STOPPED" ]; then
    eips -c >/dev/null 2>&1
    eips 2 3 "Starting the Kindle again ..." >/dev/null 2>&1
    start framework >> "$LOG" 2>&1
fi
[ "$STOP_UI" = 1 ] && lipc-set-prop com.lab126.powerd preventScreenSaver 0 >> "$LOG" 2>&1
exit 0
