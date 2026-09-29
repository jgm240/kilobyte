# box64/box86 (Windows programs on ARM): their code translator does not run
# on Apple processors (Kilobyte in a virtual machine on a Mac), so there they
# interpret, which is slower but works.
if grep -q '^CPU implementer.*0x61' /proc/cpuinfo 2>/dev/null; then
    export BOX64_DYNAREC=0 BOX86_DYNAREC=0
fi
export BOX64_NOBANNER=1 BOX86_NOBANNER=1

# Start Kilobyte after logging in on a text console (tty1-tty6).
if [ -z "${KILOBYTE:-}" ] && [ -z "${KILOBYTE_SHELL:-}" ] && [ -t 0 ] \
   && [ ! -e "$HOME/.config/kilobyte/noautostart" ] && command -v kilobyte >/dev/null; then
    case $(tty) in
        /dev/tty[1-6])
            # "Install Kilobyte" boot entry: open Setup once, on the first console.
            if [ "$(tty)" = /dev/tty1 ] && [ -d /run/live/medium ] \
               && grep -qw kilobyte.install /proc/cmdline && [ ! -e /run/kilobyte-setup-offered ]; then
                sudo touch /run/kilobyte-setup-offered
                sudo /usr/sbin/kilobyte-install
            fi
            # Log out when Kilobyte ends, stay in the shell only when the
            # user asked for it, and restart Kilobyte after anything else.
            printf '\033[r'     # the start-up logo's scroll region ends here
            while :; do
                kilobyte
                case $? in
                    0) exit ;;
                    3) break ;;
                esac
            done
            ;;
    esac
fi
