// [desc] Profils : actions sur le profil courant — enregistrer, dupliquer, exporter, importer, mettre à jour ses plugins, supprimer. [/desc]
import { api, busy, toast, confirm as ask } from "../lib/ui.js";
import { S, copyName, nameProblem } from "./state.js";
import { collect } from "./editor.js";

const $ = (id) => document.getElementById(id);
const enc = encodeURIComponent;

/** Erreur affichée sous le champ nom (et focus dessus). */
export function nameError(msg) {
  $("pf-name-error").textContent = msg;
  if (msg) { $("pf-name").setAttribute("aria-invalid", "true"); $("pf-name").focus(); }
  else $("pf-name").removeAttribute("aria-invalid");
}

function takenNames() { return new Set(S.agents.map((a) => a.name)); }

/**
 * Enregistre le profil courant. Renvoie le nom enregistré, ou null si rien n'a été écrit
 * (erreur dite sous le champ ou en toast — jamais en silence).
 */
export async function saveProfile() {
  const body = collect();
  const problem = nameProblem(body.name, { taken: takenNames(), isNew: S.current.mode === "new" });
  if (problem) { nameError(problem); return null; }
  return busy($("pf-save"), "Enregistrement…", async () => {
    let saved;
    try {
      saved = await api("POST", "/api/profiles", {
        ...body, create: S.current.mode === "new", based_on: S.current.basedOn || "",
      });
    } catch (err) {
      if (err.status === 409 || /nom/i.test(err.message)) nameError(err.message);
      else toast.err(`Profil non enregistré : ${err.message}`);
      return null;
    }
    const missing = saved.missing ? saved.missing.tools.length + saved.missing.skills.length : 0;
    toast.ok(`Profil « ${saved.name} » enregistré.`);
    if (missing) toast.info(`${missing} sélection(s) introuvable(s) dans le catalogue actuel ont été conservées.`);
    return saved.name;
  });
}

/** Passe l'éditeur en « copie non enregistrée » du profil courant. */
export function duplicateCurrent() {
  const origin = S.current.name || $("pf-name").value.trim();
  const name = copyName(origin || "profil", takenNames());
  S.current = { mode: "new", name: "", basedOn: S.current.mode === "new" ? S.current.basedOn : origin, missing: S.current.missing };
  $("pf-name").value = name;
  nameError("");
  toast.info(`Copie de « ${origin || "profil"} » — non enregistrée. Renomme-la si tu veux, puis Enregistrer.`);
  return name;
}

export async function exportProfile(name) {
  let data;
  try {
    data = await api("GET", `/api/agents/${enc(name)}/export`);
  } catch (err) {
    toast.err(`Export impossible : ${err.message}`);
    return;
  }
  const blob = new Blob([data.yaml || ""], { type: "text/yaml" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${name}.yaml`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast.ok(`Profil « ${name} » exporté (${name}.yaml).`);
}

/** Importe un profil depuis le texte YAML ; renvoie son nom ou null. */
export async function importProfile(yamlText) {
  const post = (extra) => api("POST", "/api/agents/import", { yaml: yamlText, ...extra }, { timeout: 300000 });
  let data;
  try {
    data = await post({});
    if (data && data.requires_confirmation) {
      const ok = await ask({ title: "Ce profil installe des plugins depuis git",
        text: `${data.message || ""}\n${(data.git_sources || []).join("\n")}`, confirmLabel: "Installer" });
      if (!ok) { toast.info("Import annulé."); return null; }
      data = await post({ confirm_git: true });
    }
  } catch (err) {
    toast.err(`Import impossible : ${err.message}`);
    return null;
  }
  const errs = (data.errors || []).length;
  if (errs) toast.err(`Profil « ${data.name} » importé, mais : ${data.errors.join(" ; ")}`);
  else toast.ok(`Profil « ${data.name} » importé.`);
  return data.name || null;
}

export async function upgradePlugins(name) {
  const url = `/api/agents/${enc(name)}/upgrade-plugins`;
  const t = toast.info(`Mise à jour des plugins de « ${name} »…`, { sticky: true });
  let data;
  try {
    data = await api("POST", url, {}, { timeout: 300000 });
    if (data && data.requires_confirmation) {
      const ok = await ask({ title: "Mettre à jour depuis git ?", text: data.message || "", confirmLabel: "Mettre à jour" });
      if (!ok) { t.close(); toast.info("Mise à jour annulée."); return; }
      data = await api("POST", url, { confirm_git: true }, { timeout: 300000 });
    }
  } catch (err) {
    t.close();
    toast.err(`Plugins non mis à jour : ${err.message}`);
    return;
  }
  t.close();
  const results = data.results || [];
  if (!results.length) { toast.ok(`« ${name} » n'utilise aucun plugin : rien à mettre à jour.`); return; }
  const ko = results.filter((r) => !r.ok);
  const lines = results.map((r) => (r.ok ? `${r.package} : v${r.before || "?"} → v${r.after || "?"}` : `${r.package} : échec (${r.message || "?"})`));
  if (ko.length) toast.err(`Mise à jour partielle — ${lines.join(" · ")}`);
  else toast.ok(`Plugins à jour — ${lines.join(" · ")}`);
}

/** Supprime le profil (après confirmation) ; renvoie true s'il l'a été. */
export async function deleteProfile(name) {
  const ok = await ask({ title: `Supprimer le profil « ${name} » ?`, danger: true, confirmLabel: "Supprimer",
    text: "Son fichier est effacé ; les agents déjà lancés avec ce profil ne sont pas affectés. Pense à l'exporter si tu veux le garder." });
  if (!ok) return false;
  try {
    await api("DELETE", `/api/profiles/${enc(name)}`);
  } catch (err) {
    toast.err(`Profil non supprimé : ${err.message}`);
    return false;
  }
  toast.ok(`Profil « ${name} » supprimé.`);
  return true;
}
