# [desc] Peuple le HOME du bac à sable : vrais petits dépôts git (offline), puis projets, chantiers, micro-tâches à tous les états et VRAIS agents joués contre le faux LLM (live, via l'API HTTP). [/desc]
"""Seed du bac à sable bouzeui.

    python tests/sandbox/seed.py offline   # dépôts git dans $HOME/projets (serveur inutile)
    python tests/sandbox/seed.py live      # tout le reste, PAR L'API (BZ_UI, défaut :5056)

Choix : rien n'est fabriqué à la main dans les stores. Les données passent par les routes
que l'UI appelle, et les conversations sont de VRAIS agents (`python -m bouzecode`) dont le
modèle est le faux LLM (`mock_llm_server.py`). Les états affichés sont donc ceux que le
serveur calcule pour de vrai : livré, planté, question en attente, plan à valider,
manager avec sous-agents, livraison non intégrée, récap avec reste-à-faire.

Doit tourner avec HOME = le HOME du bac à sable (run_sandbox.sh s'en charge) : le script
REFUSE de tourner si HOME ressemble au vrai HOME de l'utilisateur.
"""
from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("HOME", ""))
UI = os.environ.get("BZ_UI", "http://127.0.0.1:5056").rstrip("/")
PROJETS = HOME / "projets"


def _garde_home() -> None:
    if not os.environ.get("BOUZECODE_SANDBOX") and "sandbox" not in str(HOME):
        sys.exit(f"REFUS : HOME={HOME} ne ressemble pas à un HOME de bac à sable "
                 "(lance via tests/sandbox/run_sandbox.sh).")


# ─────────────────────────────── offline : dépôts ───────────────────────────────

def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Camille Dev", "GIT_AUTHOR_EMAIL": "camille@demo.local",
           "GIT_COMMITTER_NAME": "Camille Dev", "GIT_COMMITTER_EMAIL": "camille@demo.local"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout


