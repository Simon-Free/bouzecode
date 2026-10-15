// [desc] Profils : en-tête de l'éditeur (titre, origine, « • modifié ») et barre d'actions selon le mode (nouveau / mon profil / fourni), URL `?profil=`. [/desc]
import { S } from "./state.js";
import { isDirty } from "./editor.js";

const $ = (id) => document.getElementById(id);

function origine(mode, name) {
  if (mode === "new") return S.current.basedOn ? `Copie de ${S.current.basedOn} · non enregistré` : "Non enregistré";
  if (mode === "edit") return "Mon profil";
  const agent = S.agents.find((a) => a.name === name);
  return `Fourni · ${agent ? agent.source : ""}`;
}

/** Boutons de la barre selon le mode : un profil fourni ne s'enregistre pas, il se duplique. */
function majBoutons(mode, name, dirty) {
  $("pf-dirty").textContent = dirty && mode !== "readonly" ? "• modifié" : "";
  $("pf-save").hidden = mode === "readonly";
  // Nouveau : enregistrable dès qu'il a un nom. Existant : seulement s'il a changé.
  $("pf-save").disabled = mode === "new" ? !$("pf-name").value.trim() : !dirty;
  $("pf-readonly").hidden = mode !== "readonly";
  $("pf-duplicate").hidden = mode === "readonly";
  $("pf-use").hidden = mode === "new";
  $("pf-use").href = `/conversations?profil=${encodeURIComponent(name)}`;
}

function majNom(mode) {
  $("pf-name").readOnly = mode !== "new";
  $("pf-name").title = mode === "edit" ? "Le nom d'un profil enregistré ne change pas : duplique-le pour lui en donner un autre." : "";
}

/** L'URL garde le profil ouvert (`?profil=`), pour le lien et le rechargement. */
function majUrl(mode, name) {
  const url = new URL(location.href);
  if (mode === "new") url.searchParams.delete("profil"); else url.searchParams.set("profil", name);
  history.replaceState(null, "", url);
}

export function refreshHeader() {
  const { mode, name } = S.current;
  $("pf-title").textContent = mode === "new" ? ($("pf-name").value.trim() || "Nouveau profil") : name;
  $("pf-origin").hidden = false;
  $("pf-origin").textContent = origine(mode, name);
  majBoutons(mode, name, isDirty());
  majNom(mode);
  majUrl(mode, name);
}
