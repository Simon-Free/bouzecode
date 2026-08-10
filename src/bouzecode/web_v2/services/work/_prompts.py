"""Prompts et rapports du validateur de tickets (extraits de tickets.py).

Zéro logique de persistance ici : uniquement la construction des prompts
donnés aux agents validateurs + l'extraction du RAPPORT (FinalAnswer) du codeur.
Ré-exporté par tickets.py (façade) — les appelants continuent d'utiliser
`tickets.build_validator_prompt(...)`, etc."""
from __future__ import annotations

from pathlib import Path

from ...runtime import runner
from ..sessions import store


def extract_final_answer(messages: list[dict]) -> str:
    """Dernier RAPPORT FinalAnswer d'une session : answer du tool_call FinalAnswer,
    sinon contenu d'un tool_result FinalAnswer. Vide si aucun. Sert à nourrir le
    validateur du RAPPORT du codeur (pas seulement de son diff)."""
    for message in reversed(messages):
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if call.get("name") == "FinalAnswer":
                    answer = str((call.get("input") or {}).get("answer", "")).strip()
                    if answer:
                        return answer
        elif message.get("role") == "tool" and message.get("name") == "FinalAnswer":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def coder_report(ticket: dict) -> str:
    """RAPPORT (FinalAnswer) du run de travail le plus récent, pour le validateur.
    runs sont insérés en tête (add_run insert(0)), donc le premier run 'work' rencontré
    est le plus récent."""
    work = next((r for r in ticket.get("runs", []) if r["kind"] == "work"), None)
    if not work:
        return ""
    agent = runner.load_agent(work["agent_id"])
    if not agent:
        return ""
    data = store.load_session_json(Path(agent.session_path)) or {}
    return extract_final_answer(data.get("messages", []))


def _cap_for_cmdline(text: str, limit: int, what: str) -> str:
    """Borne un bloc de texte destiné à un prompt passé en ARGUMENT DE LIGNE DE COMMANDE
    (limite Windows ~32K → WinError 206). Au-delà, on tronque avec une note indiquant à
    l'agent (qui tourne DANS le worktree) de relire l'intégral via git lui-même."""
    if not text or len(text) <= limit:
        return text
    return (text[:limit] + f"\n\n… [{what} tronqué : {len(text)} chars > {limit}. Relis "
            f"l'intégral toi-même dans le worktree : `git diff <base>...HEAD`]")


def build_validator_prompt(ticket: dict, diff: str, report: str = "", sha: str = "") -> str:
    """Prompt du validateur unique : il a EXACTEMENT le rôle/profil du codeur, on lui
    rejoue la tâche d'origine + le DIFF produit + le RAPPORT (FinalAnswer) du codeur,
    et il rend un VERDICT tranché. Le profil coder (mêmes outils/droits) est
    appliqué à l'agent, pas ici."""
    # Le prompt part en ARGUMENT de ligne de commande au spawn (runner.create_agent) ; sous
    # Windows la ligne de commande est plafonnée (~32K chars) → un gros diff levait WinError 206
    # et bloquait TOUTE validation de ticket volumineux. On borne diff+rapport ; le validateur
    # tourne DANS le worktree et peut relire l'intégral lui-même. On lui donne le SHA EXACT
    # à juger (`sha`, figé au harvest) et on l'ancre sur `git diff <base>...<sha>` PLUTÔT que
    # `...HEAD` : HEAD est une ref mouvante (le codeur peut re-committer, ou une re-validation
    # tourner sur un autre état) → juger HEAD = risquer un verdict sur un commit ≠ celui livré
    # (faux négatif : le validateur mesure KO sur un état déjà corrigé).
    diff = _cap_for_cmdline(diff, 12000, "DIFF")
    report = _cap_for_cmdline(report, 8000, "RAPPORT")
    report_block = (
        f"## RAPPORT DU CODEUR (sa FinalAnswer)\n{report.strip()}\n\n"
        if report and report.strip() else ""
    )
    base = (ticket.get("worktree") or {}).get("base", "")
    sha_block = (
        f"## COMMIT À VALIDER (source de vérité)\n"
        f"Tu valides EXACTEMENT le commit `{sha}`. Pour relire l'intégral du travail, utilise "
        f"`git diff {base or '<base>'}...{sha}` — surtout PAS `...HEAD` : la branche a pu avancer "
        f"depuis, et juger un autre état que `{sha}` produit un verdict faux. Toutes tes "
        f"mesures (relecture, relance de tests) doivent porter sur `{sha}`.\n\n"
        if sha else ""
    )
    return (
        f"Tu valides le travail d'un agent codeur Python sur la tâche ci-dessous. "
        f"Tu as exactement les mêmes droits et outils que lui : relis le code, relance la "
        f"suite de tests pertinente, vérifie les règles de refacto (fichiers < 200 lignes, "
        f"pas de unittest.mock, tests user-centric, pas de try/except/pass).\n\n"
        f"{sha_block}"
        f"## TÂCHE D'ORIGINE : {ticket['title']}\n{ticket['prompt']}\n\n"
        f"{report_block}"
        f"## DIFF À VALIDER\n```diff\n{diff}\n```\n\n"
        f"Le codeur a pu corriger des tests/fichiers PRÉEXISTANTS cassés hors du scope du "
        f"ticket (ex. test rouge sans rapport, import mort) : si ces corrections sont "
        f"SIGNALÉES dans son rapport et raisonnables, NE mets PAS KO pour ça — juge "
        f"l'objectif RÉEL du ticket.\n\n"
        f"Termine ta réponse par une ligne contenant EXACTEMENT 'VERDICT: OK' si le travail "
        f"est correct et complet (tests verts, règles respectées), sinon 'VERDICT: KO' avec "
        f"la liste précise des problèmes juste avant. Émets toujours cette ligne."
    )


VALIDATORS = {
    "tests": (
        "Tu es un agent de validation CI. Lance la suite de tests pertinente du projet "
        "(pytest -n auto pour du Python) et analyse les échecs éventuels liés au ticket "
        "ci-dessous. Ne corrige rien.\n"
        "ENVIRONNEMENT : utilise le venv du projet, JAMAIS le Python système — depuis la "
        "racine du projet : & .venv\\Scripts\\python.exe -m pytest ... -v. Si des options "
        "pytest de la config ne sont pas installées (ex: --reruns), ajoute "
        "--override-ini=\"addopts=\".\n\nTicket : {title}\n{prompt}\n\n"
        "Termine ta réponse par une ligne contenant exactement 'VERDICT: OK' si les tests "
        "sont verts, sinon 'VERDICT: KO' avec la liste des échecs juste avant. Émets toujours "
        "cette ligne, même si les tests n'ont pas pu tourner (environnement cassé → VERDICT: KO)."
    ),
    "refacto": (
        "Tu es un agent de validation qualité. Passe en revue les fichiers touchés par le "
        "ticket ci-dessous (git status/diff ou fichiers récents). Règles : fichiers < 200 "
        "lignes, ≤ 5 fichiers par dossier, noms descriptifs, pas de try/except inutile, pas "
        "d'abstraction prématurée. Ne corrige rien.\n\nTicket : {title}\n{prompt}\n\n"
        "Termine ta réponse par une ligne contenant exactement 'VERDICT: OK' ou 'VERDICT: KO' "
        "avec les violations juste avant."
    ),
}
