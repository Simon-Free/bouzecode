# [desc] Faux LLM Anthropic HTTP (vrai socket, SSE) SANS ETAT pour plusieurs agents concurrents : le script de chaque requete se lit dans sa conversation (marqueur du demandeur + nombre de tours deja joues). [/desc]
"""Les sous-agents tournent en meme temps : une file globale de reponses (faux_llm_scripte)
les melangerait. Ici chaque requete dit qui parle (`[principal]`, `[enfant:A]`, `[enfant:B]`
dans un message utilisateur) et ou il en est (nombre de messages assistant deja recus)."""
from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bouzecode.web_v2.tests.faux_llm_refus import MODELE, FauxLlmRefus
from bouzecode.web_v2.tests.faux_llm_scripte import METHODOLOGY, final_answer, flux_texte


def appel(nom: str, ident: str, **params: str) -> str:
    corps = "".join(f'<param name="{cle}">{valeur}</param>' for cle, valeur in params.items())
    return f'<tool_use name="{nom}" id="{ident}">{corps}</tool_use>'


#  q livre, puis (repris) pose une question et livre ce qu'on lui a repondu.
_SCRIPT_Q = [
    final_answer("rapport Q"),
    METHODOLOGY + "\n" + appel("AskUserQuestion", "q1", question="Quelle teinte ?"),
    final_answer("Q a reçu sa réponse"),
]

#  Les enfants « lents » ne livrent qu'apres ce delai : ils finissent PENDANT l'attente de main.
DELAI_ENFANT_LENT = 3.0


def _principal_en_fond(textes_utilisateur: str) -> str:
    """main lance trois enfants lents EN FOND, puis les attend par un CheckAgentResult(wait=true)
    chacun, dans le MEME message (le lot attend avec l'invite ouverte), puis livre. L'etape se
    lit dans les resultats d'outils : le fil compacte fausse le compte des tours."""
    if "Attendu jusqu'à sa fin" in textes_utilisateur:
        return final_answer("main a récupéré ses enfants")
    ids = re.findall(r"Task ID: (\w+)", textes_utilisateur)
    if ids:
        return METHODOLOGY + "\n" + "\n".join(
            appel("CheckAgentResult", f"c{rang}", task_id=ident, wait="true")
            for rang, ident in enumerate(ids))
    return METHODOLOGY + "\n" + "\n".join(
        appel("Agent", f"a{rang}", prompt="[enfant:lent] livre", name=nom, background="true")
        for rang, nom in enumerate(("l1", "l2", "l3")))


SCRIPTS = {
    #  Le principal lance alpha et beta dans le MEME message (en attente, comme par defaut),
    #  puis livre (clore est refuse tant qu'un enfant travaille : le dernier tour se rejoue).
    "[principal]": [
        METHODOLOGY + "\n" + appel("Agent", "a1", prompt="[enfant:A] demande la couleur",
                                   name="alpha")
        + "\n" + appel("Agent", "a2", prompt="[enfant:B] livre tout de suite", name="beta"),
        final_answer("main a reçu les deux rapports"),
    ],
    #  main lance q, qui livre ; main livre. Repris par l'utilisateur, q pose une question
    #  qui REVEILLE main a l'invite.
    "[principal:repos]": [
        METHODOLOGY + "\n" + appel("Agent", "a1", prompt="[enfant:Q] livre", name="q"),
        final_answer("main a fini"),
    ],
    "[principal:fond]": [_principal_en_fond],
    "[enfant:lent]": [final_answer("rapport lent")],
    "[enfant:Q]": _SCRIPT_Q,
    "[reprise:Q]": _SCRIPT_Q,
    #  alpha pose une question (a son parent ET dans la barre), puis livre.
    "[enfant:A]": [
        METHODOLOGY + "\n" + appel("AskUserQuestion", "q1", question="Quelle couleur ?"),
        final_answer("rapport A"),
    ],
    #  beta livre aussitot ; relance par un message, il livre une seconde fois.
    "[enfant:B]": [final_answer("rapport B"), final_answer("reprise B")],
    #  Une session close est compactee a sa reprise : le premier enonce peut ne plus etre
    #  envoye, le message de reprise, lui, l'est toujours.
    "encore": [final_answer("reprise B")],
}


