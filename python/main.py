"""Boucle réseau : lit l'état du jeu, appelle bot.decide(), envoie les ordres.

Vous n'avez normalement pas besoin de modifier ce fichier.
"""

import json
import os
import time
import traceback
import urllib.error
import urllib.request

import bot
from models import GameState, Orders

SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8080/teams/red").rstrip("/")


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(SERVER_URL + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=35) as resp:
        return json.load(resp)


def main():
    print(f"connexion à {SERVER_URL}", flush=True)
    tick = -1
    while True:
        try:
            state = GameState.from_dict(request(f"/state?after={tick}"))
        except urllib.error.HTTPError as e:
            if e.code == 410:
                print("partie terminée :", e.read().decode(), flush=True)
                return
            if e.code != 408:          # 408 : aucun nouveau tour, on redemande
                print("erreur du serveur :", e.code, flush=True)
                time.sleep(0.5)
            continue
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.5)            # serveur pas encore prêt
            continue

        tick = state.tick
        for error in state.errors:
            print(f"tour {tick} : ordre refusé {error}", flush=True)
        try:
            orders = bot.decide(state)
        except Exception:
            traceback.print_exc()
            orders = Orders()
        try:
            request("/orders", orders.to_dict(tick))
        except urllib.error.HTTPError as e:
            if e.code == 409:
                print(f"tour {tick} : ordres arrivés trop tard", flush=True)
            else:
                print("ordres refusés :", e.code, e.read().decode(), flush=True)


if __name__ == "__main__":
    main()
