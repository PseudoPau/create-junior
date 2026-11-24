import * as THREE from 'three';
import {WorkshopViewport} from './viewport.js?v=v1';
import {parseQuantity} from './quantity-input.js';

// The adopted project and backend review projection are authoritative. The UI
// stores only navigation and unsaved inputs; no click locally grants consent.
const API='/api/workbench', $=id=>document.getElementById(id), clone=value=>structuredClone(value);
const ACTIVE=new Set(['waiting_for_session','running','needs_input']);
const STAGES=['复原','适己','怎么做','加工包'],POSTURES={upright:'正坐',reclined:'靠坐',leaning:'斜靠',cross_legged:'盘腿'};
const state={page:'R1',project:null,projects:[],review:null,pkg:null,comparison:null,proposal:null,run:null,exported:null,packageProject:null,ai:null,aiTest:null,savedProfile:null,profileNotes:'',busy:false,error:'',selected:null,tool:'select',exploded:false,isolated:false,dimensionIndex:0,boardIndex:0,nodeIndex:0,summaryKind:'board',summaryIndex:0,nodeMode:'whole',pending:'',dimensionDirty:false,previewOriginal:false,files:[],referenceUrl:'',idea:'',editText:'',answer:'',profile:null,methodDraft:null,editKind:'board',runReturn:'R4',undo:[],redo:[],exports:[],drawingIndex:0,assemblyIndex:0,settingsReturn:'R1',requestTicket:0};
let viewport=null,viewportModelKey='',pollTimer=null,previewTimer=null,previewTicket=0,loadingProject=0;
const body=$('step-body'),actions=$('step-actions'),overlay=$('viewport-overlay');
function el(tag,attrs={},...children){const e=document.createElement(tag);for(const [key,value]of Object.entries(attrs)){if(value===null||value===undefined||value===false)continue;if(key==='class')e.className=value;else if(key.startsWith('on'))e.addEventListener(key.slice(2).toLowerCase(),value);else if(key==='value')e.value=value;else if(key==='checked'||key==='disabled'||key==='hidden')e[key]=!!value;else e.setAttribute(key,String(value));}for(const child of children.flat(Infinity))if(child!==null&&child!==undefined&&child!==false)e.append(child instanceof Node?child:String(child));if(attrs.value!==undefined)e.value=attrs.value;return e;}
function text(value){return el('p',{},value);}
function button(label,fn,primary=false,opts={}){return el('button',{type:'button',class:primary?'primary':opts.quiet?'quiet':'',disabled:state.busy||opts.disabled,onClick:()=>action(fn),...opts},label);}
function rawButton(label,fn,attrs={}){return el('button',{type:'button',onClick:fn,...attrs},label);}
function field(label,value,onInput,options={}){const input=el(options.multiline?'textarea':'input',{'aria-label':label,value:value??'',inputmode:options.numeric?'decimal':null,...options,onInput:e=>onInput(e.target.value)});return el('label',{class:'field'},label,input);}
function detail(title,...contents){return el('details',{},el('summary',{},title),...contents);}
function notice(title,description){return el('div',{class:'notice'},el('strong',{},title),text(description));}
function dataRow(name,value){return el('div',{class:'data-row'},el('span',{},name),value instanceof Node?value:el('strong',{},value));}
function format(value){return Number.isFinite(Number(value))&&value!==null?String(Math.round(Number(value)*10)/10):'待补充';}
function base(){if(!state.project)throw new Error('先打开一个项目。');return '/projects/'+encodeURIComponent(state.project.id);}
function payload(method,value){return {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(value)};}
function errorMessage(detail){if(typeof detail==='string')return detail;if(Array.isArray(detail))return detail.map(d=>d.msg||d.message||String(d)).join('；');if(detail&&typeof detail==='object')return [detail.message,detail.checks?.map(c=>c.message).join('；')].filter(Boolean).join('\n')||'当前操作尚未完成。';return '服务暂时无法完成操作，请重试。';}
async function api(path,options={}){const response=await fetch(API+path,options);let data;try{data=await response.json();}catch{throw new Error('无法读取服务结果，请确认本地服务仍在运行。');}if(!response.ok){const error=new Error(errorMessage(data.detail||data));error.status=response.status;error.detail=data.detail||data;throw error;}return data;}
async function optional(path){try{return await api(path);}catch(error){if(error.status===404)return null;throw error;}}
function report(error){state.error=error?.message||String(error);$('step-error').textContent=state.error;$('step-error').hidden=!state.error;}
async function action(fn){if(state.busy)return;state.error='';state.busy=true;renderBusy();try{await fn();}catch(error){if(error.status===409&&state.project&&!error.detail?.code){try{await refresh();}catch{}}report(error);}finally{state.busy=false;render();}}
function renderBusy(){for(const b of document.querySelectorAll('#step-body button,#step-actions button,#project-picker,#new-project'))b.disabled=state.busy;$('save-status').textContent=state.busy?'正在保存…':state.project?'已保存本机 · v'+state.project.revision:'本机工作室';}
function stageIndex(){const page=state.page==='settings'?(state.settingsReturn||'R1'):state.page;return ({R:0,F:1,M:2,P:3})[page[0]]??0;}
function remember(){if(!state.project)return;localStorage.setItem('junior-studio-last',state.project.id);localStorage.setItem('junior-studio-'+state.project.id,JSON.stringify({page:state.page,dimensionIndex:state.dimensionIndex,boardIndex:state.boardIndex,nodeIndex:state.nodeIndex,summaryKind:state.summaryKind,summaryIndex:state.summaryIndex,runReturn:state.runReturn}));}
function navigate(page,{replace=false}={}){clearTimeout(previewTimer);if(state.page==='F3'&&page!=='F3')previewTicket++;state.page=page;state.error='';state.nodeMode='whole';if(!['M3','M4','M5','R2','R3','R5','F2','F3','F4','P2'].includes(page))state.selected=null;remember();const params=new URLSearchParams({step:page});if(state.project)params.set('project',state.project.id);history[replace?'replaceState':'pushState']({},'', '#'+params);render();}
function module(){return state.project?.modules?.find(m=>m.kind==='support')||state.project?.modules?.[0];}
function dimensions(){return state.review?.dimensions||[];}
function dim(){return dimensions()[state.dimensionIndex];}
function boardGroups(){return state.review?.board_groups||[];}
function nodeGroups(){return state.review?.node_groups||[];}
function currentGroup(){return state.editKind==='node'?nodeGroups()[state.nodeIndex]:boardGroups()[state.boardIndex];}
function jointFor(group){return state.project?.joints?.find(j=>group?.joint_ids?.includes(j.id));}
function shownProject(){if(state.page.startsWith('P')&&state.packageProject)return state.packageProject;if(state.proposal&&state.proposal.status==='ready'&&!state.previewOriginal&&['R4','R5','F3','M5'].includes(state.page))return {...state.project,...state.proposal.patch};return state.project;}
function shownPackage(){if(state.page.startsWith('P')&&state.exported)return state.exported.package_snapshot;if(state.proposal&&!state.previewOriginal&&['R4','R5','F3','M5'].includes(state.page))return state.proposal.package_preview;return state.pkg;}
async function listProjects(){state.projects=await api('/projects');$('project-picker').replaceChildren(el('option',{value:''},'新的设计'),...state.projects.map(p=>el('option',{value:p.id},p.name)));$('project-picker').value=state.project?.id||'';const modeEditor=$('mode-editor');if(modeEditor)modeEditor.href=state.project?.parts?.length?'/editor?project='+encodeURIComponent(state.project.id):'/editor';}
async function refresh({recover=false}={}){
  const id=state.project?.id;if(!id)return;const project=await api('/projects/'+id);if(state.project?.id!==id)return;
  const [review,pkg,comp,exports]=await Promise.all([api('/projects/'+id+'/review'),api('/projects/'+id+'/package'),project.modules?.length?api('/projects/'+id+'/modules/'+encodeURIComponent(project.modules.find(m=>m.kind==='support')?.id||project.modules[0].id)+'/comparison?canonical=true'):null,api('/projects/'+id+'/exports')]);
  if(state.project?.id!==id)return;if(review.revision!==project.revision||pkg.revision!==project.revision)return refresh({recover});
  state.project=project;state.review=review;state.pkg=pkg;state.comparison=comp;state.exports=exports.exports||[];
  if(recover){const [proposal,runs]=await Promise.all([optional('/projects/'+id+'/proposal'),api('/projects/'+id+'/design-runs')]);if(state.project?.id!==id)return;state.proposal=proposal?.status==='ready'&&proposal.base_revision===project.revision&&proposal.result_kind!=='advice'?proposal:null;state.run=runs.active||runs.runs?.[0]||null;schedulePoll();}
  state.dimensionIndex=Math.min(state.dimensionIndex,Math.max(0,dimensions().length-1));state.boardIndex=Math.min(state.boardIndex,Math.max(0,boardGroups().length-1));state.nodeIndex=Math.min(state.nodeIndex,Math.max(0,nodeGroups().length-1));
}
async function openProject(id,page=null){const ticket=++loadingProject;clearTimeout(pollTimer);state.project={id};state.proposal=null;state.run=null;state.exported=null;state.packageProject=null;state.selected=null;state.exploded=false;state.isolated=false;state.undo=[];state.redo=[];state.profile=null;state.dimensionDirty=false;await refresh({recover:true});if(ticket!==loadingProject)return;let saved={};try{saved=JSON.parse(localStorage.getItem('junior-studio-'+id)||'{}');}catch{}for(const k of ['dimensionIndex','boardIndex','nodeIndex','summaryKind','summaryIndex','runReturn'])if(saved[k]!==undefined)state[k]=saved[k];let next=page||saved.page||(state.project.parts.length?'R4':'R1');if(next.startsWith('P'))next='M9';if(state.run&&ACTIVE.has(state.run.status))next=state.run.requested_result_kind==='advice'?'F2':state.run.intent==='reconstruct'?'R2':'M4';if(!state.project.parts.length&&!state.proposal)next=['R2','R3','R5'].includes(next)?next:'R1';if(next==='F3')setDimensionPending();navigate(next,{replace:true});$('project-picker').value=id;}
async function ensureProject(){if(!state.project){state.project=await api('/projects',payload('POST',{name:'我的椅子'}));await refresh();await listProjects();}}
async function loadDemo(){state.editText='';state.idea='';const result=await api('/demos/cafe-chair',{method:'POST'});state.project=result.project;state.proposal=result.proposal;state.run=null;state.exported=null;state.packageProject=null;await refresh();await listProjects();navigate('R4');}
async function loadPs2026(){state.editText='';state.idea='';const project=await api('/demos/ps2026',{method:'POST'});await openProject(project.id,'R4');}
async function importModel(file){if(!file)return;if(file.size>2*1024*1024)throw new Error('模型文件最多 2 MB，请选择加工包中的 design.json。');const imported=await api('/projects/import',{method:'POST',headers:{'content-type':'application/json'},body:await file.text()});await listProjects();await openProject(imported.id,'R4');}
async function startReference(){if(!state.idea.trim())throw new Error('写下想复原的椅子，或粘贴参考链接。');await ensureProject();state.project=await api(base()+'/references/item',payload('POST',{expected_revision:state.project.revision,kind:'note',name:'制作想法',text:state.idea.trim()}));state.idea='';await refresh();await startRun('reconstruct','根据这条想法复原椅子；保留可见比例和结构。','R4');}
async function startRun(intent,text,returnPage,kind='design'){state.runReturn=returnPage;state.run=await api(base()+'/design-runs',payload('POST',{expected_revision:state.project.revision,intent,text,requested_result_kind:kind,client_request_id:crypto.randomUUID()}));state.proposal=null;state.previewOriginal=false;navigate(kind==='advice'?'F2':intent==='reconstruct'?'R2':'M4');schedulePoll();}
function schedulePoll(){clearTimeout(pollTimer);if(state.run&&ACTIVE.has(state.run.status))pollTimer=setTimeout(pollRun,1200);}
async function pollRun(){const id=state.project?.id,runId=state.run?.id;if(!id||!runId)return;try{const run=await api('/projects/'+id+'/design-runs/'+runId);if(state.project?.id!==id||state.run?.id!==runId)return;const changed=JSON.stringify([run.status,run.stage,run.question])!==JSON.stringify([state.run.status,state.run.stage,state.run.question]);state.run=run;if(run.status==='ready'){
      await refresh();if(state.project?.id!==id||state.run?.id!==runId)return;if(run.result_kind==='advice'){state.dimensionIndex=0;setDimensionPending();navigate('F3');}else{const proposal=await api('/projects/'+id+'/proposal');if(state.project?.id!==id||state.run?.id!==runId)return;state.proposal=proposal;navigate(state.runReturn==='R4'?'R4':'M5');}return;
    }if(changed&&!state.busy)render();
  }catch(error){if(state.project?.id===id){state.error='暂时无法读取 AI 进度；正在重试。';render();}}finally{schedulePoll();}}
