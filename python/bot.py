"""Votre bot. C'est le seul fichier que vous avez besoin de modifier.

decide() est appelée à chaque tour avec l'état du jeu et doit retourner vos ordres.
Pour l'instant, chaque déneigeuse se déplace au hasard.
"""

from dataclasses import dataclass, field
from collections import deque
from math import ceil

from models import Call, GameState, Orders, Position

_previous_positions: dict[str, tuple[int, int]] = {}
_big_post_slots: dict[str, int] = {}
_big_returning_to_post: set[str] = set()
_big_patrol_targets: dict[str, tuple[int, int]] = {}


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


@dataclass(frozen=True)
class CallPlan:
    call: Call
    path: tuple[tuple[int, int], ...]
    required_plows: int


@dataclass(frozen=True)
class BigPost:
    depot: tuple[int, int]
    side: str
    position: tuple[int, int]
    patrol: tuple[tuple[int, int], ...]


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


def garage_parking_target(state: GameState, graph):
    garage = (state.garage.x, state.garage.y)
    garage_node = graph.get(garage)
    if garage_node is None:
        return None
    for position in garage_node.neighbors.values():
        return (position.x, position.y)
    return garage


def build_big_posts(state: GameState, graph):
    posts = []
    used_positions = set()
    depots = [
        (x, y)
        for y in range(state.map.height)
        for x in range(state.map.width)
        if state.map.tile(x, y) == "D"
    ]
    for depot in sorted(depots):
        x, y = depot
        patrol = []
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            cell = ((x + dx) % state.map.width, (y + dy) % state.map.height)
            if cell in graph and cell not in patrol:
                patrol.append(cell)

        for side, dy in (("N", -1), ("S", 1)):
            desired = (x, (y + dy) % state.map.height)
            candidates = sorted(
                graph,
                key=lambda cell: (
                    min(abs(cell[0] - desired[0]), state.map.width - abs(cell[0] - desired[0]))
                    + min(abs(cell[1] - desired[1]), state.map.height - abs(cell[1] - desired[1])),
                    cell,
                ),
            )
            position = next(
                (cell for cell in candidates if cell not in used_positions),
                None,
            )
            if position is None:
                continue
            used_positions.add(position)
            posts.append(BigPost(depot, side, position, tuple(patrol)))

    return posts


def assign_big_posts(state: GameState, graph):
    big_plows = sorted(
        (plow for plow in state.my_plows if plow.type == "big"),
        key=lambda plow: plow.id,
    )
    posts = build_big_posts(state, graph)
    current_ids = {plow.id for plow in big_plows}
    for plow_id in set(_big_post_slots) - current_ids:
        del _big_post_slots[plow_id]

    assignments = {}
    used_slots = set()
    for plow in big_plows:
        slot = _big_post_slots.get(plow.id)
        if slot is not None and slot < len(posts) and slot not in used_slots:
            pass
        else:
            position = (
                plow.position.x % state.map.width,
                plow.position.y % state.map.height,
            )
            slot = next(
                (
                    index
                    for index, post in enumerate(posts)
                    if post.position == position and index not in used_slots
                ),
                None,
            )
            if slot is None:
                slot = next(
                    (index for index in range(len(posts)) if index not in used_slots),
                    None,
                )
            if slot is None:
                continue
            _big_post_slots[plow.id] = slot

        used_slots.add(slot)
        assignments[plow.id] = posts[slot]

    return assignments


def next_big_patrol_move(graph, start, post, plow_id, allow_advance):
    if not post.patrol:
        return None

    target = _big_patrol_targets.get(plow_id)
    reached_target = target == start
    if target == start:
        if not allow_advance:
            return None
        _big_patrol_targets.pop(plow_id, None)
        target = None

    if target is None and start in post.patrol and (
        reached_target or start == post.position
    ):
        index = post.patrol.index(start)
        target = post.patrol[(index + 1) % len(post.patrol)]
    elif target is None and start != post.position:
        target = post.position
    elif target is None:
        distances, first_directions = shortest_paths(graph, start)
        reachable = [cell for cell in post.patrol if cell in distances]
        if not reachable:
            return None
        target = min(reachable, key=distances.get)
    _big_patrol_targets[plow_id] = target

    _, first_directions = shortest_paths(graph, start)
    direction = first_directions.get(target)
    if direction is None:
        return None
    next_position = graph[start].neighbors[direction]
    return direction, (next_position.x, next_position.y)


