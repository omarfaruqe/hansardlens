/* HansardLens line chart: dependency-free SVG.
 *
 * <figure class="chart" data-source="ID-of-json_script" data-unit-short="‰">
 *   <div class="chart-plot"></div>
 * </figure>
 *
 * data-integer="1" keeps the axis on whole numbers (for counts).
 *
 * JSON: {months: ["2022-01", ...], denominators: [...], series: [{name, values, counts?}], unit}
 * Null values are months without sittings and are drawn as gaps, never as zeros.
 * All text goes in through textContent (series names come from user input).
 */
(function () {
  "use strict";
  var SVG = "http://www.w3.org/2000/svg";
  var COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
  var lang = document.documentElement.lang || "en";
  var monthFmt = new Intl.DateTimeFormat(lang, { month: "long", year: "numeric", timeZone: "UTC" });
  var numFmt = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
  var intFmt = new Intl.NumberFormat(lang);

  function el(name, attrs, parent) {
    var node = document.createElementNS(SVG, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceMax(v) {
    if (!(v > 0)) return 1;
    var exp = Math.pow(10, Math.floor(Math.log10(v)));
    var steps = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (var i = 0; i < steps.length; i++) if (steps[i] * exp >= v) return steps[i] * exp;
    return 10 * exp;
  }

  function monthDate(m) {
    return new Date(Date.UTC(+m.slice(0, 4), +m.slice(5, 7) - 1, 1));
  }

  function render(fig) {
    var data = JSON.parse(document.getElementById(fig.dataset.source).textContent);
    var plot = fig.querySelector(".chart-plot");
    plot.textContent = "";
    var n = data.months.length;
    if (!n || !data.series.length) return;

    var width = plot.clientWidth || 600;
    var narrow = width < 560;
    var height = narrow ? 240 : 320;
    var m = { top: 14, right: narrow ? 12 : 120, bottom: 30, left: 44 };
    var w = width - m.left - m.right, h = height - m.top - m.bottom;
    var maxV = 0;
    data.series.forEach(function (s) {
      s.values.forEach(function (v) { if (v != null && v > maxV) maxV = v; });
    });
    var yMax = fig.dataset.yMax ? +fig.dataset.yMax : niceMax(maxV * 1.05);
    // Counts (data-integer): four gridlines at whole numbers.
    if (fig.dataset.integer) yMax = 4 * Math.max(1, Math.ceil(maxV / 4));
    var step = n > 1 ? w / (n - 1) : 0;
    var x = function (i) { return m.left + (n > 1 ? i * step : w / 2); };
    var y = function (v) { return m.top + h - (v / yMax) * h; };

    var svg = el("svg", {
      viewBox: "0 0 " + width + " " + height, width: width, height: height,
      role: "img", "aria-label": fig.dataset.label || "", tabindex: "0", class: "chart-svg"
    }, plot);

    // Grid and y axis (recessive)
    for (var t = 0; t <= 4; t++) {
      var v = (yMax * t) / 4, yy = y(v);
      el("line", { x1: m.left, x2: m.left + w, y1: yy, y2: yy, class: t ? "grid" : "baseline" }, svg);
      var lab = el("text", { x: m.left - 8, y: yy + 4, class: "tick", "text-anchor": "end" }, svg);
      lab.textContent = numFmt.format(v);
    }
    // X axis: a label at each January, plus the first month unless it would collide
    data.months.forEach(function (mo, i) {
      var firstFits = data.months.slice(1).every(function (o, j) {
        return o.slice(5) !== "01" || x(j + 1) - x(0) > 40;
      });
      if ((i === 0 && firstFits) || (i > 0 && mo.slice(5) === "01")) {
        var tx = el("text", { x: x(i), y: m.top + h + 20, class: "tick", "text-anchor": i === 0 ? "start" : "middle" }, svg);
        tx.textContent = mo.slice(0, 4);
        if (i) el("line", { x1: x(i), x2: x(i), y1: m.top + h, y2: m.top + h + 5, class: "baseline" }, svg);
      }
    });

    // Series: gaps for null months; lone points get a dot so they stay visible
    var ends = [];
    data.series.forEach(function (s, si) {
      var d = "", pen = false, last = -1;
      s.values.forEach(function (v, i) {
        if (v == null) { pen = false; return; }
        d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1);
        var prev = s.values[i - 1], next = s.values[i + 1];
        if (prev == null && next == null) {
          el("circle", { cx: x(i), cy: y(v), r: 2.5, fill: COLORS[si] }, svg);
        }
        pen = true; last = i;
      });
      el("path", { d: d, fill: "none", stroke: COLORS[si], "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      if (last >= 0) ends.push({ name: s.name, y: y(s.values[last]), x: x(last), color: COLORS[si] });
    });

    // Direct labels at line ends (wide screens), nudged apart to avoid collisions
    if (!narrow && data.series.length <= 4) {
      ends.sort(function (a, b) { return a.y - b.y; });
      for (var k = 1; k < ends.length; k++) {
        if (ends[k].y - ends[k - 1].y < 15) ends[k].y = ends[k - 1].y + 15;
      }
      ends.forEach(function (e) {
        el("line", { x1: m.left + w + 4, x2: m.left + w + 14, y1: e.y, y2: e.y, stroke: e.color, "stroke-width": 2 }, svg);
        var tl = el("text", { x: m.left + w + 18, y: e.y + 4, class: "end-label" }, svg);
        tl.textContent = e.name.length > 16 ? e.name.slice(0, 15) + "…" : e.name;
      });
    }

    // Hover / keyboard layer: crosshair snaps to the nearest month
    var hair = el("line", { y1: m.top, y2: m.top + h, class: "hairline", visibility: "hidden" }, svg);
    var dots = data.series.map(function (s, si) {
      return el("circle", { r: 4, fill: COLORS[si], class: "hover-dot", visibility: "hidden" }, svg);
    });
    var tip = document.createElement("div");
    tip.className = "chart-tip";
    tip.hidden = true;
    plot.appendChild(tip);
    var current = null;

    function show(i) {
      current = i;
      hair.setAttribute("x1", x(i)); hair.setAttribute("x2", x(i));
      hair.setAttribute("visibility", "visible");
      tip.textContent = "";
      var head = document.createElement("div");
      head.className = "tip-head";
      head.textContent = monthFmt.format(monthDate(data.months[i]));
      tip.appendChild(head);
      var allNull = data.series.every(function (s) { return s.values[i] == null; });
      if (allNull) {
        var none = document.createElement("div");
        none.textContent = data.denominators[i] == null
          ? (fig.dataset.noSittings || "No sittings")
          : (fig.dataset.thin || "Too little debate this month to compare");
        tip.appendChild(none);
      }
      data.series.forEach(function (s, si) {
        var v = s.values[i];
        if (v == null) { dots[si].setAttribute("visibility", "hidden"); return; }
        dots[si].setAttribute("cx", x(i)); dots[si].setAttribute("cy", y(v));
        dots[si].setAttribute("visibility", "visible");
        var row = document.createElement("div");
        row.className = "tip-row";
        var key = document.createElement("span");
        key.className = "tip-key"; key.style.background = COLORS[si];
        var val = document.createElement("strong");
        val.textContent = numFmt.format(v) + (fig.dataset.unitShort || "");
        var name = document.createElement("span");
        name.className = "tip-name";
        name.textContent = " " + s.name;
        row.appendChild(key); row.appendChild(val); row.appendChild(name);
        if (s.counts && s.counts[i] != null) {
          var detail = document.createElement("div");
          detail.className = "tip-detail";
          detail.textContent = intFmt.format(s.counts[i]) + " / " + intFmt.format(data.denominators[i]) + " " + (fig.dataset.denominatorLabel || "");
          row.appendChild(detail);
        }
        tip.appendChild(row);
      });
      tip.hidden = false;
      var left = x(i) + 12;
      if (left + tip.offsetWidth > width) left = x(i) - tip.offsetWidth - 12;
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = m.top + "px";
    }

    function hide() {
      current = null;
      tip.hidden = true;
      hair.setAttribute("visibility", "hidden");
      dots.forEach(function (d) { d.setAttribute("visibility", "hidden"); });
    }

    svg.addEventListener("pointermove", function (ev) {
      var r = svg.getBoundingClientRect();
      var px = ((ev.clientX - r.left) / r.width) * width;
      var i = n > 1 ? Math.round((px - m.left) / step) : 0;
      show(Math.max(0, Math.min(n - 1, i)));
    });
    svg.addEventListener("pointerleave", hide);
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", function (ev) {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      var i = current == null ? n - 1 : current + (ev.key === "ArrowRight" ? 1 : -1);
      show(Math.max(0, Math.min(n - 1, i)));
    });
  }

  function init() {
    document.querySelectorAll("figure.chart[data-source]").forEach(function (fig) {
      render(fig);
      if (window.ResizeObserver) {
        var lastW = 0;
        new ResizeObserver(function () {
          var wNow = fig.clientWidth;
          if (Math.abs(wNow - lastW) > 4) { lastW = wNow; render(fig); }
        }).observe(fig);
      }
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
