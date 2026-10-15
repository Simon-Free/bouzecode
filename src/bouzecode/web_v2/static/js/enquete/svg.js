// Graphiques SVG minimalistes, une seule échelle par graphique, couleurs portées par le CSS (tokens).
const NS = "http://www.w3.org/2000/svg";
const L = 760, H = 220, MARGE = { g: 56, d: 12, h: 12, b: 28 };

function el(tag, attrs, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
  if (parent) parent.appendChild(n);
  return n;
}

function echelles(xs, ymax) {
  const x0 = xs[0], x1 = xs[xs.length - 1] === x0 ? x0 + 1 : xs[xs.length - 1];
  const sx = (x) => MARGE.g + ((x - x0) / (x1 - x0)) * (L - MARGE.g - MARGE.d);
  const sy = (y) => H - MARGE.b - (y / (ymax || 1)) * (H - MARGE.h - MARGE.b);
  return { sx, sy, x0, x1 };
}

function axes(svg, e, ymax, format) {
  const g = el("g", { class: "eq-axe" }, svg);
  for (const f of [0, 0.5, 1]) {
    const y = e.sy(ymax * f);
    el("line", { x1: MARGE.g, x2: L - MARGE.d, y1: y, y2: y, class: "eq-grille" }, g);
    el("text", { x: MARGE.g - 6, y: y + 4, "text-anchor": "end" }, g).textContent = format(ymax * f);
  }
  el("text", { x: MARGE.g, y: H - 8 }, g).textContent = `tour ${e.x0}`;
  el("text", { x: L - MARGE.d, y: H - 8, "text-anchor": "end" }, g).textContent = `tour ${e.x1}`;
}

function base(titre) {
  const svg = el("svg", { viewBox: `0 0 ${L} ${H}`, class: "eq-graphe", role: "img" });
  el("title", {}, svg).textContent = titre;
  return svg;
}

function curseur(svg, e, points, surClic) {
  const zone = el("rect", { x: MARGE.g, y: MARGE.h, width: L - MARGE.g - MARGE.d,
    height: H - MARGE.h - MARGE.b, class: "eq-zone" }, svg);
  const ligne = el("line", { y1: MARGE.h, y2: H - MARGE.b, class: "eq-curseur", visibility: "hidden" }, svg);
  const pointe = (ev) => {
    const r = svg.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / r.width) * L;
    const proche = points.reduce((a, p) => (Math.abs(e.sx(p) - x) < Math.abs(e.sx(a) - x) ? p : a), points[0]);
    return proche;
  };
  zone.addEventListener("mousemove", (ev) => {
    const p = pointe(ev);
    ligne.setAttribute("x1", e.sx(p)); ligne.setAttribute("x2", e.sx(p));
    ligne.setAttribute("visibility", "visible");
    zone.setAttribute("aria-label", `tour ${p}`);
  });
  zone.addEventListener("click", (ev) => surClic(pointe(ev)));
}

export function courbe(points, { titre, format, marques = [], surClic }) {
  const xs = points.map((p) => p.x);
  const ymax = Math.max(1, ...points.map((p) => p.y));
  const e = echelles(xs, ymax);
  const svg = base(titre);
  axes(svg, e, ymax, format);
  const d = points.map((p, i) => `${i ? "L" : "M"}${e.sx(p.x)},${e.sy(p.y)}`).join(" ");
  el("path", { d, class: "eq-trace" }, svg);
  for (const m of marques) el("circle", { cx: e.sx(m.x), cy: e.sy(m.y), r: 4, class: "eq-marque-point" }, svg);
  if (surClic) curseur(svg, e, xs, surClic);
  return svg;
}

export function aireEmpilee(series, categories, { titre, format, surClic }) {
  const xs = series.map((s) => s.tour);
  const totaux = series.map((s) => categories.reduce((a, c) => a + (s[c] || 0), 0));
  const e = echelles(xs, Math.max(1, ...totaux));
  const svg = base(titre);
  axes(svg, e, Math.max(1, ...totaux), format);
  const bas = series.map(() => 0);
  categories.forEach((c) => {
    const haut = series.map((s, i) => bas[i] + (s[c] || 0));
    const aller = series.map((s, i) => `${e.sx(s.tour)},${e.sy(haut[i])}`);
    const retour = series.map((s, i) => `${e.sx(s.tour)},${e.sy(bas[i])}`).reverse();
    el("polygon", { points: [...aller, ...retour].join(" "), class: `eq-aire eq-aire--${c}` }, svg);
    haut.forEach((v, i) => { bas[i] = v; });
  });
  if (surClic) curseur(svg, e, xs, surClic);
  return svg;
}
