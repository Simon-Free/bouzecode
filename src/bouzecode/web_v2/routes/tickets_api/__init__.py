# [desc] Blueprints de l'API cible des tickets (spec ticketing §6) : tickets, gestes, livraison, rangement, agents, route interne de fin de run (les alias dépréciés ont été retirés au lot L6). [/desc]
from .agents import agents_api_bp
from .gestes import gestes_bp
from .interne import interne_bp
from .livraison import livraison_bp
from .rangement import rangement_bp
from .tickets import tickets_v3_bp

BLUEPRINTS = (tickets_v3_bp, gestes_bp, livraison_bp, rangement_bp, agents_api_bp, interne_bp)
