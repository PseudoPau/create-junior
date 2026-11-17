import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { hardwareObject } from './hardware-geometry.js?v=1';
import { drilledBoardGeometry, clippedBoardGeometry } from './machining-geometry.js?v=3';

const degrees = value => value * Math.PI / 180;
const copy = value => structuredClone(value);

export class WorkshopViewport {
  constructor(element, callbacks = {}) {
    this.element = element; this.callbacks = callbacks; this.parts = []; this.meshes = []; this.mode = 'select'; this.selectedId = null; this.measurePoints = []; this.hiddenIds = new Set(); this.inspection = null; this.cameraMotion = null; this.hardwareData = []; this.hardwareObjects = []; this.hardwareVisible = true; this.exploded = false; this.partDisplayOffsets = new Map();
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color('#eff1eb');
    this.camera = new THREE.PerspectiveCamera(40, 1, 1, 1000000); this.camera.position.set(1100, 850, 1300);
    this.renderer = new THREE.WebGLRenderer({ antialias: true }); this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); this.renderer.outputColorSpace = THREE.SRGBColorSpace; element.append(this.renderer.domElement);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x909b81, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 2); light.position.set(800, 1500, 1100); this.scene.add(light);
    this.grid = new THREE.GridHelper(2400, 24, 0xd0d9c7, 0xe1e6da); this.scene.add(this.grid);
    this.group = new THREE.Group(); this.scene.add(this.group);
    this.hardwareGroup = new THREE.Group(); this.scene.add(this.hardwareGroup);
    this.hardwareGuides = new THREE.Group(); this.scene.add(this.hardwareGuides);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement); this.controls.target.set(0, 350, 0); this.controls.enableDamping = true; this.controls.mouseButtons = { LEFT: null, MIDDLE: THREE.MOUSE.ROTATE, RIGHT: THREE.MOUSE.PAN }; this.controls.minDistance = 20; this.controls.maxDistance = 20000;
    this.transform = new TransformControls(this.camera, this.renderer.domElement); this.transform.setSize(.8); this.scene.add(this.transform.getHelper());
    this.transform.addEventListener('dragging-changed', event => { this.draggingTransform = event.value; this.controls.enabled = !event.value; });
    this.transform.addEventListener('mouseUp', () => this.commitTransform());
    this.raycaster = new THREE.Raycaster(); this.pointer = new THREE.Vector2();
    this.renderer.domElement.addEventListener('contextmenu', event => event.preventDefault());
    this.renderer.domElement.addEventListener('pointerdown', () => this.cancelCameraMotion(), { capture:true });
    this.renderer.domElement.addEventListener('wheel', () => this.cancelCameraMotion(), { passive:true, capture:true });
    this.renderer.domElement.addEventListener('pointerdown', event => { this.pointerStart = { x: event.clientX, y: event.clientY, button: event.button, transform: !!this.transform.axis }; });
    this.renderer.domElement.addEventListener('pointerup', event => this.pick(event));
    this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(element); this.resize();
    this.renderer.setAnimationLoop(time => { this.updateCameraMotion(time); this.controls.update(); this.updateAssemblyLabels(); this.renderer.render(this.scene, this.camera); });
  }
  resize() { const width = this.element.clientWidth, height = this.element.clientHeight; if (!width || !height) return; this.renderer.setSize(width, height); this.camera.aspect = width / height; this.camera.updateProjectionMatrix(); }
  release(object) { object.traverse(child => { if (child.geometry) child.geometry.dispose(); if (child.material) (Array.isArray(child.material) ? child.material : [child.material]).forEach(material => { material.map?.dispose(); material.dispose(); }); }); }
  geometry(part) {
    const clipped = clippedBoardGeometry(part); if (clipped) return clipped;
    const machined = drilledBoardGeometry(part); if (machined) return machined;
    const [w,h,d] = part.size_mm;
    if (!part.outline_mm?.length) return new THREE.BoxGeometry(w,h,d);
    const shape = new THREE.Shape(); part.outline_mm.forEach(([x,z], i) => i ? shape.lineTo(x,z) : shape.moveTo(x,z)); shape.closePath();
    const geometry = new THREE.ExtrudeGeometry(shape, { depth:h, bevelEnabled:false, steps:1 }); geometry.rotateX(Math.PI / 2); geometry.translate(-w / 2,h / 2,-d / 2); return geometry;
  }
  seatSurfaceHeight(partId) {
    const seat=this.parts.find(part=>part.id===partId);if(!seat)return null;
    let floor=Infinity;
    const matrixFor=part=>new THREE.Matrix4().compose(new THREE.Vector3(...part.position_mm),new THREE.Quaternion().setFromEuler(new THREE.Euler(...part.rotation_deg.map(degrees))),new THREE.Vector3(1,1,1));
    for(const mesh of this.meshes){const part=this.parts.find(p=>p.id===mesh.userData.partId);if(!part)continue;const vertices=mesh.geometry.getAttribute('position'),matrix=matrixFor(part);for(let i=0;i<vertices.count;i++)floor=Math.min(floor,new THREE.Vector3().fromBufferAttribute(vertices,i).applyMatrix4(matrix).y);}
    return Number.isFinite(floor)?new THREE.Vector3(0,seat.size_mm[1]/2,0).applyMatrix4(matrixFor(seat)).y-floor:null;
  }
  facePoint(part, face, u, v, offset = .7) {
    const [w,h,d] = part.size_mm;
    if (face === 'top') return new THREE.Vector3(u-w/2,h/2+offset,v-d/2);
    if (face === 'bottom') return new THREE.Vector3(u-w/2,-h/2-offset,v-d/2);
    if (face === 'left') return new THREE.Vector3(-w/2-offset,v-h/2,u-d/2);
    if (face === 'right') return new THREE.Vector3(w/2+offset,v-h/2,u-d/2);
    if (face === 'front') return new THREE.Vector3(u-w/2,v-h/2,d/2+offset);
    return new THREE.Vector3(u-w/2,v-h/2,-d/2-offset);
  }
  addFeatures(mesh, part) {
    for (const feature of part.features || []) {
      const points = [];
      if (feature.kind === 'hole') {
        const radius = feature.diameter_mm / 2; if (!radius) continue;
        if(feature.entry_mm||feature.direction_local){
          const entry=feature.entry_mm?new THREE.Vector3(...feature.entry_mm):this.facePoint(part,feature.face,feature.u_mm,feature.v_mm,0);
          const normals={top:[0,1,0],bottom:[0,-1,0],left:[-1,0,0],right:[1,0,0],front:[0,0,1],back:[0,0,-1]};
          let normal=new THREE.Vector3(...normals[feature.face]);
          for(const cut of part.plane_cuts||[]){const n=new THREE.Vector3(...cut.normal_local);if(Math.abs(n.dot(entry)-cut.offset_mm)<.01)normal=n;}
          const axis=feature.direction_local?new THREE.Vector3(...feature.direction_local).normalize():normal.clone().negate();
          const radial=new THREE.Vector3().crossVectors(axis,Math.abs(axis.x)<.8?new THREE.Vector3(1,0,0):new THREE.Vector3(0,1,0)).normalize(),other=new THREE.Vector3().crossVectors(axis,radial);
          for(let i=0;i<48;i++){const angle=2*Math.PI*i/48,v=radial.clone().multiplyScalar(radius*Math.cos(angle)).addScaledVector(other,radius*Math.sin(angle));if(Math.abs(normal.dot(axis))>.001)v.addScaledVector(axis,-normal.dot(v)/normal.dot(axis));points.push(entry.clone().add(v).addScaledVector(normal,.7));}
          const drillLine=new THREE.Line(new THREE.BufferGeometry().setFromPoints([entry,entry.clone().addScaledVector(axis,feature.depth_mm)]),new THREE.LineDashedMaterial({color:0x44806d,dashSize:2,gapSize:1}));drillLine.computeLineDistances();drillLine.userData.feature=feature.id;mesh.add(drillLine);
        }else for (let i=0;i<48;i++) { const a = 2*Math.PI*i/48; points.push(this.facePoint(part,feature.face,feature.u_mm+radius*Math.cos(a),feature.v_mm+radius*Math.sin(a))); }
      } else {
        const w = feature.width_mm || 0, l = feature.length_mm || 0;
        for (const [du,dv] of [[0,0],[w,0],[w,l],[0,l]]) points.push(this.facePoint(part,feature.face,feature.u_mm+du,feature.v_mm+dv));
      }
      const marker = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({ color:0x44806d })); marker.userData.feature = feature.id; mesh.add(marker);
    }
  }
  load(parts, { fit = false, hardware } = {}) {
    const wasEmpty = !this.parts.length; this.transform.detach(); this.release(this.group); this.group.clear(); this.meshes = []; this.parts = copy(parts || []);
    this.release(this.hardwareGroup); this.hardwareGroup.clear(); this.hardwareObjects = [];
    this.hardwareData = copy(hardware === undefined ? (this.parts.length ? this.hardwareData : []) : hardware);
    for (const instance of this.hardwareData) { if (!this.parts.some(part => part.id === instance.part_id)) continue; const object = hardwareObject(instance); if (object) { this.hardwareGroup.add(object); this.hardwareObjects.push(object); } }
    for (const part of this.parts) {
      const material = new THREE.MeshStandardMaterial({ color: part.id === this.selectedId ? '#dc9d6c' : '#c7ad83', roughness:.85, metalness:0 });
      const mesh = new THREE.Mesh(this.geometry(part),material); mesh.position.fromArray(part.position_mm); mesh.rotation.set(...part.rotation_deg.map(degrees)); mesh.userData.partId = part.id; mesh.visible = !this.hiddenIds.has(part.id);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, 25),new THREE.LineBasicMaterial({color:0x9c886c,transparent:true,opacity:.5})); mesh.add(edges); this.addFeatures(mesh,part); this.group.add(mesh); this.meshes.push(mesh);
    }
    if (!this.parts.some(part => part.id === this.selectedId)) this.selectedId = null;
    if (this.inspection) {
      this.inspection.partIds = new Set([...this.inspection.partIds].filter(id => this.parts.some(part => part.id === id)));
      if (!this.inspection.partIds.size) this.inspection = null;
    }
    this.updateHardwareLayout(); this.applyAppearance(); this.attachTransform(); this.clearMeasurement(); if ((wasEmpty || fit) && this.parts.length) this.setView('fit');
  }
  setSelection(id, notify = false) { this.selectedId = id; this.applyAppearance(); this.attachTransform(); if (notify) this.callbacks.onSelect?.(id); }
  attachTransform() { const mesh = this.meshes.find(item => item.userData.partId === this.selectedId && item.visible); if (mesh && ['translate','rotate','scale'].includes(this.mode)) { this.transform.attach(mesh); this.transform.setMode(this.mode); this.transform.setSpace('local'); } else this.transform.detach(); }
  setTool(mode) { if (['measure','translate','rotate','scale','mirror'].includes(mode)) this.clearInspection(); if (mode === 'mirror') { this.mirrorSelected(); return; } this.mode = mode; this.attachTransform(); this.clearMeasurement(); this.renderer.domElement.style.cursor = mode === 'measure' ? 'crosshair' : 'default'; }
  setVisible(id, visible) { visible ? this.hiddenIds.delete(id) : this.hiddenIds.add(id); const mesh = this.meshes.find(item => item.userData.partId === id); if (mesh) mesh.visible = visible; this.updateHardwareLayout(); this.attachTransform(); }
  pick(event) {
    const start = this.pointerStart; if (!start || start.button !== 0 || start.transform || Math.hypot(event.clientX-start.x,event.clientY-start.y)>4) return;
    if (!['select','measure'].includes(this.mode)) return;
    const rect = this.renderer.domElement.getBoundingClientRect(); this.pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1); this.scene.updateMatrixWorld(true); this.raycaster.setFromCamera(this.pointer,this.camera);
    const partHits = this.raycaster.intersectObjects(this.meshes.filter(mesh => mesh.visible),false), hit = partHits[0];
    // Measurement remains on woodworking surfaces, independent of the hardware layer.
    if (this.mode === 'measure') { if (hit) this.addMeasurePoint(hit.point); return; }
    if (this.callbacks.onSelectHardware || this.callbacks.onInspectJoint) {
      const hardwareHit = this.raycaster.intersectObjects(this.hardwareObjects.filter(object => object.visible && !this.hiddenIds.has(object.userData.hardware.part_id)),true)[0];
      // Only the explicit transparent inspection mode permits picking through wood.
      const opaqueHit = partHits.find(candidate => !this.inspection || !candidate.object.material.transparent || candidate.object.material.opacity >= .99);
      if (hardwareHit && (!opaqueHit || hardwareHit.distance <= opaqueHit.distance + .001)) {
        let owner = hardwareHit.object;
        while (owner && !owner.userData.hardware) owner = owner.parent;
        if (owner?.userData.hardware) {
          this.setSelection(null); this.transform.detach();
          const instance = copy(owner.userData.hardware);
          if (this.callbacks.onSelectHardware) this.callbacks.onSelectHardware(instance);
          else this.callbacks.onInspectJoint(instance.joint_id);
          return;
        }
      }
    }
    this.setSelection(hit?.object.userData.partId || null,true);
  }
  clearMeasurement() { this.measurePoints = []; if (this.measureLine) { this.scene.remove(this.measureLine); this.release(this.measureLine); this.measureLine = null; } this.callbacks.onMeasure?.(null); }
  addMeasurePoint(point) {
    if (this.measurePoints.length === 2) this.clearMeasurement(); this.measurePoints.push(point.clone());
    if (this.measurePoints.length === 1) { this.callbacks.onMeasure?.({ pending:true }); return; }
    const [a,b] = this.measurePoints; this.measureLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a,b]),new THREE.LineBasicMaterial({color:0xdf643e,depthTest:false})); this.measureLine.renderOrder=99; this.scene.add(this.measureLine); this.callbacks.onMeasure?.({ distance_mm:a.distanceTo(b), points:[a.toArray(),b.toArray()] });
  }
  commitTransform() {
    const mesh = this.transform.object; if (!mesh) return;
    const part = copy(this.parts.find(item => item.id === mesh.userData.partId)); if (!part) return;
    const factors = mesh.scale.toArray(); if (factors.some(value => !Number.isFinite(value) || value <= 0)) { this.load(this.parts); this.callbacks.onError?.('缩放必须为正；请使用镜像工具翻转部件。'); return; }
    part.position_mm = mesh.position.toArray().map(value=>Math.round(value*100)/100); part.rotation_deg = [mesh.rotation.x,mesh.rotation.y,mesh.rotation.z].map(value=>Math.round(value*180/Math.PI*100)/100);
    if (factors.some(value=>Math.abs(value-1)>.0001)) {
      const originalSize=[...part.size_mm];
      part.size_mm = part.size_mm.map((value,index)=>Math.round(value*factors[index]*100)/100);
      factors.forEach((_,i)=>{factors[i]=part.size_mm[i]/originalSize[i];});
      if (part.outline_mm) part.outline_mm = part.outline_mm.map(([x,z])=>[x*factors[0],z*factors[2]]);
      // 孔径和槽宽属于加工规格，不随整体缩放默默改变；位置按加工面更新。
      for (const feature of part.features || []) { const axes = ['top','bottom'].includes(feature.face) ? [0,2] : ['left','right'].includes(feature.face) ? [2,1] : [0,1]; feature.u_mm *= factors[axes[0]]; feature.v_mm *= factors[axes[1]]; }
      for(const feature of part.features||[]){if(feature.entry_mm){feature.entry_mm=feature.entry_mm.map((v,i)=>v*factors[i]);const axes=['top','bottom'].includes(feature.face)?[0,2]:['left','right'].includes(feature.face)?[2,1]:[0,1];feature.u_mm=feature.entry_mm[axes[0]]+part.size_mm[axes[0]]/2;feature.v_mm=feature.entry_mm[axes[1]]+part.size_mm[axes[1]]/2;}if(feature.direction_local)feature.direction_local=new THREE.Vector3(...feature.direction_local.map((v,i)=>v*factors[i])).normalize().toArray();}
      for(const cut of part.plane_cuts||[]){const normal=new THREE.Vector3(...cut.normal_local.map((v,i)=>v/factors[i])),length=normal.length();cut.normal_local=normal.divideScalar(length).toArray();cut.offset_mm/=length;}
    }
    this.callbacks.onTransform?.(part);
  }
  mirrorSelected() {
    const original = this.parts.find(part=>part.id===this.selectedId); if (!original) { this.callbacks.onError?.('先选中要镜像的部件。'); return; }
    const part = copy(original), width = part.size_mm[0];
    if (part.outline_mm) part.outline_mm = part.outline_mm.map(([x,z])=>[width-x,z]).reverse();
    for(const cut of part.plane_cuts||[])cut.normal_local[0]*=-1;
    for(const feature of part.features||[]){if(feature.entry_mm)feature.entry_mm[0]*=-1;if(feature.direction_local)feature.direction_local[0]*=-1;}
    for (const feature of part.features || []) { if (feature.face==='left') feature.face='right'; else if(feature.face==='right') feature.face='left'; else feature.u_mm=width-feature.u_mm-(feature.kind==='slot'?(feature.width_mm||0):0); }
    this.callbacks.onTransform?.(part);
  }
  // Inspection is presentation-only: it never changes part transforms or visibility choices.
  applyAppearance() {
    for (const mesh of this.meshes) {
      const involved = this.inspection?.partIds.has(mesh.userData.partId);
      const faded = !!this.inspection && !involved;
      const transparent = !!this.inspection;
      mesh.material.color.set(involved ? '#e8a06d' : faded ? '#bfc7c4' : mesh.userData.partId === this.selectedId ? '#dc9d6c' : '#c7ad83');
      if (mesh.material.transparent !== transparent) { mesh.material.transparent = transparent; mesh.material.needsUpdate = true; }
      mesh.material.opacity = faded ? .05 : involved ? (this.exploded ? .72 : .24) : 1;
      mesh.material.depthWrite = !transparent;
      for (const child of mesh.children) {
        if (!child.material) continue;
        if (child.userData.feature) {
          const emphasized = !!this.inspection?.featureIds.has(child.userData.feature) && involved;
          child.material.color.set(emphasized ? '#db4e22' : '#44806d');
          if (!child.material.transparent) { child.material.transparent = true; child.material.needsUpdate = true; }
          child.material.opacity = this.inspection ? (emphasized ? 1 : .16) : 1;
          child.material.depthTest = !emphasized;
          child.renderOrder = emphasized ? 20 : 0;
        } else child.material.opacity = faded ? .12 : .5;
      }
    }
    for (const object of this.hardwareObjects) {
      const involved = this.hardwareInInspection(object.userData.hardware), faded = !!this.inspection && !involved;
      object.traverse(child => { if (!child.material) return; const material = child.material;
        material.color.copy(child.userData.baseColor); if (involved && material.metalness > .5) material.color.set('#cc8042');
        if (material.transparent !== faded) { material.transparent = faded; material.needsUpdate = true; }
        material.opacity = faded ? .08 : 1; material.depthWrite = !faded;
      });
    }
  }
  hardwareInInspection(instance) {
    if (!this.inspection) return false;
    return this.inspection.jointId ? instance.joint_id === this.inspection.jointId : this.inspection.partIds.has(instance.part_id) && this.inspection.featureIds.has(instance.feature_id);
  }
  setHardwareVisible(value) { this.hardwareVisible = !!value; this.updateHardwareLayout(); }
  setExploded(value) {
    this.exploded = !!value; this.clearMeasurement();
    if (this.inspection) this.inspectConnection([...this.inspection.partIds], [...this.inspection.featureIds], this.inspection.jointId);
    else { this.updateHardwareLayout(); this.applyAppearance(); }
  }
  addAssemblyGuide(from, to, color = 0x7c8b83) {
    if (from.distanceToSquared(to) < .01) return;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([from,to]),new THREE.LineDashedMaterial({color,dashSize:4,gapSize:3,transparent:true,opacity:.8,depthTest:false}));
    line.computeLineDistances(); line.renderOrder=18; this.hardwareGuides.add(line); return line;
  }
  addAssemblyLabel(text, anchor, index) {
    const canvas=document.createElement('canvas'); canvas.width=512; canvas.height=96;
    const context=canvas.getContext('2d'); if(!context)return;
    context.fillStyle='#fffffff2'; context.fillRect(0,0,512,96);
    context.strokeStyle='#d7dfd0'; context.lineWidth=3; context.strokeRect(2,2,508,92);
    context.fillStyle='#345445'; context.font='500 56px sans-serif'; context.textBaseline='middle';
    context.fillText(text,18,48,476);
    const texture=new THREE.CanvasTexture(canvas),label=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,depthTest:false,transparent:true}));
    const right=new THREE.Vector3(1,0,0).applyQuaternion(this.camera.quaternion),up=new THREE.Vector3(0,1,0).applyQuaternion(this.camera.quaternion);
    label.position.copy(anchor).addScaledVector(right,index%2?65:-65).addScaledVector(up,35);
    label.scale.set(128,24,1); label.renderOrder=30;
    const guide=this.addAssemblyGuide(anchor,label.position,0x658874);
    if(guide)guide.userData.labelGuide=true;
    label.userData.assemblyLabel={anchor:anchor.clone(),side:index%2?1:-1,guide};
    this.hardwareGuides.add(label);
  }
  updateAssemblyLabels() {
    const height=this.element.clientHeight; if(!height)return;
    this.camera.updateMatrixWorld();
    const right=new THREE.Vector3(1,0,0).applyQuaternion(this.camera.quaternion),up=new THREE.Vector3(0,1,0).applyQuaternion(this.camera.quaternion);
    for(const label of this.hardwareGuides.children){
      const info=label.userData.assemblyLabel; if(!info)continue;
      const depth=-info.anchor.clone().applyMatrix4(this.camera.matrixWorldInverse).z;
      label.visible=depth>this.camera.near; if(info.guide)info.guide.visible=label.visible;
      if(!label.visible)continue;
      const unitsPerPixel=2*depth*Math.tan(THREE.MathUtils.degToRad(this.camera.fov/2))/height;
      label.scale.set(128*unitsPerPixel,24*unitsPerPixel,1);
      label.position.copy(info.anchor).addScaledVector(right,info.side*72*unitsPerPixel).addScaledVector(up,30*unitsPerPixel);
      if(info.guide){const positions=info.guide.geometry.attributes.position;positions.setXYZ(1,label.position.x,label.position.y,label.position.z);positions.needsUpdate=true;info.guide.geometry.computeBoundingSphere();info.guide.computeLineDistances();}
    }
  }
  updatePartDisplayLayout() {
    this.partDisplayOffsets.clear();
    // Display offsets belong to the viewport only; the source part transforms stay assembled.
    const involved=this.inspection&&this.exploded?this.parts.filter(part=>this.inspection.partIds.has(part.id)):[];
    const bolt=this.hardwareData.find(item=>this.hardwareInInspection(item)&&item.geometry.kind==='bolt');
    let axis=bolt?new THREE.Vector3(...bolt.direction).normalize():new THREE.Vector3(0,1,0);
    if(!bolt&&involved.length>1){axis=new THREE.Vector3(...involved[1].position_mm).sub(new THREE.Vector3(...involved[0].position_mm));if(axis.lengthSq()<.001)axis.set(0,1,0);axis.normalize();}
    const ranked=[...involved].sort((a,b)=>new THREE.Vector3(...a.position_mm).dot(axis)-new THREE.Vector3(...b.position_mm).dot(axis));
    ranked.forEach((part,index)=>this.partDisplayOffsets.set(part.id,axis.clone().multiplyScalar((index-(ranked.length-1)/2)*90)));
    for(const mesh of this.meshes){
      const part=this.parts.find(item=>item.id===mesh.userData.partId);
      mesh.position.fromArray(part.position_mm).add(this.partDisplayOffsets.get(part.id)||new THREE.Vector3());
      mesh.updateWorldMatrix(true,true);
      if(!mesh.visible||!this.partDisplayOffsets.has(part.id))continue;
      const anchors=(part.features||[]).filter(feature=>this.inspection.featureIds.has(feature.id)).map(feature=>feature.entry_mm?new THREE.Vector3(...feature.entry_mm):this.facePoint(part,feature.face,feature.u_mm,feature.v_mm,0));
      const local=anchors.length?anchors.reduce((sum,point)=>sum.add(point),new THREE.Vector3()).divideScalar(anchors.length):new THREE.Vector3();
      const shown=mesh.localToWorld(local),original=shown.clone().sub(this.partDisplayOffsets.get(part.id));
      this.addAssemblyGuide(original,shown,0xb27851);
      this.addAssemblyLabel(part.name,shown,ranked.findIndex(item=>item.id===part.id));
    }
  }
  updateHardwareLayout() {
    this.release(this.hardwareGuides); this.hardwareGuides.clear();
    this.updatePartDisplayLayout();
    for (const object of this.hardwareObjects) {
      const instance = object.userData.hardware, axis = new THREE.Vector3(...instance.direction).normalize();
      const partOffset=this.partDisplayOffsets.get(instance.part_id)||new THREE.Vector3();
      object.position.fromArray(instance.position_mm).add(partOffset);
      object.visible = this.hardwareVisible && !this.hiddenIds.has(instance.part_id);
      if (!object.visible || !this.exploded || (this.inspection && !this.hardwareInInspection(instance))) continue;
      const mounted=object.position.clone(),kind = instance.geometry.kind;
      let offset = kind === 'bolt' ? -(instance.geometry.length_mm + 25) : kind === 'hex_nut' ? 55 : kind === 'barrel_nut' ? -50 : -35;
      if (kind === 'washer') {
        const matching = this.hardwareData.find(other => {
          if (other.joint_id !== instance.joint_id || other.geometry.kind !== 'bolt') return false;
          const otherAxis = new THREE.Vector3(...other.direction).normalize(), delta = new THREE.Vector3(...instance.position_mm).sub(new THREE.Vector3(...other.position_mm));
          return Math.abs(otherAxis.dot(axis)) > .999 && delta.clone().addScaledVector(axis,-delta.dot(axis)).length() < .1;
        });
        if (matching && new THREE.Vector3(...instance.position_mm).sub(new THREE.Vector3(...matching.position_mm)).dot(axis) > matching.geometry.length_mm / 2) offset = 25;
      }
      object.position.addScaledVector(axis, offset);
      this.addAssemblyGuide(mounted,object.position.clone());
    }
  }
  inspectConnection(partIds = [], featureIds = [], jointId = null) {
    const ids = new Set(partIds.filter(id => this.parts.some(part => part.id === id)));
    if (!ids.size) { this.clearInspection(); return; }
    this.inspection = { partIds:ids, featureIds:new Set(featureIds), jointId };
    this.mode = 'select'; this.attachTransform(); this.clearMeasurement();
    this.renderer.domElement.style.cursor = 'default';
    this.updateHardwareLayout(); this.applyAppearance();
    const meshes = this.meshes.filter(mesh => mesh.visible && ids.has(mesh.userData.partId));
    if (!meshes.length) return;
    const bounds = new THREE.Box3(), features = new THREE.Box3();
    for (const mesh of meshes) {
      mesh.updateWorldMatrix(true, true);
      bounds.union(new THREE.Box3().setFromObject(mesh));
      for (const child of mesh.children) if (this.inspection.featureIds.has(child.userData.feature)) features.union(new THREE.Box3().setFromObject(child));
    }
    for (const object of this.hardwareObjects) if (object.visible && this.hardwareInInspection(object.userData.hardware)) { object.updateWorldMatrix(true,true); features.union(new THREE.Box3().setFromObject(object)); }
    if(this.exploded){this.hardwareGuides.updateWorldMatrix(true,true);for(const guide of this.hardwareGuides.children)if(!guide.userData.assemblyLabel&&!guide.userData.labelGuide)features.union(new THREE.Box3().setFromObject(guide));}
    const focusBounds=features.isEmpty()?bounds:features.clone().expandByScalar(20);
    const center = focusBounds.getCenter(new THREE.Vector3());
    // Frame the actual joint; the remaining transparent parts provide context.
    const radius = Math.max(center.distanceTo(focusBounds.min), center.distanceTo(focusBounds.max), 60);
    const vertical = THREE.MathUtils.degToRad(this.camera.fov / 2);
    const halfFov = Math.min(vertical, Math.atan(Math.tan(vertical) * this.camera.aspect));
    const distance = radius / Math.sin(halfFov) * 1.45;
    const direction = this.camera.position.clone().sub(this.controls.target).normalize();
    if (direction.lengthSq() < .1) direction.set(1,.8,1).normalize();
    this.moveCamera(center, center.clone().addScaledVector(direction, distance));
  }
  clearInspection() { this.inspection = null; this.exploded = false; this.cancelCameraMotion(); this.updateHardwareLayout(); this.applyAppearance(); }
  cancelCameraMotion() {
    if (this.cameraMotion) this.controls.enableDamping = this.cameraMotion.damping;
    this.cameraMotion = null;
  }
  moveCamera(target, position) {
    this.cancelCameraMotion();
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      this.controls.target.copy(target); this.camera.position.copy(position); this.controls.update(); return;
    }
    this.cameraMotion = { start:performance.now(), fromTarget:this.controls.target.clone(), fromPosition:this.camera.position.clone(), target, position, damping:this.controls.enableDamping };
    this.controls.enableDamping = false;
  }
  updateCameraMotion(time) {
    const motion = this.cameraMotion; if (!motion) return;
    const fraction = Math.min(Math.max((time - motion.start) / 350, 0), 1);
    const eased = fraction * fraction * (3 - 2 * fraction);
    this.controls.target.lerpVectors(motion.fromTarget, motion.target, eased);
    this.camera.position.lerpVectors(motion.fromPosition, motion.position, eased);
    if (fraction === 1) this.cancelCameraMotion();
  }
  focus(id) { this.cancelCameraMotion(); const mesh = this.meshes.find(item=>item.userData.partId===id); if (!mesh) return; this.setSelection(id); const box = new THREE.Box3().setFromObject(mesh); const center = box.getCenter(new THREE.Vector3()); const delta = this.camera.position.clone().sub(this.controls.target); this.controls.target.copy(center); this.camera.position.copy(center).add(delta); }
  setView(view) {
    this.cancelCameraMotion();
    const box = this.meshes.length ? new THREE.Box3().setFromObject(this.group) : new THREE.Box3(new THREE.Vector3(-250,0,-250),new THREE.Vector3(250,800,250));
    const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()); const extent = Math.max(size.x,size.y,size.z,100); const distance = extent / (2*Math.tan(THREE.MathUtils.degToRad(this.camera.fov/2))) * 1.65;
    const direction = ({front:[0,.02,1],right:[1,.02,0],top:[0,1,.001],iso:[1,.8,1],fit:[1,.8,1]})[view] || [1,.8,1]; this.controls.target.copy(center); this.camera.position.copy(center).add(new THREE.Vector3(...direction).normalize().multiplyScalar(distance)); this.controls.update();
  }
  dispose() { this.cancelCameraMotion(); this.renderer.setAnimationLoop(null); this.resizeObserver.disconnect(); this.controls.dispose(); this.transform.dispose(); this.release(this.group); this.release(this.hardwareGroup); this.release(this.hardwareGuides); this.renderer.dispose(); }
}
