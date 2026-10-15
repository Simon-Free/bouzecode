# [desc] Sortie lisible de `bouzecode tickets|projets` (liste, fiche, geste, fichiers non suivis, journal de suivi) ; `--json` court-circuite tout ceci. [/desc]
from __future__ import annotations

import json


def en_json(donnees) -> str:
    return json.dumps(donnees, ensure_ascii=False, indent=2, default=str)


def _etat(t: dict) -> str:
    raison = t.get("state_reason") or {}
    code = raison.get("code") if isinstance(raison, dict) else ""
    libelle = t.get("libelle_statut") or t.get("state") or "?"
    return f"{libelle} [{t.get('state')}{' : ' + code if code else ''}]"


def liste(lignes: list[tuple[str, dict]]) -> str:
    if not lignes:
        return "Aucun ticket."
    return "\n".join(f"{slug}  {t['id']}  {_etat(t)}  {t.get('title', '')}" for slug, t in lignes)


def _run(run: dict) -> str:
    fin = run.get("end") or {}
    issue = run.get("issue") or fin.get("reason") or run.get("state") or ""
    texte = f"  - {run.get('kind', 'work')} {run.get('agent_id', '?')} : {issue}"
    if run.get("url"):
        texte += f" — Rundeck {run.get('execution_id')} {run['url']}"
    return texte


def _distant(distant: dict | None) -> list[str]:
    if not distant:
        return []
    lignes = [f"Rundeck : exécution {distant.get('execution_id')} — {distant.get('url') or '-'}"]
    refuses = {s: l for s, l in (distant.get("fichiers_refuses") or {}).items() if l}
    for slug, liste_refus in refuses.items():
        noms = ", ".join(f"{f.get('chemin')} ({f.get('raison')})" if isinstance(f, dict) else str(f)
                         for f in liste_refus)
        lignes.append(f"Fichiers REFUSÉS (non transmis) {slug} : {noms}")
    return lignes


def evenement(e: dict) -> str:
    donnees = e.get("data") or {}
    detail = ", ".join(f"{k}={v}" for k, v in donnees.items()
                       if k in ("code", "message", "agent_id", "close_reason", "text") and v)
    return f"[{str(e.get('at', ''))[11:19]}] {e.get('kind')} ({e.get('actor')}){' — ' + detail if detail else ''}"


def fiche(f: dict, evenements: list[dict]) -> str:
    meta = f.get("worktree") if isinstance(f.get("worktree"), dict) else {}
    lignes = [f"{f['id']}  {f.get('title', '')}", f"État : {_etat(f)}",
              f"Isolation : {f.get('isolation') or 'shared'}"
              + (f" — branche {meta['branch']}" if meta.get("branch") else "")]
    livraison = f.get("delivery") or {}
    if livraison:
        lignes.append(f"Livraison : {livraison.get('commits_ahead', 0)} commit(s), "
                      f"{len(livraison.get('code_files_ahead') or [])} fichier(s) de code en avance")
    lignes += _distant(f.get("distant"))
    lignes.append("Runs :" if f.get("runs") else "Runs : aucun")
    lignes += [_run(r) for r in f.get("runs") or []]
    if evenements:
        lignes.append("Journal (derniers) :")
        lignes += ["  " + evenement(e) for e in evenements[-10:]]
    return "\n".join(lignes)


def geste(action: str, slug: str, r: dict) -> str:
    t = r.get("ticket") if isinstance(r.get("ticket"), dict) else r
    lignes = [f"Ticket {slug}/{t['id']} créé (via {r.get('via')})" if action == "creer"
              else f"{action} : OK (via {r.get('via')})"]
    if t.get("state"):
        lignes.append(f"État : {_etat(t)}")
    if r.get("key"):
        lignes.append(f"Agent : {r['key']}")
    lignes += _distant(r.get("distant"))
    if r.get("queued"):
        lignes.append(f"Message mis en file (position {r.get('position')}) : remis à la fin du tour")
    if action in ("creer", "lancer") and t.get("id"):
        lignes.append(f"Suivre : bouzecode tickets suivre {slug} {t['id']}")
    return "\n".join(lignes)


def fichiers(r: dict) -> str:
    if not r.get("ok"):
        return f"Refus {r.get('erreur')} : {r.get('slug')}"
    git = r.get("git") or {}
    lignes = [f"{r['slug']} — {r['chemin']}", f"Branche {git.get('branche')} @ {git.get('head')}"
              f" ; non poussés : {len(git.get('commits') or [])}"
              f" ; modifiés non commités : {len(git.get('modifications_non_commitees') or [])}",
              f"Non suivis : {r.get('non_suivis_total', 0)}"
              + (" (liste tronquée)" if r.get("tronque") else "")
              + "  (+ proposé, ! secret jamais transmis, - exclu)"]
    for f in r.get("non_suivis") or []:
        marque = "!" if f.get("exclu") == "secret" else "+" if f.get("pertinent") else "-"
        raison = f" ({f['exclu']})" if f.get("exclu") else ""
        lignes.append(f"  {marque} {f['chemin']}  {f.get('taille', 0)} o{raison}")
    return "\n".join(lignes)


def projets(liste_projets: list[dict]) -> str:
    return "\n".join(f"{p.get('slug')}  {p.get('chemin')}  {p.get('branche', '')}"
                     for p in liste_projets) or "Aucun projet enregistré."


def erreur(corps: dict) -> str:
    e = corps["error"]
    texte = f"Refus {e['code']} : {e['message']}"
    if e.get("details"):
        texte += f"\n  détails : {json.dumps(e['details'], ensure_ascii=False, default=str)}"
    return texte
