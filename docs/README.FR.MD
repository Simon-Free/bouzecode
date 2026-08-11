# Bouzécode

> Un fork de [**CheetahCode**](https://github.com/SafeRL-Lab/clawspring) (Nano Claude Code) par BouzéLab, lui-même inspiré de Claude Code.

**Ce projet est un PoC.** Ce qui compte ici, ce sont les **idées** pour réduire le coût en jetons d'un agent de code *à capacité de modèle égale* — pas la qualité de l'implémentation, honnêtement rugueuse, faute de temps pour la polir. Si une idée vous parle, reprenez-la proprement dans votre propre stack.

L'angle est strict : **réduire le nombre de jetons consommés sans dégrader la capacité de raisonnement** du modèle sous-jacent. On s'interdit donc de basculer sur un modèle plus petit, et on ne travaille que la *forme* du contexte envoyé au modèle haut de gamme.

Bouzécode est un assistant de codage IA en Python, rapide et hackable. Deux visages sur le même moteur : un agent en terminal (REPL), et une interface web qui pilote une flotte d'agents en parallèle.

**Note de langue.** Le moteur, les outils et la documentation de référence sont en anglais, et les deux interfaces le sont par défaut. L'interface web est bilingue : un sélecteur de langue vit dans la barre du haut, à droite des liens *Conversations* / *Agents* / *API* ; il bascule tous les libellés entre anglais et français sans recharger la page, et le navigateur retient le choix. Le terminal écrit en anglais, sauf si `BOUZECODE_LANG` commence par `fr`.

---

## 🎯 Présentation interactive

**[▶ Voir la présentation interactive — l'économie de jetons expliquée](https://simon-free.github.io/bouzecode/)**

Un parcours visuel de la façon dont Bouzécode divise par ~10 la consommation de jetons dans un flux de codage agentique.

---

## Installation

### Prérequis

- **Python** ≥ 3.11 (3.13 est la version que les lanceurs épinglent à la création du venv).
- **[uv](https://astral.sh/uv)** — venv et résolution de dépendances. Installation : `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) ou `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).
- **ripgrep (`rg`)** — vivement recommandé : l'outil `Grep` l'appelle directement. `bouzecode.ps1` l'installe via `winget` s'il manque, et la CLI elle-même en télécharge une copie dans `~/.local/bin` sous Windows quand `rg` est absent du `PATH`. Ailleurs : `brew install ripgrep` ou `apt install ripgrep`.
- Une **clé d'API** pour le fournisseur qui sert votre modèle. Le modèle par défaut est un modèle Anthropic, donc `ANTHROPIC_API_KEY` (ou `ANTHROPIC_AUTH_TOKEN`) est la réponse habituelle ; OpenRouter et une passerelle compatible OpenAI à vous sont les deux autres emplacements — voir [Choisir un fournisseur](#choisir-un-fournisseur).

### Windows (lanceurs autonomes)

```powershell
git clone https://github.com/Simon-Free/bouzecode.git
cd bouzecode
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # ou dans un fichier .env à la racine du dépôt

.\bouzecode.ps1              # agent en terminal (REPL)
.\bouzegui.ps1               # interface web sur http://127.0.0.1:5055
.\bouzegui.ps1 5099          # interface web sur un autre port
```

Les deux lanceurs sont autonomes : ils chargent le `.env`, localisent `uv`, créent le venv, installent le projet en editable et démarrent. `bouzecode.ps1` utilise `.venv/` et vérifie en plus `ripgrep` ; `bouzegui.ps1` utilise un `.venv-ui/` distinct avec l'extra `[web]`. Chacun ne resynchronise les dépendances que si `pyproject.toml` est plus récent que sa marque d'installation.

L'ordre de ces étapes compte : le `.env` est lu **avant** toute installation, si bien que sur un réseau où l'index de paquets n'est joignable qu'à travers un proxy, y écrire `BOUZECODE_PROXY_URL` / `_USER` / `_PASSWORD` — ou les identifiants de votre index — suffit à amorcer depuis un clone nu.

Trois autres scripts vivent à la racine : `bouzecode_publish.ps1` (construit et publie le paquet), `bouzecode_self_update.ps1` (met à jour la copie de travail sur place) et `bouzecode_self_update_detached.ps1` (la variante qui survit au processus qu'elle met à jour). `load_dotenv.ps1` est le lecteur de `.env` qu'ils sourcent tous.

### macOS / Linux

Il n'y a pas de lanceur shell — on installe une fois avec `uv`, puis on appelle les points d'entrée :

```bash
git clone https://github.com/Simon-Free/bouzecode.git
cd bouzecode
uv venv --python 3.13
uv pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...

.venv/bin/bouzecode                          # REPL
.venv/bin/bouzegui                           # interface web, http://127.0.0.1:5056
.venv/bin/python -m bouzecode.web_v2         # la même chose, en module
```

Le `.env` de la racine est chargé par les lanceurs PowerShell et par la suite de tests ; si vous appelez directement les points d'entrée, faites un `source` ou exportez les variables vous-même.

### Ce qui est installé

`pyproject.toml` déclare deux scripts — `bouzecode` (le REPL) et `bouzegui` (l'interface web) — et tire anthropic, openai, httpx, requests, rich, markdown, flask, psutil, pyyaml, prompt-toolkit, tqdm et tree-sitter (avec les grammaires JavaScript et TypeScript). C'est toute l'installation : pas d'étape de compilation, aucun service externe à câbler au-delà de la clé d'API.

Extras optionnels, chacun installable par `uv pip install -e ".[<extra>]"` :

| Extra | Apporte | Pour |
|---|---|---|
| `web` | flask, psutil, pyyaml | l'interface web |
| `test` | pytest, pytest-xdist, pytest-playwright, pytest-timeout | la suite de tests |
| `voice` | sounddevice | la dictée `/voice` |
| `vision` | Pillow | le traitement d'images |

La passerelle Telegram n'a pas d'extra à elle : elle parle à l'API du bot via la bibliothèque standard et n'importe aucun client tiers.

### Choisir un fournisseur

Le modèle décide du fournisseur, et le fournisseur décide de la variable qui doit porter une clé. Le modèle par défaut est celui d'Anthropic, donc une installation nue attend `ANTHROPIC_API_KEY`. Avec une clé pour autre chose, il suffit de nommer un modèle que cet autre chose sert. Trois emplacements :

| Vous avez | À poser | Puis lancer avec |
|---|---|---|
| une clé Anthropic | `ANTHROPIC_API_KEY` (ou `ANTHROPIC_AUTH_TOKEN`) | rien à changer — `opus`, `sonnet`, `haiku`, n'importe quel `claude-*` |
| une clé OpenRouter | `OPENROUTER_KEY` (ou `OPENROUTER_API_KEY`) | `--model deepseek-v4-flash` (aussi `deepseek-v4-pro`, `kimi-k2.7-code`, `kimi-k3`, `glm-5.2`) |
| un point d'accès compatible OpenAI | `BOUZECODE_GATEWAY_API_KEY`, plus `BOUZECODE_GATEWAY_BASE_URL` et `BOUZECODE_GATEWAY_MODELS` | `--model <un des noms que vous avez listés>` |

```bash
export OPENROUTER_KEY=sk-or-...
.venv/bin/bouzecode --model deepseek-v4-flash        # pour ce run seulement
```

```bash
export BOUZECODE_GATEWAY_BASE_URL=https://gateway.example.com/v1
export BOUZECODE_GATEWAY_API_KEY=...
export BOUZECODE_GATEWAY_MODELS=gpt-5,gemini-3-pro
.venv/bin/bouzecode --model gpt-5
```

Pour que le choix tienne, posez-le une fois depuis le REPL : `/model deepseek-v4-flash` l'écrit dans `~/.bouzecode/config.json`, tout comme `/config model=deepseek-v4-flash`, et toutes les sessions suivantes démarrent dessus.

Si le fournisseur du modèle choisi n'a pas de clé, le run s'arrête avant le premier appel : il affiche quels fournisseurs *ont* une clé ici, un `--model` prêt à coller pour chacun, et la variable à poser pour celui que vous avez demandé. C'est une erreur de configuration : sortie en code 2, sans trace d'appels.

### Vérifier

```powershell
.venv\Scripts\bouzecode.exe --version
```
```bash
.venv/bin/bouzecode --version
```

Puis, dans le REPL, `/doctor` — il diagnostique l'installation (interpréteur, git, clé et joignabilité du fournisseur, `rg`, registre d'outils, modules optionnels), nomme ce qui manque et se termine sur une ligne `N passed, N warnings, N failures`.

---

## L'agent en terminal

`bouzecode` ouvre un REPL. Vous exprimez une intention en langage naturel ; l'agent lit le code, fige un plan, puis édite et teste. L'affichage diffuse au fil de l'eau le raisonnement du modèle, chaque appel d'outil au début et à la fin, et un diff coloré après chaque `Write`/`Edit`.

```
$ .venv/bin/bouzecode
> ajoute un flag --dry-run à la commande export, avec un test

  ⏺ Read  src/exporter/cli.py
  ⏺ Grep  "def export"  (content)
  ⏺ WritePlan
  ⏺ Edit  src/exporter/cli.py       +12 -3
  ⏺ Write tests/test_export_dry_run.py
  ⏺ RunPythonTest  tests/test_export_dry_run.py     3 passed
```

Options utiles :

| Option | Effet |
|---|---|
| `-p`, `--print` | Non interactif : exécute le prompt et sort |
| `-m`, `--model MODÈLE` | Impose un modèle pour ce run |
| `--cwd CHEMIN` | Répertoire de travail (défaut : répertoire de lancement) |
| `--profile NOM` | Applique un profil d'agent à l'agent de tête |
| `--accept-all` | Ne demande jamais de permission |
| `--verbose` | Affiche la réflexion et le compte de jetons |
| `--thinking` | Active la réflexion étendue |
| `--loud` | Réflexion visible dans le flux (balises `<thinking>`) |
| `--extra-dir CHEMIN` | Répertoire supplémentaire structuré `.bouzecode` (skills/plugins/profils), répétable |
| `--enable-chrome-devtools` | Attache les outils navigateur (désactivés par défaut : ~5k jetons de schémas) |
| `--session-file` / `--resume-from` | Persiste et restaure l'état de session |
| `--plan-output CHEMIN` | Écrit la réponse finale dans un fichier markdown |
| `--version [TAG]` | Affiche la version ; avec un tag, bascule la copie de travail dessus |

`-p` est fait pour le tube et pour l'intégration continue : il prend le prompt en arguments positionnels, imprime le run et sort. L'animation de chargement ne se peint que sur un vrai terminal, donc une sortie redirigée ne porte que la réponse. Une erreur de configuration — un modèle dont le fournisseur n'a pas de clé — sort en code 2 avec un paragraphe court, sans trace d'appels : c'est ce qui en fait une étape de build utilisable.

```bash
.venv/bin/bouzecode -p "résume ce que fait src/bouzecode/ui/" > reponse.md
```

### Commandes intégrées

| Commande | Effet |
|---|---|
| `/help` `/clear` `/exit` (`/quit`) | Liste les commandes, vide l'historique, quitte |
| `/model [m]` `/config [c=v]` `/cwd [chemin]` | Affiche ou change le modèle, une clé de config, le répertoire de travail |
| `/permissions [mode]` | `auto`, `accept-all` ou `manual` |
| `/thinking` `/verbose` | Cycle la réflexion (off / extended / loud) ; bascule le mode verbeux |
| `/context` `/cost` `/timing` | Remplissage du contexte, estimation de coût, temps passé par outil et par appel LLM |
| `/history` `/diff` `/compact` | Historique, diffs des `Edit`/`Write` récents, compaction de l'historique |
| `/checkpoint` `/rewind` `/revert` | Liste et restaure les points de sauvegarde ; annule jusqu'à la dernière entrée utilisateur |
| `/save` `/load` `/resume` `/where` | Persistance de session et sélecteur interactif |
| `/plan` | Entre ou sort du mode plan |
| `/agent [nom]` `/agents` `/agent-upgrade` | Bascule la session sur un profil ; affiche les agents de fond ; installe les plugins requis par un profil |
| `/skills` `/tasks` (`/task`) `/tools` | Liste les skills, gère les tâches, liste/active/désactive les outils |
| `/export` `/copy` `/init` | Exporte la conversation, copie la dernière réponse, écrit un gabarit `CLAUDE.md` |
| `/memory` `/mcp` `/plugin` | Mémoires enregistrées, serveurs MCP, paquets de plugins (voir [Sous-systèmes](#sous-systèmes)) |
| `/voice` `/video` `/video-wizard` | Dictée, et le pipeline de vidéo scriptée |
| `/doctor` | Diagnostique l'installation |

Taper `/<nom-de-skill>` lance directement une skill ; une commande inconnue est confrontée aux déclencheurs de skills avant d'échouer.

---

## Sous-systèmes

À côté du moteur, sous `src/bouzecode/`, le dépôt conserve un ensemble de paquets à plat à la racine. Ce sont du code vivant : `src/bouzecode/backend/commands/oss_shims/` câble leurs commandes slash dans le dispatcheur, et `backend/tools/registration.py` en importe deux pour leurs outils.

| Paquet | Ce qu'il apporte | Par où on y accède |
|---|---|---|
| `memory/` | Mémoires durables, portée utilisateur ou projet, recherchées et injectées dans le system prompt | `/memory`, et les outils `MemorySave` / `MemoryList` / `MemorySearch` / `MemoryDelete` |
| `mcp/` | Serveurs MCP en stdio ou HTTP ; leurs outils rejoignent le registre au démarrage | `/mcp`, configurés dans `~/.bouzecode/mcp.json` (utilisateur) et `.mcp.json` (projet, cherché depuis `cwd` en remontant) |
| `plugin/` | Paquets d'outils installables par pip, activables par utilisateur ou par projet | `/plugin`, et la page d'édition de profils |
| `voice/` | Capture micro (sounddevice, `arecord` ou `sox`) transcrite dans le prompt | `/voice` — nécessite l'extra `[voice]` |
| `video/` | Pipeline de vidéo scriptée : récit → synthèse vocale → images → sous-titres → assemblage | `/video`, `/video-wizard` |
| `html_renderer/` | Transforme le JSON structuré d'une session en blocs HTML autonomes | utilisé par les chemins de rejeu et d'export |
| `commands/` `tools/` `providers/` `ui/` `skill/` `task/` `checkpoint/` `multi_agent/` `folder_desc/` `xml_tool_protocol/` | Pendants à plat des paquets du moteur, gardés importables pour qu'un plugin ou un script y accède sans passer par `bouzecode.backend` | import direct |

`config.py`, `compaction.py`, `context_gc.py`, `tool_registry.py` et `cloudsave.py` sont livrés comme modules de premier niveau pour la même raison.

---

## L'interface web

```powershell
.\bouzegui.ps1                          # Windows — http://127.0.0.1:5055
```
```bash
.venv/bin/bouzegui --port 5056          # partout — port par défaut 5056
python -m bouzecode.web_v2 --port 5056  # la même chose, en module
```

Le serveur écoute sur `127.0.0.1` et refuse de démarrer si le port est déjà servi. Le principe : **on ne parse jamais le stdout** — toutes les vues sont rendues côté serveur depuis les JSON structurés (session, IPC des agents, dumps de payload).

Toutes les pages fonctionnent hors ligne. Aucune police, feuille de style ou script n'est chargé depuis un hôte tiers : le CSS est local, l'éditeur Monaco est vendorisé dans l'arbre, et la typographie est celle du système. Un outil de développement qui a besoin d'Internet pour afficher un diff est un outil qui s'arrête au mauvais moment.

L'interface parle anglais et français. Le sélecteur est dans la barre du haut, après les liens *Conversations* / *Agents* / *API* ; la bascule repeint les libellés sur place, sans rechargement et sans rien perdre de l'écran, et le navigateur retient le choix pour la visite suivante. Les libellés cités ci-dessous sont ceux de l'anglais, la langue par défaut ; leur équivalent français est entre parenthèses.

### La boîte de réception

`/` redirige vers `/conversations`, la page d'accueil. À gauche, la barre latérale **Conversations** liste tout ce qui tourne ou a tourné, en trois sections — **⚠ Needs attention** (*Nécessite une action*), **● Running** (*En cours*), **Done** (*Terminés*) — si bien que la première chose que vous voyez en arrivant, c'est ce qui vous attend. Les sous-agents sont imbriqués sous l'agent qui les a dispatchés, et un champ de recherche au-dessus de la liste interroge en plein texte les conversations **Open** (*Ouvertes*) ou **All** (*Toutes*).

En haut du panneau de droite, la barre de lancement : une zone de texte — *« New conversation — describe what needs doing (Enter to send)… »* — et une flèche **Send**. Un prompt, un envoi, un agent démarre. Le titre du ticket est la première ligne du prompt.

### Le panneau Options

Repliable sous la zone de prompt, **Options** porte les trois réglages du lancement :

- **Project** (*Projet*) — le dépôt sur lequel l'agent travaillera. Rien n'est deviné : tant que vous n'en avez pas choisi un, la valeur affiche *pick one*, et un lancement sans projet revient en **Project required** avec les projets enregistrés proposés en boutons. Le même panneau ouvre un projet à lui, à partir d'un *nom*, d'un *chemin absolu* et d'une *description* optionnelle ; le bouton **Add** le poste, et un refus du serveur (dossier introuvable, projet déjà ouvert) s'affiche tel quel sous les champs.
- **Agent type** (*Type d'agent*) — la typologie de l'agent (voir ci-dessous).
- **Environment** (*Environnement*) — le mode d'isolation : `shared`, `worktree` ou `worktree+venv` (voir [Modes d'exécution](#modes-dexécution)), chacun avec une ligne décrivant ce qu'il provisionne et quand le choisir.

### Les typologies

`default` est l'agent standard : aucun profil, l'outillage par défaut au complet. Il lit, écrit le code et lance les tests lui-même. À privilégier pour les **tâches courtes et autonomes** — un agent, un arbre de travail, une réponse.

Les profils intégrés vivent dans `src/bouzecode/backend/profiles/builtin/` :

- **`manager`** — un **dispatcheur en lecture seule**. Il dispose de `Read`, `Glob`, `Grep`, `Agent`, `MessageAgent`, `ListAgentTypes` et `Fleet` — ni `Write`, ni `Edit`, ni `Bash`. Il ne code pas, ne teste pas et ne valide pas le travail lui-même. Pour chaque lot il prend exactement trois décisions : **quelle typologie** doit le traiter (choisie via `ListAgentTypes`), **dans quel ordre** les agents s'exécutent (en série quand un résultat en nourrit un autre, en parallèle quand les lots sont indépendants), puis il **agrège les verdicts** que ses enfants rapportent. À privilégier pour les **chantiers qui se découpent** en plusieurs lots indépendants ou enchaînés.
- **`general-purpose`** — le généraliste léger et rapide, avec les skills `commit` et `review`.
- **`coder`** — travail Python dans un worktree isolé, avec contrat de récap.
- **`frontend`** — pilote un navigateur via les outils chrome-devtools pour se relire visuellement : rendu → capture → auto-critique → correction.
- **`meta-agent`** — construire de nouveaux agents, profils, outils et skills ; il délègue l'édition de code lourde plutôt que de la faire lui-même.

Un sixième fichier, `deferred.yaml`, est un *fragment* : pas une typologie sélectionnable, mais un complément de prompt composé dans tout agent de tête, porteur de la règle des commandes Bash différées.

Comme un manager ne peut pas écrire, il est exclu du garde-fou anti-collision : un agent en lecture seule n'écrase personne, il ne force donc jamais un worktree à un voisin.

### Suivre une conversation

Cliquez une conversation pour l'ouvrir en onglet dans le panneau de droite. Chaque onglet porte un sélecteur **Conversation / Recap** — le côté récap s'active à la fin de la session, et affiche d'ici là *available once the session ends* — plus une zone de saisie en bas (*« Message / follow-up… (Enter to send, Ctrl+C to interrupt) »*) pour répondre à une question ou relancer l'agent, et une commande **Relaunch** dans l'en-tête. Un agent mort sans clôture prouvée est marqué **crashed** et propose **Resume** ; **Kill agent** arrête un agent vivant.

`/sessions` liste toutes les sessions enregistrées, et `/sessions/<clé>` en ouvre une en grand, avec quatre onglets :

- **Conversation** — le fil des tours : la réflexion du modèle, puis chaque appel d'outil en bloc dépliable. Le texte arrive au fil de l'eau pendant que l'agent produit encore ;
- **Changed files** (*Fichiers modifiés*) — les diffs produits par le run, rendus côté serveur, avec un éditeur Monaco vendorisé pour une lecture côte à côte (un repli `difflib` couvre l'absence de la copie vendorisée) ;
- **Turns (analysis)** (*Tours (analyse)*) — une ligne par appel LLM : horodatage, Δ durée, jetons in/out, cache lu et cache écrit, % de cache hit, outils appelés, coût. Un clic ouvre le détail : le payload exact envoyé pour cet appel, item par item (système / utilisateur / assistant / résultat d'outil), chacun étiqueté **cached / new-cache / fresh** avec jetons estimés et aperçu lisible, à côté de la réponse du modèle rendue proprement. C'est ainsi qu'on diagnostique une perte de cache sans ouvrir un JSON ;
- **Costs** (*Coûts*) — l'agrégat de coût du run.

Rien n'est jamais effacé. Archiver un ticket ou une conversation le retire du board et le conserve dans son magasin, récupérable.

### L'éditeur de profils

`/agent-builder` compose ou édite un profil en trois étapes — **Identity**, **Capabilities**, **Prompt** : on le nomme ou on en charge un existant comme base, on choisit ses outils, ses skills et ses hooks dans le catalogue, on écrit un complément de prompt, et on déplie **Computed full prompt** pour lire exactement ce que l'agent recevra avant d'enregistrer, pas après. Le résultat est un profil global sous `~/.bouzecode/profiles`, activé dans une session par `/agent <nom>`. La même page installe des plugins, parcourt le catalogue d'agents partagés (**Installed** vs **Available**) et édite les fichiers `.md` des skills sur le disque.

### Pour les agents et les scripts

`GET /api/schema` décrit chaque route `/api/` avec ses paramètres et la forme de sa réponse. Il est **dérivé de la table des routes Flask**, jamais saisi à la main : il ne peut donc pas décrire une route disparue ni ignorer une route ajoutée. Les endpoints de lecture renvoient du JSON structuré ; `GET /api/sessions/<clé>/blocks?plain=1` renvoie les messages en texte brut pour analyse par un agent. `GET /api/search?q=<mots>&scope=open|all` fouille les conversations elles-mêmes — les messages de l'utilisateur et le rapport `FinalAnswer` du modèle, à l'exclusion du thinking et des résultats d'outils bruts — et rend chaque occurrence avec son ticket et un extrait de contexte.

### Périmètre de sécurité

**L'interface web est un outil de développeur mono-utilisateur, à réserver à `localhost`.** Son profil de risque est celui d'un notebook Jupyter lancé sans jeton :

- Aucune authentification. Aucune protection CSRF.
- Exécution de code à distance par construction (dispatcher un ticket lance un agent).
- Elle écoute `127.0.0.1` par défaut. **Ne l'exposez pas sur `0.0.0.0`**, ne la placez pas derrière un reverse proxy.

---

## Modes d'exécution

Un agent s'exécute dans l'un de trois environnements. Le choix est explicite — fait par celui qui lance, ou par le manager quand il dispatche, parce qu'eux seuls savent si trois agents s'apprêtent à écrire dans le même dépôt ou si un seul va toucher à `pyproject.toml`.

| Mode | Ce que ça provisionne | Quand le choisir |
|---|---|---|
| `shared` | rien — le dépôt principal | lecture seule, seul écrivain, tâche courte |
| `worktree` | un worktree git dédié, sans venv | plusieurs agents écrivent en parallèle |
| `worktree+venv` | un worktree git **et** un venv dédiés | l'agent touche aux dépendances |

Trois valeurs, pas deux booléens : « pas de worktree mais un venv dédié » n'a pas de sens et n'a pas à être représentable. Séparer le worktree du venv, c'est là qu'est la latence — un worktree git est quasi gratuit, un venv c'est un `uv sync` par agent.

Un agent en `worktree` hérite du venv du dépôt de base via `VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT` et un préfixe de `PATH` : il ne se fabrique donc pas en silence un venv d'un gigaoctet au premier `uv run`. La contrepartie est assumée : un tel agent qui lance `uv sync` modifie le venv de base partagé — raison précise pour laquelle un agent qui va toucher aux dépendances relève de `worktree+venv`.

**Garde-fou anti-collision.** Deux agents `shared` qui *écrivent* dans le même dépôt s'écraseraient mutuellement. C'est la seule erreur vraiment destructrice, donc le serveur la rattrape : le second bascule en `worktree` et un commentaire sur le ticket l'explique. Les agents incapables d'écrire — le `manager` en lecture seule, par exemple — ne sont pas comptés, puisqu'ils n'écrasent personne. Le fait qu'un agent puisse écrire est dérivé des outils que son profil accorde réellement, pas du nom de sa typologie.

Les worktrees vivent sous `~/.bouzecode/worktrees/` ; `BOUZECODE_WORKTREE_ROOT` porte le worktree courant jusque dans le system prompt de l'agent.

---

## Configuration

### Où vivent les choses

| Chemin | Contenu |
|---|---|
| `~/.bouzecode/config.json` | réglages persistants |
| `~/.bouzecode/sessions/` | journaux de session (`daily/AAAA-MM-JJ/`, plus `history.json`) |
| `~/.bouzecode/skills/` | vos skills globales |
| `~/.bouzecode/profiles/` | vos profils d'agent globaux |
| `~/.bouzecode/agent_catalog/` | le catalogue d'agents partagés, une fois tiré |
| `~/.bouzecode/mcp.json` | serveurs MCP au niveau utilisateur |
| `~/.bouzecode/worktrees/` | les worktrees des agents |
| `~/.bouzecode/web_v2/` | projets et tickets servis par l'interface web |
| `<projet>/.bouzecode/` | `skills/`, `plugins/`, `profiles/` propres au projet |
| `<projet>/.mcp.json` | serveurs MCP propres au projet |

Les réglages sont lus depuis `config.json` par-dessus les valeurs par défaut de `backend/core/config.py`. Ceux que vous toucherez le plus :

| Clé | Défaut | Sens |
|---|---|---|
| `model` | `claude-opus-4-8` | modèle des nouvelles sessions |
| `max_tokens` | `64000` | plafond de sortie par tour |
| `permission_mode` | `auto` | `auto`, `accept-all` ou `manual` |
| `thinking` / `thinking_mode` | `true` / `extended` | `extended` (réflexion API) ou `loud` (balises `<thinking>` visibles) |
| `thinking_effort` | `high` | `low`, `medium`, `high`, `max` |
| `max_tool_output` | `32000` | seuil de troncature d'un résultat d'outil |
| `max_agent_depth` | `3` | profondeur d'imbrication des sous-agents |
| `max_concurrent_agents` | `3` | sous-agents en parallèle par parent |
| `task_classification` | `false` | route automatiquement une session vers un profil d'après son premier prompt |
| `extra_dirs` | `[]` | répertoires `.bouzecode` supplémentaires, persistés d'un run à l'autre |

On les pose depuis le REPL avec `/config clé=valeur`, ou en éditant le fichier.

### Fournisseurs de modèles

Le routage est une fonction pure de la chaîne du modèle (`backend/agent/providers/registry.py`) : `resolve_provider()` associe ce que vous tapez à un fournisseur et à un identifiant d'API, si bien que `--model sonnet` et `--model deepseek-v4-flash` fonctionnent tous les deux. Un préfixe explicite `fournisseur/modèle` l'emporte sur le routage.

| Fournisseur | Clé | Endpoint | Modèles |
|---|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` ou `ANTHROPIC_AUTH_TOKEN` | l'API officielle, ou toute passerelle compatible Anthropic via `ANTHROPIC_BASE_URL` | `claude-*`, ainsi que les alias `opus` / `sonnet` / `haiku` |
| `openrouter` | `OPENROUTER_KEY` (ou `OPENROUTER_API_KEY`) | `https://openrouter.ai/api/v1` | `deepseek-v4-flash`, `deepseek-v4-pro`, `kimi-k2.7-code`, `kimi-k3`, `glm-5.2` |
| `gateway` | `BOUZECODE_GATEWAY_API_KEY` | `BOUZECODE_GATEWAY_BASE_URL` | ce que vous listez dans `BOUZECODE_GATEWAY_MODELS` |

L'emplacement `gateway` est un **endpoint compatible OpenAI qui vous appartient** — LiteLLM, vLLM, un proxy maison. Rien n'y est écrit en dur : endpoint, clé et liste de modèles viennent tous de l'environnement (voir [Choisir un fournisseur](#choisir-un-fournisseur) pour les trois variables), donc le fournisseur reste inerte tant que vous ne le pointez nulle part. Les noms de modèles sont transmis tels quels à la passerelle : ils doivent donc être exactement ceux qu'elle attend. Les tarifs entrée/sortie par modèle et les surcharges de tarif de lecture de cache vivent dans le même fichier et alimentent les colonnes de coût de l'interface web.

**Protocole d'appel d'outil.** Les fournisseurs compatibles OpenAI utilisent le function calling natif. Les endpoints Anthropic utilisent le protocole XML, sauf si vous demandez le natif avec `BOUZECODE_ANTHROPIC_NATIVE_TOOLS=1` (`0` reforce le XML) ; un profil ou une config qui pose `xml_tools` l'emporte sur les deux.

### Variables d'environnement

| Variable | Effet |
|---|---|
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | identifiants Anthropic |
| `ANTHROPIC_BASE_URL` | pointe le transport Anthropic vers une passerelle compatible |
| `OPENROUTER_KEY` / `OPENROUTER_API_KEY` | identifiants OpenRouter |
| `BOUZECODE_GATEWAY_BASE_URL` / `_API_KEY` / `_MODELS` | l'emplacement passerelle compatible OpenAI |
| `EXA_KEY` | clé de l'API de recherche Exa, que `WebSearch` privilégie ; sans elle l'outil retombe sur un moissonnage de DuckDuckGo |
| `BOUZECODE_LANG` | langue du terminal : toute valeur commençant par `fr` écrit en français, tout le reste en anglais |
| `BOUZECODE_NATIVE_TOOL_ENDPOINTS` | endpoints qui doivent utiliser le function calling natif |
| `BOUZECODE_ANTHROPIC_NATIVE_TOOLS` | `1` outils natifs, `0` protocole XML |
| `BOUZECODE_ENABLE_CHROME_DEVTOOLS` | `1` charge les outils navigateur (équivalent de `--enable-chrome-devtools`) |
| `BOUZECODE_CACHE_TTL_1H` | `1` demande le TTL de cache de prompt d'une heure sur les endpoints non officiels |
| `BOUZECODE_NO_PLUGINS` | saute entièrement le chargement des plugins (CI, tests hermétiques) |
| `BOUZECODE_NO_ENFORCE` | désactive les appels de rattrapage méthodologie/snippet |
| `BOUZECODE_AGENT_CATALOG_URL` / `_PATH` | URL git, ou chemin local, du catalogue de profils d'agents partagés |
| `BOUZECODE_GITLAB_URL` | URL de base de l'instance GitLab qui héberge vos plugins |
| `BOUZECODE_WORKTREE_ROOT` | le worktree dans lequel tourne l'agent, exposé dans son system prompt |
| `BOUZECODE_LAUNCH_CWD` | répertoire de travail par défaut en l'absence de `--cwd` |
| `BOUZECODE_TOOL_OUTPUT_DIR` | où sont déversées sur disque les sorties d'outil surdimensionnées |
| `BOUZECODE_WEB_BASE_URL` | URL de base à laquelle les agents postent leur hook de complétion |
| `BOUZECODE_PROXY_URL` / `_USER` / `_PASSWORD` | proxy HTTP sortant, si votre réseau en impose un |

---

## Étendre

Quatre points d'extension, par engagement croissant.

### Skills

Une skill est un gabarit de prompt réutilisable : un fichier markdown à frontmatter YAML, exposé au modèle par les outils `Skill` / `SkillList` / `SkillGrep` et à vous comme commande slash.

```markdown
---
name: commit
description: Indexe, rédige un message de commit conventionnel, et commite.
triggers: ["/commit", "commite mes changements"]
tools: [Bash, Read]      # `allowed-tools` est accepté au même sens
scope: ""                # "" = global ; un chemin restreint la skill à ce sous-arbre
context: inline          # `inline` l'exécute dans le tour courant, `fork` dans un sous-agent
---

Lis le diff indexé, puis …
```

Seul `name` est obligatoire ; sans `triggers`, la skill répond à `/<name>`. Les skills sont découvertes dans les `.bouzecode/skills/` et `.claude/skills/` du répertoire courant **et de ses ancêtres** (le plus proche l'emporte, ce qui fait fonctionner un monorepo), puis dans `~/.bouzecode/skills/` et `~/.claude/skills/`, puis dans tout `--extra-dir`.

### Profils d'agent

Un profil est un fichier YAML qui déclare ce qu'est un agent : sa liste blanche d'outils, ses skills, ses hooks, un modèle optionnel, et un complément de system prompt.

```yaml
name: reviewer
description: Lit un diff et rapporte, n'édite jamais.
tools: [Read, Glob, Grep, GetDiff]
skills: [review]
hooks: [run_completion_chain]
model: ""
system_prompt_extra: |
  Tu relis, tu ne corriges pas. …
```

L'ordre de résolution est builtin < `~/.bouzecode/profiles/` < `<cwd>/.bouzecode/profiles/` < chemins `--extra-dir`, si bien qu'un projet peut masquer un agent intégré sous le même nom. Un `tools: []` vide signifie *aucune restriction* ; une liste non vide est appliquée telle quelle, et les outils de cadre (`Methodology`, `Snippet`, `FinalAnswer`, `Skill`, `SkillList`, `TaskList`, `GetDiff`, `WritePlan`, `LoadProjectConfig`, `AskUserQuestion`, `AgentsMap`, `SymbolMap`) s'y ajoutent toujours — un profil ne peut jamais retirer la machinerie de discipline sous le prompt qui la prescrit.

Pointez `BOUZECODE_AGENT_CATALOG_URL` vers un dépôt git organisé en `profiles/*.yaml` et le volet catalogue de l'éditeur de profils — ainsi que `/agent` dans le REPL — proposera ses profils à l'installation, en tirant au passage les plugins requis.

### Plugins

Un plugin est un paquet installable par pip qui apporte des outils. Il expose une liste `TOOLS` de dictionnaires purs, et n'importe donc jamais bouzecode :

```python
TOOLS = [
    {
        "name": "QueryWarehouse",
        "description": "Exécute une requête SQL en lecture seule sur l'entrepôt analytique.",
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
        "func": run_query,        # (params: dict, config: dict) -> str
        "read_only": True,
        "concurrent_safe": True,
    },
]
```

Les plugins s'installent au niveau utilisateur ou projet, depuis un index de paquets ou depuis une source git, et s'activent ou se désactivent individuellement. Un profil peut déclarer `requires_plugins` : installer ce profil les matérialise. `BOUZECODE_NO_PLUGINS=1` court-circuite toute la couche.

### Serveurs d'outils externes

Deux chemins, qui atterrissent dans le même registre.

**Serveurs MCP.** Déclarez-les dans `~/.bouzecode/mcp.json` ou dans un `.mcp.json` posé à côté de votre code (même format que le `.mcp.json` de Claude Code), en stdio ou en HTTP. Ils sont initialisés au démarrage et leurs outils sont enregistrés après la passe de liste blanche, ils restent donc actifs :

```json
{
  "mcpServers": {
    "mon-serveur": { "command": "npx", "args": ["-y", "@example/mcp-server"] }
  }
}
```

**chrome-devtools.** `--enable-chrome-devtools` démarre un serveur MCP chrome-devtools par thread d'agent et enregistre ses outils navigateur — navigate, snapshot, screenshot, evaluate. Il est désactivé par défaut parce que ses schémas coûtent environ 5k jetons à chaque tour, ce qui contredit le propos du projet tant qu'un navigateur n'est pas réellement nécessaire. La paire toujours active `EnableChromeDevtools` / `DisableChromeDevtools` permet au modèle de les allumer en cours de session. Le profil `frontend` est bâti autour.

---

## Pourquoi ça compte : les jetons d'entrée font toute la facture

Un agent de code qui enveloppe un modèle haut de gamme ne reste abordable qu'à condition de regarder en face **où part l'argent**.

**Les jetons de sortie sont quasi gratuits comparés aux jetons d'entrée.** Le modèle émet quelques centaines à quelques milliers de jetons de sortie par tour. L'entrée, elle, est la **somme arithmétique cumulée** du préfixe grandissant réémis à chaque aller-retour : system prompt + schémas d'outils + toute la conversation jusqu'ici + dernier résultat d'outil.

Un calcul de coin de table : system prompt de 10k jetons, 2k jetons d'entrée neufs par tour. Trois tours facturent déjà `10k + 12k + 14k = 36k` jetons d'entrée. Une tâche de code typique fait **50 à 100 appels d'outils**, chacun avec un aller-retour LLM complet, et le fournisseur facture volontiers chaque retransmission du préfixe.

L'argent n'est que la moitié du sujet. Chaque aller-retour est aussi une attente en file. Un temps au premier jeton de 30–40 s en charge est courant — 40 allers-retours à ce rythme brûlent du temps réel, quel que soit le budget.

**Économiser, c'est supprimer des allers-retours.** Tout le reste de ce README en découle.

### Résultats observés

Évalué sur une poignée de tâches (**n = 5**, donc raisonnez en ordres de grandeur, pas en valeurs absolues) : corrections de bugs et ajouts de fonctionnalités habituels sur une base d'environ 100k lignes, les deux systèmes lancés sur les mêmes prompts.

- ~**10× moins de jetons consommés par le modèle haut de gamme**, et disparition totale de la consommation de petit modèle (typiquement : 1,5 M Opus + 3 M Haiku → 200k Opus, 0 Haiku).
- À peu près la même **division par ~10 du prix**.
- **3 à 5× moins de temps réel pour arriver au correctif**, grâce aux allers-retours et aux attentes en file économisés.
- Les gains s'élargissent encore sur les longues sessions, grâce à l'élagage du contexte.

Ce sont des ordres de grandeur sur un petit n ; à traiter comme des signaux, pas comme un benchmark.

---

## Les trois mécanismes

### 1. Tours LLM : viser le minimum théorique

Emballer dans un tour tout ce qui pouvait tenir dans un tour. Le system prompt oriente le modèle vers un flux en trois phases qui vise **3 tours LLM comme plancher** pour une tâche complète :

- **Phase 1 — LIRE** : `Read`, `Glob`, `Grep`, `GetFolderDescription`, `Skill(...)` dans un seul lot parallèle
- **Phase 2 — PLANIFIER** : un unique appel `WritePlan` qui fige le plan complet
- **Phase 3 — EXÉCUTER** : éditions + tests + diagnostics dans un seul bloc, ordonnés par `depends_on`

L'exécuteur de DAG (`backend/agent/dag.py`) construit le graphe de dépendances à partir des déclarations `depends_on` et exécute les outils niveau par niveau, en parallèle à l'intérieur de chaque niveau, dans un seul tour.

### 2. Exploration pré-indexée

`GetFolderDescription` remplace le motif de « sous-agent d'exploration » séquentiel — qui brûle typiquement des dizaines de milliers de jetons — par un outil natif qui renvoie une arborescence annotée en quelques centaines. Les descriptions sont générées et maintenues automatiquement par des hooks d'écriture. `AgentsMap` et `SymbolMap` étendent la même idée à une carte du dépôt dossier par dossier et à ses symboles : trouver une fonction coûte une consultation, pas un balayage de grep.

### 3. Le modèle élague son propre contexte

Le modèle marque les résultats d'outils périmés pour suppression (`trash`), ne garde que les tranches pertinentes (`Snippet` fige des plages de lignes d'un résultat d'outil) et tient un brouillon nommé (la note `Methodology`, en append-only). Le contexte reste **plat** au lieu de gonfler de tour en tour. Des appels de rattrapage rendent la tenue de livre non optionnelle : une lecture non snippetée ou une entrée de méthodologie manquante est rattrapée avant le tour suivant plutôt que laissée à la dérive.

### Bonus : chasser les erreurs récurrentes

Observer les erreurs que le modèle commet systématiquement et les prévenir par le prompt ou par les défauts des outils. Exemples : passer le défaut de `Grep` en mode `content`, détourner de `python -c` sous Windows, interdire les relectures inutiles, convertir les `offset`/`limit` 0-indexés de `Read` depuis les `ranges` 1-indexés que le modèle tape sans cesse.

### Pistes ouvertes

Idées non testées, laissées ouvertes :

- **Pré-lectures par un modèle plus petit.** Faire exécuter les `Read` de cadrage par un modèle intermédiaire, qui ne rend au modèle haut de gamme que les extraits pertinents.
- **Cache du system prompt.** Dépend du fournisseur ; ~30 % d'économie supplémentaire estimée avec des prompts partagés.
- **Catalogue d'erreurs récurrentes plus large.** Travail d'observation continu, dépendant des erreurs propres à chaque stack.

---

## Architecture

```
bouzecode/
├── src/
│   ├── bouzecode/
│   │   ├── backend/                  # le moteur
│   │   │   ├── agent/                # boucle de tour, DAG d'outils, streaming, compaction
│   │   │   │   ├── hooks/            # le pipeline de hooks de complétion
│   │   │   │   └── providers/        # registre de fournisseurs + backends de streaming
│   │   │   ├── checkpoint/           # sauvegardes de fichiers et instantanés de conversation
│   │   │   ├── chrome_devtools/      # client MCP chrome-devtools, sur option
│   │   │   ├── commands/             # commandes slash du REPL (+ oss_shims/)
│   │   │   ├── context_manager/      # note de méthodologie, snippets, notes, compaction
│   │   │   ├── core/                 # config, chemins, registre d'outils, assemblage du prompt
│   │   │   ├── multi_agent/          # lancement de sous-agents, isolation, files de messages
│   │   │   ├── plugin/               # extensions installables par pip
│   │   │   ├── profiles/             # profils d'agent : builtin/, découverte, composeur, catalogue
│   │   │   ├── tools/                # outils intégrés + ops/, agents_map/, folder_desc/,
│   │   │   │                         #   skill/, task/, projects_tool/
│   │   │   └── xml_tool_protocol/    # protocole d'appel d'outil textuel (parseur, émetteur, docs)
│   │   ├── ui/                       # façade terminal : CLI, REPL, rendu, rejeu
│   │   └── web_v2/                   # interface web Flask
│   │       ├── routes/               # blueprints de l'API JSON
│   │       ├── services/             # logique métier, sans Flask, testable seule
│   │       ├── runtime/              # cycle de vie des agents : runner, IPC, warm pool, contexte
│   │       ├── templates/            # conversations, session, agent-builder
│   │       └── static/               # CSS thème sombre, modules ES, dictionnaires i18n,
│   │                                 #   Monaco vendorisé (aucun CDN)
│   └── system_prompts/               # les fragments de prompt, livrés dans le wheel
├── memory/  mcp/  voice/  video/  plugin/  html_renderer/  …   # voir Sous-systèmes
├── readme_sync/                      # maintient les cartes README des dossiers en phase avec le code
├── docs/                             # cette documentation et les pages du projet
├── tests/                            # la suite de tests
├── bouzecode.ps1  bouzegui.ps1       # lanceurs Windows (ASCII pur, .env avant l'install)
├── load_dotenv.ps1                   # le lecteur de .env qu'ils partagent
└── bouzecode_publish.ps1  bouzecode_self_update.ps1
```

### La boucle

1. Prompt utilisateur → protocole d'outils (function calling natif ou XML, selon le fournisseur) → le modèle émet ses appels d'outils
2. L'exécuteur de DAG construit le graphe de dépendances à partir des déclarations `depends_on`
3. Les outils s'exécutent niveau par niveau, en parallèle à l'intérieur de chaque niveau
4. Les résultats sont réinjectés dans le contexte → tour suivant

### L'outillage

46 outils sont enregistrés. Tous ne sont pas envoyés au modèle : les outils de cadre et un jeu de travail par défaut sont actifs dès l'import, le reste s'allume par un profil d'agent, par `/tools enable`, ou par une extension.

| Groupe | Outils |
|---|---|
| Fichiers & shell | `Read` `Write` `Edit` `NotebookEdit` `Bash` `BashOutput` `Glob` `Grep` `RunPythonTest` `GetDiagnostics` `GetDiff` |
| Navigation | `GetFolderDescription` `AgentsMap` `SymbolMap` |
| Discipline de contexte | `Methodology` `Snippet` `FinalAnswer` |
| Planification & tâches | `WritePlan` `EnterPlanMode` `ExitPlanMode` `TaskCreate` `TaskUpdate` `TaskGet` `TaskList` |
| Skills | `Skill` `SkillList` `SkillGrep` |
| Mémoire | `MemorySave` `MemoryList` `MemorySearch` `MemoryDelete` |
| Flotte | `Agent` `MessageAgent` `SendMessage` `CheckAgentResult` `ListAgentTasks` `ListAgentTypes` `Fleet` |
| Web | `WebFetch` `WebSearch` |
| Interaction | `AskUserQuestion` `SleepTimer` |
| Projets | `AddProject` `LoadProjectConfig` |
| Navigateur (sur option) | `EnableChromeDevtools` `DisableChromeDevtools` + les outils chrome-devtools |

Actifs par défaut : les douze outils de cadre (`Methodology`, `Snippet`, `FinalAnswer`, `Skill`, `SkillList`, `TaskList`, `GetDiff`, `WritePlan`, `LoadProjectConfig`, `AskUserQuestion`, `AgentsMap`, `SymbolMap`) plus `Read`, `Write`, `Edit`, `Bash`, `BashOutput`, `Glob`, `Grep`, `RunPythonTest`, `WebFetch`, `WebSearch`, `AddProject`, `MemorySave`, `MemoryList` — et la paire d'amorçage chrome-devtools. Les outils MCP les rejoignent dès qu'un serveur est configuré.

---

## Tests

La suite tourne contre un modèle scripté. Un garde hermétique dans `tests/conftest.py` **bloque tout appel LLM réel** tant qu'un test ne l'a pas explicitement demandé : une clé manquante ne peut donc jamais se transformer en facture surprise.

```powershell
uv pip install -e ".[test]"
.venv\Scripts\python.exe -m pytest -q                        # toute la suite
.venv\Scripts\python.exe -m pytest -q -n auto                # en parallèle, via pytest-xdist
.venv\Scripts\python.exe -m pytest -q -m backend             # le moteur seul
.venv\Scripts\python.exe -m pytest -q tests\web_v2           # la couche service du web
```
```bash
uv pip install -e ".[test]"
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q -n auto
.venv/bin/python -m pytest -q -m backend
.venv/bin/python -m pytest -q tests/web_v2
```

`testpaths` vaut `tests/`. Chaque test est marqué automatiquement d'après le dossier où il vit : `tests/backend/` → `backend`, `tests/ui/` → `ui`, `tests/web_v2/` → `web`. Un quatrième marqueur, `slow`, étiquette les fichiers-cibles que visent les tests du lanceur de tests. Le paquet `web_v2` porte aussi ses propres tests sous `src/bouzecode/web_v2/tests/` — ils prennent le marqueur `web` eux aussi et se lancent en pointant pytest sur ce chemin, puisque `testpaths` n'entre pas dans `src/`.

Le JavaScript de l'interface a sa propre suite, sous `src/bouzecode/web_v2/tests/js/` : les vrais modules de `static/js/` chargés dans un DOM simulé (happy-dom) et pilotés par clics et événements, sans navigateur.

```bash
cd src/bouzecode/web_v2
npm install
npm test
```

`tests/backend/TEST_METHODOLOGY.md` énonce la politique. En résumé : **un test doit se comprendre sans ouvrir le code qu'il teste** — on le lit comme une histoire, *l'utilisateur demande X, l'agent fait Y, on observe Z*. La suite est donc dominée par des tests de conversation, qui pilotent l'agent comme le ferait un humain, plutôt que par des tests unitaires de fonctions internes. Quatre niveaux, toujours prendre le plus haut qui suffit :

1. **`mock_llm`** — le défaut, ~90 % des cas. Seules les réponses du modèle sont scriptées ; la boucle, les outils, l'enforcement et la méthodologie tournent pour de vrai. Pas de réseau, pas de navigateur.
2. **`mock_api`** — le transport, et rien d'autre. Un faux serveur SSE avec le vrai client pointé dessus : sérialisation sur le fil, parsing SSE, `cache_control`, retry. Lent — un serveur par appel.
3. **Client de test Flask** — le défaut pour `web_v2`. Comportement HTTP, JSON, codes de retour, effets de bord observables côté serveur, sans navigateur.
4. **Playwright** — dernier recours, strictement réservé à ce que seul un vrai DOM prouve : rendu en streaming, interaction réelle de l'utilisateur, ordre de repaint.

La suite JavaScript se glisse entre ces deux derniers niveaux : elle fait tourner les vrais scripts de l'interface avec de vrais événements, ce qui est exactement ce qui maintient le niveau Playwright aussi petit que la politique l'exige.

---

## Contribuer

Deux documents à lire avant d'écrire quoi que ce soit :

- **les cartes `README.md` de dossier** — chaque dossier de code porte la sienne, avec son objet, ses sous-dossiers et ses symboles. C'est le chemin le plus court vers une fonction sans grep. `python -m readme_sync --check` parcourt l'arbre et sort en 0 quand chaque carte colle à son code ; `--list-stale` nomme celles qui ont divergé, `--regen` en reconstruit une. Le nom du fichier est un réglage et non une constante — `--doc-name`, la variable `README_SYNC_DOC_NAME`, ou `[tool.readme_sync] doc_name` dans `pyproject.toml`, du plus spécifique au moins — si bien que le même outil entretient un arbre d'`AGENTS.md` ailleurs ; ici c'est `README.md`.
- **`tests/backend/TEST_METHODOLOGY.md`** — la politique de test en quatre niveaux ci-dessus.

Où changer quoi :

| Vous voulez changer | Commencez par |
|---|---|
| Une commande slash | `backend/commands/dispatcher.py` — la table `COMMANDS` et ses handlers |
| Une commande adossée à un paquet à plat | `backend/commands/oss_shims/` |
| La boucle de tour, le streaming, l'enforcement | `backend/agent/loop.py`, `loop_turn.py`, `dag.py` |
| Le schéma ou le comportement d'un outil | `backend/tools/schemas.py` + `backend/tools/ops/` |
| Quels outils existent tout court | `backend/core/tool_registry.py` et `backend/tools/registration.py` |
| Un modèle, un tarif, une règle de routage | `backend/agent/providers/registry.py` |
| Le system prompt | `backend/core/context.py` et `src/system_prompts/` |
| Un agent intégré | `backend/profiles/builtin/*.yaml` |
| Une page ou un endpoint web | `web_v2/routes/` (HTTP) puis `web_v2/services/` (logique) |

Trois conventions à connaître : le schéma d'API est dérivé de la table des routes plutôt qu'écrit à la main ; l'interface web ne parse jamais le stdout — si vous voulez afficher quelque chose, émettez-le dans le JSON de session structuré ; et chaque `.ps1` de la racine est en **ASCII pur**, puisque Windows PowerShell 5.1 relit un script sans BOM en ANSI et abîme tout ce qui dépasse 127. Un test parcourt les lanceurs et échoue au premier octet non-ASCII, ainsi que sur tout lanceur qui installerait des dépendances avant de charger le `.env`.

Pour aller plus loin : [l'architecture](./architecture.md) — la forme du code et les règles qui la tiennent — et le [guide du contributeur](./contributor_guide.md), qui associe chaque « je dois changer X » au fichier qui le porte.

---

## Crédit

Base : [**CheetahCode / Nano Claude Code**](https://github.com/SafeRL-Lab/clawspring) (SafeRL-Lab). Licence du projet d'origine préservée ([LICENSE](../LICENSE)).

---

## Licence

Apache-2.0. Voir [LICENSE](../LICENSE).