async function cancelRun(){if(state.run&&ACTIVE.has(state.run.status))state.run=await api(base()+'/design-runs/'+state.run.id+'/cancel',payload('POST',{expected_revision:state.project.revision}));clearTimeout(pollTimer);navigate(state.run?.requested_result_kind==='advice'?'F1':state.project.parts.length?'M9':'R1');}
async function answerRun(){if(!state.answer.trim())throw new Error('请补充这项信息。');state.run=await api(base()+'/design-runs/'+state.run.id+'/answer',payload('POST',{expected_revision:state.project.revision,answer:state.answer.trim()}));state.answer='';schedulePoll();}
async function retryRun(){const run=state.run;await refresh();await startRun(run?.intent||'reconstruct',run?.text||'根据当前参考复原椅子。',state.runReturn,run?.requested_result_kind||'design');}
async function acceptProposal(){if(!state.proposal)throw new Error('暂无可采用的修改。');const before=state.project.revision,hadParts=state.project.parts.length>0;state.project=await api(base()+'/proposal/accept',payload('POST',{expected_revision:before,proposal_id:state.proposal.id,accept_connections:false}));state.proposal=null;state.previewOriginal=false;if(hadParts){state.undo.push({before,after:state.project.revision});state.redo=[];}await refresh();}
async function dismissProposal(){if(state.proposal)await api(base()+'/proposal/dismiss',payload('POST',{expected_revision:state.project.revision,proposal_id:state.proposal.id}));state.proposal=null;state.previewOriginal=false;await refresh();}
async function beginFit(){if(state.proposal)await acceptProposal();if(!state.project.parts.length)throw new Error('先形成可编辑模型。');if(!state.project.baseline_revision)state.project=await api(base()+'/baseline',payload('POST',{expected_revision:state.project.revision}));if(!state.review?.enabled){await api(base()+'/review/start',payload('POST',{expected_revision:state.project.revision}));await refresh();}state.profile=null;navigate('F1');}
function profileDraft(){if(state.profile)return state.profile;const p=state.project?.profile_snapshot||state.savedProfile;state.profile={height:p?format(p.height_mm/10):'170',sitting:p?format(p.sitting_height_mm/10):'88',hip:p?format(p.hip_width_mm/10):'38',posture:p?.posture||'upright'};return state.profile;}
async function saveProfile(){const p=profileDraft(),mod=module();if(!mod)throw new Error('当前模型还没有坐姿支撑 Module，请先让 AI 补充。');state.project=await api(base()+'/profile',payload('POST',{expected_revision:state.project.revision,module_id:mod.id,height_mm:parseQuantity(p.height,'cm'),sitting_height_mm:parseQuantity(p.sitting,'cm'),hip_width_mm:parseQuantity(p.hip,'cm'),posture:p.posture}));state.savedProfile=state.project.profile_snapshot;await refresh();await startRun('modify','结合已保存的身体尺寸、坐姿和使用场景，对座高、座宽、座深、座面倾角、座背夹角提出有依据的适己建议。尊重原版比例和连接；仅返回建议，不改变模型。'+(state.profileNotes.trim()?' 使用场景和需求：'+state.profileNotes.trim():''),'F3','advice');}
function setDimensionPending(){clearTimeout(previewTimer);previewTicket++;const d=dim(),suggested=state.comparison?.items?.find(i=>i.key===d?.key);state.pending=String(suggested?.suggested_value??d?.current_value??'');state.dimensionDirty=false;state.proposal=null;state.previewOriginal=false;state.agentNeeded=null;}
function openDimension(index){state.dimensionIndex=index;setDimensionPending();navigate('F3');}
function parseDimension(value,item){return parseQuantity(value,item.unit==='°'?'deg':'mm');}
async function previewDimension(allowRedesign=false){const item=dim();if(!item)throw new Error('当前模型缺少可核对的座面尺寸。');const value=parseDimension(state.pending,item);if(Math.abs(value-item.current_value)<.001){state.proposal=null;return null;}const ticket=++previewTicket;try{const proposal=await api(base()+'/modules/'+encodeURIComponent(item.module_id||module().id)+'/edit-preview',payload('POST',{expected_revision:state.project.revision,key:item.key,value,decision:'custom',allow_redesign:allowRedesign}));if(ticket!==previewTicket)return null;state.proposal=proposal;state.previewOriginal=false;state.dimensionDirty=true;state.agentNeeded=null;state.error='';return proposal;}catch(error){if(ticket!==previewTicket)return null;if(error.detail?.code==='preservation_decision'){state.conflict={kind:'dimension',message:error.message};navigate('F4');return null;}if(error.detail?.code==='agent_required'){state.agentNeeded={kind:'dimension',item,value};state.error=error.message;return null;}throw error;}}
async function confirm(category,item,decision='keep'){if(!item?.fingerprint)throw new Error('这一项缺少可核对的定义，请先补充设计。');await api(base()+'/review/confirm',payload('POST',{expected_revision:state.project.revision,category,id:item.id,fingerprint:item.fingerprint,decision}));await refresh();}
async function nextDimension(){clearTimeout(previewTimer);const item=dim();if(!item)throw new Error('缺少尺寸定义。');const key=item.key,index=state.dimensionIndex,value=parseDimension(state.pending,item);if(Math.abs(value-item.current_value)>.001){const ready=state.proposal?.status==='ready'&&state.proposal.base_revision===state.project.revision&&state.proposal.edit?.key===key&&Math.abs(state.proposal.edit.value-value)<.001;if(!ready)await previewDimension();if(state.page==='F4')return;if(state.agentNeeded){await startRun('modify',`将 ${item.label} 调整为 ${value} ${item.unit}，返回板件、加工特征、连接与 Module 的完整关联修改，尊重原版；不要仅修改目标数字。`,'F3');return;}if(!state.proposal)return;await acceptProposal();}const current=dimensions().find(i=>i.key===key);await confirm('dimension',current,Math.abs(value-item.current_value)>.001?'custom':'keep');state.dimensionIndex=index;if(index<dimensions().length-1){state.dimensionIndex++;setDimensionPending();navigate('F3');}else navigate('F5');}
async function keepDimension(){const item=dim();if(state.proposal)await dismissProposal();state.pending=String(item.current_value);state.agentNeeded=null;await nextDimension();}
async function keepAllDimensions(){for(const item of [...dimensions()]){const current=dimensions().find(d=>d.id===item.id);if(!current.confirmed)await confirm('dimension',current);}navigate('F5');}
async function beginMethods(){if(!dimensions().length||dimensions().some(d=>!d.confirmed)){navigate('F5');return;}if(!state.project.scale?.confirmed){const height=dimensions().find(d=>d.key==='seat_height_mm')?.current_value;await patchProject({scale:{kind:'target',confirmed:true,length_mm:height||null,note:'用户逐项核对五项尺寸，并选择作为本次制作的目标尺度。'}});}navigate('M1');}
function startBoard(index=0){state.editKind='board';state.boardIndex=index;state.selected=boardGroups()[index]?.part_ids?.[0]||null;navigate('M2');}
function startNode(index=0){state.editKind='node';state.nodeIndex=index;state.selected=null;navigate('M8');}
async function nextMethod(kind){const groups=kind==='board'?boardGroups():nodeGroups(),index=kind==='board'?state.boardIndex:state.nodeIndex;await confirm(kind,groups[index]);if(index<groups.length-1){kind==='board'?startBoard(index+1):startNode(index+1);}else if(kind==='board'&&nodeGroups().length)startNode(0);else navigate('M9');}
function previousMethod(kind){const index=kind==='board'?state.boardIndex:state.nodeIndex;if(index>0){kind==='board'?startBoard(index-1):startNode(index-1);}else if(kind==='node'&&boardGroups().length)startBoard(boardGroups().length-1);else navigate('M1');}
function editMethod(kind){state.editKind=kind;const g=currentGroup();state.methodDraft=kind==='board'?{length_mm:g.dimensions.length_mm,width_mm:g.dimensions.width_mm,thickness_mm:g.dimensions.thickness_mm,material_id:g.material_id}:{kind:jointFor(g)?.kind||'screw',text:''};state.editText='';navigate('M3');}
async function previewMethod(allowRedesign=false){const g=currentGroup(),draft=state.methodDraft;if(state.editKind==='node'){await startRun('modify',`修改节点组 ${g.name}，对应连接 ID：${g.joint_ids.join(', ')}。目标做法：${draft.kind}。要求：${draft.text||'根据当前板件与制作条件补全合理的节点规格、孔槽及五金。'}。对称节点一并修改；返回完整关联几何、五金与装配说明。`,'M8');return;}const requested={material_id:draft.material_id,...Object.fromEntries(['length_mm','width_mm','thickness_mm'].map(k=>[k,parseQuantity(draft[k])]))};try{state.proposal=await api(base()+'/review/boards/'+encodeURIComponent(g.id)+'/edit-preview',payload('POST',{expected_revision:state.project.revision,fingerprint:g.fingerprint,...requested,allow_redesign:allowRedesign}));state.previewOriginal=false;navigate('M5');}catch(error){if(error.detail?.code==='preservation_decision'){state.conflict={kind:'board',message:error.message};navigate('F4');return;}if(error.detail?.code==='agent_required'){await startRun('modify',`修改板件组 ${g.name}，部件 ID：${g.part_ids.join(', ')}。要求长 ${requested.length_mm} mm、宽 ${requested.width_mm} mm、厚 ${requested.thickness_mm} mm、材料 ${requested.material_id}。按该组尺寸轴 ${JSON.stringify(g.dimensions.axes)} 解释。关联更新节点、孔位、五金和适己尺寸；对称件一起修改。${allowRedesign?'已选择作为改款，原版保留。':''}`,'M2');return;}throw error;}}
async function adoptMethod(){const returnPage=state.methodDraft?(state.editKind==='node'?'M8':'M2'):state.runReturn;await acceptProposal();state.methodDraft=null;if(returnPage==='F1'){state.profile=null;navigate('F1');return;}if(returnPage==='F3'){setDimensionPending();navigate('F3');return;}if(dimensions().some(d=>!d.confirmed)){navigate('F5');return;}navigate(['M1','M2','M8','M9'].includes(returnPage)?returnPage:'M9');}
async function createPackage(){if(state.proposal){navigate(state.runReturn==='R4'?'R4':'M5');return;}if(!state.review?.complete){navigate('M9');return;}const project=clone(state.project),revision=project.revision;const request={expected_revision:revision};if(viewport?.captureImage){try{request.visuals={assembled:viewport.captureImage({view:'iso',exploded:false}),exploded:viewport.captureImage({view:'iso',exploded:true})};}catch{}}
  const exported=await api(base()+'/exports',payload('POST',request));state.packageProject=project;state.exported=exported;state.drawingIndex=0;state.assemblyIndex=0;navigate('P1');}
