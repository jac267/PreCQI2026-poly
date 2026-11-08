"""Votre bot. C'est le seul fichier que vous avez besoin de modifier.

decide() est appelée à chaque tour avec l'état du jeu et doit retourner vos ordres.
Pour l'instant, chaque déneigeuse se déplace au hasard.
"""

import random

from models import GameState, Orders


def decide(state: GameState) -> Orders:
    orders = Orders()
    for plow in state.my_plows:
        orders.move(plow, random.choice(["N", "S", "E", "O"]))
    return orders
