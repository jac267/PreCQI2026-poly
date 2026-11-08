"""Régressions du planificateur : python -m unittest discover -s python -v."""

from collections import deque
from fractions import Fraction
from itertools import islice
import random
import unittest
from unittest.mock import patch

import bot
from models import GameMap, GameState, Plow, Position


def trajectory(node):
    cells = []
    while node is not None:
        cells.append(node.cell)
        node = node.parent
    return tuple(reversed(cells))


def exhaustive_oracle(neighbors, snow, start, capacity, return_distances):
    """Petit solveur indépendant : copie les visites à chaque branche."""
    candidates = []

    def expand(path, moves, collected):
        for direction, target in neighbors[path[-1]]:
            if target in path:
                continue
            new_collected = min(capacity, collected + snow[target])
            new_path = path + (target,)
            new_moves = moves + (direction,)
            if new_collected > 0 and return_distances[target] >= 0:
                duration = len(new_moves) + return_distances[target]
                candidates.append((
                    Fraction(new_collected, duration), -duration,
                    new_moves[0], new_path, new_collected,
                ))
            if new_collected < capacity:
                expand(new_path, new_moves, new_collected)

    expand((start,), (), 0)
    return max(candidates, key=lambda item: item[:2], default=None)


def make_state(tiles=("#######", "#G..D##", "#######"), position=(1, 1), load=0,
               snow=None, broken=False, others=(), money=10000):
    width, height = len(tiles[0]), len(tiles)
    return GameState(
        tick=1, you="us", money=money, garage=Position(1, 1),
        plows=[Plow("ours", "us", Position(*position), "normal", broken, load), *others],
        map=GameMap(width, height, list(tiles), snow or [[0] * width for _ in tiles]),
        calls=[], errors=[], constants={"plowCapacity": 20, "plowCost": {"normal": 250}},
    )


class DecisionTreeTests(unittest.TestCase):
    def test_return_to_start_is_rejected(self):
        nodes = list(bot.decision_tree(((('E', 1),), (('O', 0),)), [9, 5], 0, 20))
        self.assertEqual([trajectory(node) for node in nodes], [(0, 1)])
        self.assertEqual([node.snow_collected for node in nodes], [5])

    def test_revisit_to_any_ancestor_is_rejected(self):
        neighbors = ((('E', 1),), (('E', 2),), (('O', 1), ('N', 0), ('E', 3)), ())
        nodes = list(bot.decision_tree(neighbors, [0, 2, 3, 4], 0, 20))
        self.assertEqual([trajectory(node) for node in nodes], [(0, 1), (0, 1, 2), (0, 1, 2, 3)])
        for node in nodes:
            path = trajectory(node)
            self.assertEqual(len(path), len(set(path)))

    def test_snow_is_independent_between_sibling_branches(self):
        neighbors = ((('E', 1), ('S', 2)), (('S', 2),), ())
        nodes = list(bot.decision_tree(neighbors, [0, 2, 7], 0, 20))
        by_path = {trajectory(node): node.snow_collected for node in nodes}
        self.assertEqual(by_path[(0, 1, 2)], 9)
        self.assertEqual(by_path[(0, 2)], 7)

    def test_capacity_clips_pickup_and_stops_expansion(self):
        neighbors = ((('E', 1),), (('E', 2),), ())
        nodes = list(bot.decision_tree(neighbors, [0, 100, 10], 0, 3))
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].snow_collected, 3)
        self.assertEqual(list(bot.decision_tree(neighbors, [0, 100, 10], 0, 0)), [])

    def test_partial_prefix_can_beat_every_full_load_path(self):
        neighbors = ((('E', 1),), (('O', 0), ('E', 2)), (('O', 1), ('E', 3)), (('O', 2),))
        best = bot.best_decision(neighbors, [0, 6, 0, 14], 0, 20, [1, 0, 1, 2])
        self.assertEqual(trajectory(best), (0, 1))
        self.assertEqual(best.snow_collected, 6)

    def test_multi_step_snow_changes_the_first_decision(self):
        neighbors = ((('E', 1), ('S', 2)), (), (('S', 3),), ())
        best = bot.best_decision(neighbors, [0, 4, 1, 10], 0, 20, [1, 1, 1, 0])
        self.assertEqual(best.first_direction, 'S')
        self.assertEqual(trajectory(best), (0, 2, 3))

    def test_return_distance_and_existing_free_capacity_affect_the_score(self):
        neighbors = ((('E', 1), ('S', 2)), (), ())
        best = bot.best_decision(neighbors, [0, 100, 3], 0, 1, [0, 9, 0])
        self.assertEqual(best.first_direction, 'S')
        self.assertEqual(best.snow_collected, 1)

    def test_unreachable_returns_are_not_candidates(self):
        neighbors = ((('E', 1), ('S', 2)), (), ())
        best = bot.best_decision(neighbors, [0, 10, 3], 0, 20, [0, -1, 0])
        self.assertEqual(best.first_direction, 'S')

    def test_iterative_search_handles_paths_beyond_python_recursion_limit(self):
        count = 1200
        neighbors = tuple((("E", cell + 1),) if cell + 1 < count else () for cell in range(count))
        nodes = list(islice(bot.decision_tree(neighbors, [1] * count, 0, count), count))
        self.assertEqual(nodes[-1].depth, count - 1)

    def test_matches_independent_exhaustive_solver(self):
        rng = random.Random(2027)
        for trial in range(60):
            count = rng.randrange(2, 6)
            neighbors = tuple(
                tuple((str(target), target) for target in range(count)
                      if cell != target and rng.random() < 0.5)
                for cell in range(count)
            )
            snow = [rng.randrange(5) for _ in range(count)]
            capacity = rng.randrange(1, 9)
            distances = [rng.randrange(-1, 5) for _ in range(count)]
            expected = exhaustive_oracle(neighbors, snow, 0, capacity, distances)
            best = bot.best_decision(neighbors, snow, 0, capacity, distances)
            with self.subTest(trial=trial):
                if expected is None:
                    self.assertIsNone(best)
                else:
                    self.assertEqual(best.first_direction, expected[2])
                    self.assertEqual(trajectory(best), expected[3])
                    self.assertEqual(best.snow_collected, expected[4])


