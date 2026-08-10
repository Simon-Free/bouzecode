"""Garde anti-régression : tout module de route qui APPELLE json_body(...) doit AVOIR
json_body dans ses globals (import). Sinon chaque POST 500 en NameError au runtime — vu en
prod : le refacto fd0031c a extrait json_body dans _body.py mais n'a jamais cable l'import
dans fleet/tickets/builder/projects/sessions -> /api/dispatch et tous les POST morts.
On lit la SOURCE (json_body utilisé ?) et on verifie que le module l'a bien lie."""
import importlib
import pkgutil

from bouzecode.web_v2 import routes as routes_pkg


def _iter_route_modules():
    for info in pkgutil.walk_packages(routes_pkg.__path__, routes_pkg.__name__ + "."):
        if info.name.rsplit(".", 1)[-1].startswith("test"):
            continue
        yield importlib.import_module(info.name)


def test_every_route_using_json_body_imports_it():
    offenders = []
    for module in _iter_route_modules():
        source = ""
        file = getattr(module, "__file__", None)
        if file:
            with open(file, encoding="utf-8") as handle:
                source = handle.read()
        if "json_body(" in source and "json_body" not in module.__dict__:
            offenders.append(module.__name__)
    assert not offenders, f"json_body appelé mais non importé (NameError au POST): {offenders}"
