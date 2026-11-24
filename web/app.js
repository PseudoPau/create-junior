import {openDrawingViewer} from './drawing-viewer.js?v=r1-4';
import {renderReviewFlow} from './review-flow.js?v=r2-1';
import {parseQuantity} from './quantity-input.js?v=r2-2';
const API = '/api/workbench';
const state = { page:'home', packageSnapshot:null, homeDraft:localStorage.getItem('junior-home-draft')||'', commandDraft:'', projectDetails:{}, project:null, projects:[], proposal:null, checks:[], coverage:{}, versions:[], preparation:null, dirtyForms:false, context:{revision:null,preferences:{},inventory:[]}, tab:'references', sidebarMode:'tasks', sidebarOpen:false, listMode:'joints', inspectedJointId:null, listPartId:null, designViewKey:null, activeTask:'reference', selectedId:null, busy:false, viewport:null, noticeTimer:null, conversationOpen:false, interactionRecords:[], localMessages:[], conversationProject:null, historyKey:'', polling:false, referenceDraft:'', fitDraft:'', referenceErrors:{}, resolvingReference:null, aiStatus:null, generating:false, generationError:'' };
const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
function node(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) { if (key.startsWith('on')) element.addEventListener(key.slice(2).toLowerCase(),value); else if (key === 'class') element.className=value; else if (key==='checked' || key==='disabled' || key==='selected' || key==='open') element[key]=!!value; else if (value!==null && value!==undefined) element.setAttribute(key,String(value)); }
  for (const child of children.flat(Infinity)) if(child!==null && child!==undefined) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return element;
}
function svgNode(tag, attrs = {}, ...children) {
  const element = document.createElementNS('http://www.w3.org/2000/svg',tag);
  for (const [key,value] of Object.entries(attrs)) if (value!==null && value!==undefined) element.setAttribute(key,String(value));
  for (const child of children.flat(Infinity)) if(child!==null && child!==undefined) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return element;
}
const button = (label, action, className = '', disabled = false) => node('button',{type:'button',class:className,disabled,onClick:()=>Promise.resolve().then(action).catch(report)},label);
const paragraph = text => node('p',{},text);
function report(error) { notice(error?.message || String(error),true); }
function notice(text,error=false) { const target=$('notice'); target.textContent=text; target.className='notice'+(error?' error':''); clearTimeout(state.noticeTimer); state.noticeTimer=setTimeout(()=>target.classList.add('hidden'),error?9000:4500); }
async function api(path,options={}) {
  const response=await fetch(API+path,options); let payload; try { payload=await response.json(); } catch { throw new Error('服务返回了无法读取的数据，请检查本地服务。'); }
  if(!response.ok) { if(response.status===409 && path==='/context')throw new Error('个人偏好或仓库已在其他页面更新，请重新加载后再保存；本次没有覆盖远端记录。'); const detail=payload.detail; const message=typeof detail==='string'?detail:detail?.message || detail?.error || (Array.isArray(detail)?detail.map(item=>item.msg).join('；'):null);const error=new Error(message || '请求失败（'+response.status+'）');error.detail=detail;throw error; }
  return payload;
}
const json = (method,body) => ({method,headers:{'content-type':'application/json'},body:JSON.stringify(body)});
const base = () => '/projects/'+state.project.id;
function displayProject() { return state.proposal?.status==='ready'?{...state.project,...state.proposal.patch}:state.project; }
function displayChecks() { return state.proposal?.status==='ready'?(state.proposal.checks||[]):state.checks; }
function displayCoverage() { return state.proposal?.status==='ready'?(state.proposal.coverage||{}):state.coverage; }
function requireNoProposal() { if(state.proposal?.status==='ready')throw new Error('请先采用或取消当前修改，再开始新的操作。'); }
async function dismissProposal() { const proposal=state.proposal;if(!proposal)return;await guarded(async()=>{if(!proposal.local && proposal.status==='ready')await api(base()+'/proposal/dismiss',json('POST',{expected_revision:state.project.revision,proposal_id:proposal.id}));localStorage.setItem('junior-dismissed-'+state.project.id,proposal.id);state.proposal=null;await refreshData();render();});renderConversation(); }
async function recoverProposal() {
  const response=await fetch(API+base()+'/proposal');
  if(response.status===404)return;
  if(!response.ok)throw new Error('暂时无法恢复等你决定的修改，请刷新重试。');
  const proposal=await response.json();
  if(proposal.status==='ready' && proposal.base_revision===state.project.revision && proposal.id!==localStorage.getItem('junior-dismissed-'+state.project.id))state.proposal=proposal;
}
async function importProposal(file) {
  requireNoProposal();
  if(file.size>2*1024*1024)throw new Error('设计候选文件最多 2 MB。');
  const projectId=state.project.id,revision=state.project.revision;
  await guarded(async()=>{
    let payload;try {payload=JSON.parse(await file.text());}catch {throw new Error('无法读取设计候选，请选择有效的 JSON 文件。');}
    if(!payload || typeof payload!=='object' || Array.isArray(payload) || typeof payload.summary!=='string' || !payload.patch || typeof payload.patch!=='object' || Array.isArray(payload.patch))throw new Error('设计候选需要包含 summary 说明和 patch 设计数据。');
    if(state.project.id!==projectId || state.project.revision!==revision)throw new Error('项目已变化，请重新选择候选文件。');
    requireNoProposal();
    state.proposal=await api('/projects/'+projectId+'/proposal/import'+(payload.request_id?'?request_id='+encodeURIComponent(payload.request_id):''),json('POST',{expected_revision:revision,summary:payload.summary,patch:payload.patch,purpose:payload.purpose||'design'}));
    state.activeTask=state.proposal.purpose==='manufacturing'?'confirm':'reference';setPanel('tasks',false);render();notice('候选已导入，请在模型下方采用或查看依据。');
  });
}
function chooseProposalFile() {requireNoProposal();$('proposal-input').click();}
function field(label,name,value='',type='text',options=null) {
  const control=options ? node('select',{name},options.map(([val,text])=>node('option',{value:val,selected:String(value)===String(val)},text))) : node('input',{name,type,value:value??'',step:type==='number'?'any':null});
  return node('label',{class:'field'},label,control);
}
function value(form,name) { return form.querySelector('[name="'+name+'"]')?.value; }
function number(form,name,fallback=null) { const input=value(form,name); return input==='' || input===undefined ? fallback : Number(input); }
function boolField(label,name,checked=false) { return node('label',{class:'decision'},node('input',{type:'checkbox',name,checked}), ' '+label); }
function setBusy(value) { state.busy=value;if(state.project)renderGenerationControls();renderHome(); document.body.setAttribute('aria-busy',String(value)); $('save-state').textContent=value?'正在处理…':state.project?'已保存到本机 · v'+state.project.revision:'尚未创建项目'; }
async function guarded(action) {if(state.busy)throw new Error('上一个操作正在保存，请稍候。');let completed=false;setBusy(true);try{const result=await action();completed=true;return result;}finally{setBusy(false);if(state.project)renderConversation();if(completed&&state.project&&!state.dirtyForms){renderTasks();renderCandidateActions();if(state.sidebarMode==='context')renderContext();}}}
async function refreshData() {
  const project=state.project;
  const results=await Promise.allSettled([api(base()+'/checks'),api(base()+'/versions'),api(base()+'/preparation'),api(base()+'/interaction/history')]);
  if(state.project?.id!==project.id||state.project?.revision!==project.revision) return;
  state.checksError=results[0].status==='rejected';
  state.checks=results[0].status==='fulfilled'?(results[0].value.checks||[]):[]; state.coverage=results[0].status==='fulfilled'?(results[0].value.coverage||{}):{};
  state.versions=results[1].status==='fulfilled'?results[1].value:[];
  state.preparation=results[2].status==='fulfilled'?results[2].value:null;
  if(results[3].status==='fulfilled')state.interactionRecords=results[3].value.records||[];
  for (const result of results) if(result.status==='rejected') report(result.reason);
  await loadFitComparison();
}
async function mutate(patch,advance=false,proposalRevision=null) {
  if(state.proposal && proposalRevision===null)throw new Error('请先采用或取消当前修改，再继续改设计。');
  if(proposalRevision!==null && proposalRevision!==state.project.revision)throw new Error('这版修改基于旧版本，不能用于当前设计；请取消后重新生成。');
  return guarded(async()=>{ state.project=await api(base(),json('PUT',{expected_revision:state.project.revision,patch})); state.proposal=null; state.dirtyForms=false; await refreshData(); if(advance) state.activeTask=nextTask(); render(); return state.project; });
}
const tasks=[['reference','复原','这是你要的那把椅子吗'],['fit','适己','它哪里不适合你'],['make','怎么做','你打算怎么做'],['confirm','加工包','图纸、清单与装配']];
function taskDone(id) {
  const p=state.project;if(!p)return false;
  if(id==='reference')return p.scope==='supported' && p.parts?.length>0;
  if(id==='fit')return !!p.parts?.length && !!p.scale?.confirmed;
  if(id==='make')return !!p.fabrication_mode && !!p.requirements?.load_kg && !!p.requirements?.environment;
  return p.confirmed_revision===p.revision;
}
function nextTask() { return tasks.find(([id])=>!taskDone(id))?.[0] || 'confirm'; }
function taskAvailable(id) {
  if(id==='reference')return true;
  if(!taskDone('reference'))return false;
  if(id==='fit')return true;
  return true;
}
function goTask(id) {
  if(state.dirtyForms)throw new Error('先保存正在编辑的内容，再切换步骤。');
  if(!taskAvailable(id)){notice('先得到第一版模型，再继续设计。');return;}
  showPage('design');
  clearInspection(false);state.activeTask=id;state.conversationOpen=false;setPanel('tasks',true);renderTasks();renderModelGuide();renderConversation();focusTask(id);
}
function pendingRequest() {const req=state.preparation?.request;return req?.status==='pending'&&req.base_revision===state.project.revision?req:null;}
function activeRun(){const run=state.designRun;return run?.project_id===state.project?.id&&run.base_revision===state.project.revision?run:null;}
async function createDesignRun(intent,text=''){
  requireNoProposal();
  const existing=activeRun();if(existing&&['waiting_for_session','running','needs_input'].includes(existing.status))throw new Error('已有任务正在处理，请先补充当前问题或取消任务。');
  await guarded(async()=>{state.designRun=await api(base()+'/design-runs',json('POST',{expected_revision:state.project.revision,intent,text,client_request_id:crypto.randomUUID()}));state.generationError='';state.conversationOpen=false;state.dirtyForms=false;state.sidebarMode='tasks';setPanel('tasks',true);render();});
}
function runCard(){
  const run=activeRun();if(!run||['ready','completed','dismissed'].includes(run.status))return null;
  const labels={waiting_for_session:'等待当前会话处理',running:'正在处理设计',needs_input:'需要你补充一项信息',failed:'这次没有完成',cancelled:'任务已取消',stale:'设计已变化',interrupted:'处理已中断'};
  const card=node('section',{class:'session-run-card',role:'status'},node('strong',{},labels[run.status]||run.status));
  if(run.status==='waiting_for_session')card.append(paragraph('在当前聊天说“处理 Junior 请求”。模型返回后会直接显示在这里。'),button('复制协作请求',async()=>{await navigator.clipboard.writeText('处理 Junior 项目 '+run.project_id+' 的设计任务 '+run.id+'，完成参考分析、建模检查和修正后返回网页候选。');notice('已复制。');},'quiet'));
  if(run.status==='running')card.append(paragraph(run.stage||'正在读取参考并检查模型。'));
  if(run.status==='needs_input'){
    const input=node('input',{type:'text','aria-label':'补充回答'}),question=typeof run.question==='string'?run.question:run.question?.text||run.question?.message||'请补充当前设计所需的信息。';
    card.append(paragraph(question),input,button('提交并继续',async()=>{if(!input.value.trim())throw new Error('请填写回答。');state.designRun=await api(base()+'/design-runs/'+run.id+'/answer',json('POST',{expected_revision:state.project.revision,answer:input.value.trim()}));state.dirtyForms=false;render();},'primary'));
  }
  if(run.error)card.append(paragraph(typeof run.error==='string'?run.error:run.error.message||'任务未完成，请重试。'));
  if(['waiting_for_session','running','needs_input'].includes(run.status))card.append(button('取消任务',async()=>{state.designRun=await api(base()+'/design-runs/'+run.id+'/cancel',json('POST',{expected_revision:state.project.revision}));render();},'quiet'));
  else card.append(button('重新提交',()=>createDesignRun(state.project.parts.length?'modify':'reconstruct',run.text||''),'quiet'));
  return card;
}
async function refreshDesignRun(){
  const projectId=state.project.id,revision=state.project.revision;
  const data=await api(base()+'/design-runs');if(state.project.id!==projectId||state.project.revision!==revision)return;
  const terminal=new Set(['completed','dismissed']);
  const run=data.active||(data.runs||[]).find(run=>run.base_revision===revision&&!terminal.has(run.status));
  const changed=JSON.stringify(run)!==JSON.stringify(state.designRun);state.designRun=run||null;
  if(run?.status==='ready'&&run.result_kind==='advice'){await loadFitComparison();}
  else if(run?.status==='ready'&&!state.proposal&&!state.dirtyForms&&run.proposal_id!==localStorage.getItem('junior-dismissed-'+projectId))await recoverProposal();
  if(changed&&!state.dirtyForms){if(run&&['waiting_for_session','running','needs_input'].includes(run.status)&&localStorage.getItem('junior-sidebar-open-v2')!=='closed')setPanel('tasks',true,{persist:false});render();}
}
function handoffCard() {
  const req=pendingRequest();if(!req)return null;
  const text='处理 Junior 项目“'+state.project.name+'”的请求，项目 ID：'+state.project.id+'，请求 ID：'+req.id+'。';
  return node('div',{class:'flow-status'},node('strong',{},'需求已保存 · 待当前聊天处理'),paragraph('把下面这句话发到 Codex 聊天。设计返回后，这里会显示模型和采用按钮。'),node('code',{class:'handoff-text'},'请继续处理「'+state.project.name+'」的'+({reference:'参考模型',fit:'尺寸调整',manufacturing:'加工方案'})[req.stage||'manufacturing']+'。'),button('复制给当前聊天',async()=>{await navigator.clipboard.writeText(text);notice('已复制，粘贴到当前聊天即可。');},'quiet'),button('检查是否有返回方案',refreshFromSession,'quiet',state.busy));
}
function render() {
  if(!state.project)return;
  const p=state.project, shown=displayProject(), preview=state.proposal?.status==='ready';
  const historyRevision=p.id+':'+p.revision;if(state.historyRevision!==historyRevision&&!state.historyNavigating){state.undoTargets=null;state.redoTargets=[];}state.historyRevision=historyRevision;
  const viewKey=JSON.stringify([p.id,shown.parts,shown.joints]);
  if(state.designViewKey!==viewKey){clearInspection(false);state.designViewKey=viewKey;}
  if(!shown.parts?.some(part=>part.id===state.selectedId))state.selectedId=null;
  document.getElementById('selection-label').textContent=shown.parts?.find(part=>part.id===state.selectedId)?.name||'尚未选择部件';
  $('project-name').value=p.name; const currentOption=[...$('project-switch').options].find(option=>option.value===p.id);if(currentOption)currentOption.textContent=p.name; $('save-state').textContent=state.busy?'正在处理…':'已保存到本机 · v'+p.revision;
  $('progress').textContent=tasks.filter(([id])=>taskDone(id)).length+' / '+tasks.length;
  $('empty-canvas').classList.toggle('hidden',!!(preview?state.proposal.patch?.parts||p.parts:p.parts)?.length);
  const hasReferences=(p.references?.length||0)>0;
  const hasModel=!!shown.parts?.length;
  document.body.classList.toggle('awaiting-model',!hasModel);
  $('quick-reference-title').textContent=hasReferences?'在这里复原你的椅子':'你想复刻哪件家具？';
  $('quick-reference-hint').textContent=hasReferences?'任务进度和需要补充的信息都在下方。模型返回后会直接出现在这里。':'带入成品参考，先原样复原出可编辑模型，再只改不适合你的地方。';
  $('quick-reference-form').hidden=hasReferences&&!hasModel;
  const sampleEntry=document.querySelector('.sample-entry');if(sampleEntry)sampleEntry.hidden=hasReferences;
  if(document.activeElement!==$('quick-reference-input'))$('quick-reference-input').value=state.referenceDraft;
  $('reference-receipts').replaceChildren(...(p.references||[]).map(ref=>node('div',{class:'reference-receipt-item'},node('span',{},({image:'图片',link:'链接',note:'说明',document:'PDF'})[ref.kind]||'图片'),node('strong',{},ref.name))));
  renderGenerationControls();
  renderGenerationConcept(hasReferences&&!hasModel);
  const handoff=$('generation-handoff');handoff.replaceChildren();
  $('canvas-title').textContent=preview?(p.parts?.length?'修改预览 · 等你决定':'第一版模型 · 等你决定'):hasModel?p.name:'参考与模型';
  $('canvas-status').textContent=preview?'预览中':activeRun()?.status==='running'?'正在处理设计':activeRun()?.status==='waiting_for_session'?'等待会话处理':hasModel?'设计中':hasReferences?'参考已保存':'等待参考';
  document.querySelectorAll('[data-flow]').forEach(el=>{el.disabled=!!state.proposal;el.setAttribute('aria-current',(state.activeTask==='confirm'?'make':state.activeTask)===el.dataset.flow?'step':'false');el.setAttribute('aria-description',taskAvailable(el.dataset.flow)?'':el.dataset.flow==='fit'?'需要先得到第一版模型':'需要先完成适己');});
  $('flow-drawings').disabled=!p.parts?.length;
  renderCandidateActions();
  $('package-button').disabled=!p.parts?.length;
  const unresolved=state.checks.filter(item=>item.severity==='blocker').length;$('package-button').textContent='加工包'+(unresolved?' · '+unresolved+' 项待处理':' ↗');
  $('undo').disabled=(state.undoTargets?state.undoTargets.length===0:state.versions.filter(version=>version.revision<p.revision).length===0)||preview;
  if($('redo'))$('redo').disabled=!state.redoTargets?.length||preview;
  document.querySelectorAll('[data-phase]').forEach(element=>{ const active=state.activeTask==='reference'?'reference':state.activeTask==='confirm'?'make':'design';element.classList.toggle('active',element.dataset.phase===active); });
  const viewportParts=shown.parts||[],viewportHardware=packagePreview()?.hardware_instances||[];
  const viewportKey=JSON.stringify([p.id,viewportParts,viewportHardware]);
  if(state.viewport&&state.viewportKey!==viewportKey){
    state.viewport.load(viewportParts,{hardware:viewportHardware});
    state.viewportKey=viewportKey;
  }
  state.viewport?.setSelection(state.selectedId);
  document.querySelectorAll('[data-tool]').forEach(element=>{element.disabled=!!state.proposal && ['translate','rotate','scale','mirror'].includes(element.dataset.tool);});
  if(state.proposal){state.viewport?.setTool('select');document.querySelectorAll('[data-tool]').forEach(element=>element.classList.toggle('active',element.dataset.tool==='select'));}
  renderTasks(); renderContext(); renderModelGuide(); renderShortcuts(); renderConversation();
  state.projectDetails[p.id]=p;state.projects=state.projects.map(item=>item.id===p.id?{...item,name:p.name,revision:p.revision,updated_at:p.updated_at}:item);persistDrafts();renderHome();syncPage();
  if(state.page==='package')renderPackagePage();
  renderDimensionLabels();
}
function renderDimensionLabels(){
  if(!state.viewport)return;
  const project=displayProject(),module=project?.modules?.[0],seat=project?.parts?.find(p=>p.kind==='seat_board');
  if(!seat||!module||state.page!=='design'||!(state.activeTask==='fit'||state.selectedId===seat.id)){state.viewport.setDimensions([]);return;}
  const [w,h,d]=seat.size_mm,[x,y,z]=seat.position_mm;
  const dimensions=[{key:'seat_width_mm',label:'座宽 '+Math.round(w)+' mm',start:[x-w/2,y+h/2+15,z+d/2+25],end:[x+w/2,y+h/2+15,z+d/2+25]},
    {key:'seat_depth_mm',label:'座板前后 '+Math.round(d)+' mm',start:[x+w/2+25,y+h/2+15,z-d/2],end:[x+w/2+25,y+h/2+15,z+d/2]},
    {key:'seat_height_mm',label:'座高 '+Math.round(state.viewport.seatSurfaceHeight(seat.id))+' mm',start:[x-w/2-35,0,z],end:[x-w/2-35,y+h/2,z]}];
  state.viewport.setDimensions(dimensions.map(item=>({...item,onEdit:event=>openDimensionEditor(module,item.key,event.currentTarget.getBoundingClientRect())})));
}
function openDimensionEditor(module,key,anchor=null){
  document.querySelector('.model-dimension-editor')?.remove();
  const item=state.fitComparison?.items?.find(item=>item.key===key),fallback=module.target?.[key]??0;
  const input=node('input',{type:'text',inputmode:'decimal',value:item?.current_value??fallback,'aria-label':item?.label||key});
  const error=node('p',{class:'entry-error',role:'alert'}),actions=node('div',{class:'action-row'});
  const editor=node('div',{class:'model-dimension-editor'},node('strong',{},item?.label||confirmationItems.find(i=>i[0]===key)?.[1]||key),input,error,actions);
  $('viewport').append(editor);if(anchor){const bounds=$('viewport').getBoundingClientRect();editor.style.left=Math.max(160,Math.min(bounds.width-160,anchor.left-bounds.left+anchor.width/2))+'px';editor.style.top=Math.max(20,Math.min(bounds.height-190,anchor.top-bounds.top-22))+'px';}let timer,redesign=false;
  const preview=async()=>{try{await previewDimension(module,key,input.value,key==='back_angle_deg'?'deg':'mm',redesign);error.textContent='预览中 · Enter 保存，Esc 取消';}catch(exc){error.textContent=exc.message;if(exc.detail?.can_redesign&&!redesign){actions.replaceChildren(button('保留原设计',cancel,'quiet'),button('作为改款预览',async()=>{redesign=true;actions.replaceChildren();await preview();},'quiet'));}else actions.replaceChildren();throw exc;}};
  const cancel=async()=>{clearTimeout(timer);state.dimensionToken=(state.dimensionToken||0)+1;editor.remove();state.dirtyForms=false;if(state.proposal?.dimensionEdit)await dismissProposal();else render();};
  const commit=async()=>{clearTimeout(timer);try{const value=parseQuantity(input.value,key==='back_angle_deg'?'deg':'mm');if(state.proposal?.dimensionEdit?.key!==key||state.proposal.dimensionEdit.value!==value)await preview();await acceptProposal();editor.remove();}catch(exc){error.textContent=exc.message;}};
  input.addEventListener('input',()=>{clearTimeout(timer);state.dirtyForms=true;timer=setTimeout(()=>preview().catch(()=>{}),400);});
  input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();commit();}if(event.key==='Escape'){event.preventDefault();cancel().catch(report);}});
  actions.append(button('取消',cancel,'quiet'),button('保存',commit,'primary'));input.focus();input.select();
}
function renderGenerationConcept(show) { $('generation-concept')?.replaceChildren(); }
function renderTasks() {
  if(!taskAvailable(state.activeTask))state.activeTask=taskDone('reference')?'fit':'reference';
  const list=$('task-list');list.replaceChildren();
  $('task-panel').classList.toggle('has-design',!!state.project.joints?.length);
  const current=tasks.find(([id])=>id===state.activeTask)||tasks[0];
  const card=node('section',{class:'active-task'});
  if(current[0]!=='fit')card.append(node('div',{class:'active-task-heading'},node('span',{class:'task-kicker'},current[1]),node('h2',{},current[2])));
  const body=node('div',{class:'task-body'});({reference:renderReferenceTask,fit:renderFitTask,make:renderMakeTask,confirm:renderConfirmTask})[current[0]](body);card.append(body);list.append(card);
  const taskViewKey=state.project.id+':'+state.activeTask+':'+(state.proposal?.id||'');if(state.taskViewKey!==taskViewKey){$('task-panel').scrollTop=0;state.taskViewKey=taskViewKey;}
}

