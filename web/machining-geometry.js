import * as THREE from 'three';

const EPS=1e-5;
function insideCircle(center,radius,outline) {
  let inside=false;
  for(let i=0,j=outline.length-1;i<outline.length;j=i++){
    const a=outline[j],b=outline[i];
    if((a[1]>center[1])!==(b[1]>center[1])&&center[0]<(b[0]-a[0])*(center[1]-a[1])/(b[1]-a[1])+a[0])inside=!inside;
    const dx=b[0]-a[0],dy=b[1]-a[1],den=dx*dx+dy*dy;
    if(den<EPS)continue;
    const t=Math.max(0,Math.min(1,((center[0]-a[0])*dx+(center[1]-a[1])*dy)/den));
    if(Math.hypot(center[0]-a[0]-t*dx,center[1]-a[1]-t*dy)<radius-EPS)return false;
  }
  return inside;
}
function merge(geometries) {
  const values={position:[],normal:[],uv:[]};
  for(const geometry of geometries){const plain=geometry.index?geometry.toNonIndexed():geometry;for(const key of Object.keys(values))for(const value of plain.attributes[key].array)values[key].push(value);if(plain!==geometry)plain.dispose();geometry.dispose();}
  const result=new THREE.BufferGeometry();
  for(const [key,array] of Object.entries(values))result.setAttribute(key,new THREE.Float32BufferAttribute(array,key==='uv'?2:3));
  result.computeBoundingBox();result.computeBoundingSphere();return result;
}
function exteriorLayer(shape,depth,first,last) {
  const full=new THREE.ExtrudeGeometry(shape,{depth,bevelEnabled:false,steps:1,curveSegments:32});
  const values={position:[],normal:[],uv:[]};
  for(const group of full.groups)for(let i=group.start;i<group.start+group.count;i+=3){
    const normalZ=full.attributes.normal.getZ(i);
    const keep=group.materialIndex===1||(first&&normalZ<-.5)||(last&&normalZ>.5);
    if(!keep)continue;
    for(let k=i;k<i+3;k++)for(const key of Object.keys(values)){const attr=full.attributes[key];for(let c=0;c<attr.itemSize;c++)values[key].push(attr.array[k*attr.itemSize+c]);}
  }
  const result=new THREE.BufferGeometry();for(const [key,array] of Object.entries(values))result.setAttribute(key,new THREE.Float32BufferAttribute(array,key==='uv'?2:3));full.dispose();return result;
}
// Work in the existing top/bottom drilling frame, then rotate the centred
// result into the part's local coordinates. U/V follow viewport.facePoint and
// engine.FACE_AXES: side faces use Z/Y, front/back faces use X/Y.
function drillingFrame(part, features) {
  const face=features[0].face;
  if(face==='top'||face==='bottom') {
    return {size:part.size_mm,features,outline:part.outline_mm,rotation:null};
  }
  // A side face of an outlined board is not necessarily rectangular.
  if(part.outline_mm?.length)return null;
  const [x,y,z]=part.size_mm;
  let size,uAxis,outward,vAxis,mirrorU;
  switch(face) {
    case 'right':
      size=[z,x,y];uAxis=[0,0,1];outward=[1,0,0];vAxis=[0,1,0];mirrorU=false;
      break;
    case 'left':
      size=[z,x,y];uAxis=[0,0,-1];outward=[-1,0,0];vAxis=[0,1,0];mirrorU=true;
      break;
    case 'front':
      size=[x,z,y];uAxis=[-1,0,0];outward=[0,0,1];vAxis=[0,1,0];mirrorU=true;
      break;
    case 'back':
      size=[x,z,y];uAxis=[1,0,0];outward=[0,0,-1];vAxis=[0,1,0];mirrorU=false;
      break;
    default:return null;
  }
  // All bases have determinant +1. For left/front, reverse both U and its
  // coordinates to preserve the actual hole location without reflecting
  // triangle winding or normals. Canonical -Y is the drilling direction.
  const rotation=new THREE.Matrix4().makeBasis(
    new THREE.Vector3(...uAxis),new THREE.Vector3(...outward),new THREE.Vector3(...vAxis)
  );
  return {
    size,rotation,outline:null,
    features:features.map(feature=>({...feature,face:'top',u_mm:mirrorU?size[0]-feature.u_mm:feature.u_mm}))
  };
}
// Single-face drilling is represented by actual surfaces on all six faces.
// Intersecting cross-axis holes and slots remain feature overlays.
export function drilledBoardGeometry(part) {
  const source=part.features||[];
  if(part.plane_cuts?.length||source.some(f=>f.direction_local!=null||f.entry_mm!=null))return null;
  if(!source.length||!source.every(f=>f.kind==='hole'&&f.face===source[0].face))return null;
  const frame=drillingFrame(part,source);if(!frame)return null;
  const features=frame.features,[w,h,d]=frame.size,face=features[0].face;
  const outline=frame.outline||[[0,0],[w,0],[w,d],[0,d]];
  const holes=[];
  for(const f of features){
    const radius=f.diameter_mm/2,depth=f.depth_mm;
    if(![f.u_mm,f.v_mm,radius,depth].every(Number.isFinite)||radius<=0||depth<=0||depth>h+EPS||!insideCircle([f.u_mm,f.v_mm],radius,outline))return null;
    let hole=holes.find(item=>Math.hypot(item.x-f.u_mm,item.z-f.v_mm)<EPS);
    if(!hole){hole={x:f.u_mm,z:f.v_mm,cuts:[]};holes.push(hole);}
    hole.cuts.push({radius,depth:Math.min(depth,h)});
  }
  for(let i=0;i<holes.length;i++)for(let j=i+1;j<holes.length;j++){
    const a=holes[i],b=holes[j],ra=Math.max(...a.cuts.map(x=>x.radius)),rb=Math.max(...b.cuts.map(x=>x.radius));
    if(Math.hypot(a.x-b.x,a.z-b.z)<=ra+rb+EPS)return null;
  }
  const boundaries=[...new Set([0,h,...holes.flatMap(hole=>hole.cuts.map(cut=>face==='top'?cut.depth:h-cut.depth))])].sort((a,b)=>a-b);
  const layers=[],geometry=[];
  for(let i=0;i<boundaries.length-1;i++){
    const start=boundaries[i],end=boundaries[i+1];if(end-start<EPS)continue;
    const midpoint=(start+end)/2;
    const radii=holes.map(hole=>Math.max(0,...hole.cuts.filter(cut=>face==='top'?midpoint<cut.depth:midpoint>h-cut.depth).map(cut=>cut.radius)));
    const shape=new THREE.Shape();outline.forEach(([x,z],index)=>index?shape.lineTo(x,z):shape.moveTo(x,z));shape.closePath();
    holes.forEach((hole,index)=>{if(radii[index]>0){const path=new THREE.Path();path.absarc(hole.x,hole.z,radii[index],0,Math.PI*2,true);shape.holes.push(path);}});
    const layer=exteriorLayer(shape,end-start,i===0,i===boundaries.length-2);layer.rotateX(Math.PI/2);layer.translate(-w/2,h/2-start,-d/2);geometry.push(layer);
    if(layers.length){const previous=layers[layers.length-1];holes.forEach((hole,index)=>{
      const before=previous.radii[index],after=radii[index];if(Math.abs(before-after)<EPS)return;
      const min=Math.min(before,after),max=Math.max(before,after);
      const step=min>0?new THREE.RingGeometry(min,max,64):new THREE.CircleGeometry(max,64);
      step.rotateX(before>after?-Math.PI/2:Math.PI/2);step.translate(hole.x-w/2,h/2-start,hole.z-d/2);geometry.push(step);
    });}
    layers.push({radii});
  }
  const result=merge(geometry);
  if(frame.rotation) {
    result.applyMatrix4(frame.rotation);
    result.computeBoundingBox();result.computeBoundingSphere();
  }
  return result;
}


