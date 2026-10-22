// Kilobyte's website: the bottom status line, the theme list, copy buttons.
(function () {
  "use strict";

  // The status line says what the thing under the mouse (or keyboard) does,
  // like the bottom line of Kilobyte's menus.
  var status = document.querySelector(".status");
  var idle = status ? status.textContent : "";
  function hint(e) {
    var el = e.target.closest && e.target.closest("[data-help]");
    if (status) status.textContent = el ? el.getAttribute("data-help") : idle;
  }
  document.addEventListener("mouseover", hint);
  document.addEventListener("focusin", hint);

  // Themes: Kilobyte's colour themes, remembered in this browser only.
  var THEMES = [
    ["classic", "Classic Blue"], ["panels", "Blue Panels"], ["cyan", "Cyan Desk"],
    ["lightblue", "Light Blue (8-bit)"], ["orange", "Blue and Orange (16-bit)"],
    ["mono", "Black and White (1984)"], ["green", "Green Screen"], ["amber", "Amber Screen"],
    ["mustard", "Ketchup and Mustard"], ["eink", "E-ink"]
  ];
  function setTheme(id) {
    if (id === "classic") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", id);
    document.querySelectorAll(".themes button").forEach(function (b) {
      b.setAttribute("aria-pressed", b.value === id ? "true" : "false");
    });
  }
  var saved = "classic";
  try { saved = localStorage.getItem("kilobyte-theme") || "classic"; } catch (e) { /* private window */ }
  var list = document.querySelector(".themes");
  if (list) {
    THEMES.forEach(function (t) {
      var b = document.createElement("button");
      b.type = "button"; b.value = t[0]; b.textContent = t[1];
      b.setAttribute("data-help", "Show this site in Kilobyte's " + t[1] + " theme");
      b.addEventListener("click", function () {
        setTheme(t[0]);
        try { localStorage.setItem("kilobyte-theme", t[0]); } catch (e) { /* not kept */ }
      });
      list.appendChild(b);
    });
  }
  setTheme(saved);

  // Tabs (Transition: Linux, macOS, Windows): the visitor's own system first,
  // or the one named in the address (#macos).
  var tabs = document.querySelectorAll('[role="tab"]');
  if (tabs.length) {
    var pick = function (id, keepHash) {
      tabs.forEach(function (t) {
        var on = t.getAttribute("aria-controls") === id;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
      if (!keepHash) { try { history.replaceState(null, "", "#" + id); } catch (e) { /* not kept */ } }
    };
    tabs.forEach(function (t, n) {
      t.addEventListener("click", function () { pick(t.getAttribute("aria-controls")); });
      t.addEventListener("keydown", function (e) {
        var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!d) return;
        var next = tabs[(n + d + tabs.length) % tabs.length];
        next.focus(); pick(next.getAttribute("aria-controls"));
      });
    });
    var ua = navigator.userAgent, wanted = location.hash.slice(1);
    var guess = /Windows/i.test(ua) ? "windows" : /Macintosh|Mac OS X/i.test(ua) && !/iPhone|iPad/i.test(ua) ? "macos" : "linux";
    pick(document.getElementById(wanted) && document.querySelector('[aria-controls="' + wanted + '"]') ? wanted : guess, true);
  }

  // Copy buttons on commands.
  document.querySelectorAll("pre[data-copy]").forEach(function (pre) {
    var wrap = document.createElement("div");
    wrap.className = "copy";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    var b = document.createElement("button");
    b.type = "button"; b.textContent = "Copy";
    b.setAttribute("data-help", "Copy the command, then paste it into a terminal");
    b.addEventListener("click", function () {
      var text = pre.textContent.trim();
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
        .then(function () { b.textContent = "Copied"; })
        .catch(function () {
          var r = document.createRange(); r.selectNodeContents(pre);
          var s = getSelection(); s.removeAllRanges(); s.addRange(r);
          b.textContent = "Ctrl+C";
        });
      setTimeout(function () { b.textContent = "Copy"; }, 2000);
    });
    wrap.appendChild(b);
  });
})();
