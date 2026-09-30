# Kilobyte shared helpers. Sourced by every Kilobyte program; never run directly.
#
# Everything on screen is drawn by dialog(1): coloured character cells, line
# drawing and block glyphs, the same way EDIT.COM or raspi-config look.

KB_VERSION="1.4"
KB_SHARE=/usr/share/kilobyte
KB_LIB=/usr/lib/kilobyte
KB_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/kilobyte"
KB_DOCS="$HOME/Documents"
KB_DESKTOP="$HOME/Desktop"      # its files are the icons on the desktop of Kilobyte Windows

export LANG="${LANG:-C.UTF-8}"
export ESCDELAY=25   # make Esc react at once instead of after a second
export PATH="$PATH:/usr/games:/usr/sbin:/sbin"
# Distinguish every way out of a dialog box.
export DIALOG_OK=0 DIALOG_CANCEL=1 DIALOG_HELP=2 DIALOG_EXTRA=3 \
       DIALOG_ITEM_HELP=4 DIALOG_TIMEOUT=5 DIALOG_ESC=255

mkdir -p "$KB_CONF" 2>/dev/null

# Ctrl-C must not kill a Kilobyte screen. A handler (rather than ignoring the
# signal) is used so that programs started from here still get Ctrl-C, and
# a dialog box interrupted by it simply returns, like Cancel.
trap : INT QUIT

kb_is_live() { [ -d /run/live/medium ]; }

# --- theme ----------------------------------------------------------------

kb_theme_name() {
    local t="${KB_THEME:-$(cat "$KB_CONF/theme" 2>/dev/null)}"
    [ -n "$t" ] && [ -d "$KB_SHARE/themes/$t" ] || t=classic
    echo "$t"
}

# Recolour the Linux console's 16-entry palette from a file of 16 rrggbb
# lines. Other terminals ignore the escape, so this is always safe.
kb_palette() {
    # Only when writing to the console itself: output that is captured
    # (x=$(some-kilobyte-script)) must not contain the colour codes.
    [ "$TERM" = linux ] && [ -t 1 ] || return 0
    if [ -f "$1" ]; then
        local i=0 c
        while read -r c; do
            case $c in [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;; *) continue ;; esac
            printf '\033]P%X%s' "$i" "$c"
            i=$((i + 1))
        done < "$1"
    else
        printf '\033]R'
    fi
}

kb_load_theme() {
    local dir="$KB_SHARE/themes/$(kb_theme_name)"
    export DIALOGRC="$dir/dialogrc"
    export MC_SKIN="$(cat "$dir/mc-skin" 2>/dev/null || echo default)"
    kb_palette "$dir/palette"
}

# --- dialog wrappers ------------------------------------------------------

# Top line of the screen, like a menu bar: product, user, date and time.
# The network in a few words: "Wi-Fi NAME ■■■·", "Wired" or "Offline".
kb_network() {
    local dev ssid level bars
    dev=$(ip route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n 1)
    if [ -z "$dev" ]; then
        echo "Offline"
        return 1
    fi
    if [ -d "/sys/class/net/$dev/wireless" ]; then
        ssid=$(wpa_cli -i "$dev" status 2>/dev/null | sed -n 's/^ssid=//p' | cut -c1-20)
        level=$(awk -v d="$dev:" '$1 == d { printf "%d", $4 }' /proc/net/wireless 2>/dev/null)
        bars=""
        if [ -n "$level" ] && [ "$level" -lt 0 ]; then
            if   [ "$level" -ge -55 ]; then bars=" ■■■■"
            elif [ "$level" -ge -67 ]; then bars=" ■■■·"
            elif [ "$level" -ge -75 ]; then bars=" ■■··"
            else                            bars=" ■···"
            fi
        fi
        echo "Wi-Fi ${ssid:-connected}$bars"
    else
        echo "Wired"
    fi
}

# The mixer control that sets the loudness, if there is a sound card.
kb_mixer() {
    local c
    for c in Master PCM Speaker Headphone; do
        amixer -M sget "$c" >/dev/null 2>&1 && { echo "$c"; return 0; }
    done
    return 1
}