async function download(url,name){const response=await fetch(url);if(!response.ok){let data;try{data=await response.json();}catch{}throw new Error(errorMessage(data?.detail||'下载失败，请重试。'));}const blob=await response.blob();saveBlob(blob,name);}
function saveBlob(blob,name){const url=URL.createObjectURL(blob),a=el('a',{href:url,download:name});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);}
function downloadText(value,name,type='text/plain;charset=utf-8'){saveBlob(new Blob([value],{type}),name);}
async function undoRedo(redo=false){const from=redo?state.redo:state.undo,entry=from[from.length-1];if(!entry)return;state.project=await api(base()+'/restore/'+(redo?entry.after:entry.before),payload('POST',{expected_revision:state.project.revision}));from.pop();(redo?state.undo:state.redo).push(entry);state.proposal=null;await refresh();navigate('F5');}

function footer(back,label,fn){if(back)actions.append(button('上一步',typeof back==='function'?back:()=>navigate(back),false,{quiet:true}));if(label)actions.append(button(label,fn,true));}
function heading(title,kicker=STAGES[stageIndex()]){body.append(el('div',{class:'eyebrow'},kicker),el('h1',{id:'step-title'},title));}
function references(){const grid=el('div',{class:'reference-grid'});for(const ref of state.project?.references||[]){const card=el('div',{class:'reference-card'+(ref.kind==='note'?' reference-note':'')});const local=API+base()+'/references/'+encodeURIComponent(ref.id);if(ref.kind==='image')card.append(el('img',{src:local,alt:ref.name,loading:'lazy'}));else if(ref.kind==='document')card.append(el('div',{class:'reference-file-icon'},'PDF'));if(ref.kind==='link')card.append(el('a',{href:ref.url,target:'_blank',rel:'noopener noreferrer'},ref.name||new URL(ref.url).hostname));else card.append(el('span',{},ref.name));if(ref.kind==='note')card.append(text(ref.text));grid.append(card);}return grid;}
function components(){return detail('模型组成 · '+(shownProject()?.parts?.length||0)+' 件',el('div',{class:'components-list'},...(shownProject()?.parts||[]).map(part=>rawButton(part.name,()=>{state.selected=part.id;renderViewport();},{'aria-pressed':state.selected===part.id}))));}
function checksDetail(checks=state.pkg?.checks||[]){return detail('检查结果与依据',el('div',{class:'check-detail'},...checks.map(c=>el('p',{class:c.severity==='blocker'?'blocker':''},c.message))));}
function renderEntry(){heading('把喜欢的椅子，做成你的。');body.append(field('你的想法',state.idea,v=>state.idea=v,{multiline:true,placeholder:'写下想复原的椅子、使用场景和想改的地方；可以直接贴链接。',maxlength:4000}));body.append(el('div',{class:'sample-entry'},el('h3',{},'先体验两把椅子'),el('small',{},'CAFE CHAIR 现成样例；PS 2026 为参考重建。'),el('div',{class:'row'},button('打开 CAFE CHAIR',loadDemo),button('打开 PS 2026',loadPs2026))));if(!state.project&&state.projects.length)body.append(detail('继续已有项目',el('div',{class:'project-list'},...state.projects.slice(0,8).map(p=>button(p.name,()=>openProject(p.id))))));const modelFile=el('input',{type:'file',accept:'.json,application/json',hidden:true,onChange:e=>action(()=>importModel(e.target.files[0]))});body.append(modelFile,button('打开已有模型文件',()=>modelFile.click(),false,{quiet:true}));footer(null,'开始复原',startReference);}
function renderWaiting(){const run=state.run;if(!run){heading('任务尚未开始');body.append(text('你的设计仍在，重新提交后继续。'));footer(state.project?.parts?.length?'M9':'R1','重新提交',retryRun);return;}
  const advice=run.requested_result_kind==='advice',failed=['failed','interrupted','stale','cancelled','dismissed'].includes(run.status);heading(run.status==='needs_input'?'还需要这一项信息':failed?'这次处理没有完成':advice?'正在为你考虑尺寸':'正在处理这把椅子');
  if(run.status==='needs_input'){body.append(text(run.question||run.stage),field('补充说明',state.answer,v=>state.answer=v,{multiline:true,placeholder:'补充这一项即可继续'}));footer(null,'提交并继续',answerRun);body.append(button('取消这次处理',cancelRun,false,{quiet:true}));return;}
  body.append(el('strong',{class:'waiting-title'},run.stage||'正在读取参考'));if(!failed)body.append(el('div',{class:'waiting-line','aria-hidden':'true'}));
  if(run.execution_mode==='session'&&!failed)body.append(text('当前为会话协作通道。网页已经保存任务，需由协作会话领取；设置为在线 AI 后可在网页内自动完成。'),button('查看 AI 设置',()=>openSettings()));
  if(failed){body.append(text('已采用的设计和参考仍保留，可以重试。'));if(!state.ai?.ready)body.append(button('查看 AI 配置',()=>openSettings()));footer(advice?'F1':state.project.parts.length?'M9':'R1','重试',retryRun);}else footer(null,'取消处理',cancelRun);
  if(advice)body.append(button('先核对现有尺寸',async()=>{if(ACTIVE.has(run.status))await cancelRun();state.dimensionIndex=0;setDimensionPending();state.pending=String(dim()?.current_value??'');navigate('F3');},false,{quiet:true}));
}
function renderRestore(){heading(state.proposal?'这是你想复原的椅子吗？':'这是你的原版设计');body.append(field('你的想法',state.editText,v=>state.editText=v,{multiline:true,placeholder:'想改哪里？直接写尺寸、结构、材料或参考。',maxlength:4000}));if(state.editText.trim())body.append(button('按这个想法修改',()=>startRun('modify',state.editText,'R4'),false,{quiet:true}));footer('R1','就用这版，继续',beginFit);}
function renderRestoreEdit(){heading('哪里还不像？');body.append(text('在模型上选中相关部件，再描述要调整的地方。'),field('修改想法',state.editText,v=>state.editText=v,{multiline:true,placeholder:'例如：靠背要更窄，保留现在的倾角'}));footer('R4','让 AI 调整',async()=>{if(!state.editText.trim())throw new Error('写下需要调整的地方。');if(state.proposal)await dismissProposal();await startRun('modify',state.editText+(state.selected?'。选中部件：'+state.selected:''),'R4');});}
function postureIcon(kind){
  const body={upright:'<circle cx="31" cy="14" r="4"/><path d="M31 18v15l16 4v15l8 1"/><path d="M31 24l9 7"/><path d="M12 49h46M13 49V36"/>',
    reclined:'<circle cx="21" cy="20" r="4"/><path d="M23 24l11 12 16 1v14l8 1"/><path d="M27 30l7 7"/><path d="M10 50h48M12 50V37l10-4"/>',
    leaning:'<circle cx="29" cy="14" r="4"/><path d="M29 18l-2 16 17 4v14l8 1"/><path d="M27 25l-9 9"/><path d="M11 49h47M12 49V36"/>',
    cross_legged:'<circle cx="29" cy="14" r="4"/><path d="M29 18v15l14 4-8 8 14 2"/><path d="M29 25l-9 7"/><path d="M11 50h47M13 50V38"/>'}[kind]||'';
  const chair='<path d="M10 50h47M13 50V35h12" opacity=".28"/>';
  return '<svg viewBox="0 0 64 64" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'+chair+body+'</svg>';
}
function bodyField(label,value,onInput){
  return el('label',{class:'figure-field'},el('span',{},label),el('div',{},el('input',{type:'text',inputMode:'decimal',value:value,'aria-label':label,onInput:e=>onInput(e.target.value)}),el('small',{},'cm')));
}
function renderProfile(){heading('用你的身体，定义尺度。','MODULE · 模度');if(!module()){body.append(notice('还缺坐姿支撑定义','AI 需要先识别座面、靠背和关联部件，才有可核对的五项尺寸。'));footer('R4','让 AI 补充',()=>startRun('modify','给当前椅子补充 support Module，正确关联座面、靠背和支撑，提供五项适己尺寸的测量依据，不擅自改动原始几何。','F1'));return;}
  const p=profileDraft();
  body.append(el('div',{class:'body-profile-grid'},el('div',{class:'body-figure'},el('img',{src:'/static/modulor.svg',alt:'模度人：站姿身高、坐姿坐高、臀宽'})),el('div',{class:'figure-fields'},bodyField('身高',p.height,v=>p.height=v),bodyField('坐高',p.sitting,v=>p.sitting=v),bodyField('臀宽',p.hip,v=>p.hip=v))));
  footer('R4','下一步：坐姿与场景',()=>navigate('F6'));
}
function renderProfilePosture(){
  heading('你习惯怎样坐？','MODULE · 姿态');
  const p=profileDraft();
  const postures=el('div',{class:'postures'},...Object.entries(POSTURES).map(([key,label])=>{
    const icon=document.createElement('span');icon.className='posture-icon';icon.innerHTML=postureIcon(key);
    return el('label',{class:'posture'},el('input',{type:'radio',name:'posture',value:key,checked:p.posture===key,onChange:()=>p.posture=key}),icon,el('span',{},label));
  }));
  const scenario=el('div',{class:'scenario-box'},el('label',{class:'field'},'使用场景和需求 · 告诉 AI',el('textarea',{value:state.profileNotes,placeholder:'比如：我 170 cm，坐久了腰酸；十岁的侄子也会坐；放在阳台，偶尔晒太阳。',onInput:e=>state.profileNotes=e.target.value})));
  body.append(postures,scenario);
  footer('F1','保存，查看建议',saveProfile);
  body.append(button('保持原尺寸，查看尺寸总览',()=>{state.dimensionIndex=0;setDimensionPending();navigate('F5');},false,{quiet:true}));
}
function renderDimension(){
  const item=dim();heading(item?.label||'尺寸','MODULE · 逐项尺寸');
  if(!item){body.append(text('当前模型没有可以核对的座面尺寸。'));footer('F1','请 AI 补充',()=>startRun('modify','补充座面、靠背及 support Module，使座高、座宽、座深、座面倾角和座背夹角可测量。','F1'));return;}
  if(!state.pending)state.pending=String(item.current_value??'');
  const dimensionInput=el('input',{id:'dimension-input-left',type:'text',inputMode:'decimal',value:state.pending,spellcheck:false,autocomplete:'off','aria-label':item.label});
  dimensionInput.addEventListener('input',()=>dimensionInputChanged(dimensionInput.value));
  dimensionInput.addEventListener('keydown',event=>{event.stopPropagation();if(event.key==='Enter'){event.preventDefault();action(nextDimension);}else if(event.key==='Escape'){event.preventDefault();state.pending=String(item.current_value??'');render();}});
  body.append(
    el('div',{class:'step-count'},String(state.dimensionIndex+1).padStart(2,'0'),el('small',{},'/ '+String(dimensions().length).padStart(2,'0'))),
    el('div',{class:'dimension-editor'},
      el('label',{class:'dimension-input-wrap'},dimensionInput,el('span',{},item.unit)),
      el('div',{class:'dimension-original'},'原值 ',format(item.current_value)+' '+item.unit))
  );
  if(item.current_value===null){body.append(button('让 AI 补充测量定义',()=>startRun('modify','补充 '+item.label+' 的可测量几何和关联 Module 定义。','F3')));footer('F1',null);return;}
  footer(()=>state.dimensionIndex>0?openDimension(state.dimensionIndex-1):navigate('F1'),state.dimensionIndex===dimensions().length-1?'查看尺寸总览':'下一个',nextDimension);
}