class NavigationTests(unittest.TestCase):
    def setUp(self):
        bot.map_paths.cache_clear()

    def test_toroidal_routes_and_impassable_depots(self):
        state = make_state(("#####", "G..D.", "#####"), position=(0, 1))
        paths = bot.map_paths(5, 3, tuple(state.map.tiles))
        start, target = paths.indices[(0, 1)], paths.indices[(4, 1)]
        self.assertEqual(paths.distances[start][target], 1)
        self.assertEqual(paths.direction(start, target), 'O')
        self.assertNotIn((3, 1), paths.indices)
        self.assertEqual({paths.cells[index] for index in paths.depots}, {(2, 1), (4, 1)})
        self.assertEqual(bot.next_direction_to_target(state, Position(5, 1), Position(-1, 1)), 'O')

    def test_vertical_wrap_and_disconnected_targets(self):
        paths = bot.map_paths(3, 4, ("G##", "###", "##.", ".##"))
        start, target, isolated = (paths.indices[cell] for cell in ((0, 0), (0, 3), (2, 2)))
        self.assertEqual(paths.direction(start, target), 'N')
        self.assertEqual(paths.distances[start][isolated], -1)
        self.assertIsNone(paths.direction(start, isolated))

    def test_topology_cache_survives_snow_changes_and_replaces_changed_maps(self):
        state = make_state()
        bot.decide(state)
        first = bot.map_paths(7, 3, tuple(state.map.tiles))
        state.map.snow[1][2] = 10
        bot.decide(state)
        self.assertIs(bot.map_paths(7, 3, tuple(state.map.tiles)), first)
        other = bot.map_paths(7, 3, ("#######", "#G.D###", "#######"))
        self.assertIsNot(first, other)
        self.assertNotIn((3, 1), other.indices)
        self.assertEqual(bot.map_paths.cache_info().currsize, 1)

    def test_all_cached_and_blocked_routes_match_independent_bfs(self):
        paths = bot.map_paths(4, 4, ("G...", ".D..", "..#.", "...."))
        for blocked in (set(), {paths.indices[(2, 0)], paths.indices[(0, 1)]}):
            neighbors = bot.available_neighbors(paths, blocked)
            distances, moves = bot.return_routes(paths, neighbors, paths.depots, blocked)
            for start in range(len(paths.cells)):
                expected = {start: 0}
                queue = deque([start])
                while queue:
                    current = queue.popleft()
                    for _, target in neighbors[current]:
                        if target not in expected:
                            expected[target] = expected[current] + 1
                            queue.append(target)
                target_distances = [expected[target] for target in paths.depots - blocked if target in expected]
                self.assertEqual(distances[start], min(target_distances, default=-1))
                if not blocked:
                    for target in range(len(paths.cells)):
                        self.assertEqual(paths.distances[start][target], expected.get(target, -1))
                        direction = paths.direction(start, target)
                        if direction is not None:
                            next_cell = dict(neighbors[start])[direction]
                            self.assertEqual(paths.distances[next_cell][target], paths.distances[start][target] - 1)
                if moves[start] is not None:
                    next_cell = dict(neighbors[start])[moves[start]]
                    self.assertEqual(distances[next_cell], distances[start] - 1)


