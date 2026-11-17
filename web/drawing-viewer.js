let viewer;
function make(tag, className, text) {const element=document.createElement(tag);if(className)element.className=className;if(text!==undefined)element.textContent=text;return element;}
function action(label, title, run) {const b=make('button','',label);b.type='button';b.title=title;b.setAttribute('aria-label',title);b.addEventListener('click',run);return b;}
function setup() {
  const dialog=make('dialog','sheet-viewer');dialog.id='drawing-viewer';dialog.setAttribute('aria-label','工程图纸浏览器');
  const toolbar=make('div','sheet-toolbar'),name=make('strong','sheet-name'),pager=make('span','sheet-pager'),zoomLabel=action('100%','适应图幅',()=>fit());
  const previous=action('←','上一张图纸',()=>page(-1)),next=action('→','下一张图纸',()=>page(1));
  const locate=action('定位模型','在模型中定位',()=>locateCurrent());
  const browse=action('▤','收起图纸目录',()=>{dialog.classList.toggle('catalog-collapsed');browse.setAttribute('aria-expanded',String(!dialog.classList.contains('catalog-collapsed')));browse.setAttribute('aria-label',dialog.classList.contains('catalog-collapsed')?'展开图纸目录':'收起图纸目录');browse.title=browse.getAttribute('aria-label');fit();});browse.setAttribute('aria-expanded','true');
  toolbar.append(browse,name,locate,previous,pager,next,action('−','缩小图纸',()=>zoomBy(1/1.25)),zoomLabel,action('+','放大图纸',()=>zoomBy(1.25)),action('打印','打印当前图纸',()=>window.print()),action('×','关闭图纸',()=>dialog.close()));
  const body=make('div','sheet-body'),catalog=make('nav','sheet-catalog'),filter=make('select','sheet-filter'),thumbnails=make('div','sheet-thumbnails');catalog.setAttribute('aria-label','图纸目录');filter.setAttribute('aria-label','图纸分类');catalog.append(filter,thumbnails);
  const stage=make('div','sheet-stage'),sheet=make('img','sheet-image');sheet.draggable=false;stage.append(sheet);body.append(catalog,stage);dialog.append(toolbar,body);document.body.append(dialog);
  viewer={dialog,browse,name,pager,zoomLabel,previous,next,stage,sheet,locate,catalog,filter,thumbnails,filtered:[],category:'all',onLocate:null,jointLabel:id=>id,pages:[],index:0,zoom:1,x:0,y:0,width:1200,height:848.571,drag:null};
  filter.addEventListener('change',()=>{viewer.category=filter.value;renderCatalog();if(!viewer.filtered.includes(viewer.index))viewer.index=viewer.filtered[0]??0;show();});
  sheet.addEventListener('load',()=>{viewer.height=viewer.width*sheet.naturalHeight/sheet.naturalWidth;fit();});
  stage.addEventListener('wheel',event=>{event.preventDefault();const rect=stage.getBoundingClientRect();zoomBy(Math.exp(-event.deltaY*.0015),event.clientX-rect.left,event.clientY-rect.top);},{passive:false});
  stage.addEventListener('pointerdown',event=>{if(event.button!==0)return;viewer.drag={id:event.pointerId,x:event.clientX,y:event.clientY,panX:viewer.x,panY:viewer.y};stage.setPointerCapture(event.pointerId);stage.classList.add('dragging');});
  stage.addEventListener('pointermove',event=>{if(!viewer.drag||viewer.drag.id!==event.pointerId)return;viewer.x=viewer.drag.panX+event.clientX-viewer.drag.x;viewer.y=viewer.drag.panY+event.clientY-viewer.drag.y;paint();});
  const endDrag=()=>{viewer.drag=null;stage.classList.remove('dragging');};stage.addEventListener('pointerup',endDrag);stage.addEventListener('pointercancel',endDrag);dialog.addEventListener('close',endDrag);
  stage.addEventListener('dblclick',event=>{const rect=stage.getBoundingClientRect();zoomBy(event.shiftKey?.5:2,event.clientX-rect.left,event.clientY-rect.top);});
  dialog.addEventListener('keydown',event=>{event.stopPropagation();if(['ArrowRight','PageDown'].includes(event.key)){event.preventDefault();page(1);}else if(['ArrowLeft','PageUp'].includes(event.key)){event.preventDefault();page(-1);}else if(event.key==='+'||event.key==='='){event.preventDefault();zoomBy(1.25);}else if(event.key==='-'){event.preventDefault();zoomBy(1/1.25);}else if(event.key==='0'){event.preventDefault();fit();}});
  new ResizeObserver(()=>{if(dialog.open)fit();}).observe(stage);
}
function locateCurrent(){
  const v=viewer,current=v.pages[v.index];if(!v.onLocate)return;
  const ids=[...new Set(current.joint_ids?.length?current.joint_ids:current.joint_id?[current.joint_id]:[])];
  if(ids.length<2){if(!current.part_id&&!ids.length)return;v.dialog.close();v.onLocate({...current,joint_id:ids[0]});return;}
  const picker=make('dialog'),heading=make('div','dialog-head'),title=make('h2','','定位哪一处连接？'),choices=make('div','action-row');
  picker.setAttribute('aria-label','选择图纸中的连接');heading.append(title,action('×','关闭连接选择',()=>picker.close()));picker.append(heading,choices);
  for(const id of ids)choices.append(action(v.jointLabel(id),'定位 '+v.jointLabel(id),()=>{picker.close();v.dialog.close();v.onLocate({...current,joint_id:id});}));
  picker.addEventListener('close',()=>picker.remove(),{once:true});document.body.append(picker);picker.showModal();
}
function paint(){const v=viewer;v.sheet.style.width=v.width+'px';v.sheet.style.transform=`translate(${v.x}px,${v.y}px) scale(${v.zoom})`;v.zoomLabel.textContent=Math.round(v.zoom*100)+'%';}
function fit(){const v=viewer;if(!v?.dialog.open)return;v.zoom=Math.min((v.stage.clientWidth-20)/v.width,(v.stage.clientHeight-20)/v.height);v.x=(v.stage.clientWidth-v.width*v.zoom)/2;v.y=matchMedia('(max-width:600px)').matches?10:(v.stage.clientHeight-v.height*v.zoom)/2;paint();}
function zoomBy(factor,cx,cy){const v=viewer;if(!v?.dialog.open)return;cx??=v.stage.clientWidth/2;cy??=v.stage.clientHeight/2;const next=Math.min(8,Math.max(.1,v.zoom*factor)),ratio=next/v.zoom;v.x=cx-(cx-v.x)*ratio;v.y=cy-(cy-v.y)*ratio;v.zoom=next;paint();}
const categories=[['all','全部图纸'],['assembly_overview','开工总览'],['part','零件'],['machining','孔位'],['joint','连接'],['invalid','数据记录']];
function renderCatalog(){
  const v=viewer;v.thumbnails.replaceChildren();v.filtered=[];
  v.pages.forEach((sheet,index)=>{
    if(v.category!=='all'&&sheet.sheet_type!==v.category)return;
    v.filtered.push(index);
    const thumb=action('',sheet.title||'图纸 '+(index+1),()=>{v.index=index;show();});thumb.className='sheet-catalog-item';thumb.dataset.index=index;
    const img=make('img');img.alt='';img.loading='lazy';img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(sheet.svg);
    const caption=make('span','',sheet.title||sheet.id||'加工图');thumb.append(img,caption);v.thumbnails.append(thumb);
  });
}
function show(){const v=viewer,s=v.pages[v.index];v.locate.hidden=!(v.onLocate&&(s.part_id||s.joint_id||s.joint_ids?.length));v.name.textContent=s.title||s.part_id||s.joint_id||'加工图';const current=v.filtered.indexOf(v.index);v.pager.textContent=(current+1)+' / '+v.filtered.length;v.previous.disabled=current<=0;v.next.disabled=current===v.filtered.length-1;v.sheet.alt=v.name.textContent;v.sheet.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(s.svg);for(const thumb of v.thumbnails.children){const active=Number(thumb.dataset.index)===v.index;thumb.classList.toggle('active',active);thumb.setAttribute('aria-current',active?'page':'false');if(active)thumb.scrollIntoView({block:'nearest'});}}
function page(delta){const v=viewer,index=v.filtered.indexOf(v.index)+delta;if(index<0||index>=v.filtered.length)return;v.index=v.filtered[index];show();}
export function openDrawingViewer(pages,initialIndex=0,options={}){
  const available=pages.filter(page=>page.svg);if(!available.length)return;if(!viewer)setup();
  viewer.onLocate=typeof options.onLocate==='function'?options.onLocate:null;viewer.jointLabel=typeof options.jointLabel==='function'?options.jointLabel:id=>id;viewer.pages=available;viewer.index=Math.max(0,Math.min(initialIndex,available.length-1));
  viewer.category='all';viewer.filter.replaceChildren();for(const [key,label] of categories){const count=key==='all'?available.length:available.filter(sheet=>sheet.sheet_type===key).length;if(!count)continue;const option=make('option','',label+' · '+count);option.value=key;viewer.filter.append(option);}
  viewer.filter.value='all';const collapsed=matchMedia('(max-width:600px)').matches;viewer.dialog.classList.toggle('catalog-collapsed',collapsed);viewer.browse.setAttribute('aria-expanded',String(!collapsed));viewer.browse.setAttribute('aria-label',collapsed?'展开图纸目录':'收起图纸目录');viewer.browse.title=viewer.browse.getAttribute('aria-label');renderCatalog();if(!viewer.dialog.open)viewer.dialog.showModal();show();
}
