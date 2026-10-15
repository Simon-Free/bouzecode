// [desc] Profils › Bibliothèque › Plugins : liste, installation depuis GitLab / dossier git (progression, confirmation du clone), mise à jour. [/desc]
import { api, busy, toast, confirm as ask, h, skeleton, failed, empty } from "../lib/ui.js";

const $ = (id) => document.getElementById(id);
let onChanged = async () => {};

/** `changed()` recharge le catalogue de l'éditeur (un plugin apporte outils et skills). */
export function initPlugins({ changed }) {
  onChanged = changed;
  $("pf-plugin-form").addEventListener("submit", (e) => { e.preventDefault(); installFromGitlab(); });
  $("pf-plugin-input").addEventListener("input", () => { $("pf-plugin-error").textContent = ""; });
}

export async function loadPlugins() {
  skeleton($("pf-plugins"), 3);
  let plugins;
  try {
    plugins = (await api("GET", "/api/plugins")).plugins || [];
  } catch (err) {
    failed($("pf-plugins"), err, loadPlugins, { title: "Liste des plugins indisponible." });
    return;
  }
  if (!plugins.length) {
    empty($("pf-plugins"), { title: "Aucun plugin installé.", text: "Un plugin apporte des outils et des skills : installe-le depuis son dépôt GitLab ci-dessus.", inline: true });
    return;
  }
  $("pf-plugins").removeAttribute("aria-busy");
  $("pf-plugins").replaceChildren(...plugins.map((p) => {
    const btn = h("button", { type: "button", class: "btn btn--sm" }, "Mettre à jour");
    btn.addEventListener("click", () => update(p, btn));
    const nTools = (p.tools || []).length;
    return h("div", { class: "pf-cat", "data-name": p.name },
      h("div", { class: "pf-cat__meta" },
        h("b", {}, p.name, p.version ? h("span", { class: "pf-muted" }, ` v${p.version}`) : null),
        h("div", { class: "pf-muted" }, `${nTools} outil${nTools > 1 ? "s" : ""}${p.source ? ` · ${p.source}` : ""}`)),
      btn);
  }));
}

/** POST avec la confirmation git en deux temps : le serveur demande, l'utilisateur accepte, on rejoue. */
async function postConfirmable(url, body, { onClone } = {}) {
  let data = await api("POST", url, body, { timeout: 300000 });
  if (data && data.requires_confirmation) {
    const ok = await ask({ title: "Installer depuis le dépôt git ?", text: data.message || "", confirmLabel: "Cloner et installer" });
    if (!ok) return { cancelled: true };
    if (onClone) onClone();
    data = await api("POST", url, { ...body, confirm_git: true }, { timeout: 300000 });
  }
  return data;
}

async function installFromGitlab() {
  const input = $("pf-plugin-input").value.trim();
  if (!input) {
    $("pf-plugin-error").textContent = "Colle l'URL du dépôt GitLab ou le chemin d'un dossier git local.";
    $("pf-plugin-input").focus();
    return;
  }
  const btn = $("pf-plugin-install");
  await busy(btn, "Installation…", async () => {
    let data;
    try {
      data = await postConfirmable("/api/plugins/from-gitlab", { input }, { onClone: () => { btn.textContent = "Clonage…"; } });
    } catch (err) {
      $("pf-plugin-error").textContent = err.message;
      toast.err(`Plugin non installé : ${err.message}`);
      return;
    }
    if (data.cancelled) { toast.info("Installation annulée."); return; }
    $("pf-plugin-input").value = "";
    const via = data.via === "git" ? "depuis le dépôt git" : "depuis Artifactory";
    toast.ok(`Plugin « ${data.package || input} » installé ${via}. Ses outils et skills sont disponibles.`);
    await Promise.all([loadPlugins(), onChanged()]);
  });
}

async function update(p, btn) {
  await busy(btn, "Mise à jour…", async () => {
    let data;
    try {
      data = await postConfirmable("/api/plugins", { package: p.name, source: p.source || "" });
    } catch (err) {
      toast.err(`« ${p.name} » non mis à jour : ${err.message}`);
      return;
    }
    if (data.cancelled) { toast.info("Mise à jour annulée."); return; }
    toast.ok(data.message || `Plugin « ${p.name} » à jour.`);
    await Promise.all([loadPlugins(), onChanged()]);
  });
}
