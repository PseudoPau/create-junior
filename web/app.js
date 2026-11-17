import {openDrawingViewer} from './drawing-viewer.js?v=r1-4';
const API = '/api/workbench';
const state = { page:'home', packageSnapshot:null, homeDraft:localStorage.getItem('junior-home-draft')||'', commandDraft:'', projectDetails:{}, project:null, projects:[], proposal:null, checks:[], coverage:{}, versions:[], preparation:null, dirtyForms:false, context:{revision:null,preferences:{},inventory:[]}, tab:'references', sidebarMode:'tasks', sidebarOpen:true, listMode:'joints', inspectedJointId:null, listPartId:null, designViewKey:null, activeTask:'reference', selectedId:null, busy:false, viewport:null, noticeTimer:null, conversationOpen:false, interactionRecords:[], localMessages:[], conversationProject:null, historyKey:'', polling:false, referenceDraft:'', fitDraft:'', referenceErrors:{}, resolvingReference:null, aiStatus:null, generating:false, generationError:'' };
const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
function node(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) { if (key.startsWith('on')) element.addEventListener(key.slice(2).toLowerCase(),value); else if (key === 'class') element.className=value; else if (key==='checked' || key==='disabled' || key==='selected' || key==='open') element[key]=!!value; else if (value!==null && value!==undefined) element.setAttribute(key,String(value)); }
  for (const child of children.flat(Infinity)) if(child!==null && child!==undefined) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return element;
}
const button = (label, action, className = '', disabled = false) => node('button',{type:'button',class:className,disabled,onClick:()=>Promise.resolve().then(action).catch(report)},label);
const paragraph = text => node('p',{},text);
function report(error) { notice(error?.message || String(error),true); }
function notice(text,error=false) { const target=$('notice'); target.textContent=text; target.className='notice'+(error?' error':''); clearTimeout(state.noticeTimer); state.noticeTimer=setTimeout(()=>target.classList.add('hidden'),error?9000:4500); }
async function api(path,options={}) {
  const response=await fetch(API+path,options); let payload; try { payload=await response.json(); } catch { throw new Error('服务返回了无法读取的数据，请检查本地服务。'); }
  if(!response.ok) { if(response.status===409 && path==='/context')throw new Error('个人偏好或仓库已在其他页面更新，请重新加载后再保存；本次没有覆盖远端记录。'); const detail=payload.detail; const message=typeof detail==='string'?detail:detail?.message || detail?.error || (Array.isArray(detail)?detail.map(item=>item.msg).join('；'):null); throw new Error(message || '请求失败（'+response.status+'）'); }
  return payload;
}
const json = (method,body) => ({method,headers:{'content-type':'application/json'},body:JSON.stringify(body)});
const base = () => '/projects/'+state.project.id;
function displayProject() { return state.proposal?.status==='ready'?{...state.project,...state.proposal.patch}:state.project; }
function displayChecks() { return state.proposal?.status==='ready'?(state.proposal.checks||[]):state.checks; }
function displayCoverage() { return state.proposal?.status==='ready'?(state.proposal.coverage||{}):state.coverage; }
function requireNoProposal() { if(state.proposal?.status==='ready')throw new Error('请先接受或取消当前提案，再开始新的操作。'); }
async function dismissProposal() { const proposal=state.proposal;if(!proposal)return;await guarded(async()=>{if(!proposal.local && proposal.status==='ready')await api(base()+'/proposal/dismiss',json('POST',{expected_revision:state.project.revision,proposal_id:proposal.id}));localStorage.setItem('junior-dismissed-'+state.project.id,proposal.id);state.proposal=null;await refreshData();render();});renderConversation(); }
async function recoverProposal() {
  const response=await fetch(API+base()+'/proposal');
  if(response.status===404)return;
  if(!response.ok)throw new Error('暂时无法恢复待接受候选，请刷新重试。');
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
    state.activeTask=state.proposal.purpose==='manufacturing'?'confirm':'reference';setPanel('tasks',!compactLayout.matches);render();notice('候选已导入，请核对三维、参考证据和检查结果后接受。');
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
async function guarded(action) {if(state.busy)throw new Error('上一个操作正在保存，请稍候。');let completed=false;setBusy(true);try{const result=await action();completed=true;return result;}finally{setBusy(false);if(state.project)renderConversation();if(completed&&state.project&&!state.dirtyForms){renderTasks();renderCandidateActions();}}}
async function refreshData() {
  const project=state.project;
  const results=await Promise.allSettled([api(base()+'/checks'),api(base()+'/versions'),api(base()+'/preparation'),api(base()+'/interaction/history')]);
  if(state.project?.id!==project.id) return;
  state.checks=results[0].status==='fulfilled'?(results[0].value.checks||[]):[]; state.coverage=results[0].status==='fulfilled'?(results[0].value.coverage||{}):{};
  state.versions=results[1].status==='fulfilled'?results[1].value:[];
  state.preparation=results[2].status==='fulfilled'?results[2].value:null;
  if(results[3].status==='fulfilled')state.interactionRecords=results[3].value.records||[];
  for (const result of results) if(result.status==='rejected') report(result.reason);
}
async function mutate(patch,advance=false,proposalRevision=null) {
  if(state.proposal && proposalRevision===null)throw new Error('请先接受或取消当前提案，再修改设计。');
  if(proposalRevision!==null && proposalRevision!==state.project.revision)throw new Error('提案基于旧版本，不能应用到当前设计；请取消并重新生成。');
  return guarded(async()=>{ state.project=await api(base(),json('PUT',{expected_revision:state.project.revision,patch})); state.proposal=null; state.dirtyForms=false; await refreshData(); if(advance) state.activeTask=nextTask(); render(); return state.project; });
}
const tasks=[['reference','参考','参考与构造'],['fit','尺寸','空间 / 使用 / 家具尺寸'],['make','材料','材料与连接'],['confirm','资料','图纸与装配']];
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
  return taskDone('fit')&&pendingRequest()?.stage!=='fit';
}
function goTask(id) {
  if(state.dirtyForms)throw new Error('先保存正在编辑的内容，再切换步骤。');
  if(!taskAvailable(id)){notice(id==='fit'?'先采用参考模型，再调整尺寸。':'先确定目标尺寸，再安排做法。');return;}
  showPage('design');
  clearInspection(false);state.activeTask=id;state.conversationOpen=false;setPanel('tasks',true);renderTasks();renderConversation();focusTask(id);
}
function pendingRequest() {const req=state.preparation?.request;return req?.status==='pending'&&req.base_revision===state.project.revision?req:null;}
function handoffCard() {
  const req=pendingRequest();if(!req)return null;
  const text='处理 Junior 项目“'+state.project.name+'”的请求，项目 ID：'+state.project.id+'，请求 ID：'+req.id+'。';
  return node('div',{class:'flow-status'},node('strong',{},'需求已保存 · 待当前聊天处理'),paragraph('把下面这句话发到 Codex 聊天。设计返回后，这里会显示模型和采用按钮。'),node('code',{class:'handoff-text'},'请继续处理「'+state.project.name+'」的'+({reference:'参考模型',fit:'尺寸调整',manufacturing:'加工方案'})[req.stage||'manufacturing']+'。'),button('复制给当前聊天',async()=>{await navigator.clipboard.writeText(text);notice('已复制，粘贴到当前聊天即可。');},'quiet'),button('检查是否有返回方案',refreshFromSession,'quiet',state.busy));
}
function render() {
  if(!state.project)return;
  const p=state.project, shown=displayProject(), preview=state.proposal?.status==='ready';
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
  $('quick-reference-title').textContent=hasReferences?'参考已收到':'你想复刻哪件家具？';
  $('quick-reference-hint').textContent=hasReferences?'接下来先展开设计构思，确认家具类型、使用方式和需要保留的特点。':'把成品参考带进来，先得到一版可编辑模型，再调整尺寸、材料和连接。';
  $('quick-reference-form').hidden=hasReferences&&!hasModel;
  const sampleEntry=document.querySelector('.sample-entry');if(sampleEntry)sampleEntry.hidden=hasReferences;
  if(document.activeElement!==$('quick-reference-input'))$('quick-reference-input').value=state.referenceDraft;
  $('reference-receipts').replaceChildren(...(p.references||[]).map(ref=>node('div',{class:'reference-receipt-item'},node('span',{},({image:'图片',link:'链接',note:'说明',document:'PDF'})[ref.kind]||'图片'),node('strong',{},ref.name))));
  renderGenerationControls();
  renderGenerationConcept(hasReferences&&!hasModel);
  const handoff=$('generation-handoff');handoff.replaceChildren();if(pendingRequest())handoff.append(handoffCard());
  $('canvas-title').textContent=preview?'待采用的模型候选':hasModel?p.name:'参考与模型';
  $('canvas-status').textContent=preview?'候选预览':p.confirmed_revision===p.revision?'已确认 v'+p.revision:hasModel?'设计中':pendingRequest()?'等待会话返回':hasReferences?'参考已保存':'等待参考';
  document.querySelectorAll('[data-flow]').forEach(el=>{el.disabled=!!state.proposal;el.setAttribute('aria-current',(state.activeTask==='confirm'?'make':state.activeTask)===el.dataset.flow?'step':'false');el.setAttribute('aria-description',taskAvailable(el.dataset.flow)?'':el.dataset.flow==='fit'?'需要先采用参考模型':'需要先确定目标尺寸');});
  $('flow-drawings').disabled=!p.parts?.length;
  renderCandidateActions();
  $('package-button').disabled=!p.parts?.length;
  $('package-button').textContent='制作包 ↗';
  $('undo').disabled=state.versions.filter(version=>version.revision<p.revision).length===0 || preview;
  document.querySelectorAll('[data-phase]').forEach(element=>{ const active=state.activeTask==='reference'?'reference':state.activeTask==='confirm'?'make':'design';element.classList.toggle('active',element.dataset.phase===active); });
  state.viewport?.load(preview?(state.proposal.patch?.parts || p.parts):p.parts||[],{hardware:packagePreview()?.hardware_instances||[]}); state.viewport?.setSelection(state.selectedId);
  document.querySelectorAll('[data-tool]').forEach(element=>{element.disabled=!!state.proposal && ['translate','rotate','scale','mirror'].includes(element.dataset.tool);});
  if(state.proposal){state.viewport?.setTool('select');document.querySelectorAll('[data-tool]').forEach(element=>element.classList.toggle('active',element.dataset.tool==='select'));}
  renderTasks(); renderContext(); renderModelGuide(); renderShortcuts(); renderConversation();
  state.projectDetails[p.id]=p;state.projects=state.projects.map(item=>item.id===p.id?{...item,name:p.name,revision:p.revision,updated_at:p.updated_at}:item);persistDrafts();renderHome();syncPage();
  if(state.page==='package')renderPackagePage();
}
function renderGenerationConcept(show) {
  const host=$('generation-concept');if(!host)return;host.replaceChildren();
  if(!show)return;
  const pending=pendingRequest();
  const card=node('section',{class:'generation-concept-card'},node('span',{class:'eyebrow'},'下一步'),node('h3',{},pending?'设计构思已提交':'展开设计构思'),paragraph(pending?'需求已保存，等待当前聊天返回一版可编辑模型。':'参考已经收到。我会先整理家具类型、主要结构和使用方式，再给你一版可编辑模型。'));
  if(!pending)card.append(node('div',{class:'generation-concept-actions'},button(state.generating?'正在生成…':'生成可编辑模型 →',generateModel,'primary',state.busy||state.generating),button('补充参考',()=>openReferenceComposer(''),'quiet',state.busy||state.generating)));
  host.append(card);
}
function renderTasks() {
  if(!taskAvailable(state.activeTask))state.activeTask=taskDone('reference')?'fit':'reference';
  const list=$('task-list');list.replaceChildren();
  if(state.proposal&&!state.conversationOpen) {
    const proposal=state.proposal; const card=node('div',{class:'preview-banner'},node('strong',{},proposal.status==='ready'?(Object.keys(proposal.patch||{}).length?(proposal.purpose==='manufacturing'?'AI 加工方案 · 待采用':'待接受的设计修改'):'AI 说明'):'AI 暂未形成方案'),paragraph(proposal.summary || proposal.error || '请补充参考或检查 AI 设置。'));
    if(proposal.status==='ready' && Object.keys(proposal.patch||{}).length)card.append(node('div',{class:'action-row'},button(proposal.purpose==='manufacturing'?'采用加工方案':'接受修改',acceptProposal,'primary'),button('不采用这版',dismissProposal)));
    else card.append(button('知道了',dismissProposal));
    if(proposal.status==='ready' && proposal.checks) {
      const checks=[...proposal.checks].sort((a,b)=>(a.severity==='blocker'?0:1)-(b.severity==='blocker'?0:1));
      const details=node('details',{},node('summary',{},'检查结果 · '+checks.filter(check=>check.severity==='blocker').length+' 项阻塞'),checks.map(issueCard));
      const uncovered=proposal.coverage?.not_checked||[];
      if(uncovered.length)details.append(paragraph('尚未覆盖：'+uncovered.join('；')));
      card.append(details);
    }
    list.append(card);
  }
  $('task-panel').classList.toggle('has-design',!!state.project.joints?.length);
  const current=tasks.find(([id])=>id===state.activeTask)||tasks[0];
  const card=node('section',{class:'active-task'});
  card.append(node('div',{class:'active-task-heading'},node('span',{class:'task-kicker'},current[1]),node('h2',{},current[1])));
  const body=node('div',{class:'task-body'});({reference:renderReferenceTask,fit:renderFitTask,make:renderMakeTask,confirm:renderConfirmTask})[current[0]](body);card.append(body);list.append(card);
  const taskViewKey=state.project.id+':'+state.activeTask+':'+(state.proposal?.id||'');if(state.taskViewKey!==taskViewKey){$('task-panel').scrollTop=0;state.taskViewKey=taskViewKey;}
}

