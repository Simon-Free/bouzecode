// Sélecteur de langue de la barre de navigation : lit la langue courante, l'écrit au
// changement. Script classique (comme le noyau), pour être câblé sur les trois gabarits
// quel que soit leur mode de chargement.
//
// Aucun rechargement : `setLang` retraduit le DOM annoté et émet `i18n:change`, que les
// pages écoutent pour redessiner ce qu'elles ont construit en JavaScript.
(function (global) {
  "use strict";

  function wire() {
    var select = global.document.getElementById("lang-switch");
    if (!select) return;
    select.value = global.i18n.getLang();
    select.addEventListener("change", function () { global.i18n.setLang(select.value); });
  }

  if (global.document.readyState === "loading") {
    global.document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})(typeof window !== "undefined" ? window : globalThis);
