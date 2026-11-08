"""Planifie les trajets de six déneigeuses au plus avec des mutex par case."""

from array import array
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator

from models import GameState, Orders, Position


DIRECTIONS = (("N", 0, -1), ("S", 0, 1), ("E", 1, 0), ("O", -1, 0))
MAX_PLOWS = 6
Cell = tuple[int, int]
Neighbors = tuple[tuple[tuple[str, int], ...], ...]


@dataclass(frozen=True)
class MapPaths:
    """Topologie et plus courts chemins, indépendants de la neige du tour."""

    cells: tuple[Cell, ...]
    indices: dict[Cell, int]
    neighbors: Neighbors
    depots: frozenset[int]  # Cases franchissables adjacentes aux dépôts.
    distances: tuple[array, ...]
    first_moves: tuple[bytearray, ...]

    def direction(self, start: int, target: int) -> str | None:
        code = self.first_moves[start][target]
        return DIRECTIONS[code - 1][0] if code else None


class TileMutexes:
    """Un propriétaire par case, pour la planification séquentielle d'un tour."""

    def __init__(self, count: int):
        self.owners: list[str | None] = [None] * count

    def acquire(self, plow_id: str, cells: tuple[int, ...]) -> bool:
        # Vérifie tout le trajet avant de verrouiller : aucun verrou partiel
        # n'est laissé lorsqu'une seule case appartient déjà à un autre bot.
        if any(self.owners[cell] not in (None, plow_id) for cell in cells):
            return False
        for cell in cells:
            self.owners[cell] = plow_id
        return True

    def blocked_for(self, plow_id: str) -> set[int]:
        return {
            cell for cell, owner in enumerate(self.owners)
            if owner is not None and owner != plow_id
        }


@lru_cache(maxsize=1)
def map_paths(width: int, height: int, tiles: tuple[str, ...]) -> MapPaths:
    """Précalcule une fois tous les chemins de la carte torique.

    Les matrices compactes ne gardent que la distance et le premier mouvement :
    on peut reconstruire un chemin sans stocker toutes ses cases pour chaque paire.
    Un changement de carte remplace automatiquement le cache.
    """
    cells = tuple(
        (x, y)
        for y in range(height)
        for x in range(width)
        if tiles[y][x] in ".G"
    )
    indices = {cell: index for index, cell in enumerate(cells)}
    neighbors = tuple(
        tuple(
            (direction, indices[neighbor])
            for direction, dx, dy in DIRECTIONS
            if (neighbor := ((x + dx) % width, (y + dy) % height)) in indices
        )
        for x, y in cells
    )
    depots = frozenset(
        indices[neighbor]
        for y in range(height)
        for x in range(width)
        if tiles[y][x] == "D"
        for _, dx, dy in DIRECTIONS
        if (neighbor := ((x + dx) % width, (y + dy) % height)) in indices
    )
    direction_codes = {
        direction: code for code, (direction, _, _) in enumerate(DIRECTIONS, 1)
    }
    distances = []
    first_moves = []
    for start in range(len(cells)):
        distance = array("i", [-1]) * len(cells)
        first_move = bytearray(len(cells))
        distance[start] = 0
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for direction, neighbor in neighbors[current]:
                if distance[neighbor] >= 0:
                    continue
                distance[neighbor] = distance[current] + 1
                first_move[neighbor] = (
                    direction_codes[direction]
                    if current == start
                    else first_move[current]
                )
                queue.append(neighbor)
        distances.append(distance)
        first_moves.append(first_move)

    return MapPaths(
        cells, indices, neighbors, depots, tuple(distances), tuple(first_moves)
    )


def available_neighbors(paths: MapPaths, blocked: set[int]) -> Neighbors:
    """Évite les cases occupées, sans modifier le cache permanent de la carte."""
    if not blocked:
        return paths.neighbors
    return tuple(
        () if cell in blocked else tuple(
            (direction, target)
            for direction, target in neighbors
            if target not in blocked
        )
        for cell, neighbors in enumerate(paths.neighbors)
    )