function focusTask(id) { const part=state.project.parts?.find(part=>id==='fit'?part.kind==='seat_board':id==='make'?part.features?.length:true); if(part)state.viewport?.focus(part.id); }
function referenceVisualCard(ref) {
  const kind=ref.kind||'image',labels={image:'图片',link:'链接',note:'文字',document:'PDF'},card=node('article',{class:'reference-visual-card'});
  if(kind==='image'&&ref.url)card.append(node('img',{src:ref.url,alt:ref.name||'参考图片',loading:'lazy'}));
  else card.append(node('div',{class:'reference-visual-icon'},kind==='link'?'↗':kind==='document'?'▤':'✦'));
  const body=node('div',{},node('span',{class:'eyebrow'},labels[kind]||'参考'),node('strong',{},ref.name||'未命名参考'));
  if(ref.text)body.append(node('p',{},ref.text.length>110?ref.text.slice(0,110)+'…':ref.text));
  if(kind==='link')body.append(node('a',{href:ref.url,target:'_blank',rel:'noopener noreferrer'},'打开参考 ↗'));
  card.append(body);return card;
}
function renderReferenceTask(body) {
  const p=state.project,refs=p.references||[],pending=pendingRequest();
  const currentRun=runCard();if(currentRun)body.append(currentRun);
  if(!refs.length)body.append(paragraph('给我一个链接、一张图，或说说你想做什么。'));
  if(refs.length){
    body.append(node('section',{class:'reference-evidence'},node('div',{class:'reference-evidence-heading'},node('span',{class:'eyebrow'},'参考资料'),node('strong',{},'已收到 '+refs.length+' 项')),node('div',{class:'reference-evidence-grid'},refs.map(referenceVisualCard))));
    for(const ref of refs.filter(ref=>ref.kind==='link')){
      if(state.resolvingReference===ref.id)body.append(node('p',{class:'flow-status','role':'status'},'正在读取网页标题和文字…'));
      else if(state.referenceErrors[ref.id])body.append(node('div',{class:'flow-status error','role':'alert'},paragraph(state.referenceErrors[ref.id]),button('重新读取链接',()=>resolveReference(ref.id),'quiet')));
      else if(ref.text)body.append(node('details',{class:'reference-extract'},node('summary',{},'已读到网页文字 · 展开查看'),paragraph(ref.text)));
      else body.append(button('读取链接内容',()=>resolveReference(ref.id),'quiet',state.busy));
    }
  }
  if(state.proposal){body.append(paragraph('模型已显示在中央画布。先看它像不像，再在画布下方决定是否采用。'));return;}
  const editor=node('form',{class:'reference-entry','data-flow-draft':'reference'});
  const input=node('textarea',{'aria-label':'参考链接或想法',placeholder:'粘贴产品链接，或描述想做的椅子…',maxlength:6000},state.referenceDraft);
  input.addEventListener('input',()=>{state.referenceDraft=input.value;persistDrafts();});
  const error=node('p',{class:'entry-error',role:'alert'});
  const submit=node('button',{type:'submit',class:'primary',disabled:state.busy},refs.length?'添加参考':'带入参考 →');
  editor.append(input,node('div',{class:'action-row'},submit,button('图片 / PDF',()=>$('reference-input').click(),'quiet',state.busy)),error);
  editor.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{await saveReferenceText(input.value);if(!state.project.parts.length)await generateModel();}catch(exc){error.textContent=exc.message;}finally{submit.disabled=false;}});
  body.append(refs.length?node('details',{class:'optional-controls'},node('summary',{},'补充参考'),editor):editor);
  if(p.scope==='unsupported')body.append(node('div',{class:'issue'},p.scope_reason||'当前参考超出首版支持范围。'));
  if(activeRun())return;
  if(pending)body.append(handoffCard());
  if(pending&&!p.parts?.length)body.append(paragraph('已提交，等待模型返回。'));
  else if(!pending&&p.parts?.length){
    if(!p.baseline_revision){
      const versions=node('select',{'aria-label':'选择原版设计'},node('option',{value:''},'选择哪一版作为原版'),state.versions.map(v=>node('option',{value:v.revision},'v'+v.revision+(v.revision===p.revision?' · 当前设计':''))));
      body.append(paragraph('旧项目尚未设置原版。选择用于对照的版本，当前设计不会被替换。'),versions,button('设为原版并继续',async()=>{if(!versions.value)throw new Error('先选择原版设计版本。');await guarded(async()=>{state.project=await api(base()+'/baseline',json('POST',{expected_revision:state.project.revision,source_revision:Number(versions.value)}));await refreshData();state.activeTask='fit';render();});},'primary'));
    }else body.append(button('继续：适己 →',()=>goTask('fit'),'primary'));
  }
  else if(!pending&&refs.length)body.append(button('按参考复原',generateModel,'primary'));
}
function renderFitTask(body) {
  const p=state.project;
  const currentRun=runCard();if(currentRun)body.append(currentRun);
  if(!p.parts?.length){body.append(paragraph('先得到第一版模型，再来调整不适合你的地方。'),button('回到复原',()=>goTask('reference'),'primary'));return;}
  const shown=displayProject();
  const activeModule=(shown.modules||[]).find(module=>module.status!=='conflict'&&module.status!=='needs_review')||(shown.modules||[])[0];
  if(state.proposal&&!state.proposal.dimensionEdit){body.append(paragraph('画布正在预览调整，采用后继续。'));return;}
  if(activeModule)body.append(moduleFitCard(activeModule,shown));
  if(activeModule&&(!hasBodyData(activeModule)||editingModuleKey===moduleKey(activeModule)))return;
  if(!activeModule)body.append(node('div',{class:'fit-summary'},node('span',{class:'eyebrow'},'当前模型 · mm'),node('strong',{},'先看这版尺寸'),modelDimensionFacts()));
  if(state.proposal&&!state.proposal.dimensionEdit){body.append(paragraph('画布正在预览调整，采用后继续。'));return;}
  const pending=pendingRequest();
  if(pending)body.append(handoffCard());
  const form=node('form',{class:'fit-request','data-flow-draft':'fit'});
  form.append(node('label',{for:'fit-request-text'},'想怎么调整？'));
  const input=node('textarea',{id:'fit-request-text',placeholder:activeModule?'例如：坐高降低 20 mm，或告诉我谁来使用、要完成什么动作。':'例如：给身高120cm的孩子用，放在书桌前。也可以直接说座板宽度改为420mm。',maxlength:2000},state.fitDraft);
  input.addEventListener('input',()=>{state.fitDraft=input.value;persistDrafts();});
  const error=node('p',{class:'entry-error',role:'alert'}),submit=node('button',{type:'submit',class:'primary',disabled:state.busy},pending?'补充调整要求':'按这个要求调整');
  form.append(input,submit,error);
  form.addEventListener('submit',async event=>{event.preventDefault();const text=input.value.trim();if(!text){error.textContent='说说使用者、用途，或想改的尺寸。';return;}submit.disabled=true;try{await requestFit(text);}catch(exc){error.textContent=exc.message;}finally{submit.disabled=false;}});
  const optional=node('details',{class:'optional-controls'},node('summary',{},'还有其他想法？'),form);
  body.append(optional);
}
const anthropometryFields=[
  ['stature_mm','身高','站立时脚底到头顶'],
  ['sitting_height_mm','坐高','坐面到头顶'],
  ['hip_breadth_mm','臀宽','坐姿下臀部最宽处']
];
const postureOptions=[
  ['upright','正坐','身体直立，座面较平'],
  ['reclined','靠坐','背部有支撑，身体向后靠'],
  ['leaning','斜靠','更深后仰，偏休闲姿势'],
  ['cross_legged','盘腿','是否适合取决于原椅子的构造与可调范围']
];
const postureLabels=Object.fromEntries(postureOptions.map(([key,label])=>[key,label]));
let editingModuleKey=null;
const moduleKey=module=>state.project.id+':'+module.id;
function hasBodyData(module){const a=module.anthropometry||{};return a.measurement_source==='user_input'&&anthropometryFields.every(([key])=>Number(a[key])>0);}
const confirmationItems=[
  ['seat_height_mm','座高','结合身高、坐高和主要坐姿估算'],
  ['seat_depth_mm','座板前后长度','原椅子与实际座面关系'],
  ['seat_width_mm','座宽','结合臀宽和主要坐姿活动余量估算'],
  ['back_angle_deg','靠背角','当前模型目标；需要结合坐姿试靠确认']
];
function mmValue(value){return typeof value==='number'&&Number.isFinite(value)?Math.round(value):'';}
function displayUnitValue(value,unit){const mm=mmValue(value);return mm===''?'':unit==='cm'?(mm/10).toFixed(mm%10?1:0):String(mm);}
function unitToMm(value,unit){try{return parseQuantity(value,unit);}catch{return null;}}
async function confirmModuleTarget(module,key,rawValue,unit){
  const value=parseQuantity(rawValue,key==='back_angle_deg'?'deg':unit);
  if(!state.proposal?.dimensionEdit||state.proposal.dimensionEdit.key!==key||state.proposal.dimensionEdit.value!==value)await previewDimension(module,key,rawValue,unit);
  await acceptProposal();
}
async function previewDimension(module,key,rawValue,unit='mm',allowRedesign=false){
  const token=(state.dimensionToken||0)+1;state.dimensionToken=token;
  const value=parseQuantity(rawValue,key==='back_angle_deg'?'deg':unit),projectId=state.project.id,revision=state.project.revision;
  if(state.proposal&&!state.proposal.dimensionEdit)throw new Error('先采用或取消当前修改。');
  const proposal=await api(base()+'/modules/'+encodeURIComponent(module.id)+'/edit-preview',json('POST',{expected_revision:revision,key,value,decision:'custom',allow_redesign:allowRedesign}));
  if(token!==state.dimensionToken||state.project.id!==projectId||state.project.revision!==revision)return;
  proposal.dimensionEdit={moduleId:module.id,key,value};state.proposal=proposal;state.dirtyForms=false;
  state.viewport?.load(displayProject().parts,{hardware:proposal.package_preview?.hardware_instances||[]});
  // Manual preview changes the viewport; the next full render must reconcile it.
  state.viewportKey=null;
  renderCandidateActions();renderDimensionLabels();
  return proposal;
}
function normalizePosture(value){
  const aliases={坐姿:'upright',直坐:'upright',正坐:'upright',靠坐:'reclined',斜靠:'leaning',盘腿:'cross_legged'};
  return postureOptions.some(([key])=>key===value)?value:aliases[value]||'upright';
}
function estimatedAnthroValue(a,key){
  return a[key]||'';
}
async function saveAnthropometry(module,form){
  const unit=form.querySelector('[name="anthro-unit"]').value,values={...module.anthropometry,measurement_source:'user_input'};
  for(const [key,label] of anthropometryFields){
    const input=form.querySelector('[name="'+key+'"]');
    if(!input?.value.trim())throw new Error('请填写 '+label+'，三项数据都会用于生成建议。');
    const mm=unitToMm(input.value,unit);if(mm===null)throw new Error('请输入有效的 '+label+'。');values[key]=mm;
  }
  const posture=form.querySelector('[name="posture"]:checked')?.value||normalizePosture(module.posture);
  values.posture=posture;
  await guarded(async()=>{state.project=await api(base()+'/profile',json('POST',{expected_revision:state.project.revision,module_id:module.id,height_mm:values.stature_mm,sitting_height_mm:values.sitting_height_mm,hip_width_mm:values.hip_breadth_mm,posture}));state.dirtyForms=false;editingModuleKey=null;await refreshData();await loadFitComparison();render();});
  state.savedProfile={height_mm:values.stature_mm,sitting_height_mm:values.sitting_height_mm,hip_width_mm:values.hip_breadth_mm,posture};state.keptFitItems=new Set();
  await createDesignRun('modify','根据刚保存的三项身体数据和主要坐姿，对照原版基线，判断需要调整的项。通过 Module.suggestions 返回带依据与 anthropometry 快照的建议，不能直接修改当前几何；未知的范围保持未知。');
  notice('身体数据已保存，已请当前会话对照原椅子提出建议。');
}
const moduleBaseline={stature_mm:1830,sitting_height_mm:920,hip_breadth_mm:360};
function moduleHumanFigure(module){
  const a=module.anthropometry||{},unit='cm';
  const svg=svgNode('svg',{class:'module-human-svg',viewBox:'0 0 180 300',role:'img','aria-label':'柯布西耶模度人比例参考'},
    svgNode('path',{class:'module-human-grid',d:'M25 58h130M25 154h130M25 278h130'}),
    svgNode('circle',{class:'module-human-head',cx:'86',cy:'75',r:'15'}),
    svgNode('path',{class:'module-human-body',d:'M76 93 L63 105 L50 157 L55 160 L73 120 L71 165 L67 222 L59 274 L75 274 L88 186 L99 232 L111 274 L127 274 L112 216 L103 165 L103 105 L119 78 L125 20 L118 18 L109 72 L94 93 Z'}),
    svgNode('path',{class:'module-human-measure',d:'M30 60v218m-5-218h10m-10 218h10M67 165h40'}),
    svgNode('text',{class:'module-human-label',x:'38',y:'54'},'比例参考')
  );
  const fields=anthropometryFields.map(([key,label,hint])=>{
    const current=estimatedAnthroValue(a,key),baseline=moduleBaseline[key];
    return node('label',{class:'module-measurement'},node('span',{class:'module-measurement-top'},node('strong',{},label),node('small',{},'示例 '+displayUnitValue(baseline,unit)+' cm')),node('input',{type:'text',inputmode:'decimal',name:key,required:true,'aria-label':label,value:displayUnitValue(current,'cm'),placeholder:displayUnitValue(baseline,'cm')}),node('small',{},hint));
  });
  return node('div',{class:'module-human-layout'},node('div',{class:'module-human-figure'},svg,node('span',{class:'module-human-caption'},'模度人 · 参考比例')),node('div',{class:'module-measurements'},fields));
}
function anthropometryCard(module){
  if(!hasBodyData(module)&&state.savedProfile){const p=state.savedProfile;module={...module,posture:p.posture,anthropometry:{...module.anthropometry,stature_mm:p.height_mm,sitting_height_mm:p.sitting_height_mm,hip_breadth_mm:p.hip_width_mm}};}
  const a=module.anthropometry||{},form=node('form',{class:'anthropometry-card'});
  const unitSelect=node('select',{name:'anthro-unit','aria-label':'人体数据单位'},node('option',{value:'cm'},'cm'),node('option',{value:'mm'},'mm'));
  const heading=node('div',{class:'fit-card-heading'},node('span',{class:'fit-note'},state.savedProfile&&!hasBodyData(module)?'已带入本机档案，可修改后保存':'填写你的实际尺寸'),unitSelect);
  form.append(heading,moduleHumanFigure(module));
  const selected=normalizePosture(module.posture||a.posture);
  const postureHint=node('p',{class:'posture-hint'},postureOptions.find(([key])=>key===selected)[2]);
  const postureField=node('fieldset',{class:'posture-fieldset'},node('legend',{},'你主要怎么坐？'),node('div',{class:'posture-choices'},postureOptions.map(([key,label,hint])=>node('label',{class:'posture-choice'},node('input',{type:'radio',name:'posture',value:key,checked:selected===key,onChange:()=>{postureHint.textContent=hint;}}),node('strong',{},label)))),postureHint);
  unitSelect.addEventListener('change',()=>{
    const next=unitSelect.value,previous=next==='cm'?'mm':'cm';
    for(const [key] of anthropometryFields){const input=form.querySelector('[name="'+key+'"]');input.placeholder=displayUnitValue(moduleBaseline[key],next);if(!input.value)continue;const mm=unitToMm(input.value,previous);if(mm!==null)input.value=displayUnitValue(mm,next);}
  });
  const error=node('p',{class:'entry-error',role:'alert'}),submit=node('button',{type:'submit',class:'primary',disabled:state.busy},'保存，查看尺寸建议 →');
  form.append(postureField,error,submit);
  form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{await saveAnthropometry(module,form);}catch(exc){error.textContent=exc.message;}finally{submit.disabled=false;}});
  return form;
}
function moduleFitCard(module,project) {
  const anthropometry=module.anthropometry||{},posture=normalizePosture(module.posture||anthropometry.posture);
  const editing=!hasBodyData(module)||editingModuleKey===moduleKey(module);
  const heading=node('div',{class:'module-page-heading'},node('span',{class:'eyebrow'},'MODULE'),node('h2',{},editing?'把模度人改成你':'只调整需要改变的地方'));
  if(editing)return node('section',{class:'module-page','data-module-stage':'body'},heading,anthropometryCard(module),button('不填，保持原样继续',acceptCurrentDimensions,'quiet'));
  const profile=node('div',{class:'module-profile-summary'},node('span',{},anthropometryFields.map(([key,label])=>label+' '+displayUnitValue(anthropometry[key],'cm')).join(' · ')+' cm · '+postureLabels[posture]),button('修改身体数据',()=>{editingModuleKey=moduleKey(module);renderTasks();$('task-panel').scrollTop=0;},'quiet'));
  const comparison=state.fitComparison?.revision===state.project.revision?state.fitComparison:null;
  const page=node('section',{class:'module-page module-complete'},profile);
  if(!comparison){page.append(paragraph(state.fitComparisonError||'正在对照原椅子…'),button('重新比较',async()=>{await loadFitComparison();renderTasks();},'quiet'));return page;}
  const suggestions=(comparison.items||[]).filter(item=>['suggested','conflict'].includes(item.status)&&module.decisions?.[item.key]!=='keep');
  const item=suggestions[0];
  if(item){
    const input=node('input',{type:'text',inputmode:'decimal',value:item.suggested_value??item.current_value,'aria-label':item.label+'数值'}),error=node('p',{class:'entry-error',role:'alert'});
    let timer;input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>previewDimension(module,item.key,input.value,item.unit==='deg'?'deg':'mm').then(()=>error.textContent='').catch(e=>error.textContent=e.message),400);});
    const commit=async()=>{clearTimeout(timer);await confirmModuleTarget(module,item.key,input.value,item.unit==='deg'?'deg':'mm');};
    input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();commit().catch(report);}if(event.key==='Escape'){clearTimeout(timer);dismissProposal().catch(report);}});
    page.append(node('section',{class:'fit-decision'},node('span',{class:'eyebrow'},'待处理 '+suggestions.length+' 项'),node('h3',{},item.label),paragraph(item.reason),node('label',{class:'dimension-control'},'当前 '+item.current_value+(item.unit==='deg'?'°':' mm'),input),error,node('div',{class:'action-row'},button('保持原样',async()=>{if(state.proposal?.dimensionEdit)await dismissProposal();await mutate({modules:(comparison.advice_modules||state.project.modules).map(m=>m.id===module.id?{...m,decisions:{...m.decisions,[item.key]:'keep'}}:m)});},'quiet'),button('下一个 →',commit,'primary'))));
  }else page.append(paragraph(activeRun()&&['waiting_for_session','running'].includes(activeRun().status)?'正在等待有依据的调整建议，当前模型保持原样。':comparison.summary||'根据现有数据，暂不建议自动调整。你仍可点击模型尺寸修改。'),button('保持当前设计，继续 →',acceptCurrentDimensions,'primary'));
  const details=node('details',{class:'optional-controls'},node('summary',{},'尺寸与依据'));
  for(const row of comparison.items||[])details.append(node('div',{class:'fit-evidence-row'},node('strong',{},row.label+' · '+row.current_value+(row.unit==='deg'?'°':' mm')),node('small',{},row.reason),button('在模型上调整',()=>openDimensionEditor(module,row.key),'quiet',!row.editable)));
  page.append(details);
  return page;
}
async function loadFitComparison(){
  const module=state.project?.modules?.[0];state.fitComparison=null;state.fitComparisonError='';if(!module)return;
  const projectId=state.project.id,revision=state.project.revision;
  try{const result=await api(base()+'/modules/'+encodeURIComponent(module.id)+'/comparison');if(state.project.id===projectId&&state.project.revision===revision)state.fitComparison=result;}
  catch(error){state.fitComparisonError=error.message;}
}
function modelDimensionFacts() {
  const parts=displayProject().parts||[],seat=parts.filter(p=>p.kind==='seat_board'),facts=[];
  if(seat.length===1){facts.push(['座板宽',seat[0].size_mm[0]],['座板深',seat[0].size_mm[2]]);const height=state.viewport?.seatSurfaceHeight(seat[0].id);if(Number.isFinite(height))facts.push(['座面中心高',height]);}
  const host=node('div',{class:'dimension-facts'});
  if(facts.length)host.append(...facts.map(([label,number])=>node('div',{},node('small',{},label),node('strong',{},Math.round(number)))));
  else host.append(paragraph('当前方案包含 '+parts.length+' 个零件。点选模型可以查看每件尺寸。'));
  return host;
}
async function acceptCurrentDimensions() {
  requireNoProposal();if(state.fitDraft.trim())throw new Error('先提交调整要求，或清空输入后沿用当前尺寸。');
  const p=state.project;if(!p.parts?.length)throw new Error('先形成参考模型。');
  state.dirtyForms=false;
  goTask('make');
}
async function requestFit(text) {
  await createDesignRun('modify',text+'。结合个人数据与原版基线，通过 Module.suggestions 返回有依据的最小必要调整建议，不直接替换模型。');state.fitDraft='';persistDrafts();render();
}
function proposalImportControl() {
  return node('details',{class:'optional-controls'},node('summary',{},'其他操作'),button('导入设计候选',chooseProposalFile,'',!!state.proposal));
}
function conditionSummary(project=displayProject()) {
  const req=project.requirements||{},rows=[
    ['设计依据',(project.references?.length||0)+' 项参考 · '+(project.parts?.length||0)+' 个部件'],
    ['目标尺寸',project.scale?.note||'采用当前模型尺寸'],
    ['使用条件',[req.load_kg?req.load_kg+' kg 目标载荷':null,({indoor:'室内',outdoor:'室外'})[req.environment]||req.environment,req.body_height_mm?'身高记录 '+req.body_height_mm+' mm':null].filter(Boolean).join(' · ')||'未记录'],
    ['加工路径',({self:'自己加工',kit:'加工店下料/打孔，自己装配',shop:'加工店制件，自己装配'})[project.fabrication_mode]||'未记录'],
    ['工具 / 限制',[...(req.tools||[]),req.notes].filter(Boolean).join('；')||'未记录额外限制']
  ];
  return node('div',{class:'condition-summary'},node('span',{class:'eyebrow'},'当前设计条件'),rows.map(([label,text])=>node('div',{class:'condition-row'},node('span',{},label),node('strong',{},text))));
}
async function answerPreparation(key,answer) {
  const normalized=key.replace(/^requirements\./,'');
  const patch=normalized==='fabrication_mode'?{fabrication_mode:answer}:{requirements:{...state.project.requirements,[normalized]:answer}};
  const current=state.activeTask;await mutate(patch,false);state.activeTask=current==='make'?'make':'confirm';renderTasks();focusTask(state.activeTask);
}
function renderQuestion(body,question) {
  if(!question)return;
  const card=node('div',{class:'key-question'},node('small',{},'补充使用条件'),node('h3',{},question.label));
  const key=question.key.replace(/^requirements\./,'');
  const options=question.options|| (key==='fabrication_mode'?[['self','自己加工'],['kit','加工店下料/打孔，我装配'],['shop','加工店制件，我来装配']]:key==='environment'?[['indoor','室内'],['outdoor','室外']]:null);
  if(options)card.append(node('div',{class:'choice-stack'},options.map(option=>{const val=Array.isArray(option)?option[0]:option.value,label=Array.isArray(option)?option[1]:option.label;return button(label,()=>answerPreparation(question.key,val),'',!!state.proposal);} )));
  else {
    const form=node('div',{},field(key==='load_kg'?'预计最大使用载荷 kg':'补充条件','answer','',key==='load_kg'?'number':'text'));
    form.append(button('记住这个条件，继续',()=>{const answer=key==='load_kg'?number(form,'answer'):value(form,'answer').trim();if(key==='load_kg' && !(answer>0&&answer<=500))throw new Error('请填写 0 到 500 kg 之间的目标载荷。');if(!answer)throw new Error('请补充这个条件。');return answerPreparation(question.key,answer);},'primary',!!state.proposal));card.append(form);
  }
  body.append(card);
}
function renderMakeTask(body) {
  const p=state.project,currentRun=runCard();if(currentRun)body.append(currentRun);
  if(state.proposal){body.append(paragraph('修改已显示在模型上，采用后继续。'));return;}
  const mode=field('由谁加工','fabrication_mode',p.fabrication_mode||'shop','text',[['shop','加工店制件，自己装配'],['kit','加工店下料/打孔，我装配'],['self','自己加工']]);
  mode.querySelector('select').addEventListener('change',event=>mutate({fabrication_mode:event.target.value}).catch(report));body.append(mode);
  const part=p.parts.find(part=>part.id===state.selectedId)||p.parts.find(part=>part.kind==='seat_board')||p.parts[0];
  if(part){
    const select=node('select',{'aria-label':'选择修改部件'},p.parts.map(item=>node('option',{value:item.id,selected:item.id===part.id},item.name)));
    select.addEventListener('change',()=>{state.selectedId=select.value;state.viewport?.setSelection(select.value);renderTasks();renderDimensionLabels();});body.append(select);
    const material=p.materials[part.material_id],materialName=node('input',{value:material?.name||'','aria-label':'材料名称'});
    const thickness=node('input',{type:'text',inputmode:'decimal',value:part.size_mm[1],'aria-label':'板材厚度'});
    const form=node('form',{'data-flow-draft':'methods',class:'method-editor'},node('label',{class:'field'},'材料',materialName),node('label',{class:'field'},'板厚 · mm',thickness));
    const error=node('p',{class:'entry-error',role:'alert'}),submit=node('button',{type:'submit',class:'primary'},'预览做法调整');
    form.append(error,submit);form.addEventListener('submit',async event=>{event.preventDefault();try{const value=parseQuantity(thickness.value);await createDesignRun('modify','修改部件 '+part.id+'（'+part.name+'）的材料为 '+materialName.value+'，板厚为 '+value+' mm。保留原设计关系，联动重建孔位、连接和五金，检查后返回预览。');}catch(exc){error.textContent=exc.message;}});body.append(form);
    const joint=p.joints.find(j=>j.part_ids.includes(part.id));
    if(joint)body.append(node('div',{class:'method-connection'},node('strong',{},jointName(joint)),paragraph(joint.assembly_note||'沿用当前连接'),button('在模型中查看',()=>inspectJoint(joint.id),'quiet'),button('调整连接方式',()=>createDesignRun('modify','为 '+jointName(joint)+' 提出受支持的替代连接方案，说明外观和拆装差异，需要取舍时先询问用户。'),'quiet')));
  }
  body.append(button('沿用当前做法，生成加工包 →',enterPackageFlow,'primary',state.busy));
}
async function requestPreparation(text='',stage='manufacturing') {
  await createDesignRun(stage==='reference'?'reconstruct':'modify',text||'检查当前做法，补齐有依据的材料、连接与加工方案。');
}
function partName(id) { return (displayProject().parts||[]).find(part=>part.id===id)?.name||id; }
function jointName(joint) { return joint.name||(joint.part_ids||[]).map(partName).join(' ↔ '); }
function packagePreview() {
  if(state.proposal)return state.proposal.package_preview;
  const pkg=state.preparation?.package_preview;
  return pkg?.revision===state.project?.revision?pkg:null;
}
function showList(mode) {showPage('design');setPanel('context',true);clearInspection(false);state.tab='lists';state.listMode=mode;renderContext();}
function clearInspection(redraw=true) {const prior=state.inspectionReturn;state.inspectionReturn=null;state.inspectedJointId=null;state.viewport?.setExploded(false);state.viewport?.clearInspection();if(prior){state.selectedId=prior.selectedId;state.viewport?.setSelection(prior.selectedId);state.viewport?.restoreView(prior.view);}$('selection-label').textContent=displayProject()?.parts?.find(p=>p.id===state.selectedId)?.name||'尚未选择部件';renderModelGuide();if(redraw)renderContext();}
function inspectJoint(id) {
  showPage('design');
  const joint=(displayProject().joints||[]).find(item=>item.id===id);if(!joint)return;state.conversationOpen=false;renderConversation();
  state.inspectionReturn=state.inspectionReturn||{selectedId:state.selectedId,view:state.viewport?.captureView?.()};
  state.selectedId=joint.part_ids[0];state.viewport?.setSelection(state.selectedId);$('selection-label').textContent=jointName(joint);state.inspectedJointId=id;
  state.viewport?.setTool('select');document.querySelectorAll('[data-tool]').forEach(el=>el.classList.toggle('active',el.dataset.tool==='select'));
  state.viewport?.setExploded(false);state.viewport?.highlightParts?.(joint.part_ids);renderModelGuide();
}
function renderModelGuide() {
  const host=$('model-guide');host.replaceChildren();renderShortcuts();
  const show=state.page==='design'&&!state.sidebarOpen&&!state.conversationOpen&&!!state.project?.parts?.length;host.classList.toggle('hidden',!show);if(!show)return;
  const task=tasks.find(([id])=>id===state.activeTask);
  host.append(node('div',{class:'guide-copy'},node('strong',{},state.inspectedJointId?'已定位相关连接':task?.[2]||'继续设计')),button('打开当前步骤',()=>{setPanel('tasks',true);render();},'primary'));
  if(state.inspectedJointId)host.append(button('返回原视角',()=>clearInspection(),'quiet'));
}
function renderShortcuts() {
  const host=$('command-suggestions');if(!host)return;host.replaceChildren();
  $('command-input').placeholder=state.inspectedJointId?'这处连接，你想怎么改？':'告诉我怎么改，例如：座板宽度改为420mm';
}
function renderPlanPreview(body,pkg) {
  const p=displayProject(),parts=p.parts||[],hardware=pkg?.hardware||[];
  const facts=node('div',{class:'design-facts'});
  const boards=button('',()=>showList('cut'),'fact-link',!parts.length);boards.setAttribute('aria-label','查看下料清单');
  boards.append(node('span',{class:'fact-icon','aria-hidden':'true'},'▱'),node('strong',{},parts.length),node('span',{},'板件'));
  const fasteners=button('',()=>showList('hardware'),'fact-link',!hardware.length);fasteners.setAttribute('aria-label','查看五金清单');
  fasteners.append(hardwareGlyph({geometry:{kind:'bolt'}}),node('strong',{},hardware.reduce((sum,item)=>sum+item.quantity,0)),node('span',{},'五金'));
  facts.append(boards,fasteners);body.append(facts);
}
function renderConfirmTask(body) { renderReview(body); }
function renderReview(content) {
  if(state.checksError){content.append(paragraph('检查暂时未完成，请重试。'),button('重新检查',async()=>{await refreshData();renderContext();}));return;}
  if(displayChecks().some(check=>check.code==='scale_unconfirmed'&&check.severity==='blocker')){renderScaleAnchor(content);return;}
  const editPart=id=>{clearInspection(false);state.selectedId=id;state.viewport?.focus(id);state.tab='layers';setPanel('context',true);renderContext();};
  renderReviewFlow(content,{
    project:state.project,checks:displayChecks(),coverage:displayCoverage(),packagePreview:packagePreview(),busy:state.busy||!!state.proposal,
    onInspect:({partIds,jointId})=>jointId?inspectJoint(jointId):editPart(partIds[0]),
    onEditPart:editPart,onReturnToFit:()=>goTask('fit'),
    onResolve:check=>requestPreparation('请解决当前检查问题：'+(check?.message||'补齐设计信息')).catch(report),
    onRefresh:async()=>{await refreshData();renderContext();},
    onAcceptJoint:async jointId=>{requireNoProposal();await guarded(async()=>{state.project=await api(base()+'/joints/'+encodeURIComponent(jointId)+'/accept',json('POST',{expected_revision:state.project.revision}));state.dirtyForms=false;await refreshData();render();});},
    onConfirmPackage:openPackage
  });
}

