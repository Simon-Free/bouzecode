# [desc] Porte de clôture « parcours vérifiés » : une tâche d'interface ne se clôt que sur des parcours utilisateur RÉELLEMENT joués dans la session. [/desc]
"""Une interface ne se livre que sur des parcours utilisateur réellement joués.

Essai du 2026-09-24 (DeepSeek, « portail des énigmes ») : clôture en 29 min sur des
tests verts, mais l'édition effaçait les données, la réponse s'affichait avant d'être
demandée, la moitié des énigmes n'avait pas de figure. Aucun parcours n'avait été joué
comme un utilisateur. Le récap déclaratif ne pouvait pas le voir : il croit l'agent.

Cette porte ne croit que le JOURNAL de la session (`state.messages`) :
- elle s'active quand la session a écrit un fichier d'interface (html, css, js…), ou a
  écrit du code pour une demande qui nomme une interface ;
- elle exige `parcours_verifies` : pour chaque exigence, le parcours joué, l'`appel` qui le
  prouve (alias ou id, résolu directement) et sa `preuve` ; sans `appel`, la preuve en texte
  libre (commande exacte ou outil navigateur) est recoupée avec le journal ;
- chaque preuve doit correspondre à un appel RÉELLEMENT exécuté, dont la dernière
  exécution est verte ; au moins une passe par un navigateur, APRÈS la dernière
  modification d'un fichier d'interface.
Déterministe, zéro appel LLM : une petite correction sans interface n'est pas concernée.
"""
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass

_SUFFIXES_INTERFACE = {"html", "htm", "css", "scss", "js", "mjs", "jsx", "ts", "tsx",
                       "vue", "svelte", "jinja", "jinja2"}
# Un fichier de test n'est pas l'interface : l'écrire ne déclenche rien.
_FICHIER_DE_TEST_RE = re.compile(r"(^|/)(tests?|__tests__|e2e|spec)/|[._-](test|spec)\.[a-z]+$",
                                 re.I)
_DEMANDE_UI_RE = re.compile(
    r"interface (utilisateur|web|graphique)|\bUI\b|page web|site web|application web|"
    r"appli web|front-?end|navigateur|tableau de bord|dashboard", re.I)
_ECRITURES = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Outils qui n'EXÉCUTENT rien : les citer comme preuve ne prouve rien.
_NON_EXECUTANTS = _ECRITURES | {"Read", "Glob", "Grep", "Methodology", "Snippet",
                                "FinalAnswer", "WritePlan", "GetDiff"}
_NAVIGATEUR_RE = re.compile(r"playwright|puppeteer|selenium|cypress|webdriver|chromium|"
                            r"headless|\be2e\b", re.I)
_OUTIL_NAVIGATEUR_RE = re.compile(r"chrome|playwright|browser|puppeteer", re.I)
# `echo "playwright OK"` n'a rien joué : une commande qui ne fait qu'écrire ne prouve rien.
_TRIVIALE_RE = re.compile(r"^(echo|printf|true|:|cat|type|Write-Host|Write-Output)\b", re.I)
# Refus du harnais (cf. close_guard._TOOL_REFUSAL_PREFIXES) et sorties rouges usuelles.
_REFUS = ("ERROR parsing", "Error executing ", "Error: ", "Denied: ", "Skipped: ",
          "Cancelled: ", "[Plan mode]", "BLOCKED:")
_ECHEC_RE = re.compile(r"\[exited code=[1-9]\d*\]|\b[1-9]\d* (failed|errors?)\b|"
                       r"# fail [1-9]|timed out after", re.I)
# Une recette silencieuse sur son code de sortie (`… ; exit 0`) dit son échec dans sa SORTIE :
# ligne qui commence par FAIL / FAILED / ✗ / ✘ (smoke maison, pytest, Playwright), ou bilan
# « k/n OK » incomplet. Le compteur d'une page (« 1 / 310 ») n'est pas un bilan.
_LIGNE_ECHEC_RE = re.compile(r"(?m)^\s*(?:FAIL(?:ED)?\b|[✗✘])")
_BILAN_RE = re.compile(r"\b(\d+)/(\d+)\s*(?:OK|passed|pass|passés|réussis|verts?|tests?)\b", re.I)
# Une commande shell citée dans une preuve : elle doit avoir RÉELLEMENT tourné. Essai 3
# (racine 6bafe9cd, tour 37) : « python3 scraper/kangourou.py … ; RunPythonTest tests »
# passait sur le seul NOM « RunPythonTest ». pytest est exclu : RunPythonTest le lance
# sans que la commande apparaisse dans l'appel. Exécutables comparés sous forme normalisée
# (`C:\…\python.exe`, `python3.12`, `py` → python ; `npx.cmd` → npx) : le poste Windows lance
# les mêmes recettes sous PowerShell.
_EXECUTABLES = {"python", "node", "npm", "npx", "pnpm", "yarn", "bun", "deno", "curl", "wget",
                "bash", "sh", "zsh", "make", "cargo", "go", "uv", "pwsh", "powershell",
                "playwright", "invoke-webrequest", "iwr", "invoke-restmethod", "irm"}
