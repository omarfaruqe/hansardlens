/* Light or dark theme. Without a choice the site follows the system setting; the header
   button stores a choice in this browser. Loaded in <head> so the page never flashes
   the wrong theme. Storage can be unavailable (private windows): then the choice lasts
   for the page only. */
(function () {
  var KEY = "hl-theme";
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function store(value) {
    try { localStorage.setItem(KEY, value); } catch (e) { /* not kept */ }
  }
  function isDark() {
    var t = root.getAttribute("data-theme");
    if (t) return t === "hansard-dark";
    return !!(media && media.matches);
  }

  var choice = stored();
  if (choice === "hansard" || choice === "hansard-dark") root.setAttribute("data-theme", choice);

  function sync(button) {
    var dark = isDark();
    button.setAttribute("aria-pressed", dark ? "true" : "false");
    button.title = dark ? button.dataset.toLight : button.dataset.toDark;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.querySelector(".theme-toggle");
    if (!button) return;
    button.hidden = false;
    sync(button);
    button.addEventListener("click", function () {
      var next = isDark() ? "hansard" : "hansard-dark";
      root.setAttribute("data-theme", next);
      store(next);
      sync(button);
    });
    if (media && media.addEventListener) media.addEventListener("change", function () { sync(button); });
  });
})();
