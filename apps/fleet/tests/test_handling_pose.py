import pytest
from fleet.handling_pose import handling_pose, handling_duration


def test_shelf_load_is_raised_above_frontbeam_before_horizontal_withdrawal():
    origin=[0,4.95,0]
    for progress in (.53,.55,.6,.63):
        pose=handling_pose('picking_up',progress,(1.5,0,0),origin,[8,.3,0])
        assert pose['load_position'][1]-.36 >= 5.21-1e-9
        assert pose['fork_height']-.075 >= 4.95+.035+.15
    lowered=handling_pose('picking_up',.9,(1.5,0,0),origin,[8,.3,0])
    assert lowered['fork_offset']==[0,0]
    assert lowered['load_position'][0]==1.5


def test_pallet_pocket_insertion_clears_frontbeam_and_forks_retract_after_placement():
    inserted=handling_pose('picking_up',.3,(1.5,0,0),[0,1.95,0],[8,.3,0])
    assert inserted['fork_height']-.075 > 1.95+.035
    placing=handling_pose('placing',.65,(9.5,0,0),[0,1.95,0],[8,4.95,0])
    assert placing['load_position'][1]-.36 >= 5.21-1e-9
    placed=handling_pose('awaiting_receipt',1,(9.5,0,0),[0,1.95,0],[8,4.95,0])
    assert placed['fork_offset']==[0,0]
    assert placed['load_position']==pytest.approx([8,5.31,0])


def test_transit_load_remains_inside_body_envelope_and_fork_pocket_height():
    pose=handling_pose('carrying',.5,(5,3,1),[0,.3,0],[8,.3,0])
    assert pose['load_position']==[5,.91,3]
    assert pose['fork_height']==pytest.approx(.675)


def test_lift_motion_is_bounded_by_half_a_metre_per_simulation_second():
    body,origin,destination=(1.5,0,0),[0,4.95,0],[8,.3,0]
    total=handling_duration('picking_up',body,origin,destination)
    previous=handling_pose('picking_up',0,body,origin,destination)
    for index in range(1,1001):
        current=handling_pose('picking_up',index/1000,body,origin,destination)
        assert abs(current['fork_height']-previous['fork_height']) <= .5*total/1000+1e-9
        previous=current