def _texte(contenu) -> str:
    if isinstance(contenu, str):
        return contenu
    return "".join(str(b.get("text") or b.get("content") or "") for b in contenu or []
                   if isinstance(b, dict))


#  La question d'un enfant remontee a main (avis « [Question n°N … (id X)] ») : main y repond
#  lui-meme par MessageAgent avec la reponse de son script, puis livre (le compte des tours
#  ne vaut plus : le fil compacte du tour de reveil n'a pas le meme nombre de messages).
REPONSES_DE_MAIN = {"[principal]": ("bleu", "main a reçu les deux rapports"),
                    "[principal:repos]": ("vert", "main a fini")}


def _repondre_a_la_question(messages: list, demandeur: str) -> str:
    tout = " ".join(_texte(m.get("content")) for m in messages)
    avis = re.search(r"\[Question n°(\d+) du sous-agent .*?\(id (\w+)\)\]", tout)
    if demandeur not in REPONSES_DE_MAIN or avis is None:
        return ""
    reponse, livraison = REPONSES_DE_MAIN[demandeur]
    if "Message pour « " in tout:
        return final_answer(livraison)
    return METHODOLOGY + "\n" + appel("MessageAgent", "r1", ticket_id=avis[2], text=reponse,
                                      question=avis[1])


def _lire(corps: dict) -> tuple[list, str, int, str]:
    """(messages, textes utilisateur, tours deja joues, demandeur — "" pour un appel annexe)."""
    messages = corps.get("messages") or []
    textes_utilisateur = " ".join(_texte(m.get("content")) for m in messages
                                  if m.get("role") == "user")
    tours = sum(1 for m in messages if m.get("role") == "assistant")
    #  Une session reprise est compactee en UNE note utilisateur : ses tours passes n'y sont
    #  plus des messages assistant, mais chaque livraison y laisse un bloc « ## FinalAnswer @ ».
    tours += textes_utilisateur.count("## FinalAnswer @")
    #  Le PREMIER marqueur de la conversation designe le demandeur : le fil du principal peut
    #  citer plus loin les consignes de ses enfants.
    trouves = [(textes_utilisateur.find(m), m) for m in SCRIPTS if m in textes_utilisateur]
    return messages, textes_utilisateur, tours, min(trouves)[1] if trouves else ""


def reponse_pour(corps: dict) -> str:
    messages, textes_utilisateur, tours, demandeur = _lire(corps)
    if not demandeur:
        return "ok"  # appel annexe (resume, classification…) : reponse courte
    script = SCRIPTS[demandeur]
    etape = script[min(tours, len(script) - 1)]
    return (_repondre_a_la_question(messages, demandeur)
            or (etape(textes_utilisateur) if callable(etape) else etape))


def delai_pour(corps: dict) -> float:
    _messages, _textes, tours, demandeur = _lire(corps)
    return DELAI_ENFANT_LENT if demandeur == "[enfant:lent]" and tours == 0 else 0.0


class _Routeur(BaseHTTPRequestHandler):
    def log_message(self, *arguments):
        pass

    def do_POST(self):  # noqa: N802 — nommage de http.server
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.requetes.append(corps)
        time.sleep(delai_pour(corps))
        donnees = flux_texte(str(corps.get("model") or MODELE), reponse_pour(corps))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)


class FauxLlmAgents(FauxLlmRefus):
    def __init__(self) -> None:
        self._serveur = ThreadingHTTPServer(("127.0.0.1", 0), _Routeur)
        self._serveur.daemon_threads = True
        self._serveur.requetes = []
