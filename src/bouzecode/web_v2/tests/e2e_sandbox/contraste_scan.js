// [desc] Mesure du contraste WCAG texte/fond de chaque texte visible d'une zone : couleur et fond effectifs (fonds translucides empilés, opacité), seuil 4,5:1 (3:1 pour le grand texte). [/desc]
//  Évalué par Playwright : `page.evaluate(SCAN, {racine, seuil})` → liste des échecs.
//  Ignorés (WCAG 1.4.3 « incidental ») : texte désactivé ou occupé, décor `aria-hidden`, éléments invisibles.
({ racine = "body", seuil = 4.5 } = {}) => {
  const canvas = document.createElement("canvas").getContext("2d");
  const parse = (c) => {
    let m = /^rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)$/.exec(c);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
    m = /^color\(srgb ([\d.e-]+) ([\d.e-]+) ([\d.e-]+)(?: \/ ([\d.e-]+))?\)$/.exec(c);
    if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : +m[4]];
    //  Autre espace (oklch, lab…) : le canevas le ramène en sRGB.
    canvas.clearRect(0, 0, 1, 1); canvas.fillStyle = "#000"; canvas.fillStyle = c; canvas.fillRect(0, 0, 1, 1);
    const d = canvas.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const sur = (haut, bas) => {  // `haut` (rgba) posé sur `bas` (opaque)
    const a = haut[3];
    return [0, 1, 2].map((i) => haut[i] * a + bas[i] * (1 - a)).concat(1);
  };
  const lum = (c) => {
    const [r, g, b] = c.slice(0, 3).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

  //  Fond effectif : on empile les fonds des ancêtres, du plus lointain (fond de page) au plus proche.
  const fond = (el) => {
    const couches = [];
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      const c = parse(cs.backgroundColor);
      if (c[3] > 0) couches.push(c);
      if (c[3] >= 1) break;
    }
    let bas = [255, 255, 255, 1];
    const html = parse(getComputedStyle(document.documentElement).backgroundColor);
    if (html[3] > 0) bas = sur(html, bas);
    for (const c of couches.reverse()) bas = sur(c, bas);
    return bas;
  };
  const opacite = (el) => { let o = 1; for (let e = el; e; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
  //  Occupé (aria-busy) = inactif le temps de la requête, comme un bouton désactivé.
  const desactive = (el) => !!el.closest(":disabled, [aria-disabled='true'], [aria-busy='true'], [inert]");
  const decrire = (el) => el.tagName.toLowerCase() + (el.id ? `#${el.id}` : "")
    + (el.classList.length ? "." + [...el.classList].join(".") : "");

  const echecs = [];
  const vus = new Set();
  const zone = document.querySelector(racine);
  if (!zone) return [{ erreur: `zone introuvable : ${racine}` }];
  const marcheur = document.createTreeWalker(zone, NodeFilter.SHOW_TEXT);
  for (let n = marcheur.nextNode(); n; n = marcheur.nextNode()) {
    const texte = n.textContent.trim();
    const el = n.parentElement;
    if (!texte || !el || vus.has(el)) continue;
    vus.add(el);
    if (el.closest("script, style, noscript, template, option, .sr-only, [aria-hidden='true']")) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
    if (desactive(el)) continue;
    const cs = getComputedStyle(el);
    const bg = fond(el);
    let couleur = parse(cs.color);
    const o = opacite(el);
    couleur = sur([...couleur.slice(0, 3), couleur[3] * o], bg);
    const taille = parseFloat(cs.fontSize);
    const grand = taille >= 24 || (taille >= 18.66 && +cs.fontWeight >= 700);
    const min = grand ? Math.min(3, seuil) : seuil;
    const x = ratio(couleur, bg);
    if (x < min) {
      echecs.push({ el: decrire(el), texte: texte.slice(0, 50), ratio: Math.round(x * 100) / 100, min,
                    couleur: cs.color, fond: `rgb(${bg.slice(0, 3).map(Math.round).join(", ")})` });
    }
  }
  return echecs;
}
