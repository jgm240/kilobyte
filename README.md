# Kilobyte

**A desktop environment that is not really one.**

Kilobyte is a small Debian-based Linux system whose desktop is drawn entirely
with coloured character cells: box-drawing lines, block characters and
shadows, like EDIT.COM, Norton Commander, Windows 1.0 or `raspi-config`. It
has no graphics server, no window system and no toolkit. It is shell scripts
on top of [`dialog`](https://invisible-island.net/dialog/) and classic
text-mode programs, plus a few small Python programs for the real-time parts
(games, Paint, screen saver).

It runs on 64-bit and 32-bit PCs and on the Raspberry Pi.

```
 ■ Kilobyte 1.3  │  user@kilobyte  │  Tue 29 Sep  14:02  │  Battery 87%
 ─────────────────────────────────────────────────────────────────────────

         ┌──────────── Program Manager ────────────┐   ┌─── Weather ───────
         │ Choose with the arrow keys or first      │   │ Vienna, Austria
         │ letter, then Enter.                      │   │ Sunny        19°C
         │ ┌──────────────────────────────────────┐ │   │ Tue  13°  23°
         │ │ Editor       Text editor             │ │   └───────────────────
         │ │ Spreadsheet  Spreadsheet             │ │   ┌─── News ──────────
         │ │ Web          Web browser             │ │   │ · Headline one
         │ │ Mail         Email                   │ │   │ · Headline two
         │ │ Internet     Internet  »             │ │   └───────────────────
         │ │ Files        File manager            │ │
         │ │ Terminal     Terminal                │ │
         │ │ Media        Media  »                │ │
         │ │ Accessories  Accessories  »          │ │
         │ │ Games        Games  »                │ │
         │ │ Settings     Settings                │ │
         │ └──────────────────────────────────────┘ │
         │         <  Run  >      < Exit  >         │
         └──────────────────────────────────────────┘▒▒
 Write and edit text files (mcedit, F9 opens its menus)
```

## What's inside

| Program Manager entry | Program | |
|---|---|---|
| Editor | `mcedit` | EDIT.COM-style editor with a menu bar (F9); also opens and saves DOCX and ODT |
| Spreadsheet | `sc-im` | formulas; opens and saves XLSX, ODS and CSV, `:w` saves |
| Web | `elinks` | web browser with CSS and JavaScript, menus on Esc |
| Email | `alpine` | Pine's successor; a setup wizard knows Gmail, Outlook, iCloud, Yahoo, GMX, WEB.DE, Posteo, mailbox.org |
| Internet › Chat | `weechat` | IRC: pick a network and a room |
| Internet › BBS Dialer | `telnet`, `ssh`, `luit` | bulletin boards that still run today, with modem sounds and CP437 ANSI art |
| Internet › YouTube Downloader | `yt-dlp` + QuickJS | search, watch, save video (MP4) or sound (MP3) |
| Files | `mc` | Midnight Commander, a Norton Commander clone |
| Terminal | `bash` | fullscreen shell, `exit` returns |
| Media › Video Player | `mpv` | video and music as coloured character blocks, or the real picture |
| Media › Pictures | `mpv` | photos in coloured blocks or the real picture; opens them in Paint |
| Media › Disc Player | `mpv`, `lsdvd` | DVD titles, audio CDs, data discs |
| Internet › Network drives | `cifs-utils`, `sshfs` | shared folders of Windows PCs, NAS boxes (SMB) and SSH servers (SFTP) as folders in `~/Network` |
| Internet › Remote Kilobyte | `ssh` | another Kilobyte (its Program Manager and windows) inside a window |
| Internet › Citrix Workspace | Citrix's own client | installs the package you download from Citrix and runs it on the graphics screen; see below |
| Media › Music Player | Kilobyte (`ffmpeg`, `aplay`) | songs and playlists with spectrum bars |
| Accessories › Trash | Kilobyte | the freedesktop trash: put back or delete for good |
| Accessories › Store | Kilobyte, `apt` | a curated list of text-mode programs from Debian, installed with a keypress |
| Accessories › Lock the screen | Kilobyte | hides everything until the user's password is typed |
| Accessories › Windows programs | Wine, box64, box86 | runs `.exe` and `.msi` files; see below |
| Accessories | Kilobyte | Paint, calculator, agenda (calcurse), block clock, cardfile, calendar, battery meter, character map, print, USB sticks, backup, screen saver |
| Games | Kilobyte, bsdgames, moon-buggy | Mines, Solitaire, Reversi, Moon Buggy, Snake, Robots, Hangman, Adventure, Trek |
| Settings | Kilobyte | Kilobyte Update, Wi-Fi, hotspot, Bluetooth, network, theme, wallpaper, default programs, font, swap, screen saver, desktop tiles, sound, printers, battery, email, keyboard, date and time, software, login and startup, password, task manager |
| Install | `kilobyte-install` | installs the live system to disk (PC live medium only) |

**Swap** (Settings › Swap, `kb-swap`): compressed memory (zram, a quarter to
one and a half times the memory's size, zstd), a swap file on the disk
(`/swapfile`, installed systems only: the live system runs from memory) and
how readily the kernel swaps (swappiness). Compressed memory is set up again
at every start by `kilobyte-swap.service`. Nothing is on by default; on a
computer with little memory, compressed memory is the one to switch on.

**Default programs** (Settings › Defaults): which program opens for each job:
the text editor (Kilobyte's mcedit, nano, vi, Vim, Micro, Emacs), the web
browser (ELinks, Lynx, w3m), the file manager (mc, Ranger), email (Alpine,
NeoMutt), the spreadsheet (sc-im, VisiData) and the music player. The choice
is kept in `~/.config/kilobyte/defaults`; the list is
`/usr/share/kilobyte/defaults.tsv`. A program that is not installed yet is
installed when chosen. The editor is also `$EDITOR`, and mc's F4 opens it.

**Themes** (Settings › Appearance): Classic Blue (EDIT.COM), Norton
Commander, Windows 1.0, Commodore 64, Amiga Workbench 1.3, Mac System 1,
Green Screen, Amber Screen and Hot Dog Stand. On the Linux console the themes
reprogram the 16-colour palette, so the phosphor, C64, Amiga and Mac themes
recolour every program.

**Kilobyte Windows** (`py/desk.py`, `py/deskbg.py`) is a desktop in text
mode. Every program runs in a window of its own: a pseudo terminal emulated
with `pyte` and drawn with the same character cells as everything else. The
Program Manager is one of those windows and stays where it is.

- **Windows** have a title bar with close `[X]`, minimise and maximise boxes,
  a double frame when active and a shadow. Drag a title bar to move a window
  or its corner to resize it: an outline shows where it will go and it moves
  when you let go. Alt+Tab or the bottom bar switch between them.
- **Menu bar** (top): `■ Kilobyte` or F12 opens the *Programs* menu, a
  pull-down with every program by category, the desktop's files, window
  actions, copy and paste, volume, lock, switch user, log out, restart and
  shut down. On the right: update notice, network (Wi-Fi name and signal,
  Wired or Offline), volume (click for a slider), battery and clock; each
  part can be clicked.
- **Desktop**: a wallpaper (Settings › Wallpaper: 15 patterns, your own
  characters, two colours, or a picture dithered into half-block pixels),
  the weather and news tiles, and **icons**: the programs chosen in
  Settings › Desktop icons and every file and folder in `~/Desktop`.
  Double-click opens (files with the program for their kind, `kb-open`); the
  right mouse button offers "Open with" and "Move to the trash".
- **Copy and paste**: drag over text to copy it (with Shift where the program
  uses the mouse itself); the middle button or F11 pastes into the window in
  front, as bracketed paste where the program supports it.
- **Notes** pop up in the lower right corner: download finished, USB stick
  plugged in or removed, network changed, battery low, update available.
  Any program can show one with `kb-notify TITLE TEXT`.
- **Screen saver and lock**: the saver covers every window after the idle
  time from Settings; the lock screen (`py/lock.py`) checks the password
  with PAM's `unix_chkpwd`, so it needs no root.

Programs talk to Kilobyte Windows over a private socket (`KB_DESK_SOCK`,
`py/deskrun.py`): open a window for a program, show a note, put text on the
clipboard, or borrow the whole screen.

**Video in Kilobyte Windows**: a window is a pseudo terminal, so it cannot
switch the console to a pixel font or draw on the screen itself. For the
block modes and the real picture `kb-play` therefore borrows the whole
screen: the windows step aside, the video plays exactly as without windows,
and they return when it ends. The Text picture mode and sound play inside
the window.

**Files**: the file manager (mc) opens files with Kilobyte's programs
(`~/.config/mc/mc.ext.ini`, set up on the first start): documents in the
editor, tables in the spreadsheet, pictures in the block viewer (`kb-view`,
also F3), music in the Music Player, PDF as text. Its F2 menu has "Open
with", "Move to the trash", "Put on the desktop" and "Print".

**Several people**: Settings › Users adds and removes users. "Switch user"
shows another console (a login prompt, or a session that is already there)
while your programs keep running.

**Remote Kilobyte and Citrix**: Settings › Remote login switches the SSH
server on (it is off, and has no host keys, until then); Internet › Remote
Kilobyte on another computer then runs that Kilobyte in a window. Citrix
Workspace is proprietary and may not be redistributed, so Kilobyte cannot
include it: Internet › Citrix Workspace installs the Debian package you
download from Citrix (amd64, arm64, armhf) and runs it, and `.ica` files, on
the graphics screen that Windows programs use (`kb-x`).

**Undoing an update**: Kilobyte Update keeps the previous Kilobyte in
`/var/lib/kilobyte/previous`. Settings › Kilobyte Update can go back to it,
and installed PCs get a boot menu entry "Kilobyte: undo the last update"
(`/etc/grub.d/11_kilobyte_undo`, `kilobyte-undo.service`) for the day an
update leaves Kilobyte unusable.

**Office files**: `kb-office` turns Word and Writer documents (DOCX, ODT) into
plain text for the Editor. Headings become `#`, lists `-` and table rows
`| a | b |`. On saving, the text goes back into the document and its styles,
headers and page layout are kept. Excel and Calc sheets (XLSX, ODS) open in
sc-im with values, text and formulas (SUM, AVERAGE, IF... are translated),
and are written back. Bold, italics, pictures and cell colours are not kept.
The old version is kept as `FILE~`. It uses only Python's standard library.

**The web browser** is ELinks, rebuilt for Kilobyte with JavaScript (MuJS)
and real CSS (NetSurf's libcss and libdom, compiled from source because
Debian does not package them): `image/debs/elinks`. It runs the scripts of
ordinary pages; large web applications are beyond it.

**Mouse**: a click on a menu item highlights it, a click on the highlighted
item (so a double-click) runs it. That is a small patch to `dialog`
(`image/debs/dialog`), rebuilt as a Debian package for each architecture.

**Paint** draws with half blocks: every character cell is two square
pixels in 16 colours. It has pencil, line, box, ellipse, fill, eraser and
colour picker, undo and mouse support. It saves PNG, exports ANSI art (`.ans`)
and imports any picture.

**Video and pictures as coloured blocks.** The video player switches the
console to one of Kilobyte's pixel fonts while a film plays. These fonts are
generated by `tools/make-fonts.py` with 1×2, 2×4 or 4×8 pixels per character.
libcaca (through mpv) draws each cell with a foreground colour, a background
colour and a character from the ramp ` .:;t%SX@8`, and in these fonts each
ramp character is an ordered-dither pattern with exactly that much ink. With
the 1×2 font on a 1280×800 screen the picture is 1280×400 cells, made of
single pixels. "Real picture" plays through DRM straight onto the screen,
still without any graphical desktop.

**Screen saver**: Starfield, bouncing lines or flying floppies, in the 2×4
pixel font, after a few idle minutes in the Program Manager.

**Start-up**: a BIOS-style power-on screen with the real processor, memory
test, drives, network and sound, then the POST beep. Kilobyte plays its own
8-bit start-up and shut-down tunes, generated by `tools/make-sounds.py`.
Each can be switched off.

**Desktop tiles**: on screens at least 132 characters wide, the weather
(wttr.in) and news headlines (any RSS feed) appear beside the Program
Manager.

**Wi-Fi is on by default.** At boot `kilobyte-wifi.service` unblocks the
radios and starts `wpa_supplicant` on every wireless adapter;
`systemd-networkd` gets addresses over DHCP for cable and Wi-Fi. Settings ›
Wi-Fi scans, connects and forgets networks. The **hotspot** turns the Wi-Fi
adapter into an access point that shares the computer's other connection
(`hostapd` plus networkd's DHCP server and masquerading). **Bluetooth**
pairs keyboards, mice, headphones and speakers; sound goes to headphones
through BlueALSA.

**Printing** is driverless (IPP Everywhere, AirPrint, IPP over USB): CUPS
finds printers on the network and on USB.

**USB sticks** open, safely remove and format (FAT32 or exFAT) without a
password, but only removable drives. **Backup** copies documents, pictures,
music, index cards and settings to a stick as a `.tar.gz`, and restores them.

**YouTube** changes often, so the image ships the current `yt-dlp` release
from GitHub rather than Debian's. The downloader can update itself. QuickJS
runs YouTube's JavaScript challenges.

**Windows programs** (Accessories › Windows programs): Wine runs many
Windows programs without Windows. On the 64-bit PC image it is Debian's Wine
with 32-bit support (i386 multiarch), so both 64- and 32-bit programs run; on
the 32-bit PC image, 32-bit programs. On the Raspberry Pi, Wine for PCs (the
newest stable build from WineHQ, in `/opt/wine`) runs through **box64**
(64-bit image, from Debian: 64-bit Windows programs) or **box86** (32-bit
image, built from source by the image build: 32-bit Windows programs), which
translate x86 code to ARM while it runs. Expect it to be slow on a Pi, and
not every program works. Graphical programs open full screen in a Windows
desktop in an X server of their own (`kb-x`, started only for them), and
you are back in Kilobyte when they close; Ctrl+Alt+Backspace leaves at once.
Text-mode programs can run right in the terminal.

**Start-up**: the Kilobyte logo is on screen from the boot menu on. GRUB shows
a graphical Kilobyte menu (text if the screen can't), and from the initramfs
on the logo stays at the top of the console while every kernel and systemd
message scrolls below it (a scroll region; `/usr/lib/kilobyte/bootlogo`).
The boot is verbose by default; the live medium's "quiet start" entry is the
old silent boot.

**Optical drives**: `cdrom`, `sr_mod`, `usb_storage`, `uas`, `isofs` and
`udf` load at boot. Users are in the `cdrom` group, and `/media/cdrom` can be
mounted without root. Encrypted commercial DVDs need `libdvdcss`, which
Debian does not ship (see Help › DVDs).

**Battery**: on laptops the top line shows the charge (`Battery 87%`, `+`
while charging), and Kilobyte warns once below 10%. Accessories › Battery
shows the charge, the capacity (how much of its design capacity the battery
still holds), time left and charge cycles.

**Ctrl-C never drops you into a shell.** In a program it closes the program
and returns to the Program Manager. mcedit, mc, sc-im, calcurse and a few
games read the keyboard raw and would ignore Ctrl-C, so they run under
`kb-guard`, a small pty relay written against `perl-base`. It types the
program's own quit key on the first Ctrl-C (mcedit then offers to save) and
ends the program on the second. In a menu Ctrl-C goes back. In the Program
Manager it opens the Shut Down dialog. Ctrl-Z is disabled. In the Terminal,
Ctrl-C keeps its usual meaning.

**Font**: the console uses Kilobyte's VGA font (`tools/make-console-font.py`).
It is Debian's IBM VGA font with every DOS graphics character and the Western
European letters combined.

**Mouse**: `gpm` provides a block pointer on the text console. Programs that
run under `kb-guard` are on a pseudo terminal and get no mouse there.

## Downloads and builds

| Image | For | Build |
|---|---|---|
| `kilobyte-1.4-amd64.iso` | 64-bit PCs (BIOS, UEFI, and 32-bit EFI such as early Intel Macs) | `./build.sh` |
| `kilobyte-1.4-amd64-usb.img` | USB stick for UEFI PCs and Intel Macs | `./build.sh` |
| `kilobyte-1.4-i386.iso` | 32-bit PCs, from the Pentium 4 era on (BIOS and 32-bit UEFI); Debian 13 with Debian 12's kernel | `./build.sh --arch i386` |
| `kilobyte-1.4-i386-cd.iso` | The same for a 650 MB CD (PCs and laptops that only start from CDs): DOSBox for DOS programs instead of Wine; starts without windows | `./build.sh --arch i386 --cd` |
| `kilobyte-1.4-raspberrypi-arm64.img.xz` | Raspberry Pi 3, 4, 400, 5, 500, Zero 2 W (with Raspberry Pi's own kernel) | `./build.sh --arch arm64` |
| `kilobyte-1.4-raspberrypi-armhf.img.xz` | Raspberry Pi 2, 3 (32-bit) | `./build.sh --arch armhf` |
| `kilobyte-1.4-raspberrypi-armel.img.xz` | Raspberry Pi 1, Zero, Zero W (ARMv6); no Windows programs, and it starts without windows | `./build.sh --arch armel` |

`./build.sh --arch all` builds all five (the PC builds also write a
`-usb.img`).

The long part of a build, installing Debian and some 1,500 packages in an
emulated container, is **cached**: the base system of each architecture is
kept in its Docker volume and reused until the package lists or the patched
packages change (or it is two weeks old). A rebuild after changing only
Kilobyte's own files copies the base, adds the files and runs
`image/customize.sh`: minutes instead of most of an hour. Downloaded
packages and the compiler cache of the patched packages (ccache) are kept
too. `--fresh` rebuilds the base, `--fast` compresses quickly for test
images.

You need Docker. Debian is installed in a container of the target
architecture (emulated when your computer has a different one); compression
runs natively. `--lite` leaves out the large
Wi-Fi firmware (about 70 MB).

The 64-bit image boots from 64-bit UEFI and falls back to 32-bit EFI GRUB
(`BOOTIA32.EFI`) on machines whose firmware is 32-bit although the processor
is 64-bit (old EFI 1.x PCs, the first Intel Macs); Setup installs both, at
the removable-media paths that every firmware looks at.

**Intel Macs** (and UEFI PCs that don't list the ISO stick in their boot
menu): write `kilobyte-1.4-amd64-usb.img` to the stick instead (`dd`, Etcher),
hold ⌥ Option at the chime and choose **EFI Boot**. It is a plain stick: one
FAT32 EFI partition with GRUB, the kernel and the live system, listed in both
a GPT and a hybrid MBR, which is what Apple's firmware looks for. The hybrid
ISO carries a blessed HFS+ volume too, so macOS shows it under Startup Disk,
but the firmware of Macs from around 2008 does not start it from a USB stick.
The USB image is UEFI only; BIOS PCs use the ISO.

The PC images are hybrid ISOs. Burn one to a DVD or write it to a USB stick
(`dd`, Etcher, Rufus in DD mode). Secure Boot must be off. The 32-bit image is
Debian 13 like the others, with the kernel from Debian 12 (6.1 LTS), because
Debian 13 still builds its packages for i386 but no longer a 32-bit PC kernel.

Write the Raspberry Pi images to an SD card with Raspberry Pi Imager
("Use custom") or `xzcat … | dd`. On the first start Kilobyte grows the root
partition to fill the card and asks for keyboard, time zone, computer name
and your account.

## Try it in QEMU

```bash
test/qemu.sh
```

Choose **Install Kilobyte** in the boot menu, or run Setup from the Program
Manager. It installs to the empty test disk. Afterwards boot the result with
`test/qemu.sh --disk`. `--bios` uses a legacy BIOS instead of UEFI.

## Installing

Setup (`kilobyte-install`) is a dialog wizard like the rest. It asks for the
disk, keyboard layout, time zone, computer name, user name, password, and
whether to log in automatically. It then:

1. erases the disk and creates a GPT with a BIOS boot partition, a 512 MB EFI
   partition and an ext4 root, so the disk boots with BIOS or UEFI;
2. copies the live system's pristine root file system onto it;
3. replaces the live user with your account (administrator via `sudo`),
   removes the live-boot tools and installs GRUB for BIOS, UEFI and (on
   64-bit PCs) 32-bit EFI.

The live session's keyboard, font, Wi-Fi networks and theme are carried over.
Automatic login can be changed later in Settings › Login and startup.

## Updates

**Settings › Kilobyte Update** gets new versions of Kilobyte straight from
this repository (`jgm240/kilobyte`, branch `main`; set in
`/usr/share/kilobyte/update.conf`). Every image records the commit it was
built from in `/usr/share/kilobyte/commit`. The update:

1. asks the GitHub API for the newest commit and lists what changed;
2. downloads that commit, checks the shell scripts and the sudoers file;
3. swaps in Kilobyte's own files (`/usr/lib/kilobyte`, `/usr/share/kilobyte`,
   the programs in `/usr/bin` and `/usr/sbin`, Kilobyte's files in `/etc`);
4. installs packages that were added to the package lists since this system
   was built (programs you removed stay removed);
5. restarts the Program Manager.

The owner's settings (keyboard, font, host name, Wi-Fi, accounts, theme) are
never touched. Kilobyte checks once a day in the background and shows
`▲ Update available` in the top line. Debian packages are updated in
Settings › Software. On the live system an update lasts until a restart.

So publishing an update means pushing to `main`.

## Live session

The PC live system logs in as `user` (password `live`) on tty1 and starts the
Program Manager. Ctrl+Alt+F2...F6 give ordinary login consoles. Kilobyte
starts automatically after any login on tty1-tty6; this can be turned off in
Settings › Login and startup.

## Layout

```
build.sh                     host entry point (Docker), --arch amd64|i386|arm64|armhf|armel|all
image/
  build-in-container.sh      mmdebstrap -> squashfs -> grub-mkrescue, or -> Pi SD image
  customize.sh               runs in the chroot: live user or Pi first start, services
  packages.txt               packages on every architecture
  packages-pc.txt            PCs: live-boot, GRUB, laptop sound firmware
  packages-pi.txt            Raspberry Pi: boot firmware, SD card resize
  packages-wifi.txt          Wi-Fi firmware (skipped by --lite)
  grub.cfg                   live medium boot menu
  debs/                      Debian packages rebuilt for Kilobyte (dialog, elinks)
rootfs/                      copied over the Debian root file system
  usr/bin/kilobyte           the Program Manager
  usr/lib/kilobyte/lib.sh    shared dialog helpers, theming, sounds, USB
  usr/lib/kilobyte/apps/     settings, player, pictures, youtube, disc, mail,
                             chat, bbs, paint, mines, solitaire, reversi, saver,
                             usb, backup, print, battery, calculator, clock...
  usr/lib/kilobyte/py/       kbui.py (half-block canvas for the Python programs), tiles.py
  usr/lib/kilobyte/kb-root   the few root actions allowed without a password
  usr/lib/kilobyte/kb-guard  makes Ctrl-C close programs that ignore it
  usr/lib/kilobyte/kb-play   mpv in block, real-picture or audio mode
  usr/lib/kilobyte/kb-update Kilobyte Update from GitHub
  usr/lib/kilobyte/kb-hotspot, kb-tiles, post, wifi-up, resize-root
  usr/sbin/kilobyte-install  the PC installer
  usr/sbin/kilobyte-firstboot  the Raspberry Pi first start
  usr/share/kilobyte/        themes, pixel fonts, sounds, help, start page
  usr/share/consolefonts/    Kilobyte's VGA console font
tools/                       generators for themes, fonts, sounds, console font
test/qemu.sh                 boot the ISO or the installed disk in QEMU
```

On any Debian or Ubuntu machine, Kilobyte also runs without the image: install
the packages from `image/packages.txt`, copy `rootfs/usr` into place and run
`kilobyte`.

## Licence

Copyright (C) 2026 Kilobyte contributors.

Kilobyte is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See [LICENSE](LICENSE) for the details.

This covers Kilobyte's own files (this repository). The images also contain
Debian and other programs (Wine, box86, yt-dlp, Raspberry Pi's kernel and
firmware, ...), each under its own licence; on a running system they are in
`/usr/share/doc/*/copyright`.