def return_routes(
    paths: MapPaths, neighbors: Neighbors, targets: frozenset[int], blocked: set[int]
) -> tuple[list[int], list[str | None]]:
    """Distance et premier mouvement vers la cible accessible la plus proche."""
    distances = [-1] * len(paths.cells)
    first_moves: list[str | None] = [None] * len(paths.cells)
    if not blocked:
        sorted_targets = sorted(targets)
        for start, row in enumerate(paths.distances):
            target = min(
                (target for target in sorted_targets if row[target] >= 0),
                key=row.__getitem__,
                default=None,
            )
            if target is not None:
                distances[start] = row[target]
                first_moves[start] = paths.direction(start, target)
        return distances, first_moves

    # Les obstacles du tour ne sont pas permanents : BFS multi-source seulement
    # lorsqu'il faut corriger les chemins précalculés.
    opposites = {"N": "S", "S": "N", "E": "O", "O": "E"}
    queue = deque(sorted(targets - blocked))
    for target in queue:
        distances[target] = 0
    while queue:
        current = queue.popleft()
        for direction, neighbor in neighbors[current]:
            if distances[neighbor] >= 0:
                continue
            distances[neighbor] = distances[current] + 1
            first_moves[neighbor] = opposites[direction]
            queue.append(neighbor)
    return distances, first_moves


@dataclass(frozen=True, slots=True)
class DecisionNode:
    """Un préfixe complet du trajet, relié à son parent dans l'arbre."""

    cell: int
    depth: int
    snow_collected: int
    first_direction: str | None
    direction: str | None
    parent: "DecisionNode | None" = None


def decision_tree(
    neighbors: Neighbors, snow: list[int], start: int, free_capacity: int
) -> Iterator[DecisionNode]:
    """Construit et parcourt l'arbre en profondeur, un mouvement par niveau.

    La racine compte comme une visite de la case de départ. Chaque branche a ses
    propres visites : tout retour sur une case de cette branche est interdit.
    Une branche s'arrête dès que la charge est pleine.
    Les parents représentent le trajet sans conserver tout l'arbre en mémoire.
    Aucun plafond de profondeur, de temps ou de nombre de noeuds n'est imposé.
    """
    if free_capacity <= 0:
        return
    visits = bytearray(len(neighbors))
    visits[start] = 1
    root = DecisionNode(start, 0, 0, None, None)
    stack = [(root, iter(neighbors[start]))]
    while stack:
        parent, children = stack[-1]
        edge = next(children, None)
        if edge is None:
            stack.pop()
            visits[parent.cell] = 0
            continue
        direction, cell = edge
        if visits[cell]:
            continue

        collected = parent.snow_collected + min(
            snow[cell], free_capacity - parent.snow_collected
        )
        node = DecisionNode(
            cell, parent.depth + 1, collected,
            parent.first_direction or direction, direction, parent,
        )
        yield node
        if collected < free_capacity:
            visits[cell] = 1
            stack.append((node, iter(neighbors[cell])))


def best_decision(
    neighbors: Neighbors,
    snow: list[int],
    start: int,
    free_capacity: int,
    return_distances: list[int],
) -> DecisionNode | None:
    """Maximise neige ramassée / (profondeur + distance au dépôt).

    Tous les préfixes non vides sont candidats, même si la charge reste partielle.
    Le ramassage est plafonné à la capacité disponible. Les produits croisés
    comparent exactement les scores, sans arrondi flottant.
    """
    # Si aucune neige n'est disponible hors de la racine, tous les scores sont 0.
    if not any(amount > 0 for cell, amount in enumerate(snow) if cell != start):
        return None

    best = None
    best_time = 0
    for node in decision_tree(neighbors, snow, start, free_capacity):
        distance = return_distances[node.cell]
        if distance < 0 or node.snow_collected <= 0:
            continue
        total_time = node.depth + distance
        if best is None:
            best, best_time = node, total_time
            continue
        comparison = node.snow_collected * best_time - best.snow_collected * total_time
        if comparison > 0 or (comparison == 0 and total_time < best_time):
            best, best_time = node, total_time
    return best


def decision_cells(node: DecisionNode) -> tuple[int, ...]:
    """Reconstruit toutes les cases du préfixe choisi, racine comprise."""
    cells = []
    current: DecisionNode | None = node
    while current is not None:
        cells.append(current.cell)
        current = current.parent
    return tuple(reversed(cells))


