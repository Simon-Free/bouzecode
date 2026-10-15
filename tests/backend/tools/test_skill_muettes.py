# [desc] Une skill ne doit jamais mourir en silence : avertissement sur name manquant + garde sur les stores réels. [/desc]
"""Le piège des skills muettes.

Un `skill.md` à qui il manque `name:` était jeté par le chargeur sans un mot.
Huit fichiers étaient dans ce cas sur le disque, dont deux skills entières de
`demo_application` — on croyait disposer de capacités absentes.
"""
import pytest

from bouzecode.backend.tools.skill.loader import _get_skill_paths, _iter_skill_files
from bouzecode.backend.tools.skill.parsing import _parse_skill_file


def _ecrire(dossier, nom, contenu):
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / nom
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_une_skill_sans_name_est_signalee_sur_stderr(tmp_path, capsys):
    chemin = _ecrire(
        tmp_path / "orpheline", "skill.md",
        '---\ndescription: "ALWAYS LOAD WHEN ..."\n---\n\n# Corps\n',
    )

    assert _parse_skill_file(chemin) is None
    erreurs = capsys.readouterr().err
    assert "frontmatter sans champ 'name'" in erreurs
    assert "skill.md" in erreurs


def test_un_md_sans_frontmatter_reste_silencieux(tmp_path, capsys):
    """Les annexes (`focus.md`, `tables.md`…) ne sont pas des skills ratées :
    les signaler noierait le vrai signal."""
    chemin = _ecrire(tmp_path / "annexes", "focus.md", "# Focus\n\nDu texte.\n")

    assert _parse_skill_file(chemin) is None
    assert capsys.readouterr().err == ""


def test_une_skill_complete_ne_dit_rien(tmp_path, capsys):
    chemin = _ecrire(
        tmp_path / "bonne", "skill.md",
        '---\nname: bonne\ndescription: "ALWAYS LOAD WHEN ..."\n---\n\n# Corps\n',
    )

    assert _parse_skill_file(chemin).name == "bonne"
    assert capsys.readouterr().err == ""


def _skills_muettes_sur_disque():
    """Tout `<store>/<nom>/skill.md` que le chargeur refuse, sur les vrais stores."""
    muettes = []
    vus = set()
    for dossier, _source in _get_skill_paths():
        if not dossier.is_dir() or dossier in vus:
            continue
        vus.add(dossier)
        for fichier in _iter_skill_files(dossier):
            if fichier.name.lower() in ("skill.md", "skill.md".upper()):
                if _parse_skill_file(fichier) is None:
                    muettes.append(str(fichier))
    return muettes


def test_aucune_skill_du_disque_n_est_muette():
    """Garde-fou permanent : un `skill.md` qui ne produit rien est une capacité
    qu'on croit avoir et qu'on n'a pas."""
    muettes = _skills_muettes_sur_disque()

    assert muettes == [], "skills muettes sur disque :\n  " + "\n  ".join(muettes)