function renderConflict(){heading('这会改变原来的设计');body.append(notice('保留原版，还是作为改款？',state.conflict?.message||'这项变化尚未有确认的保型范围。原版会保留以供比较。'));footer(state.conflict?.kind==='board'?'M3':'F3','作为改款预览',async()=>{if(state.conflict?.kind==='board')await previewMethod(true);else{navigate('F3');await previewDimension(true);}});body.append(button('保持原样',async()=>{const kind=state.conflict?.kind;state.conflict=null;if(kind==='board'){state.methodDraft=null;navigate('M2');}else{state.pending=String(dim()?.current_value??'');state.proposal=null;navigate('F3');}},false,{quiet:true}));}
function selectDimension(index){
  state.dimensionIndex=Math.max(0,Math.min(index,dimensions().length-1));
  setDimensionPending();
  render();
}
function renderSizeSummary(){
  heading('尺寸确认','MODULE · 尺寸确定');
  const items=dimensions();
  if(!items.length){body.append(text('当前模型没有可确认的尺寸。'));footer('F1','返回',()=>navigate('F1'));return;}
  state.dimensionIndex=Math.max(0,Math.min(state.dimensionIndex,items.length-1));
  if(!state.pending)state.pending=String(items[state.dimensionIndex].current_value??'');
  const complete=items.every(item=>item.confirmed);
  body.append(el('div',{class:'size-list'},...items.map((item,index)=>el('button',{type:'button',class:'size-row'+(index===state.dimensionIndex?' on':''),onclick:()=>selectDimension(index)},el('span',{},item.label),el('strong',{},format(item.current_value)+' '+item.unit),el('small',{},item.confirmed?'已确认':'待核对')))));
  body.append(button('修改选中项',()=>openDimension(state.dimensionIndex),false,{quiet:true}));
  footer('F1',complete?'确定尺寸，进入做法':'核对下一项',()=>complete?beginMethods():openDimension(Math.max(0,items.findIndex(item=>!item.confirmed))));
}

