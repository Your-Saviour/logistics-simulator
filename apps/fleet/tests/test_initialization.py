import json
from pathlib import Path
from copy import deepcopy

import pytest

from fleet.initialize import validate_configuration
from fleet.navigation import Navigation


def topology():
    return json.loads((Path('/app/contracts/fleet/v1/navigation.json')).read_text())


def test_default_parking_is_clear_disjoint_and_outside_through_lanes():
    value = topology()
    validate_configuration(value, 16)
    nav = Navigation(value)
    previous = set()
    for robot in value['parking']:
        cells = nav.occupancy(tuple(robot['pose']))
        assert cells.isdisjoint(previous)
        previous.update(cells)


def test_bad_size_and_overlapping_or_blocked_parking_are_rejected():
    for size in (0, 17, True):
        with pytest.raises(ValueError): validate_configuration(topology(), size)
    value = topology()
    value['parking'][1]['pose'] = value['parking'][0]['pose']
    with pytest.raises(ValueError): validate_configuration(value, 8)
    value = topology()
    value['parking'][0]['pose'] = [-28, -18, 0]  # inside raw rack
    with pytest.raises(ValueError): validate_configuration(value, 8)