_PYTHON_RE = re.compile(r"^(python[\d.]*|py)$")
_SUFFIXE_EXE_RE = re.compile(r"\.(exe|cmd|bat|com)$", re.I)
# Invite de commande recopiée devant la commande (`$ node x.js`, `PS C:\proj> node x.js`).
_INVITE_RE = re.compile(r"^(\$\s+|PS(\s+[^>]*)?>\s*|>\s+)")
_COUPE_PREUVE_RE = re.compile(r"`|→|->|=>|;|&&|\|\||\||\(|\)|«|»|\n|\s\+\s|\s(?:puis|then)\s|\s:\s")
_COUPE_COMMANDE_RE = re.compile(r"&&|\|\||;|\||\n|\s&\s")
# `$(curl … "http://…$u")` dans un `printf` : la substitution est une commande lancée.
_SUBSTITUTION_RE = re.compile(r"\$\(([^()]*)\)")
_REDIRECTION_RE = re.compile(r"\s+\d?>{1,2}&?\s*\S+")
# `timeout 60 python3 x.py`, `FOO=1 node s.js`, `$env:BASE='…'; node s.js`, `& "C:\…\npx.cmd"`,
# `do curl …` (corps de boucle) : la commande est ce qui suit l'enveloppe.
_ENVELOPPE_RE = re.compile(r"^((timeout\s+\S+|nohup|time|exec|env|do|then|else|\{|!|&|"
                           r"\$env:\w+\s*=\s*\S+|\w+=\S+)\s+)+", re.I)
_AFFECTATION_RE = re.compile(r"^(\$env:)?\w+=", re.I)
# Prose au milieu d'une commande citée (« curl -s … sur http://… ») : la citation s'arrête là.
_PROSE = {"sur", "puis", "dans", "avec", "pour", "et", "ou", "via", "depuis", "vers", "par",
          "contre", "on", "then", "with", "against", "…", "...", "etc", "etc.", "=", "(", ")"}
_EXTENSION_SCRIPT_RE = re.compile(r"\.(sh|bash|js|mjs|cjs|ts|tsx|py|ps1|rb|pl)$", re.I)
# Paramètres de plomberie : ils ne disent rien de CE qu'a fait l'appel.
_META = {"tool_call_alias", "depends_on", "parallel", "no_sync", "timeout", "pageId",
         "run_in_background", "description", "includeSnapshot"}
# Exigence qui AGIT : sa preuve navigateur doit montrer l'action, pas seulement l'écran.
# Des VERBES (infinitif, présent, impératif, gérondif) et les noms d'action ; pas les
# participes d'état : « compteur conservé, énigme acceptée non reproposée » décrit ce qu'on
# relit après rechargement (62a7742e, msg 177), pas un geste à jouer.
_V = r"(?:er|e|es|ent|ez|ons|ant)"
_EXIGENCE_ACTION_RE = re.compile(
    r"\b(?:"
    rf"modifi(?:er|e|es|ent|ez|ons|ant|ables?|cations?)|[ée]dit(?:er|e|es|ent|ez|ant|ions?|ing)?|"
    rf"enregistr(?:{_V}|ement)|sauvegard{_V}|supprim{_V}|suppressions?|effa(?:c{_V}|çant)|"
    rf"ajout{_V}?|ajouts|cré(?:{_V}|ations?)|chang(?:er|e|es|ent|ez|eant|ements?)|"
    rf"renomm{_V}|corrig(?:er|e|es|ent|ez|eant)|corrections?|accept{_V}|refus{_V}|"
    rf"envo(?:y(?:er|ez|ons|ant)|ie|ies|ient|is)|saisi(?:r|ssez|ssant|e)|"
    rf"rempli(?:r|ssez|ssant)|(?:dé)?coch{_V}|dépla(?:c{_V}|çant)|gliss{_V}|swip(?:er|e|es)|"
    r"save|delete|remove|add|create|update|submit|edit|rename|drag|toggle|upload"
    r")\b", re.I)
# Exigence de PERSISTANCE : le geste a pu être joué (et prouvé) dans un autre parcours déclaré,
# celui-ci recharge et relit. Essai du 2026-09-25 (6bafe9cd t65) : « Les choix
# (accepter/refuser/corrections) sont conservés après rechargement ».
_PERSISTANCE_RE = re.compile(r"conserv|persist|surviv|recharg|reload|restaur|rafraîch", re.I)
_INTERACTION_RE = re.compile(r"click|fill|press_key|type|drag|upload|select_option|handle_dialog",
                             re.I)
_SCRIPT_QUI_AGIT_RE = re.compile(
    r"\.click\(|\.value\s*=|\.checked\s*=|dispatchEvent|\.submit\(|requestSubmit|"
    r"setItem\(|removeItem\(|method\s*:\s*['\"](POST|PUT|PATCH|DELETE)", re.I)
_CONSTAT_RE = re.compile(r"snapshot|screenshot|evaluate_script|wait_for", re.I)
# « après clic sur Accepter » : la prose française d'un click (5 preuves sur 9 à l'essai 3).
_CLIC_RE = re.compile(r"\bclic\b|\bcliqu(e|é|er|ant)\b", re.I)


def _nomme(cible: str, nom: str) -> bool:
    """`nom` apparaît comme un mot dans la preuve : « onclick » ne nomme pas `click`."""
    if re.search(rf"(?<![\w-]){re.escape(nom)}(?![\w-])", cible):
        return True
    return nom.endswith("click") and bool(_CLIC_RE.search(cible))

CHAMPS = ("exigence", "parcours", "preuve")


class Manque(str):
    """Un problème de la porte, avec sa nature : « format » (la preuve n'est pas reconnue —
    l'appel a peut-être bien eu lieu) ou « echec » (rien n'a tourné, ou c'est rouge)."""
    nature: str

    def __new__(cls, texte: str, nature: str = "echec") -> "Manque":
        objet = super().__new__(cls, texte)
        objet.nature = nature
        return objet


def _prefixe(etiquette: str, probleme: str) -> Manque:
    return Manque(f"{etiquette} : {probleme}", getattr(probleme, "nature", "echec"))


