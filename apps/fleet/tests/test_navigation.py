"""Geometry assertions deliberately check world-space clearance, not lock IDs."""
import math

from fleet.navigation import Navigation


def floor(**extra):
    return Navigation({'bounds': [0, 0, 12, 12], 'cell_size': .25,
                       'obstacles': [], 'lanes': [], **extra})


def test_route_is_deterministic_and_cannot_cross_solid_equipment():
    obstacle = {'id': 'machine', 'bounds': [4, 0, 6, 8]}
    nav = floor(obstacles=[obstacle])
    route = nav.plan((2, 2, 0), (9, 2, 0))
    assert route is not None
    assert route == nav.plan((2, 2, 0), (9, 2, 0))
    assert any(p[1] > 8 for p in route.poses)
    for x, z, heading in route.poses:
        hx, hz = ((.425, .525) if heading % 2 == 0 else (.525, .425))
        assert x + hx + .15 <= 4 or x - hx - .15 >= 6 or z - hz - .15 >= 8


def test_enclosed_destination_is_unreachable_without_corner_cutting():
    nav = floor(obstacles=[{'id': 'wall', 'bounds': [4, 0, 6, 12]}])
    assert nav.plan((2, 2, 0), (9, 2, 0)) is None


def test_opposite_directed_lanes_use_distinct_space():
    nav = floor(lanes=[{'id': 'eastbound', 'bounds': [0, 2, 12, 4], 'direction': 1},
                       {'id': 'westbound', 'bounds': [0, 6, 12, 8], 'direction': 3}])
    east = nav.plan((2, 3, 1), (9, 3, 1))
    west = nav.plan((9, 7, 3), (2, 7, 3))
    assert east and west and east.resources.isdisjoint(west.resources)
    assert nav.plan((9, 3, 3), (2, 3, 3)) is None  # wrong-way start


def test_reservations_cover_body_turn_sweep_and_opposing_edges():
    nav = floor()
    first = nav.plan((2, 3, 1), (8, 3, 1))
    assert first
    assert nav.plan((8, 3, 3), (2, 3, 3), first.resources) is None
    turn = nav.plan((3, 3, 0), (3, 3, 1))
    assert turn and len(turn.resources) > len(nav.occupancy((3, 3, 0)))
    radius = math.hypot(.425, .525) + .15
    assert f'cell:{round((3 + radius - .1) / .25)}:12' in turn.resources


def test_parallel_headway_and_parked_robot_are_physical_obstacles():
    nav = floor()
    parked = nav.occupancy((5, 5, 0))
    route = nav.plan((2, 5, 1), (9, 5, 1), parked)
    assert route and route.resources.isdisjoint(parked)
    assert any(abs(z - 5) >= 1 for _, z, _ in route.poses)


def test_off_grid_connectors_retain_exact_pose_and_reject_swept_obstacle():
    nav = floor()
    route = nav.plan((2.1, 2.1, 0), (8.1, 8.1, 0))
    assert route and route.poses[0] == (2.1, 2.1, 0) and route.poses[-1] == (8.1, 8.1, 0)
    blocked = floor(obstacles=[{'id': 'post', 'bounds': [1.7, 1.7, 1.8, 1.8]}])
    assert blocked.plan((2.1, 2.1, 0), (8.1, 8.1, 0)) is None


def test_service_bays_at_different_heights_share_floor_exclusion():
    nav = floor()
    low = nav.service_resources({'position': [3, .45, 3]}, (4.5, 3, 0))
    high = nav.service_resources({'position': [3, 4.95, 3]}, (4.5, 3, 0))
    assert low == high
    assert low & nav.occupancy((3.5, 3, 0))