# kb_volume [get | set PERCENT | up | down | mute]: "get" prints 0-100 or "mute".
kb_volume() {
    local c
    c=$(kb_mixer) || return 1
    case ${1:-get} in
        get)  amixer -M sget "$c" 2>/dev/null | awk -F'[][]' '/%/ { v = $2; sub("%", "", v); print ($0 ~ /\[off\]/) ? "mute" : v; exit }' ;;
        set)  amixer -q -M sset "$c" "${2:-50}%" unmute 2>/dev/null || amixer -q -M sset "$c" "${2:-50}%" ;;
        up)   amixer -q -M sset "$c" 5%+ unmute 2>/dev/null || amixer -q -M sset "$c" 5%+ ;;
        down) amixer -q -M sset "$c" 5%- ;;
        mute) amixer -q -M sset "$c" toggle ;;
    esac
}

# For the menu bar of Kilobyte Windows, five lines: network, battery,
# "update" when a newer Kilobyte is known, volume, USB sticks (a;b;c).
kb_status() {
    local net bat vol usb
    net=$(kb_network)
    bat=$(kb_battery)
    vol=$(kb_volume get 2>/dev/null)
    usb=$(kb_usb_list 2>/dev/null | awk -F'|' '{ l = substr($2, 1, 12); gsub(/ +$/, "", l); print l }' | paste -sd';' -)
    printf '%s\n%s\n%s\n%s\n%s\n' "$net" "$bat" "$(kb_update_available && echo update)" "$vol" "$usb"
}

kb_backtitle() {
    local where="${USER:-$(id -un)}@$(hostname 2>/dev/null)" note="" bat
    kb_is_live && where="$where (live)"
    # In Kilobyte Windows the menu bar above already shows the rest.
    if [ -n "${KILOBYTE_DESK:-}" ]; then
        printf ' ■ Kilobyte %s  │  %s' "$KB_VERSION" "$where"
        return
    fi
    note+="  │  $(kb_network)"
    bat=$(kb_battery) && note+="  │  Battery $bat"
    kb_update_available && note+="  │  ▲ Update available"
    printf ' ■ Kilobyte %s  │  %s  │  %s%s' "$KB_VERSION" "$where" "$(date '+%a %d %b  %H:%M')" "$note"
}

# --- battery --------------------------------------------------------------

KB_POWER=${KB_POWER:-/sys/class/power_supply}

kb_psu() { cat "$1/$2" 2>/dev/null; }  # kb_psu DEVICE ATTRIBUTE

