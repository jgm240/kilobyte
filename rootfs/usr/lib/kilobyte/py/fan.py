#!/usr/bin/python3
"""Fan Control: the temperatures and fans of this computer, and how the fans
run: automatically (the computer's own way), quiet, normal or cool (by
temperature, Kilobyte's way), at full speed or at a fixed speed.

    fan.py ui              the program (Accessories > Fan control)
    fan.py status          what there is, as text
    fan.py mode            the mode set: auto, quiet, normal, cool, full or 10-100
    fan.py set MODE        (root) set the mode: /etc/kilobyte/fan.conf, and
                           kilobyte-fan.service runs it
    fan.py run             (root, kilobyte-fan.service) keep the fans as the
                           mode says; back to automatic when it stops

Fans it can set: a PC's fan chips (hwmon pwm: most desktop boards, Dell and
ThinkPad laptops), Apple's SMC (Intel Macs: from their lowest to their
highest speed), and fans the kernel runs by temperature (thermal cooling
devices: the Raspberry Pi 5's fan, a fan on a Pi's GPIO pin). Above 85 °C
every fan runs at full speed, whatever the mode.
"""
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time

CONF = "/etc/kilobyte/fan.conf"
SAVED = "/run/kilobyte-fan.json"               # how the fans were before Kilobyte set them
HOT = 85                                       # °C: full speed above this, in every mode
PROFILES = {                                   # (°C, % of full speed) points, in between straight lines
    "quiet": [(50, 20), (65, 40), (80, 100)],
    "normal": [(45, 30), (60, 55), (75, 100)],
    "cool": [(40, 50), (55, 75), (68, 100)],
}
NAMES = {"auto": "Automatic", "quiet": "Quiet", "normal": "Normal", "cool": "Cool", "full": "Full speed"}


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def write(path, value):
    with open(path, "w") as f:
        f.write(str(value))


def number(path):
    v = read(path)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --- temperatures ------------------------------------------------------------
CPU_LABELS = re.compile(r"^(Package id \d+|Tctl|Tdie|Tccd\d+|CPU|Core 0|TC0P|TC0D|TC0H)$", re.I)


def temperatures():
    """[(name, °C, is the processor)], hottest first."""
    found, seen = [], set()
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        chip = read(hw + "/name", "?")
        for t in sorted(glob.glob(hw + "/temp*_input")):
            v = number(t)
            if v is None or v <= 0 or v > 150000:
                continue
            label = read(t.replace("_input", "_label")) or "%s %s" % (chip, os.path.basename(t)[4:-6])
            cpu = bool(CPU_LABELS.match(label)) or chip in ("k10temp", "cpu_thermal", "coretemp") and "Core" not in label
            key = (chip, label)
            if key not in seen:
                seen.add(key)
                found.append(("%s (%s)" % (label, chip), v / 1000, cpu))
    if not found:
        for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            v = number(z + "/temp")
            kind = read(z + "/type", "?")
            if v is not None and 0 < v < 150000:
                found.append((kind, v / 1000, kind in ("x86_pkg_temp", "cpu-thermal", "cpu_thermal", "soc_thermal")))
    found.sort(key=lambda t: -t[1])
    return found


def main_temperature(temps=None):
    """The processor's temperature (the hottest reading if none says it is
    the processor's), or None."""
    temps = temperatures() if temps is None else temps
    cpu = [t for _, t, is_cpu in temps if is_cpu]
    if cpu:
        return max(cpu)
    plausible = [t for _, t, _ in temps if t < 120]
    return max(plausible) if plausible else None


# --- fans --------------------------------------------------------------------
class Fan:
    """One fan: its name, its speed (rpm, or None) and, if it can be set,
    how: set(percent) and auto()."""
    kind = "none"

    def __init__(self, name, rpm_path=None):
        self.name, self.rpm_path = name, rpm_path

    def rpm(self):
        return number(self.rpm_path) if self.rpm_path else None

    def key(self):
        return self.name

    def settable(self):
        return False

    def percent(self):
        return None


