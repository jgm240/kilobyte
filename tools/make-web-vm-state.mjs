// Start Kilobyte's CD version in v86 (in Node) and save the PC's state once
// the Program Manager shows, for the website's "Try it" page.
//   node make-web-vm-state.mjs ISO V86-DIR STATE-FILE      (MEMORY_MB: memory)
import fs from "node:fs";
import { V86 } from "v86";

const [iso, dir, out] = process.argv.slice(2);
const memory = (+process.env.MEMORY_MB || 256) * 1024 * 1024;
const started = Date.now();
const seconds = () => Math.round((Date.now() - started) / 1000);

const emulator = new V86({
    wasm_path: dir + "/v86.wasm",
    memory_size: memory,
    vga_memory_size: 8 * 1024 * 1024,
    bios: { url: dir + "/seabios.bin" },
    vga_bios: { url: dir + "/vgabios.bin" },
    // Read as it is used, like the browser does: a CD loaded whole would
    // end up in the saved state.
    cdrom: { url: iso, async: true, size: fs.statSync(iso).size },
    // RESUME=state.bin: carry on from a saved state (skips the long start).
    ...(process.env.RESUME ? { initial_state: { url: process.env.RESUME } } : {}),
    autostart: true,
});

// The text on the screen, read from the VGA card's memory the way v86 draws
// it (from the start address, which Linux moves to scroll).
function text() {
    const vga = emulator.v86.cpu.devices.vga;
    if (vga.graphical_mode) return "(graphics mode)";
    const cols = vga.max_cols, rows = vga.max_rows;
    const rowOffset = Math.max(0, (vga.offset_register * 2 - cols) * 2);
    let addr = vga.start_address << 1;
    const lines = [];
    for (let r = 0; r < rows; r++) {
        let line = "";
        for (let c = 0; c < cols; c++, addr += 2) {
            const ch = vga.vga_memory[addr];
            line += ch >= 32 && ch < 127 ? String.fromCharCode(ch) : ch >= 128 ? "#" : " ";
        }
        lines.push(line.trimEnd());
        addr += rowOffset;
    }
    return lines.join("\n");
}

// The boot menu (GRUB, in a graphics mode) takes "Kilobyte (safe graphics)",
// the fourth entry: nomodeset keeps the console in VGA text mode, which v86
// draws far faster than a graphics console (Debian would load the driver
// for v86's Bochs graphics card otherwise). Its kernel line gets
// init_on_free=1 too: freed memory is zeroed, so the saved state packs small.
let menuDone = !!process.env.RESUME;          // resumed: past the menu already
const KEY = { down: [0xe0, 0x50, 0xe0, 0xd0], e: [0x12, 0x92], end: [0xe0, 0x4f, 0xe0, 0xcf],
              ctrlx: [0x1d, 0x2d, 0xad, 0x9d], enter: [0x1c, 0x9c], home: [0xe0, 0x47, 0xe0, 0xc7] };
const wait = ms => new Promise(r => setTimeout(r, ms));
async function keys(...names) {
    for (const k of names) { emulator.keyboard_send_scancodes(KEY[k]); await wait(300); }
}
async function bootMenu() {
    if (menuDone || seconds() > 120 || !emulator.v86.cpu.devices.vga.graphical_mode) return;
    menuDone = true;
    console.log(`boot menu at ${seconds()} s: "safe graphics" with init_on_free=1`);
    await wait(1500);
    await keys("down", "down", "down", "e");            // edit the fourth entry
    await wait(1500);
    await keys("end");                                   // the end of its first line: linux ...
    emulator.keyboard_send_text(" init_on_free=1");
    await wait(1500);
    await keys("ctrlx");                                 // start it
}
setInterval(() => { try { bootMenu(); } catch (e) { /* not started yet */ } }, 250);

// Before the state is saved: Kilobyte's Terminal empties the file cache (the
// pages it frees are zeroed), then the Program Manager is back as it was.
async function emptyCaches() {
    emulator.keyboard_send_text("t");                    // the Terminal item
    await keys("enter");
    await wait(8000);
    // Empty the file cache, then have Python touch every free page (the
    // kernel hands them over zeroed) and give them back: free memory is
    // then all zeros, which the compressed state hardly notices.
    emulator.keyboard_send_text(" sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'; " +
        "python3 -c \"a=[int(l.split()[1]) for l in open('/proc/meminfo') if l.startswith('MemAvailable')][0]*1024-50331648; " +
        "b=bytearray(max(a, 0)); b[::4096]=bytes(len(range(0, len(b), 4096)))\"; " +
        "sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'; exit\n");
    await wait(90000);
    await keys("home");                                  // the highlight back on Editor
    await wait(5000);
}

let lastShown = 0;
const timer = setInterval(async () => {
    const t = text();
    if (seconds() - lastShown >= 60) {             // the whole screen once a minute
        lastShown = seconds();
        console.log(`--- ${seconds()} s ` + "-".repeat(60) + "\n" + t.replace(/ +$/gm, ""));
    }
    if (t.includes("Program Manager") && t.includes("Choose with the arrow keys") && seconds() >= 15) {
        clearInterval(timer);
        console.log(`Program Manager after ${seconds()} s; letting it settle`);
        await wait(20000);
        await emptyCaches();
        console.log("caches emptied; the screen now:\n" + text());
        if (!text().includes("Program Manager")) console.log("(the Program Manager is not showing: check this state)");
        const state = await emulator.save_state();
        fs.writeFileSync(out, Buffer.from(state));
        console.log(`saved ${Math.round(state.byteLength / 1e6)} MB`);
        await emulator.destroy();
        process.exit(0);
    }
    if (seconds() > 1800) {
        console.error("Kilobyte did not show its Program Manager within 30 minutes:\n" + t);
        process.exit(1);
    }
}, 5000);