# "87%" or "87%+" (charging) for the first battery; nothing without one.
kb_battery() {
    local b
    for b in "$KB_POWER"/*; do
        [ "$(kb_psu "$b" type)" = Battery ] && [ "$(kb_psu "$b" present)" != 0 ] || continue
        [ -n "$(kb_psu "$b" capacity)" ] || continue
        printf '%s%%%s' "$(kb_psu "$b" capacity)" "$([ "$(kb_psu "$b" status)" = Charging ] && echo +)"
        return 0
    done
    return 1
}

# --- sounds ---------------------------------------------------------------

# kb_sound NAME [wait]: play one of Kilobyte's sounds unless switched off.
kb_sound() {
    [ -e /etc/kilobyte/sounds-off ] || [ -e "$KB_CONF/sounds-off" ] && return 0
    local f="$KB_SHARE/sounds/$1.wav"
    [ -r "$f" ] || return 0
    if [ "${2:-}" = wait ]; then
        timeout 4 aplay -q "$f" >/dev/null 2>&1
    else
        (aplay -q "$f" >/dev/null 2>&1 &)
    fi
}

# --- USB sticks -------------------------------------------------------------

# Removable drives, one "PARTITION|description" line each.
kb_usb_list() {
    local live NAME TYPE TRAN RM SIZE MODEL PKNAME LABEL FSTYPE MOUNTPOINT disk
    live=$(lsblk -no PKNAME "$(findmnt -no SOURCE /run/live/medium 2>/dev/null)" 2>/dev/null | head -n 1)
    while read -r line; do
        eval "$line"
        [ -n "$FSTYPE" ] || continue
        [ "$TYPE" = part ] && disk=$PKNAME || disk=${NAME#/dev/}
        disk=${disk#/dev/}
        [ "$disk" = "$live" ] && continue
        case $disk in sr* | loop* | zram*) continue ;; esac
        [ "$(cat "/sys/block/$disk/removable" 2>/dev/null)" = 1 ] ||
            [ "$(lsblk -dno TRAN "/dev/$disk" 2>/dev/null)" = usb ] || continue
        printf '%s|%-12s %6s  %-6s %s%s
' "$NAME" "${LABEL:-no name}" "$SIZE" "$FSTYPE"             "$(lsblk -dno MODEL "/dev/$disk" | xargs)" "${MOUNTPOINT:+  (open)}"
    done < <(lsblk -Ppno NAME,TYPE,TRAN,RM,SIZE,MODEL,PKNAME,LABEL,FSTYPE,MOUNTPOINT 2>/dev/null)
}

# Mount a stick (if needed) and print where it is.
kb_usb_mount() {
    local mnt
    mnt=$(findmnt -no TARGET "$1" 2>/dev/null | head -n 1)
    [ -n "$mnt" ] || mnt=$(sudo -n "$KB_LIB/kb-root" usb mount "$1" 2>/dev/null) || return 1
    [ -d "$mnt" ] && printf '%s\n' "$mnt"
}

# --- updates from GitHub --------------------------------------------------

# True when the last check found a newer Kilobyte than the installed one.
kb_update_available() {
    local latest
    latest=$(cat "$KB_CONF/update-latest" 2>/dev/null) || return 1
    [ -n "$latest" ] && [ "$latest" != "$(cat "$KB_SHARE/commit" 2>/dev/null)" ]
}

# Look for a new version at most once a day, quietly, in the background.
kb_update_check_later() {
    local stamp="$KB_CONF/update-latest"
    [ -n "$(find "$stamp" -mmin -1440 2>/dev/null)" ] && return 0
    (
        read -r _ new < <("$KB_LIB/kb-update" check 2>/dev/null) && echo "$new" > "$stamp"
    ) </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null || true
}

# Run dialog with the common options; the selection is printed on stdout and
# dialog's exit status is returned unchanged.
kb_dialog() {
    dialog --backtitle "$(kb_backtitle)" --colors --cr-wrap "$@" 3>&1 1>&2 2>&3
}

kb_msg() {   # kb_msg TITLE TEXT [HEIGHT WIDTH]
    kb_dialog --title " $1 " --msgbox "$2" "${3:-10}" "${4:-60}"
}

kb_info() {  # kb_info TEXT: a box that stays while a command runs
    kb_dialog --infobox "$1" 5 $(( ${#1} + 6 > 40 ? ${#1} + 6 : 40 ))
}

kb_yesno() { # kb_yesno TITLE TEXT [HEIGHT WIDTH]
    kb_dialog --title " $1 " --yesno "$2" "${3:-9}" "${4:-60}"
}

kb_input() { # kb_input TITLE TEXT [DEFAULT]
    kb_dialog --title " $1 " --inputbox "$2" 10 60 "$3"
}

kb_password() { # kb_password TITLE TEXT
    kb_dialog --title " $1 " --insecure --passwordbox "$2" 10 60
}

kb_textfile() { # kb_textfile TITLE FILE
    kb_dialog --title " $1 " --exit-label "Close" --textbox "$2" 0 0
}

# kb_title TEXT: name the window this runs in (Kilobyte Windows' title bar
# and taskbar). Does nothing outside a window.
kb_title() {
    # (A program in a window of its own keeps the name the window was given.)
    [ -n "${KILOBYTE_DESK:-}" ] && [ -z "${KB_APP_WINDOW:-}" ] && printf '\033]2;%s\007' "$1"
    return 0
}

# A friendly window title for a program.
kb_program_title() {
    local p=$1
    [ "$(basename "$p")" = kb-guard ] && { shift; [ "${1:-}" = -q ] && shift 2; p=${1:-$p}; }
    case $(basename "$p") in
        mcedit) echo Editor ;;      sc-im) echo Spreadsheet ;;  elinks) echo Web ;;
        alpine) echo Email ;;       mc) echo Files ;;           weechat) echo Chat ;;
        calcurse) echo Agenda ;;    htop) echo Tasks ;;         mpv | kb-play) echo Player ;;
        paint) echo Paint ;;        mines) echo Mines ;;        solitaire) echo Solitaire ;;
        reversi) echo Reversi ;;    alsamixer) echo Sound ;;    *) basename "$p" ;;
    esac
}

# Leave dialog's screen and run a fullscreen program on a clean terminal.
kb_run() {
    kb_title "$(kb_program_title "$@")"
    clear
    tput cnorm 2>/dev/null
    "$@"
    local rc=$?
    kb_load_theme   # a program may have reset the console palette
    kb_title "Program Manager"
    return $rc
}

# kb_guarded QUIT-KEYS PROGRAM [ARGS]: kb_run through kb-guard, so Ctrl-C
# closes the program even if it reads the keyboard raw. QUIT-KEYS are typed
# into the program on the first Ctrl-C (empty: end it at once).
kb_guarded() {
    local keys=$1
    shift
    if [ -n "$keys" ]; then
        kb_run "$KB_LIB/kb-guard" -q "$keys" "$@"
    else
        kb_run "$KB_LIB/kb-guard" "$@"
    fi
}

# Run a program, then wait so its output can be read before returning.
kb_run_pause() {
    kb_run "$@"
    local rc=$?
    printf '\n\033[7m Press Enter to return to Kilobyte \033[0m'
    read -r _
    return $rc
}

# Make sure sudo works before a dialog screen needs it, so a password prompt
# never lands in the middle of a drawn box.
kb_sudo() {
    sudo -n true 2>/dev/null && return 0
    clear
    printf '\n  \033[1mKilobyte needs administrator rights for this.\033[0m\n\n'
    sudo -v
}

# kb_pick_file TITLE PATTERN...: choose an existing document or ask for a new
# name. Prints the chosen path; returns non-zero if cancelled.
kb_pick_file() {
    local title=$1 items=() f choice names=() p
    shift
    for p in "$@"; do names+=(${names[0]:+-o} -name "$p"); done
    mkdir -p "$KB_DOCS"
    items+=("<New>" "Create a new file")
    items+=("<Browse>" "Open a file anywhere on the system")
    while IFS= read -r f; do
        items+=("${f#"$KB_DOCS"/}" "$(date -r "$f" '+%d %b %Y %H:%M')")
    done < <(find "$KB_DOCS" -maxdepth 2 -type f \( "${names[@]}" \) 2>/dev/null | sort)

    choice=$(kb_dialog --title " $title " --ok-label "Open" --cancel-label "Back" \
        --menu "Documents in ~/Documents:" 18 64 10 "${items[@]}") || return 1
    case $choice in
        "<New>")
            f=$(kb_input "$title" "Name for the new file (saved in ~/Documents):") || return 1
            [ -n "$f" ] || return 1
            case $f in /*) ;; *) f="$KB_DOCS/$f" ;; esac
            ;;
        "<Browse>")
            f=$(kb_dialog --title " $title - Browse " --fselect "$HOME/" 14 64) || return 1
            [ -f "$f" ] || { kb_msg "$title" "\"$f\" is not a file."; return 1; }
            ;;
        *) f="$KB_DOCS/$choice" ;;
    esac
    printf '%s\n' "$f"
}

# Things Kilobyte expects in a home folder: the Desktop folder, and once per
# version the file manager's Kilobyte settings (file kinds, F2 menu).
kb_setup_home() {
    local mc="$HOME/.config/mc" mark="$HOME/.config/mc/.kilobyte-$KB_VERSION"
    mkdir -p "$KB_DESKTOP" "$KB_CONF" 2>/dev/null
    [ -e "$mark" ] && return 0
    mkdir -p "$mc" || return 0
    if [ -r "$KB_SHARE/mc/ext.ini" ]; then
        { cat "$KB_SHARE/mc/ext.ini"
          [ -r /etc/mc/mc.ext.ini ] && sed '/^\[mc\.ext\.ini\]/,/^$/d' /etc/mc/mc.ext.ini
        } > "$mc/mc.ext.ini.new" && mv "$mc/mc.ext.ini.new" "$mc/mc.ext.ini"
    fi
    if [ -r "$KB_SHARE/mc/menu" ]; then
        { cat "$KB_SHARE/mc/menu"
          [ -r /etc/mc/mc.menu ] && grep -v '^shell_patterns=' /etc/mc/mc.menu
        } > "$mc/menu.new" && mv "$mc/menu.new" "$mc/menu"
    fi
    : > "$mark"
}

kb_load_theme