function renderScaleAnchor(host){
  const input=node('input',{type:'text',inputmode:'decimal','aria-label':'参考中的实测尺寸',placeholder:'例如 400 mm'}),note=node('input',{type:'text','aria-label':'尺寸依据',placeholder:'这个尺寸来自哪里、对应哪里？'}),error=node('p',{class:'entry-error',role:'alert'});
  host.append(node('h3',{},'补充一个有依据的尺寸'),paragraph('填写参考图纸、产品说明或实际测量中的尺寸。程序会核对它与模型是否一致。'),input,note,error,button('保存尺寸依据',async()=>{try{state.project=await api(base()+'/scale-anchor',json('POST',{expected_revision:state.project.revision,length_mm:parseQuantity(input.value),note:note.value.trim()}));state.dirtyForms=false;await refreshData();render();}catch(exc){error.textContent=exc.message;}},'primary'));
}

async function refreshFromSession() {
  if(state.busy||state.proposal||state.dirtyForms||!state.project)return;
  await guarded(async()=>{const current=await api(base());state.project=current;await refreshData();await recoverProposal();await refreshDesignRun();render();});
}
function issueCard(check) {return node('div',{class:'issue '+(check.severity==='blocker'?'':check.severity==='warning'?'warning':'pass')},node('strong',{},check.severity==='blocker'?'设计检查':check.severity==='warning'?'提醒':'已记录'),check.message,(check.part_ids||[]).map(id=>button('定位 '+partName(id),()=>{clearInspection(false);state.selectedId=id;state.viewport?.focus(id);state.tab='layers';setPanel('context',true);renderContext();})));}
function renderGenerationControls() {
  const start=$('empty-reference-start');start.disabled=state.busy||state.generating||!!state.proposal||(!state.referenceDraft.trim()&&!state.project?.references?.length);
  start.textContent=state.generating?'正在提交…':activeRun()?'已提交，等待当前会话':'提交给当前聊天处理 →';
  $('quick-reference-error').textContent=state.generationError;$('ai-settings').textContent='设置';
}
function renderCandidateActions() {
  const host=$('candidate-actions'),p=state.proposal;host.replaceChildren();host.hidden=p?.status!=='ready'||!!p?.dimensionEdit;if(host.hidden)return;
  const first=!state.project.parts?.length,conflict=p.preservation_conflict;
  host.append(node('div',{},node('strong',{},first?'这是你想复原的椅子吗？':conflict?'这项修改会改变原设计':'修改预览'),node('small',{},conflict||p.summary||'在模型上查看变化')));
  if(conflict)host.append(button('作为改款预览',async()=>{state.proposal=await api(base()+'/proposal/'+p.id+'/redesign',json('POST',{expected_revision:state.project.revision}));render();},'primary',state.busy));
  else host.append(button(first?'继续 →':'采用修改',acceptProposal,'primary',state.busy));
  host.append(button(first?'哪里不像':'取消',async()=>{await dismissProposal();if(first){state.activeTask='reference';state.referenceDraft='这版与参考不同的地方是：';setPanel('tasks',true);renderTasks();const details=$('task-list').querySelector('.optional-controls');if(details)details.open=true;$('task-list').querySelector('textarea')?.focus();}},'quiet',state.busy));
}
async function beginGeneration() {
  try {if(state.referenceDraft.trim())await saveReferenceText(state.referenceDraft);await generateModel();}
  catch(error){state.generationError=error.message;render();}
}
async function generateModel(){
  if(!state.project.references?.length)throw new Error('先添加图片、链接或文字参考。');
  await createDesignRun('reconstruct','根据已提供参考复原椅子，保留形态、比例与结构，给出默认做法及有依据的保型关系。');
}
async function runAnalysis(){return beginGeneration();}
async function openCafeDemo() {
  if(state.busy||state.dirtyForms)throw new Error('请先保存正在编辑的条件。');persistDrafts();
  await guarded(async()=>{
    const result=await api('/demos/cafe-chair',{method:'POST'});
    state.project=result.project;state.referenceDraft='';state.fitDraft='';state.commandDraft='';$('command-input').value='';showPage('design');state.proposal=result.proposal;state.selectedId=null;state.activeTask='reference';state.generationError='';state.conversationOpen=false;
    localStorage.setItem('junior-project-id',state.project.id);
    await listProjects();await refreshData();setPanel('tasks',false);render();
  });
}
async function openAiSettings() {
  state.aiStatus=await api('/ai/status');
  const status=state.aiStatus,host=$('ai-settings-content');host.replaceChildren();
  host.append(node('p',{},'当前通道：'+status.label),node('h3',{},'会话协作 · 无需密钥'),paragraph('提交后，把交接文字发给当前聊天。聊天返回模型后，页面会显示出来。网页不会自动调用这段聊天。'),node('h3',{},'样例体验 · 立即看到模型'),paragraph('使用首页的“体验 CAFE CHAIR 样例”，新建独立项目体验编辑、检查和图纸。不会声称识别了你的参考。'),node('h3',{},'在线 AI · 自动生成'),paragraph('在项目目录的 .env 中填写以下配置；使用支持图片和 JSON 输出的模型。密钥只存服务端，不填入网页。'),node('pre',{class:'setup-code'},'CREATE_JUNIOR_AI_PROVIDER=openai_compatible\nCREATE_JUNIOR_AI_BASE_URL=https://你的服务地址/v1\nCREATE_JUNIOR_AI_API_KEY=你的密钥\nCREATE_JUNIOR_AI_MODEL=服务商提供的视觉模型名称'),paragraph('保存后重启本地服务：'),node('pre',{class:'setup-code'},'uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file .env'),paragraph('填写状态：'+Object.entries(status.configured).map(([key,ok])=>key+' '+(ok?'已填写':'未填写')).join(' · ')));
  $('ai-dialog').showModal();renderGenerationControls();
}
async function acceptProposal() {
  const proposal=state.proposal;if(!proposal)return;
  if(proposal.base_revision!==state.project.revision)throw new Error('这版修改基于旧版本，不能用于当前设计；请取消后重新生成。');
  if(proposal.local){await mutate(proposal.patch,false,proposal.base_revision);return;}
  const first=!state.project.parts.length;
  await guarded(async()=>{state.project=await api(base()+'/proposal/accept',json('POST',{expected_revision:state.project.revision,proposal_id:proposal.id,accept_connections:true}));state.proposal=null;state.dirtyForms=false;if(first){state.project=await api(base()+'/baseline',json('POST',{expected_revision:state.project.revision}));state.activeTask='fit';setPanel('tasks',true);}await refreshData();render();});
}
async function stagePatch(patch,summary) {
  if(state.busy || state.proposal){notice(state.busy?'正在保存，请稍候。':'请先采用或取消当前修改。');render();return;}
  try {
    await guarded(async()=>{
      state.proposal=await api(base()+'/proposal/import',json('POST',{expected_revision:state.project.revision,summary,patch,purpose:'design'}));
      state.dirtyForms=false;render();
    });
  } catch(error) {render();throw error;}
}
function requireReferenceEdit() {requireNoProposal();if(state.busy)throw new Error('正在保存，请稍后再试。');if(state.dirtyForms)throw new Error('先保存正在编辑的条件，再添加参考。');}
async function uploadFiles(files) {
  requireReferenceEdit();
  const refs=state.project.references||[],types=['image/jpeg','image/png','image/webp','application/pdf'];
  if(refs.length+files.length>20)throw new Error('每个项目最多保存20项参考。');
  if(refs.filter(r=>(r.kind||'image')==='image').length+files.filter(f=>f.type!=='application/pdf').length>8)throw new Error('每个项目最多保存8张图片。');
  if(files.some(file=>file.size>10*1024*1024))throw new Error('每份文件最多10 MB。');
  if(files.some(file=>!types.includes(file.type)))throw new Error('支持 JPG、PNG、WebP 和 PDF。');
  await guarded(async()=>{for(const file of files)state.project=await api(base()+'/references?filename='+encodeURIComponent(file.name),{method:'POST',headers:{'content-type':file.type},body:file});state.proposal=null;state.dirtyForms=false;await refreshData();state.activeTask='reference';state.tab='references';state.conversationOpen=false;render();});
  if(!state.project.parts.length)await generateModel();
}
function openReferenceComposer(initial='') {
  requireNoProposal();$('reference-text').value=initial;$('reference-error').textContent='';$('reference-dialog').showModal();$('reference-text').focus();
}
async function saveReferenceText(text) {
  requireReferenceEdit();text=text.trim();if(!text)throw new Error('粘贴一个链接，或写下参考说明。');
  const linkMatch=/(?:^|\s)(https?:\/\/\S+)(?=\s|$)/i.exec(text),url=linkMatch?.[1];
  const isLink=!!url,note=isLink?(text.slice(0,linkMatch.index)+text.slice(linkMatch.index+linkMatch[0].length)).trim():text;
  if(/^[a-z][a-z0-9+.-]*:\/\//i.test(text)&&!isLink)throw new Error('链接请使用完整的 http 或 https 地址。');
  if(state.project.references.length+(isLink&&note?2:1)>20)throw new Error('每个项目最多保存 20 条参考资料，链接与制作想法会分别保存。');
  let added;
  await guarded(async()=>{
    state.project=await api(base()+'/references/item',json('POST',{expected_revision:state.project.revision,kind:isLink?'link':'note',...(isLink?{url}:{text:note})}));
    added=state.project.references.at(-1);
    // Link resolution replaces extracted page text, so keep the user's own idea
    // as a separate note that remains intact when the page is read again.
    if(isLink&&note)state.project=await api(base()+'/references/item',json('POST',{expected_revision:state.project.revision,kind:'note',name:'制作想法',text:note}));
    state.referenceDraft='';state.dirtyForms=false;state.conversationOpen=false;await refreshData();state.activeTask='reference';setPanel('tasks',!!state.project.parts?.length,{persist:false});render();
  });
  render();
  if(isLink&&added)await resolveReference(added.id);
  return isLink?'链接已保存，读取结果在当前参考任务中。':'参考说明已保存，下一步在当前任务中。';
}
async function resolveReference(id) {
  requireReferenceEdit();state.resolvingReference=id;delete state.referenceErrors[id];renderTasks();
  try {await guarded(async()=>{state.project=await api(base()+'/references/'+encodeURIComponent(id)+'/resolve',json('POST',{expected_revision:state.project.revision}));await refreshData();});}
  catch(error){state.referenceErrors[id]=error.message;}
  finally{state.resolvingReference=null;render();}
}
function referenceCard(ref) {
  const kind=ref.kind||'image',card=node('article',{class:'reference-card'});
  if(kind==='image'){const preview=button('',()=>previewReference(ref),'reference-thumb');preview.append(node('img',{src:ref.url,alt:ref.name,loading:'lazy'}),node('small',{},ref.name));card.append(preview);}
  else if(kind==='link'){card.append(node('span',{class:'eyebrow'},'产品链接'),node('a',{href:ref.url,target:'_blank',rel:'noopener noreferrer'},ref.name||ref.url),node('small',{},ref.url));if(ref.text)card.append(paragraph(ref.text));}
  else if(kind==='document')card.append(node('span',{class:'eyebrow'},'PDF 图纸 / 资料'),button(ref.name+' ↗',()=>previewReference(ref),'quiet'));
  else card.append(node('span',{class:'eyebrow'},'文字参考'),node('details',{},node('summary',{},ref.name||'参考说明'),paragraph(ref.text)));
  return card;
}
function previewReference(ref) {
  const host=$('reference-preview-content');host.replaceChildren();$('reference-preview-title').textContent=ref.name;
  if((ref.kind||'image')==='image')host.append(node('img',{src:ref.url,alt:ref.name}));
  else host.append(node('iframe',{src:ref.url,title:ref.name}),node('a',{href:ref.url,target:'_blank',rel:'noopener noreferrer'},'单独打开 PDF ↗'));
  $('reference-preview').showModal();
}
function renderContext() {
  if(!state.project)return;
  syncSidebar();
  const content=$('context-content');content.replaceChildren();
  ({references:renderReferences,versions:renderVersions,layers:renderLayers,lists:renderLists})[state.tab](content);
}
function renderReferences(content) {
  const p=state.project;
  content.append(node('h3',{},'参考资料'));
  content.append(node('div',{class:'reference-grid'},(p.references||[]).map(referenceCard)),button('+ 链接或文字',()=>openReferenceComposer(),'add-reference'),button('+ 图片 / PDF',()=>$('reference-input').click(),'add-reference'),proposalImportControl());
  const evidence=state.proposal?.patch?.evidence || p.evidence || [];
  if(evidence.length)content.append(node('details',{class:'optional-controls'},node('summary',{},'参考记录'),evidence.map(item=>node('div',{class:'evidence '+(item.status==='unknown'?'unknown':'')},node('small',{},({observed:'图中观察',inferred:'推测',unknown:'未知',adopted:'采用的设计'})[item.status]||item.status),item.statement))));
  const assumptions=displayProject().assumptions||[];if(assumptions.length)content.append(node('details',{class:'optional-controls'},node('summary',{},'设计假设'),assumptions.map(assumption=>paragraph(assumption))));
}
function renderVersions(content) {
  content.append(node('h3',{},'设计版本'),paragraph('修改会保存新版本，旧确认不会沿用。恢复也会创建新版本。'));
  for(const version of [...state.versions].sort((a,b)=>b.revision-a.revision))content.append(node('div',{class:'version-card'},node('strong',{},'v'+version.revision+' · '+(version.name||state.project.name)),node('small',{},version.confirmed?'已确认快照':'设计草稿'),version.revision===state.project.revision?node('span',{class:'tag'},'当前'):button('恢复此版本',()=>restoreVersion(version.revision))));
}
async function restoreVersion(revision) {await guarded(async()=>{state.project=await api(base()+'/restore/'+revision,json('POST',{expected_revision:state.project.revision}));state.proposal=null;await refreshData();render();notice('已恢复为新的设计版本。');});}
function selectPart(id,{focus=false}={}) {
  clearInspection(false);state.selectedId=id;state.viewport?.setSelection(id);
  const part=displayProject()?.parts?.find(part=>part.id===id);
  $('selection-label').textContent=part?.name||'尚未选择部件';
  if(part){state.tab='layers';if(focus)state.viewport?.focus(id);}
  renderContext();renderDimensionLabels();
}
function renderLayers(content) {
  const project=displayProject(),parts=project.parts||[],part=parts.find(item=>item.id===state.selectedId);
  if(!parts.length){content.append(node('div',{class:'empty-note'},'有了第一版模型后，部件会出现在这里。'));return;}
  if(part){
    const inspector=node('section',{class:'part-inspector','aria-label':'选中部件属性'});
    inspector.append(node('span',{class:'eyebrow'},'选中部件'),node('h2',{},part.name),node('div',{class:'spec-chips'},node('span',{class:'chip'},project.materials?.[part.material_id]?.name||'材料'),node('span',{class:'chip'},(part.features?.length||0)+' 处加工')));
    inspector.append(node('div',{class:'action-row'},button('定位部件',()=>state.viewport?.focus(part.id)),button('零件图 ↗',()=>openDrawing(part.id),'',!packagePreview()?.drawings?.some(sheet=>sheet.part_id===part.id))));
    if(!state.proposal){
      const form=node('div',{class:'property-form'});
      form.append(node('span',{class:'hint'},'尺寸 · mm'),node('div',{class:'field-row'},['X','Y','Z'].map((axis,index)=>field(axis,'size'+index,part.size_mm[index],'number'))));
      const advanced=node('details',{class:'optional-controls'},node('summary',{},'位置与旋转'));
      for(const [title,prefix,values] of [['位置 mm','position',part.position_mm],['旋转 °','rotation',part.rotation_deg]])advanced.append(node('span',{class:'hint'},title),node('div',{class:'field-row'},['X','Y','Z'].map((axis,index)=>field(axis,prefix+index,values[index],'number'))));
      form.append(advanced,button('预览修改',()=>{const changed=clone(part);changed.size_mm=[0,1,2].map(i=>number(form,'size'+i));changed.position_mm=[0,1,2].map(i=>number(form,'position'+i));changed.rotation_deg=[0,1,2].map(i=>number(form,'rotation'+i));if(changed.size_mm.some(n=>!(n>0)))throw new Error('部件尺寸必须大于 0。');return stagePatch({parts:parts.map(item=>item.id===part.id?changed:item)},'修改 '+part.name+' 的尺寸或位置');},'primary'));
      inspector.append(form);
    } else inspector.append(node('span',{class:'tag'},'修改预览'));
    const joints=(project.joints||[]).filter(joint=>joint.part_ids.includes(part.id));
    if(joints.length){const related=node('div',{class:'related-connections'},node('h3',{},'关联连接 · '+joints.length));for(const joint of joints)related.append(button(jointName(joint)+' ↗',()=>inspectJoint(joint.id),'related-joint'));inspector.append(related);}
    if(!state.proposal){
      const features=node('details',{class:'optional-controls'},node('summary',{},'孔与槽 · '+(part.features?.length||0)));
      for(const feature of part.features||[])features.append(featureEditor(part,feature));
      features.append(button('+ 添加孔 / 槽',()=>{const feature={id:'feature_'+crypto.randomUUID().slice(0,8),kind:'hole',face:'top',u_mm:part.size_mm[0]/2,v_mm:part.size_mm[2]/2,diameter_mm:6,depth_mm:Math.min(10,part.size_mm[1])};features.insertBefore(featureEditor(part,feature,true),features.lastChild);}));inspector.append(features);
    }
    content.append(inspector);
  }
  const tree=node('details',{class:'part-tree',open:!part},node('summary',{},'全部部件 · '+parts.length));
  for(const item of parts){
    const visibility=node('input',{type:'checkbox',checked:!state.viewport?.hiddenIds.has(item.id),'aria-label':'显示 '+item.name,onChange:event=>state.viewport?.setVisible(item.id,event.target.checked)});
    const select=button('',()=>selectPart(item.id),'layer-select');select.append(node('span',{class:'layer-title'},item.name,node('small',{},item.size_mm.join(' × ')+' mm')));
    tree.append(node('div',{class:'layer-item'+(state.selectedId===item.id?' selected':'')},visibility,select));
  }
  content.append(tree);
}
function featureEditor(part,feature,isNew=false) {
  const details=node('details',{class:'decision',open:isNew});details.append(node('summary',{},feature.id+' · '+(feature.kind==='hole'?'孔':'槽')));
  const form=node('div',{});form.append(field('类型','kind',feature.kind,'text',[['hole','孔'],['slot','槽']]),field('加工面','face',feature.face,'text',[['top','顶面'],['bottom','底面'],['left','左面'],['right','右面'],['front','前面'],['back','背面']]));
  if(feature.entry_mm||feature.direction_local){
    const axes={top:[0,2,1],bottom:[0,2,1],left:[2,1,0],right:[2,1,0],front:[0,1,2],back:[0,1,2]},[a,b,n]=axes[feature.face],entry=feature.entry_mm||part.size_mm.map((v,i)=>i===a?feature.u_mm-v/2:i===b?feature.v_mm-v/2:v/2*(['top','right','front'].includes(feature.face)?1:-1)),direction=feature.direction_local||[0,0,0].map((_,i)=>i===n?(['top','right','front'].includes(feature.face)?-1:1):0);
    form.append(node('div',{class:'field-row'},...entry.map((v,i)=>field('入口 '+'XYZ'[i]+' mm','entry'+i,v,'number'))),node('div',{class:'field-row'},...direction.map((v,i)=>field('孔轴 '+'XYZ'[i],'axis'+i,v,'number'))));
  }else form.append(node('div',{class:'field-row'},field('定位 u mm','u',feature.u_mm,'number'),field('定位 v mm','v',feature.v_mm,'number')));
  form.append(field('深度 mm','depth',feature.depth_mm,'number'),field('孔径 mm','diameter',feature.diameter_mm||'','number'),node('div',{class:'field-row'},field('槽宽 mm','width',feature.width_mm||'','number'),field('槽长 mm','length',feature.length_mm||'','number')));
  form.append(button('预览加工特征',()=>{const kind=value(form,'kind'),updated={id:feature.id,role:feature.role||'connection',kind,face:value(form,'face'),u_mm:number(form,'u'),v_mm:number(form,'v'),depth_mm:number(form,'depth')};if(feature.entry_mm||feature.direction_local){const axes={top:[0,2],bottom:[0,2],left:[2,1],right:[2,1],front:[0,1],back:[0,1]},[a,b]=axes[updated.face];updated.entry_mm=[0,1,2].map(i=>number(form,'entry'+i));const axis=[0,1,2].map(i=>number(form,'axis'+i)),length=Math.hypot(...axis);if(!length)throw new Error('孔轴方向不能为空。');updated.direction_local=axis.map(v=>v/length);updated.u_mm=updated.entry_mm[a]+part.size_mm[a]/2;updated.v_mm=updated.entry_mm[b]+part.size_mm[b]/2;}if(kind==='hole')updated.diameter_mm=number(form,'diameter');else{updated.width_mm=number(form,'width');updated.length_mm=number(form,'length');}if([updated.depth_mm,kind==='hole'?updated.diameter_mm:updated.width_mm,kind==='slot'?updated.length_mm:1].some(n=>!(n>0)))throw new Error('请输入有效加工尺寸。');const changed={...part,features:[...(part.features||[]).filter(item=>item.id!==feature.id),updated]};return stagePatch({parts:state.project.parts.map(item=>item.id===part.id?changed:item),joints:state.project.joints.map(joint=>joint.part_ids.includes(part.id)?{...joint,confirmed:false}:joint)},'更新 '+part.name+' 的加工特征；相关连接需要重新确认。');}));
  if(!isNew)form.append(button('删除特征',()=>{const changed={...part,features:part.features.filter(item=>item.id!==feature.id)};return stagePatch({parts:state.project.parts.map(item=>item.id===part.id?changed:item),joints:state.project.joints.map(joint=>joint.feature_ids?.includes(feature.id)?{...joint,confirmed:false,feature_ids:joint.feature_ids.filter(id=>id!==feature.id)}:joint)},'删除加工特征 '+feature.id);}));details.append(form);return details;
}
function hardwareGeometry(item) {
  return item.geometry||(displayProject()?.joints||[]).flatMap(joint=>joint.hardware||[]).find(entry=>entry.name===item.name&&entry.spec===item.spec)?.geometry||{};
}
function hardwareGlyph(item) {
  const kind=hardwareGeometry(item).kind;
  const shapes={bolt:'<path d="M10 17h32v8H10zM6 13h5v16H6zM22 17l-4 8m11-8-4 8m11-8-4 8"/>',washer:'<ellipse cx="25" cy="22" rx="16" ry="10"/><ellipse cx="25" cy="22" rx="6" ry="4"/>',barrel_nut:'<path d="M15 12v21c0 5 20 5 20 0V12"/><ellipse cx="25" cy="12" rx="10" ry="5"/><circle cx="25" cy="25" r="4"/>',hex_nut:'<path d="M16 10h18l9 13-9 13H16L7 23z"/><circle cx="25" cy="23" r="6"/>'};
  const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 44" fill="none" stroke="currentColor" color="#5e6c5c" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'+(shapes[kind]||'<path d="M12 12h26v24H12zM18 18h14M18 24h14"/>')+'</svg>';
  return node('img',{class:'hardware-glyph',src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg),alt:'','aria-hidden':'true'});
}
function compactHardwareSpec(item) {
  const g=hardwareGeometry(item),n=value=>Number(value).toLocaleString('en-US',{maximumFractionDigits:3});
  if(g.kind==='bolt')return 'M'+n(g.diameter_mm)+' × '+n(g.length_mm);
  if(g.kind==='washer')return 'Ø'+n(g.bore_diameter_mm)+' / '+n(g.diameter_mm)+' × '+n(g.length_mm);
  if(g.kind==='barrel_nut')return 'M'+n(g.bore_diameter_mm)+' · Ø'+n(g.diameter_mm)+' × '+n(g.length_mm);
  if(g.kind==='hex_nut')return 'M'+n(g.bore_diameter_mm)+' · 厚 '+n(g.length_mm);
  return item.spec||'';
}
function hardwareTile(item) {
  // The card is the source of truth for procurement; keep the full supplied specification visible here.
  const spec=item.spec||compactHardwareSpec(item);
  const card=node('div',{class:'visual-hardware',title:item.name+' · '+spec},hardwareGlyph(item),node('b',{class:'hardware-quantity'},'×'+item.quantity),node('strong',{},item.name),node('small',{},spec));
  return card;
}
function grainDirectionGraphic(part) {
  const axis=displayProject()?.materials?.[part.material_id]?.grain_axis||'unknown';
  // Show the broad face in local coordinates, retaining its real proportions.
  const axes=[0,1,2].sort((a,b)=>part.size_mm[b]-part.size_mm[a]).slice(0,2).sort((a,b)=>a-b);
  const factor=Math.min(86/part.size_mm[axes[0]],34/part.size_mm[axes[1]]);
  const w=part.size_mm[axes[0]]*factor,h=part.size_mm[axes[1]]*factor,x=(96-w)/2,y=(44-h)/2;
  const grainIndex=axis==='x'?0:axis==='z'?2:-1,horizontal=grainIndex===axes[0],vertical=grainIndex===axes[1];
  const label=grainIndex<0?'纹理方向未记录':'局部 '+'XYZ'[axes[0]]+'XYZ'[axes[1]]+' 面 · 纹理沿 '+axis.toUpperCase()+' 向';
  let grain='',arrow='';
  if(horizontal||vertical){
    for(const fraction of [.2,.4,.6,.8]){
      const d=horizontal?'M'+x+' '+(y+h*fraction)+' Q'+(x+w*.4)+' '+(y+h*fraction-h*.06)+' '+(x+w)+' '+(y+h*fraction):'M'+(x+w*fraction)+' '+y+' Q'+(x+w*fraction-w*.06)+' '+(y+h*.4)+' '+(x+w*fraction)+' '+(y+h);
      grain+='<path d="'+d+'" stroke="#c9ad7b" stroke-width=".7"/>';
    }
    const a=horizontal?x+w*.15:y+h*.15,b=horizontal?x+w*.85:y+h*.85,c=horizontal?22:48,t=Math.min(3,(horizontal?h:w)*.22);
    arrow=horizontal?'<path d="M'+a+' '+c+'H'+b+'m-'+t+' -'+t+' '+t+' '+t+' -'+t+' '+t+'M'+(a+t)+' '+(c-t)+' '+a+' '+c+' '+(a+t)+' '+(c+t)+'"/>':'<path d="M'+c+' '+a+'V'+b+'m-'+t+' -'+t+' '+t+' '+t+' '+t+' -'+t+'M'+(c-t)+' '+(a+t)+' '+c+' '+a+' '+(c+t)+' '+(a+t)+'"/>';
  }else if(grainIndex<0)grain='<path d="M'+x+' '+y+' '+(x+w)+' '+(y+h)+'M'+(x+w)+' '+y+' '+x+' '+(y+h)+'" stroke="#b5b9af" stroke-dasharray="2 2"/>';
  else grain='<circle cx="48" cy="22" r="2" fill="#55735c"/>';
  const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 44" fill="none" stroke="#55735c" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" fill="#f4ead7" stroke="#c8b58f"/>'+grain+arrow+'</svg>';
  return node('img',{class:'grain-direction',src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg),alt:label,title:label});
}
function renderLists(content) {
  const p=displayProject(),pkg=packagePreview();
  if(state.listMode==='review'){renderReview(content);return;}
  content.append(node('div',{class:'list-tabs'},[['joints','连接'],['cut','下料'],['hardware','五金'],['review','核对']].map(([mode,label])=>button(label,()=>showList(mode),state.listMode===mode?'active':''))));
  if(state.listMode==='hardware'){
    content.append(node('h3',{},'五金 · 汇总采购'));
    content.append(node('div',{class:'hardware-inventory'},(pkg?.hardware||[]).map(hardwareTile)));
    const stock=node('details',{class:'optional-controls'},node('summary',{},'我的仓库 · '+(state.context.inventory?.length||0)+' 项'));
    for(const item of state.context.inventory||[])stock.append(paragraph((item.name||item.spec)+' × '+(item.quantity??'—')));
    stock.append(button('记录库存',()=>{const name=prompt('材料或五金名称');if(!name)return;const spec=prompt('规格')||'';const quantityText=prompt('数量','1');if(quantityText===null)return;const quantity=Number(quantityText);if(!(quantity>=0))throw new Error('数量必须是非负数。');return saveInventory({id:crypto.randomUUID(),name,spec,quantity});}));content.append(stock);return;
  }
  if(state.listMode==='cut'){
    content.append(node('h3',{},'下料 · '+(p.parts?.length||0)+' 件'));
    for(const part of p.parts||[]){const row=button('',()=>{state.listPartId=part.id;state.selectedId=part.id;state.viewport?.focus(part.id);renderContext();},'cut-row'+(state.listPartId===part.id?' active':''));const info=node('span',{class:'cut-info'},node('strong',{},part.name),node('small',{},part.size_mm.join(' × ')+' mm'));row.append(info,grainDirectionGraphic(part));content.append(row);}
    const part=(p.parts||[]).find(x=>x.id===state.listPartId)||p.parts?.[0];
    if(part){content.append(node('div',{class:'spec-chips'},node('span',{class:'chip'},p.materials?.[part.material_id]?.name||'材料未设定'),node('span',{class:'chip'},(part.features?.length||0)+' 处加工')));const drawing=pkg?.drawings?.find(x=>x.part_id===part.id);if(drawing?.svg){const thumb=button('',()=>openDrawing(part.id),'drawing-grid');thumb.setAttribute('aria-label','放大 '+part.name+' 图纸');thumb.append(node('img',{src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(drawing.svg),alt:part.name+' 加工图'}));content.append(thumb);}}
    return;
  }
  const joints=p.joints||[],selected=joints.find(j=>j.id===state.inspectedJointId);
  content.append(node('h3',{},'连接 · '+joints.length+' 处'));
  if(!joints.length){content.append(paragraph('还没有连接设计'));return;}
  const rows=node('div',{class:'connection-list'+(selected?' compact':'' )});
  joints.forEach((joint,index)=>{const row=button('',()=>inspectJoint(joint.id),'connection-row'+(joint.id===state.inspectedJointId?' active':''));row.setAttribute('aria-label','查看连接 '+(index+1)+' '+jointName(joint));row.setAttribute('title',jointName(joint));row.append(node('span',{},String(index+1).padStart(2,'0')));if(!selected)row.append(node('strong',{},jointName(joint)),node('span',{},'↗'));rows.append(row);});content.append(rows);
  if(!selected)return;
  const detail=node('div',{class:'connection-detail'},node('h3',{},jointName(selected)));
  const owned=(p.parts||[]).flatMap(part=>part.features||[]).filter(f=>selected.feature_ids?.includes(f.id));
  const holes=[...new Set(owned.filter(f=>f.kind==='hole').map(f=>'Ø'+f.diameter_mm))];
  detail.append(node('div',{class:'spec-chips'},holes.map(label=>node('span',{class:'chip'},label)),node('span',{class:'chip'},owned.length+' 处加工')));
  detail.append(node('div',{class:'hardware-inventory connection-kit','aria-label':'这处连接的五金'},(selected.hardware||[]).map(hardwareTile)));

  const jointSheet=pkg?.drawings?.find(sheet=>sheet.joint_id===selected.id||sheet.joint_ids?.includes(selected.id));
  const actions=node('div',{class:'connection-actions'});
  actions.append(button(state.viewport?.exploded?'收拢连接':'展开连接',()=>{state.viewport?.setExploded(!state.viewport?.exploded);renderContext();renderModelGuide();},'primary'));
  if(jointSheet)actions.append(button('连接大样 ↗',()=>openJointDrawing(selected.id),'quiet'));detail.append(actions);
  content.append(detail);
}

