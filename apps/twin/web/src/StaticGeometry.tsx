import {createContext,useContext,useId,useLayoutEffect,useMemo,useRef,type ReactNode} from 'react';
import {useFrame,useThree} from '@react-three/fiber';
import {Color,InstancedMesh,Object3D} from 'three';
import type {Vec3} from './facility';
type Shape={kind:'box'|'wheel';at:Vec3;size:Vec3;color:string;rotation:Vec3};
type Store={entries:Map<string,Shape>;dirty:boolean;invalidate:()=>void};
const Shapes=createContext<Store|null>(null);
function ShapeInstance({shape}: {shape:Shape}){
 const store=useContext(Shapes),id=useId();
 if(!store)throw new Error('Static geometry needs its batch');
 useLayoutEffect(()=>{store.entries.set(id,shape);store.dirty=true;store.invalidate();return()=>{store.entries.delete(id);store.dirty=true;};},[store,id,shape.kind,...shape.at,...shape.size,shape.color,...shape.rotation]);
 return null;
}
export function StaticBox({at,size,color}:{at:Vec3;size:Vec3;color:string}){
 return <ShapeInstance shape={{kind:'box',at,size,color,rotation:[0,0,0]}}/>;
}
export function StaticWheel({at}:{at:Vec3}){
 return <ShapeInstance shape={{kind:'wheel',at,size:[1,1,1],color:'#18262b',rotation:[0,0,Math.PI/2]}}/>;
}
export function StaticGeometry({children}:{children:ReactNode}){
 const {invalidate}=useThree();
 const store=useMemo<Store>(()=>({entries:new Map(),dirty:true,invalidate}),[invalidate]);
 const boxes=useRef<InstancedMesh>(null),wheels=useRef<InstancedMesh>(null);
 const temporary=useMemo(()=>new Object3D(),[]);
 useFrame(()=>{
  if(!store.dirty||!boxes.current||!wheels.current)return;
  const counts={box:0,wheel:0};
  for(const shape of store.entries.values()){
   const mesh=shape.kind==='box'?boxes.current:wheels.current,index=counts[shape.kind]++;
   if(index>=1024)throw new Error('Static geometry batch capacity exceeded');
   temporary.position.set(...shape.at);temporary.scale.set(...shape.size);temporary.rotation.set(...shape.rotation);temporary.updateMatrix();
   mesh.setMatrixAt(index,temporary.matrix);mesh.setColorAt(index,new Color(shape.color));
  }
  for(const [mesh,count] of [[boxes.current,counts.box],[wheels.current,counts.wheel]] as const){mesh.count=count;mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;}
  store.dirty=false;
 },-3);
 return <Shapes.Provider value={store}>{children}
  <instancedMesh ref={boxes} args={[undefined,undefined,1024]} frustumCulled={false}><boxGeometry/><meshLambertMaterial/></instancedMesh>
  <instancedMesh ref={wheels} args={[undefined,undefined,1024]} frustumCulled={false}><cylinderGeometry args={[.32,.32,.18,12]}/><meshLambertMaterial/></instancedMesh>
 </Shapes.Provider>;
}