def route_cells(
    neighbors: Neighbors, start: int, distances: list[int], moves: list[str | None]
) -> tuple[int, ...]:
    """Reconstruit le chemin vers un dépôt ou le garage pour le verrouiller."""
    if distances[start] < 0:
        return ()
    cells = [start]
    current = start
    while distances[current] > 0:
        current = next(
            target for direction, target in neighbors[current]
            if direction == moves[current]
        )
        cells.append(current)
    return tuple(cells)


def next_direction_to_target(
    state: GameState, start: Position, target: Position
) -> str | None:
    """Retourne le premier mouvement d'un chemin précalculé vers la cible."""
    game_map = state.map
    paths = map_paths(
        game_map.width, game_map.height, tuple("".join(row) for row in game_map.tiles)
    )
    start_id = paths.indices.get((start.x % game_map.width, start.y % game_map.height))
    target_id = paths.indices.get((target.x % game_map.width, target.y % game_map.height))
    if start_id is None or target_id is None:
        return None
    return paths.direction(start_id, target_id)


def decide(state: GameState) -> Orders:
    orders = Orders()
    game_map = state.map
    paths = map_paths(
        game_map.width, game_map.height, tuple("".join(row) for row in game_map.tiles)
    )
    snow = [game_map.snow[y][x] for x, y in paths.cells]
    capacity = state.constants["plowCapacity"]
    my_plows = sorted(state.my_plows, key=lambda plow: plow.id)
    garage_cell = (state.garage.x % game_map.width, state.garage.y % game_map.height)
    positions = {
        plow.id: paths.indices.get((
            plow.position.x % game_map.width, plow.position.y % game_map.height
        ))
        for plow in state.plows
    }
    garage_occupied = any(
        (plow.position.x % game_map.width, plow.position.y % game_map.height) == garage_cell
        for plow in state.plows
    )
    if (
        len(my_plows) < MAX_PLOWS
        and not garage_occupied
        and state.money >= state.constants["plowCost"]["normal"]
    ):
        orders.buy = "normal"

    if my_plows:
        offset = state.tick % len(my_plows)
        my_plows = my_plows[offset:] + my_plows[:offset]
    # Les mutex sont reconstruits chaque tour : aucune ancienne route ne peut
    # rester verrouillée après une panne, un blocage ou un changement de plan.
    mutexes = TileMutexes(len(paths.cells))
    for plow in my_plows:
        start = positions[plow.id]
        if start is not None:
            mutexes.acquire(plow.id, (start,))

    for plow in my_plows:
        start = positions[plow.id]
        if start is None:
            continue
        if not mutexes.acquire(plow.id, (start,)):
            continue  # Plusieurs bots peuvent physiquement partager un garage.
        occupied = {
            cell
            for other in state.plows
            if other.id != plow.id and not other.broken
            if (cell := positions[other.id]) is not None
            if game_map.tile(*paths.cells[cell]) != "G"
        }
        blocked = (occupied | mutexes.blocked_for(plow.id)) - {start}
        neighbors = available_neighbors(paths, blocked)
        return_distances, return_moves = return_routes(paths, neighbors, paths.depots, blocked)
        load = plow.load or 0
        chosen_cells: tuple[int, ...] = ()

        if plow.broken:
            garage = paths.indices.get(garage_cell)
            if garage is None:
                continue
            repair_distances, repair_moves = return_routes(
                paths, neighbors, frozenset({garage}), blocked
            )
            chosen_cells = route_cells(neighbors, start, repair_distances, repair_moves)
            direction = repair_moves[start]
        elif load > 0 and start in paths.depots:
            orders.unload(plow)
            continue
        elif load >= capacity:
            chosen_cells = route_cells(neighbors, start, return_distances, return_moves)
            direction = return_moves[start]
        elif return_distances[start] < 0:
            continue  # Aucune neige ne peut être livrée depuis cette composante.
        else:
            best = best_decision(neighbors, snow, start, capacity - load, return_distances)
            if best is not None:
                chosen_cells = decision_cells(best) + route_cells(
                    neighbors, best.cell, return_distances, return_moves
                )[1:]
                direction = best.first_direction
            elif load > 0:
                chosen_cells = route_cells(neighbors, start, return_distances, return_moves)
                direction = return_moves[start]
            else:
                direction = None

        if direction is not None and mutexes.acquire(plow.id, chosen_cells):
            orders.move(plow, direction)
    return orders