class PwmFan(Fan):
    """A fan chip's pwm (0-255); pwmN_enable 1 is "set by hand"."""
    kind = "pwm"

    def __init__(self, name, rpm_path, pwm):
        super().__init__(name, rpm_path)
        self.pwm = pwm

    def key(self):
        return self.pwm

    def settable(self):
        return os.path.exists(self.pwm + "_enable") or os.path.exists(self.pwm)

    def percent(self):
        v = number(self.pwm)
        return None if v is None else round(v * 100 / 255)

    def save(self):
        return {"enable": read(self.pwm + "_enable")}

    def set(self, pct):
        if os.path.exists(self.pwm + "_enable") and read(self.pwm + "_enable") != "1":
            write(self.pwm + "_enable", 1)
        write(self.pwm, round(pct * 255 / 100))

    def auto(self, saved):
        enable = (saved or {}).get("enable") or "2"
        if os.path.exists(self.pwm + "_enable"):
            try:
                write(self.pwm + "_enable", enable if enable != "1" else "2")
            except OSError:
                write(self.pwm, 255)           # (no automatic mode: at least not slow)


class SmcFan(Fan):
    """An Intel Mac's fan (applesmc): fanN_manual 1, and fanN_output in rpm
    between fanN_min and fanN_max."""
    kind = "smc"

    def __init__(self, name, base):
        super().__init__(name, base + "_input")
        self.base = base

    def key(self):
        return self.base

    def settable(self):
        return os.path.exists(self.base + "_manual")

    def range(self):
        lo, hi = number(self.base + "_min") or 1000, number(self.base + "_max") or 6000
        return lo, max(hi, lo + 1)

    def percent(self):
        lo, hi = self.range()
        v = number(self.base + "_output") if read(self.base + "_manual") == "1" else self.rpm()
        return None if v is None else max(0, min(100, round((v - lo) * 100 / (hi - lo))))

    def save(self):
        return {}

    def set(self, pct):
        lo, hi = self.range()
        write(self.base + "_manual", 1)
        write(self.base + "_output", round(lo + (hi - lo) * pct / 100))

    def auto(self, saved):
        write(self.base + "_manual", 0)


class CoolingFan(Fan):
    """A fan the kernel runs by temperature (a thermal cooling device): set
    by hand, its thermal zones' governor is user_space while Kilobyte runs it."""
    kind = "cooling"

    def __init__(self, name, dev, rpm_path=None):
        super().__init__(name, rpm_path)
        self.dev = dev

    def key(self):
        return self.dev

    def zones(self):
        out = []
        for z in glob.glob("/sys/class/thermal/thermal_zone*"):
            for cdev in glob.glob(z + "/cdev*"):
                if os.path.basename(os.path.realpath(cdev)) == os.path.basename(self.dev):
                    out.append(z)
        return sorted(set(out))

    def settable(self):
        return os.path.exists(self.dev + "/cur_state") and (number(self.dev + "/max_state") or 0) > 0

    def percent(self):
        cur, top = number(self.dev + "/cur_state"), number(self.dev + "/max_state")
        return None if cur is None or not top else round(cur * 100 / top)

    def save(self):
        return {"policies": {z: read(z + "/policy") for z in self.zones()}}

    def set(self, pct):
        for z in self.zones():
            if read(z + "/policy") != "user_space" and "user_space" in (read(z + "/available_policies") or ""):
                write(z + "/policy", "user_space")
        top = number(self.dev + "/max_state") or 1
        write(self.dev + "/cur_state", round(pct * top / 100))

    def auto(self, saved):
        for z, policy in ((saved or {}).get("policies") or {}).items():
            if policy and policy != "user_space":
                try:
                    write(z + "/policy", policy)
                except OSError:
                    pass


