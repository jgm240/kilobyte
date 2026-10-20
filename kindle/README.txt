KILOBYTEINK
===========

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
       documents/KilobytEink.sh   -> the Kindle's documents folder
       kilobyteink/               -> a new folder next to documents
  3. Eject the Kindle. "KilobytEink" appears in the Library.


USING IT
--------
  Tap KilobytEink in the Library. The Program Manager opens:
    arrow keys       move          (on kterm's keyboard: the arrow keys)
    Enter            run / open
    Esc              back
    first letter     jump to an item
  Quit (Exit) asks to leave KilobytEink and brings the Kindle back.

  Your documents are in the folder kilobyteink/Documents, which a computer
  sees over USB too. Settings, programs and everything else are kept inside
  kilobyteink.img: nothing is lost when you leave KilobytEink.

  Leave KilobytEink before connecting the Kindle to a computer: over USB the
  computer gets the Kindle's storage, kilobyteink.img included, and taking it
  away from a running KilobytEink can damage it.

  Not on a Kindle: video, music and sound, pictures, Windows and DOS
  programs, printing, and animated games. The Kindle looks after Wi-Fi, the
  clock and the screen.


SETTINGS
--------
  kilobyteink/kilobyteink.conf:
    FONT_SIZE     smaller fits more on the screen (empty: kterm's 8)
    ORIENTATION   U upright, R or L for landscape (more characters per line)
    KEYBOARD      1 shows kterm's keyboard, 0 hides it
    STOP_UI       1 stops the Kindle's reading interface while KilobytEink
                  runs (more memory for KilobytEink; the Kindle's home screen
                  is back about half a minute after you leave), 0 keeps it


STARTING STRAIGHT INTO KILOBYTEINK
--------------------------------
  Update_kilobyteink_boot_install.bin makes the Kindle open KilobytEink instead
  of its home screen, once each time it starts. Leaving KilobytEink brings the
  normal Kindle back until the next start. Nothing of the Kindle's own
  system is replaced: the package adds one start-up job.

  Installing: install KilobytEink as above first. Then copy the .bin to the
  Kindle's main folder and choose Settings > Menu > Update Your Kindle.

  Turning it off: put a file named DONT_START_KILOBYTEINK (any content) in the
  Kindle's main folder, next to documents. Removing it for good:
  Update_kilobyteink_boot_uninstall.bin, installed the same way.


COMING FROM KINLOBYTE
---------------------
  KilobytEink was called Kinlobyte before. To move over, copy only the new
  documents/KilobytEink.sh to the Kindle and tap it: it renames the folder
  kinlobyte to kilobyteink (your documents and settings stay) and removes
  the old Kinlobyte.sh. If the Kindle starts straight into it, install the
  new Update_kilobyteink_boot_install.bin as well; it replaces the old job.


IF IT DOES NOT START
--------------------
  kilobyteink/kilobyteink.log says why. To remove KilobytEink, delete
  documents/KilobytEink.sh and the folder kilobyteink.


Copyright (C) 2026 Kilobyte contributors. KilobytEink is free software under
the GNU General Public License, version 3 or later: see COPYING.
The Debian programs inside kilobyteink.img keep their own licences.