def synchronized_big_moves(
    state, graph, posts, capacity, reserved_cells, normal_reserved_cells
):
    groups = {}
    for plow in state.my_plows:
        if plow.type == "big" and plow.id in posts:
            groups.setdefault(posts[plow.id].depot, []).append(plow)

    moves = {}
    paused_depots = set()
    for depot, plows in groups.items():
        if any(plow.broken for plow in plows):
            paused_depots.add(depot)
            for plow in plows:
                _big_returning_to_post.add(plow.id)
                _big_patrol_targets.pop(plow.id, None)
            continue

        if any(
            plow.id in _big_returning_to_post
            or (plow.load is not None and plow.load >= capacity)
            for plow in plows
        ):
            paused_depots.add(depot)

        if depot in paused_depots:
            continue

        group_ready = all(
            (
                _big_patrol_targets.get(plow.id)
                == (
                    plow.position.x % state.map.width,
                    plow.position.y % state.map.height,
                )
            )
            or (
                plow.id not in _big_patrol_targets
                and (
                    plow.position.x % state.map.width,
                    plow.position.y % state.map.height,
                )
                == posts[plow.id].position
            )
            for plow in plows
        )

        for plow in plows:
            start = (
                plow.position.x % state.map.width,
                plow.position.y % state.map.height,
            )
            current_target = _big_patrol_targets.get(plow.id)
            if not group_ready and (
                current_target == start
                or (current_target is None and start == posts[plow.id].position)
            ):
                continue

            occupied_cells = reserved_cells | {
                (
                    other.position.x % state.map.width,
                    other.position.y % state.map.height,
                )
                for other in state.plows
                if other.id != plow.id
            }
            plow_graph = graph_without_locked_roads(
                graph, {}, plow.id, start, occupied_cells
            )
            move = next_big_patrol_move(
                plow_graph, start, posts[plow.id], plow.id, group_ready
            )
            if move is None:
                if current_target != start:
                    paused_depots.add(depot)
                continue

            direction, destination = move
            moves[plow.id] = direction
            if (
                len(graph[destination].neighbors) >= 3
                and normal_near_intersection(
                    state, destination, normal_reserved_cells
                )
            ):
                paused_depots.add(depot)

    return moves, paused_depots


def normal_near_intersection(state: GameState, intersection, reserved_cells):
    normal_cells = set(reserved_cells)
    normal_cells.update(
        (
            plow.position.x % state.map.width,
            plow.position.y % state.map.height,
        )
        for plow in state.my_plows
        if plow.type == "normal"
    )
    for cell in normal_cells:
        dx = abs(cell[0] - intersection[0])
        dy = abs(cell[1] - intersection[1])
        dx = min(dx, state.map.width - dx)
        dy = min(dy, state.map.height - dy)
        if dx + dy <= 1:
            return True
    return False


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
        if plow.load is None:
            continue
        cell = (
            plow.position.x % state.map.width,
            plow.position.y % state.map.height,
        )
        road_key = road_by_cell.get(cell)
        if road_key is not None:
            roads[road_key].locked_by.add(plow.id)


def graph_without_locked_roads(graph, roads, plow_id, start, occupied_cells):
    """Retire du graphe les rues réservées et les cases déjà occupées."""
    blocked_cells = set(occupied_cells)
    blocked_cells.discard(start)
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


def shortest_paths(graph, start: tuple[int, int], blocked_first_steps=frozenset()):
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
            if current == start and neighbor in blocked_first_steps:
                continue
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


def shortest_path_to_any(graph, start, targets):
    """Retourne un plus court chemin depuis start vers la première cible atteinte."""
    if start not in graph:
        return None

    previous = {start: None}
    queue = deque([start])
    target = None
    while queue:
        current = queue.popleft()
        if current in targets:
            target = current
            break
        for position in graph[current].neighbors.values():
            neighbor = (position.x, position.y)
            if neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)

    if target is None:
        return None

    path = []
    current = target
    while current is not None:
        path.append(current)
        current = previous[current]
    return tuple(reversed(path))


def make_call_plans(state: GameState, graph, deposit_keys):
    plans = []
    for call in state.calls:
        call_key = (
            call.position.x % state.map.width,
            call.position.y % state.map.height,
        )
        path = shortest_path_to_any(graph, call_key, deposit_keys)
        if path is None:
            continue

        snow_on_path = sum(graph[key].snow for key in path)
        required_plows = max(1, ceil(snow_on_path * 1.2 / 20))
        plans.append(CallPlan(call, path, required_plows))

    return sorted(
        plans,
        key=lambda plan: plan.call.reward / plan.required_plows,
        reverse=True,
    )


def assign_call_plows(state: GameState, plans, graph):
    assignments = {}
    available = [
        plow
        for plow in state.my_plows
        if plow.type == "normal" and not plow.broken
    ]

    for plan in plans:
        target = (
            plan.call.position.x % state.map.width,
            plan.call.position.y % state.map.height,
        )
        remaining_ticks = max(0, plan.call.expires_at - state.tick)
        candidates = []
        for plow in available:
            start = (
                plow.position.x % state.map.width,
                plow.position.y % state.map.height,
            )
            occupied_cells = {
                (
                    other.position.x % state.map.width,
                    other.position.y % state.map.height,
                )
                for other in state.plows
                if other.id != plow.id
            }
            plow_graph = graph_without_locked_roads(
                graph, {}, plow.id, start, occupied_cells
            )
            distances, _ = shortest_paths(plow_graph, start)
            if target in distances and distances[target] <= remaining_ticks:
                candidates.append((distances[target], plow.id, plow))

        minimum_available = ceil(3 * plan.required_plows / 5)
        if len(candidates) < minimum_available:
            continue

        candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
        for _, _, plow in candidates[:plan.required_plows]:
            assignments[plow.id] = plan
            available.remove(plow)

    return assignments