@dataclass
class Appel:
    rang: int
    nom: str
    entree: dict
    resultat: str | None
    ident: str = ""

    def designe_par(self, reference: str) -> bool:
        """`reference` = son alias (`tool_call_alias`) ou son id (y compris l'id d'origine
        d'un id rendu unique par la boucle, `t12_<id>`)."""
        alias = str(self.entree.get("tool_call_alias") or "").strip()
        return bool(reference) and (reference == alias or reference == self.ident
                                    or self.ident.endswith("_" + reference))

    def texte(self) -> str:
        return _normaliser(" ".join(str(v) for v in self.entree.values()))

    def arguments(self) -> str:
        """Ce que l'appel a fait, sans la plomberie (alias, dépendances, page…)."""
        valeurs = []
        for cle, valeur in self.entree.items():
            if cle not in _META:
                valeurs += valeur if isinstance(valeur, list) else [valeur]
        return _normaliser(" ".join(str(v) for v in valeurs))

    def court(self) -> str:
        return self.nom.rsplit("__", 1)[-1]

    def segments(self) -> list[str]:
        """Les commandes élémentaires d'un appel shell (`a && b | c` → a, b, c), y compris
        celles lancées dans une substitution `$(…)`."""
        commande = self.entree.get("command")
        if not isinstance(commande, str):
            return []
        morceaux = _COUPE_COMMANDE_RE.split(commande)
        morceaux += [m for sub in _SUBSTITUTION_RE.findall(commande)
                     for m in _COUPE_COMMANDE_RE.split(sub)]
        return [_commande_nue(morceau) for morceau in morceaux if morceau.strip()]

    def constate(self) -> bool:
        """Un regard navigateur réussi sur la page (instantané, capture, script)."""
        return (self.nom.startswith("mcp__") and self.vert()
                and bool(_CONSTAT_RE.search(self.court())))

    def agit(self) -> bool:
        """Un geste navigateur qui CHANGE la page (clic, saisie, touche, script qui agit)."""
        if not self.nom.startswith("mcp__"):
            return False
        if self.court() == "evaluate_script":
            return bool(_SCRIPT_QUI_AGIT_RE.search(self.texte()))
        return bool(_INTERACTION_RE.search(self.court()))

    def vert(self) -> bool:
        """Réussi = exécuté, sans marqueur d'échec. Une sortie VIDE n'est pas un échec : une
        commande silencieuse (`bash run.sh > log`) a réussi. Essai du 2026-09-25 : refus n° 4
        de la racine, « a échoué () » sur une recette 20/20, 7/7, 5/5."""
        if self.resultat is None:
            return False
        res = self.resultat.strip()
        return not (res.startswith(_REFUS) or _ECHEC_RE.search(res)
                    or _LIGNE_ECHEC_RE.search(res) or _bilan_incomplet(res))

    def execute(self) -> bool:
        """L'appel a-t-il rendu un résultat ? (Non : il n'a pas encore tourné.)"""
        return self.resultat is not None

    def navigateur(self) -> bool:
        if self.nom.startswith("mcp__"):
            return bool(_OUTIL_NAVIGATEUR_RE.search(self.nom))
        if self.nom in _NON_EXECUTANTS:
            return False
        return bool(_NAVIGATEUR_RE.search(self.texte())) or _script_navigateur(self.texte())


def _bilan_incomplet(sortie: str) -> bool:
    """« FIGURES: 6/7 OK », « 19/20 passed » : un bilan k/n avec k < n."""
    return any(int(k) < int(n) for k, n in _BILAN_RE.findall(sortie))


def _normaliser(texte: str) -> str:
    return " ".join(str(texte).replace("`", " ").split())


# `( python3 server.py … & )`, `node x.js &` : le sous-shell et la mise en fond ne changent
# pas CE qui a été lancé. Essai du 2026-09-25, refus n° 3 : « python3 server.py --port 8798 … & »
# cité, « (python3 server.py … &) » lancé — jugé « jamais exécuté ».
_SOUS_SHELL_RE = re.compile(r"^\(+\s*|\s*&?\s*\)+$|\s*&$")


def _commande_nue(morceau: str) -> str:
    """La commande elle-même : sans redirection, sous-shell, mise en fond ni enveloppe
    (`timeout 60`, `HOME=… BASE=…`)."""
    commande = _normaliser(_REDIRECTION_RE.sub("", morceau.strip()))
    commande = _SOUS_SHELL_RE.sub("", _SOUS_SHELL_RE.sub("", commande)).strip()
    return _ENVELOPPE_RE.sub("", _INVITE_RE.sub("", commande))


def _jetons(commande: str) -> list[str]:
    """Les mots d'une commande, guillemets ôtés (`<<'EOF'` ≡ `<<EOF`, `"C:\\a b\\x.exe"` reste
    un seul mot), variables d'environnement de tête ignorées."""
    jetons = [re.sub(r"[\"']", "", j) for j in re.findall(r"\"[^\"]*\"|'[^']*'|\S+", commande)]
    while jetons and (_AFFECTATION_RE.match(jetons[0]) or jetons[0] in {"&", "(", "{"}):
        jetons.pop(0)
    return jetons


def _executable(jeton: str) -> str:
    """`C:\\Python312\\python.exe`, `/usr/bin/python3.12`, `py` → `python` ; `npx.cmd` → `npx`."""
    nom = _SUFFIXE_EXE_RE.sub("", jeton.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower())
    return "python" if _PYTHON_RE.match(nom) else nom


def _chemin(jeton: str) -> str:
    return jeton.replace("\\", "/").lower()


def _forme(commande: str) -> tuple[str, list[str], str]:
    """(exécutable normalisé, arguments normalisés sans `$…`, premier chemin de script)."""
    jetons = _jetons(commande)
    if not jetons:
        return "", [], ""
    arguments = []
    for jeton in jetons[1:]:
        if jeton.lower() in _PROSE:
            break
        if "$" not in jeton:
            arguments.append(_chemin(jeton))
    script = next((a for a in arguments if not a.startswith("-") and "://" not in a
                   and _EXTENSION_SCRIPT_RE.search(a)), "")
    return _executable(jetons[0]), arguments, script


