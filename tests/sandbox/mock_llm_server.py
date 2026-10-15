# [desc] Faux LLM Anthropic (/v1/messages, SSE) PILOTÉ PAR SCÉNARIO pour le bac à sable web_v2 : la réponse se déduit de la requête (mot-clé [scn:…] du premier message, résultats d'outils déjà reçus), sans file globale, donc N agents concurrents. [/desc]
"""Faux LLM du bac à sable bouzeui.

Principe : SANS ÉTAT. Chaque requête porte tout l'historique ; on y lit
  - le SCÉNARIO : premier mot-clé ``[scn:<nom>]`` trouvé dans les messages user
    (sinon ``default``, ou ``assistant`` pour le profil bureau-assistant) ;
  - l'ÉTAPE : chaque étape d'un scénario porte un id d'appel d'outil « clé » ; l'étape
    courante est la première dont la clé n'a PAS encore de ``<tool_result id=…>`` dans
    l'historique. Une relance (enforcement, refus de clôture) rejoue donc la même étape.
Les side-calls (système sans le protocole XML : résumé de thinking, validateur, classifieur)
reçoivent une réponse courte plausible.

Seul état : un compteur par conversation pour ``[scn:error429]`` (N échecs puis succès).

Variables d'environnement :
  MOCK_LLM_PORT      (5099)   port d'écoute
  MOCK_LLM_LATENCY   (0.8)    délai avant le premier octet, en secondes
  MOCK_LLM_CHUNK_DELAY (0.02) délai entre deux fragments de texte
  MOCK_LLM_SLOW_DELAY  (0.35) délai entre fragments pour [scn:slow]
  MOCK_LLM_USAGE_SEMANTICS (gateway) « gateway » : input_tokens INCLUT cache_creation (mesuré sur
                           le internal LLM gateway, cf. docs/archive/RAPPORT_TOP_SESSIONS_2026-06-12.md) ;
                           « anthropic » : sémantique officielle, input_tokens = frais seuls.

USAGE DÉTERMINISTE (vérité terrain des comptages de tokens) : chaque réponse porte un `usage`
calculé depuis la requête — 1 token = 4 caractères du JSON envoyé (système + messages), cache
simulé sur les points `cache_control` (préfixe déjà vu = lu en cache, reste du préfixe = écrit),
sortie = ceil(len(texte généré) / 4). Chaque appel est journalisé avec son usage exact :
``GET /usage_log?conv=<sha1 du 1er énoncé>`` (voir ``conv_id``).

Lancement : ``.venv/bin/python tests/sandbox/mock_llm_server.py`` (jamais `uv run` : index corporate injoignable)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time

from flask import Flask, Response, request

from bouzecode.backend.xml_tool_protocol.serializer import serialize_tool_call

PORT = int(os.environ.get("MOCK_LLM_PORT", "5099"))
LATENCY = float(os.environ.get("MOCK_LLM_LATENCY", "0.8"))
CHUNK_DELAY = float(os.environ.get("MOCK_LLM_CHUNK_DELAY", "0.02"))
SLOW_DELAY = float(os.environ.get("MOCK_LLM_SLOW_DELAY", "0.35"))
USAGE_SEMANTICS = os.environ.get("MOCK_LLM_USAGE_SEMANTICS", "gateway")

_SCN_RE = re.compile(r"\[scn:([a-z0-9_-]+)\]", re.I)
_RESULT_ID_RE = re.compile(r'<tool_result id="([^"]+)"')
_XML_PROTOCOL_MARK = "# Tool calls — XML protocol"

app = Flask(__name__)
_lock = threading.Lock()
_error_counters: dict[str, int] = {}
LOG: list[dict] = []
LAST: list[dict] = [{}]
USAGE_LOG: list[dict] = []
_SEEN_PREFIXES: set[str] = set()


# ─────────────────────────────── lecture de la requête ───────────────────────────────

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    parts.append(f'<tool_result id="{block.get("tool_use_id", "")}">'
                                 + _text_of(block.get("content", "")) + "</tool_result>")
        return "\n".join(parts)
    return str(content or "")


def _system_text(body: dict) -> str:
    return _text_of(body.get("system", ""))


_UTTER_RE = re.compile(r"\n## User @[^\n]*\n")
_MARK_RE = re.compile(r"⟦mock u(\d+) s(\d+)⟧")


class Req:
    """Vue d'une requête. Deux pièges du harnais, mesurés sur le fil :
    - le premier message user N'EST PAS dans `messages` : il vit dans la note Methodology
      (bloc system), sous la forme « ## User @<ts>\n<texte> » — comme chaque relance ;
    - les tool_result d'un lot DISPARAISSENT au tour suivant (sauf Snippet/Methodology).
    L'étape d'un scénario se lit donc dans des MARQUEURS que le faux LLM écrit lui-même
    dans sa Methodology (append-only, persistante) : « ⟦mock u<N> s<k>⟧ »."""

    def __init__(self, body: dict):
        self.body = body
        self.system = _system_text(body)
        self.messages = body.get("messages", []) or []
        self.user_texts = [_text_of(m.get("content")) for m in self.messages if m.get("role") == "user"]
        self.all_user = "\n".join(self.user_texts)
        self.results = set(_RESULT_ID_RE.findall(self.all_user))
        # Appel ANNEXE (rattrapage d'enforcement) : son système contient aussi le protocole
        # XML (un outil y est documenté), il faut donc le reconnaître à son propre énoncé.
        self.recovery = "maintiens la mémoire de travail (Methodology)" in self.system
        self.main = _XML_PROTOCOL_MARK in self.system and not self.recovery
        self.is_assistant = "## LancerAgent" in self.system and "## Chantiers" in self.system
        self.is_manager = "Tu es le **Manager**" in self.system
        # Énoncés de l'utilisateur : ceux de la note (chronologiques), sinon les messages
        # user qui ne sont pas des résultats d'outils.
        # L'énoncé entier jusqu'à la section suivante (« ## … ») : un prompt de tâche du Bureau
        # contient des lignes vides (titre, chantier, brief) et son tag est dans le brief.
        utter = [u.split("\n## ")[0].strip() for u in _UTTER_RE.split(self.system)[1:]]
        if not utter:
            utter = [t for t in self.user_texts if not t.lstrip().startswith("<tool_result")]
        self.utterances = utter
        self.n_utt = len(utter)
        # Scénario : celui du DERNIER énoncé s'il porte un tag ; sinon celui du premier
        # énoncé tant qu'il est seul ; une RELANCE sans tag (« et maintenant ? ») reçoit la
        # réponse par défaut — rejouer le scénario d'origine re-poserait la même question.
        last_tag = _SCN_RE.search(utter[-1]) if utter else None
        first_tag = _SCN_RE.search(utter[0]) if utter else None
        if last_tag:
            self.scenario = last_tag.group(1).lower()
        elif first_tag and (len(utter) == 1 or first_tag.group(1).lower() in SCENARIOS_COLLANTS):
            self.scenario = first_tag.group(1).lower()
        else:
            self.scenario = "assistant" if self.is_assistant else "default"
        first = utter[0] if utter else ""
        self.task = _SCN_RE.sub("", first.split("\n\n")[0]).strip()[:200] or "la demande"
        self.last_user = utter[-1] if utter else ""
        self.conv_key = hashlib.sha1((first + str(self.n_utt)).encode("utf-8", "ignore")).hexdigest()[:12]
        steps = [int(k) for u, k in _MARK_RE.findall(self.system) if int(u) == self.n_utt]
        self.step = (max(steps) + 1) if steps else 0

    def has(self, rid: str) -> bool:
        return rid in self.results

    def mark(self) -> str:
        return f"⟦mock u{self.n_utt} s{self.step}⟧"


# ─────────────────────────────── fabrique de réponses ───────────────────────────────

def call(tool: str, rid: str, /, **inp) -> str:
    # Positionnels purs : l'outil Agent a lui-même un paramètre `name`.
    return serialize_tool_call({"id": rid, "name": tool, "input": inp})


def thinking(text: str) -> str:
    """Le format du protocole (prompt système) : balises seules sur leur ligne. Une balise
    fermante en fin de ligne n'est pas reconnue par le harnais (col 0 exigée, pour ne pas
    fermer sur une simple mention) : la réflexion restait ouverte et s'affichait en double."""
    return f"<thinking>\n{text}\n</thinking>\n"


