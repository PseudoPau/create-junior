import * as THREE from 'three';
import {WorkshopViewport} from './viewport.js?v=v1';

const WIDTH=1000, HEIGHT=700;

function frameCamera(bounds) {
  const center=bounds.getCenter(new THREE.Vector3());
  const extent=Math.max(...bounds.getSize(new THREE.Vector3()).toArray(),100);
  const camera=new THREE.OrthographicCamera(-1,1,1,-1,1,extent*20);
  camera.position.copy(center).addScaledVector(new THREE.Vector3(1,.8,1).normalize(),extent*5);
  camera.lookAt(center);camera.updateMatrixWorld(true);
  const projected=[];
  for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z])projected.push(new THREE.Vector3(x,y,z).applyMatrix4(camera.matrixWorldInverse));
  const horizontal=Math.max(...projected.map(p=>Math.abs(p.x)));
  const vertical=Math.max(...projected.map(p=>Math.abs(p.y)));
  const halfHeight=Math.max(vertical/.79,horizontal/(WIDTH/HEIGHT*.72),50);
  camera.top=halfHeight;camera.bottom=-halfHeight;camera.left=-halfHeight*WIDTH/HEIGHT;camera.right=-camera.left;
  camera.updateProjectionMatrix();return camera;
}

function screenPoint(position,camera) {
  const point=position.clone().project(camera);
  return {x:(point.x+1)*WIDTH/2,y:(1-point.y)*HEIGHT/2};
}

function captionParts(context,meshes,camera,legend) {
  const entries=meshes.map((mesh,index)=>({...screenPoint(mesh.position,camera),code:legend[index].code}));
  for(const side of ['left','right']) {
    const list=entries.filter(item=>(item.x<WIDTH/2?'left':'right')===side).sort((a,b)=>a.y-b.y);
    const spacing=Math.min(48,(HEIGHT-100)/Math.max(list.length,1));
    const top=(HEIGHT-spacing*Math.max(list.length-1,0))/2;
    list.forEach((item,index)=>{
      const x=side==='left'?65:WIDTH-65,y=top+index*spacing;
      context.beginPath();context.setLineDash([5,5]);context.strokeStyle='#91a394';context.lineWidth=1.4;
      context.moveTo(item.x,item.y);context.lineTo(x+(side==='left'?28:-28),y);context.stroke();context.setLineDash([]);
      context.beginPath();context.arc(item.x,item.y,3,0,Math.PI*2);context.fillStyle='#3c6553';context.fill();
      context.fillStyle='#ffffff';context.strokeStyle='#9bafa1';context.lineWidth=1;
      context.beginPath();context.roundRect(x-28,y-14,56,28,7);context.fill();context.stroke();
      context.font='600 16px system-ui, sans-serif';context.fillStyle='#315342';context.textAlign='center';context.textBaseline='middle';context.fillText(item.code,x,y);
    });
  }
}

// Render immutable package geometry in a temporary scene. The editor camera,
// selection and part positions are never changed by creating these pictures.
export async function createPackageVisuals(project,pkg={}) {
  const parts=structuredClone(project.parts||[]);
  if(!parts.length)throw new Error('这版加工包还没有模型。');
  const legend=parts.map((part,index)=>({code:'P'+String(index+1).padStart(2,'0'),id:part.id,name:part.name}));
  const host=document.createElement('div');
  host.setAttribute('aria-hidden','true');
  Object.assign(host.style,{position:'fixed',left:'-12000px',top:'0',width:WIDTH+'px',height:HEIGHT+'px',pointerEvents:'none'});
  document.body.append(host);
  let viewport;
  try {
    viewport=new WorkshopViewport(host);
    viewport.renderer.setAnimationLoop(null);
    viewport.renderer.setPixelRatio(1);viewport.renderer.setSize(WIDTH,HEIGHT);
    viewport.scene.background=new THREE.Color('#f1f3ed');viewport.grid.visible=false;
    viewport.load(parts,{hardware:structuredClone(pkg.hardware_instances||[])});
    viewport.controls.enabled=false;
    const canvas=document.createElement('canvas');canvas.width=WIDTH;canvas.height=HEIGHT;
    const context=canvas.getContext('2d');
    if(!context)throw new Error('浏览器暂时无法生成模型图片。');
    const capture=(labels=false)=>{
      viewport.group.updateMatrixWorld(true);
      const bounds=new THREE.Box3().setFromObject(viewport.group),camera=frameCamera(bounds);
      viewport.renderer.render(viewport.scene,camera);
      context.clearRect(0,0,WIDTH,HEIGHT);context.drawImage(viewport.renderer.domElement,0,0,WIDTH,HEIGHT);
      if(labels)captionParts(context,viewport.meshes,camera,legend);
      return canvas.toDataURL('image/png');
    };
    const assembled=capture();
    const bounds=new THREE.Box3().setFromObject(viewport.group),center=bounds.getCenter(new THREE.Vector3());
    const size=bounds.getSize(new THREE.Vector3()),extent=Math.max(size.x,size.y,size.z,100);
    // A presentation separation, not a claimed disassembly trajectory. Retain
    // every part's shape and orientation while spreading centers from the chair.
    viewport.hardwareGroup.visible=false;
    for(const mesh of viewport.meshes) {
      const offset=mesh.position.clone().sub(center);
      if(offset.length()<extent*.12)offset.y+=extent*.22;
      mesh.position.add(offset.multiplyScalar(1.25));
    }
    const exploded=capture(true);
    return {assembled,exploded,legend};
  } finally {
    if(viewport){
      viewport.dispose();
      viewport.renderer.forceContextLoss();
    }
    host.remove();
  }
}