function focusTask(id) { const part=state.project.parts?.find(part=>id==='fit'?part.kind==='seat_board':id==='make'?part.features?.length:true); if(part)state.viewport?.focus(part.id); }
function renderReferenceTask(body) {
  const p=state.project,refs=p.references||[],pending=pendingRequest();
  if(!refs.length)body.append(paragraph('给我一个链接、一张图，或说说你想做什么。'));
  if(refs.length){
    body.append(node('div',{class:'reference-receipt'},node('strong',{},'已收到 '+refs.length+' 项参考'),refs.map(ref=>node('div',{class:'reference-receipt-item'},node('span',{},({image:'图片',link:'链接',note:'说明',document:'PDF'})[ref.kind||'image']),node('strong',{},ref.name)))));
    for(const ref of refs.filter(ref=>ref.kind==='link')){
      if(state.resolvingReference===ref.id)body.append(node('p',{class:'flow-status','role':'status'},'正在读取网页标题和文字…'));
      else if(state.referenceErrors[ref.id])body.append(node('div',{class:'flow-status error','role':'alert'},paragraph(state.referenceErrors[ref.id]),button('重新读取链接',()=>resolveReference(ref.id),'quiet')));
      else if(ref.text)body.append(node('details',{class:'reference-extract'},node('summary',{},'已读到网页文字 · 展开查看'),paragraph(ref.text)));
      else body.append(button('读取链接内容',()=>resolveReference(ref.id),'quiet',state.busy));
    }
  }
  if(state.proposal){body.append(button('查看三维候选',()=>setPanel('tasks',false),'primary'));return;}
  const editor=node('form',{class:'reference-entry','data-flow-draft':'reference'});
  const input=node('textarea',{'aria-label':'参考链接或想法',placeholder:'粘贴产品链接，或描述想做的椅子…',maxlength:6000},state.referenceDraft);
  input.addEventListener('input',()=>{state.referenceDraft=input.value;persistDrafts();});
  const error=node('p',{class:'entry-error',role:'alert'});
  const submit=node('button',{type:'submit',class:'primary',disabled:state.busy},refs.length?'添加参考':'带入参考 →');
  editor.append(input,node('div',{class:'action-row'},submit,button('图片 / PDF',()=>$('reference-input').click(),'quiet',state.busy)),error);
  editor.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{await saveReferenceText(input.value);}catch(exc){error.textContent=exc.message;}finally{submit.disabled=false;}});
  body.append(refs.length?node('details',{class:'optional-controls'},node('summary',{},'补充参考'),editor):editor);
  if(p.scope==='unsupported')body.append(node('div',{class:'issue'},p.scope_reason||'当前参考超出首版支持范围。'));
  if(pending)body.append(handoffCard());
  if(pending&&!p.parts?.length)body.append(button('生成可编辑模型 →',generateModel,'primary',state.busy||!!state.resolvingReference));
  else if(!pending&&p.parts?.length)body.append(button('看尺寸方案 →',()=>goTask('fit'),'primary'));
  else if(!pending&&refs.length)body.append(node('div',{class:'flow-next'},paragraph('参考已就位。生成一个可编辑模型候选，再继续调整尺寸和加工条件。'),button('生成可编辑模型 →',generateModel,'primary',state.busy||!!state.resolvingReference)));
}
function renderFitTask(body) {
  const p=state.project;
  if(!p.parts?.length){body.append(paragraph('先完成参考模型，尺寸会从模型带入。'),button('回到参考',()=>goTask('reference'),'primary'));return;}
  const shown=displayProject();
  const activeModule=(shown.modules||[]).find(module=>module.status!=='conflict'&&module.status!=='needs_review')||(shown.modules||[])[0];
  if(activeModule)body.append(moduleFitCard(activeModule,shown));
  body.append(node('div',{class:'fit-summary'},node('span',{class:'eyebrow'},'当前模型 · mm'),node('strong',{},'先看这版尺寸'),modelDimensionFacts()));
  if(state.proposal){body.append(paragraph('画布正在预览调整，采用后再核对尺寸。'));return;}
  const pending=pendingRequest();
  if(pending)body.append(handoffCard());
  const form=node('form',{class:'fit-request','data-flow-draft':'fit'});
  form.append(node('label',{for:'fit-request-text'},'想怎么调整？'));
  const input=node('textarea',{id:'fit-request-text',placeholder:activeModule?'例如：坐高降低 20 mm，或告诉我谁来使用、要完成什么动作。':'例如：给身高120cm的孩子用，放在书桌前。也可以直接说座板宽度改为420mm。',maxlength:2000},state.fitDraft);
  input.addEventListener('input',()=>{state.fitDraft=input.value;persistDrafts();});
  const error=node('p',{class:'entry-error',role:'alert'}),submit=node('button',{type:'submit',class:'primary',disabled:state.busy},pending?'补充调整要求':'按这个要求调整');
  form.append(input,submit,error);
  form.addEventListener('submit',async event=>{event.preventDefault();const text=input.value.trim();if(!text){error.textContent='说说使用者、用途，或想改的尺寸。';return;}submit.disabled=true;try{await requestFit(text);}catch(exc){error.textContent=exc.message;}finally{submit.disabled=false;}});
  body.append(form);
  if(!pending)body.append(button(p.scale?.confirmed?'尺寸已定，继续 →':'就用当前尺寸 →',acceptCurrentDimensions,'quiet',state.busy));
}
function moduleFitCard(module,project) {
  const target=module.target||module.targets||{};
  const anthropometry=module.anthropometry||{};
  const values=[
    ['座宽',target.width_mm??target.seat_width_mm],
    ['座深',target.depth_mm??target.seat_depth_mm],
    ['座高',target.height_mm??target.seat_height_mm],
    ['靠背角',target.angle_deg??target.back_angle_deg]
  ].filter(([,value])=>value!==null&&value!==undefined&&value!=='');
  const kindLabels={support:'支撑',reach:'触达',clearance:'净空',storage:'收纳',surface:'操作面'};
  const statusLabels={inferred:'待确认',target:'目标',confirmed:'已确认',conflict:'有冲突',needs_review:'需重新核对',observed:'已观察'};
  const title=module.name||module.label||kindLabels[module.kind]||'当前使用方式';
  const purpose=module.purpose||'';
  const people=module.occupant||anthropometry.occupant||({adult:'成人',child:'儿童',older_adult:'长者'})[anthropometry.user_group]||anthropometry.posture;
  const parts=(module.affected_part_ids||module.part_ids||[]).map(id=>project.parts?.find(part=>part.id===id)?.name||id).filter(Boolean);
  const status=statusLabels[module.status]||'适配目标';
  const card=node('section',{class:'module-fit-card'},node('div',{class:'module-fit-heading'},node('div',{},node('span',{class:'eyebrow'},'当前适配目标'),node('h3',{},title)),node('span',{class:'module-status'},status)));
  if(purpose)card.append(node('p',{class:'module-fit-purpose'},purpose));
  if(people||module.posture)card.append(node('p',{class:'module-fit-meta'},'使用方式 · '+[people,module.posture&&module.posture!==people?module.posture:null].filter(Boolean).join(' · ')));
  if(values.length)card.append(node('div',{class:'module-target-grid'},values.map(([label,value])=>node('div',{},node('small',{},label),node('strong',{},typeof value==='number'?Math.round(value):value),node('span',{},label==='靠背角'?'°':'mm')))));
  else card.append(node('p',{class:'module-fit-empty'},'先告诉我谁使用、怎么使用，Junior 会把它整理成可调整的尺寸目标。'));
  if(parts.length)card.append(node('p',{class:'module-fit-parts'},'影响部件 · '+parts.join('、')));
  if(module.status==='conflict'||module.status==='needs_review')card.classList.add('is-warning');
  return card;
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
  requireNoProposal();if(pendingRequest())throw new Error('先处理当前调整要求，再确认尺寸。');if(state.fitDraft.trim())throw new Error('先提交调整要求，或清空输入后沿用当前尺寸。');
  const p=state.project;if(!p.parts?.length)throw new Error('先形成参考模型。');
  if(!p.scale?.confirmed)await mutate({scale:{kind:p.scale?.kind||'target',length_mm:p.scale?.length_mm||null,note:p.scale?.note||'采用当前模型各零件尺寸作为本次制作尺寸。',confirmed:true}},false);
  goTask('make');
}
async function requestFit(text) {
  requireNoProposal();if(state.busy)throw new Error('正在保存，请稍后再试。');
  await guarded(async()=>{
    const result=await api(base()+'/interaction',json('POST',{expected_revision:state.project.revision,text,selected_part_id:state.selectedId,stage:'fit'}));
    state.fitDraft='';state.dirtyForms=false;state.conversationOpen=false;
    if(result.proposal)state.proposal=result.proposal;
    await refreshData();state.activeTask='fit';setPanel('tasks',true);render();
    if(result.kind==='reply')notice(result.reply);
  });
}
function proposalImportControl() {
  return node('details',{class:'optional-controls'},node('summary',{},'其他操作'),button('导入设计候选',chooseProposalFile,'',!!state.proposal));
}
function conditionSummary(project=displayProject()) {
  const req=project.requirements||{},rows=[
    ['设计依据',(project.references?.length||0)+' 项参考 · '+(project.parts?.length||0)+' 个部件'],
    ['目标尺寸',project.scale?.note||'采用当前模型尺寸'],
    ['使用条件',[req.load_kg?req.load_kg+' kg 目标载荷':null,({indoor:'室内',outdoor:'室外'})[req.environment]||req.environment,req.body_height_mm?'身高记录 '+req.body_height_mm+' mm':null].filter(Boolean).join(' · ')||'未记录'],
    ['加工路径',({self:'自己加工',shop:'加工店制件，自己装配'})[project.fabrication_mode]||'未记录'],
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
  const options=question.options|| (key==='fabrication_mode'?[['self','自己加工'],['shop','加工店制件，我来装配']]:key==='environment'?[['indoor','室内'],['outdoor','室外']]:null);
  if(options)card.append(node('div',{class:'choice-stack'},options.map(option=>{const val=Array.isArray(option)?option[0]:option.value,label=Array.isArray(option)?option[1]:option.label;return button(label,()=>answerPreparation(question.key,val),'',!!state.proposal);} )));
  else {
    const form=node('div',{},field(key==='load_kg'?'预计最大使用载荷 kg':'补充条件','answer','',key==='load_kg'?'number':'text'));
    form.append(button('记住这个条件，继续',()=>{const answer=key==='load_kg'?number(form,'answer'):value(form,'answer').trim();if(key==='load_kg' && !(answer>0&&answer<=500))throw new Error('请填写 0 到 500 kg 之间的目标载荷。');if(!answer)throw new Error('请补充这个条件。');return answerPreparation(question.key,answer);},'primary',!!state.proposal));card.append(form);
  }
  body.append(card);
}
function renderMakeTask(body) {
  const question=state.preparation?.missing_questions?.[0];
  if(question){body.append(paragraph('先补齐制作条件，再确定材料、连接和装配做法。'));renderQuestion(body,question);return;}
  renderConfirmTask(body);
}
async function requestPreparation(text='',stage='manufacturing') {
  if(state.busy)throw new Error('正在保存上一项，请稍候再提交。');
  requireNoProposal();
  await guarded(async()=>{await api(base()+'/preparation/request',json('POST',{expected_revision:state.project.revision,text,stage}));await refreshData();setPanel('tasks',true);render();notice('需求已保存，下一步说明留在当前任务中。');});
}
function partName(id) { return (displayProject().parts||[]).find(part=>part.id===id)?.name||id; }
function jointName(joint) { return joint.name||(joint.part_ids||[]).map(partName).join(' ↔ '); }
function packagePreview() {return state.proposal?state.proposal.package_preview:state.preparation?.package_preview;}
function showList(mode) {showPage('design');setPanel('context',true);clearInspection(false);state.tab='lists';state.listMode=mode;renderContext();}
function clearInspection(redraw=true) {state.inspectedJointId=null;$('selection-label').textContent=displayProject()?.parts?.find(p=>p.id===state.selectedId)?.name||'尚未选择部件';state.viewport?.setExploded(false);state.viewport?.clearInspection();renderModelGuide();if(redraw)renderContext();}
function inspectJoint(id) {
  showPage('design');
  const joint=(displayProject().joints||[]).find(item=>item.id===id);if(!joint)return;state.conversationOpen=false;renderConversation();
  if(compactLayout.matches){setPanel('tasks',false);setPanel('context',false);}else setPanel('context',true);
  state.selectedId=null;state.viewport?.setSelection(null);$('selection-label').textContent=jointName(joint);state.inspectedJointId=id;state.tab='lists';state.listMode='joints';
  state.viewport?.setTool('select');document.querySelectorAll('[data-tool]').forEach(el=>el.classList.toggle('active',el.dataset.tool==='select'));
  state.viewport?.inspectConnection(joint.part_ids,joint.feature_ids||[],joint.id);state.viewport?.setExploded(true);renderContext();renderModelGuide();
}
function renderModelGuide() {
  const host=$('model-guide');if(!host)return;
  const joints=displayProject()?.joints||[],index=joints.findIndex(j=>j.id===state.inspectedJointId),joint=joints[index];
  host.classList.toggle('hidden',!joint);host.replaceChildren();renderShortcuts();if(!joint)return;
  const previous=button('←',()=>inspectJoint(joints[index-1].id),'',index===0);previous.setAttribute('aria-label','上一处连接');
  const next=button(index===joints.length-1?'完成 ✓':'下一处 →',()=>index===joints.length-1?clearInspection():inspectJoint(joints[index+1].id),'primary');
  const details=button('细节',()=>setPanel('context',true),'quiet');details.setAttribute('aria-label','查看连接资料');
  const explode=button(state.viewport?.exploded?'收拢':'展开',()=>{state.viewport?.setExploded(!state.viewport?.exploded);renderContext();renderModelGuide();},'quiet');explode.setAttribute('aria-label',state.viewport?.exploded?'收拢连接':'展开连接');
  const close=button('×',()=>clearInspection(),'quiet');close.setAttribute('aria-label','结束连接查看');
  host.append(node('div',{class:'guide-copy'},node('span',{class:'guide-count'},'连接图 · '+(index+1)+' / '+joints.length),node('strong',{},jointName(joint))),node('div',{class:'guide-nav'},previous,next,explode,details,close));
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
function renderConfirmTask(body) {
  const p=state.project,proposal=state.proposal,pkg=packagePreview(),blockers=displayChecks().filter(x=>x.severity==='blocker');
  const confirmed=!proposal&&p.confirmed_revision===p.revision,hasAssembly=!!displayProject().joints?.length;
  const question=state.preparation?.missing_questions?.[0];
  body.append(node('div',{class:'guide-intro'},node('span',{class:'guide-spark','aria-hidden':'true'},confirmed?'✓':'✦'),node('div',{},node('h2',{},confirmed?'设计资料已确认':hasAssembly?'看图装起来':'把做法补齐'),node('p',{},confirmed?'查看采购、加工与装配资料；未覆盖的工程事项仍需核对。':hasAssembly?'展开连接，看清零件和五金的位置。':'按现有尺寸，设定材料、连接与装配。'))));
  if(question&&!proposal)renderQuestion(body,question);
  renderPlanPreview(body,pkg);
  if(hasAssembly)body.append(button('查看装配爆炸图',()=>inspectJoint(displayProject().joints[0].id),'primary guide-start'));
  if(!confirmed&&(!hasAssembly||blockers.length))body.append(button(hasAssembly?'完善加工方案':'设定加工方案',()=>requestPreparation('按当前尺寸和使用条件，完成选材、连接、孔位、五金与装配设定。'),hasAssembly?'quiet':'primary guide-start',!!proposal||!!question||state.preparation?.request?.status==='pending'));
  const documents=node('div',{class:'guide-documents'});
  documents.append(button('一页开工总览 ↗',openOverview,'',!pkg?.drawings?.some(sheet=>sheet.sheet_type==='assembly_overview')),button('完整设计包',openPackage,'quiet',!!proposal||!p.parts?.length));body.append(documents);
  if(!confirmed)body.append(button(blockers.length?'查看 '+blockers.length+' 项检查':'确认这版设计',()=>showList('review'),'quiet review-final',!!proposal));
  if(state.preparation?.request?.status==='pending')body.append(node('div',{class:'request-status'},'要求已记录',button('刷新方案',refreshFromSession,'quiet',!!proposal||state.dirtyForms)));
  const conditions=node('details',{class:'optional-controls'},node('summary',{},'使用条件'),conditionSummary());
  conditions.append(button('调整尺寸',()=>{state.activeTask='fit';clearInspection(false);renderTasks();focusTask('fit');},'quiet',!!proposal),button('调整加工条件',()=>{state.activeTask='make';clearInspection(false);renderTasks();},'quiet',!!proposal));body.append(conditions);
}
function renderReview(content) {
  const p=state.project,checks=displayChecks(),blockers=checks.filter(x=>x.severity==='blocker'),coverage=displayCoverage();
  content.append(node('h3',{},'确认这一版'),paragraph('v'+p.revision+' · '+p.parts.length+' 件 · '+p.joints.length+' 处连接'));
  if(blockers.length)content.append(blockers.map(issueCard));
  const detail=node('details',{class:'optional-controls'},node('summary',{},'检查结果与范围'),checks.filter(x=>x.severity!=='blocker').map(issueCard));
  if(coverage.checked?.length)detail.append(paragraph('已检查：'+coverage.checked.join('；')));
  if(coverage.not_checked?.length)detail.append(paragraph('未计算 / 未验证：'+coverage.not_checked.join('；')));
  content.append(detail);
  if(p.assumptions?.length)content.append(node('details',{class:'optional-controls'},node('summary',{},'设计设定'),node('ul',{},p.assumptions.map(item=>node('li',{},item)))));
  const ack=boolField('已核对设计、检查结果与设计设定','acknowledged',p.acknowledged_limits);content.append(ack);
  content.append(button(p.confirmed_revision===p.revision?'✓ 已确认':'确认设计，准备出包',async()=>{if(state.proposal)throw new Error('请先采用或取消当前方案。');if(!ack.querySelector('input').checked)throw new Error('请先核对设计与检查结果。');await guarded(async()=>{state.project=await api(base()+'/confirm',json('POST',{expected_revision:state.project.revision,acknowledged_limits:true}));await refreshData();render();notice('设计已确认，可以生成加工资料。');});},'primary',blockers.length>0||!!state.proposal||p.confirmed_revision===p.revision));
}

async function refreshFromSession() {
  if(state.busy||state.proposal||state.dirtyForms||!state.project)return;
  await guarded(async()=>{const current=await api(base());state.project=current;await refreshData();await recoverProposal();if(state.proposal?.purpose==='manufacturing')state.activeTask='confirm';render();});
}
function issueCard(check) {return node('div',{class:'issue '+(check.severity==='blocker'?'':check.severity==='warning'?'warning':'pass')},node('strong',{},check.severity==='blocker'?'设计检查':check.severity==='warning'?'提醒':'已记录'),check.message,(check.part_ids||[]).map(id=>button('定位 '+partName(id),()=>{clearInspection(false);state.selectedId=id;state.viewport?.focus(id);state.tab='layers';setPanel('context',true);renderContext();})));}
function renderGenerationControls() {
  const start=$('empty-reference-start');
  start.disabled=state.busy||state.generating||!!state.proposal||(!state.referenceDraft.trim()&&!state.project?.references?.length);
  start.textContent=state.generating?'正在生成模型…':state.aiStatus?.ready?'生成可编辑模型 →':pendingRequest()?'查看 / 更新设计请求 →':'提交设计请求 →';
  $('quick-reference-error').textContent=state.generationError;
  $('ai-settings').textContent='设置';
}
function renderCandidateActions() {
  const host=$('candidate-actions'),p=state.proposal;host.replaceChildren();host.hidden=p?.status!=='ready';
  if(host.hidden)return;
  const blockers=(p.checks||[]).filter(x=>x.severity==='blocker').length;
  host.append(node('div',{},node('strong',{},p.source==='demo'?'CAFE CHAIR · 样例候选':'模型候选 · 等待你采用'),node('small',{},(p.patch.parts?.length||state.project.parts.length)+' 个部件 · '+blockers+' 项待完善')),button('采用模型',acceptProposal,'primary',state.busy),button('不采用',dismissProposal,'',state.busy),button('查看依据与检查',()=>setPanel('tasks',true),'quiet'));
}
async function beginGeneration() {
  requireNoProposal();if(state.busy||state.generating)return;
  state.generationError='';
  try {if(state.referenceDraft.trim())await saveReferenceText(state.referenceDraft);await generateModel();}
  catch(error){state.generationError=error.message;render();}
}
async function generateModel() {
  requireNoProposal();if(state.busy||state.generating)return;
  if(!state.project.references?.length)throw new Error('先添加图片、链接或文字参考。');
  state.generating=true;renderGenerationControls();
  const projectId=state.project.id,revision=state.project.revision;
  try {
    await guarded(async()=>{
      const result=await api('/projects/'+projectId+'/analyze',json('POST',{expected_revision:revision}));
      if(state.project.id!==projectId||state.project.revision!==revision)throw new Error('项目已变化，请刷新后重新生成。');
      state.activeTask='reference';state.conversationOpen=false;
      if(result.status==='ready'){state.proposal=result;state.generationError='';setPanel('tasks',!compactLayout.matches);}
      else if(result.status==='handoff'){state.generationError='';setPanel('tasks',false,{persist:false});}
      else {state.generationError=result.error||'未生成候选，请重试或使用会话协作。';setPanel('tasks',false,{persist:false});}
      await refreshData();render();
    });
  } finally {state.generating=false;render();}
}
async function runAnalysis() {return beginGeneration();}
async function openCafeDemo() {
  if(state.busy||state.dirtyForms)throw new Error('请先保存正在编辑的条件。');persistDrafts();
  await guarded(async()=>{
    const result=await api('/demos/cafe-chair',{method:'POST'});
    state.project=result.project;state.referenceDraft='';state.fitDraft='';state.commandDraft='';$('command-input').value='';showPage('design');state.proposal=result.proposal;state.selectedId=null;state.activeTask='reference';state.generationError='';state.conversationOpen=false;
    localStorage.setItem('junior-project-id',state.project.id);
    await listProjects();await refreshData();setPanel('tasks',!compactLayout.matches);render();
  });
}
async function openAiSettings() {
  state.aiStatus=await api('/ai/status');
  const status=state.aiStatus,host=$('ai-settings-content');host.replaceChildren();
  host.append(node('p',{},'当前通道：'+status.label),node('h3',{},'会话协作 · 无需密钥'),paragraph('提交设计请求后，把交接文字发给当前聊天。我整理并导入候选，页面会显示模型。网页不会自动调用这段聊天。'),node('h3',{},'样例体验 · 立即看到模型'),paragraph('使用首页的“体验 CAFE CHAIR 样例”，新建独立项目体验编辑、检查和图纸。不会声称识别了你的参考。'),node('h3',{},'在线 AI · 自动生成'),paragraph('在项目目录的 .env 中填写以下配置；使用支持图片和 JSON 输出的模型。密钥只存服务端，不填入网页。'),node('pre',{class:'setup-code'},'CREATE_JUNIOR_AI_PROVIDER=openai_compatible\nCREATE_JUNIOR_AI_BASE_URL=https://你的服务地址/v1\nCREATE_JUNIOR_AI_API_KEY=你的密钥\nCREATE_JUNIOR_AI_MODEL=服务商提供的视觉模型名称'),paragraph('保存后重启本地服务：'),node('pre',{class:'setup-code'},'uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file .env'),paragraph('填写状态：'+Object.entries(status.configured).map(([key,ok])=>key+' '+(ok?'已填写':'未填写')).join(' · ')));
  $('ai-dialog').showModal();renderGenerationControls();
}
async function acceptProposal() {
  const proposal=state.proposal;if(!proposal)return;
  if(proposal.base_revision!==state.project.revision)throw new Error('提案基于旧版本，不能应用到当前设计；请取消并重新生成。');
  if(proposal.local){await mutate(proposal.patch,false,proposal.base_revision);return;}
  await guarded(async()=>{state.project=await api(base()+'/proposal/accept',json('POST',{expected_revision:state.project.revision,proposal_id:proposal.id,accept_connections:proposal.purpose==='manufacturing'}));state.proposal=null;state.dirtyForms=false;await refreshData();state.activeTask=nextTask();setPanel('tasks',true);render();});
}
async function stagePatch(patch,summary) {
  if(state.busy || state.proposal){notice(state.busy?'正在保存，请稍候。':'请先接受或取消当前修改。');render();return;}
  try {
    await guarded(async()=>{
      state.proposal=await api(base()+'/proposal/import',json('POST',{expected_revision:state.project.revision,summary,patch,purpose:'design'}));
      setPanel('tasks',true);state.dirtyForms=false;render();
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
  await guarded(async()=>{for(const file of files)state.project=await api(base()+'/references?filename='+encodeURIComponent(file.name),{method:'POST',headers:{'content-type':file.type},body:file});state.proposal=null;state.dirtyForms=false;await refreshData();state.activeTask='reference';state.tab='references';state.conversationOpen=false;setPanel('tasks',!!state.project.parts?.length,{persist:false});render();notice('参考已收到。');});
}
function openReferenceComposer(initial='') {
  requireNoProposal();$('reference-text').value=initial;$('reference-error').textContent='';$('reference-dialog').showModal();$('reference-text').focus();
}
async function saveReferenceText(text) {
  requireReferenceEdit();text=text.trim();if(!text)throw new Error('粘贴一个链接，或写下参考说明。');
  const isLink=/^https?:\/\/\S+$/i.test(text);
  if(/^[a-z][a-z0-9+.-]*:\/\//i.test(text)&&!isLink)throw new Error('链接请使用完整的 http 或 https 地址。');
  let added;
  await guarded(async()=>{
    state.project=await api(base()+'/references/item',json('POST',{expected_revision:state.project.revision,kind:isLink?'link':'note',...(isLink?{url:text}:{text})}));
    added=state.project.references.at(-1);state.referenceDraft='';state.dirtyForms=false;state.conversationOpen=false;await refreshData();state.activeTask='reference';setPanel('tasks',!!state.project.parts?.length,{persist:false});render();
  });
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
async function restoreVersion(revision) {await guarded(async()=>{state.project=await api(base()+'/restore/'+revision,json('POST',{expected_revision:state.project.revision}));state.proposal=null;await refreshData();state.activeTask=nextTask();setPanel('tasks',true);render();notice('已恢复为新的草稿版本。');});}
function selectPart(id,{focus=false}={}) {
  clearInspection(false);state.selectedId=id;state.viewport?.setSelection(id);
  const part=displayProject()?.parts?.find(part=>part.id===id);
  $('selection-label').textContent=part?.name||'尚未选择部件';
  if(part){setPanel('context',true);state.tab='layers';if(focus)state.viewport?.focus(id);}
  renderContext();
}
function renderLayers(content) {
  const project=displayProject(),parts=project.parts||[],part=parts.find(item=>item.id===state.selectedId);
  if(!parts.length){content.append(node('div',{class:'empty-note'},'接受参考结构后，部件会出现在这里。'));return;}
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
  content.append(node('div',{class:'list-tabs'},[['joints','连接'],['cut','下料'],['hardware','五金'],['review','核对']].map(([mode,label])=>button(label,()=>showList(mode),state.listMode===mode?'active':''))));
  if(state.listMode==='review'){renderReview(content);return;}
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

async function openPackage() {
  if(state.dirtyForms)throw new Error('先保存正在编辑的条件，再查看制作包。');
  if(state.proposal)throw new Error('先采用或取消当前候选，再查看当前设计的制作包。');
  const projectId=state.project.id,revision=state.project.revision;
  const pkg=await api('/projects/'+projectId+'/package');
  if(state.project.id!==projectId||state.project.revision!==revision)throw new Error('设计已变化，请重新打开制作包。');
  state.packageSnapshot={project:clone(state.project),pkg};
  showPage('package');renderPackagePage();
}
function renderPackagePage() {
  const host=$('package-page-content'),snapshot=state.packageSnapshot;if(!snapshot)return;
  const {project,pkg}=snapshot,stale=project.id!==state.project.id||pkg.revision!==state.project.revision;
  host.replaceChildren();
  const status=stale?'设计已更新 · 当前显示历史快照':pkg.status==='ready'?'已确认设计资料 · 待加工核对':'设计资料草稿';
  const summary=node('section',{class:'package-summary'},node('div',{},node('h2',{},project.name),paragraph('v'+pkg.revision+' · '+(pkg.parts?.length||0)+' 个板件 · '+(pkg.joints?.length||0)+' 处连接'),node('span',{class:'tag'},status)),node('div',{class:'package-actions'},button('更新资料',openPackage,'quiet'),button('下载设计包 ZIP',()=>downloadPackage({id:project.id,name:project.name,revision:pkg.revision}),'primary',stale||pkg.status!=='ready')));
  host.append(summary);
  const blockers=(pkg.checks||[]).filter(check=>check.severity==='blocker');
  if(stale)host.append(node('p',{class:'preview-banner'},'设计已修改，重新更新资料后再下载。历史快照不会覆盖当前设计。'));
  else if(pkg.status!=='ready')host.append(node('div',{class:'preview-banner'},paragraph(blockers.length?'还有 '+blockers.length+' 项需要处理；可以先浏览草稿。':'请核对当前设计与检查范围，确认后下载。'),button(blockers.length?'查看待解决项':'核对并确认设计',()=>showList('review'))));
  const moduleRows=pkg.modules||project.modules||[];
  if(moduleRows.length){
    const moduleSection=node('section',{class:'package-module-summary'},node('span',{class:'eyebrow'},'适配目标'),node('h2',{},'这件家具为谁、怎么使用'),paragraph('制作资料沿用当前设计版本的使用模块；它表达适配目标，不替代承载和安全复核。'));
    moduleRows.forEach(module=>{
      const target=module.target||{},labels={seat_width_mm:'座宽',seat_depth_mm:'座深',seat_height_mm:'座高',back_angle_deg:'靠背角'};
      const values=Object.entries(target).filter(([,value])=>value!==null&&value!==undefined&&value!=='').map(([key,value])=>labels[key]?labels[key]+' '+value+(key.endsWith('_deg')?'°':' mm'):key+' '+value).join(' · ');
      const parts=(module.affected_part_ids||[]).map(id=>(project.parts||[]).find(part=>part.id===id)?.name||id).filter(Boolean).join('、');
      moduleSection.append(node('article',{class:'package-module-card'},node('div',{},node('strong',{},module.name||'使用模块'),node('p',{},[module.occupant,module.posture].filter(Boolean).join(' · ')||'使用条件待补充')),node('span',{class:'tag'},({inferred:'待确认',target:'目标',confirmed:'已确认',conflict:'有冲突',needs_review:'需重新核对'})[module.status]||'适配目标'),values?node('p',{},values):null,parts?node('small',{},'关联部件 · '+parts):null));
    });
    host.append(moduleSection);
  }
  const nav=node('nav',{class:'package-section-nav','aria-label':'制作资料目录'});for(const [id,label] of [['purchase','我买什么'],['workshop','交给加工店什么'],['assembly','我怎么装']])nav.append(button(label,()=>$('package-'+id).scrollIntoView({behavior:'smooth',block:'start'})));host.append(nav);
  const purchase=node('section',{id:'package-purchase',class:'package-section'},node('span',{class:'eyebrow'},'01 · 采购与下料'),node('h2',{},'我买什么'),paragraph('板件尺寸单位为 mm。毛坯余量、锯缝和实际供料规格需与加工者核对。'));
  purchase.append(node('h3',{},'板件清单'),node('div',{class:'table-scroll'},renderRecords(pkg.cut_list||[])),node('h3',{},'五金采购'),node('div',{class:'table-scroll'},renderRecords(pkg.hardware||[])));host.append(purchase);
  const workshop=node('section',{id:'package-workshop',class:'package-section'},node('span',{class:'eyebrow'},'02 · 加工资料'),node('h2',{},'交给加工店什么'),paragraph(({self:'当前计划：自行加工。',shop:'当前计划：加工店制件，自己装配。'})[pkg.fabrication_mode]||'制作方式尚未确定。'),paragraph('按零件编号查看图纸、加工面和连接。图纸可通过浏览器打印；本版 ZIP 包含 SVG 图纸与结构化设计数据。'));
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
}
function renderRecords(records) {
  if(!records.length)return paragraph('未生成');
  const known=[['name','名称'],['part_id','编号'],['quantity','数量'],['material','材料'],['material_name','材料'],['size_mm','尺寸 mm'],['stock_size_mm','毛坯尺寸 mm'],['dimensions_mm','尺寸 mm'],['spec','规格'],['grain_axis','纹理轴']];
  const columns=known.filter(([key])=>records.some(record=>record[key]!==undefined));
  return node('table',{class:'compact-table'},node('thead',{},node('tr',{},columns.map(([,label])=>node('th',{},label)))),node('tbody',{},records.map(record=>node('tr',{},columns.map(([key])=>node('td',{},Array.isArray(record[key])?record[key].join(' × '):typeof record[key]==='object'?Object.values(record[key]||{}).join(' × '):record[key]??''))))));
}
async function downloadPackage(snapshot) {const response=await fetch(API+'/projects/'+encodeURIComponent(snapshot.id)+'/package/download?revision='+encodeURIComponent(snapshot.revision));if(!response.ok)throw new Error('此设计包版本已变化或尚不可下载，请关闭后重新核对加工包。');const url=URL.createObjectURL(await response.blob());const link=node('a',{href:url,download:snapshot.name+'-v'+snapshot.revision+'.zip'});link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
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
  if(open&&compactLayout.matches)setPanel('tasks',false);
  renderConversation();if(!state.dirtyForms)renderTasks();
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
  const labels={pending:'等待会话处理',ready:'修改候选',completed:'已完成',stale:'基于旧版本',superseded:'已合并到新请求',cancelled:'方案未采用',revision_requested:'等待调整方案',error:'发送未完成'};
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
  const submittedDraft=$('command-input').value,text=submittedDraft.trim();if(!text||!state.project||state.busy)return;
  const submittedProjectId=state.project.id;
  const clearSubmittedDraft=()=>{if(state.project?.id===submittedProjectId&&$('command-input').value===submittedDraft)setCommandDraft('');};
  if(/^https?:\/\/\S+$/i.test(text)&&!state.proposal){try{const reply=await saveReferenceText(text);clearSubmittedDraft();conversationReply(text,reply);notice(reply);}catch(error){openConversation(true);conversationReply(text,error.message,'error');}return;}
  openConversation(true);
  const local=localNavigation(text);
  if(local){conversationReply(text,local);clearSubmittedDraft();return;}
  if(state.proposal){conversationReply(text,'先采用或取消当前修改，再继续调整。','error');return;}
  if(state.dirtyForms){conversationReply(text,'先保存正在编辑的条件，再把它们一起带入这次请求。','error');return;}
  try {
    await guarded(async()=>{
      const result=await api(base()+'/interaction',json('POST',{expected_revision:state.project.revision,text,selected_part_id:state.selectedId}));
      clearSubmittedDraft();
      if(result.proposal){state.proposal=result.proposal;clearInspection(false);await refreshData();render();if(result.record?.part_id)state.viewport?.focus(result.record.part_id);}
      await refreshInteractionHistory();openConversation(true);
    });
  }catch(error){conversationReply(text,error.message||String(error),'error');}
  renderConversation();
}
async function pollInteractions() {
  if(state.polling||state.busy||document.hidden||!state.project)return;
  state.polling=true;
  try {
    const history=await refreshInteractionHistory();if(!history||state.dirtyForms)return;
    const ready=(history.records||[]).find(r=>r.status==='ready'&&r.proposal_id!==localStorage.getItem('junior-dismissed-'+state.project.id));
    if(history.revision!==state.project.revision||ready&&!state.proposal){await refreshFromSession();if(ready){state.conversationOpen=false;if(compactLayout.matches){state.sidebarOpen=false;state.sidebarMode='tasks';syncSidebar();}else{setPanel('tasks',true);}render();}}
  } finally {state.polling=false;}
}

const compactLayout=matchMedia('(max-width:900px), (max-height:600px)');
function syncSidebar() {
  const open=state.sidebarOpen,guide=state.sidebarMode==='tasks';
  document.body.classList.toggle('sidebar-collapsed',!open);
  $('work-sidebar').inert=!open;
  $('task-panel').hidden=!guide;$('context-panel').hidden=guide;
  $('sidebar-context-heading').hidden=guide;
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
  toggle.setAttribute('aria-label',open?'收起工作侧栏':'展开工作侧栏');toggle.title=toggle.getAttribute('aria-label');
}
function setPanel(name,open,{persist=true}={}) {
  if(open)state.sidebarMode=name;
  $('sidebar-library').open=false;
  state.sidebarOpen=open;syncSidebar();
  if(persist&&!compactLayout.matches)localStorage.setItem('junior-sidebar-open',open?'open':'closed');
}
function applyLayout(){state.sidebarOpen=!compactLayout.matches&&localStorage.getItem('junior-sidebar-open')!=='closed';syncSidebar();}
$('toggle-sidebar').addEventListener('click',()=>setPanel(state.sidebarMode,!state.sidebarOpen));
document.querySelector('[data-sidebar="tasks"]').addEventListener('click',()=>setPanel('tasks',true));
compactLayout.addEventListener('change',applyLayout);applyLayout();

document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;if($('sidebar-library').open){$('sidebar-library').open=false;return;}if(state.inspectedJointId)clearInspection();});
document.addEventListener('input',event=>{if(event.target.closest('.task-panel,.context-panel')&&!event.target.closest('.layer-item,[data-flow-draft]'))state.dirtyForms=true;});
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
$('undo').addEventListener('click',()=>{const previous=[...state.versions].filter(version=>version.revision<state.project.revision).sort((a,b)=>b.revision-a.revision)[0];if(previous)restoreVersion(previous.revision).catch(report);});
$('package-button').addEventListener('click',()=>openPackage().catch(report));
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
$('flow-drawings').addEventListener('click',()=>openPackage().catch(report));
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
  $('home-channel-note').textContent=state.aiStatus?.ready?'在线 AI 已配置：提交后将生成模型候选。':'原型会话协作：先保存需求，再由当前聊天返回可编辑模型。';
  $('home-start').disabled=state.busy||!state.homeDraft.trim();$('home-upload').disabled=state.busy;$('home-demo').disabled=state.busy;
  const list=$('home-project-list');list.replaceChildren();
  for(const item of state.projects){const p=state.projectDetails[item.id],current=item.id===state.project?.id,pending=current&&state.proposal;
    const status=pending?'有候选待采用':p?.confirmed_revision===p?.revision&&p?'设计资料已确认':p?.parts?.length?'继续调整设计':p?.references?.length?'参考已保存':'继续项目';
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
    if(upload)$('reference-input').click();else {await beginGeneration();}
    state.homeDraft='';localStorage.removeItem('junior-home-draft');renderHome();
  }catch(error){$('home-error').textContent=error.message;report(error);}
}
$('home-link').addEventListener('click',event=>{event.preventDefault();showPage('design');});
$('command-input').addEventListener('input',event=>{state.commandDraft=event.target.value;persistDrafts();});
$('home-input').addEventListener('input',event=>{state.homeDraft=event.target.value;localStorage.setItem('junior-home-draft',state.homeDraft);$('home-start').disabled=state.busy||!state.homeDraft.trim();});
$('home-form').addEventListener('submit',event=>{event.preventDefault();beginFromHome();});
$('home-upload').addEventListener('click',()=>beginFromHome({upload:true}));
$('home-demo').addEventListener('click',()=>openCafeDemo().catch(report));
$('home-project-refresh').addEventListener('click',()=>listProjects().catch(report));
$('package-back').addEventListener('click',()=>showPage('design'));
window.addEventListener('beforeunload',event=>{persistDrafts();if(state.dirtyForms){event.preventDefault();event.returnValue='';}});

setInterval(()=>pollInteractions().catch(()=>{}),4000);

(async()=>{
  try {
    const {WorkshopViewport}=await import('./viewport.js?v=r1-4');state.viewport=new WorkshopViewport($('viewport'),{onSelect:id=>selectPart(id),onSelectHardware:instance=>inspectJoint(instance.joint_id),onTransform:part=>{if(!state.project)return;stagePatch({parts:state.project.parts.map(item=>item.id===part.id?part:item),joints:state.project.joints.map(joint=>joint.part_ids.includes(part.id)?{...joint,confirmed:false}:joint)},'调整 '+part.name).catch(report);},onMeasure:result=>{$('measure-result').classList.toggle('hidden',!result);if(result)$('measure-result').textContent=result.pending?'选择第二个模型表面点':result.distance_mm.toFixed(1)+' mm · 两点空间距离';},onError:report});
  } catch(error) {$('viewport-error').textContent='三维视口加载失败：'+error.message;$('viewport-error').classList.remove('hidden');}
  try {state.aiStatus=await api('/ai/status');} catch(error) {report(error);}
  try {state.context=await api('/context');} catch(error) {report(error);}
  try {
    await listProjects();
    const route=new URL(location.href),explicit=route.searchParams.has('project');
    const requestedId=explicit?route.searchParams.get('project'):localStorage.getItem('junior-project-id');
    const existing=state.projects.find(project=>project.id===requestedId)||(explicit?null:state.projects[0]);
    if(explicit&&!existing){
      showPage('home');$('home-error').textContent='链接中的项目在本机不存在。请从“我的项目”选择，或开始新的设计。';
    }else{
      if(existing)await selectProject(existing.id);else await newProject();
      if(route.searchParams.get('view')==='package'&&state.project?.parts?.length)await openPackage();
    }
  } catch(error) {report(error);$('save-state').textContent='连接失败，请确认本地服务已启动';}

})();
