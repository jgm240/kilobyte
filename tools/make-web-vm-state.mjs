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
// for v86's Bochs graphics card otherwise).
let menuDone = false;
function bootMenu() {
    if (menuDone || seconds() > 120 || !emulator.v86.cpu.devices.vga.graphical_mode) return;
    menuDone = true;
    console.log(`boot menu at ${seconds()} s: choosing "safe graphics"`);
    const down = [0xe0, 0x50, 0xe0, 0xd0];
    setTimeout(() => emulator.keyboard_send_scancodes([...down, ...down, ...down, 0x1c, 0x9c]), 1500);
}
setInterval(() => { try { bootMenu(); } catch (e) { /* not started yet */ } }, 250);

let lastShown = 0;
const timer = setInterval(async () => {
    const t = text();
    if (seconds() - lastShown >= 60) {             // the whole screen once a minute
        lastShown = seconds();
        console.log(`--- ${seconds()} s ` + "-".repeat(60) + "\n" + t.replace(/ +$/gm, ""));
    }
    if (t.includes("Program Manager") && t.includes("Choose with the arrow keys")) {
        clearInterval(timer);
        console.log(`Program Manager after ${seconds()} s; letting it settle`);
        await new Promise(r => setTimeout(r, 20000));
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
