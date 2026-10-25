import {useEffect,useLayoutEffect,useMemo,useRef} from 'react';
import {useThree} from '@react-three/fiber';
import {BufferGeometry,Float32BufferAttribute,InstancedMesh,Object3D} from 'three';
import topology from '../../../../contracts/fleet/v1/navigation.json' with {type:'json'};
import type {FleetObservation} from './fleetState';

/** Every transform comes from a reported snapshot; no frame-time interpolation. */
export function OperationalFleet({fleet,selected}:{fleet:FleetObservation;selected:string}) {
  const mesh=useRef<InstancedMesh>(null),loads=useRef<InstancedMesh>(null),pallets=useRef<InstancedMesh>(null),forks=useRef<InstancedMesh>(null);
  const object=useMemo(()=>new Object3D(),[]),{invalidate}=useThree();
  const robots=fleet.snapshot?.robots??[];
  useLayoutEffect(()=>{
    robots.forEach((robot,index)=>{
      const [x,z,h]=robot.pose,yaw=h*Math.PI/2;
      const write=(target:InstancedMesh|null,slot:number,at:number[],size:number[],rotation=yaw)=>{
        if(!target)return;object.position.set(at[0],at[1],at[2]);object.scale.set(size[0],size[1],size[2]);
        object.rotation.set(0,rotation,0);object.updateMatrix();target.setMatrixAt(slot,object.matrix);
      };
      write(mesh.current,index*2,[x,.3,z],[.85,.38,1.05]);
      write(mesh.current,index*2+1,[x,Math.max(.7,robot.fork_height/2),z],[.12,Math.max(1.3,robot.fork_height+.6),.12]);
      const [dx,dz]=robot.fork_offset,reach=Math.hypot(dx,dz),angle=reach>.01?Math.atan2(dx,dz):yaw;
      for(let side=0;side<2;side++){
        const offset=side?.23:-.23;
        write(forks.current,index*2+side,[x+dx/2+offset*Math.cos(angle),robot.fork_height-.04,z+dz/2-offset*Math.sin(angle)],[.1,.07,Math.max(.9,reach+.5)],angle);
      }
      const at=robot.load_position,visible=Boolean(robot.carried_unit_id&&at);
      const loadYaw=(robot.load_heading??h)*Math.PI/2,center=at??[0,0,0];
      write(loads.current,index,[center[0],center[1]+.08,center[2]],visible?[.8,.56,.86]:[0,0,0],loadYaw);
      const parts=[{offset:[0,-.21,0],size:[.8,.02,.86]},
        ...[-.34,.34].flatMap(px=>[-.36,.36].map(pz=>({offset:[px,-.29,pz],size:[.08,.14,.06]})))];
      parts.forEach((part,partIndex)=>{
        const [px,py,pz]=part.offset,c=Math.cos(loadYaw),s=Math.sin(loadYaw);
        write(pallets.current,index*5+partIndex,[center[0]+px*c+pz*s,center[1]+py,center[2]-px*s+pz*c],visible?part.size:[0,0,0],loadYaw);
      });
    });
    for(const target of [mesh.current,forks.current,loads.current,pallets.current])if(target){target.count=robots.length*(target===loads.current?1:target===pallets.current?5:2);target.instanceMatrix.needsUpdate=true;}
    invalidate();
  },[robots,object,invalidate,selected]);
  return <>
    <instancedMesh ref={mesh} args={[undefined,undefined,32]} frustumCulled={false}><boxGeometry/><meshLambertMaterial color={fleet.stale?'#82999e':'#d7b568'}/></instancedMesh>
    <instancedMesh ref={forks} args={[undefined,undefined,32]} frustumCulled={false}><boxGeometry/><meshLambertMaterial color="#bbc7c4"/></instancedMesh>
    <instancedMesh ref={pallets} args={[undefined,undefined,80]} frustumCulled={false}><boxGeometry/><meshLambertMaterial color="#8b7154"/></instancedMesh>
    <instancedMesh ref={loads} args={[undefined,undefined,16]} frustumCulled={false}><boxGeometry/><meshLambertMaterial color="#c5a276"/></instancedMesh>
  </>;
}

export function NavigationGrid({fleet}:{fleet:FleetObservation}) {
  const {invalidate}=useThree(),reserved=useRef<InstancedMesh>(null),object=useMemo(()=>new Object3D(),[]);
  const geometry=useMemo(()=>{
    const points:number[]=[],[a,b,c,d]=topology.bounds,step=topology.cell_size;
    // Resource cells are centred on integer grid indices. Lines mark their
    // half-cell edges, independent of the non-aligned physical floor bounds.
    for(let x=(Math.ceil(a/step-.5)+.5)*step;x<=c;x+=step)points.push(x,.018,b,x,.018,d);
    for(let z=(Math.ceil(b/step-.5)+.5)*step;z<=d;z+=step)points.push(a,.018,z,c,.018,z);
    const result=new BufferGeometry();result.setAttribute('position',new Float32BufferAttribute(points,3));return result;
  },[]);
  const arrows=useMemo(()=>{
    const points:number[]=[];
    for(const lane of topology.lanes){const [a,b,c,d]=lane.bounds,z=(b+d)/2,sign=lane.direction===1?1:-1;
      for(let x=a+2;x<c-2;x+=6)points.push(x-sign*.6,.04,z,x+sign*.6,.04,z,x+sign*.6,.04,z,x+sign*.2,.04,z-.35,x+sign*.6,.04,z,x+sign*.2,.04,z+.35);
    }
    const result=new BufferGeometry();result.setAttribute('position',new Float32BufferAttribute(points,3));return result;
  },[]);
  useEffect(()=>()=>{geometry.dispose();arrows.dispose();},[geometry,arrows]);
  const cells=(fleet.snapshot?.reservations??[]).flatMap(row=>{
    const match=/^cell:(-?\d+):(-?\d+)$/.exec(row.resource);
    return match?[[Number(match[1])*topology.cell_size,Number(match[2])*topology.cell_size]]:[];
  });
  useLayoutEffect(()=>{
    if(reserved.current){cells.forEach(([x,z],index)=>{object.position.set(x,.027,z);object.rotation.set(0,0,0);object.scale.set(1,1,1);object.updateMatrix();reserved.current!.setMatrixAt(index,object.matrix);});reserved.current.count=cells.length;reserved.current.instanceMatrix.needsUpdate=true;}
    invalidate();
  },[cells,object,invalidate]);
  return <>
    <lineSegments geometry={geometry}><lineBasicMaterial color="#a5b8b8" transparent opacity={.16} depthWrite={false}/></lineSegments>
    <lineSegments geometry={arrows}><lineBasicMaterial color="#83d6cb"/></lineSegments>
    <instancedMesh key={cells.length} ref={reserved} args={[undefined,undefined,Math.max(1,cells.length)]} frustumCulled={false}><boxGeometry args={[.23,.012,.23]}/><meshBasicMaterial color="#ffb800" transparent opacity={.3} depthWrite={false}/></instancedMesh>
  </>;
}