def _meme_script(cite: str, lance: str) -> bool:
    """Même script, au répertoire près : `smoke.js` ≡ `/tmp/pe-pw/smoke.js` ≡ `C:\\pe\\smoke.js`."""
    return cite == lance or lance.endswith("/" + cite) or cite.endswith("/" + lance)


# Un script lancé par la commande (`bash all.sh`, `node smoke.js`) : c'est SON contenu qui dit
# s'il pilote un navigateur. Essai du 2026-09-25 : `bash /tmp/pe-pw/all.sh 8802` lançait
# `node smoke.js` (Playwright, 20/20) — « aucun parcours n'est prouvé par un navigateur ».
_SCRIPT_RE = re.compile(r"(?:^|[\s;&|(])([^\s;&|()'\"]+\.(?:sh|bash|js|mjs|cjs|ts|py))(?=[\s;&|)]|$)")
_SCRIPT_MAX_OCTETS = 200_000


def _script_navigateur(commande: str, profondeur: int = 2) -> bool:
    """Un des scripts que lance `commande` pilote-t-il un navigateur (un niveau d'imbrication
    suivi pour un script shell qui en lance d'autres) ?"""
    repertoires = _CD_RE.findall(commande or "")
    for chemin in _SCRIPT_RE.findall(commande or ""):
        contenu = next((c for c in map(_lire_script, _candidats(chemin, repertoires))
                        if c is not None), None)
        if contenu is None:
            continue
        if _NAVIGATEUR_RE.search(contenu):
            return True
        if profondeur > 1 and _script_navigateur(contenu, profondeur - 1):
            return True
    return False


# `cd /tmp/pe-pw && node smoke.js`, `Set-Location C:\pe ; node .\smoke.js` : un script relatif
# se lit dans le répertoire où la commande s'est placée (essai du 2026-09-25, 6bafe9cd t114).
_CD_RE = re.compile(r"(?:^|[;&|(\s])(?:cd|pushd|Set-Location|sl)\s+(?:-Path\s+)?[\"']?"
                    r"([^\s;&|\"')]+)", re.I)


def _candidats(chemin: str, repertoires: list[str]) -> list[str]:
    """Le chemin tel quel, puis relatif à chaque `cd` de la commande (le dernier d'abord)."""
    if chemin.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", chemin):
        return [chemin]
    sep = "\\" if any("\\" in r for r in repertoires) else "/"
    relatif = re.sub(r"^\.[\\/]", "", chemin)
    return [chemin] + [r.rstrip("\\/") + sep + relatif for r in reversed(repertoires)]


def _lire_script(chemin: str) -> str | None:
    """Le contenu d'un script lancé par une recette (None : absent, illisible ou trop gros)."""
    from pathlib import Path
    fichier = Path(chemin)
    try:
        if not fichier.is_file() or fichier.stat().st_size > _SCRIPT_MAX_OCTETS:
            return None
        return fichier.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def journal(messages: list) -> list[Appel]:
    """Les appels d'outils de la session, dans l'ordre, avec leur résultat réel."""
    resultats = {m.get("tool_call_id"): m.get("content") for m in messages
                 if m.get("role") == "tool"}
    appels: list[Appel] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for tc in message.get("tool_calls") or []:
            entree = tc.get("input") if isinstance(tc.get("input"), dict) else {}
            res = resultats.get(tc.get("id"))
            appels.append(Appel(len(appels), str(tc.get("name") or ""), entree,
                                res if isinstance(res, str) else None, str(tc.get("id") or "")))
    return appels


def _ecriture_interface(appel: Appel) -> bool:
    if appel.nom not in _ECRITURES or appel.entree.get("temp") or not appel.vert():
        return False
    chemin = str(appel.entree.get("file_path") or appel.entree.get("notebook_path") or "")
    chemin = chemin.replace("\\", "/")
    suffixe = chemin.rsplit(".", 1)[-1].lower() if "." in chemin else ""
    return (suffixe in _SUFFIXES_INTERFACE and not _FICHIER_DE_TEST_RE.search(chemin)
            and not _hors_depot(chemin))


# Répertoires temporaires (Linux, macOS, Windows) et brouillons du harnais : un script
# Playwright écrit là est un OUTIL de vérification, pas l'interface livrée. Essai du 2026-09-25
# (6bafe9cd t114) : `/tmp/pe-pw/diag.js` retouché après la recette → « rejoue les parcours ».
_HORS_DEPOT_RE = re.compile(
    r"^(/tmp/|/var/tmp/|/private/tmp/|/private/var/folders/|/var/folders/|/dev/shm/)|"
    r"/bouzecode_scratch/|/scratchpad/|"
    r"^[a-z]:/(users/[^/]+/appdata/local/temp|windows/temp|temp|tmp)/|"
    r"^(%temp%|\$env:temp|~/appdata/local/temp)/", re.I)


def _ecriture_hors_depot_racines() -> tuple[str, ...]:
    """Le répertoire temporaire du système, s'il n'est pas déjà couvert par le motif."""
    racine = tempfile.gettempdir().replace("\\", "/").rstrip("/").lower()
    return (racine + "/",) if racine else ()


def _racines_depot() -> tuple[str, ...]:
    """Le répertoire de travail de l'agent (son dépôt ou son worktree) : ce qui s'y écrit est
    le livrable, même s'il vit sous /tmp."""
    import os
    try:
        from ..core.dossier_agent import courant  # sous-agent isole : SON dossier
        return (courant().replace("\\", "/").rstrip("/").lower() + "/",)
    except OSError:
        return ()


