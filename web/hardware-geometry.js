import * as THREE from 'three';

const metal = () => new THREE.MeshStandardMaterial({color:0x8c9393,metalness:.72,roughness:.33});
const dark = () => new THREE.MeshStandardMaterial({color:0x343d40,metalness:.15,roughness:.7});
function ringShape(radius, bore, sides=0) {
  const shape=new THREE.Shape();
  if(sides){for(let i=0;i<sides;i++){const a=i*Math.PI*2/sides;const x=radius*Math.cos(a),y=radius*Math.sin(a);i?shape.lineTo(x,y):shape.moveTo(x,y);}shape.closePath();}
  else shape.absarc(0,0,radius,0,Math.PI*2,false);
  if(bore>0){const hole=new THREE.Path();hole.absarc(0,0,bore,0,Math.PI*2,true);shape.holes.push(hole);}
  return shape;
}
function extrusion(shape,length,z,material=metal()) {
  const geometry=new THREE.ExtrudeGeometry(shape,{depth:length,bevelEnabled:false,steps:1,curveSegments:32});
  const mesh=new THREE.Mesh(geometry,material);mesh.position.z=z;return mesh;
}
function cylinder(radius,length,z,material=metal()) {
  const mesh=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,length,36),material);mesh.rotation.x=Math.PI/2;mesh.position.z=z+length/2;return mesh;
}
// Analytical intersection of a cylinder with a transverse cylindrical bore.
// Threads are represented by the nominal hole envelope, not helical teeth.
function barrelGeometry(radius,length,bore) {
  if(!(bore>0&&bore<radius&&bore<length/2))return new THREE.CylinderGeometry(radius,radius,length,36).rotateX(Math.PI/2).translate(0,0,length/2);
  const vertices=[],normals=[];
  const tri=(a,b,c,na,nb,nc)=>{vertices.push(...a,...b,...c);normals.push(...na,...nb,...nc);};
  const quad=(a,b,c,d,na,nb,nc,nd)=>{tri(a,b,c,na,nb,nc);tri(a,c,d,na,nc,nd);};
  const count=96,angles=Array.from({length:count+1},(_,i)=>2*Math.PI*i/count),edge=Math.asin(bore/radius);
  angles.push(edge,Math.PI-edge,Math.PI+edge,2*Math.PI-edge);angles.sort((a,b)=>a-b);
  for(let i=0;i<angles.length-1;i++){
    const a=angles[i],b=angles[i+1],xa=radius*Math.cos(a),ya=radius*Math.sin(a),xb=radius*Math.cos(b),yb=radius*Math.sin(b);
    const ha=Math.sqrt(Math.max(0,bore*bore-ya*ya)),hb=Math.sqrt(Math.max(0,bore*bore-yb*yb));
    const na=[Math.cos(a),Math.sin(a),0],nb=[Math.cos(b),Math.sin(b),0];
    quad([xa,ya,0],[xb,yb,0],[xb,yb,length/2-hb],[xa,ya,length/2-ha],na,nb,nb,na);
    quad([xa,ya,length/2+ha],[xb,yb,length/2+hb],[xb,yb,length],[xa,ya,length],na,nb,nb,na);
    tri([0,0,0],[xb,yb,0],[xa,ya,0],[0,0,-1],[0,0,-1],[0,0,-1]);
    tri([0,0,length],[xa,ya,length],[xb,yb,length],[0,0,1],[0,0,1],[0,0,1]);
  }
  for(let i=0;i<count;i++){
    const a=2*Math.PI*i/count,b=2*Math.PI*(i+1)/count,ya=bore*Math.cos(a),za=length/2+bore*Math.sin(a),yb=bore*Math.cos(b),zb=length/2+bore*Math.sin(b);
    const xa=Math.sqrt(radius*radius-ya*ya),xb=Math.sqrt(radius*radius-yb*yb),na=[0,-Math.cos(a),-Math.sin(a)],nb=[0,-Math.cos(b),-Math.sin(b)];
    quad([-xa,ya,za],[xa,ya,za],[xb,yb,zb],[-xb,yb,zb],na,na,nb,nb);
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geometry.setAttribute('normal',new THREE.Float32BufferAttribute(normals,3));geometry.computeBoundingSphere();return geometry;
}
export function hardwareObject(instance) {
  const g=instance.geometry,group=new THREE.Group(),r=g.diameter_mm/2,length=g.length_mm,bore=(g.bore_diameter_mm||0)/2;
  if(g.kind==='bolt'){
    group.add(cylinder(r,length,0));
    const headR=g.head_diameter_mm/2,headH=g.head_height_mm,socket=(g.socket_across_flats_mm||g.diameter_mm*2/3)/Math.sqrt(3);
    const shape=ringShape(headR,0),hole=new THREE.Path();
    for(let i=5;i>=0;i--){const a=i*Math.PI/3,x=socket*Math.cos(a),y=socket*Math.sin(a);i===5?hole.moveTo(x,y):hole.lineTo(x,y);}hole.closePath();shape.holes.push(hole);
    group.add(extrusion(shape,headH*.68,-headH));
    group.add(cylinder(headR,headH*.32,-headH*.32));
    group.add(extrusion(ringShape(socket,0,6),.08,-headH*.33,dark()));
  }else if(g.kind==='washer')group.add(extrusion(ringShape(r,bore),length,0));
  else if(g.kind==='hex_nut'){
    const corner=(g.across_flats_mm||g.diameter_mm*Math.sqrt(3)/2)/Math.sqrt(3);
    group.add(extrusion(ringShape(corner,bore,6),length,0));
    // The darker ring marks the nylon insert at the free end.
    group.add(extrusion(ringShape(Math.min(corner*.83,bore+1),bore),.2,length-.18,dark()));
  }else if(g.kind==='barrel_nut')group.add(new THREE.Mesh(barrelGeometry(r,length,bore),metal()));
  else return null;
  group.userData.hardware=instance;
  group.traverse(child=>{if(child.material){child.userData.baseColor=child.material.color.clone();child.material.side=THREE.DoubleSide;}});
  const axis=new THREE.Vector3(...instance.direction).normalize();
  if(g.kind==='barrel_nut'&&instance.bore_direction){const x=new THREE.Vector3(...instance.bore_direction);x.addScaledVector(axis,-x.dot(axis)).normalize();const y=new THREE.Vector3().crossVectors(axis,x);group.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,y,axis));}
  else group.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),axis);
  group.position.fromArray(instance.position_mm);return group;
}