def _repo(nom: str, fichiers: list[dict[str, str]], messages: list[str]) -> Path:
    """Un dépôt avec un commit par lot de fichiers (historique réaliste)."""
    path = PROJETS / nom
    if (path / ".git").exists():
        return path
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    for lot, message in zip(fichiers, messages):
        for rel, contenu in lot.items():
            f = path / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(contenu, encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", message)
    return path


def offline() -> None:
    _garde_home()
    _repo("demo-api", [
        {"README.md": "# demo-api\n\nAPI de facturation de démonstration (Flask).\n",
         "pyproject.toml": "[project]\nname = \"demo-api\"\nversion = \"0.1.0\"\n"
                           "requires-python = \">=3.11\"\ndependencies = []\n\n"
                           "[tool.uv]\npackage = false\n",
         "src/app.py": "def total(lignes):\n    return sum(l['montant'] for l in lignes)\n"},
        {"src/export.py": "import csv\n\n\ndef exporter(lignes, chemin):\n"
                          "    with open(chemin, 'w', encoding='cp1252', newline='') as f:\n"
                          "        w = csv.writer(f, delimiter=';')\n"
                          "        for l in lignes:\n            w.writerow([l['id'], l['montant']])\n",
         "tests/test_app.py": "from src.app import total\n\n\ndef test_total():\n"
                              "    assert total([{'montant': 2}, {'montant': 3}]) == 5\n"},
        {"src/app.py": "def total(lignes):\n    \"\"\"Somme des montants.\"\"\"\n"
                       "    return sum(l['montant'] for l in lignes)\n"},
    ], ["init: squelette de l'API", "feat: export CSV + premier test", "docs: docstring de total"])
    _repo("demo-front", [
        {"README.md": "# demo-front\n\nFront du portail client.\n",
         "index.html": "<!doctype html><title>Portail</title><div id=app></div>\n",
         "app.js": "document.getElementById('app').textContent = 'Bonjour';\n"},
        {"style.css": "body { font-family: sans-serif; }\n"},
    ], ["init: page d'accueil", "style: police de base"])
    _repo("demo-data", [
        {"README.md": "# demo-data\n\nPipelines de données (SQL + notebooks).\n",
         "sql/ventes.sql": "SELECT region, SUM(montant) FROM ventes GROUP BY region;\n"},
        {"sql/clients.sql": "SELECT * FROM clients WHERE actif = 1;\n"},
    ], ["init: requête ventes", "feat: requête clients actifs"])
    print(f"[seed] dépôts prêts dans {PROJETS}")


# ─────────────────────────────── live : API ───────────────────────────────

#  Boucle locale : jamais par le proxy d'entreprise.
OUVREUR = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@functools.lru_cache(maxsize=None)
def jeton() -> str:
    """Jeton `X-Bouzecode-Token` du serveur du bac à sable, lu où le front le lit (meta)."""
    with OUVREUR.open(UI + "/", timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    return re.search(r'<meta name="bouzecode-token" content="([^"]*)"', page).group(1)


def api(method: str, path: str, body: dict | None = None, ok=(200, 201)) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    en_tetes = {"Content-Type": "application/json"}
    if method != "GET":
        en_tetes["X-Bouzecode-Token"] = jeton()
    req = urllib.request.Request(UI + path, data=data, method=method, headers=en_tetes)
    try:
        with OUVREUR.open(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        texte = e.read().decode("utf-8", "replace")
        if e.code in ok:
            return json.loads(texte or "{}")
        raise RuntimeError(f"{method} {path} → {e.code} {texte[:300]}") from None


def tree() -> list[dict]:
    return api("GET", "/api/agents/tree?offset=0&limit=200").get("nodes", [])


def node(key: str) -> dict:
    return next((n for n in tree() if n.get("key") == key), {})


def attendre(key: str, etats: set[str], delai: float = 120) -> dict:
    fin = time.time() + delai
    n = {}
    while time.time() < fin:
        n = node(key)
        if n.get("state") in etats:
            return n
        time.sleep(2)
    print(f"[seed] ⚠ {key} pas dans {etats} après {delai}s (état {n.get('state')})")
    return n


def dispatch(titre: str, scenario: str, projet: str, isolation: str = "shared") -> str:
    """Le tag de scénario va en 2ᵉ ligne : le titre du ticket reste propre. `defer: false` :
    la réponse porte déjà la clé de l'agent né."""
    body = {"title": titre, "prompt": f"{titre}\n[scn:{scenario}]", "isolation": isolation,
            "defer": False}
    r = api("POST", f"/api/projects/{projet}/tickets", body)
    if not r.get("key"):
        raise RuntimeError(f"dispatch refusé : {r}")
    print(f"[seed] agent {r['key']} ← {scenario:<10} « {titre} » ({r.get('isolation')})")
    return r["key"]


def projets() -> dict[str, str]:
    existants = {p["slug"] for p in api("GET", "/api/projects").get("projects", [])}
    descriptions = {
        "demo-api": "API de facturation (Python/Flask)",
        "demo-front": "Portail client (HTML/JS)",
        "demo-data": "Pipelines SQL et notebooks",
    }
    for nom, desc in descriptions.items():
        if nom not in existants:
            api("POST", "/api/projects", {"name": nom, "path": str(PROJETS / nom), "description": desc})
    print("[seed] projets :", ", ".join(descriptions))
    return descriptions


def chantiers_et_lignes() -> dict[str, str]:
    existants = {m["titre"]: m["id"] for m in api("GET", "/api/macros").get("macros", [])}

    def macro(titre, corps, projets_):
        if titre in existants:
            return existants[titre]
        return api("POST", "/api/macros", {"titre": titre, "corps": corps, "projets": projets_})["macro"]["id"]

    exports = macro("Fiabiliser les exports",
                    "Les exports CSV/Excel cassent à chaque nouveau client.\n\n"
                    "**Périmètre** : demo-api, demo-data. **Hors périmètre** : le front.",
                    ["demo-api", "demo-data"])
    front = macro("Refonte du portail client", "Moderniser le portail, accessibilité AA.", ["demo-front"])
    databricks = macro("Migrer les rapports vers Databricks",
                       "Chantier long : sortir les rapports du SQL Server.", ["demo-data", "demo-api"])

    if api("GET", "/api/micros").get("micros"):
        print("[seed] micro-tâches déjà présentes, on ne les recrée pas")
        return {"exports": exports, "front": front, "databricks": databricks}

    def micro(titre, macro_id, projet="", corps="", decision=False):
        return api("POST", "/api/micros", {"titre": titre, "corps": corps, "macro_id": macro_id,
                                           "projet_slug": projet, "decision": decision})["micro"]["id"]

    # brouillon nu, brouillon enrichi (précisions), prête, faite, abandonnée, décision.
    micro("Gérer le cas du fichier vide dans l'export", exports, "demo-api")
    m = micro("Passer l'export en UTF-8", exports, "demo-api",
              corps="Les clients Excel FR voient des caractères cassés.\n\n"
                    "Fichier : `src/export.py`.")
    api("POST", f"/api/micros/{m}/precisions", {"texte": "Attention : garder le BOM pour Excel.",
                                                 "auteur": "humain"})
    api("POST", f"/api/micros/{m}/precisions", {"texte": "Ajouter un test de non-régression.",
                                                 "auteur": "humain"})
    p = micro("Documenter le format d'export", exports, "demo-data",
              corps="Une page README qui décrit les colonnes.")
    api("POST", f"/api/micros/{p}/pret", {})
    f = micro("Mettre la police du site en variable CSS", front, "demo-front")
    api("POST", f"/api/micros/{f}/etat", {"etat": "faite"})
    a = micro("Réécrire le portail en React", front, "demo-front",
              corps="Idée abandonnée : trop lourd pour le gain.")
    api("POST", f"/api/micros/{a}/etat", {"etat": "abandonnee", "pourquoi": "Trop lourd pour le gain."})
    micro("Databricks : cluster partagé ou dédié ?", databricks, "demo-data",
          corps="Le partagé coûte moins cher, le dédié isole les pics.", decision=True)
    micro("Inventorier les rapports existants", databricks, "demo-data")
    micro("Note en vrac sans chantier", "", "")
    # Une micro LANCÉE (vrai agent, via le chemin de lancement du Bureau).
    lance = micro("Lister les requêtes SQL lentes", databricks, "demo-data",
                  corps="Explorer `sql/` et écrire un NOTES.md.\n[scn:tools]")
    api("POST", f"/api/micros/{lance}/pret", {})
    r = api("POST", f"/api/micros/{lance}/lancer", {"projet_slug": "demo-data"})
    print(f"[seed] micro lancée → {r.get('key') or r}")
    print("[seed] chantiers + lignes créés")
    return {"exports": exports, "front": front, "databricks": databricks}


def conversations() -> None:
    if len(tree()) >= 8:
        print("[seed] conversations déjà présentes, on ne les rejoue pas")
        return
    k_reply = dispatch("Explique la fonction total()", "reply", "demo-api")
    k_recap = dispatch("Corrige l'encodage de l'export CSV", "recap", "demo-api", isolation="worktree")
    k_tools = dispatch("Ajoute un NOTES.md au dépôt", "tools", "demo-front", isolation="worktree")
    k_long = dispatch("Fais un audit détaillé du dépôt", "long", "demo-data")
    k_crash = dispatch("Migre la base de test", "crash", "demo-api", isolation="worktree")
    k_q = dispatch("Branche la base de données", "question", "demo-api", isolation="worktree")
    k_plan = dispatch("Refactore le module d'export", "plan", "demo-api", isolation="worktree")
    k_mgr = dispatch("Orchestre la doc et le choix de base", "subagents", "demo-data", isolation="worktree")
    k_arch = dispatch("Vieille conversation à archiver", "reply", "demo-front", isolation="worktree")

    for k in (k_reply, k_recap, k_tools, k_long, k_arch):
        attendre(k, {"finished", "idle"})  # idle : tour fini, process gardé chaud
    attendre(k_crash, {"finished", "crashed"})
    attendre(k_q, {"awaiting_input"})
    attendre(k_plan, {"awaiting_plan_validation", "awaiting_input"})
    attendre(k_mgr, {"finished", "idle"}, 180)
    api("POST", "/api/conversations/archive", {"keys": [k_arch]})
    print(f"[seed] {k_arch} archivée (récupérable)")
    # Une conversation LANCÉE en dernier, lente : elle tourne encore à la fin du seed.
    dispatch("Rédige la note de version (lent)", "slow", "demo-front")


def live() -> None:
    _garde_home()
    t0 = time.time()
    projets()
    chantiers_et_lignes()
    conversations()
    nodes = tree()
    etats: dict[str, int] = {}
    for n in nodes:
        e = n.get("liveness") if n.get("liveness") == "crashed" else n.get("state")
        etats[e] = etats.get(e, 0) + 1
    print(f"[seed] fini en {time.time() - t0:.0f}s — {len(nodes)} agents : {etats}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "offline"
    {"offline": offline, "live": live}[mode]()
