"""Explicit first-run initialization; never replaces an existing physical scope."""
import json
import os
from pathlib import Path

from .navigation import Navigation, intersects
from .store import FleetStore, Conflict


def validate_configuration(topology, size):
    if type(size) is not int or not 1 <= size <= 16:
        raise ValueError('Fleet size must be an integer from 1 to 16')
    robots = topology['parking'][:size]
    if len(robots) != size:
        raise ValueError('Not enough validated parking positions')
    navigation, occupied = Navigation(topology), set()
    for robot in robots:
        pose = tuple(robot['pose'])
        cells = navigation.occupancy(pose)
        if not navigation._safe(pose) or not cells.isdisjoint(occupied):
            raise ValueError('Parking must be clear and disjoint')
        if any(intersects(navigation._rectangle(pose), lane['bounds']) for lane in topology['lanes']):
            raise ValueError('Parking cannot occupy through lanes')
        occupied.update(cells)
    return robots


def main():
    store = FleetStore(os.environ['DATABASE_URL'])
    store.migrate()
    topology = json.loads((Path(__file__).resolve().parents[1] / 'contracts/fleet/v1/navigation.json').read_text())
    robots = validate_configuration(topology, int(os.getenv('FLEET_SIZE', '8')))
    sources = json.loads(os.environ['FLEET_SCOPE'])
    run_id, epoch = os.environ['FLEET_RUN_ID'], os.environ['FLEET_EPOCH']
    with store.transaction() as db:
        old = db.execute('SELECT * FROM fleet_runs WHERE current').fetchone()
        if old:
            if str(old['id']) != run_id or str(old['epoch']) != epoch or old['sources'] != sources:
                raise Conflict('Existing fleet requires explicit physical reconciliation before scope replacement')
            if old['layout_digest'] != store.layout_digest:
                raise Conflict('Layout changed; physical reconciliation required before using existing fleet state')
            actual = db.execute('SELECT id,parking FROM fleet_robots WHERE run_id=%s ORDER BY id', (old['id'],)).fetchall()
            if actual != [{'id': r['id'], 'parking': r['pose']} for r in robots]:
                raise Conflict('Existing robot fleet configuration differs; reconcile before changing parking or size')
            return
    store.initialize(run_id, epoch, sources, robots)


if __name__ == '__main__':
    main()