class OrderTests(unittest.TestCase):
    def test_moves_toward_snow_and_does_not_buy_when_garage_is_occupied(self):
        state = make_state()
        state.map.snow[1][2] = 6
        orders = bot.decide(state)
        self.assertEqual(orders.actions, [{"plowId": "ours", "type": "move", "direction": "E"}])
        self.assertNotIn('buy', orders.to_dict(state.tick))

    def test_full_plow_returns_and_partial_or_full_plow_unloads_at_depot(self):
        orders = bot.decide(make_state(load=20))
        self.assertEqual(orders.actions[0]['direction'], 'E')
        for load in (5, 20):
            orders = bot.decide(make_state(position=(3, 1), load=load))
            self.assertEqual(orders.actions, [{"plowId": "ours", "type": "unload"}])

    def test_broken_plow_returns_to_garage_even_if_another_plow_is_there(self):
        other = Plow("other", "them", Position(1, 1), "normal", False, None)
        orders = bot.decide(make_state(position=(3, 1), broken=True, others=(other,)))
        self.assertEqual(orders.actions[0]['direction'], 'O')

    def test_no_snow_returns_partial_load_or_waits_if_empty(self):
        self.assertEqual(bot.decide(make_state()).actions, [])
        orders = bot.decide(make_state(position=(2, 1), load=5))
        self.assertEqual(orders.actions[0]['direction'], 'E')

    def test_occupied_street_is_avoided_but_broken_plow_does_not_block(self):
        other = Plow("other", "them", Position(2, 1), "normal", False, None)
        self.assertEqual(bot.decide(make_state(load=20, others=(other,))).actions, [])
        other.broken = True
        self.assertEqual(bot.decide(make_state(load=20, others=(other,))).actions[0]['direction'], 'E')

    def test_missing_or_unreachable_depot_does_not_crash_or_search(self):
        self.assertEqual(bot.decide(make_state(("#####", "#G.##", "#####"))).actions, [])

    def test_successive_ticks_collect_and_deliver_cash_without_purchases(self):
        state = make_state(money=0)
        state.map.snow[1][2] = 6
        state.map.snow[1][3] = 10
        plow = state.my_plows[0]
        steps = {direction: (dx, dy) for direction, dx, dy in bot.DIRECTIONS}
        for _ in range(6):
            orders = bot.decide(state)
            self.assertIsNone(orders.buy)
            for action in orders.actions:
                if action['type'] == 'unload':
                    state.money += plow.load
                    plow.load = 0
                else:
                    dx, dy = steps[action['direction']]
                    plow.position = Position(
                        (plow.position.x + dx) % state.map.width,
                        (plow.position.y + dy) % state.map.height,
                    )
            x, y = plow.position.x, plow.position.y
            pickup = min(state.map.snow[y][x], 20 - plow.load)
            plow.load += pickup
            state.map.snow[y][x] -= pickup
            state.tick += 1
        self.assertEqual(state.money, 16)
        self.assertEqual(plow.load, 0)
        self.assertEqual(sum(map(sum, state.map.snow)), 0)


class TileMutexTests(unittest.TestCase):
    def test_owner_can_reacquire_its_tiles_but_other_plow_cannot(self):
        mutexes = bot.TileMutexes(5)
        self.assertTrue(mutexes.acquire('a', (0, 1, 2)))
        self.assertTrue(mutexes.acquire('a', (2, 1, 3)))
        self.assertFalse(mutexes.acquire('b', (1,)))
        self.assertEqual(mutexes.blocked_for('a'), set())
        self.assertEqual(mutexes.blocked_for('b'), {0, 1, 2, 3})

    def test_failed_path_acquisition_does_not_leave_partial_locks(self):
        mutexes = bot.TileMutexes(5)
        mutexes.acquire('a', (3,))
        self.assertFalse(mutexes.acquire('b', (0, 1, 3, 4)))
        self.assertEqual(mutexes.blocked_for('a'), set())
        self.assertEqual(mutexes.owners, [None, None, None, 'a', None])


def make_fleet_state(full_first=False):
    """Deux trajets se croisent loin de la prochaine case du premier bot."""
    tiles = (
        '#########',
        '#G...D###',
        '###.#####',
        '#.....D##',
        '#########',
    )
    second = Plow('second', 'us', Position(3, 3), 'normal', False, 0)
    state = make_state(tiles, load=20 if full_first else 0, others=(second,), money=0)
    state.tick = 0
    for x in (2, 3, 4):
        state.map.snow[1][x] = 6
    for x in (4, 5):
        state.map.snow[3][x] = 1
    return state