def _hors_depot(chemin: str) -> bool:
    """Écrit dans un répertoire temporaire, hors du répertoire de travail de l'agent ?"""
    chemin_bas = chemin.lower()
    if any(chemin_bas.startswith(racine) for racine in _racines_depot()):
        return False
    return bool(_HORS_DEPOT_RE.search(chemin_bas)) or any(
        chemin_bas.startswith(racine) for racine in _ecriture_hors_depot_racines())


def demande_d_origine(messages: list) -> str:
    return next((m["content"] for m in messages
                 if m.get("role") == "user" and isinstance(m.get("content"), str)), "")


def tache_d_interface(messages: list, appels: list[Appel], delegue: bool = False) -> bool:
    """Condition d'activation : une interface a été écrite, ou demandée ET du code écrit.

    Un agent DÉLÉGUÉ (lancé par un autre agent) n'est concerné que s'il écrit lui-même un
    fichier d'interface : le brief qu'un parent rédige évoque volontiers « l'UI » qu'il garde
    pour lui. Essai du 2026-09-25 : l'enfant 625883f1 (scraper seul, aucun fichier front) a
    subi trois refus et une clôture forcée « NON prouvés » parce que son brief disait
    « l'UI affichera « réponse à vérifier » »."""
    if any(_ecriture_interface(a) for a in appels):
        return True
    if delegue:
        return False
    ecrit = any(a.nom in _ECRITURES and not a.entree.get("temp") for a in appels)
    return ecrit and bool(_DEMANDE_UI_RE.search(demande_d_origine(messages)))


def _cite(cible: str, appel: Appel) -> bool:
    """La preuve désigne-t-elle cet appel ? Par ce qu'il a FAIT : sa commande (citée en
    entier ou en partie), ou son outil ET ses arguments. Le nom seul ne désigne qu'un outil
    navigateur (« click uid=1_4 puis take_snapshot → '2' », prose réelle d'un modèle) : pour
    un Bash ou un RunPythonTest, le nom désigne n'importe lequel des appels de la session."""
    texte, arguments = appel.texte(), appel.arguments()
    if (len(cible) >= 8 and cible in texte) or (len(texte) >= 8 and texte in cible):
        return True
    if appel.nom.startswith("mcp__"):
        return appel.nom in cible or (len(appel.court()) >= 5 and _nomme(cible, appel.court()))
    return appel.nom in cible and _arguments_cites(cible, appel, arguments)


def _arguments_cites(cible: str, appel: Appel, arguments: str) -> bool:
    return (bool(arguments) and arguments in cible) or _element_cite(cible, appel)


def _element_cite(cible: str, appel: Appel) -> bool:
    """Un élément d'une liste d'arguments (un des `paths` d'ImageQuestion) est nommé dans la
    preuve, en entier ou par son nom de fichier."""
    for valeur in appel.entree.values():
        for element in valeur if isinstance(valeur, list) else []:
            element = str(element)
            nom = element.replace("\\", "/").rsplit("/", 1)[-1]
            if len(nom) >= 5 and (element in cible or nom in cible):
                return True
    return False


def _commandes_citees(preuve: str) -> list[str]:
    """Les commandes shell que la preuve affirme avoir lancées (prose et résultats ôtés)."""
    commandes = []
    for morceau in _COUPE_PREUVE_RE.split(preuve):
        # « Bash hauteur (1240, 340) » : le NOM de l'outil, pas le shell (625883f1 t79).
        commande = re.sub(r"^Bash\s+", "", _commande_nue(morceau))
        if _est_commande(commande):
            commandes.append(commande)
    return commandes


def _est_commande(commande: str) -> bool:
    """Une commande shell connue, avec au moins un argument ; pytest exclu (RunPythonTest le
    lance sans que la commande apparaisse). Un CHEMIN qui contient « pytest »
    (`/tmp/pytest-of-x/…`) n'est pas pytest."""
    jetons = _jetons(commande)
    if len(jetons) < 2:
        return False
    exe = _executable(jetons[0])
    if exe in {"pytest", "py.test"} or (exe == "python" and jetons[1:3] == ["-m", "pytest"]):
        return False
    return exe in _EXECUTABLES or jetons[0].startswith(("./", ".\\"))


def _execution_de(commande: str, appels: list[Appel], preuve: str = "") -> Appel | None:
    """L'appel shell qui a lancé cette commande (citée en entier, ou suivie d'arguments ou de
    prose : `python3 x.py` désigne `python3 x.py --out d.json`). Le DERNIER, sauf si un
    autre a rendu une sortie que la preuve cite (≥ 20 caractères) : une citation vague
    (`python3 - <<EOF`) désigne alors l'exécution dont elle recopie le résultat."""
    candidats = [a for a in appels
                 if any(_meme_commande(commande, segment) for segment in a.segments())]
    if not candidats:
        return None
    extraits = _extraits(preuve)
    cites = [a for a in candidats if _sortie_citee(extraits, a)]
    return (cites or candidats)[-1]


def _meme_commande(citee: str, segment: str) -> bool:
    """Même exécutable (forme normalisée) ET : même premier script (`python3 server.py …` pour
    `(python3 server.py --port 8798 … &)`), ou, sans script, chaque mot hors option de la
    citation — coupée à la première prose (« curl -s … sur http://… ») — figure dans la
    commande lancée. Les mots contenant `$` ne se comparent pas (`"$B/x"`, `$env:X`)."""
    exe_cite, args_cites, script_cite = _forme(citee)
    exe_lance, args_lances, script_lance = _forme(segment)
    if not exe_cite or exe_cite != exe_lance or not (args_lances or script_lance):
        return False
    if script_cite:
        return bool(script_lance) and _meme_script(script_cite, script_lance)
    return all(_mot_lance(mot, args_lances) for mot in args_cites if not mot.startswith("-"))


