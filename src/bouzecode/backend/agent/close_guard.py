# [desc] Décide si un tour SUPPORTE sa propre clôture : refus d'outils, sous-agent en fond. [/desc]
"""Ce qui autorise une session à se fermer — et ce qui le lui refuse.

Extrait de `loop_turn.py`, qui mêlait cette décision au streaming et à l'exécution
d'outils. Elle vit seule parce qu'elle a sa propre règle, son propre budget de refus et
son propre vocabulaire ; l'y noyer rendait invisible le fait que DEUX chemins très
différents aboutissent au même verdict.
"""
from __future__ import annotations

import re

# Une session ne se ferme que sur un acte de clôture que le tour SUPPORTE réellement.
# Deux façons pour un tour de ne pas supporter sa propre clôture, une seule règle :
#   - la « clôture » n'est que de la prose à côté de la comptabilité
#     (Methodology/Snippet) -> aucun acte ;
#   - la clôture EST explicite (FinalAnswer) mais un outil du même lot n'a jamais
#     tourné -> la réponse s'appuie sur quelque chose qui n'a pas eu lieu.
# Les deux dépensent un tour à dire au modèle exactement pourquoi, sous le budget
# PARTAGÉ ctx.final_answer_nudges (« combien de fois le harnais a-t-il refusé de
# clôturer pour cet agent »), puis ferment avec un close_reason qui garde l'anomalie.
MAX_CLOSE_REFUSALS = 3

# Comptabilité pure : le modèle ÉCRIT dedans, il n'en attend aucune donnée. Leur
# présence à côté d'une clôture ne prouve donc rien sur ce qu'il a lu.
META_ONLY_TOOLS = {"Methodology", "Snippet"}

# Refus/abandons AU NIVEAU DU HARNAIS — l'outil n'a PAS fait son travail. Comparés
# ANCRÉS EN DÉBUT de résultat : c'est exactement ce qui sépare « le harnais a refusé
# l'appel » de « l'outil a tourné et sa sortie mentionne une erreur ». Un run pytest qui
# rapporte des tests rouges, un log de build, un grep qui tombe sur le mot Error — ce
# sont des appels RÉUSSIS rapportant un vrai résultat, et ils ne doivent jamais bloquer
# une clôture, sans quoi l'agent ne pourrait jamais livrer « les tests échouent parce que
# X ». Le vocabulaire ci-dessous est celui du harnais lui-même, issu de
# tool_registry.execute_tool et des chemins de refus de la boucle ; la carte des gardes
# est docs/investigations/refused_tool_attempts.md.
_TOOL_REFUSAL_PREFIXES = (
    "ERROR parsing your tool call XML:",
    "Error executing ",
    "Error: ",
    "Denied: ",
    "Skipped: a dependency was denied",
    "Cancelled: ",
    "[Plan mode]",
    "BLOCKED:",
)