function jointEditor(joint) {
  const details=node('details',{class:'decision'});details.append(node('summary',{},jointName(joint)));
  details.append(paragraph(joint.assembly_note||'装配说明未生成。'));
  for(const hardware of joint.hardware||[])details.append(node('p',{},hardware.name+' '+hardware.spec+' × '+hardware.quantity));
  if(joint.feature_ids?.length)details.append(paragraph('加工孔槽：'+joint.feature_ids.length+' 处'));
  if(!state.proposal) {
    const edit=node('details',{class:'optional-controls'},node('summary',{},'编辑装配说明'));
    const note=node('textarea',{'aria-label':'装配说明'},joint.assembly_note||'');edit.append(note,button('保存说明修改',()=>mutate({joints:state.project.joints.map(item=>item.id===joint.id?{...item,assembly_note:note.value,confirmed:false}:item)},false)));
    details.append(edit);
  }
  return details;
}
async function savePreference(key,val) { if(val===null)return;state.context=await api('/context',json('PUT',{expected_revision:state.context.revision,preferences:{...state.context.preferences,[key]:val}}));notice('已记住，下个项目可选择使用。'); }
async function saveInventory(item) {state.context=await api('/context',json('PUT',{expected_revision:state.context.revision,inventory:[...(state.context.inventory||[]),item]}));renderContext();notice('已记录到仓库。');}
function openDrawing(partId) {
  const sheets=packagePreview()?.drawings||[],index=sheets.findIndex(sheet=>sheet.part_id===partId);if(index<0)return;
  openDrawingViewer(sheets,index,drawingViewerOptions());
}
function openJointDrawing(jointId) {
  const sheets=packagePreview()?.drawings||[],index=sheets.findIndex(sheet=>sheet.joint_id===jointId||sheet.joint_ids?.includes(jointId));if(index<0)return;
  openDrawingViewer(sheets,index,drawingViewerOptions());
}