function renderMethods(){heading('先看整体，再看怎么做。');body.append(text('按板件、连接节点依次核对。完全相同或对称的做法合并确认。'),dataRow('板件',boardGroups().length+' 组 · '+state.project.parts.length+' 件'),dataRow('节点',nodeGroups().length+' 组 · '+state.project.joints.length+' 处'),components());footer('F5','从板件开始',()=>boardGroups().length?startBoard(0):navigate('M9'));body.append(button('查看做法清单',()=>navigate('M9'),false,{quiet:true}));}
function renderBoard(){const g=boardGroups()[state.boardIndex];if(!g){heading('需要补充板件');footer('M1','查看清单',()=>navigate('M9'));return;}heading(g.name,'做法 · 板件');body.append(text('B'+(state.boardIndex+1)+' · '+g.quantity+' 件'+(g.quantity>1?'，一起核对':'')),dataRow('材料',state.project.materials[g.material_id]?.name||g.material_id),...['length','width','thickness'].map((key,i)=>dataRow(['长','宽','厚'][i],format(g.dimensions[key+'_mm'])+' mm')),button('修改板件',()=>editMethod('board')));if(g.quantity>1)body.append(text('尺寸和加工相同的对称板件，一次确认覆盖整组。'));footer(()=>previousMethod('board'),'下一个',()=>nextMethod('board'));body.append(button('返回做法汇总',()=>navigate('M9'),false,{quiet:true}));}
const jointKinds={screw:'螺钉 / 螺栓连接',dowel:'木销连接',half_lap:'半搭接',mortise_tenon:'榫卯连接',cam_lock:'偏心件（cam lock）'};
function renderNode(){const g=nodeGroups()[state.nodeIndex],joint=jointFor(g);if(!g||!joint){heading('需要补充连接节点');footer('M1','让 AI 补充',()=>startRun('modify','为当前所有板件补全连接节点、孔位、五金规格和装配说明。','M8'));return;}heading(g.name,'做法 · 连接节点');body.append(text('J'+(state.nodeIndex+1)+' · '+g.quantity+' 处'+(g.quantity>1?'，对称做法一起确认':'')),dataRow('连接方式',jointKinds[joint.kind]||joint.kind));for(const h of joint.hardware||[])body.append(dataRow(h.name,h.quantity+' 件 / 处'));body.append(text('整椅看位置，局部看连接，拆解看装配。'),button('修改节点',()=>editMethod('node')),detail('节点规格与装配说明',...(joint.hardware||[]).map(h=>text(h.name+' · '+h.spec)),...g.joint_ids.map(id=>text(state.project.joints.find(j=>j.id===id)?.assembly_note||''))));footer(()=>previousMethod('node'),state.nodeIndex===nodeGroups().length-1?'完成节点核对':'下一个',()=>nextMethod('node'));body.append(button('返回做法汇总',()=>navigate('M9'),false,{quiet:true}));}
function renderMethodEdit(){const g=currentGroup();heading(state.editKind==='node'?'修改这个连接':'修改这一组板件');if(!g){footer('M9','返回清单',()=>navigate('M9'));return;}body.append(text(g.name+' · '+g.quantity+' '+(state.editKind==='node'?'处':'件')));const draft=state.methodDraft;if(!draft){editMethod(state.editKind);return;}
  if(state.editKind==='board'){body.append(el('div',{class:'form-grid'},...['length','width','thickness'].map((key,i)=>field(['长','宽','厚'][i]+' · mm',draft[key+'_mm'],v=>draft[key+'_mm']=v,{numeric:true}))),el('label',{class:'field'},'材料',el('select',{'aria-label':'材料',value:draft.material_id,onChange:e=>draft.material_id=e.target.value},...Object.entries(state.project.materials).map(([id,m])=>el('option',{value:id},m.name)))));}
  else{body.append(el('label',{class:'field'},'节点做法',el('select',{'aria-label':'节点做法',value:draft.kind,onChange:e=>draft.kind=e.target.value},...Object.entries({...jointKinds,nail:'钉接',other:'其他节点'}).map(([key,label])=>el('option',{value:key},label)))),field('具体要求',draft.text,v=>draft.text=v,{multiline:true,placeholder:'希望的五金、榫卯、工具或装配方式'}));}
  body.append(text('先生成关联修改并预览，采用后才改变当前设计。'));footer(state.editKind==='node'?'M8':'M2','预览修改',()=>previewMethod());}
function renderMethodPreview(){heading('看看这次修改。');if(!state.proposal){body.append(text('这版候选已变化，请重新读取当前设计。'));footer('M9','刷新设计',async()=>{await refresh({recover:true});navigate(state.proposal?'M5':'M9');});return;}body.append(text(state.proposal.summary),el('div',{class:'row'},button('看原方案',()=>{state.previewOriginal=true;}),button('看修改后',()=>{state.previewOriginal=false;})),checksDetail(state.proposal.checks));if(state.proposal.preservation_conflict)body.append(notice('需要作为改款确认',state.proposal.preservation_conflict.message||'这版修改超出已知保型范围。'),button('作为改款保留原版',async()=>{state.proposal=await api(base()+'/proposal/'+state.proposal.id+'/redesign',payload('POST',{expected_revision:state.project.revision}));}));footer(()=>navigate(state.methodDraft?'M3':'M9'),'采用修改',adoptMethod);body.append(button('不采用，返回设计',async()=>{await dismissProposal();navigate('M9');},false,{quiet:true}));}
function selectSummary(kind,index){state.summaryKind=kind;state.summaryIndex=index;state.selected=null;state.nodeMode='whole';render();remember();}
async function confirmAllMethods(){
  if(!state.review?.enabled){await api(base()+'/review/start',payload('POST',{expected_revision:state.project.revision}));await refresh();}
  for(const category of ['board','node']){
    for(;;){
      const groups=category==='board'?boardGroups():nodeGroups();
      const next=groups.find(group=>!group.confirmed);
      if(!next)break;
      try{
        await api(base()+'/review/confirm',payload('POST',{expected_revision:state.project.revision,category,id:next.id,fingerprint:next.fingerprint,decision:'keep'}));
      }catch(error){
        if(error.status===409){await refresh();continue;}
        throw error;
      }
      await refresh();
    }
  }
  await refresh();
}

function renderMethodSummary(){
  heading('做法汇总');
  if(state.proposal)body.append(notice('有一版修改尚未采用','先查看候选，采用或取消后再生成加工包。'),button('查看待采用修改',()=>navigate(state.runReturn==='R4'?'R4':'M5')));
  const nodes=state.summaryKind==='node',groups=nodes?nodeGroups():boardGroups();state.summaryIndex=Math.min(state.summaryIndex,Math.max(0,groups.length-1));
  body.append(el('div',{class:'summary-tabs'},...['board','node'].map((kind,i)=>rawButton([`板件 · ${boardGroups().length} 组`,`节点 · ${nodeGroups().length} 组`][i],()=>selectSummary(kind,0),{'aria-pressed':kind===state.summaryKind}))));
  const table=el('table',{class:'parts-table'},el('thead',{},el('tr',{},...(nodes?['节点','做法','处']:['板件','长','宽','厚','件']).map(name=>el('th',{},name))))),rows=el('tbody');groups.forEach((g,i)=>rows.append(el('tr',{'aria-selected':state.summaryIndex===i},el('td',{},rawButton((nodes?'J':'B')+(i+1)+' '+g.name,()=>selectSummary(state.summaryKind,i))),...(nodes?[el('td',{},jointKinds[g.kind]?.replace('连接','')||g.kind),el('td',{},g.quantity)]:['length','width','thickness'].map(k=>el('td',{},format(g.dimensions[k+'_mm']))).concat(el('td',{},g.quantity))))));table.append(rows);body.append(table);
  const g=groups[state.summaryIndex];if(g)body.append(text(g.name+' · '+(g.confirmed?'已确认':'待确认')));
  const pendingDimensions=dimensions().filter(d=>!d.confirmed),blockers=(state.pkg?.checks||[]).filter(c=>c.severity==='blocker'&&c.code!=='joint_unconfirmed');
  if(pendingDimensions.length)body.append(notice('尺寸需要重新核对',pendingDimensions.map(d=>d.label).join('、')));
  if(blockers.length)body.append(notice('出包前还有 '+blockers.length+' 项',blockers[0].message));
  if(pendingDimensions.length){footer('F5','返回尺寸确定',()=>navigate('F5'));return;}
  if(blockers.length){footer('M9','处理未解决项',()=>navigate('M6'));return;}
  if(state.review?.complete){footer('M9','生成加工包',createPackage);return;}
  footer('F5','确认全部做法',confirmAllMethods);
}

