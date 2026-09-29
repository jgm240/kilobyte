# Kilobyte shared helpers. Sourced by every Kilobyte program; never run directly.
#
# Everything on screen is drawn by dialog(1): coloured character cells, line
# drawing and block glyphs, the same way EDIT.COM or raspi-config look.

KB_VERSION="1.0"
KB_SHARE=/usr/share/kilobyte
KB_LIB=/usr/lib/kilobyte
KB_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/kilobyte"
KB_DOCS="$HOME/Documents"

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
    [ "$TERM" = linux ] || return 0
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
kb_backtitle() {
    local where="${USER:-$(id -un)}@$(hostname 2>/dev/null)" note="" bat
    kb_is_live && where="$where (live)"
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

# Leave dialog's screen and run a fullscreen program on a clean terminal.
kb_run() {
    clear
    tput cnorm 2>/dev/null
    "$@"
    local rc=$?
    kb_load_theme   # a program may have reset the console palette
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

kb_load_theme