function drawingViewerOptions() {return {onLocate:locateDrawing,jointLabel:id=>{const joint=displayProject()?.joints?.find(item=>item.id===id);return joint?jointName(joint):id;}};}
function locateDrawing(sheet) {
  showPage('design');
  if(sheet.joint_id)inspectJoint(sheet.joint_id);
  else if(sheet.part_id)selectPart(sheet.part_id,{focus:true});
}
function openDrawings() {
  const sheets=packagePreview()?.drawings||[];
  if(sheets.length)openDrawingViewer(sheets,0,drawingViewerOptions());
}

function openOverview() {
  const sheets=packagePreview()?.drawings||[],index=sheets.findIndex(sheet=>sheet.sheet_type==='assembly_overview');
  if(index>=0)openDrawingViewer(sheets,index,drawingViewerOptions());
}

async function enterPackageFlow() {
  requireNoProposal();if(state.dirtyForms)throw new Error('先保存或取消当前输入，再生成加工包。');
  await refreshData();
  if(displayChecks().some(item=>item.severity==='blocker')){state.activeTask='confirm';state.sidebarMode='tasks';setPanel('tasks',true);render();return;}
  await openPackage();
}
async function openPackage() {
  requireNoProposal();if(state.dirtyForms)throw new Error('先保存或取消正在编辑的内容。');
  const projectId=state.project.id,revision=state.project.revision,capturedProject=clone(state.project);
  await guarded(async()=>{
    const exported=await api('/projects/'+projectId+'/exports',json('POST',{expected_revision:revision}));
    if(state.project.id!==projectId)throw new Error('项目已切换，请重新打开加工包。');
    state.packageSnapshot={project:capturedProject,pkg:exported.package_snapshot,exported};
    showPage('package');renderPackagePage();
  });
}
function packageVisualStory(snapshot){
  const host=node('section',{class:'package-visual-story','aria-label':'模型与装配预览'});
  const heading=node('div',{class:'package-visual-heading'},node('div',{},node('span',{class:'eyebrow'},'从这把椅子开始'),node('h2',{},'先看成品，再看怎么组成')));
  const tabs=node('div',{class:'package-visual-tabs','aria-label':'模型展示方式'});
  const stage=node('div',{class:'package-visual-stage','aria-live':'polite'},paragraph('正在从这版模型生成图片…'));
  const legend=node('div',{class:'package-part-legend'}),caption=node('p',{class:'package-visual-caption'});
  host.append(heading,stage,caption,legend);
  const load=async()=>{
    try{
      snapshot.visualsPromise??=import('./package-visuals.js?v=1').then(module=>module.createPackageVisuals(snapshot.project,snapshot.pkg));
      const visuals=await snapshot.visualsPromise;if(!host.isConnected)return;
      const assembled=button('成品效果',()=>show('assembled'),'active'),exploded=button('拆开看',()=>show('exploded'));
      tabs.append(assembled,exploded);heading.append(tabs);
      const show=mode=>{
        const isExploded=mode==='exploded';
        assembled.classList.toggle('active',!isExploded);exploded.classList.toggle('active',isExploded);
        assembled.setAttribute('aria-pressed',String(!isExploded));exploded.setAttribute('aria-pressed',String(isExploded));
        stage.replaceChildren(node('img',{src:visuals[mode],alt:isExploded?'当前版本椅子的板件爆炸示意图':'当前版本椅子的完整模型效果'}));
        caption.replaceChildren(node('span',{},isExploded?'按编号认识板件；分离方向用于展示组成，不代表实际装配顺序。':'直接来自加工包 v'+snapshot.pkg.revision+' 的模型。'),node('a',{href:visuals[mode],download:'junior-v'+snapshot.pkg.revision+'-'+mode+'.png'},'保存这张图'));
        legend.hidden=!isExploded;
      };
      legend.append(...visuals.legend.map(part=>node('span',{},node('b',{},part.code),part.name)));
      show('assembled');
    }catch(error){snapshot.visualsPromise=null;if(host.isConnected)stage.replaceChildren(paragraph('模型图片暂时未生成。'),button('重新生成图片',()=>{stage.replaceChildren(paragraph('正在生成…'));return load();},'quiet'));}
  };
  queueMicrotask(load);return host;
}
function renderPackagePage() {
  const host=$('package-page-content'),snapshot=state.packageSnapshot;if(!snapshot)return;
  const {project,pkg,exported}=snapshot,stale=project.id!==state.project.id||pkg.revision!==state.project.revision;
  host.replaceChildren();
  const status=stale?'设计已更新 · 当前显示历史快照':pkg.status==='ready'?'已确认设计资料 · 待加工核对':'设计资料草稿';
  const summary=node('section',{class:'package-summary'},node('div',{},node('h2',{},project.name),paragraph('v'+pkg.revision+' · '+(pkg.parts?.length||0)+' 个板件 · '+(pkg.joints?.length||0)+' 处连接'),node('span',{class:'tag'},status)),node('div',{class:'package-actions'},button('生成当前版本',openPackage,'quiet'),node('a',{href:exported?.pdf_url||API+'/projects/'+project.id+'/exports/'+pkg.revision+'/pdf',target:'_blank',rel:'noopener'},'下载 PDF'),button('下载加工包 ZIP',()=>downloadPackage({id:project.id,name:project.name,revision:pkg.revision}),'primary',pkg.status!=='ready')));
  host.append(summary);
  host.append(packageVisualStory(snapshot));
  const blockers=(pkg.checks||[]).filter(check=>check.severity==='blocker');
  if(stale)host.append(node('p',{class:'preview-banner'},'这是历史版本加工包，仍可下载。当前设计需要重新生成。'));
  else if(pkg.status!=='ready')host.append(node('div',{class:'preview-banner'},paragraph(blockers.length?'还有 '+blockers.length+' 项需要处理；可以先浏览草稿。':'请核对当前设计与检查范围，确认后下载。'),button(blockers.length?'查看待解决项':'核对并确认设计',()=>showList('review'))));
  const moduleRows=pkg.modules||project.modules||[];
  if(moduleRows.length){
    const moduleSection=node('details',{class:'package-module-summary'},node('summary',{},'尺寸与使用者'),paragraph('沿用这一版模型的适配目标。'));
    moduleRows.forEach(module=>{
      const target=module.target||{},labels={seat_width_mm:'座宽',seat_depth_mm:'座深',seat_height_mm:'座高',back_angle_deg:'靠背角'};
      const values=Object.entries(target).filter(([,value])=>value!==null&&value!==undefined&&value!=='').map(([key,value])=>labels[key]?labels[key]+' '+value+(key.endsWith('_deg')?'°':' mm'):key+' '+value).join(' · ');
      const parts=(module.affected_part_ids||[]).map(id=>(project.parts||[]).find(part=>part.id===id)?.name||id).filter(Boolean).join('、');
      moduleSection.append(node('article',{class:'package-module-card'},node('div',{},node('strong',{},module.name||'使用模块'),node('p',{},[module.occupant,postureLabels[module.posture]||module.posture].filter(Boolean).join(' · ')||'使用条件待补充')),node('span',{class:'tag'},({inferred:'待确认',target:'目标',confirmed:'已确认',conflict:'有冲突',needs_review:'需重新核对'})[module.status]||'适配目标'),values?node('p',{},values):null,parts?node('small',{},'关联部件 · '+parts):null));
    });
    host.append(moduleSection);
  }
  const nav=node('nav',{class:'package-section-nav','aria-label':'加工包目录'});for(const [id,label] of [['purchase','我买什么'],['workshop','交给加工店什么'],['assembly','我怎么装']])nav.append(button(label,()=>{const section=$('package-'+id);section.open=true;section.scrollIntoView({behavior:'smooth',block:'start'});}));host.append(nav);
  const purchase=node('section',{id:'package-purchase',class:'package-section'},node('span',{class:'eyebrow'},'01 · 采购与下料'),node('h2',{},'我买什么'),paragraph('板件尺寸单位为 mm。毛坯余量、锯缝和实际供料规格需与加工者核对。'));
  purchase.append(node('h3',{},'板件清单'),node('div',{class:'table-scroll'},renderRecords(pkg.cut_list||[])),node('h3',{},'五金采购'),node('div',{class:'table-scroll'},renderRecords(pkg.hardware||[])));host.append(purchase);
  const workshop=node('section',{id:'package-workshop',class:'package-section'},node('span',{class:'eyebrow'},'02 · 加工资料'),node('h2',{},'交给加工店什么'),paragraph(({self:'当前计划：自行加工。',shop:'当前计划：加工店制件，自己装配。'})[pkg.fabrication_mode]||'制作方式尚未确定。'),paragraph('按零件编号查看图纸、加工面和连接。当前版本同时提供 PDF、SVG 图纸和结构化设计数据。'));
  const sheets=pkg.drawings||[],gallery=node('div',{class:'package-sheet-grid'});
  sheets.forEach((sheet,index)=>{const card=button('',()=>openDrawingViewer(sheets,index,drawingViewerOptions()),'package-sheet');card.append(node('img',{src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(sheet.svg),alt:sheet.title||'加工图',loading:'lazy'}),node('strong',{},(pkg.status==='ready'?'':'草稿 · ')+(sheet.title||sheet.id)));gallery.append(card);});
  workshop.append(sheets.length?gallery:paragraph('图纸尚未生成，先完成模型与做法。'));
  const checks=node('details',{class:'optional-controls'},node('summary',{},'检查结果与尚待核对事项'),(pkg.checks||[]).map(check=>node('p',{class:'issue '+(check.severity==='blocker'?'':'warning')},check.message)));
  if(pkg.coverage?.not_checked?.length)checks.append(paragraph('当前检查未覆盖：'+pkg.coverage.not_checked.join('；')));
  if(pkg.assumptions?.length)checks.append(node('h3',{},'设计设定'),node('ul',{},pkg.assumptions.map(item=>node('li',{},item))));workshop.append(checks);host.append(workshop);
  const assembly=node('section',{id:'package-assembly',class:'package-section'},node('span',{class:'eyebrow'},'03 · 装配资料'),node('h2',{},'我怎么装'),paragraph('按连接记录查看相关板件与五金，结合装配图核对顺序和工具。'));
  const steps=pkg.assembly_steps||[];
  if(!steps.length)assembly.append(paragraph('装配方案尚未形成，回到做法阶段补齐连接。'));
  for(const step of steps){
    const copy=node('div',{},node('h3',{},step.name),paragraph((step.part_ids||[]).map(id=>(pkg.parts||[]).find(p=>p.id===id)?.name||id).join(' + ')));
    const instruction=node('div',{},paragraph(step.instruction),node('ul',{},(step.hardware||[]).map(item=>node('li',{},item.name+' '+item.spec+' × '+item.quantity))));
    if(!step.confirmed){copy.append(node('p',{class:'preview-banner'},'连接待重新核对。以下是尚未确认的方案说明，勿作为当前加工依据。'),node('details',{class:'optional-controls'},node('summary',{},'查看未确认的说明与五金'),instruction));}
    else copy.append(instruction);
    copy.append(button('在模型中看这处连接',()=>{if(stale)throw new Error('请先更新资料，再定位当前模型。');inspectJoint(step.joint_id);},'quiet',stale));
    assembly.append(node('article',{class:'assembly-step'+(step.confirmed?'':' assembly-pending')},node('span',{class:'assembly-number'},String(step.order).padStart(2,'0')),copy));
  }
  host.append(assembly);
  // One readable chapter at a time; drawings and long tables stay available on demand.
  for(const section of [purchase,workshop,assembly]){
    const title=section.querySelector('h2'),kicker=section.querySelector('.eyebrow');
    const chapter=node('details',{id:section.id,class:'package-section package-chapter'},node('summary',{},node('span',{},kicker.textContent),node('strong',{},title.textContent),node('span',{class:'chapter-toggle','aria-hidden':'true'},'+')));
    title.remove();kicker.remove();while(section.firstChild)chapter.append(section.firstChild);section.replaceWith(chapter);
  }
}
function renderRecords(records) {
  if(!records.length)return paragraph('未生成');
  const known=[['name','名称'],['part_id','编号'],['quantity','数量'],['material','材料'],['material_name','材料'],['size_mm','尺寸 mm'],['stock_size_mm','毛坯尺寸 mm'],['dimensions_mm','尺寸 mm'],['spec','规格'],['grain_axis','纹理轴']];
  const columns=known.filter(([key])=>records.some(record=>record[key]!==undefined));
  const format=value=>typeof value==='number'?Number(value.toFixed(2)):value;
  return node('table',{class:'compact-table'},node('thead',{},node('tr',{},columns.map(([,label])=>node('th',{},label)))),node('tbody',{},records.map(record=>node('tr',{},columns.map(([key])=>node('td',{},Array.isArray(record[key])?record[key].map(format).join(' × '):typeof record[key]==='object'?Object.values(record[key]||{}).map(format).join(' × '):format(record[key])??''))))));
}
async function downloadPackage(snapshot) {const response=await fetch(API+'/projects/'+encodeURIComponent(snapshot.id)+'/exports/'+encodeURIComponent(snapshot.revision)+'/download');if(!response.ok)throw new Error('这版加工包尚未生成或下载失败，请重试。');const url=URL.createObjectURL(await response.blob());const link=node('a',{href:url,download:snapshot.name+'-v'+snapshot.revision+'.zip'});link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function selectProject(id) {
  if(state.busy)throw new Error('正在处理当前操作，请稍后再切换项目。');
  if(id===state.project?.id){showPage('design');return;}
  if(state.dirtyForms)throw new Error('先保存正在编辑的条件，再切换项目。');
  persistDrafts();
  await guarded(async()=>{
    const project=await api('/projects/'+id);
    clearInspection(false);state.viewport?.setExploded(false);state.viewport?.setHardwareVisible(true);$('hardware-toggle').setAttribute('aria-pressed','true');state.viewport?.hiddenIds.clear();state.viewport?.load([]);state.listPartId=null;
    state.project=project;restoreDrafts();showPage('design');localStorage.setItem('junior-project-id',project.id);state.proposal=null;state.selectedId=null;
    await refreshData();await recoverProposal();state.activeTask=state.proposal?.purpose==='manufacturing'?'confirm':nextTask();state.conversationOpen=state.proposal?.source==='local_command';state.sidebarMode='tasks';state.dirtyForms=false;state.generationError='';
    if(!state.project.parts?.length&&!state.proposal)setPanel('tasks',false,{persist:false});
    render();for(const control of ['project-switch','compact-project-switch'])$(control).value=state.project.id;
  });
}
async function listProjects() {state.projects=await api('/projects');for(const id of ['project-switch','compact-project-switch'])$(id).replaceChildren(...state.projects.map(project=>node('option',{value:project.id,selected:project.id===state.project?.id},project.name)));renderHome();}
async function newProject() {
  if(state.busy||state.dirtyForms)throw new Error('先保存正在编辑的条件，再新建项目。');persistDrafts();
  await guarded(async()=>{
    const project=await api('/projects',json('POST',{name:'我的家具'}));
    clearInspection(false);state.viewport?.setExploded(false);state.viewport?.setHardwareVisible(true);$('hardware-toggle').setAttribute('aria-pressed','true');state.viewport?.hiddenIds.clear();state.viewport?.load([]);state.listPartId=null;
    state.project=project;state.referenceDraft='';state.fitDraft='';state.commandDraft='';$('command-input').value='';state.conversationOpen=false;state.generationError='';showPage('design');localStorage.setItem('junior-project-id',project.id);state.proposal=null;state.selectedId=null;
    await refreshData();state.activeTask='reference';await listProjects();setPanel('tasks',false,{persist:false});render();
  });
}


function openConversation(open=true) {
  state.conversationOpen=open;
  if(open)setPanel('tasks',true);
  renderConversation();renderModelGuide();if(!state.dirtyForms)renderTasks();
}
function conversationReply(text,reply,status='completed') {
  state.localMessages.push({id:crypto.randomUUID(),text,reply,status,created_at:new Date().toISOString(),kind:'local'});
  renderConversation();
}
function renderConversation() {
  const host=$('conversation-messages');if(!host||!state.project)return;
  if(state.conversationProject!==state.project.id){state.conversationProject=state.project.id;state.localMessages=[];state.historyKey='';}
  $('conversation-panel').hidden=!state.conversationOpen;
  $('conversation-toggle').setAttribute('aria-expanded',String(state.conversationOpen));
  const records=[...state.interactionRecords,...state.localMessages].sort((a,b)=>a.created_at.localeCompare(b.created_at));
  const labels={pending:'等待会话处理',ready:'修改等你决定',completed:'已完成',stale:'基于旧版本',superseded:'已合并到新请求',cancelled:'方案未采用',revision_requested:'等待调整方案',error:'发送未完成'};
  const latest=records.at(-1),lastStatus=latest?.status;
  $('command-state').textContent=state.busy?'正在处理…':latest?(labels[lastStatus]||lastStatus):'告诉我怎么改';
  const key=JSON.stringify([records,state.proposal?.id,state.busy]);if(state.historyKey===key)return;state.historyKey=key;host.replaceChildren();
  if(!records.length)host.append(paragraph('试试“打开下料”“切到前视图”，或“座板宽度改为420mm”。'));
  for(const record of records){
    const status=record.status;
    const user=node('div',{class:'conversation-message user'},node('small',{},'你'),paragraph(record.text));
    const reply=node('div',{class:'conversation-message assistant'},node('small',{},(record.kind==='handoff'?'会话协作':'Junior')+' · '+(labels[status]||status)),paragraph(status==='cancelled'?'这版方案未采用，当前设计保持不变。':record.reply));
    if(status==='ready'){
      const actions=node('div',{class:'action-row'});
      if(state.proposal?.id===record.proposal_id){
        actions.append(button('采用修改',async()=>{await acceptProposal();await refreshInteractionHistory();openConversation(true);},'primary',state.busy),button('不采用这版',async()=>{await dismissProposal();state.historyKey='';renderConversation();},'',state.busy));
      }else actions.append(button('查看修改',async()=>{if(state.dirtyForms)throw new Error('请先保存正在编辑的内容，再查看修改。');await refreshFromSession();openConversation(true);},'primary',state.busy));
      reply.append(actions);
    }
    if(status==='pending'||status==='revision_requested')reply.append(button('查看返回结果',async()=>{await refreshInteractionHistory();await refreshFromSession();openConversation(true);},'quiet',state.busy));
    host.append(user,reply);
  }
  const panel=$('conversation-panel');requestAnimationFrame(()=>{panel.scrollTop=panel.scrollHeight;});
}
async function refreshInteractionHistory() {
  if(!state.project)return;
  const id=state.project.id,result=await api('/projects/'+id+'/interaction/history');
  if(state.project?.id!==id)return;
  state.interactionRecords=result.records||[];renderConversation();return result;
}
function localNavigation(text) {
  const clean=text.trim().replace(/[。！!？?]$/,'');
  const views={'前视图':'front','前视':'front','右视图':'right','顶视图':'top','俯视图':'top','等轴视图':'iso','等轴':'iso','适应视图':'fit'};
  const view=clean.replace(/^(切到|切换到|切换为|打开|查看)/,'');
  if(views[view]){setPanel('tasks',false);state.viewport?.setView(views[view]);return '已切换到'+view+'。';}
  const target=clean.replace(/^(打开|查看|显示)/,'');
  const lists={'下料':'cut','下料表':'cut','下料清单':'cut','五金':'hardware','采购单':'hardware','核对':'review','连接':'joints'};
  if(lists[target]){showList(lists[target]);return '已打开'+target+'。';}
  if(['参考','参考资料','版本','设计版本'].includes(target)){state.tab=target.includes('版本')?'versions':'references';setPanel('context',true);renderContext();return '已打开'+target+'。';}
  if(target==='图纸'||target==='开工总览'){if(!packagePreview()?.drawings?.length)return '先形成设计，图纸会随模型生成。';if(target==='图纸')openDrawings();else openOverview();return '已打开'+target+'。';}
  if(target==='爆炸图'||target==='装配爆炸图'){const joint=displayProject()?.joints?.[0];if(!joint)return '当前还没有连接方案。';openConversation(false);inspectJoint(joint.id);return '已展开第一处连接。';}
  return null;
}
async function submitInteraction() {
  const submitted=$('command-input').value.trim();if(!submitted||!state.project||state.busy)return;
  try{if(state.dirtyForms)throw new Error('先保存或取消正在编辑的内容.');const local=localNavigation(submitted);if(local){notice(local);setCommandDraft('');return;}await createDesignRun(state.project.parts.length?'modify':'reconstruct',submitted);setCommandDraft('');}catch(error){report(error);}
}
async function pollInteractions() {
  if(state.polling||state.busy||document.hidden||!state.project)return;
  state.polling=true;
  try {
    await refreshDesignRun();
    const history=await refreshInteractionHistory();if(!history||state.dirtyForms)return;
    const ready=(history.records||[]).find(r=>r.status==='ready'&&r.proposal_id!==localStorage.getItem('junior-dismissed-'+state.project.id));
    if(history.revision!==state.project.revision||ready&&!state.proposal){await refreshFromSession();if(ready){state.conversationOpen=false;render();}}
  } finally {state.polling=false;}
}

const compactLayout=matchMedia('(max-width:900px), (max-height:600px)');
function syncSidebar() {
  const open=state.sidebarOpen,guide=state.sidebarMode==='tasks';
  document.body.classList.toggle('module-surface-open',open&&guide&&state.activeTask==='fit');
  document.body.classList.toggle('bottom-surface-open',open);
  document.body.classList.toggle('sidebar-collapsed',!open);
  $('work-sidebar').inert=!open;
  const reviewing=!guide&&state.tab==='lists'&&state.listMode==='review';
  $('work-sidebar').querySelector('.sidebar-header>strong').textContent=reviewing?'出包前核对':guide?'当前任务':'辅助信息';
  $('task-panel').hidden=!guide;$('context-panel').hidden=guide;
  $('sidebar-context-heading').hidden=guide||reviewing;
  const step=tasks.find(([id])=>id===state.activeTask);
  $('sidebar-step-summary').textContent=step?'当前 · '+step[1]:'';
  const selected=displayProject()?.parts?.find(part=>part.id===state.selectedId);
  const joint=displayProject()?.joints?.find(item=>item.id===state.inspectedJointId);
  const titles={references:'参考资料',versions:'设计版本',layers:selected?.name||'全部部件',lists:state.listMode==='joints'&&joint?jointName(joint):'完整清单'};
  $('sidebar-context-title').textContent=titles[state.tab]||'项目资料';
  for(const element of document.querySelectorAll('#sidebar-library [data-tab]')){
    element.setAttribute('aria-current',!guide&&element.dataset.tab===state.tab?'page':'false');
  }
  const toggle=$('toggle-sidebar');toggle.setAttribute('aria-expanded',String(open));
  toggle.setAttribute('aria-label',open?'收起辅助信息':'打开辅助信息');toggle.title=toggle.getAttribute('aria-label');
  requestAnimationFrame(syncViewportFraming);
}
function syncViewportFraming(){
  const active=state.page==='design'&&state.sidebarOpen&&matchMedia('(min-width:601px) and (min-height:601px)').matches;
  state.viewport?.setBottomOcclusion(active?$('work-sidebar').getBoundingClientRect().height+28:0);
}
function setPanel(name,open,{persist=true}={}) {
  if(open)state.sidebarMode=name;
  $('sidebar-library').open=false;
  state.sidebarOpen=open;syncSidebar();
  if(persist&&!compactLayout.matches)localStorage.setItem('junior-sidebar-open-v2',open?'open':'closed');
  if(state.project)renderModelGuide();
}
function applyLayout(){state.sidebarOpen=!compactLayout.matches&&localStorage.getItem('junior-sidebar-open-v2')==='open';syncSidebar();}
$('toggle-sidebar').addEventListener('click',()=>setPanel(state.sidebarMode,!state.sidebarOpen));
document.querySelector('[data-sidebar="tasks"]').addEventListener('click',()=>setPanel('tasks',true));
compactLayout.addEventListener('change',()=>{syncSidebar();syncViewportFraming();});applyLayout();
window.addEventListener('resize',syncViewportFraming);
new ResizeObserver(syncViewportFraming).observe($('work-sidebar'));

document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;if($('sidebar-library').open){$('sidebar-library').open=false;return;}if(state.inspectedJointId)clearInspection();});
document.addEventListener('input',event=>{if(event.target.type==='checkbox')return;if(event.target.closest('.task-panel,.context-panel')&&!event.target.closest('.layer-item,[data-flow-draft]'))state.dirtyForms=true;});
window.addEventListener('focus',()=>refreshFromSession().catch(report));