def _mot_lance(mot: str, args_lances: list[str]) -> bool:
    """Le mot figure dans la commande lancée, au besoin suivi d'un échappement
    (`'%{http_code}'` cité, `"%{http_code}\\n"` lancé)."""
    return any(arg == mot or (len(mot) >= 4 and arg.startswith(mot)) for arg in args_lances)


def _appel_de_preuve(preuve: str, appels: list[Appel]) -> Appel | None:
    """Le DERNIER appel exécutant que la preuve désigne (commande ou outil navigateur) ; à
    défaut, le dernier dont la preuve recopie un extrait (≥ 20 caractères) de la sortie ou
    de la description : « script d'intégrité : 2024-e-24: answer_text=None conf=0.0 »."""
    cible = _normaliser(preuve)
    if len(cible) < 3:
        return None
    executants = [a for a in appels
                  if a.nom not in _NON_EXECUTANTS and not _TRIVIALE_RE.match(a.texte())]
    for appel in reversed(executants):
        if _cite(cible, appel):
            return appel
    extraits = _extraits(preuve)
    return next((a for a in reversed(executants) if _sortie_citee(extraits, a)), None)


_EXTRAIT_MIN = 20
_GUILLEMETS_RE = re.compile(r"«\s*([^»]+?)\s*»|\"([^\"]+)\"|“([^”]+)”|`([^`]+)`")


def _extraits(preuve: str) -> list[str]:
    """Les morceaux de la preuve assez longs pour désigner une sortie : les passages entre
    guillemets et les morceaux entre séparateurs (→, ;, « : »…), espaces normalisés."""
    morceaux = [next(g for g in groupes if g) for groupes in _GUILLEMETS_RE.findall(preuve)]
    morceaux += _COUPE_PREUVE_RE.split(preuve)
    vus = []
    for morceau in morceaux:
        morceau = " ".join(morceau.split()).strip(" .,:")
        if len(morceau) >= _EXTRAIT_MIN and morceau not in vus:
            vus.append(morceau)
    return vus


def _sortie_citee(extraits: list[str], appel: Appel) -> bool:
    """La preuve recopie-t-elle un morceau de ce que l'appel a rendu (ou de sa description) ?"""
    if not extraits or not appel.execute():
        return False
    sortie = " ".join((appel.resultat or "").split())
    description = " ".join(str(appel.entree.get("description") or "").split())
    return any(e in sortie or (description and e in description) for e in extraits)


def _liste(parcours: object) -> list:
    """Les parcours déclarés ([] si absents) ; tolère une liste sérialisée en chaîne JSON."""
    if isinstance(parcours, str) and parcours.strip().startswith("["):
        try:
            parcours = json.loads(parcours)
        except ValueError:
            return []
    return parcours if isinstance(parcours, list) else []


def _commandes_jamais_lancees(preuve: str, appels: list[Appel]) -> tuple[str, Appel | None]:
    """(commande citée mais jamais lancée, sinon "" ; dernier appel qui en exécute une)."""
    execution = None
    for commande in _commandes_citees(preuve):
        appel = _execution_de(commande, appels, preuve)
        if appel is None:
            return commande, None
        execution = appel if execution is None or appel.rang > execution.rang else execution
    return "", execution


def _action_non_jouee(preuve: str, appels: list[Appel], designes: tuple = ()) -> bool:
    """Vrai si la preuve ne cite (ni ne référence, `designes`) AUCUN geste navigateur réussi
    suivi d'un constat réussi."""
    cible = _normaliser(preuve)
    gestes = [a.rang for a in appels if a.agit() and a.vert()
              and (a in designes or a.nom in cible or _nomme(cible, a.court()))]
    constats = [a.rang for a in appels if a.constate()]
    return not any(constat > geste for geste in gestes for constat in constats)


def _appel_prouvant(preuve: str, appels: list[Appel]) -> tuple[Appel | None, str]:
    """(l'appel que la preuve désigne, "") ou (None, pourquoi elle ne désigne rien de réel)."""
    absente, execution = _commandes_jamais_lancees(preuve, appels)
    if absente:
        return None, (f"la commande « {absente[:100]} » citée en preuve n'a JAMAIS été "
                      "exécutée dans cette session — lance-la, puis cite-la")
    appel = execution or _appel_de_preuve(preuve, appels)
    if appel is None:
        return None, Manque(f"la preuve « {preuve[:120]} » ne correspond à AUCUN appel "
                            "exécuté dans cette session (preuve non reconnue) — désigne l'appel "
                            "qui prouve par `appel` (son tool_call_alias), ou cite la commande "
                            "exacte (ou l'outil navigateur)", "format")
    return appel, ""


def _probleme_d_execution(appel: Appel, preuve: str, exigence: str,
                          appels: list[Appel], gestes_cites: str = "") -> str:
    """L'appel désigné a-t-il réussi, et montre-t-il l'ACTION quand l'exigence agit ?
    `gestes_cites` : le texte où chercher le geste (parcours + preuve, et pour une exigence
    de persistance, tous les parcours déclarés)."""
    if not appel.execute():
        return (f"« {preuve[:80]} » n'avait pas encore rendu de résultat au moment de la "
                "clôture : place FinalAnswer APRÈS l'appel qui prouve")
    if not appel.vert():
        extrait = " ".join((appel.resultat or "").split())[-160:]
        return f"la dernière exécution de « {preuve[:80]} » a échoué ({extrait})"
    if (appel.nom.startswith("mcp__") and _EXIGENCE_ACTION_RE.search(exigence)
            and _action_non_jouee(gestes_cites or preuve, appels)):
        return ("cette exigence AGIT, mais la preuve navigateur ne fait que regarder la page "
                "— joue l'action (click, fill, press_key, evaluate_script qui modifie…) PUIS "
                "constate son effet (take_snapshot, evaluate_script), et cite ces appels")
    return ""


