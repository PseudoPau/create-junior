import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { hardwareObject } from './hardware-geometry.js?v=1';
import { drilledBoardGeometry, clippedBoardGeometry } from './machining-geometry.js?v=3';

const degrees = value => value * Math.PI / 180;
const copy = value => structuredClone(value);

export class WorkshopViewport {
  constructor(element, callbacks = {}) {
    this.element = element; this.callbacks = callbacks; this.parts = []; this.meshes = []; this.mode = 'select'; this.selectedId = null; this.measurePoints = []; this.measureSnapTypes=[]; this.snapMarker=null; this.hiddenIds = new Set(); this.inspection = null; this.cameraMotion = null; this.hardwareData = []; this.hardwareObjects = []; this.hardwareVisible = true; this.exploded = false; this.partDisplayOffsets = new Map();
    this.joints=[];this.jointGroup=null;this.inspectionView=null;this.highlightIds=new Set();
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color('#eff1eb');
    this.camera = new THREE.PerspectiveCamera(40, 1, 1, 1000000); this.camera.position.set(1100, 850, 1300);
    this.renderer = new THREE.WebGLRenderer({ antialias: true }); this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); this.renderer.outputColorSpace = THREE.SRGBColorSpace; element.append(this.renderer.domElement);
    this.renderer.domElement.setAttribute('role','img');this.renderer.domElement.setAttribute('aria-label','可旋转、缩放、选择和聚焦的家具三维模型');this.renderer.domElement.style.touchAction='none';
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x909b81, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 2); light.position.set(800, 1500, 1100); this.scene.add(light);
    this.grid = new THREE.GridHelper(2400, 24, 0xd0d9c7, 0xe1e6da);this.grid.material.transparent=true;this.grid.material.opacity=.5;this.grid.position.y=-.5; this.scene.add(this.grid);
    this.group = new THREE.Group(); this.scene.add(this.group);
    this.hardwareGroup = new THREE.Group(); this.scene.add(this.hardwareGroup);
    this.hardwareGuides = new THREE.Group(); this.scene.add(this.hardwareGuides);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement); this.controls.target.set(0, 350, 0); this.controls.enableDamping = true; this.controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN }; this.controls.touches={ONE:THREE.TOUCH.ROTATE,TWO:THREE.TOUCH.DOLLY_PAN};this.controls.minDistance = 20; this.controls.maxDistance = 20000;
    this.transform = new TransformControls(this.camera, this.renderer.domElement); this.transform.setSize(.8); this.scene.add(this.transform.getHelper());
    this.transform.addEventListener('dragging-changed', event => { this.draggingTransform = event.value; this.controls.enabled = !event.value; });
    this.transform.addEventListener('mouseUp', () => this.commitTransform());
    this.raycaster = new THREE.Raycaster(); this.pointer = new THREE.Vector2();
    this.renderer.domElement.addEventListener('contextmenu', event => event.preventDefault());
    this.renderer.domElement.addEventListener('pointerdown', () => this.cancelCameraMotion(), { capture:true });
    this.renderer.domElement.addEventListener('wheel', () => this.cancelCameraMotion(), { passive:true, capture:true });
    this.renderer.domElement.addEventListener('pointerdown', event => { this.pointerStart = { x: event.clientX, y: event.clientY, button: event.button, transform: !!this.transform.axis }; });
    this.renderer.domElement.addEventListener('pointermove', event => this.hoverMeasure(event));
    this.renderer.domElement.addEventListener('pointerleave', () => this.clearHoverMeasure());
    this.renderer.domElement.addEventListener('pointerup', event => this.pick(event));
    this.renderer.domElement.addEventListener('dblclick',event=>{if(this.mode!=='select')return;const hit=this.partAt(event);if(hit){this.setSelection(hit.object.userData.partId,true);this.focus(hit.object.userData.partId);}});
    this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(element); this.resize();
    this.dimensionLayer=document.createElement('div');this.dimensionLayer.className='model-dimensions';element.append(this.dimensionLayer);this.dimensionLabels=[];
    this.jointIndexLayer=document.createElement('div');this.jointIndexLayer.className='model-joint-index';element.append(this.jointIndexLayer);
    this.dimensionLines=new THREE.Group();this.scene.add(this.dimensionLines);
    this.refreshTheme();this.themeObserver=new MutationObserver(()=>this.refreshTheme());this.themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['class','style','data-theme']});this.themeMedia=window.matchMedia('(prefers-color-scheme: dark)');this.themeListener=()=>this.refreshTheme();this.themeMedia.addEventListener('change',this.themeListener);
    this.renderer.setAnimationLoop(time => {if(!this.element.isConnected)return; this.updateCameraMotion(time); this.controls.update(); this.updateAssemblyLabels();this.updateDimensionLabels();this.updateJointIndex(); this.renderer.render(this.scene, this.camera); });
  }
  captureView(){return {position:this.camera.position.toArray(),target:this.controls.target.toArray()};}
  refreshTheme(){
    const resolved=(name,fallback)=>{if(!getComputedStyle(this.element).getPropertyValue(name).trim())return fallback;const probe=document.createElement('span');probe.style.color='var('+name+')';probe.style.display='none';this.element.append(probe);const value=getComputedStyle(probe).color;probe.remove();return value;};
    this.palette={background:resolved('--canvas','#eff1eb'),accent:resolved('--accent','#b95d40'),line:resolved('--line','#d0d9c7'),wood:'#c7ad83',edge:'#9c886c'};
    this.scene.background.set(this.palette.background);this.grid.material.vertexColors=false;this.grid.material.color.set(this.palette.line);this.grid.material.needsUpdate=true;this.applyAppearance();
    this.dimensionLines?.traverse(child=>child.material?.color?.set(this.palette.accent));
  }
  restoreView(view){if(view)this.moveCamera(new THREE.Vector3(...view.target),new THREE.Vector3(...view.position));}
  highlightParts(ids){this.clearInspection();this.highlightIds=new Set(ids);this.applyAppearance();}
  setDimensions(items){
    this.dimensionLayer.replaceChildren();this.dimensionLabels=[];this.release(this.dimensionLines);this.dimensionLines.clear();
    for(const item of items){
      const points=(item.points||[item.start,item.end]).filter(Boolean).map(point=>new THREE.Vector3(...point));if(!points.length)continue;
      const start=points[0],end=points[points.length-1];
      for(const [extensionStart,extensionEnd] of item.extensions||[]){
        const a=new THREE.Vector3(...extensionStart),b=new THREE.Vector3(...extensionEnd);
        const direction=b.clone().sub(a);const length=direction.length();
        if(length>0.1){const unit=direction.clone().normalize();const gap=2,overshoot=2;const from=a.clone().addScaledVector(unit,gap);const to=b.clone().addScaledVector(unit,overshoot);const extension=new THREE.Line(new THREE.BufferGeometry().setFromPoints([from,to]),new THREE.LineBasicMaterial({color:this.palette.accent,transparent:true,opacity:.55,depthTest:false}));extension.renderOrder=39;this.dimensionLines.add(extension);}
      }
      const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:this.palette.accent,depthTest:false}));line.renderOrder=40;this.dimensionLines.add(line);
      const direction=end.clone().sub(start);if(direction.length()>1){const unit=direction.clone().normalize();const side=Math.abs(unit.y)>.9?new THREE.Vector3(1,0,0):new THREE.Vector3(0,1,0);const slash=unit.clone().add(side).normalize().multiplyScalar(4);const tickPoints=[start.clone().add(slash),start.clone().sub(slash),end.clone().add(slash),end.clone().sub(slash)];const ticks=new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(tickPoints),new THREE.LineBasicMaterial({color:this.palette.accent,depthTest:false}));ticks.renderOrder=40;this.dimensionLines.add(ticks);}
      let label;
      if(item.value!==undefined){label=document.createElement('label');label.className='model-dimension model-dimension-input';const input=document.createElement('input');input.type='text';input.inputMode='decimal';input.value=String(item.value);input.setAttribute('aria-label',item.label||'尺寸');
        input.addEventListener('input',()=>item.onInput?.(input.value));input.addEventListener('keydown',event=>{event.stopPropagation();if(event.key==='Enter'){event.preventDefault();item.onCommit?.(input.value);}else if(event.key==='Escape'){event.preventDefault();item.onCancel?.();}});
        const unit=document.createElement('span');unit.textContent=item.unit||'mm';label.append(input,unit);
      }else{label=document.createElement('button');label.type='button';label.className='model-dimension';label.textContent=item.label;label.setAttribute('aria-label',(item.onEdit?'修改':'查看')+item.label);if(item.onEdit)label.addEventListener('click',item.onEdit);}
      this.dimensionLayer.append(label);
      this.dimensionLabels.push({label,point:item.labelPoint?new THREE.Vector3(...item.labelPoint):start.clone().add(end).multiplyScalar(.5)});
    }
  }
  updateDimensionLabels(){
    const width=this.element.clientWidth,height=this.element.clientHeight;this.camera.updateMatrixWorld();
    for(const {label,point} of this.dimensionLabels||[]){const p=point.clone().project(this.camera),x=(p.x+1)*width/2,y=(-p.y+1)*height/2;label.hidden=p.z>1||p.z< -1||x<0||x>width||y<0||y>height;label.style.left=Math.min(width-64,Math.max(64,x))+'px';label.style.top=Math.min(height-35,Math.max(35,y))+'px';}
  }
  resize() { const width = this.element.clientWidth, height = this.element.clientHeight; if (!width || !height) return; this.renderer.setSize(width, height); this.updateProjection(); }
  setBottomOcclusion(pixels=0) {
    const inset=Math.max(0,pixels);
    if(Math.abs((this.bottomOcclusion||0)-inset)<1)return;
    const previous=this.bottomOcclusion||0;
    if(!previous&&inset){this.occlusionView={position:this.camera.position.clone(),target:this.controls.target.clone()};}
    this.bottomOcclusion=inset;
    if(!inset&&this.occlusionView){this.camera.position.copy(this.occlusionView.position);this.controls.target.copy(this.occlusionView.target);this.occlusionView=null;this.controls.update();}
    else if(inset&&this.occlusionView){
      const base=this.occlusionView, direction=base.position.clone().sub(base.target),factor=1+Math.min(inset,this.element.clientHeight*.46)/Math.max(this.element.clientHeight,1)*.72;
      this.camera.position.copy(base.target).addScaledVector(direction,factor);
      this.controls.target.copy(base.target);this.controls.target.y-=Math.min(inset,260)*.22;this.controls.update();
    }
    this.updateProjection();
  }
  updateProjection() {
    const width=this.element.clientWidth,height=this.element.clientHeight;
    if(!width||!height)return;
    this.camera.aspect=width/height;
    const shift=Math.min(this.bottomOcclusion||0,height*.18)/2;
    if(shift)this.camera.setViewOffset(width,height,0,shift,width,height);
    else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
  }
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
          const drillLine=new THREE.Line(new THREE.BufferGeometry().setFromPoints([entry,entry.clone().addScaledVector(axis,feature.depth_mm)]),new THREE.LineDashedMaterial({color:0x44806d,dashSize:2,gapSize:1}));drillLine.computeLineDistances();drillLine.userData.feature=feature.id;drillLine.userData.drillAxis=true;mesh.add(drillLine);
        }else{
          for (let i=0;i<48;i++) { const a = 2*Math.PI*i/48; points.push(this.facePoint(part,feature.face,feature.u_mm+radius*Math.cos(a),feature.v_mm+radius*Math.sin(a))); }
          const axis=new THREE.Vector3(...({top:[0,-1,0],bottom:[0,1,0],left:[1,0,0],right:[-1,0,0],front:[0,0,-1],back:[0,0,1]})[feature.face]);
          const entry=this.facePoint(part,feature.face,feature.u_mm,feature.v_mm,0),drillLine=new THREE.Line(new THREE.BufferGeometry().setFromPoints([entry,entry.clone().addScaledVector(axis,feature.depth_mm)]),new THREE.LineDashedMaterial({color:0xb95d40,dashSize:2,gapSize:1}));
          drillLine.computeLineDistances();drillLine.userData.feature=feature.id;drillLine.userData.drillAxis=true;mesh.add(drillLine);
        }
      } else {
        const w = feature.width_mm || 0, l = feature.length_mm || 0;
        for (const [du,dv] of [[0,0],[w,0],[w,l],[0,l]]) points.push(this.facePoint(part,feature.face,feature.u_mm+du,feature.v_mm+dv));
      }
      const marker = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({ color:0x44806d })); marker.userData.feature = feature.id; mesh.add(marker);
    }
  }
  load(parts, { fit = false, hardware, joints } = {}) {
    const wasEmpty = !this.parts.length; this.transform.detach(); this.release(this.group); this.group.clear(); this.meshes = []; this.parts = copy(parts || []);
    this.release(this.hardwareGroup); this.hardwareGroup.clear(); this.hardwareObjects = [];
    this.hardwareData = copy(hardware === undefined ? (this.parts.length ? this.hardwareData : []) : hardware);
    if(joints!==undefined)this.joints=copy(joints||[]);
    const validParts=new Set(this.parts.map(part=>part.id));this.hiddenIds=new Set([...this.hiddenIds].filter(id=>validParts.has(id)));this.highlightIds=new Set([...this.highlightIds].filter(id=>validParts.has(id)));
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
    if(this.jointGroup)this.resolveJointInspection();
    this.updateHardwareLayout(); this.applyAppearance(); this.attachTransform(); this.clearMeasurement(); if ((wasEmpty || fit) && this.parts.length) this.setView('fit');
  }
  setSelection(id, notify = false, event = null) { this.selectedId = this.parts.some(part=>part.id===id)?id:null;this.highlightIds=new Set(); this.applyAppearance(); this.attachTransform(); if (notify) this.callbacks.onSelect?.(this.selectedId, event); }
  attachTransform() { const mesh = this.meshes.find(item => item.userData.partId === this.selectedId && item.visible); if (mesh && ['translate','rotate','scale'].includes(this.mode)) { this.transform.attach(mesh); this.transform.setMode(this.mode); this.transform.setSpace('local'); } else this.transform.detach(); }
  setTool(mode) { if (['measure','translate','rotate','scale','mirror'].includes(mode)) this.clearInspection(); if (mode === 'mirror') { this.mirrorSelected(); return; } this.mode = mode; this.attachTransform(); this.clearMeasurement(); this.renderer.domElement.style.cursor = mode === 'measure' ? 'crosshair' : 'default'; }
  setVisible(id, visible) { visible ? this.hiddenIds.delete(id) : this.hiddenIds.add(id); const mesh = this.meshes.find(item => item.userData.partId === id); if (mesh) mesh.visible = visible; this.updateHardwareLayout(); this.attachTransform(); }
  partAt(event){const rect=this.renderer.domElement.getBoundingClientRect();if(!rect.width||!rect.height)return null;this.pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);this.scene.updateMatrixWorld(true);this.raycaster.setFromCamera(this.pointer,this.camera);return this.raycaster.intersectObjects(this.meshes.filter(mesh=>mesh.visible),false)[0]||null;}
  pick(event) {
    const start = this.pointerStart; if (!start || start.button !== 0 || start.transform || Math.hypot(event.clientX-start.x,event.clientY-start.y)>4) return;
    if (!['select','measure'].includes(this.mode)) return;
    this.partAt(event);
    const partHits = this.raycaster.intersectObjects(this.meshes.filter(mesh => mesh.visible),false), hit = partHits[0];
    // Measurement remains on woodworking surfaces, independent of the hardware layer.
    if (this.mode === 'measure') { if (hit) { const snapped = this.snapPoint(hit); this.addMeasurePoint(snapped.point, snapped.type); } return; }
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
    this.setSelection(hit?.object.userData.partId || null,true,event);
  }
  clearMeasurement() { this.clearHoverMeasure(); this.clearSnapMarker(); this.measurePoints = []; this.measureSnapTypes = []; if (this.measureLine) { this.scene.remove(this.measureLine); this.release(this.measureLine); this.measureLine = null; } this.callbacks.onMeasure?.(null); }
  snapPoint(hit) {
    const point = hit.point.clone(), mesh = hit.object;
    if (!mesh) return { point, type: '面' };
    const box = new THREE.Box3().setFromObject(mesh);
    if (box.isEmpty()) return { point, type: '面' };
    const min = box.min, max = box.max;
    const corners = [new THREE.Vector3(min.x,min.y,min.z),new THREE.Vector3(min.x,min.y,max.z),new THREE.Vector3(min.x,max.y,min.z),new THREE.Vector3(min.x,max.y,max.z),new THREE.Vector3(max.x,min.y,min.z),new THREE.Vector3(max.x,min.y,max.z),new THREE.Vector3(max.x,max.y,min.z),new THREE.Vector3(max.x,max.y,max.z)];
    const mids = [];
    for (let i=0;i<8;i++) for (let j=i+1;j<8;j++) { let diff=0; for (const axis of ['x','y','z']) if (Math.abs(corners[i][axis]-corners[j][axis])>1e-6) diff++; if (diff===1) mids.push(corners[i].clone().add(corners[j]).multiplyScalar(.5)); }
    const cx=(min.x+max.x)/2,cy=(min.y+max.y)/2,cz=(min.z+max.z)/2;const faces = [new THREE.Vector3(cx,min.y,cz),new THREE.Vector3(cx,max.y,cz),new THREE.Vector3(min.x,cy,cz),new THREE.Vector3(max.x,cy,cz),new THREE.Vector3(cx,cy,min.z),new THREE.Vector3(cx,cy,max.z)];
    const centers = [new THREE.Vector3((min.x+max.x)/2,(min.y+max.y)/2,(min.z+max.z)/2)];
    const candidates = [...corners.map(p=>({point:p,type:'端点'})),...mids.map(p=>({point:p,type:'中点'})),...faces.map(p=>({point:p,type:'面心'})),...centers.map(p=>({point:p,type:'中心'}))];
    // Include the closest point on each bounding-box edge for edge inference.
    for (let i=0;i<corners.length;i++) for (let j=i+1;j<corners.length;j++) {
      let diff=0; for (const axis of ['x','y','z']) if (Math.abs(corners[i][axis]-corners[j][axis])>1e-6) diff++;
      if (diff!==1) continue;
      const a=corners[i],b=corners[j],ab=b.clone().sub(a);const t=Math.max(0,Math.min(1,point.clone().sub(a).dot(ab)/ab.lengthSq()));candidates.push({point:a.clone().addScaledVector(ab,t),type:'边'});
    }
    let best=null,bestDistance=Infinity;
    for (const candidate of candidates) { const distance=candidate.point.distanceTo(point); if (distance<bestDistance) { best=candidate; bestDistance=distance; } }
    return bestDistance <= 55 ? { point: best.point, type: best.type } : { point, type: '面' };
  }
  showSnapMarker(point, type) {
    if (!this.snapMarker) {
      this.snapMarker = new THREE.Mesh(new THREE.SphereGeometry(7, 12, 12), new THREE.MeshBasicMaterial({color:this.palette.accent,depthTest:false}));
      this.snapMarker.renderOrder = 101; this.scene.add(this.snapMarker);
    }
    this.snapMarker.position.copy(point); this.snapMarker.visible = true;
  }
  clearSnapMarker() { if (this.snapMarker) this.snapMarker.visible = false; }
  hoverMeasure(event) {
    if (this.mode !== 'measure') return;
    const hit = this.partAt(event);
    if (!hit) { this.clearHoverMeasure(); return; }
    const snapped = this.snapPoint(hit);
    if (!this.measurePoints.length) {
      this.showSnapMarker(snapped.point, snapped.type);
      this.callbacks.onMeasure?.({ preview: true, snap: snapped.type, point: snapped.point.toArray() });
      return;
    }
    const a = this.measurePoints[0], b = snapped.point;
    this.showSnapMarker(b, snapped.type);
    if (!this.hoverMeasureLine) {
      this.hoverMeasureLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: 0xdf643e, transparent: true, opacity: 0.65, depthTest: false }));
      this.hoverMeasureLine.renderOrder = 98; this.scene.add(this.hoverMeasureLine);
    } else {
      this.hoverMeasureLine.geometry.setFromPoints([a, b]); this.hoverMeasureLine.geometry.attributes.position.needsUpdate = true;
    }
    this.callbacks.onMeasure?.({ hover: true, distance_mm: a.distanceTo(b), points: [a.toArray(), b.toArray()], snap: snapped.type });
  }
  clearHoverMeasure() {
    if (this.hoverMeasureLine) { this.scene.remove(this.hoverMeasureLine); this.release(this.hoverMeasureLine); this.hoverMeasureLine = null; }
    this.clearSnapMarker();
    if (this.mode === 'measure' && this.measurePoints.length === 1) this.callbacks.onMeasure?.({ pending: true });
    else if (this.mode === 'measure' && !this.measurePoints.length) this.callbacks.onMeasure?.({ preview: false });
  }
  addMeasurePoint(point, snapType = '面') {
    if (this.measurePoints.length === 2) this.clearMeasurement();
    this.measurePoints.push(point.clone());
    this.measureSnapTypes.push(snapType);
    if (this.measurePoints.length === 1) { this.callbacks.onMeasure?.({ pending:true, snap:snapType }); return; }
    this.clearHoverMeasure();
    const [a,b] = this.measurePoints;
    this.measureLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a,b]),new THREE.LineBasicMaterial({color:0xdf643e,depthTest:false}));
    this.measureLine.renderOrder=99; this.scene.add(this.measureLine);
    this.callbacks.onMeasure?.({ distance_mm:a.distanceTo(b), points:[a.toArray(),b.toArray()], snap:[this.measureSnapTypes[0],this.measureSnapTypes[1]].filter(Boolean).join(' → ') });
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
      const highlighted=involved||this.highlightIds.has(mesh.userData.partId)||this.jointGroup?.partIds.has(mesh.userData.partId)||mesh.userData.partId===this.selectedId;
      mesh.visible=!this.hiddenIds.has(mesh.userData.partId)&&(!this.inspection||involved);
      mesh.material.color.set(this.palette?.wood||'#c7ad83');
      if (mesh.material.transparent !== transparent) { mesh.material.transparent = transparent; mesh.material.needsUpdate = true; }
      mesh.material.opacity = involved ? .14 : 1;
      mesh.material.depthWrite = !transparent;
      for (const child of mesh.children) {
        if (!child.material) continue;
        if (child.userData.feature) {
          const emphasized = !!this.inspection?.featureIds.has(child.userData.feature) && involved;
          child.visible=emphasized||(!this.inspection&&!child.userData.drillAxis);
          child.material.color.set(emphasized ? this.palette.accent : '#8d795d');
          if (!child.material.transparent) { child.material.transparent = true; child.material.needsUpdate = true; }
          child.material.opacity = this.inspection ? (emphasized ? 1 : .16) : .6;
          child.material.depthTest = true;
          child.renderOrder = emphasized ? 20 : 0;
        } else {child.material.color.set(highlighted?this.palette.accent:this.palette.edge);child.material.opacity=highlighted?1:.45;}
      }
    }
    for (const object of this.hardwareObjects) {
      const involved = this.hardwareInInspection(object.userData.hardware), faded = !!this.inspection && !involved;
      object.visible=this.hardwareVisible&&!this.hiddenIds.has(object.userData.hardware.part_id)&&(!this.inspection||involved)&&(!this.jointGroup||this.jointGroup.defined||!this.jointGroup.jointIds.has(object.userData.hardware.joint_id));
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
    if(this.jointGroup){this.setJointGroup(this.jointGroup.source,{mode:value?'exploded':'whole',label:this.jointGroup.label,defined:this.jointGroup.defined});}
    else if (this.inspection) this.inspectConnection([...this.inspection.partIds], [...this.inspection.featureIds], this.inspection.jointId);
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
    if(this.exploded&&!this.inspection&&this.parts.length){
      const center=this.parts.reduce((sum,part)=>sum.add(new THREE.Vector3(...part.position_mm)),new THREE.Vector3()).divideScalar(this.parts.length);
      const extent=Math.max(...this.parts.flatMap(part=>part.size_mm),100);
      this.parts.forEach((part,index)=>{const delta=new THREE.Vector3(...part.position_mm).sub(center);if(delta.length()<extent*.1)delta.set(0,extent*.2*(index%2?1:-1),0);this.partDisplayOffsets.set(part.id,delta.multiplyScalar(.65));});
    }
    for(const mesh of this.meshes){
      const part=this.parts.find(item=>item.id===mesh.userData.partId);
      mesh.position.fromArray(part.position_mm).add(this.partDisplayOffsets.get(part.id)||new THREE.Vector3());
      mesh.updateWorldMatrix(true,true);
      if(!mesh.visible||!this.partDisplayOffsets.has(part.id))continue;
      if(!this.inspection)continue;
      const anchors=(part.features||[]).filter(feature=>this.inspection.featureIds.has(feature.id)).map(feature=>feature.entry_mm?new THREE.Vector3(...feature.entry_mm):this.facePoint(part,feature.face,feature.u_mm,feature.v_mm,0));
      const local=anchors.length?anchors.reduce((sum,point)=>sum.add(point),new THREE.Vector3()).divideScalar(anchors.length):new THREE.Vector3();
      const shown=mesh.localToWorld(local),original=shown.clone().sub(this.partDisplayOffsets.get(part.id));
      this.addAssemblyGuide(original,shown,0xb27851);
      // The adjacent review list names the parts. Do not cover a node close-up
      // with large repeated sprites; only its true separation guides remain.
    }
  }
  updateHardwareLayout() {
    this.release(this.hardwareGuides); this.hardwareGuides.clear();
    this.updatePartDisplayLayout();
    for (const object of this.hardwareObjects) {
      const instance = object.userData.hardware, axis = new THREE.Vector3(...instance.direction).normalize();
      const partOffset=this.partDisplayOffsets.get(instance.part_id)||new THREE.Vector3();
      object.position.fromArray(instance.position_mm).add(partOffset);
      object.visible = this.hardwareVisible && !this.hiddenIds.has(instance.part_id)&&(!this.inspection||this.hardwareInInspection(instance))&&(!this.jointGroup||this.jointGroup.defined||!this.jointGroup.jointIds.has(instance.joint_id));
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
  setJointGroup(group,{mode='whole',label='节点',joints,defined=true,onModeChange}={}) {
    if(!group){this.clearInspection();return;}
    if(joints!==undefined)this.joints=copy(joints||[]);
    if(!['whole','local','exploded'].includes(mode))mode='whole';
    const key=group.id||JSON.stringify(group.joint_ids||[]),previous=this.jointGroup;
    const changed=previous?.key!==key||previous?.mode!==mode;
    if(previous?.key!==key&&this.inspectionView){this.cancelCameraMotion();this.camera.position.fromArray(this.inspectionView.position);this.controls.target.fromArray(this.inspectionView.target);this.controls.update();this.inspectionView=null;}
    if(mode!=='whole'&&!this.inspectionView)this.inspectionView=this.captureView();
    this.jointGroup={key,source:copy(group),mode,label,defined:!!defined,onModeChange,
      jointIds:new Set(group.joint_ids||[]),partIds:new Set(group.part_ids||[]),representativeId:previous?.key===key?previous.representativeId:null};
    this.resolveJointInspection();this.exploded=mode==='exploded';this.mode='select';this.attachTransform();this.clearMeasurement();this.updateHardwareLayout();this.applyAppearance();
    if(mode==='whole'&&this.inspectionView){const view=this.inspectionView;this.inspectionView=null;this.restoreView(view);}
    else if(changed&&this.inspection)this.focusInspection();
    this.rebuildJointIndex();
  }
  resolveJointInspection(){
    const group=this.jointGroup;if(!group)return;
    const joints=this.joints.filter(joint=>group.jointIds.has(joint.id));
    group.partIds=new Set([...group.source.part_ids||[],...joints.flatMap(joint=>joint.part_ids||[])].filter(id=>this.parts.some(part=>part.id===id)));
    if(!group.partIds.size){this.jointGroup=null;this.inspection=null;this.jointIndexLayer?.replaceChildren();return;}
    group.featureIds=new Set(joints.flatMap(joint=>joint.feature_ids||[]));
    if(group.mode==='whole'){this.inspection=null;return;}
    let representative=joints.find(joint=>joint.id===group.representativeId);
    if(!representative){
      const distance=joint=>{const instances=this.hardwareData.filter(h=>h.joint_id===joint.id);return instances.length?Math.min(...instances.map(h=>new THREE.Vector3(...h.position_mm).distanceToSquared(this.camera.position))):Infinity;};
      representative=[...joints].sort((a,b)=>distance(a)-distance(b))[0];
    }
    group.representativeId=representative?.id||null;
    this.inspection={partIds:new Set(representative?.part_ids||[...group.partIds]),featureIds:group.defined?new Set(representative?.feature_ids||[]):new Set(),jointId:representative?.id||null};
  }
  rebuildJointIndex(){
    this.jointIndexLayer.replaceChildren();const group=this.jointGroup;if(!group||group.mode!=='whole')return;
    const button=document.createElement('button');button.type='button';button.className='model-joint-label';button.textContent=group.label+' · '+group.jointIds.size+' 处';button.setAttribute('aria-label','查看'+(group.source.name||'当前节点')+'局部');
    button.addEventListener('click',()=>{if(group.onModeChange)group.onModeChange('local');else if(this.callbacks.onJointModeChange)this.callbacks.onJointModeChange('local');else this.setJointGroup(group.source,{mode:'local',label:group.label,defined:group.defined});});
    this.jointIndexLayer.append(button);this.updateJointIndex();
  }
  updateJointIndex(){
    const group=this.jointGroup,button=this.jointIndexLayer?.firstElementChild;if(!button||!group)return;
    const candidates=[];
    for(const mesh of this.meshes){if(!mesh.visible)continue;const part=this.parts.find(p=>p.id===mesh.userData.partId);mesh.updateWorldMatrix(true,false);
      for(const feature of part.features||[]){if(!group.featureIds.has(feature.id))continue;const local=feature.entry_mm?new THREE.Vector3(...feature.entry_mm):this.facePoint(part,feature.face,feature.u_mm,feature.v_mm,0);candidates.push(mesh.localToWorld(local));}
    }
    const width=this.element.clientWidth,height=this.element.clientHeight;this.camera.updateMatrixWorld();let chosen=null;
    for(const anchor of candidates){const vector=anchor.clone().sub(this.camera.position),distance=vector.length();this.raycaster.set(this.camera.position,vector.normalize());const hit=this.raycaster.intersectObjects(this.meshes.filter(mesh=>mesh.visible),false)[0];if(hit&&hit.distance<distance-1.5)continue;const point=anchor.clone().project(this.camera),x=(point.x+1)*width/2,y=(1-point.y)*height/2;if(point.z< -1||point.z>1||x<35||x>width-35||y<35||y>height-35)continue;chosen={x,y};break;}
    button.hidden=!chosen;if(chosen){button.style.left=chosen.x+'px';button.style.top=chosen.y+'px';}
  }
  inspectConnection(partIds = [], featureIds = [], jointId = null) {
    const ids = new Set(partIds.filter(id => this.parts.some(part => part.id === id)));
    if (!ids.size) { this.clearInspection(); return; }
    this.inspection = { partIds:ids, featureIds:new Set(featureIds), jointId };
    this.mode = 'select'; this.attachTransform(); this.clearMeasurement();
    this.renderer.domElement.style.cursor = 'default';
    this.updateHardwareLayout(); this.applyAppearance();
    this.focusInspection();
  }
  focusInspection(){
    if(!this.inspection)return;
    const ids=this.inspection.partIds;
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
  clearInspection() {const view=this.inspectionView;this.inspectionView=null;this.jointGroup=null; this.inspection = null; this.exploded = false;this.jointIndexLayer?.replaceChildren(); this.cancelCameraMotion(); this.updateHardwareLayout(); this.applyAppearance();if(view)this.restoreView(view); }
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
  frameBounds(box,direction=null){
    if(box.isEmpty())return;
    const center=box.getCenter(new THREE.Vector3()),radius=Math.max(box.getSize(new THREE.Vector3()).length()/2,25),vertical=THREE.MathUtils.degToRad(this.camera.fov/2),halfFov=Math.min(vertical,Math.atan(Math.tan(vertical)*this.camera.aspect));
    const distance=radius/Math.sin(halfFov)*1.08,dir=direction?new THREE.Vector3(...direction).normalize():this.camera.position.clone().sub(this.controls.target).normalize();
    this.moveCamera(center,center.clone().addScaledVector(dir,distance));
  }
  focus(id=this.selectedId) { this.cancelCameraMotion(); const mesh = this.meshes.find(item=>item.userData.partId===id&&item.visible); if (!mesh) return; this.setSelection(id);this.frameBounds(new THREE.Box3().setFromObject(mesh)); }
  setView(view) {
    this.cancelCameraMotion();
    const box=new THREE.Box3();for(const mesh of this.meshes)if(mesh.visible)box.union(new THREE.Box3().setFromObject(mesh));
    if(box.isEmpty())box.set(new THREE.Vector3(-250,0,-250),new THREE.Vector3(250,800,250));
    const direction = ({front:[0,.02,1],right:[1,.02,0],top:[0,1,.001],iso:[1,.7,1]})[view] || null;this.frameBounds(box,direction);
  }
  captureImage({view='iso',exploded=false}={}){
    const original={view:this.captureView(),inspection:this.inspection,jointGroup:this.jointGroup,exploded:this.exploded,dimensionVisible:this.dimensionLines.visible,selected:this.selectedId,highlight:this.highlightIds};
    this.cancelCameraMotion();
    try{this.inspection=null;this.jointGroup=null;this.exploded=!!exploded;this.selectedId=null;this.highlightIds=new Set();this.dimensionLines.visible=false;this.updateHardwareLayout();this.applyAppearance();this.setView(view);
      if(this.cameraMotion){this.camera.position.copy(this.cameraMotion.position);this.controls.target.copy(this.cameraMotion.target);this.cancelCameraMotion();}this.camera.lookAt(this.controls.target);this.camera.updateMatrixWorld();this.renderer.render(this.scene,this.camera);return this.renderer.domElement.toDataURL('image/png');
    }finally{this.inspection=original.inspection;this.jointGroup=original.jointGroup;this.exploded=original.exploded;this.selectedId=original.selected;this.highlightIds=original.highlight;this.dimensionLines.visible=original.dimensionVisible;this.updateHardwareLayout();this.applyAppearance();this.camera.position.fromArray(original.view.position);this.controls.target.fromArray(original.view.target);this.controls.update();this.renderer.render(this.scene,this.camera);}
  }
  dispose() { this.cancelCameraMotion(); this.renderer.setAnimationLoop(null); this.resizeObserver.disconnect();this.themeObserver.disconnect();this.themeMedia.removeEventListener('change',this.themeListener); this.controls.dispose(); this.transform.dispose(); this.clearMeasurement();this.release(this.group); this.release(this.hardwareGroup); this.release(this.hardwareGuides);this.release(this.dimensionLines);this.release(this.grid);this.dimensionLayer.remove();this.jointIndexLayer.remove(); this.renderer.dispose();this.renderer.domElement.remove(); }
}
