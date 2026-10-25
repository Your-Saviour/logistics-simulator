import {useEffect,useMemo} from 'react';
import {useFrame,useThree} from '@react-three/fiber';
import {Mesh,Vector2,type InstancedMesh} from 'three';

export const FACILITY_LAYER=1;

/** Preserve the unchanged facility's exact color/depth; render robots each frame. */
export function FacilityRenderCache(){
 const {gl,scene,camera,raycaster,invalidate}=useThree();
 const context=gl.getContext() as WebGL2RenderingContext;
 const cache=useMemo(()=>({framebuffer:null as WebGLFramebuffer|null,color:null as WebGLTexture|null,depth:null as WebGLRenderbuffer|null,width:0,height:0,size:new Vector2(),signature:'',supported:true}),[]);
 function dispose(){
  context.deleteFramebuffer(cache.framebuffer);context.deleteTexture(cache.color);context.deleteRenderbuffer(cache.depth);
  cache.framebuffer=null;cache.color=null;cache.depth=null;cache.width=0;cache.height=0;cache.signature='';
 }
 useEffect(()=>{
  const mask=raycaster.layers.mask;raycaster.layers.enable(FACILITY_LAYER);
  const restored=()=>{cache.framebuffer=null;cache.color=null;cache.depth=null;cache.width=0;cache.height=0;cache.signature='';cache.supported=true;invalidate();};
  gl.domElement.addEventListener('webglcontextrestored',restored);
  return()=>{gl.domElement.removeEventListener('webglcontextrestored',restored);raycaster.layers.mask=mask;dispose();};
 },[cache,raycaster,context,gl,invalidate]);
 function direct(){
  const mask=camera.layers.mask;camera.layers.enable(FACILITY_LAYER);
  try{gl.render(scene,camera);}finally{camera.layers.mask=mask;}
 }
 function blit(restore:boolean){
  const scissor=context.isEnabled(context.SCISSOR_TEST);
  if(scissor)context.disable(context.SCISSOR_TEST);
  try{
   context.bindFramebuffer(context.READ_FRAMEBUFFER,restore?cache.framebuffer:null);
   context.bindFramebuffer(context.DRAW_FRAMEBUFFER,restore?null:cache.framebuffer);
   context.blitFramebuffer(0,0,cache.width,cache.height,0,0,cache.width,cache.height,context.COLOR_BUFFER_BIT|context.DEPTH_BUFFER_BIT|context.STENCIL_BUFFER_BIT,context.NEAREST);
  }finally{
   context.bindFramebuffer(context.FRAMEBUFFER,null);
   if(scissor)context.enable(context.SCISSOR_TEST);
  }
 }
 useFrame(()=>{
  if(context.isContextLost())return;
  if(!cache.supported||!context.getContextAttributes()?.stencil){direct();return;}
  gl.getDrawingBufferSize(cache.size);
  if(cache.size.x<1||cache.size.y<1)return;
  const resized=cache.width!==cache.size.x||cache.height!==cache.size.y;
  if(resized){
   const depthBits=context.getParameter(context.DEPTH_BITS);
   const depthFormat=depthBits===24?context.DEPTH24_STENCIL8:depthBits===32?context.DEPTH32F_STENCIL8:null;
   if(!depthFormat||context.getParameter(context.STENCIL_BITS)!==8){cache.supported=false;direct();return;}
   const texture=context.getParameter(context.TEXTURE_BINDING_2D),renderbuffer=context.getParameter(context.RENDERBUFFER_BINDING);
   const read=context.getParameter(context.READ_FRAMEBUFFER_BINDING),draw=context.getParameter(context.DRAW_FRAMEBUFFER_BINDING);
   try{
    cache.framebuffer??=context.createFramebuffer();cache.color??=context.createTexture();cache.depth??=context.createRenderbuffer();
    context.bindTexture(context.TEXTURE_2D,cache.color);
    context.texParameteri(context.TEXTURE_2D,context.TEXTURE_MIN_FILTER,context.NEAREST);context.texParameteri(context.TEXTURE_2D,context.TEXTURE_MAG_FILTER,context.NEAREST);
    context.texImage2D(context.TEXTURE_2D,0,context.RGBA8,cache.size.x,cache.size.y,0,context.RGBA,context.UNSIGNED_BYTE,null);
    context.bindRenderbuffer(context.RENDERBUFFER,cache.depth);context.renderbufferStorage(context.RENDERBUFFER,depthFormat,cache.size.x,cache.size.y);
    context.bindFramebuffer(context.FRAMEBUFFER,cache.framebuffer);
    context.framebufferTexture2D(context.FRAMEBUFFER,context.COLOR_ATTACHMENT0,context.TEXTURE_2D,cache.color,0);
    context.framebufferRenderbuffer(context.FRAMEBUFFER,context.DEPTH_STENCIL_ATTACHMENT,context.RENDERBUFFER,cache.depth);
    cache.supported=context.checkFramebufferStatus(context.FRAMEBUFFER)===context.FRAMEBUFFER_COMPLETE;
    cache.width=cache.size.x;cache.height=cache.size.y;
   }finally{
    context.bindTexture(context.TEXTURE_2D,texture);context.bindRenderbuffer(context.RENDERBUFFER,renderbuffer);
    context.bindFramebuffer(context.READ_FRAMEBUFFER,read);context.bindFramebuffer(context.DRAW_FRAMEBUFFER,draw);
   }
   if(!cache.supported){dispose();direct();return;}
  }
  scene.updateMatrixWorld();camera.updateMatrixWorld();
  const keys=[...camera.matrixWorld.elements,...camera.projectionMatrix.elements].map(value=>String(Math.round(value*1e8)));
  scene.traverse(node=>{
   if(!(node instanceof Mesh)||!node.layers.isEnabled(FACILITY_LAYER))return;
   const mesh=node as InstancedMesh;
   keys.push(node.uuid,String(node.visible),String(mesh.count),String(mesh.instanceMatrix?.version),String(mesh.instanceColor?.version),...node.matrixWorld.elements.map(String));
  });
  const signature=keys.join('/'),mask=camera.layers.mask,autoClear=gl.autoClear,background=scene.background;
  try{
   if(resized||signature!==cache.signature){
    gl.autoClear=true;camera.layers.set(FACILITY_LAYER);gl.render(scene,camera);blit(false);cache.signature=signature;
   }else blit(true);
   gl.autoClear=false;scene.background=null;camera.layers.set(0);gl.render(scene,camera);
  }finally{camera.layers.mask=mask;scene.background=background;gl.autoClear=autoClear;}
 },1);
 return null;
}