def turn(req: "Req", prose: str, *calls: str, note: str = "", **extra) -> dict:
    """Un tour valide : prose visible + lot XML contenant TOUJOURS la Methodology (avec le
    marqueur d'étape) — l'enforcement l'exige à chaque lot."""
    m = call("Methodology", f"m{req.n_utt}_{req.step}", content=f"{req.mark()} {note or 'étape'}")
    body = prose + "\n\n<tool_calls>\n" + "\n".join((m,) + calls) + "\n</tool_calls>"
    return {"text": body, **extra}


def _recap(files: list[str] | None = None) -> dict:
    files = files or ["src/app.py"]
    return {
        "symptoms": "Demande simulée par le bac à sable : l'utilisateur veut voir un agent livrer.",
        "explanation": "Réponse fabriquée par le faux LLM ; aucun vrai modèle n'a été appelé.",
        "tests": "Aucun test réel (scénario simulé).",
        "changes": [{"file": f, "summary": "Modifie le fichier (simulation)."} for f in files],
    }


def final(req: "Req", prose: str, answer: str, restantes: list | None = None,
          terminees: list | None = None, recap: dict | None = None, **extra) -> dict:
    """Clôture valide pour la porte déterministe (taches_* + recap objet complet)."""
    fa = call("FinalAnswer", f"fa{req.n_utt}_{req.step}",
              answer=answer,
              taches_terminees=terminees if terminees is not None else [f"Traité : {req.task[:80]}"],
              taches_restantes=restantes if restantes is not None else [],
              recap=recap if recap is not None else _recap())
    return turn(req, prose, fa, note="clôture", **extra)


def run_steps(req: "Req", steps: list) -> dict:
    """Joue l'étape courante ; au-delà de la dernière, rejoue la dernière (clôture) —
    c'est ce qui se passe quand une clôture est refusée ou qu'un manager est réveillé."""
    return steps[min(req.step, len(steps) - 1)](req)


