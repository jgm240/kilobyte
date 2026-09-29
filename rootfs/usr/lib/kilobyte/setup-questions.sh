# Kilobyte's setup questions, shared by the installer (kilobyte-install) and
# the Raspberry Pi first start (kilobyte-firstboot). Each function sets a
# global variable and fails when the person cancels.
#   KEYMAP TZONE HOST NAME PW1 AUTOLOGIN
# Set RESERVED_USERS_FROM to the passwd file whose names may not be taken,
# and LIVE_USER to a name that is allowed anyway.

ask_keyboard() {
    local cur
    cur=$(sed -n 's/^XKBLAYOUT="\?\([^"]*\)"\?/\1/p' /etc/default/keyboard 2>/dev/null)
    KEYMAP=$(kb_dialog --title " Keyboard " --default-item "${KEYMAP:-${cur:-us}}" --ok-label "Next" --cancel-label "Cancel" \
        --menu "Keyboard layout:" 20 60 12 \
        us "English (US)"   gb "English (UK)"   de "German"      at "German (Austria)" \
        ch "Swiss"          fr "French"         be "Belgian"     es "Spanish" \
        pt "Portuguese"     br "Portuguese (Brazil)" it "Italian" nl "Dutch" \
        dk "Danish"         no "Norwegian"      se "Swedish"     "fi" "Finnish" \
        pl "Polish"         cz "Czech"          hu "Hungarian"   tr "Turkish" \
        ru "Russian"        ua "Ukrainian"      gr "Greek"       jp "Japanese" \
        latam "Spanish (Latin America)" ca "Canadian (French)")
}

ask_timezone() {
    local region city cities f
    TZONE=${TZONE:-$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')}
    TZONE=${TZONE:-UTC}
    while true; do
        region=$(kb_dialog --title " Time Zone " --default-item "${TZONE%%/*}" --ok-label "Next" --cancel-label "Cancel" \
            --menu "Region (now: $TZONE):" 20 50 12 \
            Africa "" America "" Antarctica "" Arctic "" Asia "" Atlantic "" \
            Australia "" Europe "" Indian "" Pacific "" UTC "Universal time") || return 1
        if [ "$region" = UTC ]; then TZONE=UTC; return 0; fi
        cities=()
        while IFS= read -r f; do cities+=("${f#/usr/share/zoneinfo/"$region"/}" ""); done \
            < <(find "/usr/share/zoneinfo/$region" -type f | sort)
        city=$(kb_dialog --title " Time Zone - $region " --default-item "${TZONE#*/}" --ok-label "Next" --cancel-label "Back" \
            --menu "City:" 20 50 12 "${cities[@]}") && { TZONE="$region/$city"; return 0; }
    done
}

ask_hostname() {
    while true; do
        HOST=$(kb_input "Computer Name" "A name for this computer on the network:" "${HOST:-kilobyte}") || return 1
        [[ $HOST =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$ ]] && return 0
        kb_msg "Computer Name" "Use only letters, digits and dashes." 7 50
    done
}

ask_user() {
    while true; do
        NAME=$(kb_input "Your Account" "Your user name (lower case, e.g. \"ada\"):" "${NAME:-}") || return 1
        if [[ ! $NAME =~ ^[a-z][a-z0-9_-]{0,31}$ ]]; then
            kb_msg "Your Account" "Start with a letter; use only lower case letters, digits, - and _." 7 60
        elif [ "$NAME" != "${LIVE_USER:-}" ] && grep -q "^$NAME:" "${RESERVED_USERS_FROM:-/etc/passwd}"; then
            kb_msg "Your Account" "\"$NAME\" is reserved by the system. Pick another name." 7 60
        else
            return 0
        fi
    done
}

ask_password() {
    local pw2
    while true; do
        PW1=$(kb_password "Your Account" "Password for $NAME:") || return 1
        pw2=$(kb_password "Your Account" "Type the password again:") || return 1
        if [ -z "$PW1" ]; then
            kb_msg "Your Account" "The password must not be empty." 7 50
        elif [ "$PW1" != "$pw2" ]; then
            kb_msg "Your Account" "The passwords do not match." 7 50
        else
            return 0
        fi
    done
}

ask_autologin() {
    AUTOLOGIN=no
    kb_dialog --title " Your Account " --defaultno --yes-label "Automatic" --no-label "Password" --yesno \
"How should $NAME log in when the computer starts?

  \\ZbPassword\\Zn    type the password each time (safer)
  \\ZbAutomatic\\Zn   go straight to the Program Manager

This can be changed later in Settings > Login and startup." 12 64 && AUTOLOGIN=yes
    return 0
}

# The groups a Kilobyte user belongs to, as far as they exist in GROUP_FILE.
user_groups() {
    local g out=""
    for g in sudo users netdev audio video plugdev cdrom lpadmin bluetooth; do
        grep -q "^$g:" "${1:-/etc/group}" && out+="$g,"
    done
    printf '%s' "${out%,}"
}

# write_autologin ROOT USER: log USER in on tty1 without a password.
write_autologin() {
    mkdir -p "$1/etc/systemd/system/getty@tty1.service.d"
    printf '[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin %s --noclear %%I $TERM\n' "$2" \
        > "$1/etc/systemd/system/getty@tty1.service.d/autologin.conf"
}
