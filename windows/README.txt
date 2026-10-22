KILOBYTE FOR WINDOWS (kilobyte-transition)
==========================================

Kilobyte, the text-mode desktop, in Windows: a Linux system of its own in
WSL, shown in Windows Terminal with Kilobyte's colours and pixel font.

  kb open             go to Kilobyte
  kb close            close Kilobyte
  kb autolaunch on    open Kilobyte when you sign in to Windows
  kb autolaunch off   do not
  kb size N           its text size (16, the size it has on a PC; 24, 32...)
  kb remove           remove Kilobyte (its system and its files)

The first "kb open" sets everything up:
  - if WSL (the part of Windows that runs Linux systems) is off, it turns it
    on; Windows asks for permission and then wants one restart
  - it downloads the Kilobyte system (a few hundred MB), checks it and sets
    it up as the WSL system "Kilobyte", with a user named after yours
  - it adds Kilobyte's font and a "Kilobyte" profile to Windows Terminal

Kilobyte keeps its files in its own system; Windows' drives are in /mnt
(C: is /mnt/c). Kilobyte Update (in Settings) keeps Kilobyte new.

Installing: winget install Kilobyte.Transition
Website:    https://jgm240.github.io/kilobyte/

Copyright (C) 2026 Kilobyte contributors. Free software: GNU General Public
License, version 3 or later (COPYING). The font is GNU GPL 2 or later.