def _long_markdown() -> str:
    parts = ["# Rapport détaillé (simulation)\n"]
    for i in range(1, 13):
        parts.append(f"## {i}. Section {i}\n")
        parts.append("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6 + "\n")
        parts.append(f"- point {i}.a\n- point {i}.b\n- point {i}.c\n")
        parts.append("```python\n"
                     f"def fonction_{i}(x: int) -> int:\n"
                     f"    \"\"\"Exemple {i}.\"\"\"\n"
                     f"    return x * {i}\n"
                     "```\n")
        parts.append("| col A | col B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n")
    return "".join(parts)


# ─────────────────────────────── scénarios ───────────────────────────────

def scn_default(req: Req) -> dict:
    return final(req, thinking("Demande simple, je réponds directement.")
                 + "Voici ma réponse (simulée par le bac à sable).",
                 f"C'est fait : « {req.task[:120]} » (réponse simulée).")


def scn_slow(req: Req) -> dict:
    prose = ("Je réfléchis à voix haute, lentement, pour que l'interface montre le texte "
             "arriver au fil de l'eau. " * 9)  # ~30 s : de la marge pour agir pendant qu'il tourne
    return final(req, thinking("Réponse lente demandée.") + prose, "Réponse lente terminée.",
                 delay=SLOW_DELAY, chunk=10)


def scn_long(req: Req) -> dict:
    return final(req, _long_markdown(), "Rapport long livré (voir ci-dessus).")


def scn_question(req: Req) -> dict:
    return run_steps(req, [
        lambda r: turn(r, thinking("Il me manque une décision.")
                       + "Avant d'aller plus loin, j'ai besoin d'un choix de ta part.",
                       call("AskUserQuestion", "q1",
                            question="Quelle base de données dois-je cibler ?",
                            options=[{"label": "PostgreSQL", "description": "la base de prod"},
                                     {"label": "SQLite", "description": "pour les tests locaux"}],
                            allow_freetext=True),
                       note="question posée"),
        lambda r: final(r, "Merci pour ta réponse, je termine.",
                        "Choix pris en compte, travail terminé."),
    ])


def scn_plan(req: Req) -> dict:
    return run_steps(req, [
        lambda r: turn(r, "Voici mon plan, à valider avant que je code.",
                       call("WritePlan", "p1",
                            content="# Plan\n\n1. Écrire un test qui échoue\n"
                                    "2. Corriger `src/app.py`\n3. Relancer les tests\n",
                            user_validation_required=True),
                       note="plan écrit"),
        lambda r: final(r, "Plan validé, j'exécute.", "Plan exécuté (simulation)."),
    ])


def scn_tools(req: Req) -> dict:
    return run_steps(req, [
        lambda r: turn(r, thinking("Je regarde le dépôt.") + "Je commence par explorer le dépôt.",
                       call("Bash", "b1", command="ls; git log --oneline -5"),
                       call("Glob", "g1", pattern="**/*"), note="exploration"),
        lambda r: turn(r, "Je lis le README.", call("Read", "r1", file_path="README.md"),
                       note="lecture"),
        lambda r: turn(r, "J'ajoute une note au fichier NOTES.md.",
                       call("Snippet", "s1", file_path="README.md", discard=True),
                       call("Write", "w1", file_path="NOTES.md",
                            content="# Notes\n\nFichier écrit par un agent simulé.\n"),
                       note="écriture"),
        lambda r: turn(r, "Je vérifie et je committe.",
                       call("Bash", "b2", command="git add NOTES.md; git -c user.name=agent "
                            "-c user.email=agent@sandbox commit -m 'docs: NOTES.md (agent simulé)'"),
                       note="commit"),
        lambda r: final(r, "Tout est fait.", "Exploration, lecture, écriture et commit effectués.",
                        recap=_recap(["NOTES.md"])),
    ])


def scn_subagents(req: Req) -> dict:
    return run_steps(req, [
        lambda r: turn(r, thinking("Deux sous-tâches indépendantes : je les lance en parallèle.")
                       + "Je découpe en deux sous-agents parallèles.",
                       call("Agent", "a1", prompt="Sous-tâche A : documenter le module\n[scn:slow]",
                            name="sous-agent-A", background=True, isolation="worktree"),
                       call("Agent", "a2", prompt="Sous-tâche B : choisir la base\n[scn:question]",
                            name="sous-agent-B", background=True, isolation="worktree"),
                       note="2 sous-agents lancés"),
        lambda r: final(r, "Mes sous-agents sont lancés ; je rends la main en attendant leurs verdicts.",
                        "Orchestration : sous-agents A et B dispatchés ; verdicts agrégés au réveil."),
    ])


def scn_lot_pause(req: Req) -> dict:
    """Deux Agent dans UN message, SANS background (le parent attend) : ils doivent partir
    ENSEMBLE (TODO 2026-09-25 §4), pas le second après la fin du premier."""
    return run_steps(req, [
        lambda r: turn(r, "Deux parties indépendantes, lancées dans le même message.",
                       call("Agent", "lp1", prompt="Partie A du lot\n[scn:etapes]", name="lot-A", isolation="worktree"),
                       call("Agent", "lp2", prompt="Partie B du lot\n[scn:etapes]", name="lot-B", isolation="worktree"),
                       note="lot lancé"),
        lambda r: final(r, "Les deux parties sont revenues.", "Lot de deux parties terminé."),
    ])


def scn_recap(req: Req) -> dict:
    restantes = [
        {"titre": "Ajouter un test de non-régression sur l'export CSV",
         "corps": "Le correctif couvre le cas nominal ; le cas fichier vide n'est pas testé.\n\n"
                  "Fichier : `src/export.py`. Critère : `pytest -k export` vert.",
         "macro_titre": "Fiabiliser les exports"},
        {"titre": "Garder le séparateur `;` ou passer à `,` ?",
         "corps": "Les utilisateurs Excel FR attendent `;`, l'API attend `,`.",
         "decision": True,
         "options": [{"key": "garder_pv", "label": "Garder ;"},
                     {"key": "virgule", "label": "Passer à ,"}]},
    ]
    return final(req, "Correctif livré, voici le récap.",
                 "Export CSV corrigé. Deux points restent ouverts (voir récap).",
                 restantes=restantes,
                 terminees=["Corrigé l'encodage de l'export CSV", "Ajouté 3 tests unitaires"],
                 recap={"symptoms": "L'export CSV produisait des caractères illisibles.",
                        "explanation": "Le fichier était écrit en cp1252 ; il l'est désormais en UTF-8 avec BOM.",
                        "tests": "3 tests unitaires ajoutés, tous verts.",
                        "changes": [{"file": "src/export.py", "summary": "Écrit en UTF-8 avec BOM."},
                                    {"file": "tests/test_export.py", "summary": "Couvre l'encodage."}]})


def scn_crash(req: Req) -> dict:
    # 400 : non retentable par le SDK → l'agent meurt vite, sans clôture.
    return {"status": 400, "message": "mock: requête invalide (crash simulé)"}


def scn_refus(req: Req) -> dict:
    """Refus du filtre de contenu : aucun contenu, `stop_reason: "refusal"` (clôture
    `content_refusal` -> ticket `idle_no_delivery` + signalement « reformule ou relance »)."""
    return {"text": "", "stop_reason": "refusal"}


def scn_error429(req: Req) -> dict:
    with _lock:
        n = _error_counters.get(req.conv_key, 0)
        _error_counters[req.conv_key] = n + 1
    if n < 2:
        return {"status": 429, "message": "mock: rate limit (simulé)"}
    return scn_default(req)


def scn_error500(req: Req) -> dict:
    return {"status": 500, "message": "mock: erreur serveur persistante (simulée)"}


def scn_hang(req: Req) -> dict:
    """Premier token très tardif (45 s) : pour voir les états d'attente du modèle."""
    return final(req, "Enfin une réponse.", "Réponse tardive.", latency=45)


# ── assistant du Bureau (outils : Taches, Chantiers, LancerAgent, Flotte, Decisions…) ──

def scn_assistant(req: Req) -> dict:
    return final(req, "Bien reçu. (Assistant simulé : écris [scn:bureau-tache], "
                 "[scn:bureau-chantier], [scn:bureau-lancer] ou [scn:bureau-flotte] pour me faire agir.)",
                 "Message reçu (assistant simulé).", recap={})


def _assistant_steps(req: Req, prose: str, action_call: str, done: str) -> dict:
    return run_steps(req, [
        lambda r: turn(r, prose, action_call, note=prose),
        lambda r: final(r, done, done, recap={}),
    ])


def scn_bureau_tache(req: Req) -> dict:
    return _assistant_steps(req, "Je crée la tâche.",
                            call("Taches", "t1", action="creer",
                                 titre="Fiabiliser les exports : couvrir le fichier vide",
                                 intent="Demandé depuis l'assistant du Bureau (simulation)."),
                            "Tâche créée (voir la liste à gauche).")


def scn_bureau_chantier(req: Req) -> dict:
    return _assistant_steps(req, "Je crée le chantier.",
                            call("Chantiers", "c1", action="creer",
                                 titre="Migrer les rapports vers Databricks",
                                 corps="Chantier créé par l'assistant simulé.",
                                 projets=["demo-api"]),
                            "Chantier créé.")


def scn_bureau_lancer(req: Req) -> dict:
    return _assistant_steps(req, "Je lance un agent de développement.",
                            call("LancerAgent", "l1",
                                 prompt="Explorer le dépôt et écrire NOTES.md\n[scn:tools]",
                                 project_slug="demo-api", defer=True),
                            "Agent lancé sur demo-api.")


def scn_bureau_lancer_question(req: Req) -> dict:
    """Assistant : lance (LancerAgent) une tâche qui POSE UNE QUESTION ; l'assistant doit être
    réveillé avec la question (TODO 2026-09-25 §6)."""
    return _assistant_steps(req, "Je lance un agent qui aura une question.",
                            call("LancerAgent", "lq1",
                                 prompt="Brancher la base de données\n[scn:question]",
                                 project_slug="demo-api", defer=True),
                            "Agent lancé sur demo-api.")


def scn_bureau_flotte(req: Req) -> dict:
    return run_steps(req, [
        lambda r: turn(r, "Je regarde la flotte.", call("Flotte", "f1"),
                       call("ResteAFaire", "f2", fenetre="7j"), note="lecture flotte"),
        lambda r: final(r, "Voici l'état de la flotte (lu via Flotte et ResteAFaire).",
                        "État de la flotte résumé.", recap={}),
    ])


def scn_overflow(req: Req) -> dict:
    """Réflexion interminable SANS appel d'outil : la boucle la coupe (dépassement), résume
    la réflexion par un appel annexe, puis relance ; au retour on conclut."""
    last = req.user_texts[-1] if req.user_texts else ""
    if "Tour précédent interrompu" in last:
        return final(req, "Je passe à l'action après la coupure.", "Réflexion coupée puis conclue.")
    # Texte VARIÉ : une phrase répétée déclenche le détecteur de boucle (annulation du
    # tour), pas le dépassement de réflexion qu'on veut montrer.
    musing = " ".join(f"Hypothèse {i} : le module {i % 17} dépend de {i * 7 % 23}, "
                      f"je vérifie la piste {i * 13 % 101}." for i in range(700))
    return {"text": thinking(musing), "chunk": 400}


def scn_nometh(req: Req) -> dict:
    """Un lot SANS Methodology : l'enforcement la rattrape par un appel annexe forcé."""
    if req.step == 0 and not req.has("b_nometh"):
        return {"text": thinking("J'oublie ma note ce tour-ci.") + "Je lance une commande.\n\n"
                "<tool_calls>\n" + call("Bash", "b_nometh", command="echo nometh") + "\n</tool_calls>"}
    return final(req, "C'est fait.", "Commande lancée, note rattrapée.")


# ── scénarios COMPOSÉS : les enchaînements réels observés avec un vrai modèle (2026-09-24) ──
#  Un manager se met en worktree, écrit sans commiter, délègue 2 enfants (worktree + commit +
#  intégration), rend la main, est RÉVEILLÉ quand ses enfants ont fini, commite, intègre sa
#  branche, conclut ; puis on le RELANCE « même agent » avec un retour. C'est dans ces
#  enchaînements (pas dans les scénarios isolés) que les bugs d'état et d'intégration sont apparus.

_FICHIER_RE = re.compile(r"Fichier\s*:\s*(\S+)")
#  Commandes PORTABLES : sous Windows l'outil Bash exécute PowerShell 5.1 (ni `&&`, ni `||`, ni
#  `printf`, ni `| head`) — les fichiers s'écrivent par l'outil Write, les commandes se séparent
#  par `;`, valide dans les deux shells.
_GIT = "git -c user.name=agent -c user.email=agent@sandbox"


def _manager_delegation(req: Req, enfant_b: str) -> dict:
    return run_steps(req, [
        lambda r: turn(r, thinking("Deux agents vont travailler en parallèle : je m'isole d'abord.")
                       + "Je me mets dans un worktree dédié.",
                       call("Environment", "env_wt", action="worktree"), note="worktree"),
        lambda r: turn(r, "J'écris la spécification commune (pas encore commitée).",
                       call("Write", "w_spec", file_path="SPEC_COMMUNE.md", content="# Spec commune\n"),
                       call("Bash", "b_spec", command="ls"),
                       note="spec écrite, non commitée"),
        lambda r: turn(r, "Je délègue deux sous-agents, chacun sur son fichier.",
                       call("Agent", "a_ea", prompt="Enfant A : écrire enfant_a.md\nFichier : enfant_a.md\n"
                            "[scn:enfant-commit]", name="enfant-A", background=True, isolation="worktree"),
                       call("Agent", "a_eb", prompt=f"Enfant B : écrire enfant_b.md\nFichier : enfant_b.md\n"
                            f"[scn:{enfant_b}]", name="enfant-B", background=True, isolation="worktree"),
                       note="2 sous-agents lancés"),
        lambda r: final(r, "Mes sous-agents travaillent ; je rends la main jusqu'à leur retour.",
                        "Délégation faite : enfant A et enfant B lancés, j'attends leurs verdicts.",
                        recap={}),
    ])


def _manager_reveil(req: Req) -> dict:
    return run_steps(req, [
        lambda r: turn(r, "Réveillé : je regarde ce que mes sous-agents ont rendu.",
                       call("ListAgentTasks", "lat"), note="bilan des enfants"),
        lambda r: turn(r, "Je commite ma spécification avant d'intégrer.",
                       call("Bash", "b_cm", command=f"git add -A; {_GIT} commit -m 'spec commune (manager)'"),
                       note="commit du manager"),
        lambda r: turn(r, "J'intègre ma branche dans la base.",
                       call("Environment", "env_int", action="integrate"), note="intégration"),
        lambda r: final(r, "Tout est intégré.", "Spec commune et travail des sous-agents intégrés.",
                        recap=_recap(["SPEC_COMMUNE.md", "enfant_a.md", "enfant_b.md"])),
    ])


def _scn_manager(enfant_b: str):
    def scn(req: Req) -> dict:
        #  1er énoncé : délégation ; énoncés suivants SANS tag (le réveil du serveur) : bilan.
        return _manager_delegation(req, enfant_b) if req.n_utt <= 1 else _manager_reveil(req)
    return scn


def scn_enfant_commit(req: Req) -> dict:
    fichier = (_FICHIER_RE.search(req.utterances[0] if req.utterances else "") or [None, "enfant.md"])[1]
    return run_steps(req, [
        lambda r: turn(r, "Je m'isole.", call("Environment", "env_wt", action="worktree"), note="worktree"),
        lambda r: turn(r, f"J'écris et je commite {fichier}.",
                       call("Write", "w_w", file_path=fichier, content="Livré par un sous-agent.\n"),
                       call("Bash", "b_w", command=f"git add {fichier}; {_GIT} commit -m 'feat: {fichier} (sous-agent)'"),
                       note="commit"),
        lambda r: turn(r, "J'intègre mon travail.", call("Environment", "env_int", action="integrate"),
                       note="intégration"),
        lambda r: final(r, "Mon lot est livré.", f"{fichier} écrit, commité et intégré.",
                        recap=_recap([fichier])),
    ])


def scn_integre_soi_meme(req: Req) -> dict:
    """Agent isolé dès son lancement (worktree) qui demande avant d'intégrer — le temps pour le
    test de poser un brouillon « Fusionner la branche agent/<ticket> » — puis commite, intègre
    LUI-MÊME sa branche (Environment) et conclut."""
    return run_steps(req, [
        lambda r: turn(r, "Avant d'intégrer ma branche, je te demande.",
                       call("AskUserQuestion", "q_int", question="Puis-je intégrer ma branche ?",
                            options=[{"label": "Oui", "description": "intègre"}], allow_freetext=True),
                       note="question avant intégration"),
        lambda r: turn(r, "J'écris et je commite.",
                       call("Write", "w_liv", file_path="LIVRE.md", content="Livré.\n"),
                       call("Bash", "b_liv", command=f"git add LIVRE.md; "
                            f"{_GIT} commit -m 'feat: LIVRE.md (agent simulé)'"),
                       note="commit"),
        lambda r: turn(r, "J'intègre ma branche.", call("Environment", "env_int", action="integrate"),
                       note="intégration"),
        lambda r: final(r, "Livré et intégré.", "LIVRE.md écrit, commité et intégré.",
                        recap=_recap(["LIVRE.md"])),
    ])


def scn_relance_apres_final(req: Req) -> dict:
    """Retour de l'utilisateur à un agent déjà conclu (relance « même agent ») : il retravaille
    plusieurs tours — dont deux commandes qui durent quelques secondes, pour qu'on le VOIE
    travailler — puis conclut."""
    return run_steps(req, [
        lambda r: turn(r, thinking("Retour reçu : je reprends.") + "Je reprends avec ton retour.",
                       call("Bash", "b_r1", command="sleep 3; ls"), note="reprise"),
        lambda r: turn(r, "J'ajoute ce qui manquait.",
                       call("Write", "w_r2", file_path="RETOUR.md", content="Complément après retour.\n"),
                       call("Bash", "b_r2", command="ls"),
                       note="complément"),
        lambda r: turn(r, "Je commite.",
                       call("Bash", "b_r3", command=f"sleep 3; git add RETOUR.md; {_GIT} commit -m 'suite au retour'"),
                       note="commit"),
        lambda r: final(r, "Le retour est traité.", "Retour pris en compte : RETOUR.md ajouté et commité.",
                        recap=_recap(["RETOUR.md"])),
    ])


# ── messages écrits PENDANT le travail (SPEC §4.10, §4.6) : un message déposé pendant un tour
#  arrive comme un NOUVEL énoncé (« ## User @… » dans la Methodology) à la frontière de tour
#  suivante ; son tag, s'il en porte un, prend alors la main — c'est ce qui PROUVE qu'il a été
#  lu, et à quel moment. ──

def scn_etapes(req: Req) -> dict:
    """Agent : quatre lots d'outils de ~3 s chacun avant de conclure — le temps de lui parler."""
    etapes = [lambda r, i=i: turn(r, f"Étape {i + 1} sur 4.",
                                  call("Bash", f"b_et{i}", command=f"sleep 3; echo etape{i + 1}"),
                                  note=f"étape {i + 1}")
              for i in range(4)]
    return run_steps(req, etapes + [lambda r: final(r, "Les quatre étapes sont faites.",
                                                   "Quatre étapes faites, sans précision reçue.")])


def scn_ecrire_fichier(req: Req) -> dict:
    """Agent : écrit le fichier nommé « Fichier : X » dans le DERNIER énoncé, puis conclut."""
    fichier = (_FICHIER_RE.search(req.last_user) or [None, "PRECISION.md"])[1]
    return run_steps(req, [
        lambda r: turn(r, f"Précision reçue : j'écris {fichier}.",
                       call("Write", "w_fic", file_path=fichier, content="Écrit après la précision.\n"),
                       call("Bash", "b_fic", command="ls"),
                       note=f"fichier {fichier}"),
        lambda r: final(r, f"{fichier} est écrit.", f"Précision appliquée : {fichier} écrit.",
                        recap=_recap([fichier])),
    ])


def scn_assistant_etapes(req: Req) -> dict:
    """Assistant : trois lectures de la flotte, chaque réponse streamée en ~3 s."""
    lent = {"delay": 0.5, "chunk": 12}
    prose = "Je relis la flotte pour faire le point, calmement, étape par étape. "
    return run_steps(req, [
        lambda r: turn(r, prose, call("Flotte", "f_e1"), note="flotte 1", **lent),
        lambda r: turn(r, prose, call("Flotte", "f_e2"), note="flotte 2", **lent),
        lambda r: turn(r, prose, call("Flotte", "f_e3"), note="flotte 3", **lent),
        lambda r: final(r, "Point fait (trois lectures).", "Point de flotte fait.", recap={}),
    ])


def scn_assistant_lent(req: Req) -> dict:
    """Assistant : une lecture de flotte, PUIS une réponse interminable (~60 s) à interrompre."""
    return run_steps(req, [
        lambda r: turn(r, "Je lis la flotte d'abord.", call("Flotte", "f_l1"), note="flotte lue"),
        lambda r: final(r, "Je développe longuement ma réponse, mot après mot, sans me presser. " * 12,
                        "Réponse longue terminée.", recap={}, delay=0.8, chunk=10),
    ])


def _tours_de_reflexion(n: int = 3) -> list:
    """N tours enchaînés, chacun : réflexion streamée lentement + un outil court. De quoi voir,
    dans le fil, si le tour n+1 s'AJOUTE au tour n ou le remplace (TODO 2026-09-25 §3)."""
    lent = {"delay": 0.15, "chunk": 8}
    return [lambda r, i=i: turn(r, thinking(f"Réflexion du tour {i + 1} : je pèse la suite, "
                                            "posément, avant d'agir. " * 3)
                                + f"Tour {i + 1} sur {n}.",
                                call("Bash", f"b_rt{i}", command=f"sleep 1; echo tour{i + 1}"),
                                note=f"tour {i + 1}", **lent)
            for i in range(n)]


def scn_reflexion_tours(req: Req) -> dict:
    """Agent : trois tours avec réflexion et outil, puis conclusion."""
    return run_steps(req, _tours_de_reflexion() + [
        lambda r: final(r, "Les trois tours sont faits.", "Trois tours de réflexion faits.")])


def scn_question_reflexion(req: Req) -> dict:
    """Agent : question d'abord (pause CHAUDE), puis trois tours avec réflexion, puis conclusion."""
    question = lambda r: turn(r, "Une décision d'abord.",  # noqa: E731
                              call("AskUserQuestion", "q_rt", question="Je continue en trois tours ?",
                                   options=[{"label": "Oui", "description": "vas-y"},
                                            {"label": "Non", "description": "arrête"}],
                                   allow_freetext=True),
                              note="question posée")
    return run_steps(req, [question] + _tours_de_reflexion()
                     + [lambda r: final(r, "Réponse reçue, trois tours faits.",
                                        "Trois tours après la réponse faits.")])


_TACHE_RE = re.compile(r"tâche=(\S+)")
_PRECISION_RE = re.compile(r"précision=«(.*?)»", re.S)


def scn_bureau_preciser(req: Req) -> dict:
    """Assistant : transmet une précision à la tâche nommée (« tâche=<id> précision=«…» ») ;
    `{scn:x}` dans la précision devient `[scn:x]` pour piloter l'agent qui la reçoit."""
    tache = (_TACHE_RE.search(req.last_user) or [None, ""])[1]
    texte = (_PRECISION_RE.search(req.last_user) or [None, ""])[1].replace("{scn:", "[scn:").replace("}", "]")
    interrompre = "interrompre=oui" in req.last_user
    return _assistant_steps(req, "Je transmets ta précision à l'agent de la tâche.",
                            call("Taches", "t_pr", action="preciser", task_id=tache, texte=texte,
                                 interrompre=interrompre),
                            "Précision transmise à l'agent.")


#  Scénarios qui se POURSUIVENT sur un énoncé suivant sans tag (réveil du manager par le
#  serveur) au lieu de retomber sur la réponse par défaut.
SCENARIOS_COLLANTS = {"manager-worktree", "manager-worktree-crash"}


SCENARIOS = {
    "manager-worktree": _scn_manager("enfant-commit"),
    "manager-worktree-crash": _scn_manager("crash"),
    "enfant-commit": scn_enfant_commit,
    "relance-apres-final": scn_relance_apres_final,
    "integre-soi-meme": scn_integre_soi_meme,
    "default": scn_default, "reply": scn_default, "slow": scn_slow, "long": scn_long,
    "question": scn_question, "plan": scn_plan, "tools": scn_tools,
    "subagents": scn_subagents, "recap": scn_recap, "crash": scn_crash, "refus": scn_refus,
    "overflow": scn_overflow, "nometh": scn_nometh,
    "error429": scn_error429, "error500": scn_error500, "hang": scn_hang,
    "assistant": scn_assistant, "bureau-tache": scn_bureau_tache,
    "bureau-chantier": scn_bureau_chantier, "bureau-lancer": scn_bureau_lancer,
    "bureau-flotte": scn_bureau_flotte, "bureau-lancer-question": scn_bureau_lancer_question,
    "etapes": scn_etapes, "ecrire-fichier": scn_ecrire_fichier,
    "assistant-etapes": scn_assistant_etapes, "assistant-lent": scn_assistant_lent,
    "bureau-preciser": scn_bureau_preciser,
    "reflexion-tours": scn_reflexion_tours, "lot-pause": scn_lot_pause, "question-reflexion": scn_question_reflexion,
}


def side_call(req: Req) -> dict:
    sysl = req.system.lower()
    if "valides la clôture" in sysl:
        return {"text": "OK"}
    if "classif" in sysl:
        return {"text": "default"}
    return {"text": "Résumé simulé : l'agent avance normalement."}



# ─────────────────────────────── usage déterministe ───────────────────────────────

def _tok(obj) -> int:
    """1 token = 4 caractères du JSON compact (arrondi supérieur) : simple, exact, rejouable."""
    raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return -(-len(raw) // 4)


def _wire_units(body: dict) -> list[tuple[object, bool]]:
    """Le prompt découpé en unités ordonnées (bloc système, bloc de message), chacune avec
    son drapeau `cache_control`. Le cache d'Anthropic porte sur un PRÉFIXE qui s'arrête à un
    point `cache_control` : c'est ce découpage qui permet de le simuler."""
    units: list[tuple[object, bool]] = []
    system = body.get("system")
    if isinstance(system, list):
        units += [(b, bool(isinstance(b, dict) and b.get("cache_control"))) for b in system]
    elif system:
        units.append((system, False))
    for msg in body.get("messages") or []:
        content = msg.get("content")
        if isinstance(content, list):
            for b in content:
                units.append(({"role": msg.get("role"), "b": b},
                              bool(isinstance(b, dict) and b.get("cache_control"))))
        else:
            units.append(({"role": msg.get("role"), "c": content}, False))
    return units


def compute_usage(body: dict) -> dict:
    """Usage VRAI d'une requête : total, lu en cache, écrit au cache, frais."""
    units = _wire_units(body)
    sizes = [_tok(u) for u, _ in units]
    total = sum(sizes)
    breakpoints = [i for i, (_, cc) in enumerate(units) if cc]
    read = created = 0
    if breakpoints:
        digest = hashlib.sha1()
        prefix_hashes = []
        for i, (u, _) in enumerate(units):
            digest.update(json.dumps(u, sort_keys=True, ensure_ascii=False).encode("utf-8"))
            prefix_hashes.append(digest.hexdigest())
        last_bp = breakpoints[-1]
        cached_prefix = sum(sizes[: last_bp + 1])
        with _lock:
            hit = max((bp for bp in breakpoints if prefix_hashes[bp] in _SEEN_PREFIXES), default=-1)
            for bp in breakpoints:
                _SEEN_PREFIXES.add(prefix_hashes[bp])
        read = sum(sizes[: hit + 1]) if hit >= 0 else 0
        created = cached_prefix - read
    fresh = total - read - created
    reported_input = fresh + created if USAGE_SEMANTICS == "gateway" else fresh
    return {"total": total, "fresh": fresh, "cache_read": read, "cache_creation": created,
            "input_tokens": reported_input}


def conv_id(req: "Req") -> str:
    first = req.utterances[0] if req.utterances else ""
    return hashlib.sha1(first.encode("utf-8", "ignore")).hexdigest()[:12]

# ─────────────────────────────── SSE ───────────────────────────────

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _chunks(text: str, size: int) -> list[str]:
    """Fragments de ~`size` caractères pour la prose, le lot XML d'un seul tenant.

    On ne coupe JAMAIS au milieu d'une suite de backticks : le parser incrémental de prod
    perd alors le lot <tool_calls> qui suit (bug reproduit : « intro\n`` » | « `python… »
    → l'appel d'outil passe en texte, clôture `text_no_tools`). Le bac à sable doit montrer
    l'UI, pas ce bug ; il est signalé à part."""
    head, sep, tail = text.partition("<tool_calls>")
    out, i = [], 0
    while i < len(head):
        j = min(i + size, len(head))
        while 0 < j < len(head) and (head[j] == "`" or head[j - 1] == "`"):
            j += 1
        out.append(head[i:j])
        i = j
    if sep:
        out.append(sep + tail)
    return out


def _stream(item: dict, model: str, usage: dict):
    time.sleep(float(item.get("latency", LATENCY)))
    delay = float(item.get("delay", CHUNK_DELAY))
    text = item.get("text", "")
    yield _sse("message_start", {"type": "message_start", "message": {
        "id": f"msg_mock_{int(time.time() * 1000)}", "type": "message", "role": "assistant",
        "content": [], "model": model, "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": usage["input_tokens"], "output_tokens": 1,
                  "cache_read_input_tokens": usage["cache_read"],
                  "cache_creation_input_tokens": usage["cache_creation"]}}})
    yield _sse("content_block_start", {"type": "content_block_start", "index": 0,
                                       "content_block": {"type": "text", "text": ""}})
    for c in _chunks(text, int(item.get("chunk", 24))):
        yield _sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                           "delta": {"type": "text_delta", "text": c}})
        time.sleep(delay)
    yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield _sse("message_delta", {"type": "message_delta",
                                 "delta": {"stop_reason": item.get("stop_reason", "end_turn"),
                                           "stop_sequence": None},
                                 "usage": {"output_tokens": usage["output_tokens"]}})
    yield "event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"