function renderUnresolved(){const issues=(state.pkg?.checks||[]).filter(c=>c.severity==='blocker'&&c.code!=='joint_unconfirmed'),issue=issues[0];heading(issue?'先处理这一项':'已经可以继续核对');if(!issue){footer('M9','返回清单',()=>navigate('M9'));return;}body.append(text('剩余 '+issues.length+' 项'),notice('需要你的决定',issue.message));if(issue.part_ids?.length){state.selected=issue.part_ids[0];body.append(button('聚焦相关部件',()=>viewport?.focus(issue.part_ids[0])));}
  if(issue.code==='scale_unconfirmed'){state.scaleValue??='';state.scaleNote??='';body.append(field('已知尺寸 · mm',state.scaleValue,v=>state.scaleValue=v,{numeric:true}),field('依据',state.scaleNote,v=>state.scaleNote=v,{placeholder:'图纸标注、产品说明或实测'}));footer('M9','保存尺度依据',async()=>{state.project=await api(base()+'/scale-anchor',payload('POST',{expected_revision:state.project.revision,length_mm:parseQuantity(state.scaleValue),note:state.scaleNote}));await refresh();});}
  else if(issue.code==='fabrication_mode_missing'){body.append(button('加工店制件，我来装配',()=>patchProject({fabrication_mode:'shop'})),button('加工店下料/打孔，我装配',()=>patchProject({fabrication_mode:'kit'})),button('我自行加工和装配',()=>patchProject({fabrication_mode:'self'})));footer('M9',null);}
  else if(issue.code==='grain_unconfirmed'){const part=state.project.parts.find(p=>issue.part_ids.includes(p.id));body.append(text('选择这块板的木纹 / 板材主方向。'));for(const axis of ['x','z'])body.append(button(axis==='x'?'沿局部宽边 X':'沿局部长边 Z',()=>patchProject({materials:{...state.project.materials,[part.material_id]:{...state.project.materials[part.material_id],grain_axis:axis}}})));footer('M9',null);}
  else if(issue.code==='scope_unconfirmed'){body.append(text('首版支持平直板件、简单平面斜切与孔槽。请核对当前结构。'));footer('M9','确认属于支持范围',()=>patchProject({scope:'supported',scope_reason:'用户核对：平直板件及简单平面裁切木椅。'}));}
  else if(issue.code==='reference_views_missing'){footer('M9','补充参考',()=>navigate('R1'));}
  else{body.append(field('补充要求',state.editText,v=>state.editText=v,{multiline:true,placeholder:'可补充制作条件或你希望的做法'}));footer('M9','请 AI 修正',()=>startRun('repair',issue.message+'\n'+state.editText,'M9'));}
}

function packageMenu(){return el('div',{class:'links-list'},button('采购清单',()=>navigate('P3')),button('加工资料与图纸',()=>navigate('P4')),button('装配步骤',()=>navigate('P5')));}
function packagePrefix(){if(state.page!=='P1')body.append(el('div',{class:'row'},button('加工包主页',()=>navigate('P1'),false,{quiet:true}),el('small',{},' / v'+state.exported.revision)));}
function renderPackage(){if(!state.exported){heading('生成当前版本加工包');body.append(text('先完成尺寸和做法核对，生成后所有资料绑定同一版本。'));footer('M9','查看核对清单',()=>navigate('M9'));return;}
  const pkg=state.exported.package_snapshot,revision=state.exported.revision;packagePrefix();
  if(state.page==='P1'){heading('加工包');body.append(button('拆开看组成',()=>navigate('P2')));footer('M9','下载加工包',()=>navigate('P7'));return;}
  if(state.page==='P2'){heading('拆开看组成');footer('P1','查看装配步骤',()=>navigate('P5'));return;}
  if(state.page==='P3'){heading('我需要买什么？');body.append(text('按当前版本列出木料与五金，板材采购量需结合实际供料规格。'));for(const cut of pkg.cut_list){const d=cut.stock_dimensions_mm;body.append(dataRow(cut.name,button((d?[d.length_mm,d.width_mm,d.thickness_mm]:cut.stock_size_mm).map(format).join(' × ')+' · '+cut.quantity+' 件',()=>{state.selected=cut.part_id;renderViewport();})));}body.append(detail('五金清单',...pkg.hardware.map(h=>dataRow(h.name,h.spec+' × '+h.quantity))));footer('P1','查看加工资料',()=>navigate('P4'));return;}
  if(state.page==='P4'){heading('交给加工店什么？');body.append(text('选择图纸，查看加工面、尺寸和孔位。'),el('div',{class:'links-list'},...pkg.drawings.map((sheet,i)=>button(sheet.title||sheet.id,()=>{state.drawingIndex=i;navigate('P6');}))),button('下载完整 PDF',()=>download(state.exported.pdf_url,'junior-v'+revision+'.pdf')));footer('P1','查看装配步骤',()=>navigate('P5'));return;}
  if(state.page==='P6'){const sheet=pkg.drawings[state.drawingIndex]||pkg.drawings[0];heading(sheet?.title||'图纸预览');if(!sheet){body.append(text('这一版没有图纸。'));footer('P4',null);return;}body.append(text('方案 v'+revision+' · '+sheet.id),el('label',{class:'field'},'图纸',el('select',{'aria-label':'图纸',value:String(state.drawingIndex),onChange:e=>{state.drawingIndex=Number(e.target.value);render();}},...pkg.drawings.map((d,i)=>el('option',{value:i},d.title||d.id)))),button('下载本页 SVG',()=>downloadText(sheet.svg,'junior-v'+revision+'-'+sheet.id+'.svg','image/svg+xml')),button('下载完整 PDF',()=>download(state.exported.pdf_url,'junior-v'+revision+'.pdf')));footer(null,'返回加工资料',()=>navigate('P4'));return;}
  if(state.page==='P5'){const steps=pkg.assembly_steps||[],step=steps[state.assemblyIndex];heading(step?.name||'装配步骤');if(!step){body.append(text('暂无装配步骤。'));footer('P1',null);return;}body.append(text((state.assemblyIndex+1)+' / '+steps.length),text(step.instruction),detail('这一步用什么',...step.hardware.map(h=>dataRow(h.name,h.spec+' × '+h.quantity))));footer(()=>state.assemblyIndex>0?(state.assemblyIndex--,render()):navigate('P1'),state.assemblyIndex===steps.length-1?'完成，返回加工包':'下一组',()=>{if(state.assemblyIndex===steps.length-1)navigate('P1');else{state.assemblyIndex++;state.nodeMode='whole';render();}});return;}
  if(state.page==='P7'){heading('把设计带到工坊。');body.append(text('方案 v'+revision),...['可编辑模型 JSON','PDF / SVG 图纸','采购单、下料表、五金表','装配说明与模型图片'].map(label=>dataRow(label,'已生成')));footer('P1','下载加工包 ZIP',()=>download(state.exported.download_url,'junior-v'+revision+'.zip'));body.append(button('返回设计',()=>navigate('M9'),false,{quiet:true}));}
}
function openSettings(){state.settingsReturn=state.page==='settings'?state.settingsReturn:state.page;navigate('settings');}
function renderSettings(){
  heading('AI 连接','工作室设置');
  const ai=state.ai||{};
  const provider=el('label',{class:'field'},'提供方',el('select',{'data-ai-provider':''},...[
    ['openai','OpenAI（Responses）'],['openai_compatible','OpenAI 兼容接口'],['session','会话协作（当前聊天返回）'],['prototype','本地原型（不调用模型）'],['none','关闭 AI']
  ].map(([value,label])=>el('option',{value,selected:(ai.provider||ai.mode||'openai_compatible')===value},label))));
  const base=field('服务地址 · Base URL',ai.base_url||'',()=>{}, {placeholder:'https://api.openai.com/v1','data-ai-base':''});
  const model=field('模型名称',ai.model||'',()=>{}, {placeholder:'支持图片的模型','data-ai-model':''});
  const key=field('API 密钥', '',()=>{}, {type:'password',placeholder:ai.configured?.API_KEY?'已保存，留空不改':'输入密钥','data-ai-key':''});
  body.append(
    el('div',{class:'data-row'},el('span',{},'当前状态'),el('strong',{},ai.label||'尚未读取')),
    provider,base,model,key,
    el('div',{class:'data-row'},el('span',{},'配置文件'),el('small',{class:'config-path'},ai.config_path||'.data/ai-config.json')),
    state.aiTest?el('small',{class:state.aiTest.ok?'test-ok':'test-fail'},state.aiTest.message):null
  );
  footer(state.settingsReturn,'保存配置',saveAISettings);
  actions.append(button('测试连接',testAISettings,false,{quiet:true}));
}
async function testAISettings(){
  state.aiTest=await api('/ai/test',{method:'POST'});
  state.ai=await api('/ai/status');
  render();
}
async function saveAISettings(){
  const provider=document.querySelector('[data-ai-provider]')?.value||'openai_compatible';
  const base=document.querySelector('[data-ai-base]')?.value||'';
  const model=document.querySelector('[data-ai-model]')?.value||'';
  const key=document.querySelector('[data-ai-key]')?.value||'';
  state.ai=await api('/ai/config',payload('PUT',{provider,base_url:base,model,api_key:key}));
  state.aiTest=null; state.error='';
  render();
}
async function switchStage(index){if(state.proposal&&index!==0&&state.page!=='F3'&&state.page!=='M5')throw new Error('先采用或取消当前候选。');if(index===0){navigate(state.project?.parts.length||state.proposal?'R4':'R1');return;}if(!state.project?.parts.length)throw new Error('先采用第一版模型。');if(index===1){if(!state.review?.enabled){await api(base()+'/review/start',payload('POST',{expected_revision:state.project.revision}));await refresh();}navigate(dimensions().length&&dimensions().every(d=>d.confirmed)?'F5':'F1');return;}if(index===2){if(dimensions().some(d=>!d.confirmed)){navigate('F5');return;}navigate('M9');return;}if(state.exported&&state.exported.revision===state.project.revision)navigate('P1');else await createPackage();}
function renderAIRail(){
  const rail=$('ai-rail');if(!rail)return;
  const ai=state.ai||{};
  rail.replaceChildren(
    el('span',{class:'dot'+(ai.ready?' ready':'')}),
    el('span',{},ai.label||'AI 未读取'),
    button('配置',openSettings,false,{quiet:true})
  );
}
function renderContext(){
  const context=$('studio-context');if(!context)return;context.replaceChildren();
  const project=shownProject();
  if(!project){
    context.append(el('div',{class:'context-head'},el('strong',{},'还没打开椅子'),el('small',{},'从参考或样例开始')));
    context.append(el('div',{class:'context-section'},el('h3',{},'四步工作流'),el('ul',{},...['01 复原','02 适己','03 怎么做','04 加工包'].map(text=>el('li',{},text)))));
    if(state.ai)context.append(el('div',{class:'context-section'},el('h3',{},'AI'),el('p',{},state.ai.label||'尚未读取')));
    return;
  }
  const page=state.page==='settings'?'设置':state.page.startsWith('R')?'复原':state.page.startsWith('F')?'适己':state.page.startsWith('M')?'怎么做':'加工包';
  context.append(el('div',{class:'context-head'},el('strong',{},project.name),el('small',{},'v'+project.revision+' · '+page)));
  context.append(el('div',{class:'context-actions'},...(project.parts?.length?[el('a',{href:'/editor?project='+encodeURIComponent(project.id)},'打开编辑器')]:[])));
  context.append(el('div',{class:'context-section'},el('h3',{},'模型'),el('p',{},(project.parts?.length||0)+' 块板 · '+(project.joints?.length||0)+' 处连接')));
  const parts=project.parts||[];if(parts.length)context.append(el('div',{class:'context-list'},...parts.slice(0,8).map(part=>el('div',{class:'context-row'},el('span',{},part.name),el('strong',{},'×1')))));
  const checks=state.pkg?.checks||[];const blockers=checks.filter(c=>c.severity==='blocker');const warnings=checks.filter(c=>c.severity==='warning');
  context.append(el('div',{class:'context-section'},el('h3',{},'检查'),el('p',{},blockers.length?blockers.length+' 项 blocker':warnings.length?warnings.length+' 项警告':'没有 blocker'),...(blockers.length?blockers.slice(0,3).map(c=>el('p',{},c.message)):[])));
  if(state.page==='settings'&&state.ai){
    context.append(el('div',{class:'context-section'},el('h3',{},'AI 配置'),el('p',{},state.ai.label||'尚未读取'),el('p',{class:'config-path'},state.ai.config_path||'.data/ai-config.json')));
  }
}
function render(){const index=stageIndex();document.body.dataset.stage=STAGES[index];document.body.dataset.page=state.page;body.replaceChildren();actions.replaceChildren();$('step-error').textContent=state.error;$('step-error').hidden=!state.error;$('stage-nav').replaceChildren(...STAGES.map((label,i)=>el('button',{type:'button','aria-current':i===index?'step':null,disabled:state.busy,onClick:()=>action(()=>switchStage(i))},el('span',{},String(i+1).padStart(2,'0')),label)));
  if(state.page==='settings')renderSettings();else if(state.page.startsWith('P'))renderPackage();else if(['R2','F2','M4'].includes(state.page))renderWaiting();else ({R1:renderEntry,R4:renderRestore,R5:renderRestoreEdit,F1:renderProfile,F6:renderProfilePosture,F3:renderDimension,F4:renderConflict,F5:renderSizeSummary,M1:renderMethods,M2:renderBoard,M3:renderMethodEdit,M5:renderMethodPreview,M8:renderNode,M9:renderMethodSummary,M6:renderUnresolved}[state.page]||renderEntry)();
  renderViewport();renderContext();renderAIRail();renderBusy();$('project-picker').value=state.project?.id||'';const modeEditor=$('mode-editor');if(modeEditor)modeEditor.href=state.project?.parts?.length?'/editor?project='+encodeURIComponent(state.project.id):'/editor';
}