$('project-name').addEventListener('change',()=>mutate({name:$('project-name').value.trim()||'我的木椅'}).then(listProjects).catch(report));
for(const id of ['project-switch','compact-project-switch'])$(id).addEventListener('change',event=>selectProject(event.target.value).catch(report));
for(const id of ['new-project','compact-new-project'])$(id).addEventListener('click',()=>newProject().catch(report));
$('proposal-input').addEventListener('change',event=>{const file=event.target.files[0];event.target.value='';if(file)importProposal(file).catch(report);});
$('reference-input').addEventListener('change',event=>{const files=[...event.target.files];event.target.value='';if(files.length)uploadFiles(files).catch(report);});
document.querySelectorAll('[data-upload]').forEach(element=>element.addEventListener('click',()=>$('reference-input').click()));
document.querySelectorAll('[data-tab]').forEach(element=>element.addEventListener('click',()=>{state.tab=element.dataset.tab;setPanel('context',true);renderContext();}));
document.querySelectorAll('[data-view]').forEach(element=>element.addEventListener('click',()=>{state.viewport?.setView(element.dataset.view);document.querySelectorAll('[data-view]').forEach(button=>button.classList.toggle('active',button===element));}));
document.querySelectorAll('[data-tool]').forEach(element=>element.addEventListener('click',()=>{clearInspection();state.viewport?.setTool(element.dataset.tool);if(element.dataset.tool!=='mirror')document.querySelectorAll('[data-tool]').forEach(button=>button.classList.toggle('active',button===element));}));
$('hardware-toggle').addEventListener('click',()=>{const visible=!state.viewport?.hardwareVisible;state.viewport?.setHardwareVisible(visible);$('hardware-toggle').setAttribute('aria-pressed',String(visible));});
$('undo').addEventListener('click',()=>navigateHistory(false).catch(report));
const redoButton=button('重做',()=>navigateHistory(true),'more-item',true);redoButton.id='redo';$('undo').after(redoButton);
async function navigateHistory(redo=false){
  if(state.busy||state.proposal||state.dirtyForms)throw new Error('先完成或取消当前编辑。');
  state.undoTargets??=state.versions.filter(v=>v.revision<state.project.revision).sort((a,b)=>a.revision-b.revision).map(v=>v.revision);state.redoTargets??=[];
  const source=redo?state.redoTargets:state.undoTargets,target=source.at(-1);if(!target)return;
  const current=state.project.revision;state.historyNavigating=true;
  try{await restoreVersion(target);source.pop();(redo?state.undoTargets:state.redoTargets).push(current);state.historyRevision=state.project.id+':'+state.project.revision;}
  finally{state.historyNavigating=false;render();}
}
$('package-button').addEventListener('click',()=>enterPackageFlow().catch(report));
$('command-form').addEventListener('submit',event=>{event.preventDefault();submitInteraction();});
$('conversation-toggle').addEventListener('click',()=>openConversation(!state.conversationOpen));
$('conversation-close').addEventListener('click',()=>openConversation(false));
document.querySelectorAll('[data-add-reference]').forEach(el=>el.addEventListener('click',()=>{goTask('reference');document.querySelector('.reference-entry textarea')?.focus();}));
$('quick-reference-input').addEventListener('input',event=>{state.referenceDraft=event.target.value;persistDrafts();renderGenerationControls();});
$('quick-reference-form').addEventListener('submit',event=>{event.preventDefault();beginGeneration().catch(report);});
$('start-cafe-demo').addEventListener('click',()=>openCafeDemo().catch(report));
$('ai-settings').addEventListener('click',()=>openAiSettings().catch(report));
$('ai-close').addEventListener('click',()=>$('ai-dialog').close());
const moreMenu=$('more-menu');
$('more-home').addEventListener('click',()=>{moreMenu.open=false;persistDrafts();showPage('home');$('home-page').scrollTop=0;listProjects().catch(report);});
$('more-demo').addEventListener('click',()=>{moreMenu.open=false;openCafeDemo().catch(report);});
$('more-sidebar').addEventListener('click',()=>{moreMenu.open=false;setPanel(state.sidebarMode,!state.sidebarOpen);});
document.querySelectorAll('#more-menu .more-item').forEach(item=>item.addEventListener('click',()=>{moreMenu.open=false;}));
document.querySelectorAll('[data-flow]').forEach(el=>el.addEventListener('click',()=>{try{goTask(el.dataset.flow==='make'&&taskDone('make')?'confirm':el.dataset.flow);render();}catch(error){report(error);}}));
$('flow-drawings').addEventListener('click',()=>enterPackageFlow().catch(report));
$('reference-close').addEventListener('click',()=>$('reference-dialog').close());
$('reference-preview-close').addEventListener('click',()=>$('reference-preview').close());
$('reference-form').addEventListener('submit',async event=>{event.preventDefault();$('reference-save').disabled=true;try{await saveReferenceText($('reference-text').value);$('reference-dialog').close();}catch(error){$('reference-error').textContent=error.message;}finally{$('reference-save').disabled=false;}});
$('sidebar-canvas').addEventListener('click',()=>setPanel('tasks',false));

