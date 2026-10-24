import {Component, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {Canvas, useFrame, useLoader, useThree} from '@react-three/fiber';
import {Html} from '@react-three/drei/web/Html.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {Box3, Mesh, OrthographicCamera, Vector3} from 'three';
import {vehicleState, type SceneEntity} from './sceneState';
import './facility3d.css';

type Vec3 = [number, number, number];
type Props = {entities: SceneEntity[]; selected: string; choose: (entity: SceneEntity) => void; lost: boolean};
const AMBER = '#ffb800';

function Block({position, size, color = '#64727a', ...props}: {position: Vec3; size: Vec3; color?: string; metalness?: number}) {
  return <mesh position={position} castShadow receiveShadow><boxGeometry args={size}/><meshStandardMaterial color={color} roughness={0.7} metalness={props.metalness ?? 0.12}/></mesh>;
}

// Original CC0 GLB assets are local: no remote model/texture/font dependencies.
function Model({name, position = [0,0,0], scale = 1, rotation = 0}: {name: string; position?: Vec3; scale?: number; rotation?: number}) {
  const {scene} = useLoader(GLTFLoader, `/models/${name}.glb`);
  const copy = useMemo(() => {
    const object = scene.clone(true);
    object.traverse(node => {if (node instanceof Mesh) {node.castShadow = true; node.receiveShadow = true;}});
    const bounds = new Box3().setFromObject(object), center = bounds.getCenter(new Vector3());
    object.position.set(-center.x, -bounds.min.y, -center.z);
    return object;
  }, [scene]);
  return <group position={position} scale={scale} rotation={[0,rotation,0]}><primitive object={copy}/></group>;
}

function Cell() {
  return <group>
    <Block position={[0,0.04,0]} size={[3.9,0.08,3.8]} color="#596365"/>
    <Model name="machine-window" position={[-1,0.08,-0.45]} scale={1.15}/>
    <Model name="machine-fortified" position={[1.05,0.08,-0.5]} scale={1.1}/>
    <Model name="conveyor-long" position={[0,0.08,1.15]} scale={1.65}/>
    <Model name="robot-arm-a" position={[0,0.6,0.15]} scale={1.5}/>
    <Model name="screen-wide" position={[-1.5,0.08,-1.45]} scale={0.55} rotation={Math.PI/3}/>
    {[-1.9,1.9].map(x=><Block key={x} position={[x,0.09,0]} size={[0.05,0.025,3.8]} color={AMBER}/>)}
  </group>;
}

function Rack({entity}: {entity: SceneEntity}) {
  const stock = entity.related.filter(row => typeof row.on_hand === 'number').reduce((sum,row) => sum + (row.on_hand as number),0);
  return <group>
    <Block position={[0,0.025,0]} size={[3.2,0.05,2.1]} color="#465051"/>
    {[-1.35,1.35].flatMap(x=>[-0.77,0.77].map(z=><Block key={`${x}:${z}`} position={[x,1.7,z]} size={[0.1,3.4,0.1]} color="#567b96"/>))}
    {[0.2,1.2,2.2,3.2].map(y=><group key={y}>
      <Block position={[0,y,0]} size={[2.8,0.08,1.6]} color="#909c9d"/>
      {[-0.8,0.8].map(z=><Block key={z} position={[0,y+0.02,z]} size={[2.85,0.14,0.07]} color="#d88a31"/>)}
    </group>)}
    {stock > 0 && [0.25,1.25,2.25].flatMap((y,i)=>[-0.7,0.7].map((x,j)=>
      i*2+j < Math.min(6,stock) ? <Model key={`${x}:${y}`} name="box-large" position={[x,y,0]} scale={0.9}/> : null))}
  </group>;
}

function Dock() {
  return <group>
    <Block position={[0,0.15,0]} size={[3.8,0.3,3]} color="#626d70"/>
    <Block position={[0,1.85,-0.8]} size={[3.8,3.4,0.22]} color="#a0a9a8"/>
    <Block position={[0,1.6,-0.64]} size={[2.7,2.7,0.12]} color="#1c292c"/>
    <Model name="door-wide-open" position={[0,2.35,-0.5]} scale={1.5}/>
    {[-1.5,1.5].map(x=><group key={x}>
      <Block position={[x,0.65,1.1]} size={[0.17,1.05,0.17]} color={AMBER}/>
      <Block position={[x,0.66,1.1]} size={[0.18,0.23,0.18]} color="#1a2022"/>
    </group>)}
    <Block position={[0,0.32,1.25]} size={[2.7,0.12,0.32]} color="#202c30"/>
  </group>;
}

function Pallet({entity}: {entity: SceneEntity}) {
  // One pallet marks an order; it is not a visual unit-to-quantity conversion.
  return <group>
    {[-0.65,0,0.65].map(x=><Block key={x} position={[x,0.1,0]} size={[0.18,0.2,1.7]} color="#9b7952"/>)}
    {[-0.6,-0.2,0.2,0.6].map(z=><Block key={z} position={[0,0.24,z]} size={[1.8,0.12,0.25]} color="#b29169"/>)}
    {entity.row.status !== 'cancelled' && <><Model name="box-large" position={[0,0.3,-0.35]}/><Model name="box-small" position={[0.4,0.3,0.45]}/></>}
  </group>;
}

function Camera({reset}: {reset: number}) {
  const {camera,size,gl,invalidate} = useThree();
  const controls = useMemo(() => new OrbitControls(camera), [camera,gl.domElement]);
  useLayoutEffect(() => {
    camera.position.set(25,29,32); camera.lookAt(0,0,2);
    if (camera instanceof OrthographicCamera) {camera.zoom = Math.max(5,Math.min(size.width/42,size.height/35)); camera.updateProjectionMatrix();}
    controls.target.set(0,0,2);
    controls.minPolarAngle = 0.12; controls.maxPolarAngle = Math.PI/2.15;
    controls.minZoom = 4; controls.maxZoom = 80;
    controls.enableDamping = true; controls.dampingFactor = 0.12;
    controls.update(); invalidate();
  },[camera,size.width,size.height,reset,controls,invalidate]);
  useEffect(() => {
    controls.connect(gl.domElement);
    const redraw = () => invalidate();
    controls.addEventListener('change',redraw);
    return () => {controls.removeEventListener('change',redraw);controls.dispose();};
  },[controls,invalidate,gl.domElement]);
  useFrame(() => {controls.update();});
  return null;
}

function Floor() {
  return <group>
    <Block position={[0,-0.28,2]} size={[29,0.5,29]} color="#394447"/>
    <Block position={[0,-0.012,4]} size={[28.7,0.035,3.2]} color="#242f33"/>
    <gridHelper args={[29,29,'#586567','#434f52']} position={[0,-0.02,2]}/>
    {[-13,-10,-7,-4,-1,2,5,8,11].map(x=><Block key={x} position={[x,0.015,4]} size={[1.35,0.015,0.055]} color="#c6baa0"/>)}
    {[2.4,5.6].map(z=><Block key={z} position={[0,0.015,z]} size={[28.5,0.02,0.07]} color="#a5a99d"/>)}
    <Block position={[0,0.5,-12.3]} size={[29,1,0.18]} color="#77878a"/>
    <Block position={[-14.4,0.5,2]} size={[0.18,1,29]} color="#77878a"/>
    {[-11,-4,3,10].map(x=><group key={x}>
      <Block position={[x,2.2,-12.2]} size={[0.15,4.4,0.15]} color="#899695"/>
      <Block position={[x,4.4,-11.6]} size={[0.25,0.16,1.6]} color="#d6d7c6"/>
    </group>)}
  </group>;
}

function World({entities,selected,choose,lost,onReady}: Props & {onReady: () => void}) {
  const positions = useRef(new Map<string,number>());
  useEffect(onReady, [onReady]);
  const counts: Record<string,number> = {};
  const visible = entities.filter(entity => (counts[entity.source.name] = (counts[entity.source.name] ?? 0)+1) <= 9);
  const offsets: Record<string,number> = {};
  return <>
    <Floor/>
    {visible.map(entity => {
      const index = offsets[entity.kind] ?? 0; offsets[entity.kind] = index+1;
      let x = -10 + index%3*4.3, z = -8 + Math.floor(index/3)*4.1;
      const motion = vehicleState(entity,lost,positions.current);
      if (entity.kind === 'storage rack') {x = 3.8 + index%3*3.8; z = -8+Math.floor(index/3)*4;}
      if (entity.kind === 'loading bay') {x = 9; z = 8;}
      if (entity.kind === 'order') {x = 3.5+index%3*3; z = 10+Math.floor(index/3)*2.5;}
      if (entity.kind === 'vehicle') {x = -10+index%3*4; z = 8+Math.floor(index/3)*3.2;}
      if (motion.estimated) {x = -10 + motion.progress*19; z = 4;}
      const active = selected === entity.key;
      return <group key={entity.key} position={[x,0,z]} onClick={event => {event.stopPropagation(); choose(entity);}}>
        <mesh rotation={[-Math.PI/2,0,0]} position={[0,0.025,0]}><ringGeometry args={[1.9,active ? 2.04 : 1.94,64]}/><meshBasicMaterial color={active ? AMBER : '#6a7774'} transparent opacity={active ? 0.95 : 0.25}/></mesh>
        {entity.kind === 'production cell' ? <Cell/> : entity.kind === 'storage rack' ? <Rack entity={entity}/> : entity.kind === 'loading bay' ? <Dock/> : entity.kind === 'vehicle' ? <Model name="truck" scale={1.25} rotation={motion.estimated ? -Math.PI/2 : Math.PI/2}/> : <Pallet entity={entity}/>}
        <Html center position={[0,entity.kind === 'storage rack' ? 4.1 : 3.3,0]} zIndexRange={[30,0]}>
          <div className={`scene-label ${active ? 'is-selected' : ''}`}>
            <button type="button" aria-label={`Select ${entity.kind} ${entity.label}`} aria-pressed={active} data-position={`${x}:${z}`} onClick={() => choose(entity)}>{entity.label}</button>
            {motion.frozen && <span className="scene-source-state">Last known</span>}
            {motion.estimated && <span>Estimated position{motion.frozen ? ' · frozen' : ''}</span>}
            {motion.awaitingConfirmation && <span>Awaiting arrival confirmation</span>}
          </div>
        </Html>
      </group>;
    })}
  </>;
}

class SceneBoundary extends Component<{children: ReactNode}, {failed: boolean}> {
  state = {failed: false};
  static getDerivedStateFromError() {return {failed: true};}
  render() {return this.state.failed ? <p className="scene-unavailable" role="status">3D graphics are unavailable in this browser. Use the source asset list below to inspect records.</p> : this.props.children;}
}

export default function Facility3D(props: Props) {
  const [reset,setReset] = useState(0), [ready,setReady] = useState(false);
  const onReady = useMemo(() => () => setReady(true), []);
  return <div className="facility-stage" role="group" aria-label="Selectable 3D facility" data-models-ready={ready}>
    <div className="scene-controls"><span>Drag to orbit · Scroll to zoom</span><button type="button" onClick={() => setReset(value => value+1)}>Reset view</button></div>
    <SceneBoundary>
      <Canvas orthographic shadows dpr={[1,1.6]} frameloop="demand" camera={{position:[25,29,32],near:0.1,far:120,zoom:15}} gl={{antialias:true,alpha:false}}>
        <color attach="background" args={['#151d20']}/>
        <hemisphereLight args={['#f3f4e8','#34414b',2.1]}/>
        <directionalLight position={[-9,22,10]} intensity={3.2} castShadow shadow-mapSize={[2048,2048]} shadow-camera-left={-24} shadow-camera-right={24} shadow-camera-top={24} shadow-camera-bottom={-24} shadow-bias={-0.0008}/>
        <directionalLight position={[15,7,-7]} color="#c9def1" intensity={1.3}/>
        <Camera reset={reset}/>
        <Suspense fallback={null}><World {...props} onReady={onReady}/></Suspense>
      </Canvas>
    </SceneBoundary>
    {!ready && <p className="scene-loading" role="status">Loading 3D facility…</p>}
    {!props.entities.length && <p className="scene-empty">No assets in received snapshots</p>}
  </div>;
}