function viewportNodeGroup(){if(state.page==='M9'&&state.summaryKind==='node')return nodeGroups()[state.summaryIndex];if((['M8','M3','M4'].includes(state.page)||state.page==='M5'&&(state.runReturn==='M8'||state.methodDraft))&&state.editKind==='node')return currentGroup();if(state.page==='P5'&&state.exported){const step=state.exported.package_snapshot.assembly_steps[state.assemblyIndex];return step?{id:step.joint_id,joint_ids:[step.joint_id],part_ids:step.part_ids,quantity:1,name:step.name}:null;}return null;}
function selectionIds(){if(state.page==='M9'&&state.summaryKind==='board')return boardGroups()[state.summaryIndex]?.part_ids||[];if((['M2','M3'].includes(state.page)||state.page==='M5'&&(state.runReturn==='M2'||state.methodDraft))&&state.editKind==='board')return boardGroups()[state.boardIndex]?.part_ids||[];if(state.page==='F3')return dim()?.part_ids||[];return state.selected?[state.selected]:[];}
function dimensionInputChanged(raw){
  state.pending=raw;state.dimensionDirty=true;state.agentNeeded=null;state.error='';
  const left=document.getElementById('dimension-input-left');
  if(left&&document.activeElement!==left)left.value=raw;
  const model=document.querySelector('.model-dimension-input input');
  if(model&&document.activeElement!==model)model.value=raw;
  clearTimeout(previewTimer);
  previewTimer=setTimeout(async()=>{
    if(state.page!=='F3'||state.busy)return;
    try{
      const focused=document.activeElement?.matches('.model-dimension-input input,#dimension-input-left'),position=document.activeElement?.selectionStart;
      await previewDimension();
      renderViewport();
      if(focused&&state.page==='F3'){
        const input=document.activeElement?.matches('.model-dimension-input input')?document.activeElement:document.querySelector('.model-dimension-input input');
        input?.focus();input?.setSelectionRange(position,position);
      }
      if(state.error)report(state.error);
    }catch(error){report(error);}
  },600);
}

