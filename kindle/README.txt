KINLOBYTE
=========

Kilobyte, the desktop that is not really one, on a jailbroken Kindle
(made for the Kindle Paperwhite 2; other Kindles with firmware 5 may work).
Black on white, typed with kterm's on-screen keyboard.


WHAT YOU NEED
-------------
  - A jailbroken Kindle with the Universal Hotfix (it shows .sh files in the
    documents folder as "scriptlets" in the Library).
  - kterm 2.6, unpacked anywhere on the Kindle (for example /mnt/us/kterm,
    so that kterm/bin/kterm is in the main folder):
      https://github.com/bfabiszewski/kterm/releases
      kterm-kindle-2.6.zip for firmware up to 5.16.3,
      kterm-kindle-2.6-armhf.zip for newer firmware.
  - About 1 GB free.


INSTALLING
----------
  1. Connect the Kindle to a computer with USB.
  2. Copy both folders from this ZIP to the Kindle's main folder:
       documents/Kinlobyte.sh   -> the Kindle's documents folder
       kinlobyte/               -> a new folder next to documents
  3. Eject the Kindle. "Kinlobyte" appears in the Library.


USING IT
--------
  Tap Kinlobyte in the Library. The Program Manager opens:
    arrow keys       move          (on kterm's keyboard: the arrow keys)
    Enter            run / open
    Esc              back
    first letter     jump to an item
  Quit (Exit) asks to leave Kinlobyte and brings the Kindle back.

  Your documents are in the folder kinlobyte/Documents, which a computer
  sees over USB too. Settings, programs and everything else are kept inside
  kinlobyte.img: nothing is lost when you leave Kinlobyte.

  Leave Kinlobyte before connecting the Kindle to a computer: over USB the
  computer gets the Kindle's storage, kinlobyte.img included, and taking it
  away from a running Kinlobyte can damage it.

  Not on a Kindle: video, music and sound, pictures, Windows and DOS
  programs, printing, and animated games. The Kindle looks after Wi-Fi, the
  clock and the screen.


SETTINGS
--------
  kinlobyte/kinlobyte.conf:
    FONT_SIZE     smaller fits more on the screen (empty: kterm's 8)
    ORIENTATION   U upright, R or L for landscape (more characters per line)
    KEYBOARD      1 shows kterm's keyboard, 0 hides it
    STOP_UI       1 stops the Kindle's reading interface while Kinlobyte
                  runs (more memory for Kinlobyte; the Kindle's home screen
                  is back about half a minute after you leave), 0 keeps it


STARTING STRAIGHT INTO KINLOBYTE
--------------------------------
  Update_kinlobyte_boot_install.bin makes the Kindle open Kinlobyte instead
  of its home screen, once each time it starts. Leaving Kinlobyte brings the
  normal Kindle back until the next start. Nothing of the Kindle's own
  system is replaced: the package adds one start-up job.

  Installing: install Kinlobyte as above first. Then copy the .bin to the
  Kindle's main folder and choose Settings > Menu > Update Your Kindle.

  Turning it off: put a file named DONT_START_KINLOBYTE (any content) in the
  Kindle's main folder, next to documents. Removing it for good:
  Update_kinlobyte_boot_uninstall.bin, installed the same way.


IF IT DOES NOT START
--------------------
  kinlobyte/kinlobyte.log says why. To remove Kinlobyte, delete
  documents/Kinlobyte.sh and the folder kinlobyte.


Copyright (C) 2026 Kilobyte contributors. Kinlobyte is free software under
the GNU General Public License, version 3 or later: see COPYING.
The Debian programs inside kinlobyte.img keep their own licences.
