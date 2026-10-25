import {Component, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {Canvas, useFrame, useThree, type ThreeEvent} from '@react-three/fiber';
import {Html} from '@react-three/drei/web/Html.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {Color, InstancedMesh, Object3D, OrthographicCamera} from 'three';
import {facility, rackGroups, truckGroups, recordedPlacement, visibleUnits, type RecordedUnit, type Vec3} from './facility';
import {JourneyQueue,type Movement} from './journeys';
import {ReplayDriver,RobotFleet,replayUnitKey,type ReplayProps,type ReplayStats} from './RobotReplay';
import type {SceneEntity} from './sceneState';
import './facility3d.css';

type Props = {
  entities: SceneEntity[]; selected: string; choose: (entity: SceneEntity) => void; lost: boolean;
  units?: RecordedUnit[]; sources?: SceneEntity['source'][]; movements?:Movement[];
};
const COLORS = {floor: '#303c40', steel: '#82999e', beam: '#d29c50', raw: '#c5a276', finished: '#82aa9d', selected: '#ffb800'};
const racks = rackGroups();
function Box({at, size, color}: {at: Vec3; size: Vec3; color: string}) {
  return <mesh position={at}><boxGeometry args={size}/><meshStandardMaterial color={color} roughness={0.8}/></mesh>;
}
function Rack({rack}: {rack: typeof racks[number]}) {
  const x = rack.slots[0].position[0];
  const minimum = Math.min(...rack.slots.map(slot => slot.position[2])) - .7;
  const maximum = Math.max(...rack.slots.map(slot => slot.position[2])) + .7;
  return <group>
    {[-.58,.58].flatMap(dx => [minimum,maximum].map(z => <Box key={`${dx}:${z}`} at={[x+dx,2.7,z]} size={[.09,5.4,.09]} color={COLORS.steel}/>))}
    {rack.elevations.map(y => <group key={y}>
      <Box at={[x,y-.07,(minimum+maximum)/2]} size={[1.2,.12,maximum-minimum]} color="#65777c"/>
      {[-.6,.6].map(dx => <Box key={dx} at={[x+dx,y-.04,(minimum+maximum)/2]} size={[.06,.15,maximum-minimum]} color={COLORS.beam}/>)}
    </group>)}
  </group>;
}
function Markers() {
  const ref = useRef<InstancedMesh>(null);
  const locations = useMemo(() => facility.locations.filter(location => location.kind !== 'shelf'), []);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const object = new Object3D();
    locations.forEach((location,index) => {
      object.position.set(location.position[0],location.position[1]-.08,location.position[2]);
      object.updateMatrix(); ref.current!.setMatrixAt(index, object.matrix);
      ref.current!.setColorAt(index,new Color(location.kind === 'truck' ? '#9aa6a4' : location.owner === 'manufacturing' ? '#819caf' : '#a79973'));
    });
    ref.current.instanceMatrix.needsUpdate = true;
    if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
  },[locations]);
  return <instancedMesh ref={ref} args={[undefined,undefined,locations.length]}><boxGeometry args={[1.05,.12,1.05]}/><meshStandardMaterial roughness={.8}/></instancedMesh>;
}
function Machines() {
  const cells = useMemo(() => facility.locations.filter(location => location.kind === 'cell_input' && location.id.endsWith('input01')), []);
  return <group>{cells.map(cell => <group key={cell.id} position={[cell.position[0],0,cell.position[2]+1.6]}>
    <Box at={[.6,.15,0]} size={[2.2,.3,1.7]} color="#53676b"/>
    <Box at={[.6,1.25,-.25]} size={[1.7,2.2,1.05]} color="#82959c"/>
    <Box at={[.6,1.4,.3]} size={[1.2,.95,.08]} color="#213a42"/>
    <Box at={[.6,.65,1]} size={[1.7,.18,.8]} color="#aab5b0"/>
    <Box at={[-.35,1.6,.1]} size={[.18,.7,.5]} color={COLORS.beam}/>
  </group>)}</group>;
}
function Trucks() {
  const trucks = useMemo(truckGroups,[]);
  return <group>{trucks.map(({id,slots}) => {
    const x=slots[0].position[0], minimum=Math.min(...slots.map(slot=>slot.position[2]))-.55;
    const maximum=Math.max(...slots.map(slot=>slot.position[2]))+.55;
    return <group key={id}>
      <Box at={[x,.72,(minimum+maximum)/2]} size={[1.5,.22,maximum-minimum]} color="#899a9a"/>
      <Box at={[x-.78,1.1,(minimum+maximum)/2]} size={[.1,.85,maximum-minimum]} color="#adb9b6"/>
      <Box at={[x,1.1,minimum-.8]} size={[1.6,1.5,1.4]} color="#6f8d9b"/>
      <Box at={[x,1.65,minimum-1.51]} size={[1.1,.45,.04]} color="#263e46"/>
      {[minimum+.7,maximum-.7,minimum-.8].flatMap(z => [-.72,.72].map(dx => <mesh key={`${z}:${dx}`} position={[x+dx,.37,z]} rotation={[0,0,Math.PI/2]}><cylinderGeometry args={[.32,.32,.18,12]}/><meshStandardMaterial color="#18262b"/></mesh>))}
    </group>;
  })}</group>;
}

