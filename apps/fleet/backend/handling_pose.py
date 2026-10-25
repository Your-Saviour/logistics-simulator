"""Bounded pallet/fork stages; own support contact never permits beam crossing."""
import math

# Increment on physical stage/envelope changes so persisted plans from another
# motion model cannot silently resume under different movement semantics.
MOTION_MODEL_VERSION = 2


def clamp(value):
    return max(0,min(1,value))


def stage_times(state, body, origin, destination):
    x,z,_=body
    at=origin if state=='picking_up' else destination
    reach=math.hypot(at[0]-x,at[2]-z)
    if state=='picking_up':
        return [abs(at[1]+.125-.15)/.5,reach/.5,.26/.5,reach/.5,abs(at[1]+.26-.55)/.5]
    return [abs(at[1]+.26-.55)/.5,reach/.5,.26/.5,reach/.5]


def handling_duration(state, body, origin, destination):
    return sum(stage_times(state,body,origin,destination))


def handling_pose(state, progress, body, origin, destination):
    x,z,_=body
    base,offset,load=.55,[0,0],[x,.91,z]
    p=clamp(progress)
    height=base+.125  # forks enter the pallet pocket, below its upper deck
    if state=='picking_up':
        ox,oy,oz=origin
        times=stage_times(state,body,origin,destination)
        elapsed=p*sum(times)
        stage=0
        while stage<len(times)-1 and elapsed>=times[stage]:
            elapsed-=times[stage];stage+=1
        fraction=clamp(elapsed/times[stage]) if times[stage] else 1
        if stage==0:
            height=.15+(oy+.125-.15)*fraction
            offset=[0,0]
            load=[ox,oy+.36,oz]
        elif stage==1:
            height=oy+.125
            reach=fraction
            offset=[(ox-x)*reach,(oz-z)*reach]
            load=[ox,oy+.36,oz]
        elif stage==2:
            base=oy+.26*fraction
            height=base+.125
            offset=[ox-x,oz-z]
            load=[ox,base+.36,oz]
        elif stage==3:
            base=oy+.26
            height=base+.125
            retract=fraction
            offset=[(ox-x)*(1-retract),(oz-z)*(1-retract)]
            load=[x+offset[0],base+.36,z+offset[1]]
        else:
            base=oy+.26+(.55-oy-.26)*fraction
            height=base+.125
            load=[x,base+.36,z]
    elif state in {'placing','awaiting_receipt'}:
        dx,dy,dz=destination
        times=stage_times('placing',body,origin,destination)
        elapsed=p*sum(times)
        stage=0
        while stage<len(times)-1 and elapsed>=times[stage]:
            elapsed-=times[stage];stage+=1
        fraction=clamp(elapsed/times[stage]) if times[stage] else 1
        if state=='awaiting_receipt' or stage==3:
            height=dy+.125
            retract=1 if state=='awaiting_receipt' else fraction
            offset=[(dx-x)*(1-retract),(dz-z)*(1-retract)]
            load=[dx,dy+.36,dz]
        elif stage==0:
            base=.55+(dy+.26-.55)*fraction
            height=base+.125
            load=[x,base+.36,z]
        elif stage==1:
            base=dy+.26
            height=base+.125
            extend=fraction
            offset=[(dx-x)*extend,(dz-z)*extend]
            load=[x+offset[0],base+.36,z+offset[1]]
        else:
            base=dy+.26-.26*fraction
            height=base+.125
            offset=[dx-x,dz-z]
            load=[dx,base+.36,dz]
    return {'fork_height':height,'fork_offset':offset,'load_position':load}
