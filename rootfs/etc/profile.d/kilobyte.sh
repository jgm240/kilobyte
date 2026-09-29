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
