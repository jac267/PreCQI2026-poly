"""Votre bot. C'est le seul fichier que vous avez besoin de modifier.

decide() est appelée à chaque tour avec l'état du jeu et doit retourner vos ordres.
Pour l'instant, chaque déneigeuse se déplace au hasard.
"""

from dataclasses import dataclass
from collections import deque

from models import GameState, Orders, Position


@dataclass(frozen=True)
class GraphNode:
    """Noeud correspondant à une case praticable de la carte."""

    position: Position
    tile: str
    snow: int
    neighbors: dict[str, Position]


def build_graph(state: GameState) -> dict[tuple[int, int], GraphNode]:
    """Construit le graphe des cases praticables et conserve la neige par noeud.

    Les coordonnées suivent la carte torique du jeu : un voisin qui sort de la
    carte réapparaît de l'autre côté.
    """
    game_map = state.map
    nodes: dict[tuple[int, int], GraphNode] = {}

    for y in range(game_map.height):
        for x in range(game_map.width):
            if game_map.passable(x, y):
                position = Position(x, y)
                nodes[(x, y)] = GraphNode(
                    position=position,
                    tile=game_map.tile(x, y),
                    snow=game_map.snow[y][x],
                    neighbors={},
                )

    directions = {
        "N": (0, -1),
        "S": (0, 1),
        "E": (1, 0),
        "O": (-1, 0),
    }
    for (x, y), node in nodes.items():
        neighbors = {}
        for direction, (dx, dy) in directions.items():
            neighbor = ((x + dx) % game_map.width, (y + dy) % game_map.height)
            if neighbor in nodes:
                neighbors[direction] = nodes[neighbor].position
        nodes[(x, y)] = GraphNode(
            position=node.position,
            tile=node.tile,
            snow=node.snow,
            neighbors=neighbors,
        )

    return nodes


def next_direction_to_target(
    state: GameState, start: Position, target: Position
) -> str | None:
    """Retourne la première direction d'un plus court chemin vers la cible."""
    graph = build_graph(state)
    start_key = (start.x % state.map.width, start.y % state.map.height)
    target_key = (target.x % state.map.width, target.y % state.map.height)

    if start_key not in graph or target_key not in graph:
        return None
    if start_key == target_key:
        return None

    directions = ("N", "S", "E", "O")
    previous: dict[tuple[int, int], tuple[tuple[int, int], str] | None] = {
        start_key: None
    }
    queue = deque([start_key])

    while queue:
        current = queue.popleft()
        for direction in directions:
            neighbor_position = graph[current].neighbors.get(direction)
            if neighbor_position is None:
                continue
            neighbor = (neighbor_position.x, neighbor_position.y)
            if neighbor in previous:
                continue
            previous[neighbor] = (current, direction)
            queue.append(neighbor)
            if neighbor == target_key:
                queue.clear()
                break

    if target_key not in previous:
        return None

    current = target_key
    while previous[current] is not None:
        parent, direction = previous[current]
        if parent == start_key:
            return direction
        current = parent

    return None


def unload_targets(state: GameState) -> list[Position]:
    """Retourne les rues adjacentes à un dépôt où un plow peut se vider."""
    targets = []
    for y in range(state.map.height):
        for x in range(state.map.width):
            if state.map.tiles[y][x] != "D":
                continue
            for dx, dy in ((0, -1), (0, 1), (1, 0), (-1, 0)):
                nx = (x + dx) % state.map.width
                ny = (y + dy) % state.map.height
                if state.map.passable(nx, ny):
                    targets.append(Position(nx, ny))
    return targets


def best_snow_target(state: GameState) -> Position | None:
    """Choisit la case praticable qui contient le plus de neige."""
    graph = build_graph(state)
    if not graph:
        return None
    node = max(graph.values(), key=lambda candidate: candidate.snow)
    return node.position if node.snow > 0 else None


def decide(state: GameState) -> Orders:
    orders = Orders()
    deposits = unload_targets(state)

    for plow in state.my_plows:
        if plow.broken:
            direction = next_direction_to_target(state, plow.position, state.garage)
        elif plow.load and deposits:
            target = next(
                (
                    position
                    for position in deposits
                    if (
                        position.x == plow.position.x
                        and position.y == plow.position.y
                    )
                    or next_direction_to_target(state, plow.position, position)
                    is not None
                ),
                None,
            )
            if target is None:
                continue
            if (
                plow.position.x % state.map.width == target.x
                and plow.position.y % state.map.height == target.y
            ):
                orders.unload(plow)
                continue
            direction = next_direction_to_target(state, plow.position, target)
        else:
            target = best_snow_target(state)
            direction = (
                next_direction_to_target(state, plow.position, target)
                if target is not None
                else None
            )
        if direction is not None:
            orders.move(plow, direction)
    return orders
