// Price history: one step line per listing (size · supplier). A price holds until it
// changes, so lines step rather than slope. Hovering shows every series' price that day.
(function () {
  const root = document.getElementById("price-chart");
  const series = JSON.parse(document.getElementById("price-data").textContent)
    .map(s => ({ ...s, points: s.points.map(([t, p]) => [new Date(t).getTime(), p]) }));
  const color = i => `var(--series-${(i % 8) + 1})`;
  const money = p => "€" + p.toFixed(2);
  const whole = p => "€" + (Number.isInteger(p) ? p : p.toFixed(2));
  const day = t => new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });

  const W = root.clientWidth, H = 240, pad = { l: 64, r: 16, t: 16, b: 28 };
  const times = series.flatMap(s => s.points.map(p => p[0]));
  const prices = series.flatMap(s => s.points.map(p => p[1]));
  let t0 = Math.min(...times), t1 = Math.max(...times);
  if (t1 - t0 < 864e5) t0 = t1 - 7 * 864e5;  // under a day of data: show the last week
  // Round price gridlines (every €5, €10, €20, €50…) with some room above and below.
  let p0 = Math.min(...prices), p1 = Math.max(...prices);
  const room = Math.max((p1 - p0) * 0.15, p1 * 0.05);
  const raw = (p1 - p0 + 2 * room) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(v => v >= raw);
  p0 = Math.max(0, Math.floor((p0 - room) / step) * step);
  p1 = Math.ceil((p1 + room) / step) * step;
  const ticks = Math.round((p1 - p0) / step);
  const x = t => pad.l + (t - t0) / (t1 - t0) * (W - pad.l - pad.r);
  const y = p => pad.t + (1 - (p - p0) / (p1 - p0)) * (H - pad.t - pad.b);

  const ns = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, parent) => {
    const n = document.createElementNS(ns, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    parent.appendChild(n); return n;
  };
  const svg = el("svg", { width: W, height: H, role: "img", "aria-label": "Price history" }, root);

  for (let i = 0; i <= ticks; i++) {  // recessive grid with price labels
    const p = p0 + step * i;
    el("line", { x1: pad.l, x2: W - pad.r, y1: y(p), y2: y(p), class: "grid" }, svg);
    el("text", { x: pad.l - 8, y: y(p) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = whole(p);
  }
  for (let i = 0; i <= 3; i++) {
    const t = t0 + (t1 - t0) * i / 3;
    el("text", { x: x(t), y: H - 8, "text-anchor": i === 0 ? "start" : i === 3 ? "end" : "middle", class: "tick" }, svg).textContent = day(t);
  }
  series.forEach((s, i) => {
    let d = "";
    s.points.forEach(([t, p], j) => { d += j ? ` H${x(t)} V${y(p)}` : `M${x(t)} ${y(p)}`; });
    el("path", { d, fill: "none", stroke: color(i), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
  });

  if (series.length > 1) {  // legend: identity never by color alone
    const legend = document.createElement("div");
    legend.className = "legend";
    legend.innerHTML = series.map((s, i) => `<span><i style="background:${color(i)}"></i>${s.label}</span>`).join("");
    root.prepend(legend);
  }

  const cross = el("line", { y1: pad.t, y2: H - pad.b, class: "cross", visibility: "hidden" }, svg);
  const tip = document.createElement("div");
  tip.className = "tip"; tip.hidden = true; root.appendChild(tip);
  const priceAt = (s, t) => { let p = null; for (const [pt, pp] of s.points) if (pt <= t) p = pp; return p; };
  svg.addEventListener("mousemove", e => {
    const box = svg.getBoundingClientRect(), mx = e.clientX - box.left;
    if (mx < pad.l || mx > W - pad.r) { cross.setAttribute("visibility", "hidden"); tip.hidden = true; return; }
    const t = t0 + (mx - pad.l) / (W - pad.l - pad.r) * (t1 - t0);
    cross.setAttribute("x1", mx); cross.setAttribute("x2", mx); cross.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>${day(t)}</b>` + series.map((s, i) => {
      const p = priceAt(s, t);
      return p === null ? "" : `<div><i style="background:${color(i)}"></i>${s.label} <b>${money(p)}</b></div>`;
    }).join("");
    tip.hidden = false;
    tip.style.left = Math.min(mx + 12, W - tip.offsetWidth - 4) + "px";
  });
  svg.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; });
})();