class FleetPlanningTests(unittest.TestCase):
    def test_chosen_collection_path_is_culled_from_other_plows_tree(self):
        state = make_fleet_state()
        paths = bot.map_paths(state.map.width, state.map.height, tuple(state.map.tiles))
        with patch.object(bot, 'best_decision', wraps=bot.best_decision) as search:
            orders = bot.decide(state)
        moves = {action['plowId']: action['direction'] for action in orders.actions}
        self.assertEqual(moves, {'ours': 'E', 'second': 'E'})
        self.assertEqual(search.call_count, 2)
        first_choice = bot.best_decision(*search.call_args_list[0].args)
        self.assertEqual(bot.decision_cells(first_choice), tuple(paths.indices[(x, 1)] for x in (1, 2, 3, 4)))
        second_neighbors = search.call_args_list[1].args[0]
        forbidden = {paths.indices[(x, 1)] for x in (1, 2, 3, 4)}
        for cell in forbidden:
            self.assertEqual(second_neighbors[cell], ())
        self.assertTrue(all(target not in forbidden for edges in second_neighbors for _, target in edges))

    def test_full_return_path_is_locked_beyond_immediate_destination(self):
        state = make_fleet_state(full_first=True)
        paths = bot.map_paths(state.map.width, state.map.height, tuple(state.map.tiles))
        with patch.object(bot, 'best_decision', wraps=bot.best_decision) as search:
            orders = bot.decide(state)
        self.assertEqual({action['plowId']: action['direction'] for action in orders.actions}, {'ours': 'E', 'second': 'E'})
        self.assertEqual(search.call_count, 1)
        second_neighbors = search.call_args.args[0]
        self.assertEqual(second_neighbors[paths.indices[(3, 1)]], ())
        self.assertEqual(second_neighbors[paths.indices[(4, 1)]], ())

    def test_unlocked_second_plow_prefers_previously_reserved_path_next_tick(self):
        state = make_fleet_state()
        first_orders = bot.decide(state)
        self.assertEqual(next(action for action in first_orders.actions if action['plowId'] == 'second')['direction'], 'E')
        state.plows = [plow for plow in state.plows if plow.id == 'second']
        state.tick += 1
        second_orders = bot.decide(state)
        self.assertEqual(second_orders.actions[0]['direction'], 'N')

    def test_priority_rotates_each_tick_and_replanning_releases_old_routes(self):
        state = make_fleet_state()
        self.assertEqual(bot.decide(state).actions[0]['plowId'], 'ours')
        state.tick += 1
        orders = bot.decide(state)
        self.assertEqual(orders.actions[0]['plowId'], 'second')
        self.assertEqual(orders.actions[0]['direction'], 'N')
        self.assertNotIn('ours', {action['plowId'] for action in orders.actions})

    def test_friendly_current_tile_is_locked_before_other_plows_plan(self):
        state = make_fleet_state()
        state.plows[1].position = Position(3, 1)
        with patch.object(bot, 'best_decision', wraps=bot.best_decision) as search:
            bot.decide(state)
        # Le premier bot n'a aucun dépôt accessible sans traverser l'autre bot.
        self.assertEqual(search.call_count, 1)
        paths = bot.map_paths(state.map.width, state.map.height, tuple(state.map.tiles))
        self.assertEqual(search.call_args.args[2], paths.indices[(3, 1)])

    def test_empty_plow_yields_when_another_route_owns_its_only_exit(self):
        state = make_fleet_state(full_first=True)
        state.map.snow[3] = [0] * state.map.width
        orders = bot.decide(state)
        self.assertEqual(orders.actions, [{'plowId': 'ours', 'type': 'move', 'direction': 'E'}])

    def test_repair_path_is_reserved_through_the_garage(self):
        state = make_fleet_state()
        state.plows[0].position = Position(4, 1)
        state.plows[0].broken = True
        paths = bot.map_paths(state.map.width, state.map.height, tuple(state.map.tiles))
        with patch.object(bot, 'best_decision', wraps=bot.best_decision) as search:
            orders = bot.decide(state)
        self.assertEqual({action['plowId']: action['direction'] for action in orders.actions}, {'ours': 'O', 'second': 'E'})
        second_neighbors = search.call_args.args[0]
        self.assertEqual(second_neighbors[paths.indices[(2, 1)]], ())
        self.assertEqual(second_neighbors[paths.indices[(1, 1)]], ())

    def test_shared_garage_allows_only_one_plow_to_claim_the_same_exit(self):
        other = Plow('second', 'us', Position(1, 1), 'normal', False, 0)
        state = make_state(others=(other,))
        state.map.snow[1][2] = 10
        state.tick = 0
        self.assertEqual(bot.decide(state).actions, [{'plowId': 'ours', 'type': 'move', 'direction': 'E'}])
        state.tick = 1
        self.assertEqual(bot.decide(state).actions, [{'plowId': 'second', 'type': 'move', 'direction': 'E'}])

    def test_planning_order_is_stable_when_server_reorders_plows(self):
        state = make_fleet_state()
        first = bot.decide(state).to_dict(state.tick)
        state.plows.reverse()
        self.assertEqual(bot.decide(state).to_dict(state.tick), first)

    def test_six_plows_never_share_street_destinations_or_swap_positions(self):
        rng = random.Random(6)
        tiles = ('G...', '.D..', '....', '....')
        streets = [(x, y) for y, row in enumerate(tiles) for x, tile in enumerate(row) if tile in '.G']
        steps = {'N': (0, -1), 'S': (0, 1), 'E': (1, 0), 'O': (-1, 0)}
        for trial in range(40):
            starts = rng.sample(streets, 6)
            plows = [Plow(f'p-{index}', 'us', Position(*cell), 'normal', False, rng.choice((0, 9, 19, 20)))
                     for index, cell in enumerate(starts)]
            state = make_state(tiles)
            state.tick = trial
            state.garage = Position(0, 0)
            state.plows = plows
            state.map.snow = [[10 if tile == '.' else 0 for tile in row] for row in tiles]
            orders = bot.decide(state)
            destinations = {plow.id: (plow.position.x, plow.position.y) for plow in plows}
            for action in orders.actions:
                if action['type'] == 'move':
                    x, y = destinations[action['plowId']]
                    dx, dy = steps[action['direction']]
                    destinations[action['plowId']] = ((x + dx) % 4, (y + dy) % 4)
            with self.subTest(trial=trial):
                self.assertIsNone(orders.buy)
                street_destinations = [cell for cell in destinations.values() if cell != (0, 0)]
                self.assertEqual(len(street_destinations), len(set(street_destinations)))
                for index, plow in enumerate(plows):
                    for other in plows[index + 1:]:
                        self.assertFalse(
                            destinations[plow.id] == (other.position.x, other.position.y)
                            and destinations[other.id] == (plow.position.x, plow.position.y)
                        )


