"""Deterministic heading-aware grid routing with conservative swept envelopes.

Reservations rasterize expanded physical envelopes, not just path centre cells.
An intersecting raster cell therefore conflicts even for different lane/edge IDs.
All coordinates use facility metres, x east and z south. Heading 0 is north.
"""
from dataclasses import dataclass
from functools import lru_cache
import heapq
import math


@dataclass(frozen=True)
class Route:
    poses: tuple[tuple[float, float, int], ...]
    resources: frozenset[str]
    distance: float


def intersects(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


class Navigation:
    def __init__(self, topology):
        self.topology = topology
        self.cell = float(topology['cell_size'])
        self.bounds = tuple(topology['bounds'])
        self.obstacles = tuple(tuple(o['bounds']) for o in topology['obstacles'])
        self.lanes = topology.get('lanes', [])
        self.clearance = .15
        self.half_width, self.half_length = .425, .525
        if self.cell <= 0 or not all(math.isfinite(n) for n in self.bounds):
            raise ValueError('Finite floor bounds and positive cell size required')

    def _rectangle(self, pose, turning=False):
        x, z, heading = pose
        if turning:
            hx = hz = math.hypot(self.half_width, self.half_length)
        else:
            hx, hz = ((self.half_width, self.half_length) if heading % 2 == 0
                      else (self.half_length, self.half_width))
        return (x - hx - self.clearance, z - hz - self.clearance,
                x + hx + self.clearance, z + hz + self.clearance)

    @lru_cache(maxsize=262144)
    def _cells(self, bounds):
        # Resource (i,j) is the square centred on (i*cell,j*cell).
        a, b, c, d = bounds
        low_x, high_x = math.floor(a / self.cell + .5), math.ceil(c / self.cell - .5)
        low_z, high_z = math.floor(b / self.cell + .5), math.ceil(d / self.cell - .5)
        return frozenset(f'cell:{x}:{z}' for x in range(low_x, high_x + 1)
                         for z in range(low_z, high_z + 1))

    def occupancy(self, pose):
        return self._cells(self._rectangle(tuple(pose)))

    def service_resources(self, endpoint, pose):
        x, _, z = endpoint['position']
        bounds = self._rectangle(pose)
        # Includes the extended fork and load sweep from service pose to shelf.
        return self._cells((min(bounds[0], x - .55), min(bounds[1], z - .58),
                            max(bounds[2], x + .55), max(bounds[3], z + .58)))

    @lru_cache(maxsize=262144)
    def _safe(self, pose, turning=False):
        rect = self._rectangle(pose, turning)
        if rect[0] < self.bounds[0] or rect[1] < self.bounds[1] or rect[2] > self.bounds[2] or rect[3] > self.bounds[3]:
            return False
        if any(intersects(rect, obstacle) for obstacle in self.obstacles):
            return False
        x, z, heading = pose
        return all(heading == lane['direction'] or (lane.get('crossing') and heading % 2 != lane['direction'] % 2) for lane in self.lanes
                   if lane['bounds'][0] <= x <= lane['bounds'][2]
                   and lane['bounds'][1] <= z <= lane['bounds'][3])

    def _sweep(self, first, second):
        turn = first[2] != second[2]
        a, b = self._rectangle(first, turn), self._rectangle(second, turn)
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))

    def _edge(self, first, second, occupied):
        turn = first[2] != second[2]
        if not self._safe(first, turn) or not self._safe(second, turn):
            return None
        sweep = self._sweep(first, second)
        if any(intersects(sweep, obstacle) for obstacle in self.obstacles):
            return None
        cells = self._cells(sweep)
        return cells if cells.isdisjoint(occupied) else None

    def plan(self, start, destination, occupied=frozenset()):
        start, destination = tuple(start), tuple(destination)
        if (len(start) != 3 or len(destination) != 3 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    for p in (start, destination) for v in p) or
                start[2] not in range(4) or destination[2] not in range(4)):
            raise ValueError('Finite x/z coordinates and cardinal integer heading required')
        snap = lambda p: (round(p[0] / self.cell) * self.cell,
                          round(p[1] / self.cell) * self.cell, p[2])
        first, goal = snap(start), snap(destination)
        if self._edge(start, first, occupied) is None or self._edge(goal, destination, occupied) is None:
            return None
        heuristic = lambda p: abs(p[0] - goal[0]) + abs(p[1] - goal[1])
        pending = [(heuristic(first), 0, first)]
        costs, parents = {first: 0}, {}
        directions = ((0, -1), (1, 0), (0, 1), (-1, 0))
        while pending:
            _, cost, pose = heapq.heappop(pending)
            if cost != costs.get(pose):
                continue
            if pose == goal:
                path = [pose]
                while pose in parents:
                    pose = parents[pose]
                    path.append(pose)
                path.reverse()
                if start != first:
                    path.insert(0, start)
                if destination != goal:
                    path.append(destination)
                resources = set(self.occupancy(start))
                for a, b in zip(path, path[1:]):
                    resources.update(self._cells(self._sweep(a, b)))
                distance = sum(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(path, path[1:]))
                return Route(tuple(path), frozenset(resources), distance)
            x, z, h = pose
            dx, dz = directions[h]
            neighbors = [((x + dx * self.cell, z + dz * self.cell, h), self.cell),
                         ((x, z, (h + 1) % 4), .5), ((x, z, (h - 1) % 4), .5)]
            for next_pose, increment in neighbors:
                next_cost = cost + increment
                if next_cost >= costs.get(next_pose, math.inf) or self._edge(pose, next_pose, occupied) is None:
                    continue
                costs[next_pose], parents[next_pose] = next_cost, pose
                heapq.heappush(pending, (next_cost + heuristic(next_pose), next_cost, next_pose))
        return None