function setCommandDraft(text) {state.commandDraft=text;$('command-input').value=text;persistDrafts();}
function persistDrafts() {
  if(!state.project)return;
  localStorage.setItem('junior-draft-'+state.project.id,JSON.stringify({reference:state.referenceDraft,fit:state.fitDraft,command:state.commandDraft}));
}
function restoreDrafts() {
  let draft={};try{draft=JSON.parse(localStorage.getItem('junior-draft-'+state.project.id)||'{}');}catch{}
  state.referenceDraft=draft.reference||'';state.fitDraft=draft.fit||'';state.commandDraft=draft.command||'';$('command-input').value=state.commandDraft;
}
function syncPage() {
  document.body.dataset.page=state.page;
  const url=new URL(location.href);
  if(state.page==='home'){url.searchParams.delete('project');url.searchParams.delete('view');}
  else if(state.project){url.searchParams.set('project',state.project.id);url.searchParams.set('view',state.page);}
  history.replaceState(null,'',url);
}
function showPage(page) {
  state.page=page;syncPage();
  if(page==='home')renderHome();
  const menu=$('more-menu');if(menu)menu.open=false;
}
function renderHome() {
  if(document.activeElement!==$('home-input'))$('home-input').value=state.homeDraft;
  $('home-channel-note').textContent='会话 Agent：提交参考后，由当前聊天读取资料、建模并检查，结果直接回到工作台。';
  $('home-start').disabled=state.busy||!state.homeDraft.trim();$('home-upload').disabled=state.busy;$('home-demo').disabled=state.busy;
  const list=$('home-project-list');list.replaceChildren();
  for(const item of state.projects){const p=state.projectDetails[item.id],current=item.id===state.project?.id,pending=current&&state.proposal;
    const status=pending?'有一版修改等你决定':p?.confirmed_revision===p?.revision&&p?'设计资料已确认':p?.parts?.length?'继续调整设计':p?.references?.length?'参考已保存':'继续项目';
    const card=button('',()=>selectProject(item.id),'project-card',state.busy);
    card.append(node('span',{class:'project-marker','aria-hidden':'true'},p?.parts?.length?String(p.parts.length).padStart(2,'0'):'↗'),node('div',{},node('strong',{},item.name),node('small',{},'v'+item.revision+' · '+new Date(item.updated_at).toLocaleDateString('zh-CN')),node('span',{class:'project-status'},status)),node('span',{class:'project-continue'},current?'继续当前 →':'打开 →'));list.append(card);
  }
  if(!state.projects.length)list.append(paragraph('你的家具设计会保存在这里。'));
}
async function beginFromHome({upload=false}={}) {
  $('home-error').textContent='';
  try {
    if(!upload&&!state.homeDraft.trim())return;
    const draft=state.homeDraft;await newProject();state.referenceDraft=draft;persistDrafts();render();
    if(upload){if(draft.trim())await saveReferenceText(draft);$('reference-input').click();}else {await saveReferenceText(draft);await generateModel();}
    state.homeDraft='';localStorage.removeItem('junior-home-draft');renderHome();
  }catch(error){$('home-error').textContent=error.message;report(error);}
}
$('home-link').addEventListener('click',event=>{event.preventDefault();showPage('home');});
$('command-input').addEventListener('input',event=>{state.commandDraft=event.target.value;persistDrafts();});
$('home-input').addEventListener('input',event=>{state.homeDraft=event.target.value;localStorage.setItem('junior-home-draft',state.homeDraft);$('home-start').disabled=state.busy||!state.homeDraft.trim();});
$('home-form').addEventListener('submit',event=>{event.preventDefault();beginFromHome();});
$('home-upload').addEventListener('click',()=>beginFromHome({upload:true}));
$('home-demo').addEventListener('click',()=>openCafeDemo().catch(report));
$('home-project-refresh').addEventListener('click',()=>listProjects().catch(report));
const modelFileInput=node('input',{type:'file',accept:'.json,application/json',hidden:true});document.body.append(modelFileInput);
const chooseModel=()=>{if(state.dirtyForms||state.busy)throw new Error('先保存或取消当前输入。');modelFileInput.click();};
$('home-project-refresh').before(button('打开模型文件',chooseModel,'quiet'));
$('new-project').after(button('打开模型文件',chooseModel,'more-item'));
modelFileInput.addEventListener('change',async()=>{
  const file=modelFileInput.files?.[0];modelFileInput.value='';if(!file)return;
  try{if(file.size>2*1024*1024)throw new Error('模型文件最多 2 MB。');let imported;await guarded(async()=>{imported=await api('/projects/import',{method:'POST',headers:{'content-type':'application/json'},body:await file.text()});await listProjects();});await selectProject(imported.id);notice('已打开为独立项目，原项目保持不变。');}
  catch(error){report(error);}
});
$('package-back').addEventListener('click',()=>showPage('design'));
window.addEventListener('beforeunload',event=>{persistDrafts();if(state.dirtyForms){event.preventDefault();event.returnValue='';}});

