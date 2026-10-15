"""Execution distante sur Rundeck rec : `lancer_sur_rundeck`, `lancer_tests_sur_rundeck`, `suivre`, `recuperer`.

Import paresseux recommande cote appelant (`from bouzecode.remote import lancer_sur_rundeck`) :
ce paquet n'ouvre aucune connexion a l'import.
"""
from bouzecode.remote.lancement import lancer_sur_rundeck
from bouzecode.remote.suivi import recuperer, suivre
from bouzecode.remote.tests_distants import lancer_tests_sur_rundeck

__all__ = ["lancer_sur_rundeck", "lancer_tests_sur_rundeck", "recuperer", "suivre"]