@app.post("/v1/messages")
def messages():
    body = request.get_json(force=True, silent=True) or {}
    LAST[0] = body
    req = Req(body)
    if req.recovery:
        item = {"text": "<tool_calls>\n" + call("Methodology", "m_recovery",
                content="⟦mock recovery⟧ note rattrapée") + "\n</tool_calls>"}
    elif req.main:
        fn = SCENARIOS.get(req.scenario, scn_default)
        item = fn(req)
    else:
        item = side_call(req)
    LOG.append({"t": time.time(), "main": req.main, "scenario": req.scenario,
                "utt": req.n_utt, "step": req.step, "status": item.get("status", 200)})
    del LOG[:-500]
    print(f"[mock-llm] main={req.main} scn={req.scenario} utt={req.n_utt} step={req.step} "
          f"-> {item.get('status', 200)}", file=sys.stderr, flush=True)
    usage = compute_usage(body)
    usage["output_tokens"] = max(1, -(-len(item.get("text", "")) // 4))
    if not item.get("status"):
        USAGE_LOG.append({"t": time.time(), "conv": conv_id(req), "main": req.main,
                          "scenario": req.scenario, "utt": req.n_utt, "step": req.step,
                          "model": body.get("model", ""), **usage})
        del USAGE_LOG[:-5000]
    if item.get("status"):
        etype = {429: "rate_limit_error", 500: "api_error", 529: "overloaded_error"}.get(
            item["status"], "invalid_request_error")
        return {"type": "error", "error": {"type": etype, "message": item.get("message", "mock")}}, item["status"]
    if body.get("stream") is False:
        text = item.get("text", "")
        return {"id": "msg_mock", "type": "message", "role": "assistant", "model": body.get("model", "mock"),
                "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {
                    "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                    "cache_read_input_tokens": usage["cache_read"],
                    "cache_creation_input_tokens": usage["cache_creation"]}}
    return Response(_stream(item, body.get("model", "mock"), usage), mimetype="text/event-stream")


@app.get("/v1/models")
def models():
    return {"data": [{"id": "claude-opus-5", "type": "model"},
                     {"id": "claude-sonnet-5", "type": "model"}]}


@app.get("/")
@app.get("/health")
def health():
    return {"ok": True, "mock": True, "scenarios": sorted(SCENARIOS)}


@app.get("/last")
def last():
    return LAST[0]


@app.get("/log")
def log():
    return {"calls": LOG[-100:]}


@app.get("/usage_log")
def usage_log():
    conv = request.args.get("conv", "")
    rows = [r for r in USAGE_LOG if not conv or r["conv"] == conv]
    return {"semantics": USAGE_SEMANTICS, "calls": rows}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, threaded=True, use_reloader=False)
