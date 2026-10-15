// [desc] Enregistrement automatique d'un champ (brief d'une tâche) : à la frappe (≈ 800 ms), à la perte de focus et avant de lancer / quitter ; « Enregistrement… » → « Enregistré » ; en erreur, message + nouvel essai, texte jamais perdu ; la dernière frappe gagne. [/desc]
//
// Remplace les boutons Enregistrer / Annuler et la garde « modifications non enregistrées »
// (SPEC R9) : il n'y a plus rien à confirmer, sauf quand un envoi est encore en vol au moment
// de quitter la page.

const DELAI_FRAPPE = 800;
const DELAI_NOUVEL_ESSAI = 5000;

const actifs = new Set(); // contrôleurs ayant quelque chose à enregistrer

// Numéros de séquence partagés par les lectures du serveur et les enregistrements : une lecture
// partie AVANT la fin d'un enregistrement (et arrivée après) porte le brief d'avant, elle ne doit
// pas l'écraser. `horloge()` numérote une lecture au départ, ou un enregistrement réussi.
let tic = 0;
export function horloge() { return ++tic; }

let gardeInstallee = false;
function installerGarde() {
  if (gardeInstallee || typeof window === "undefined") return;
  gardeInstallee = true;
  window.addEventListener("beforeunload", (e) => {
    const enCours = [...actifs].filter((c) => c.enAttente());
    if (!enCours.length) return;
    for (const c of enCours) c.envoyer();
    e.preventDefault();
    e.returnValue = "";
  });
}

/**
 * @param {HTMLTextAreaElement|HTMLInputElement} champ
 * @param {HTMLElement} etat  zone discrète « Enregistrement… / Enregistré / erreur » (role=status)
 * @param {(valeur:string) => Promise<any>} sauver  appel serveur ; lève en cas d'échec
 * @param {(reponse:any, valeur:string) => void} [surEnregistre]
 */
export function autosave(champ, etat, sauver, surEnregistre = () => {}) {
  installerGarde();
  let dernier = champ.value; // ce que le serveur a
  let minuteur = null;
  let nouvelEssai = null;
  let enVol = null;
  let aRefaire = false;
  let erreur = null;
  let enregistreNo = 0; // séquence du dernier enregistrement réussi

  const dire = (texte, enErreur = false) => {
    etat.textContent = texte;
    etat.dataset.erreur = enErreur ? "true" : "false";
  };

  function reussir(r, valeur) {
    dernier = valeur;
    enregistreNo = horloge();
    erreur = null;
    if (champ.value === valeur) dire("Enregistré");
    surEnregistre(r, valeur);
  }

  function echouer(e) {
    erreur = e;
    dire(`Pas encore enregistré : ${e.message} — nouvel essai dans 5 s.`, true);
    clearTimeout(nouvelEssai);
    nouvelEssai = setTimeout(envoyer, DELAI_NOUVEL_ESSAI);
  }

  function lancerEnvoi() {
    const valeur = champ.value;
    dire("Enregistrement…");
    enVol = sauver(valeur).then((r) => reussir(r, valeur), echouer).finally(() => {
      enVol = null;
      if (aRefaire) { aRefaire = false; envoyer(); }
      if (!ctrl.enAttente()) actifs.delete(ctrl);
    });
    return enVol;
  }

  /** Envoie maintenant ce qui n'est pas encore enregistré (la dernière frappe gagne). */
  function envoyer() {
    clearTimeout(minuteur);
    minuteur = null;
    clearTimeout(nouvelEssai);
    if (enVol) { aRefaire = true; return enVol; }
    if (champ.value === dernier && !erreur) return Promise.resolve();
    return lancerEnvoi();
  }

  const ctrl = {
    envoyer,
    /** Quelque chose reste à enregistrer (frappe en attente, envoi en vol, ou erreur). */
    enAttente: () => champ.value !== dernier || !!enVol || !!minuteur || !!erreur,
    /** Enregistre tout de suite et attend ; lève si l'enregistrement échoue (ne lance rien sur un vieux brief). */
    async vider() {
      await envoyer();
      while (enVol) await enVol;
      if (erreur) throw erreur;
    },
    /** Le serveur a une nouvelle valeur : on la prend seulement si l'utilisateur n'écrit pas, et si
     *  la lecture (`lueNo`, pris par `horloge()` à son départ) est postérieure au dernier enregistrement. */
    depuisServeur(valeur, lueNo) {
      if (ctrl.enAttente() || document.activeElement === champ) return;
      if (lueNo != null && lueNo < enregistreNo) return;
      if (champ.value !== valeur) champ.value = valeur;
      dernier = valeur;
    },
  };

  champ.addEventListener("input", () => {
    actifs.add(ctrl);
    if (!enVol) dire("");
    clearTimeout(minuteur);
    minuteur = setTimeout(envoyer, DELAI_FRAPPE);
  });
  champ.addEventListener("blur", () => { if (ctrl.enAttente()) envoyer(); });
  return ctrl;
}