def next_direction_along_call_path(graph, start, plan, toward_call):
    """Rejoint le chemin calculé, puis avance vers l'appel ou le dépôt."""
    route = tuple(reversed(plan.path))
    if start in route:
        index = route.index(start)
        next_index = index + 1 if toward_call else index - 1
        if next_index < 0 or next_index >= len(route):
            return None
        target = route[next_index]
        for direction, position in graph[start].neighbors.items():
            if (position.x, position.y) == target:
                return direction
        return None

    distances, first_directions = shortest_paths(graph, start)
    reachable_path = [key for key in route if key in distances]
    if not reachable_path:
        return None
    nearest_path = min(reachable_path, key=distances.get)
    return first_directions.get(nearest_path)


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
    my_plows = state.my_plows
    normal_plow_cost = state.constants["plowCost"]["normal"]
    if len(my_plows) < 6 and state.money >= normal_plow_cost:
        orders.buy = "normal"

    graph = build_graph(state)
    roads, road_by_cell = build_roads(graph)
    refresh_road_locks(state, roads, road_by_cell)
    deposit_keys = {
        (position.x, position.y) for position in unload_targets(state)
    }
    call_plans = make_call_plans(state, graph, deposit_keys)
    call_assignments = assign_call_plows(state, call_plans, graph)
    return_distances = distances_to_targets(graph, deposit_keys)
    capacity = state.constants["plowCapacity"]
    reserved_cells = set()
    direction_steps = {
        "N": (0, -1),
        "S": (0, 1),
        "E": (1, 0),
        "O": (-1, 0),
    }
    ordered_plows = sorted(my_plows, key=lambda plow: plow.type == "big")
    for plow in ordered_plows:
        start = (plow.position.x % state.map.width, plow.position.y % state.map.height)
        occupied_cells = reserved_cells | {
            (
                other.position.x % state.map.width,
                other.position.y % state.map.height,
            )
            for other in state.plows
            if other.id != plow.id
        }
        assigned_call = call_assignments.get(plow.id)
        is_big = plow.type == "big"
        blocked_roads = {} if assigned_call is not None or is_big else roads
        plow_graph = graph_without_locked_roads(
            graph, blocked_roads, plow.id, start, occupied_cells
        )
        outbound_distances, first_directions = shortest_paths(plow_graph, start)
        return_distances = distances_to_targets(plow_graph, deposit_keys)

        if plow.broken:
            garage = (state.garage.x, state.garage.y)
            direction = first_directions.get(garage)
        elif is_big:
            target = garage_parking_target(state, graph)
            direction = (
                first_directions.get(target)
                if target is not None and start != target
                else None
            )
        elif plow.load is not None and plow.load >= capacity:
            if start in deposit_keys:
                orders.unload(plow)
                continue
            previous_position = _previous_positions.get(plow.id)
            blocked_first_steps = (
                {previous_position} if previous_position is not None else set()
            )
            call_plan = call_assignments.get(plow.id)
            direction = None
            if call_plan is not None:
                route = tuple(reversed(call_plan.path))
                if start in route:
                    index = route.index(start)
                    if (
                        index > 0
                        and previous_position == route[index - 1]
                    ):
                        call_plan = None
                if call_plan is not None:
                    direction = next_direction_along_call_path(
                        plow_graph, start, call_plan, toward_call=False
                    )

            outbound_distances, first_directions = shortest_paths(
                plow_graph, start, blocked_first_steps
            )
            reachable_deposits = {
                target
                for target in deposit_keys.intersection(outbound_distances)
                if road_by_cell.get(target) is None
                or not roads[road_by_cell[target]].locked_by - {plow.id}
            }
            if not reachable_deposits and blocked_first_steps:
                outbound_distances, first_directions = shortest_paths(
                    plow_graph, start
                )
                reachable_deposits = {
                    target
                    for target in deposit_keys.intersection(outbound_distances)
                    if road_by_cell.get(target) is None
                    or not roads[road_by_cell[target]].locked_by - {plow.id}
                }
            if not reachable_deposits:
                continue
            target = min(reachable_deposits, key=outbound_distances.get)
            if direction is None:
                direction = first_directions.get(target)
            road_key = road_by_cell.get(target)
            if road_key is not None and not is_big:
                roads[road_key].locked_by.add(plow.id)
        elif plow.id in call_assignments:
            direction = next_direction_along_call_path(
                plow_graph,
                start,
                call_assignments[plow.id],
                toward_call=True,
            )
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
            dx, dy = direction_steps[direction]
            destination = (
                (plow.position.x + dx) % state.map.width,
                (plow.position.y + dy) % state.map.height,
            )
            reserved_cells.add(destination)
    _previous_positions.clear()
    _previous_positions.update(
        {
            plow.id: (
                plow.position.x % state.map.width,
                plow.position.y % state.map.height,
            )
            for plow in state.plows
        }
    )
    return orders
