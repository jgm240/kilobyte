# Kilobyte

**A desktop environment that is not really one.**

Kilobyte is a small Debian-based Linux system whose desktop is drawn entirely
with coloured character cells: box-drawing lines, block characters and
shadows, like EDIT.COM, Norton Commander, Windows 1.0 or `raspi-config`. It
has no graphics server, no window system and no toolkit. It is a set of shell
scripts on top of [`dialog`](https://invisible-island.net/dialog/), plus
classic text-mode programs.

```
 ■ Kilobyte 1.0   │   user@kilobyte   │   Tue 29 Sep 2026  14:02
 ──────────────────────────────────────────────────────────────────

            ┌──────────── Program Manager ────────────┐
            │ Pick a program with the arrow keys or   │
            │ its first letter, then press Enter.     │
            │ ┌─────────────────────────────────────┐ │
            │ │ Editor       Text editor            │ │
            │ │ Spreadsheet  Spreadsheet            │ │
            │ │ Web          Web browser            │ │
            │ │ Files        File manager           │ │
            │ │ Terminal     Terminal               │ │
            │ │ Accessories  Accessories  ►         │ │
            │ │ Games        Games  ►               │ │
            │ │ Settings     Settings               │ │
            │ └─────────────────────────────────────┘ │
            ├─────────────────────────────────────────┤
            │        <  Run  >      < Exit  >         │
            └─────────────────────────────────────────┘▒▒
              ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
 Write and edit text files (mcedit, F9 opens its menus)
```

## What's inside

| Program Manager entry | Program | |
|---|---|---|
| Editor | `mcedit` | EDIT.COM-style editor with a menu bar (F9) |
| Spreadsheet | `sc-im` | formulas, CSV/XLSX import, `:w` saves |
| Web | `links` | text-mode web browser with menus (Esc) |
| Files | `mc` | Midnight Commander, a Norton Commander clone |
| Email | `alpine` | Pine's successor; a setup wizard knows Gmail, Outlook, iCloud, Yahoo, GMX, WEB.DE, Posteo, mailbox.org |
| Media › Video Player | `mpv` | video and music as coloured character blocks, or the real picture |
| Media › YouTube Downloader | `yt-dlp` + QuickJS | search, watch, save video (MP4) or sound (MP3) |
| Media › Disc Player | `mpv`, `lsdvd` | DVD titles, audio CDs, data discs |
| Media › Sound volume | `alsamixer` | |
| Terminal | `bash` | fullscreen shell, `exit` returns |
| Accessories | Kilobyte | calculator (bc), agenda (calcurse), big block clock, cardfile, calendar, battery meter, character map |
| Games | bsdgames, moon-buggy | Moon Buggy, Snake, Robots, Hangman, Adventure, Trek... |
| Settings | Kilobyte | Kilobyte Update, Wi-Fi, network, colour theme, console font, battery, email account, sound, keyboard, date/time zone, add/remove programs, password, task manager (htop), autostart, about |
| Install | `kilobyte-install` | installs the live system to disk (live medium only) |

**Themes** (Settings › Appearance): Classic Blue (EDIT.COM), Norton
Commander, Windows 1.0, Green Screen, Amber Screen, Hot Dog Stand. On the
Linux console the phosphor themes reprogram the 16-colour palette, so every
program turns green or amber.

**Video as coloured blocks.** The video player switches the text console to
one of Kilobyte's pixel fonts while a film plays. These fonts are generated
by `tools/make-fonts.py` with 1×2, 2×4 or 4×8 pixels per character. libcaca
(through mpv) draws each cell with a foreground colour, a background colour
and a character from the ramp ` .:;t%SX@8`. In these fonts each ramp
character is an ordered-dither pattern with exactly that much "ink". On a
1280×800 screen the 1×2 font gives 1280×400 cells, so the picture is made of
single pixels in the 16 console colours. Afterwards the normal font comes
back. If a screen is too large for the console's cell limit, the next larger
size is used. "Real picture" plays through DRM straight onto the screen,
still without any graphical desktop.

**YouTube** changes often, so the image ships the current `yt-dlp` release
from GitHub rather than Debian's. The downloader can update itself, which
needs no password. QuickJS runs YouTube's JavaScript challenges.

**Optical drives**: `cdrom`, `sr_mod`, `usb_storage`, `uas`, `isofs` and
`udf` load at boot. Users are in the `cdrom` group, and `/media/cdrom` can be
mounted without root. `eject` and `lsdvd` are included. Encrypted commercial
DVDs need `libdvdcss`, which Debian does not ship (see Help › DVDs).

**Battery**: on laptops the top line shows the charge (`Battery 87%`, `+`
while charging), and Kilobyte warns once below 10%. Accessories › Battery
shows block gauges for charge and capacity (how much of its design capacity
the battery still holds), time left or time to full, and charge cycles.

**Wi-Fi is on by default.** At boot `kilobyte-wifi.service` unblocks the
radios and starts `wpa_supplicant` on every wireless adapter.
`systemd-networkd` gets addresses over DHCP for both cable and Wi-Fi.
Settings › Wi-Fi scans, connects, forgets networks and turns the radio on or
off. Firmware for Intel, Realtek, Atheros, Broadcom and MediaTek adapters is
included.

**Ctrl-C never drops you into a shell.** In a program it closes the program
and returns to the Program Manager. mcedit, mc, sc-im, calcurse and a few
games read the keyboard raw and would ignore Ctrl-C, so they run under
`kb-guard`, a small pty relay written against `perl-base`. It types the
program's own quit key on the first Ctrl-C (mcedit then offers to save) and
ends the program on the second. In a menu Ctrl-C goes back. In the Program
Manager it opens the Shut Down dialog. Ctrl-Z is disabled. In the Terminal,
Ctrl-C keeps its usual meaning.

**Font**: the console uses the IBM VGA font with the full DOS graphics set
(`FullGreek-VGA16`): blocks, shades, double lines, arrows and card suits.

**Mouse**: `gpm` provides a block pointer on the text console. Programs that
run under `kb-guard` are on a pseudo terminal and get no mouse.

## Build

You need Docker. Debian is installed in an x86-64 `debian:trixie`
container, which is emulated on Apple Silicon. Compression, the slow part,
runs in a native container.

```bash
./build.sh
```

The ISO is written to `out/kilobyte-1.0-amd64.iso`. It is a hybrid image:
burn it to a CD or write it to a USB stick (`dd`, Etcher, Rufus in DD mode),
and it boots on BIOS and UEFI PCs. Secure Boot must be off.

`./build.sh --lite` leaves out the large Wi-Fi firmware, which makes the ISO
about 70 MB smaller.

## Try it in QEMU

```bash
test/qemu.sh
```

Choose **Install Kilobyte** in the boot menu, or run Setup from the Program
Manager. It installs to the empty test disk. Afterwards boot the result:

```bash
test/qemu.sh --disk
```

`--bios` uses a legacy BIOS instead of UEFI.

## Installing

Setup (`kilobyte-install`) is a dialog wizard like the rest. It asks for the
disk, keyboard layout, time zone, computer name, user name and password. It
then:

1. erases the disk and creates a GPT with a BIOS boot partition, a 512 MB EFI
   partition and an ext4 root, so the disk boots with BIOS or UEFI;
2. copies the live system's pristine root file system onto it;
3. replaces the live user with your account (administrator via `sudo`),
   removes the live-boot tools and installs GRUB for both BIOS and UEFI.

The live session's keyboard, font, Wi-Fi networks and theme are carried over.

## Updates

**Settings › Kilobyte Update** gets new versions of Kilobyte straight from
this repository (`jgm240/kilobyte`, branch `main`; set in
`/usr/share/kilobyte/update.conf`). Every image records the commit it was
built from in `/usr/share/kilobyte/commit`. The update:

1. asks the GitHub API for the newest commit and lists what changed;
2. downloads that commit, checks the shell scripts and the sudoers file;
3. swaps in Kilobyte's own files (`/usr/lib/kilobyte`, `/usr/share/kilobyte`,
   `kilobyte`, `kilobyte-install` and Kilobyte's files in `/etc`);
4. installs packages that were added to `image/packages.txt`;
5. restarts the Program Manager.

The owner's settings (keyboard, font, host name, Wi-Fi, accounts, theme) are
never touched. Kilobyte checks once a day in the background and shows
`▲ Update available` in the top line. Debian packages are updated separately,
in Settings › Software. On the live system an update lasts until a restart.

So publishing an update means pushing to `main`.

## Live session

The live system logs in as `user` (password `live`) on tty1 and starts the
Program Manager. Ctrl+Alt+F2...F6 give ordinary login consoles. Kilobyte
starts automatically after any login on tty1-tty6; this can be turned off in
Settings › Startup.

## Layout

```
build.sh                    host entry point (Docker)
image/
  build-in-container.sh     mmdebstrap -> squashfs -> grub-mkrescue
  customize.sh              runs in the chroot: live user, services, cleanup
  packages.txt              everything in the image
  packages-wifi.txt         Wi-Fi firmware (skipped by --lite)
  grub.cfg                  live medium boot menu
rootfs/                     copied over the Debian root file system
  usr/bin/kilobyte          the Program Manager
  usr/lib/kilobyte/lib.sh   shared dialog helpers and theming
  usr/lib/kilobyte/apps/    settings, calculator, clock, cardfile, player,
                            youtube, disc
  usr/lib/kilobyte/kb-play  mpv in block, real-picture or audio mode
  usr/lib/kilobyte/kb-update Kilobyte Update from GitHub
  usr/share/kilobyte/fonts/ the pixel fonts for block video
  usr/lib/kilobyte/kb-root  the few root actions allowed without a password
  usr/lib/kilobyte/kb-guard makes Ctrl-C close programs that ignore it
  usr/lib/kilobyte/wifi-up  boot-time Wi-Fi
  usr/sbin/kilobyte-install the installer
  usr/share/kilobyte/       themes, help, start page, character map
tools/make-themes.py        regenerates the theme files
tools/make-fonts.py         regenerates the pixel fonts
test/qemu.sh                boot the ISO or the installed disk in QEMU
```

On any Debian or Ubuntu machine, Kilobyte also runs without the image: install
`dialog mc links sc-im calcurse htop bc`, copy `rootfs/usr` into place and run
`kilobyte`.
