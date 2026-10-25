from fleet.clock import authorized_time


def run():
    return {'committed': 10, 'sources': {'storage': {'run_id': 'r', 'epoch': 'e', 'offset': 0},
                                       'shipping': {'run_id': 's', 'epoch': 'f', 'offset': 0}}, 'observations': {}}


def observations():
    return {'storage': {'run_id': 'r', 'epoch': 'e', 'committed': 20, 'granted': 20, 'state': 'running', 'cursor': 'a', 'received_at': 100},
            'shipping': {'run_id': 's', 'epoch': 'f', 'committed': 15, 'granted': 18, 'state': 'running', 'cursor': 'b', 'received_at': 100}}


def test_earlier_grant_and_slowest_committed_source_bound_motion():
    time, reason = authorized_time(run(), observations(), 102)
    assert time == 15 and reason is None


def test_stale_held_missing_or_replaced_scope_never_authorizes_motion():
    for change in ({'received_at': 94}, {'state': 'held'}, {'epoch': 'replacement'}, {'committed': 19, 'granted': 18}):
        values = observations()
        values['shipping'].update(change)
        time, reason = authorized_time(run(), values, 100)
        assert time == 10 and reason
    assert authorized_time(run(), {}, 100)[0] == 10


def test_reversed_or_mutated_cursor_and_nonfinite_time_are_rejected():
    previous = run()
    previous['observations'] = observations()
    for change in ({'committed': 14}, {'committed': 16}, {'committed': float('nan')}, {'received_at': 200}):
        values = observations()
        values['shipping'].update(change)
        assert authorized_time(previous, values, 100)[1]