setInterval(()=>pollInteractions().catch(()=>{}),4000);

(async()=>{
  try {
    const {WorkshopViewport}=await import('./viewport.js?v=r2-1');state.viewport=new WorkshopViewport($('viewport'),{onSelect:id=>selectPart(id),onSelectHardware:instance=>inspectJoint(instance.joint_id),onTransform:part=>{if(!state.project)return;stagePatch({parts:state.project.parts.map(item=>item.id===part.id?part:item)},'调整 '+part.name).catch(report);},onMeasure:result=>{$('measure-result').classList.toggle('hidden',!result);if(result)$('measure-result').textContent=result.pending?'选择第二个模型表面点':result.distance_mm.toFixed(1)+' mm · 两点空间距离';},onError:report});
  } catch(error) {$('viewport-error').textContent='三维视口加载失败：'+error.message;$('viewport-error').classList.remove('hidden');}
  try {state.aiStatus=await api('/ai/status');} catch(error) {report(error);}
  try {state.context=await api('/context');} catch(error) {report(error);}
  try {state.savedProfile=await api('/profile');}catch{}
  try {
    await listProjects();
    const route=new URL(location.href),explicit=route.searchParams.has('project');
    const requestedId=explicit?route.searchParams.get('project'):localStorage.getItem('junior-project-id');
    const existing=state.projects.find(project=>project.id===requestedId);
    if(explicit&&!existing){
      showPage('home');$('home-error').textContent='链接中的项目在本机不存在。请从“我的项目”选择，或开始新的设计。';
    }else{
      if(existing)await selectProject(existing.id);else { state.project=null; showPage('home'); renderHome(); }
      if(route.searchParams.get('view')==='package'&&state.project?.parts?.length)await openPackage();
    }
  } catch(error) {report(error);$('save-state').textContent='连接失败，请确认本地服务已启动';}
  finally {state.busy=false;state.generating=false;if(state.project)render();}

})();
