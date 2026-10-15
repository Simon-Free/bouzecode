# [desc] conftest RACINE : charge les plugins d'étanchéité (HOME jetable, Teams) et --only-changed même quand `addopts` est remplacé (`-o addopts=""`), avant tout autre conftest. [/desc]
"""`pyproject.toml` charge ces plugins par `-p` en tête d'`addopts`. La suite complète se lance
aussi avec `-o addopts=""` (pour retirer le `-m` par défaut) : sans ce fichier, le HOME n'était
plus redirigé et `tests/test_home_etanche.py` ne trouvait pas sa fixture `_home_du_test`. Ce
conftest est le premier chargé (rootdir), avant `tests/conftest.py` et tout import de
`bouzecode` ; un plugin déjà chargé par `-p` n'est pas rechargé."""
pytest_plugins = [
    "bouzecode.web_v2.tests.pytest_home_etanche",
    "bouzecode.web_v2.tests.pytest_teams_etanche",
    "bouzecode.web_v2.tests.pytest_only_changed",
]
