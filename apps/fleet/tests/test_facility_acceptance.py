"""Acceptance of the real fixed catalog, not synthetic unobstructed fixtures."""
import json
import pytest
from fleet_geometry_audit import audit, connectivity


@pytest.fixture(scope='module')
def fixed_floor():
    result = audit()
    print("FIXED_FLOOR_REPORT " + json.dumps(result, sort_keys=True))
    return result


def test_every_fixed_endpoint_has_loaded_body_and_fork_service_clearance(fixed_floor):
    assert fixed_floor['endpoints'] == 800
    assert fixed_floor['service_pose_count'] == 800
    assert not fixed_floor['issues'], (
        f"{fixed_floor['invalid_endpoints']}/800 unsafe fixed endpoint services; "
        f"by owner={fixed_floor['invalid_by_owner']}; first issues={fixed_floor['issues'][:16]}"
    )


def test_fixed_parking_has_clearance_and_no_overlap(fixed_floor):
    assert fixed_floor['parking_count'] == 16
    assert not fixed_floor['parking_issues'], fixed_floor['parking_issues']
    assert not fixed_floor['parking_conflicts'], fixed_floor['parking_conflicts']


def test_real_workflow_routes_are_available(fixed_floor):
    invalid = [r for r in fixed_floor['planner'] if not r['reachable']]
    assert not invalid, invalid


def test_every_endpoint_is_reachable_from_parking_and_can_return():
    for result in connectivity():
        assert not result['budget_exhausted'], f'Connectivity audit exceeded the finite grid-state bound: {result}'
        assert not result['unreachable_parking'], result
        assert not result['unreachable'], (
            f"{result['direction']}: {len(result['unreachable'])}/800 unreachable; "
            f"visited {result['states_visited']} directed states; "
            f"first endpoints={result['unreachable'][:32]}"
        )


def test_all_fixed_load_placements_retain_clearance_and_avoid_machines(fixed_floor):
    assert not fixed_floor['placement_conflicts'], fixed_floor['placement_conflicts'][:20]
    assert fixed_floor['minimum_load_gap'] >= .15-1e-8
    assert not fixed_floor['machine_load_conflicts'], fixed_floor['machine_load_conflicts']


def small_connectivity_floor(monkeypatch, tmp_path, blocked=False):
    import fleet_geometry_audit
    topology = {'bounds': [0, 0, 6, 6], 'cell_size': .25, 'lanes': [],
                'obstacles': [{'id': 'wall', 'bounds': [2.5, 0, 3.5, 6]}] if blocked else [],
                'parking': [{'id': 'robot-01', 'pose': [1, 1, 0]}],
                'service_poses': {'sample.endpoint': [4.5, 4, 0]}}
    for path, value in [('fleet/v1/navigation.json', topology),
                        ('handling/v1/facility.json', {'locations': [{'id': 'sample.endpoint'}]})]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))
    monkeypatch.setattr(fleet_geometry_audit, 'ROOT', tmp_path)
    return fleet_geometry_audit


def test_connectivity_proof_does_not_depend_on_wall_clock_scheduling(monkeypatch, tmp_path):
    from itertools import count
    from types import SimpleNamespace
    audit_module = small_connectivity_floor(monkeypatch, tmp_path)
    ticks = count(0, 100)
    monkeypatch.setattr(audit_module, 'time', SimpleNamespace(perf_counter=lambda: next(ticks)))
    for result in audit_module.connectivity():
        assert not result['budget_exhausted']
        assert not result['unreachable']
        assert not result['unreachable_parking']


def test_connectivity_proof_still_rejects_an_actual_disconnected_endpoint(monkeypatch, tmp_path):
    audit_module = small_connectivity_floor(monkeypatch, tmp_path, blocked=True)
    for result in audit_module.connectivity():
        assert not result['budget_exhausted']
        assert result['unreachable'] == ['sample.endpoint']
