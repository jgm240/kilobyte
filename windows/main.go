// kb.exe: Kilobyte for Windows (the kilobyte-transition WinGet package).
//
// Kilobyte runs as a WSL system of its own ("Kilobyte"), in Windows Terminal
// with its colours and pixel font:
//
//	kb open             go to Kilobyte (the first time: turn WSL on if it is
//	                    off, then download and set up the Kilobyte system)
//	kb close            close Kilobyte
//	kb autolaunch on    open Kilobyte when you sign in to Windows
//	kb autolaunch off   do not
//	kb autolaunch       say which it is
//	kb size N           Kilobyte's text size (as on the Mac: 16 is the size it
//	                    has on a PC, each font pixel one screen pixel; 24, 32...)
//	kb size auto        16 again
//	kb remove           remove the Kilobyte system and everything kb added
//
// Copyright (C) 2026 Kilobyte contributors. GNU GPL, version 3 or later.
package main

import (
	"bufio"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

// Set when building (tools/make-windows.sh): the system to download.
var (
	version      = "dev"
	rootfsURL    = ""
	rootfsSHA256 = ""
)

const distro = "Kilobyte"

//go:embed assets/kilobyte-vga16.ttf
var fontData []byte

//go:embed assets/kilobyte.ico
var iconData []byte

var (
	local    = os.Getenv("LOCALAPPDATA")
	home     = filepath.Join(local, "Kilobyte")
	fontFile = filepath.Join(local, "Microsoft", "Windows", "Fonts", "KilobyteVGA.ttf")
	fragment = filepath.Join(local, "Microsoft", "Windows Terminal", "Fragments", "Kilobyte", "kilobyte.json")
)

const runKey = `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
const fontKey = `HKCU\Software\Microsoft\Windows NT\CurrentVersion\Fonts`

func main() {
	args := append(os.Args[1:], "", "")
	var err error
	switch args[0] + " " + args[1] {
	case "open ":
		err = open()
	case "close ":
		err = run("wsl.exe", "--terminate", distro)
	case "autolaunch on":
		err = autolaunch(true)
	case "autolaunch off":
		err = autolaunch(false)
	case "autolaunch ":
		if exec.Command("reg.exe", "query", runKey, "/v", distro).Run() == nil {
			fmt.Println("on: Kilobyte opens when you sign in to Windows")
		} else {
			fmt.Println("off: Kilobyte does not open by itself")
		}
	case "size ":
		fmt.Printf("Kilobyte's text size: %d (16 is the size it has on a PC)\n", textSize())
	case "size auto":
		os.Remove(filepath.Join(home, "size"))
		fmt.Println("Kilobyte's text size: 16. kb open shows it.")
	case "size " + args[1]:
		n, perr := strconv.Atoi(args[1])
		if perr != nil || n < 4 || n > 200 {
			err = fmt.Errorf("a size such as 16, 24 or 32, or auto")
			break
		}
		os.MkdirAll(home, 0o755)
		err = os.WriteFile(filepath.Join(home, "size"), []byte(strconv.Itoa(n)+"\n"), 0o644)
		if err == nil {
			fmt.Printf("Kilobyte's text size: %d (sharpest at 8, 16, 24, 32...). kb open shows it.\n", n)
		}
	case "remove ":
		err = remove()
	case "version ", "--version ":
		fmt.Println("kb (Kilobyte for Windows) " + version)
	default:
		fmt.Print(usage)
		if args[0] != "" && args[0] != "help" && args[0] != "--help" && args[0] != "-h" {
			os.Exit(2)
		}
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "kb:", err)
		os.Exit(1)
	}
}

const usage = `kb: Kilobyte, the text-mode desktop, in Windows.

  kb open             go to Kilobyte (the first time it sets it up)
  kb close            close Kilobyte
  kb autolaunch on    open Kilobyte when you sign in to Windows
  kb autolaunch off   do not
  kb size N           its text size (16, as on a PC; 24, 32... bigger)
  kb remove           remove Kilobyte (its system and its files)

https://jgm240.github.io/kilobyte/
`

func run(name string, args ...string) error {
	c := exec.Command(name, args...)
	c.Stdout, c.Stderr, c.Stdin = os.Stdout, os.Stderr, os.Stdin
	c.Env = append(os.Environ(), "WSL_UTF8=1")
	return c.Run()
}

// output runs a command and gives its output as text (wsl.exe can answer in
// UTF-16: the zero bytes are taken out).
func output(name string, args ...string) (string, error) {
	c := exec.Command(name, args...)
	c.Env = append(os.Environ(), "WSL_UTF8=1")
	b, err := c.CombinedOutput()
	return strings.ReplaceAll(string(b), "\x00", ""), err
}

func ask(question string) bool {
	fmt.Print(question + " [y/N] ")
	line, _ := bufio.NewReader(os.Stdin).ReadString('\n')
	line = strings.ToLower(strings.TrimSpace(line))
	return line == "y" || line == "yes" || line == "j" || line == "ja"
}

// WSL: on, and able to run a system?
func wslReady() bool {
	if _, err := exec.LookPath("wsl.exe"); err != nil {
		return false
	}
	_, err := output("wsl.exe", "--status")
	return err == nil
}

// turnOnWSL turns WSL on (Windows asks for permission); a restart finishes it.
func turnOnWSL() error {
	fmt.Println("WSL, the part of Windows that runs Linux systems, is not on yet.")
	fmt.Println("Turning it on: Windows asks for permission...")
	ps := `$p = Start-Process -FilePath wsl.exe -ArgumentList '--install','--no-distribution' -Verb RunAs -Wait -PassThru; exit $p.ExitCode`
	if err := run("powershell.exe", "-NoProfile", "-Command", ps); err != nil {
		return fmt.Errorf("WSL could not be turned on (%v). In a terminal opened as administrator: wsl --install", err)
	}
	fmt.Println()
	fmt.Println("WSL is on. Windows has to restart once to finish; after that, type  kb open  again.")
	if ask("Restart Windows now?") {
		return run("shutdown.exe", "/r", "/t", "5", "/c", "Restarting to finish turning on WSL for Kilobyte")
	}
	os.Exit(0)
	return nil
}

func haveDistro() bool {
	out, err := output("wsl.exe", "--list", "--quiet")
	if err != nil {
		return false
	}
	for _, l := range strings.Split(out, "\n") {
		if strings.TrimSpace(l) == distro {
			return true
		}
	}
	return false
}

// download fetches the Kilobyte system and checks it against its checksum.
func download(dest string) error {
	if rootfsURL == "" {
		return fmt.Errorf("this kb.exe was built without the address of the Kilobyte system")
	}
	fmt.Println("Downloading Kilobyte from", rootfsURL)
	resp, err := http.Get(rootfsURL)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("download failed: %s", resp.Status)
	}
	f, err := os.Create(dest + ".part")
	if err != nil {
		return err
	}
	h := sha256.New()
	total, done, shown := resp.ContentLength, int64(0), int64(-1)
	buf := make([]byte, 1<<20)
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			f.Write(buf[:n])
			h.Write(buf[:n])
			done += int64(n)
			if total > 0 && done*20/total != shown {
				shown = done * 20 / total
				fmt.Printf("\r  [%-20s] %3d%%  %d of %d MB", strings.Repeat("■", int(shown)), done*100/total, done>>20, total>>20)
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			f.Close()
			return rerr
		}
	}
	f.Close()
	fmt.Println()
	if rootfsSHA256 != "" && hex.EncodeToString(h.Sum(nil)) != rootfsSHA256 {
		os.Remove(dest + ".part")
		return fmt.Errorf("the download is damaged (its checksum is wrong): try again")
	}
	return os.Rename(dest+".part", dest)
}

// linuxName: the Windows user name, as a Linux one.
func linuxName() string {
	n := strings.ToLower(os.Getenv("USERNAME"))
	n = regexp.MustCompile(`[^a-z0-9_-]`).ReplaceAllString(n, "")
	if len(n) > 32 {
		n = n[:32]
	}
	if n == "" || !regexp.MustCompile(`^[a-z_]`).MatchString(n) || n == "root" {
		n = "user"
	}
	return n
}

// setUp imports the Kilobyte system into WSL and makes its user.
func setUp() error {
	if err := os.MkdirAll(home, 0o755); err != nil {
		return err
	}
	tarball := filepath.Join(home, "kilobyte-wsl.tar.gz")
	if _, err := os.Stat(tarball); err != nil {
		if err := download(tarball); err != nil {
			return err
		}
	}
	fmt.Println("Setting up Kilobyte (a minute or two)...")
	if out, err := output("wsl.exe", "--import", distro, filepath.Join(home, "wsl"), tarball); err != nil {
		// WSL is there, but a part of Windows it needs is still off.
		if regexp.MustCompile(`(?i)virtual machine platform|hyper-?v|HCS_E_|0x80370102|wsl --install|not enabled`).MatchString(out) {
			return turnOnWSL()
		}
		return fmt.Errorf("WSL could not set up the Kilobyte system: %v\n%s", err, strings.TrimSpace(out))
	}
	name := linuxName()
	script := fmt.Sprintf(`set -e
id %[1]s >/dev/null 2>&1 || useradd -m -s /bin/bash -c "%[1]s" -G sudo,users,audio,video,plugdev %[1]s 2>/dev/null ||
    useradd -m -s /bin/bash -G sudo,users %[1]s
grep -q '^\[user\]' /etc/wsl.conf || printf '\n[user]\ndefault=%[1]s\n' >> /etc/wsl.conf`, name)
	if err := run("wsl.exe", "-d", distro, "-u", "root", "--", "sh", "-c", script); err != nil {
		return fmt.Errorf("the user %s could not be made: %v", name, err)
	}
	run("wsl.exe", "--terminate", distro) // the default user counts from the next start
	os.Remove(tarball)
	fmt.Println("Kilobyte is set up for", name+".")
	return nil
}

// textSize: the size chosen with "kb size", in the Mac's points: 16 is the size
// Kilobyte has on a PC (each font pixel one screen pixel, 2 x 2 at 200 %).
func textSize() int {
	b, err := os.ReadFile(filepath.Join(home, "size"))
	if n, e := strconv.Atoi(strings.TrimSpace(string(b))); err == nil && e == nil && n > 0 {
		return n
	}
	return 16
}

// look: Kilobyte's pixel font and a Windows Terminal profile with its colours.
func look() {
	if _, err := os.Stat(fontFile); err != nil {
		os.MkdirAll(filepath.Dir(fontFile), 0o755)
		if os.WriteFile(fontFile, fontData, 0o644) == nil {
			exec.Command("reg.exe", "add", fontKey, "/v", "Kilobyte VGA (TrueType)", "/t", "REG_SZ", "/d", fontFile, "/f").Run()
		}
	}
	icon := filepath.Join(home, "kilobyte.ico")
	os.MkdirAll(home, 0o755)
	os.WriteFile(icon, iconData, 0o644)
	profile := fmt.Sprintf(`{
  "profiles": [
    {
      "name": "Kilobyte",
      "commandline": "wsl.exe -d Kilobyte -- /usr/bin/kilobyte",
      "icon": %q,
      "colorScheme": "Kilobyte CGA",
      "font": { "face": "Kilobyte VGA", "size": %s },
      "cursorShape": "underscore",
      "tabColor": "#0000AA",
      "closeOnExit": "always",
      "suppressApplicationTitle": false,
      "antialiasingMode": "aliased"
    }
  ],
  "schemes": [
    {
      "name": "Kilobyte CGA",
      "background": "#000000", "foreground": "#AAAAAA",
      "cursorColor": "#FFFFFF", "selectionBackground": "#AAAAAA",
      "black": "#000000", "red": "#AA0000", "green": "#00AA00", "yellow": "#AA5500",
      "blue": "#0000AA", "purple": "#AA00AA", "cyan": "#00AAAA", "white": "#AAAAAA",
      "brightBlack": "#555555", "brightRed": "#FF5555", "brightGreen": "#55FF55", "brightYellow": "#FFFF55",
      "brightBlue": "#5555FF", "brightPurple": "#FF55FF", "brightCyan": "#55FFFF", "brightWhite": "#FFFFFF"
    }
  ]
}
`, icon, strconv.FormatFloat(float64(textSize())*0.75, 'f', -1, 64))
	if old, _ := os.ReadFile(fragment); string(old) != profile {
		os.MkdirAll(filepath.Dir(fragment), 0o755)
		os.WriteFile(fragment, []byte(profile), 0o644)
	}
}

func open() error {
	if !wslReady() {
		return turnOnWSL()
	}
	if !haveDistro() {
		if err := setUp(); err != nil {
			return err
		}
	}
	look()
	// Windows Terminal with Kilobyte's profile (if it is not known yet, the
	// same command in the usual profile); else a console window.
	if wt, err := exec.LookPath("wt.exe"); err == nil {
		// Maximised: like Kilobyte on a PC, the whole screen.
		return exec.Command(wt, "--maximized", "-p", "Kilobyte", "wsl.exe", "-d", distro, "--", "/usr/bin/kilobyte").Start()
	}
	return exec.Command("cmd.exe", "/c", "start", "Kilobyte", "/max", "wsl.exe", "-d", distro, "--", "/usr/bin/kilobyte").Start()
}

func autolaunch(on bool) error {
	if !on {
		exec.Command("reg.exe", "delete", runKey, "/v", distro, "/f").Run()
		fmt.Println("Kilobyte no longer opens when you sign in.")
		return nil
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	if err := exec.Command("reg.exe", "add", runKey, "/v", distro, "/t", "REG_SZ", "/d", fmt.Sprintf(`"%s" open`, exe), "/f").Run(); err != nil {
		return fmt.Errorf("the start-up entry could not be made: %v", err)
	}
	fmt.Println("Kilobyte opens when you sign in to Windows. (kb autolaunch off undoes it.)")
	return nil
}

func remove() error {
	fmt.Println("This removes the Kilobyte system with everything in it (your Kilobyte documents too),")
	fmt.Println("its start-up entry, Windows Terminal profile and font.")
	if !ask("Remove Kilobyte?") {
		return nil
	}
	if haveDistro() {
		run("wsl.exe", "--unregister", distro)
	}
	exec.Command("reg.exe", "delete", runKey, "/v", distro, "/f").Run()
	exec.Command("reg.exe", "delete", fontKey, "/v", "Kilobyte VGA (TrueType)", "/f").Run()
	os.RemoveAll(filepath.Dir(fragment))
	os.Remove(fontFile)
	os.RemoveAll(home)
	fmt.Println("Kilobyte is removed. (winget uninstall Kilobyte.Transition removes kb itself.)")
	return nil
}
