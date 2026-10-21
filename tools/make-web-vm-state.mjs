// Start Kilobyte's CD version in v86 (in Node) and save the PC's state once
// the Program Manager shows, for the website's "Try it" page.
//   node make-web-vm-state.mjs ISO V86-DIR STATE-FILE      (MEMORY_MB: memory)
import fs from "node:fs";
import { V86 } from "v86";

const [iso, dir, out] = process.argv.slice(2);
const memory = (+process.env.MEMORY_MB || 256) * 1024 * 1024;
const COLS = 80, ROWS = 25;
const screen = Array.from({ length: ROWS }, () => new Array(COLS).fill(" "));
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

// The text screen, from the characters the VGA card is given.
emulator.add_listener("screen-put-char", ([row, col, chr]) => {
    if (row < ROWS && col < COLS) screen[row][col] = chr >= 32 && chr < 127 ? String.fromCharCode(chr) : " ";
});
const text = () => screen.map(r => r.join("")).join("\n");

let last = "";
const timer = setInterval(async () => {
    const t = text();
    if (t !== last && seconds() % 30 < 5) {
        console.log(`--- ${seconds()} s`);
        console.log(t.split("\n").filter(l => l.trim()).slice(-4).join("\n"));
        last = t;
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