def fans():
    found, rpm_taken = [], set()
    cooling_names = ("pwm-fan", "gpio-fan", "Fan", "fan")
    for dev in sorted(glob.glob("/sys/class/thermal/cooling_device*")):
        kind = read(dev + "/type", "")
        if kind in cooling_names:
            # Its speed, if its hwmon tells it (the Pi 5's pwmfan).
            rpm = next(iter(sorted(glob.glob(dev + "/device/hwmon/hwmon*/fan1_input"))), None)
            if rpm:
                rpm_taken.add(os.path.realpath(rpm))
            name = {"pwm-fan": "Fan", "gpio-fan": "Fan on a GPIO pin"}.get(kind, "Fan (ACPI)")
            found.append(CoolingFan(name, dev, rpm))
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        chip = read(hw + "/name", "?")
        if chip == "pwmfan":
            continue                           # (as a cooling device, above)
        for f in sorted(glob.glob(hw + "/fan*_input"), key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
            if os.path.realpath(f) in rpm_taken:
                continue
            n = re.sub(r"\D", "", os.path.basename(f))
            label = read(hw + "/fan%s_label" % n) or "Fan %s" % n
            name = "%s (%s)" % (label, chip)
            if chip == "applesmc":
                found.append(SmcFan(name, hw + "/fan" + n))
            elif os.path.exists(hw + "/pwm" + n):
                found.append(PwmFan(name, f, hw + "/pwm" + n))
            else:
                found.append(Fan(name, f))
        if chip != "applesmc":
            # Fan chips that can set a fan but not tell its speed.
            for p in sorted(glob.glob(hw + "/pwm[0-9]")):
                if not os.path.exists(hw + "/fan%s_input" % p[-1]):
                    found.append(PwmFan("Fan %s (%s)" % (p[-1], chip), None, p))
    return found


def thinkpad_locked():
    """A ThinkPad whose driver does not let the fan be set (fan_control=0)."""
    return any(read(h + "/name") == "thinkpad" and not os.path.exists(h + "/pwm1")
               for h in glob.glob("/sys/class/hwmon/hwmon*"))


def is_pi():
    return "raspberry pi" in (read("/proc/device-tree/model", "") or "").lower()


# --- the mode ----------------------------------------------------------------
def mode():
    m = "auto"
    for line in (read(CONF, "") or "").splitlines():
        if line.startswith("mode="):
            m = line[5:].strip()
    return m if valid(m) else "auto"


def valid(m):
    return m in NAMES or m in PROFILES or (m.isdigit() and 10 <= int(m) <= 100)


def mode_name(m):
    return NAMES.get(m) or ("%s%% of full speed" % m if m.isdigit() else m)


def wanted(m, temp):
    """How fast (%) the fans should run in mode m at temp °C."""
    if temp is not None and temp >= HOT:
        return 100
    if m == "full":
        return 100
    if m.isdigit():
        return int(m)
    points = PROFILES.get(m)
    if not points:
        return None
    if temp is None:
        return 60
    if temp <= points[0][0]:
        return points[0][1]
    for (t0, p0), (t1, p1) in zip(points, points[1:]):
        if temp <= t1:
            return round(p0 + (p1 - p0) * (temp - t0) / (t1 - t0))
    return 100


def saved():
    try:
        with open(SAVED) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def to_auto():
    """Every fan back as the computer runs it."""
    s = saved()
    for f in fans():
        if f.settable():
            try:
                f.auto(s.get(f.key()))
            except OSError:
                pass
    try:
        os.unlink(SAVED)
    except OSError:
        pass


def run():
    """kilobyte-fan.service: every two seconds, the fans as the mode says."""
    m = mode()
    if m == "auto":
        to_auto()
        return 0
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    signal.signal(signal.SIGINT, lambda *a: stop.append(1))
    controlled = [f for f in fans() if f.settable()]
    if not controlled:
        print("fan: no fan here can be set", file=sys.stderr)
        return 0
    s = saved()
    for f in controlled:
        s.setdefault(f.key(), f.save())
    with open(SAVED, "w") as fh:
        json.dump(s, fh)
    last = None
    try:
        while not stop:
            pct = wanted(m, main_temperature())
            # (Small changes wait: a fan that changes its speed all the time is louder.)
            if pct is not None and (last is None or abs(pct - last) >= 3 or pct == 100 and last != 100):
                for f in controlled:
                    try:
                        f.set(pct)
                    except OSError as e:
                        print("fan: %s: %s" % (f.name, e), file=sys.stderr)
                last = pct
            for _ in range(20):
                if stop:
                    break
                time.sleep(0.1)
    finally:
        to_auto()
    return 0


def systemctl(*args):
    try:
        return subprocess.run(["systemctl"] + list(args), capture_output=True).returncode
    except OSError:
        return 1


def set_mode(m):
    if not valid(m):
        print("fan: auto, quiet, normal, cool, full or 10-100", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    write(CONF, "# Fan Control (Accessories > Fan control, kbutils settings chg fan MODE)\nmode=%s\n" % m)
    mac_fans = systemctl("cat", "mbpfan.service") == 0
    if m == "auto":
        systemctl("stop", "kilobyte-fan.service")
        to_auto()
        if mac_fans:                           # (the Mac version's own fan helper takes over again)
            systemctl("enable", "--now", "mbpfan.service")
    else:
        if mac_fans:
            systemctl("disable", "--now", "mbpfan.service")
        systemctl("enable", "kilobyte-fan.service")
        systemctl("restart", "kilobyte-fan.service")
    return 0


def status():
    temps = temperatures()
    print("Mode: %s" % mode_name(mode()))
    for name, t, cpu in temps:
        print("  %-40s %5.1f °C%s" % (name[:40], t, "  (processor)" if cpu else ""))
    fs = fans()
    for f in fs:
        rpm, pct = f.rpm(), f.percent()
        print("  %-40s %s%s%s" % (f.name[:40], "%d rpm" % rpm if rpm is not None else "-",
                                   "  %d%%" % pct if pct is not None else "", "" if f.settable() else "  (cannot be set)"))
    if not fs:
        print("  No fans found.")


# --- the program -------------------------------------------------------------
def ui():
    import curses
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kbui
    from kbui import BLACK, BLUE, CYAN, DARKGREY, LIGHTGREEN, LIGHTGREY, LIGHTRED, WHITE, YELLOW

    buttons = [("A", "auto", "Automatic"), ("Q", "quiet", "Quiet"), ("N", "normal", "Normal"),
               ("C", "cool", "Cool"), ("F", "full", "Full")]

    def bar(pct, w):
        n = max(0, min(w, round(pct * w / 100)))
        return "█" * n + "░" * (w - n)

    def apply(m):
        r = subprocess.run(["sudo", "-n", "/usr/lib/kilobyte/kb-root", "fan", m], capture_output=True, text=True)
        return None if r.returncode == 0 else (r.stderr.strip().splitlines() or ["not allowed"])[-1]

    def main(s):
        s.scr.timeout(1000)
        message, hits = "", []
        while True:
            h, w = s.size()
            s.fill(LIGHTGREY, BLUE)
            s.put(0, 0, " Fan Control".ljust(w), BLACK, CYAN)
            temps, fs, m = temperatures(), fans(), mode()
            y = 2
            s.put(y, 2, "Temperatures", YELLOW, BLUE)
            y += 1
            main_t = main_temperature(temps)
            for name, t, cpu in temps[: max(1, (h - 14) // 2)]:
                colour = LIGHTRED if t >= 80 else YELLOW if t >= 65 else LIGHTGREEN
                s.put(y, 4, name[: w - 30].ljust(w - 30), WHITE if cpu else LIGHTGREY, BLUE)
                s.put(y, w - 25, "%5.1f °C " % t, colour, BLUE)
                s.put(y, w - 15, bar(min(100, t), 12), colour, BLUE)
                y += 1
            if not temps:
                s.put(y, 4, "No thermometer found.", LIGHTGREY, BLUE)
                y += 1
            y += 1
            s.put(y, 2, "Fans", YELLOW, BLUE)
            y += 1
            for f in fs[: max(1, h - y - 7)]:
                rpm, pct = f.rpm(), f.percent()
                s.put(y, 4, f.name[: w - 30].ljust(w - 30), WHITE, BLUE)
                s.put(y, w - 25, ("%d rpm" % rpm if rpm is not None else "").rjust(9), LIGHTGREY, BLUE)
                if pct is not None:
                    s.put(y, w - 15, bar(pct, 12), CYAN, BLUE)
                elif not f.settable():
                    s.put(y, w - 15, "(not settable)", DARKGREY, BLUE)
                y += 1
            settable = [f for f in fs if f.settable()]
            if not settable:
                why = "No fan here that Kilobyte can set: the computer runs them itself."
                if not fs:
                    why = "No fans found (passive cooling, or the firmware hides them)."
                s.put(y, 4, why[: w - 6], LIGHTGREY, BLUE)
                y += 1
                if thinkpad_locked():
                    s.put(y, 4, "T: let Kilobyte set this ThinkPad's fan (after a restart)"[: w - 6], YELLOW, BLUE)
                    y += 1
                if is_pi() and not fs:
                    s.put(y, 4, "G: a fan on a GPIO pin (with a transistor), on above a temperature"[: w - 6], YELLOW, BLUE)
                    y += 1
            # The modes, as buttons.
            y = h - 5
            text = "Mode: %s" % mode_name(m)
            if m in PROFILES and main_t is not None:
                text += "  (now %d%% at %.0f °C)" % (wanted(m, main_t), main_t)
            s.put(y, 2, text[: w - 4], WHITE, BLUE)
            x, hits = 2, []
            for key, mm, label in buttons:
                on = m == mm
                t = " %s %s " % (key, label)
                s.put(y + 2, x, t, BLACK if on else WHITE, CYAN if on else DARKGREY)
                hits.append((x, x + len(t), mm))
                x += len(t) + 1
            t = " 1-9 %s " % ("%s%%" % m if m.isdigit() else "fixed")
            s.put(y + 2, x, t, BLACK if m.isdigit() else WHITE, CYAN if m.isdigit() else DARKGREY)
            s.put(h - 1, 0, (" " + (message or "A Q N C F or 1-9 (10%-90%) choose   Esc closes   Above 85 °C the fans run at full speed"))[: w - 1].ljust(w - 1),
                  BLACK, CYAN)
            s.scr.refresh()
            try:
                k = s.scr.get_wch()
            except curses.error:
                continue
            new = None
            if k in ("\x1b", curses.KEY_F10, "x", "X"):
                return
            if k == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, b = curses.getmouse()
                except curses.error:
                    continue
                if my == h - 3 and b & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):
                    new = next((mm for a, z, mm in hits if a <= mx < z), None)
            elif isinstance(k, str):
                c = k.upper()
                new = next((mm for key, mm, _ in buttons if key == c), None)
                if c.isdigit() and c != "0":
                    new = str(int(c) * 10)
                if c == "T" and thinkpad_locked():
                    err = apply("thinkpad")
                    message = err or "Done: after a restart Kilobyte can set this ThinkPad's fan."
                if c == "G" and is_pi():
                    curses.endwin()
                    subprocess.call(["/usr/lib/kilobyte/apps/fans", "--gpio"])
                    s.scr.clear()
            if new and new != m:
                if not settable and new != "auto":
                    message = "There is no fan here that Kilobyte can set."
                else:
                    err = apply(new)
                    message = ("Could not set it: " + err) if err else "Mode: " + mode_name(new)

    kbui.run(main)


def main(argv):
    what = argv[0] if argv else ""
    if what == "ui":
        ui()
    elif what == "status":
        status()
    elif what == "mode":
        print(mode())
    elif what == "set" and len(argv) == 2:
        return set_mode(argv[1])
    elif what == "run":
        return run()
    else:
        sys.exit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