def _verifier(i: int, item: object, appels: list[Appel],
              tous: list | None = None) -> tuple[str, Appel | None]:
    """(problème, appel qui prouve) pour UN parcours déclaré (`tous` : les parcours déclarés,
    où une exigence de persistance peut retrouver le geste joué). Avec `appel` (référence),
    l'appel est résolu directement ; sinon la `preuve` en texte libre est recoupée."""
    item = item if isinstance(item, dict) else {}
    references = _references(item.get("appel"))
    requis = [c for c in CHAMPS if not (c == "preuve" and references)]
    vides = [c for c in requis if not str(item.get(c) or "").strip()]
    if vides:
        return Manque(f"parcours_verifies[{i}] : champ(s) vide(s) {', '.join(vides)}",
                      "format"), None
    etiquette = f"parcours_verifies[{i}] ({str(item['exigence'])[:60]})"
    if references:
        probleme, appel = _verifier_references(references, item, appels, tous or [item])
        return (_prefixe(etiquette, probleme), None) if probleme else ("", appel)
    preuve = str(item["preuve"])
    appel, probleme = _appel_prouvant(preuve, appels)
    if appel is not None:
        probleme = _probleme_d_execution(appel, preuve, str(item["exigence"]), appels,
                                         _gestes_cites(item, tous or [item]))
    return (_prefixe(etiquette, probleme), None) if probleme else ("", appel)


def _references(valeur: object) -> list[str]:
    """`appel` : un alias/id, une liste (éventuellement sérialisée en JSON), ou plusieurs
    séparés par des virgules."""
    if isinstance(valeur, str) and valeur.strip().startswith("["):
        try:
            valeur = json.loads(valeur)
        except ValueError:
            valeur = valeur.strip().strip("[]")
    if isinstance(valeur, str):
        valeur = valeur.split(",")
    if not isinstance(valeur, list):
        return []
    return [str(v).strip().strip("`'\"") for v in valeur if str(v).strip()]


def _verifier_references(references: list[str], item: dict, appels: list[Appel],
                         tous: list) -> tuple[str, Appel | None]:
    """(problème, appel qui prouve) quand le parcours désigne ses appels par référence : ils
    existent, exécutent quelque chose, ont réussi ; un appel navigateur a joué APRÈS la
    dernière retouche d'interface ; le geste est là quand l'exigence agit."""
    designes = []
    for reference in references:
        appel = next((a for a in reversed(appels) if a.designe_par(reference)), None)
        if appel is None:
            return Manque(f"`appel` « {reference[:60]} » ne désigne aucun appel de cette "
                          "session — donne l'alias (tool_call_alias) ou l'id d'un appel "
                          "réellement exécuté", "format"), None
        if appel.nom in _NON_EXECUTANTS or _TRIVIALE_RE.match(appel.texte()):
            return Manque(f"`appel` « {reference[:60]} » est un {appel.court()} : il "
                          "n'exécute rien, il ne prouve aucun parcours", "format"), None
        if not appel.execute():
            return (f"`appel` « {reference[:60]} » n'avait pas encore rendu de résultat au "
                    "moment de la clôture : place FinalAnswer APRÈS l'appel qui prouve"), None
        if not appel.vert():
            extrait = " ".join((appel.resultat or "").split())[-160:]
            return f"la dernière exécution de `appel` « {reference[:60]} » a échoué ({extrait})", None
        designes.append(appel)
    derniere_ecriture = max((a.rang for a in appels if _ecriture_interface(a)), default=-1)
    perimes = [a for a in designes if a.navigateur() and a.rang < derniere_ecriture]
    if perimes and not any(a.navigateur() and a.rang > derniere_ecriture for a in designes):
        return ("un fichier d'interface a été modifié APRÈS l'appel navigateur désigné : "
                "rejoue le parcours sur le code final et désigne ce nouvel appel"), None
    exigence = str(item.get("exigence") or "")
    if (any(a.nom.startswith("mcp__") for a in designes) and _EXIGENCE_ACTION_RE.search(exigence)
            and _action_non_jouee(_gestes_cites(item, tous), appels, tuple(designes))):
        return ("cette exigence AGIT, mais les appels désignés ne font que regarder la page "
                "— joue l'action (click, fill, press_key, evaluate_script qui modifie…) PUIS "
                "constate son effet, et désigne ces appels"), None
    navigateurs = [a for a in designes if a.navigateur()]
    return "", (navigateurs or designes)[-1]


def _gestes_cites(item: dict, tous: list) -> str:
    """Où chercher le geste d'une exigence qui agit : son parcours et sa preuve (« cliquer
    l'étoile 4 » décrit dans le parcours, 6bafe9cd t63) ; pour une exigence de persistance,
    aussi ceux des autres parcours déclarés (le geste y est prouvé, celui-ci recharge)."""
    sources = tous if _PERSISTANCE_RE.search(str(item.get("exigence") or "")) else [item]
    return " ".join(str(p.get(c) or "") for p in sources if isinstance(p, dict)
                    for c in ("parcours", "preuve"))