function Units(props: Props & {replay:ReplayProps}) {
  const records = useMemo(() => visibleUnits(props.units ?? []), [props.units]);
  const ref = useRef<InstancedMesh>(null);
  const temporary=useMemo(()=>new Object3D(),[]);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const object = temporary;
    records.forEach((unit,index) => {
      const position = recordedPlacement(unit)!;
      object.position.set(position[0],position[1]+.36,position[2]); object.updateMatrix();
      ref.current!.setMatrixAt(index,object.matrix);
      ref.current!.setColorAt(index,new Color(props.selected === `unit:${unit.run_id}:${unit.epoch}:${unit.id}` ? COLORS.selected : unit.category === 'raw' ? COLORS.raw : COLORS.finished));
    });
    ref.current.instanceMatrix.needsUpdate = true;
    if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
  },[records,props.selected,temporary]);
  useFrame(()=>{
    if(!ref.current)return;
    const active=new Set(props.replay.queue.active.map(journey=>`${journey.move.run_id}/${journey.move.epoch}/${journey.move.unit_id}`));
    const object=temporary;
    records.forEach((unit,index)=>{const position=recordedPlacement(unit)!;object.position.set(position[0],position[1]+.36,position[2]);object.scale.setScalar(active.has(replayUnitKey(unit))?0:1);object.updateMatrix();ref.current!.setMatrixAt(index,object.matrix);});
    ref.current.instanceMatrix.needsUpdate=true;
  });
  function choose(event: ThreeEvent<MouseEvent>) {
    if (event.instanceId === undefined) return;
    const unit = records[event.instanceId], source = props.sources?.find(source => source.name === unit.owner);
    if (!source) return;
    event.stopPropagation();
    props.choose({key:`unit:${unit.run_id}:${unit.epoch}:${unit.id}`,kind:'handling unit',label:unit.barcode,
      row:unit as unknown as Record<string,unknown>,related:[],source});
  }
  if (!records.length) return null;
  return <instancedMesh ref={ref} args={[undefined,undefined,records.length]} onClick={choose}>
    <boxGeometry args={[.8,.72,.86]}/><meshStandardMaterial roughness={.88}/>
  </instancedMesh>;
}
function Camera({reset}: {reset: number}) {
  const {camera,size,gl,invalidate} = useThree();
  const controls = useMemo(() => new OrbitControls(camera),[camera]);
  useLayoutEffect(() => {
    camera.position.set(75,83,100); camera.lookAt(-1,0,1);
    if (camera instanceof OrthographicCamera) {camera.zoom=Math.max(2,Math.min(size.width/112,size.height/86));camera.updateProjectionMatrix();}
    controls.target.set(-1,0,1);controls.minPolarAngle=.12;controls.maxPolarAngle=Math.PI/2.1;
    controls.minZoom=2;controls.maxZoom=75;controls.enableDamping=true;controls.update();invalidate();
  },[camera,size.width,size.height,reset,controls,invalidate]);
  useEffect(() => {const redraw=()=>invalidate();controls.connect(gl.domElement);controls.addEventListener('change',redraw);return () => {controls.removeEventListener('change',redraw);controls.dispose();};},[controls,gl,invalidate]);
  useFrame(() => controls.update());
  return null;
}
function World(props: Props & {replay:ReplayProps}) {
  return <>
    <Box at={[-1,-.22,1]} size={[91,.4,61]} color={COLORS.floor}/>
    <Box at={[-46,1,1]} size={[.18,2,61]} color="#7b9297"/>
    <Box at={[-1,1,-29.5]} size={[91,2,.18]} color="#7b9297"/>
    {facility.lanes.map(lane => {
      const dx=lane.to[0]-lane.from[0], dz=lane.to[2]-lane.from[2];
      return <group key={lane.id}>
        <Box at={[(lane.from[0]+lane.to[0])/2,.003,(lane.from[2]+lane.to[2])/2]} size={[Math.abs(dx)||2.1,.015,Math.abs(dz)||2.1]} color="#243237"/>
      </group>;
    })}
    {racks.map(rack => <Rack key={rack.id} rack={rack}/>)}
    <ReplayDriver {...props.replay}/><Markers/><Machines/><Trucks/><Units {...props}/><RobotFleet {...props.replay}/>
    {([{text:'Raw storage',at:[-18,7,-14]},{text:'Finished storage',at:[-18,7,12]},{text:'Manufacturing',at:[7,5,1]},{text:'Inbound',at:[-39,3,-22]},{text:'Outbound',at:[29,4,-22]}] as {text:string;at:Vec3}[]).map(label =>
      <Html key={label.text} center position={label.at} zIndexRange={[20,0]}><span className="facility-area-label">{label.text}</span></Html>)}
  </>;
}
class SceneBoundary extends Component<{children: ReactNode; onFailure: () => void}, {failed: boolean}> {
  state={failed:false};
  static getDerivedStateFromError() {return {failed:true};}
  componentDidCatch() {this.props.onFailure();}
  render() {return this.state.failed ? <p className="scene-unavailable">3D graphics are unavailable. Recorded units remain available in the asset list.</p> : this.props.children;}
}
export default function Facility3D(props: Props) {
  const root=useRef<HTMLDivElement>(null),queue=useRef(new JourneyQueue());
  const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(()=>{const query=matchMedia('(prefers-reduced-motion: reduce)'),update=()=>setReduced(query.matches);query.addEventListener('change',update);return()=>query.removeEventListener('change',update);},[]);
  const [stats,setStats]=useState<ReplayStats>({active:0,queued:0,trails:0,skipped:0,unmapped:0,frozen:false});
  const sources=useMemo(()=>(props.sources??[]).flatMap(source=>source.status ? [{name:source.name,run_id:source.status.run.id,epoch:source.status.run.epoch,running:source.status.run.state==='running',connected:source.connected&&!source.stale&&!props.lost}] : []),[props.sources,props.lost]);
  const replay:ReplayProps={queue:queue.current,movements:props.movements??[],sources,reduced,units:props.units??[],root,onStats:setStats,selected:props.selected};
  const [reset,setReset]=useState(0),[ready,setReady]=useState(false),[failed,setFailed]=useState(false);
  return <div ref={root} className="facility-stage" role="group" aria-label="Selectable 3D facility" data-models-ready={ready} data-recorded-units={visibleUnits(props.units ?? []).length}>
    <div className="scene-controls"><span>Fixed catalog · Drag to orbit · Scroll to zoom</span><button type="button" onClick={()=>setReset(value=>value+1)}>Reset view</button></div>
    <SceneBoundary onFailure={()=>setFailed(true)}>
      <Canvas orthographic dpr={1} frameloop="demand" camera={{near:.1,far:300,zoom:6}} gl={{antialias:true,alpha:false}} onCreated={()=>setReady(true)}>
        <color attach="background" args={['#151d20']}/><hemisphereLight args={['#f3f1e2','#3b5058',2.3]}/>
        <directionalLight position={[-30,60,30]} intensity={2.5}/><directionalLight position={[40,15,-30]} intensity={.7}/>
        <Camera reset={reset}/><World {...props} replay={replay}/>
      </Canvas>
    </SceneBoundary>
    <div className="scene-replay" aria-label="Visual replay">{reduced?'Reduced motion · recorded positions':`Visual estimate · ${stats.active} robots · ${stats.queued} queued${stats.frozen?' · frozen':''}`}<span>Generated robots, routes and timing · {stats.skipped} movements coalesced{stats.unmapped?` · ${stats.unmapped} unmapped`:''}</span></div>
    {!ready&&!failed&&<p className="scene-loading" role="status">Loading 3D facility…</p>}
    {!props.units?.length&&<p className="scene-empty">No recorded handling units</p>}
  </div>;
}
