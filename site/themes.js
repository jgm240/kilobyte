// The theme gallery: Kilobyte's own themes (themes/builtin.json), the ones
// people made (themes/gallery.json on the gh-pages branch, added by
// .github/workflows/theme-gallery.yml), and ?add=CODE: a theme on its way in.
// A theme travels as a short code; py/themes.py has its description.
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var GALLERY = "https://raw.githubusercontent.com/jgm240/kilobyte/gh-pages/themes/gallery.json";
  var ISSUE = "https://github.com/jgm240/kilobyte/issues/new";
  var BASE = ["BLACK", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN", "WHITE"];
  var ROLES = ["screen", "dialog", "title", "border", "border2", "item", "sel", "tag", "sel_tag", "key", "sel_key",
               "btn_on", "btn_off", "btn_key_on", "btn_key_off", "input", "arrow", "status", "gauge"];
  var MC = ["default", "dark", "darkfar", "double-lines", "gotar", "mc46", "nicedark"];
  var CGA = "000000 aa0000 00aa00 aa5500 0000aa aa00aa 00aaaa aaaaaa 555555 ff5555 55ff55 ffff55 5555ff ff55ff 55ffff ffffff".split(" ");

  function decode(code) {
    if (!/^[A-Za-z0-9_-]{20,200}$/.test(code || "")) return null;
    var bin;
    try { bin = atob(code.replace(/-/g, "+").replace(/_/g, "/")); } catch (e) { return null; }
    var b = [];
    for (var i = 0; i < bin.length; i++) b.push(bin.charCodeAt(i));
    if (b.length < 3 + ROLES.length || b[0] !== 1 || b[2] >= MC.length) return null;
    var t = { shadow: b[1] & 1 ? "ON" : "OFF", mc: MC[b[2]], roles: {}, palette: null };
    var p = 3;
    for (var r = 0; r < ROLES.length; r++, p++) {
      var fg = b[p] >> 3, bg = b[p] & 7;
      if (fg > 15) return null;
      t.roles[ROLES[r]] = [fg, bg];
    }
    if (b[1] & 2) {
      if (b.length < p + 48) return null;
      t.palette = [];
      for (var j = 0; j < 16; j++, p += 3) t.palette.push(hex(b[p]) + hex(b[p + 1]) + hex(b[p + 2]));
    }
    var name = "";
    try { name = decodeURIComponent(escape(String.fromCharCode.apply(null, b.slice(p)))); } catch (e) { name = ""; }
    t.name = name.replace(/[^\w .,'()&+-]/g, "").slice(0, 40).trim() || "Gallery theme";
    return t;
  }
  function hex(n) { return (n < 16 ? "0" : "") + n.toString(16); }

  // The theme as theme.conf / .kbtheme text (what Theme editor > Import reads).
  function kbtheme(t) {
    var out = ["# Kilobyte theme (Settings > Colour theme > Theme editor)", "name=" + t.name, "mc=" + t.mc, "shadow=" + t.shadow];
    if (t.palette) out.push("palette=" + t.palette.join(" "));
    ROLES.forEach(function (r) {
      var c = t.roles[r];
      out.push(r + "=" + BASE[c[0] & 7] + "," + BASE[c[1]] + "," + (c[0] >= 8 ? "ON" : "OFF"));
    });
    return out.join("\n") + "\n";
  }

  // A small Kilobyte screen in the theme's colours: the Program Manager.
  function preview(t) {
    var pal = t.palette || CGA;
    var col = function (i) { return "#" + pal[i]; };
    var span = function (role, text, fgOnly) {
      var c = t.roles[role];
      return '<span style="color:' + col(c[0]) + (fgOnly ? "" : ";background:" + col(c[1])) + '">' + esc(text) + "</span>";
    };
    var IW = 28, line = function (s, n) { return s + new Array(Math.max(0, n - s.length) + 1).join(" "); };
    var rows = [];
    var desk = function (s) { return span("screen", s); };
    // A row of the box: its pieces ([role, text]...), padded to the box's width.
    var boxrow = function (pieces) {
      var n = 0, html = "";
      pieces.forEach(function (p) { html += span(p[0], p[1]); n += p[1].length; });
      return desk(" ") + span("border", "│") + html + span("dialog", line("", IW - n)) + span("border2", "│") + desk(t.shadow === "ON" ? "▒" : " ") + desk(" ");
    };
    rows.push(desk(line(" ■ Kilobyte 1.5 │ anna@pc", IW + 4)));
    rows.push(desk(line("", IW + 4)));
    rows.push(desk(" ") + span("border", "┌──────") + span("title", " Program Manager ") + span("border2", "─────┐") + desk("  "));
    var item = function (key, rest, desc, sel) {
      return boxrow(sel ? [["dialog", " "], ["sel_key", key], ["sel", rest], ["sel_tag", desc]]
                        : [["dialog", " "], ["key", key], ["item", rest], ["tag", desc]]);
    };
    rows.push(item("E", "ditor     ", "Text editor  ", true));
    rows.push(item("W", "eb        ", "Web browser  ", false));
    rows.push(item("G", "ames      ", "Games  »     ", false));
    rows.push(boxrow([["dialog", "  "], ["btn_key_on", "<"], ["btn_on", " Run "], ["btn_key_on", ">"], ["dialog", "   "],
                      ["btn_off", "<"], ["btn_key_off", "E"], ["btn_off", "xit>"]]));
    rows.push(desk(" ") + span("border2", "└" + new Array(IW + 1).join("─") + "┘") + desk(t.shadow === "ON" ? "▒ " : "  "));
    rows.push(desk(" ") + desk(t.shadow === "ON" ? " " + new Array(IW + 2).join("▒") + " " : line("", IW + 3)));
    rows.push(span("status", line(" Text files and documents", IW + 4)));
    return '<pre class="themepreview" aria-label="' + esc(t.name) + '">' + rows.join("\n") + "</pre>";
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function download(t, a) {
    var blob = new Blob([kbtheme(t)], { type: "text/plain" });
    a.href = URL.createObjectURL(blob);
    a.download = t.name.replace(/[^\w .-]/g, "") + ".kbtheme";
  }

  function card(entry) {
    var t = decode(entry.code);
    if (!t) return null;
    var div = document.createElement("div");
    div.className = "themecard";
    div.innerHTML = preview(t) + '<p><b>' + esc(t.name) + "</b>" + (entry.by ? " <span class=\"dim\">by " + esc(String(entry.by).slice(0, 30)) + "</span>" : "") +
      ' · <a href="#" data-help="The theme as a file: Theme editor › Import adds it">Download</a></p>';
    var a = div.querySelector("a");
    if (entry.file) { a.href = "themes/" + entry.file; a.download = ""; } else { download(t, a); }
    return div;
  }

  function fill(id, list) {
    var box = $(id);
    list.forEach(function (e) { var c = card(e); if (c) box.appendChild(c); });
    return box.children.length;
  }

  fetch("themes/builtin.json").then(function (r) { return r.json(); }).then(function (l) { fill("builtin", l); }).catch(function () {});
  fetch(GALLERY, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
    .then(function (l) {
      var n = fill("gallery", Array.isArray(l) ? l.slice().reverse() : []);
      $("gallery-note").textContent = n ? n + " theme" + (n === 1 ? "" : "s") + ", newest first." : "None yet: be the first (see Add yours below).";
    })
    .catch(function () { $("gallery-note").textContent = "None yet: be the first (see Add yours below)."; });

  // ?add=CODE&by=NAME: a theme someone uploads from Kilobyte.
  var q = new URLSearchParams(location.search), code = q.get("add");
  if (code) {
    var t = decode(code), by = (q.get("by") || "").replace(/[^\w .-]/g, "").slice(0, 30);
    $("incoming").hidden = false;
    if (!t) {
      $("incoming-card").innerHTML = "<p class=\"warn\">This link has no theme in it that could be read (is it cut off?).</p>";
      $("submit").hidden = $("incoming-dl").hidden = true;
    } else {
      $("incoming-card").innerHTML = preview(t) + "<p><b>" + esc(t.name) + "</b>" + (by ? " by " + esc(by) : "") + "</p>";
      var body = "A theme for the gallery, from Kilobyte's theme gallery page.\n\nkbtheme: " + code + "\nby: " + by +
                 "\n\n(It is published when a maintainer adds the label theme-approved.)";
      $("submit").href = ISSUE + "?title=" + encodeURIComponent("Theme: " + t.name) + "&body=" + encodeURIComponent(body);
      download(t, $("incoming-dl"));
      $("incoming").scrollIntoView();
    }
  }
})();