class PurchaseTests(unittest.TestCase):
    def fleet_state(self, count, money=250):
        state = make_state(('############', '#G........D#', '############'), position=(2, 1), money=money)
        state.plows.extend(
            Plow(f'plow-{index}', 'us', Position(index + 2, 1), 'normal', False, 0)
            for index in range(1, count)
        )
        return state

    def test_buys_normal_plow_below_six_when_affordable_and_garage_free(self):
        for count in (1, 5):
            with self.subTest(count=count):
                self.assertEqual(bot.decide(self.fleet_state(count)).buy, 'normal')

    def test_does_not_buy_when_already_at_or_above_six(self):
        for count in (6, 7):
            with self.subTest(count=count):
                self.assertIsNone(bot.decide(self.fleet_state(count, money=10000)).buy)

    def test_does_not_buy_without_enough_money(self):
        self.assertIsNone(bot.decide(self.fleet_state(1, money=249)).buy)

    def test_purchase_uses_server_cost_and_counts_broken_plows(self):
        state = self.fleet_state(5, money=250)
        state.constants['plowCost']['normal'] = 300
        self.assertIsNone(bot.decide(state).buy)
        state = self.fleet_state(6, money=10000)
        state.plows[-1].broken = True
        self.assertIsNone(bot.decide(state).buy)

    def test_other_teams_do_not_count_toward_fleet_limit(self):
        state = self.fleet_state(5)
        state.plows.append(Plow('enemy', 'them', Position(8, 1), 'normal', False, None))
        self.assertEqual(bot.decide(state).buy, 'normal')

    def test_no_purchase_when_garage_is_occupied_even_if_plow_moves_away(self):
        state = make_state(money=10000)
        state.map.snow[1][2] = 5
        orders = bot.decide(state)
        self.assertIsNone(orders.buy)
        self.assertEqual(orders.actions[0]['type'], 'move')
        state = self.fleet_state(1)
        state.plows.append(Plow('enemy', 'them', state.garage, 'normal', True, None))
        self.assertIsNone(bot.decide(state).buy)


if __name__ == '__main__':
    unittest.main()