def _navigateur_a_jour(prouves: list, appels: list[Appel]) -> str:
    """Au moins un parcours passe par un navigateur, APRÈS la dernière retouche d'interface."""
    navigateurs = [a.rang for a in prouves if a is not None and a.navigateur()]
    if not navigateurs:
        return ("aucun parcours n'est prouvé par un navigateur (Playwright, chrome-devtools…) : "
                "une interface se vérifie en la faisant tourner")
    derniere_ecriture = max((a.rang for a in appels if _ecriture_interface(a)), default=-1)
    if max(navigateurs) < derniere_ecriture:
        return ("un fichier d'interface a été modifié APRÈS ton dernier parcours navigateur : "
                "rejoue les parcours sur le code final")
    return ""


def manques(parcours: object, messages: list, delegue: bool = False) -> list[str]:
    """Ce qui manque pour clore une tâche d'interface ([] = rien, ou tâche non concernée)."""
    appels = journal(messages)
    if not tache_d_interface(messages, appels, delegue):
        return []
    parcours = _liste(parcours)
    if not parcours:
        return ["parcours_verifies : absent ou vide — tâche d'interface (fichiers front écrits "
                "ou interface demandée)"]
    verifies = [_verifier(i, item, appels, parcours) for i, item in enumerate(parcours)]
    problemes = [p for p, _ in verifies if p]
    return problemes or [p for p in [_navigateur_a_jour([a for _, a in verifies], appels)] if p]


# Un succès FORCÉ dans une recette : le code de sortie ne dit plus rien.
_SUCCES_FORCE_RE = re.compile(r"\bexit\s+0\b|\|\|\s*true\b|process\.exit\(\s*0\s*\)|"
                              r"sys\.exit\(\s*0\s*\)|exit\s*/b\s+0\b|\$LASTEXITCODE\s*=\s*0", re.I)
_REFUS_DE_CLOTURE = "CLÔTURE REFUSÉE"


def signalements(parcours: object, messages: list, delegue: bool = False) -> list[str]:
    """Ce que l'utilisateur doit savoir d'une clôture ACCEPTÉE, sans la bloquer : une recette
    citée en preuve modifiée après un refus pour forcer un succès (`exit 0`, `|| true`…).

    Essai du 2026-09-25 (6bafe9cd t140 → t142) : après le 4e refus, `exit 0` ajouté en fin de
    `/tmp/pe-pw/all.sh` (légitime ici : `kill` + `wait` rendaient 143). La sortie reste jugée
    (lignes FAIL, bilans k/n), mais le code de sortie ne prouve plus rien : on le dit."""
    appels = journal(messages)
    if not tache_d_interface(messages, appels, delegue):
        return []
    refus = [a.rang for a in appels if a.nom == "FinalAnswer"
             and _REFUS_DE_CLOTURE in str(a.resultat or "")[:200]]
    if not refus:
        return []
    parcours = _liste(parcours)
    notes: list[str] = []
    for i, item in enumerate(parcours):
        _, appel = _verifier(i, item, appels, parcours)
        for chemin in _recettes_forcees(appel, appels, refus[0]) if appel else []:
            note = (f"la recette « {chemin} », citée en preuve, a été modifiée après un refus de "
                    "clôture pour forcer un succès (exit 0, || true…) : son code de sortie ne "
                    "prouve plus rien, seule sa sortie a été jugée")
            if note not in notes:
                notes.append(note)
    return notes


def _recettes_forcees(appel: Appel, appels: list[Appel], premier_refus: int) -> list[str]:
    """Les scripts lancés par `appel` qu'une écriture, entre le premier refus et `appel`, a
    modifiés pour y AJOUTER un succès forcé."""
    commande = str(appel.entree.get("command") or "")
    scripts = [_chemin(s) for s in _SCRIPT_RE.findall(commande)]
    forcees = []
    for ecriture in appels[premier_refus:appel.rang]:
        if ecriture.nom not in _ECRITURES:
            continue
        chemin = str(ecriture.entree.get("file_path") or "")
        if not any(_meme_script(s, _chemin(chemin)) for s in scripts):
            continue
        avant = str(ecriture.entree.get("old_string") or "") + " " + next(
            (str(a.entree.get("content") or "") for a in reversed(appels[:ecriture.rang])
             if a.nom == "Write" and a.entree.get("file_path") == chemin), "")
        apres = " ".join(str(ecriture.entree.get(c) or "")
                         for c in ("new_string", "content", "edits"))
        if _SUCCES_FORCE_RE.search(apres) and not _SUCCES_FORCE_RE.search(avant):
            forcees.append(chemin)
    return forcees


def reels(problemes: list[str]) -> list[str]:
    """Les problèmes qui disent un VRAI manque (pas un simple défaut de format de preuve)."""
    return [p for p in problemes if getattr(p, "nature", "echec") != "format"]


def message_de_refus(problemes: list[str]) -> str:
    echecs = reels(problemes)
    formats = [p for p in problemes if p not in echecs]
    sections = []
    if formats:
        sections.append("preuves NON RECONNUES (format : l'appel a peut-être bien eu lieu, "
                        "désigne-le par `appel`) —\n- " + "\n- ".join(formats))
    if echecs:
        sections.append("parcours utilisateur non prouvés —\n- " + "\n- ".join(echecs))
    return (
        "\n".join(sections) + "\n"
        "Pour CHAQUE exigence de la demande, joue le parcours comme un utilisateur "
        "(ex. afficher → répondre → éditer → enregistrer → recharger → relire) avec un test "
        "navigateur ou E2E, puis déclare-le dans `parcours_verifies` : "
        "{exigence, parcours, appel, preuve} où `appel` = le tool_call_alias (ou l'id) de "
        "l'appel exécuté, vert, qui le prouve (une liste pour geste + constat) et `preuve` = "
        "ce qu'il montre. Les appels des tours précédents comptent : ne rejoue que ce qui a "
        "échoué ou dont le code a changé depuis. Une fois les preuves rendues, rappelle "
        "FinalAnswer SEUL, dans un lot à part."
    )