// Plane cuts keep n·p <= offset in the centred part coordinate system.
// This closed convex surface is independent of hole overlays and part rotation.
export function clippedBoardGeometry(part) {
  const cuts=part.plane_cuts||[];
  if(!cuts.length)return null;
  if(part.outline_mm?.length)throw new Error('平面裁切暂只支持矩形料框。');
  if(!Array.isArray(part.size_mm)||part.size_mm.length!==3||!part.size_mm.every(v=>Number.isFinite(v)&&v>0))throw new Error('平面裁切需要有效的零件尺寸。');
  const [x,y,z]=part.size_mm.map(v=>v/2),point=(a,b,c)=>new THREE.Vector3(a,b,c);
  let faces=[
    [point(x,-y,-z),point(x,y,-z),point(x,y,z),point(x,-y,z)],
    [point(-x,-y,-z),point(-x,-y,z),point(-x,y,z),point(-x,y,-z)],
    [point(-x,y,-z),point(-x,y,z),point(x,y,z),point(x,y,-z)],
    [point(-x,-y,-z),point(x,-y,-z),point(x,-y,z),point(-x,-y,z)],
    [point(-x,-y,z),point(x,-y,z),point(x,y,z),point(-x,y,z)],
    [point(-x,-y,-z),point(-x,y,-z),point(x,y,-z),point(x,-y,-z)]
  ];
  const unique=points=>points.filter((p,index)=>!points.slice(0,index).some(q=>p.distanceToSquared(q)<EPS*EPS));
  for(const cut of cuts) {
    const values=cut.normal_local;
    if(!Array.isArray(values)||values.length!==3||!values.every(Number.isFinite)||!Number.isFinite(cut.offset_mm))throw new Error('裁切平面的法线或偏移无效。');
    const normal=new THREE.Vector3(...values),length=normal.length();
    if(Math.abs(length-1)>1e-4)throw new Error('裁切平面的法线必须是单位向量。');
    normal.divideScalar(length);
    const offset=cut.offset_mm/length,clipped=[],boundary=[];
    let removed=false;
    for(const face of faces) {
      const result=[];
      for(let index=0;index<face.length;index++) {
        const a=face[index],b=face[(index+1)%face.length],da=normal.dot(a)-offset,db=normal.dot(b)-offset;
        const insideA=da<=EPS,insideB=db<=EPS;
        if(insideA)result.push(a);
        else removed=true;
        if(insideA!==insideB)result.push(a.clone().lerp(b,Math.max(0,Math.min(1,da/(da-db)))));
      }
      const polygon=unique(result);
      if(polygon.length>=3)clipped.push(polygon);
      for(const p of polygon)if(Math.abs(normal.dot(p)-offset)<=EPS)boundary.push(p);
    }
    const cap=unique(boundary);
    if(removed&&cap.length>=3) {
      const center=cap.reduce((sum,p)=>sum.add(p),new THREE.Vector3()).divideScalar(cap.length);
      const reference=Math.abs(normal.x)<.8?point(1,0,0):point(0,1,0);
      const u=normal.clone().cross(reference).normalize(),v=normal.clone().cross(u);
      const angle=p=>{const delta=p.clone().sub(center);return Math.atan2(delta.dot(v),delta.dot(u));};
      cap.sort((a,b)=>angle(a)-angle(b));clipped.push(cap);
    }
    faces=clipped;
  }
  const positions=[],uvs=[];
  for(const face of faces)for(let index=1;index<face.length-1;index++) {
    const triangle=[face[0],face[index],face[index+1]];
    const area=triangle[1].clone().sub(triangle[0]).cross(triangle[2].clone().sub(triangle[0]));
    if(area.lengthSq()<EPS*EPS)continue;
    for(const p of triangle){positions.push(p.x,p.y,p.z);uvs.push((p.x+x)/(2*x),(p.z+z)/(2*z));}
  }
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));
  geometry.computeVertexNormals();geometry.computeBoundingBox();geometry.computeBoundingSphere();
  return geometry;
}