def _refused_tool_results(tool_calls: list[dict], results: dict,
                          prefixes_de_l_agent: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """(nom d'outil, première ligne du refus) pour chaque appel refusé par le harnais.

    FinalAnswer n'est PAS exempté, et c'est tout l'intérêt : une réponse vide est
    arrêtée par le garde de paramètre requis du registre, qui rend « Error: ... » SANS
    jamais exécuter _final_answer — donc le drapeau `_final_answer_refused` de
    _final_answer n'était jamais posé et la session se fermait sur un livrable vide. Une
    seule règle, aucune exception : un acte de clôture que le harnais a refusé n'est pas
    une clôture.

    `prefixes_de_l_agent` (config["close_failure_prefixes"]) : la façon dont les outils
    de l'agent HÔTE signent un échec — Focus rend « Erreur : … ». Par la config et non
    dans la liste ci-dessus : ailleurs, une sortie réelle peut commencer par « Erreur »
    (un Bash sous Windows en français) et c'est alors une donnée, pas un refus.
    """
    prefixes = _TOOL_REFUSAL_PREFIXES + tuple(prefixes_de_l_agent)
    refused = []
    for tc in tool_calls:
        raw = results.get(tc["id"])
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if text.startswith(prefixes):
            refused.append((tc["name"], text.splitlines()[0]))
    return refused


def deja_executes(noms: list[str]) -> str:
    """La phrase qui empêche de REJOUER un lot : ces appels ont eu lieu, leurs effets restent.

    Assistant du Bureau, 2026-09-24 : `Taches(preciser)` et FinalAnswer dans le même lot,
    clôture refusée, et le modèle a renvoyé la précision — le brief la portait deux fois.
    Un refus de clôture ne défait rien : le dire explicitement coûte une ligne."""
    if not noms:
        return ""
    return (f"Déjà EXÉCUTÉS dans ce lot, effets acquis : {', '.join(dict.fromkeys(noms))}. "
            "Ne les rejoue PAS (une écriture, un envoi ou une précision refaits seraient "
            "doublés).\n")


def _close_over_failed_tool_nudge(refused: list[tuple[str, str]],
                                  executes: list[str] = ()) -> str:
    """Ce que lit le modèle quand sa FinalAnswer voyageait avec un outil refusé."""
    details = "\n".join(f"- {name} : {err}" for name, err in refused)
    return (
        "(System Automated Event): ta clôture n'a PAS été acceptée. Dans le tour "
        "où tu as appelé FinalAnswer, un appel d'outil n'a pas fait son travail :\n"
        f"{details}\n"
        f"{deja_executes(list(executes))}"
        "Ta réponse finale s'appuie donc sur un résultat que tu n'as jamais obtenu. "
        "Corrige la cause (ré-émets l'appel correctement, ou utilise un outil dont "
        "tu disposes), PUIS rappelle FinalAnswer (sans `answer` si ta réponse reste juste "
        ": le harnais reprend le texte de ta clôture refusée). Si l'échec est irrémédiable, "
        "rappelle FinalAnswer en disant EXPLICITEMENT ce qui n'a pas pu être "
        "vérifié — ne présente jamais comme fait ce que l'outil n'a pas confirmé."
    )


def tools_answered_blind(tool_calls: list[dict], ends_turn_names: set[str]) -> list[str]:
    """Les outils du lot dont le modèle ne peut PAS avoir lu le résultat.

    Un résultat n'est rendu au modèle qu'au tour SUIVANT. Un acte de clôture émis
    dans le même lot qu'un outil producteur de données ferme donc la session avant
    que ce résultat n'ait jamais été lu : la réponse ne peut pas s'appuyer dessus,
    même si l'outil a parfaitement fonctionné.

    C'est la deuxième moitié de `_refused_tool_results` — là, l'outil n'avait pas
    tourné ; ici, il a tourné et personne n'a lu sa sortie. Autopsie de la
    conversation Focus 6e67be34 (2026-08-18) : 16 appels et la clôture dans une
    SEULE complétion, le modèle ayant écrit lui-même les résultats qu'il attendait.
    Les vrais — dont `relation "f_train_jour" does not exist` — n'ont jamais été lus.

    Liste TOUT ce qui a tourné (c'est aussi la liste « déjà exécutés, ne rejoue pas ») ;
    `appels_a_relire` en retire le ménage sans enjeu de lecture.
    """
    return [
        tc["name"] for tc in tool_calls
        if tc["name"] not in META_ONLY_TOOLS and tc["name"] not in ends_turn_names
    ]


# Ménage de fin de session : des appels dont le résultat, QUAND IL DIT CE QU'ON ATTEND,
# ne peut ni confirmer ni contredire une réponse. Relevé des sessions opus-5 du poste
# Windows (09/09 → 25/09) : 18 des 34 refus « même lot » portaient sur eux seuls, et le
# modèle y perdait un tour, souvent deux (un `git worktree list` pour « vérifier » un
# rangement dont le résultat disait déjà « Rangé »). Chaque entrée exige le résultat de
# réussite : un rangement REFUSÉ (« pas intégré ») contredit « intégré dans develop » et
# doit être lu. Hors liste, exprès :
#   - `Environment(integrate)` : un merge en conflit contredit la réponse ;
#   - `Environment(status)`, Bash qui ÉCRIT quelque chose (un `rm` suivi d'un
#     `git status` en 2fe8f867, le sha d'un commit, des chiffres), Write/Edit : ce sont
#     des données que la réponse peut citer — et c'est là que le modèle les invente
#     (Focus 6e67be34 : 8 chiffres livrés, aucun lu).
# Un Bash RÉUSSI ET MUET (code 0, ni stdout ni stderr) passe : la clôture est traitée
# comme si elle dépendait de lui (`depends_on`), sa réussite est tout ce qu'elle en
# attend. Session d407d73d (2026-10-07) : `del temp_check_models.py` + FinalAnswer,
# refusée, puis la même réponse de 2 k caractères retapée pour rien.
_RANGEMENT_REUSSI = ("Rangé :", "Déjà rangé", "Rien à ranger")
_TRACE_PYTHON = "Traceback (most recent call last)"


def _sans_enjeu_de_lecture(tc: dict, resultat, effets_sans_lecture=frozenset()) -> bool:
    texte = resultat.strip() if isinstance(resultat, str) else ""
    params = tc.get("input") or {}
    nom = tc["name"]
    if nom in effets_sans_lecture:
        #  config["close_ok_tools"] : effets de l'agent hôte (Focus : generate_csv,
        #  store_dsm…) qu'une réponse annonce sans en citer la sortie. Audit Focus
        #  2026-09-29 : 59 refus sur eux, réponse ré-émise telle quelle à chaque fois.
        #  Un échec, lui, doit être lu : résultat vide ou trace Python. Les échecs
        #  préfixés sont déjà passés par `_refused_tool_results`, avant ce filtre.
        return bool(texte) and _TRACE_PYTHON not in texte
    if nom == "DisableChromeDevtools":
        #  Éteint le navigateur de CET agent : rien du travail livré n'en dépend.
        return True
    if nom == "Environment" and params.get("action") == "cleanup":
        return texte.startswith(_RANGEMENT_REUSSI)
    if nom == "Bash" and params.get("deferred") in (True, "true", "True", 1):
        #  Mise en file d'une vérification qui tournera APRÈS la clôture : son résultat
        #  n'est qu'un accusé (« Bash deferred #1 saved »), il n'y a rien à lire avant.
        return texte.startswith("Bash deferred #")
    if nom == "Bash":
        from ..tools.ops.shell_search import SORTIE_VIDE_REUSSIE
        return SORTIE_VIDE_REUSSIE in texte
    return False


def appels_a_relire(tool_calls: list[dict], ends_turn_names: set[str],
                    results: dict, effets_sans_lecture=frozenset()) -> list[dict]:
    """Les appels du lot dont la clôture doit attendre la lecture : ni comptabilité, ni
    acte de clôture, ni ménage réussi, ni effet réussi que l'agent déclare sans lecture."""
    lus_a_l_aveugle = set(tools_answered_blind(tool_calls, ends_turn_names))
    return [tc for tc in tool_calls if tc["name"] in lus_a_l_aveugle
            and not _sans_enjeu_de_lecture(tc, results.get(tc["id"]), effets_sans_lecture)]


_CODE_DE_SORTIE = re.compile(r"\[exited code=(-?\d+)\]\s*$")
_EXTRAIT_TETE, _EXTRAIT_QUEUE, _EXTRAIT_LARGEUR = 4, 4, 200


def _appel_en_bref(tc: dict) -> str:
    """Ce qui distingue CET appel de ses voisins du même nom : action, commande, fichier."""
    params = tc.get("input") or {}
    for cle in ("action", "command", "file_path", "path", "pattern", "query"):
        valeur = params.get(cle)
        if isinstance(valeur, str) and valeur.strip():
            premiere = valeur.strip().splitlines()[0]
            return premiere if len(premiere) <= 90 else premiere[:87] + "..."
    return ""


def _releve(tc: dict, resultat) -> str:
    """Une entrée du relevé : l'appel, son statut, puis un extrait (tête + fin) du résultat.

    Tête ET fin : un commit dit son sha en tête, une suite de tests son verdict en fin."""
    texte = resultat.strip() if isinstance(resultat, str) else ""
    bref = _appel_en_bref(tc)
    entete = f"- {tc['name']}" + (f"({bref})" if bref else "") + f" [id {tc['id']}]"
    if not texte:
        return f"{entete} — résultat VIDE"
    code = _CODE_DE_SORTIE.search(texte)
    if code:
        statut = f"code de sortie {code.group(1)} (ÉCHEC)"
    elif tc["name"] == "Bash":
        statut = "code de sortie 0"
    else:
        statut = "terminé"
    lignes = texte.splitlines()
    if len(lignes) > _EXTRAIT_TETE + _EXTRAIT_QUEUE + 1:
        omises = len(lignes) - _EXTRAIT_TETE - _EXTRAIT_QUEUE
        lignes = (lignes[:_EXTRAIT_TETE] + [f"[... {omises} lignes, texte complet au-dessus ...]"]
                  + lignes[-_EXTRAIT_QUEUE:])
    extrait = "\n".join("    " + (ligne if len(ligne) <= _EXTRAIT_LARGEUR
                                   else ligne[:_EXTRAIT_LARGEUR] + "...") for ligne in lignes)
    return f"{entete} — {statut}, {len(texte.splitlines())} ligne(s) :\n{extrait}"


def _close_over_unread_results_nudge(appels: list[dict], results: dict) -> str:
    """Ce que lit le modèle quand sa clôture précédait les résultats qu'elle cite.

    Le relevé est DANS l'avis. Sessions du poste Windows : l'avis disait « lis-les,
    ci-dessous » quand les résultats étaient au-dessus, puis voyageait seul sur le fil ;
    le modèle concluait « les résultats du Bash de commit ne sont pas lisibles »
    (28dcaf81) et refaisait la vérification — ou, en 2fe8f867, ne retrouvait plus un
    résultat mort entre-temps. Ce qu'il doit lire, il l'a ici, quoi que garde le fil."""
    listed = ", ".join(dict.fromkeys(tc["name"] for tc in appels))
    releve = "\n".join(_releve(tc, results.get(tc["id"])) for tc in appels)
    return (
        "(System Automated Event): ta clôture n'a PAS été acceptée (si le résultat de "
        "ta clôture dit « delivered », elle est en réalité SUSPENDUE). Tu as "
        f"clos la session dans le MÊME lot que : {listed}. Ces appels ONT été exécutés — "
        "leurs effets sont acquis, ne les rejoue PAS. Mais tu ne pouvais pas avoir lu leurs "
        "résultats en répondant. Ils sont AU-DESSUS de cet avis, dans les résultats de ce "
        "lot ; en voici le relevé :\n"
        f"{releve}\n"
        "Compare-les à ta réponse. S'ils la confirment, rappelle FinalAnswer SEUL et SANS "
        "`answer` (omets-le : le harnais reprend le texte de ta clôture suspendue ; ne "
        "redonne que taches_terminees et taches_restantes) — ne retape pas ta réponse, et "
        "inutile de re-vérifier ce que ce relevé montre déjà. S'ils la "
        "contredisent — une erreur, un code de sortie non nul, un schéma différent, des "
        "chiffres différents — refais le travail sur les VRAIS résultats. N'invente jamais "
        "ce qu'un outil a renvoyé."
    )


def annexer_au_lot(messages: list, texte: str) -> None:
    """Pose un avis du harnais À LA SUITE des résultats du lot, pas comme un tour user.

    Essai 3 (2026-09-24, racine 6bafe9cd, tours 37-41) : l'avis de clôture refusée était
    un message `user` ajouté après les résultats du lot. Le fil minimal
    (`minimal_payload`) lit un message user comme la FIN du lot : il n'a envoyé que
    l'avis (keep=0), sans aucun résultat — ni le refus du validateur porté par
    FinalAnswer, ni la sortie d'Environment. « Lis-les ci-dessous » : il n'y avait rien
    dessous. Accroché au dernier résultat du lot, l'avis voyage AVEC ces résultats."""
    dernier = messages[-1] if messages else None
    contenu = dernier.get("content") if isinstance(dernier, dict) else None
    if dernier is None or dernier.get("role") != "tool" or not isinstance(contenu, (str, list)):
        messages.append({"role": "user", "content": texte})
    elif isinstance(contenu, str):
        dernier["content"] = f"{contenu}\n\n{texte}"
    else:
        dernier["content"] = [*contenu, {"type": "text", "text": texte}]


def _bg_agent_keeps_turn_open(config: dict, tool_calls: list) -> bool:
    """Un sous-agent lancé EN FOND (outil Agent, mode web, wait=False) pendant ce tour
    signifie que le manager doit continuer SANS que le turn-protocol ne le pousse vers
    FinalAnswer ni ne ferme le tour. Consomme le drapeau (remis à zéro chaque tour) ;
    rend True si et seulement si un Agent de fond a été lancé ET que le manager n'a pas
    AUSSI appelé FinalAnswer explicitement dans le même lot (une FinalAnswer explicite
    est toujours honorée)."""
    launched = config.pop("_bg_agent_launched", False)
    if not launched:
        return False
    has_final_answer = bool(tool_calls) and any(
        tc.get("name") == "FinalAnswer" for tc in tool_calls
    )
    return not has_final_answer