function setViewportDimension(){if(!viewport)return;const item=dim(),project=shownProject();if(!item||item.current_value===null){viewport.setDimensions([]);return;}const seat=project.parts.find(p=>p.id===item.part_ids[0]);if(!seat){viewport.setDimensions([]);return;}const transform=new THREE.Matrix4().compose(new THREE.Vector3(...seat.position_mm),new THREE.Quaternion().setFromEuler(new THREE.Euler(...seat.rotation_deg.map(v=>v*Math.PI/180))),new THREE.Vector3(1,1,1));const world=v=>new THREE.Vector3(...v).applyMatrix4(transform).toArray();const [w,t,d]=seat.size_mm;let start,end,points,labelPoint;
  let extensions=[];
  if(item.key==='seat_height_mm'){
    const left=world([-w/2,t/2,d/2]),floor=world([-w/2,0,d/2]);
    const lineTop=world([-w/2-90,t/2,d/2]),lineBase=world([-w/2-90,0,d/2]);
    start=lineBase;end=lineTop;extensions=[[floor,lineBase],[left,lineTop]];
  }
  else if(item.key==='seat_width_mm'){
    const left=world([-w/2,t/2,d/2]),right=world([w/2,t/2,d/2]);
    const lineLeft=world([-w/2,t/2,d/2+90]),lineRight=world([w/2,t/2,d/2+90]);
    start=lineLeft;end=lineRight;extensions=[[left,lineLeft],[right,lineRight]];
  }
  else if(item.key==='seat_depth_mm'){
    const back=world([w/2,t/2,-d/2]),front=world([w/2,t/2,d/2]);
    const lineBack=world([w/2+90,t/2,-d/2]),lineFront=world([w/2+90,t/2,d/2]);
    start=lineBack;end=lineFront;extensions=[[back,lineBack],[front,lineFront]];
  }
  else{
    const center=world([0,t/2,0]),radius=110,tilt=dimensions().find(v=>v.key==='seat_tilt_deg')?.current_value||0,angle=item.key==='seat_tilt_deg'?item.current_value:(item.current_value+tilt);const a=item.key==='seat_tilt_deg'?0:tilt;const point=deg=>[center[0],center[1]+Math.sin(deg*Math.PI/180)*radius,center[2]+Math.cos(deg*Math.PI/180)*radius];points=[center,point(a),...Array.from({length:30},(_,i)=>point(a+(angle-a)*i/29)),center];start=center;end=point(angle);
  }
  labelPoint=points&&points.length>2?points[Math.floor(points.length/2)]:[(start[0]+end[0])/2,(start[1]+end[1])/2,(start[2]+end[2])/2];
  viewport.setDimensions([{start,end,points,extensions,labelPoint,label:item.label,value:state.pending||String(item.current_value??''),unit:item.unit,onInput:raw=>dimensionInputChanged(raw),onCommit:()=>action(nextDimension),onCancel:()=>{state.pending=String(item.current_value);state.proposal=null;state.agentNeeded=null;render();}}]);
}
function boardDimensions(){const g=boardGroups()[state.summaryIndex],project=shownProject(),part=project?.parts.find(p=>g?.part_ids.includes(p.id));if(!part)return [];const axes=g.dimensions.axes,matrix=new THREE.Matrix4().compose(new THREE.Vector3(...part.position_mm),new THREE.Quaternion().setFromEuler(new THREE.Euler(...part.rotation_deg.map(v=>v*Math.PI/180))),new THREE.Vector3(1,1,1));return ['length','width'].map(key=>{const axis={local_x:0,local_y:1,local_z:2}[axes[key]],a=part.size_mm.map(n=>n/2+20),b=[...a];a[axis]=-part.size_mm[axis]/2;b[axis]=part.size_mm[axis]/2;return {start:new THREE.Vector3(...a).applyMatrix4(matrix).toArray(),end:new THREE.Vector3(...b).applyMatrix4(matrix).toArray(),label:format(g.dimensions[key+'_mm'])+' mm',onEdit:()=>action(()=>{startBoard(state.summaryIndex);editMethod('board');})};});}
function tool(label,text,run,disabled=false,pressed=false){return rawButton(text,run,{'aria-label':label,title:label,disabled,'aria-pressed':pressed});}
function renderViewport(){if(!viewport)return;const project=shownProject(),pkg=shownPackage(),parts=project?.parts||[],key=JSON.stringify([project?.id,project?.revision,state.proposal?.id,state.previewOriginal,state.page.startsWith('P')?state.exported?.revision:null]);const empty=!parts.length;$('viewport-empty').hidden=!empty;$('drawing-view').hidden=state.page!=='P6';$('viewport').hidden=state.page==='P6';overlay.hidden=state.page==='P6';overlay.replaceChildren();
  if(key!==viewportModelKey){viewport.load(parts,{fit:viewportModelKey===''||viewportModelKey.split(',')[0]!==key.split(',')[0],hardware:pkg?.hardware_instances||[],joints:project?.joints||[]});viewportModelKey=key;}
  const toolbar=$('viewport-tools');toolbar.replaceChildren();if(state.page==='P6'){const sheet=state.exported?.package_snapshot.drawings[state.drawingIndex];$('drawing-view').replaceChildren(sheet?el('img',{src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(sheet.svg),alt:sheet.title||sheet.id}):text('没有图纸。'));toolbar.append(button('返回三维',()=>navigate('P4')));return;}
  const disabled=empty||state.busy;toolbar.append(el('div',{class:'tool-set'},tool('选择部件，拖动旋转','选择',()=>{state.tool='select';viewport.setTool('select');renderViewport();},disabled,state.tool==='select'),tool('点选两点测量距离','测量',()=>{state.tool=state.tool==='measure'?'select':'measure';viewport.setTool(state.tool);renderViewport();},disabled,state.tool==='measure'),tool('只显示当前选中','隔离',isolateSelection,disabled||!selectionIds().length,state.isolated),tool('显示全部零件','全部',showAllParts,disabled,false),tool('拆开/合上零件','拆开',toggleExploded,disabled,state.exploded),button('撤销',()=>undoRedo(false),false,{disabled:disabled||!state.undo.length}),button('重做',()=>undoRedo(true),false,{disabled:disabled||!state.redo.length})),el('div',{class:'view-set'},...['iso','front','right','top'].map((v,i)=>tool(['等轴视角','前视图','右视图','俯视图'][i],['等轴','前','右','顶'][i],()=>viewport.setView(v),disabled)),tool('聚焦选中部件','聚焦',()=>viewport.focus(state.selected),disabled||!state.selected),tool('适应整个模型','适应',()=>{state.nodeMode='whole';viewport.clearInspection();viewport.setView('iso');renderViewport();},disabled)));
  if(empty){viewport.setDimensions([]);return;}overlay.append(el('span',{class:'viewport-hint'},'拖动旋转 · 滚轮缩放 · 右拖平移'));
  const group=viewportNodeGroup();if(group){const index=state.page==='M9'?state.summaryIndex:state.nodeIndex;viewport.setJointGroup(group,{mode:state.nodeMode,label:'J'+(index+1),joints:project.joints,defined:true,onModeChange:mode=>{state.nodeMode=mode;renderViewport();}});overlay.append(el('div',{class:'node-view-tabs'},...['whole','local','exploded'].map((mode,i)=>rawButton(['整椅','局部','拆解'][i],()=>{state.nodeMode=mode;renderViewport();},{'aria-pressed':state.nodeMode===mode}))),el('small',{class:'node-view-caption'},state.nodeMode==='whole'?group.quantity+' 处连接':group.quantity>1?'展示一侧 · 同组一起确认':'当前连接 · 孔轴与五金'));}else{viewport.clearInspection();viewport.highlightParts(selectionIds());if(state.selected)viewport.setSelection(state.selected);viewport.setExploded(state.exploded||state.page==='P2');}
  if(state.page==='F3'||state.page==='F5')setViewportDimension();else viewport.setDimensions(state.page==='M9'&&state.summaryKind==='board'?boardDimensions():[]);
  if(state.proposal&&['R4','R5','F3','M5'].includes(state.page))overlay.append(el('div',{class:'viewport-status'},el('span',{},state.previewOriginal?'原方案':'候选预览 · 尚未采用')));
  if(state.selected&&!group){const part=parts.find(p=>p.id===state.selected);if(part)overlay.append(el('div',{class:'selection-bar'},el('strong',{},part.name),rawButton('聚焦',()=>viewport.focus(part.id)),rawButton('取消',()=>{state.selected=null;renderViewport();})));}
  if(state.tool==='measure')overlay.append(el('div',{class:'viewport-status'},el('span',{id:'measure-readout'},'点选端点或中点作为起点')));
  $('viewport').dataset.parts=parts.length;$('viewport').dataset.revision=project.revision;$('viewport').dataset.seatHeight=dimensions().find(d=>d.key==='seat_height_mm')?.current_value??'';
}

function isolateSelection(){
  const ids=new Set(selectionIds());if(!ids.size)return;
  for(const part of shownProject()?.parts||[])viewport.setVisible(part.id,ids.has(part.id));
  state.isolated=true;
}
function showAllParts(){for(const part of shownProject()?.parts||[])viewport.setVisible(part.id,true);state.isolated=false;}
function toggleExploded(){state.exploded=!state.exploded;viewport.setExploded(state.exploded);renderViewport();}
function initializeViewport(){try{viewport=new WorkshopViewport($('viewport'),{onSelect:id=>{state.selected=id;if(state.page==='M9'&&state.summaryKind==='board'&&id){const index=boardGroups().findIndex(g=>g.part_ids.includes(id));if(index>=0){state.summaryIndex=index;render();return;}}renderViewport();},onMeasure:value=>{const readout=$('measure-readout');if(!readout)return;if(!value){readout.textContent='点选端点或中点';return;}if(value.pending){readout.textContent='起点已定'+(value.snap?' · '+value.snap:'')+' · 移到终点';return;}if(value.distance_mm!==undefined){readout.textContent=format(value.distance_mm)+' mm'+(value.snap?' · '+value.snap:'')+(value.hover?' · 点击确定':' · 点击再测 / Esc 退出');}},onError:report});}catch(error){$('viewport-empty').replaceChildren(el('h2',{},'三维视口未能启动'),text('请使用支持 WebGL 的浏览器，或启用硬件加速后重新打开。'));report(error);}}
async function boot(){initializeViewport();$('new-project').addEventListener('click',()=>action(async()=>{if(state.run&&ACTIVE.has(state.run.status))throw new Error('先取消当前处理，再开始新设计。');state.project=null;state.review=null;state.pkg=null;state.proposal=null;state.run=null;state.files=[];state.referenceUrl='';state.idea='';state.exported=null;state.packageProject=null;state.profile=null;state.profileNotes='';state.undo=[];state.redo=[];navigate('R1');}));$('settings-button').addEventListener('click',()=>action(()=>openSettings()));$('project-picker').addEventListener('change',e=>{if(e.target.value)action(()=>openProject(e.target.value));});window.addEventListener('popstate',()=>{const p=new URLSearchParams(location.hash.slice(1)),page=p.get('step');if(p.get('project')&&p.get('project')!==state.project?.id)action(()=>openProject(p.get('project'),page));else if(page){state.page=page.startsWith('P')&&!state.exported?'M9':page;render();}});
  try{const [ai,profile]=await Promise.all([api('/ai/status'),api('/profile')]);state.ai=ai;state.savedProfile=profile;await listProjects();const params=new URLSearchParams(location.hash.slice(1)),id=params.get('project')||localStorage.getItem('junior-studio-last');if(id&&state.projects.some(p=>p.id===id))await openProject(id,params.get('step'));else render();}catch(error){report(error);render();}}
boot();
