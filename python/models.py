"""Classes qui représentent l'état du jeu reçu à chaque tour et les ordres à envoyer."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Position:
    x: int
    y: int

    @staticmethod
    def from_dict(d):
        return Position(d["x"], d["y"])


@dataclass
class Plow:
    id: str
    team: str
    position: Position
    type: str                  # "normal" ou "big"
    broken: bool
    load: Optional[int]        # None pour les déneigeuses des autres équipes

    @staticmethod
    def from_dict(d):
        return Plow(d["id"], d["team"], Position.from_dict(d["position"]), d["type"],
                    d["broken"], d.get("load"))


@dataclass
class Call:
    id: str
    position: Position
    reward: int
    expires_at: int

    @staticmethod
    def from_dict(d):
        return Call(d["id"], Position.from_dict(d["position"]), d["reward"], d["expiresAt"])


@dataclass
class GameMap:
    width: int
    height: int
    tiles: list                # tiles[y][x] : "." rue, "#" bâtiment, "D" dépôt, "G" garage
    snow: list                 # snow[y][x] : unités de neige

    def tile(self, x, y):
        """La carte se referme sur elle-même : (-1, 0) est la dernière colonne."""
        return self.tiles[y % self.height][x % self.width]

    def passable(self, x, y):
        return self.tile(x, y) in ".G"


@dataclass
class GameState:
    tick: int
    you: str
    money: int
    garage: Position
    plows: list
    map: GameMap
    calls: list
    errors: list
    constants: dict

    @property
    def my_plows(self):
        return [p for p in self.plows if p.team == self.you]

    @staticmethod
    def from_dict(d):
        m = d["map"]
        return GameState(
            tick=d["tick"],
            you=d["you"],
            money=d["money"],
            garage=Position.from_dict(d["garage"]),
            plows=[Plow.from_dict(p) for p in d["plows"]],
            map=GameMap(m["width"], m["height"], m["tiles"], m["snow"]),
            calls=[Call.from_dict(c) for c in d["calls"]],
            errors=d["errors"],
            constants=d["constants"],
        )


@dataclass
class Orders:
    actions: list = field(default_factory=list)
    buy: Optional[str] = None  # None, "normal" ou "big"

    def move(self, plow, direction):
        """direction : "N", "S", "E" ou "O"."""
        self.actions.append({"plowId": plow.id, "type": "move", "direction": direction})

    def unload(self, plow):
        self.actions.append({"plowId": plow.id, "type": "unload"})

    def to_dict(self, tick):
        body = {"tick": tick, "actions": self.actions}
        if self.buy:
            body["buy"] = self.buy
        return body
