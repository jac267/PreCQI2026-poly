"""Votre bot. C'est le seul fichier que vous avez besoin de modifier.

decide() est appelée à chaque tour avec l'état du jeu et doit retourner vos ordres.
Pour l'instant, chaque déneigeuse se déplace au hasard.
"""

from dataclasses import dataclass, field
from collections import deque

from models import GameState, Orders, Position


@dataclass(frozen=True)
class GraphNode:
    """Noeud correspondant à une case praticable de la carte."""

    position: Position
    tile: str
    snow: int
    neighbors: dict[str, Position]


@dataclass
class Road:
    entry: tuple[int, int]
    exit: tuple[int, int]
    cells: tuple[tuple[int, int], ...]
    locked_by: set[str] = field(default_factory=set)


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


def build_roads(graph):
    """Construit les rues entre jonctions et indexe leurs cases intérieures."""
    roads = {}
    road_by_cell = {}
    visited_edges = set()
    junctions = {
        key for key, node in graph.items() if len(node.neighbors) != 2
    }

    for entry in junctions:
        for neighbor_position in graph[entry].neighbors.values():
            neighbor = (neighbor_position.x, neighbor_position.y)
            first_edge = tuple(sorted((entry, neighbor)))
            if first_edge in visited_edges:
                continue

            path = [entry, neighbor]
            visited_edges.add(first_edge)
            previous = entry
            current = neighbor
            while current not in junctions:
                next_positions = [
                    (position.x, position.y)
                    for position in graph[current].neighbors.values()
                    if (position.x, position.y) != previous
                ]
                if not next_positions:
                    break
                next_cell = next_positions[0]
                edge = tuple(sorted((current, next_cell)))
                if edge in visited_edges:
                    break
                visited_edges.add(edge)
                path.append(next_cell)
                previous, current = current, next_cell

            exit_cell = current
            road_key = tuple(sorted((entry, exit_cell)))
            road = roads.setdefault(
                road_key,
                Road(entry=road_key[0], exit=road_key[1], cells=tuple(path[1:-1])),
            )
            for cell in path[1:-1]:
                road_by_cell[cell] = road_key

    return roads, road_by_cell


def refresh_road_locks(state: GameState, roads, road_by_cell):
    """Reconstruit les verrous depuis les positions actuelles de toutes les souffleuses."""
    for road in roads.values():
        road.locked_by.clear()

    for plow in state.plows:
        cell = (
            plow.position.x % state.map.width,
            plow.position.y % state.map.height,
        )
        road_key = road_by_cell.get(cell)
        if road_key is not None:
            roads[road_key].locked_by.add(plow.id)


def graph_without_locked_roads(graph, roads, road_by_cell, plow_id, start):
    """Retire du graphe les rues réservées par d'autres souffleuses."""
    blocked_cells = set()
    for road_key, road in roads.items():
        if road.locked_by - {plow_id} and start not in road.cells:
            blocked_cells.update(road.cells)

    available_graph = {}
    for key, node in graph.items():
        if key in blocked_cells:
            continue
        neighbors = {
            direction: position
            for direction, position in node.neighbors.items()
            if (position.x, position.y) not in blocked_cells
        }
        available_graph[key] = GraphNode(
            position=node.position,
            tile=node.tile,
            snow=node.snow,
            neighbors=neighbors,
        )
    return available_graph


def next_direction_to_target(
    state: GameState, start: Position, target: Position
) -> str | None:
    """Retourne la première direction d'un plus court chemin vers la cible."""
    graph = build_graph(state)
    start_key = (start.x % state.map.width, start.y % state.map.height)
    target_key = (target.x % state.map.width, target.y % state.map.height)

    _, first_directions = shortest_paths(graph, start_key)
    return first_directions.get(target_key)


def shortest_paths(graph, start: tuple[int, int]):
    """Retourne les distances et la première direction vers chaque case atteignable."""
    if start not in graph:
        return {}, {}

    distances = {start: 0}
    first_directions = {start: None}
    queue = deque([start])

    while queue:
        current = queue.popleft()
        for direction, position in graph[current].neighbors.items():
            neighbor = (position.x, position.y)
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            first_directions[neighbor] = (
                direction if current == start else first_directions[current]
            )
            queue.append(neighbor)

    return distances, first_directions


def distances_to_targets(graph, targets: set[tuple[int, int]]):
    """Distance de chaque case atteignable à la case de déchargement la plus proche."""
    distances = {target: 0 for target in targets if target in graph}
    queue = deque(distances)

    while queue:
        current = queue.popleft()
        for position in graph[current].neighbors.values():
            neighbor = (position.x, position.y)
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)

    return distances


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


def best_snow_target(
    graph,
    start,
    outbound_distances,
    return_distances,
    roads,
    road_by_cell,
    plow_id,
):
    """Choisit la neige qui maximise N / (temps aller + temps retour)."""
    best_target = None
    best_score = 0
    for key, node in graph.items():
        if key == start or node.snow <= 0:
            continue
        road_key = road_by_cell.get(key)
        if road_key is not None and roads[road_key].locked_by - {plow_id}:
            continue
        if key not in outbound_distances or key not in return_distances:
            continue

        total_time = outbound_distances[key] + return_distances[key]
        score = node.snow / total_time
        if score > best_score:
            best_score = score
            best_target = key

    return best_target



def decide(state: GameState) -> Orders:
    orders = Orders()
    normal_plow_cost = state.constants["plowCost"]["normal"]
    if state.money >= normal_plow_cost:
        orders.buy = "normal"

    graph = build_graph(state)
    roads, road_by_cell = build_roads(graph)
    refresh_road_locks(state, roads, road_by_cell)
    deposit_keys = {
        (position.x, position.y) for position in unload_targets(state)
    }
    return_distances = distances_to_targets(graph, deposit_keys)
    capacity = state.constants["plowCapacity"]

    for plow in state.my_plows:
        start = (plow.position.x % state.map.width, plow.position.y % state.map.height)
        plow_graph = graph_without_locked_roads(
            graph, roads, road_by_cell, plow.id, start
        )
        outbound_distances, first_directions = shortest_paths(plow_graph, start)
        return_distances = distances_to_targets(plow_graph, deposit_keys)

        if plow.broken:
            garage = (state.garage.x, state.garage.y)
            direction = first_directions.get(garage)
        elif plow.load is not None and plow.load >= capacity:
            if start in deposit_keys:
                orders.unload(plow)
                continue
            reachable_deposits = {
                target
                for target in deposit_keys.intersection(outbound_distances)
                if road_by_cell.get(target) is None
                or not roads[road_by_cell[target]].locked_by - {plow.id}
            }
            if not reachable_deposits:
                continue
            target = min(reachable_deposits, key=outbound_distances.get)
            direction = first_directions.get(target)
            road_key = road_by_cell.get(target)
            if road_key is not None:
                roads[road_key].locked_by.add(plow.id)
        else:
            target = best_snow_target(
                graph,
                start,
                outbound_distances,
                return_distances,
                roads,
                road_by_cell,
                plow.id,
            )
            direction = first_directions.get(target) if target is not None else None
            road_key = road_by_cell.get(target) if target is not None else None
            if road_key is not None:
                roads[road_key].locked_by.add(plow.id)

        if direction is not None:
            orders.move(plow, direction)
    return orders
