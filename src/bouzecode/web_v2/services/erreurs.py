# [desc] Le refus métier UNIQUE des services : code machine, message français, statut HTTP, détails. Les services le lèvent ; les routes (routes/_errors) le sérialisent — un service n'importe jamais une route. [/desc]
"""Un service qui refuse un geste lève `Refus(code, message, status, **details)`. Le gestionnaire
posé par `routes/_errors.installer` le rend à la forme unique de l'API
`{"error": {"code", "message", "details"?}}` (spec ticketing §9) ; un appelant interne (le Bureau
qui relaie une création de ticket) le relit tel quel, avec le MÊME code (spec §5.4, constat C6)."""
from __future__ import annotations


class Refus(Exception):
    def __init__(self, code: str, message: str, status: int = 409, **details):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details
