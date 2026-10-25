import {useEffect,useLayoutEffect,useMemo,useRef,type RefObject} from 'react';
import {useFrame,useThree} from '@react-three/fiber';
import {BoxGeometry,Color,Group,InstancedMesh,Mesh,MeshStandardMaterial,Object3D} from 'three';
import {JourneyQueue,LIMITS,poseAt,type Movement,type MotionSource} from './journeys';
import {visibleUnits,type RecordedUnit,type Vec3} from './facility';
export type ReplayStats={active:number;queued:number;trails:number;skipped:number;unmapped:number;frozen:boolean};
export type ReplayProps={queue:JourneyQueue;movements:Movement[];sources:MotionSource[];reduced:boolean;units:RecordedUnit[];
  root:RefObject<HTMLDivElement|null>;onStats:(stats:ReplayStats)=>void;selected:string};
export const replayUnitKey=(unit:{run_id:string;epoch:string;id:string})=>`${unit.run_id}/${unit.epoch}/${unit.id}`;
export function ReplayDriver(props:ReplayProps) {
  const {invalidate}=useThree();
  const previous=useRef('');
  useLayoutEffect(()=>{props.queue.observe(props.movements,props.sources,performance.now(),props.reduced);invalidate();},[props.queue,props.movements,props.sources,props.reduced,invalidate]);
  useFrame(()=>{
    const queue=props.queue;queue.tick(performance.now());
    const running=(source:string)=>props.sources.some(state=>state.name===source&&state.running&&state.connected);
    const frozen=queue.active.length>0&&!queue.active.some(journey=>running(journey.move.source));
    const activeKeys=new Set(queue.active.map(journey=>`${journey.move.run_id}/${journey.move.epoch}/${journey.move.unit_id}`));
    const placed=visibleUnits(props.units);
    const staticCount=placed.filter(unit=>!activeKeys.has(replayUnitKey(unit))).length;
    const stats={active:queue.active.length,queued:queue.queued.length,trails:queue.trails.length,skipped:queue.skipped,unmapped:queue.unmapped,frozen};
    if(props.root.current) Object.assign(props.root.current.dataset,{activeJourneys:String(stats.active),queuedJourneys:String(stats.queued),staticUnits:String(staticCount),replayUnits:String(queue.active.length),replayFrozen:String(frozen),replayTrails:String(stats.trails)});
    const signature=JSON.stringify(stats);if(previous.current!==signature){previous.current=signature;props.onStats(stats);}
    if(queue.active.some(journey=>running(journey.move.source))||queue.trails.some(trail=>running(trail.move.source))||queue.queued.some(journey=>running(journey.move.source))) invalidate();
  },-2);
  return null;
}
export function RobotFleet(props:ReplayProps) {
  const groups=useRef<(Group|null)[]>([]),parts=useRef<(InstancedMesh|null)[]>([]),trails=useRef<InstancedMesh>(null);
  const object=useMemo(()=>new Object3D(),[]);
  const units=useMemo(()=>new Map(props.units.map(unit=>[replayUnitKey(unit),unit])),[props.units]);
  const geometry=useMemo(()=>new BoxGeometry(.8,.72,.86),[]);
  const materials=useMemo(()=>({raw:new MeshStandardMaterial({color:'#c5a276',roughness:.85}),finished:new MeshStandardMaterial({color:'#82aa9d',roughness:.85}),selected:new MeshStandardMaterial({color:'#ffb800',roughness:.85})}),[]);
  useEffect(()=>()=>{geometry.dispose();Object.values(materials).forEach(material=>material.dispose());},[geometry,materials]);
  useLayoutEffect(()=>{if(trails.current){trails.current.setColorAt(0,new Color(1,1,1));trails.current.count=0;}},[]);
  const colors=['#d7b568','#607f88','#2c393e','#bbc7c4'];
  function place(part:number,index:number,at:Vec3,size:Vec3,rotation=0) {
    object.position.set(...at);object.scale.set(...size);object.rotation.set(0,rotation,0);object.updateMatrix();
    parts.current[part]?.setMatrixAt(index,object.matrix);
  }
  useFrame(()=>{
    const active=props.queue.active;
    for(let index=0;index<LIMITS.active;index++) {
      const root=groups.current[index],journey=active[index];
      if(root) root.visible=!!journey;
      if(!journey) continue;
      const p=journey.elapsed/journey.duration,pose=poseAt(journey.route,p),ahead=poseAt(journey.route,Math.min(1,p+.002));
      const [x,,z]=pose.position;
      let dx=ahead.position[0]-x,dz=ahead.position[2]-z;
      if(Math.hypot(dx,dz)<.00001){dx=pose.forkOffset[0];dz=pose.forkOffset[2];}
      const yaw=Math.atan2(dx,dz),sin=Math.sin(yaw),cos=Math.cos(yaw);
      const height=Math.max(1.3,pose.forkHeight+.6);
      place(0,index,[x,.3,z],[.85,.38,1.05],yaw);
      place(1,index,[x-sin*.32,height/2,z-cos*.32],[.12,height,.12],yaw);
      for(let wheel=0;wheel<4;wheel++) {
        const a=wheel<2 ? -.44 : .44,b=wheel%2 ? -.33 : .33;
        place(2,index*4+wheel,[x+a*cos+b*sin,.18,z-a*sin+b*cos],[.16,.25,.29],yaw);
      }
      const reach=Math.hypot(pose.forkOffset[0],pose.forkOffset[2]),forkYaw=reach>.01 ? Math.atan2(pose.forkOffset[0],pose.forkOffset[2]) : yaw;
      for(let fork=0;fork<2;fork++) {
        const side=fork ? .23 : -.23;
        place(3,index*2+fork,[x+pose.forkOffset[0]/2+side*Math.cos(forkYaw),pose.forkHeight-.04,z+pose.forkOffset[2]/2-side*Math.sin(forkYaw)],[.1,.07,Math.max(.9,reach+.5)],forkYaw);
      }
      if(root) {
        root.position.set(x,0,z);
        const carried=root.children[0] as Mesh;
        if(pose.phase==='pickup'&&!pose.carrying) carried.position.set(journey.route.origin.position[0]-x,journey.route.origin.position[1]+.36,journey.route.origin.position[2]-z);
        else if(pose.phase==='place'&&!pose.carrying) carried.position.set(journey.route.destination.position[0]-x,journey.route.destination.position[1]+.36,journey.route.destination.position[2]-z);
        else carried.position.set(pose.forkOffset[0],pose.forkHeight+.36,pose.forkOffset[2]);
        const unit=units.get(`${journey.move.run_id}/${journey.move.epoch}/${journey.move.unit_id}`);
        carried.material=unit&&props.selected===`unit:${unit.run_id}:${unit.epoch}:${unit.id}` ? materials.selected : unit?.category==='finished' ? materials.finished : materials.raw;
      }
    }
    parts.current.forEach((part,index)=>{if(part){part.count=active.length*(index===2?4:index===3?2:1);part.instanceMatrix.needsUpdate=true;}});
    if(trails.current) {
      let index=0;
      for(const trail of props.queue.trails) for(let segment=1;segment<trail.route.points.length;segment++) {
        const a=trail.route.points[segment-1],b=trail.route.points[segment],length=Math.hypot(b[0]-a[0],b[2]-a[2]);
        object.position.set((a[0]+b[0])/2,.025,(a[2]+b[2])/2);object.scale.set(.055,.025,length);object.rotation.set(0,Math.atan2(b[0]-a[0],b[2]-a[2]),0);object.updateMatrix();
        trails.current.setMatrixAt(index,object.matrix);const alpha=1-trail.elapsed/LIMITS.trail;trails.current.setColorAt(index,new Color(alpha,alpha,alpha));index++;
      }
      trails.current.count=index;trails.current.instanceMatrix.needsUpdate=true;if(trails.current.instanceColor)trails.current.instanceColor.needsUpdate=true;
    }
  },-1);
  return <>
    {colors.map((color,index)=><instancedMesh key={color} ref={node=>{parts.current[index]=node;}} args={[undefined,undefined,LIMITS.active*(index===2?4:index===3?2:1)]} frustumCulled={false}><boxGeometry/><meshStandardMaterial color={color} roughness={.8}/></instancedMesh>)}
    {Array.from({length:LIMITS.active},(_,index)=><group key={index} name={`visual-robot-${index+1}`} ref={node=>{groups.current[index]=node;}} visible={false}><mesh name="carried-unit" geometry={geometry} material={materials.raw} dispose={null}/></group>)}
    <instancedMesh ref={trails} args={[undefined,undefined,LIMITS.queued*5]} frustumCulled={false}><boxGeometry/><shaderMaterial transparent depthWrite={false}
      vertexShader={'varying float fade; void main(){fade=instanceColor.r;gl_Position=projectionMatrix*modelViewMatrix*instanceMatrix*vec4(position,1.0);}'}
      fragmentShader={'varying float fade;void main(){gl_FragColor=vec4(0.85,0.68,0.32,0.45*fade);}'}/></instancedMesh>
  </>;
}
