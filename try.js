// Try it: Kilobyte's CD version in v86, a PC emulated in the browser.
// try/disk/manifest.json (made by tools/make-web-vm.sh) names the CD image,
// cut into compressed 1 MB pieces that load as the system reads them, and the
// saved state of a PC that has started Kilobyte already (so it opens at once).
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var emulator = null;

  // The on-screen keys, as PC keyboard scan codes (set 1): press, release.
  var KEYS = {
    esc: [0x01, 0x81], tab: [0x0f, 0x8f], enter: [0x1c, 0x9c], f10: [0x44, 0xc4],
    up: [0xe0, 0x48, 0xe0, 0xc8], down: [0xe0, 0x50, 0xe0, 0xd0],
    left: [0xe0, 0x4b, 0xe0, 0xcb], right: [0xe0, 0x4d, 0xe0, 0xcd],
    ctrlc: [0x1d, 0x2e, 0xae, 0x9d]
  };
  function press(name) {
    if (emulator) emulator.keyboard_send_scancodes(KEYS[name]);
    $("screen").focus();
  }

  function say(text) { $("msg").hidden = !text; $("msg").textContent = text || ""; }

  function start(m) {
    $("start-row").hidden = true;
    $("bar").hidden = false;
    say("Downloading the virtual PC...");
    var base = "try/disk/";
    var options = {
      wasm_path: "try/v86/v86.wasm",
      memory_size: m.memory,
      vga_memory_size: 8 * 1024 * 1024,
      screen: { container: $("screen"), use_graphical_text: true },
      bios: { url: "try/v86/seabios.bin" },
      vga_bios: { url: "try/v86/vgabios.bin" },
      cdrom: { url: base + m.iso, size: m.size, async: true, fixed_chunk_size: m.chunk, use_parts: true },
      autostart: true
    };
    if (m.state) options.initial_state = { url: base + m.state };
    emulator = new V86(options);
    emulator.add_listener("download-progress", function (e) {
      if (e.lengthComputable && e.total) {
        $("bar").firstElementChild.style.width = Math.round(100 * e.loaded / e.total) + "%";
        say("Downloading the virtual PC... " + Math.round(e.loaded / 1e6) + " of " + Math.round(e.total / 1e6) + " MB");
      }
    });
    emulator.add_listener("emulator-ready", function () {
      var st = document.querySelector(".status");
      if (st) st.textContent = "Kilobyte runs below: click the screen, then type. Arrow keys and first letters choose, Enter runs, Esc goes back.";
      $("bar").hidden = true;
      say(m.state ? "" : "Starting Kilobyte (a minute or two)...");
      $("keys").hidden = false;
      $("screen").focus();
    });
    emulator.add_listener("screen-set-size", function () { if (!m.state) say(""); });
  }

  $("start").addEventListener("click", function () {
    if (typeof V86 === "undefined") { say("The emulator could not be loaded."); return; }
    fetch("try/disk/manifest.json")
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(start)
      .catch(function () { say("The virtual PC is not ready yet. Come back soon, or download Kilobyte meanwhile."); });
  });
  document.querySelectorAll("[data-key]").forEach(function (b) {
    b.addEventListener("click", function () { press(b.getAttribute("data-key")); });
  });
  $("typing").addEventListener("submit", function (e) {
    e.preventDefault();
    if (emulator && $("text").value) { emulator.keyboard_send_text($("text").value); $("text").value = ""; }
    $("screen").focus();
  });
  $("full").addEventListener("click", function () {
    var s = $("screen");
    (s.requestFullscreen || s.webkitRequestFullscreen || function () {}).call(s);
    s.focus();
  });
})();
