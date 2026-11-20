// A review surface presents one actionable issue and keeps diagnostics on demand.
const el=(tag,attrs={},...children)=>{
  const element=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)){
    if(value===null||value===undefined)continue;
    if(key==='class')element.className=value;
    else element.setAttribute(key,String(value));
  }
  for(const child of children.flat(Infinity))if(child!==null&&child!==undefined)element.append(child instanceof Node?child:String(child));
  return element;
};

const issueTitles={
  module_constraint_violation:'这项尺寸需要调整',module_constraint_missing:'补齐尺寸目标',
  module_geometry_mismatch:'让模型与尺寸目标一致',module_fit_pending:'先完成尺寸应用',
  joint_holes_misaligned:'这处连接的孔位需要对齐',joint_parts_separated:'把连接部件放回正确位置',
  joint_features_missing:'补齐这处连接的孔位',joint_features_incomplete:'补齐连接两侧的加工孔',
  joint_feature_missing:'恢复缺失的加工孔',joint_feature_owner:'核对孔位所属部件',
  feature_invalid:'这处加工孔需要调整',joints_missing:'先补齐连接做法',
  assembly_disconnected:'还有部件没有连接到主体',hardware_missing:'补齐这处连接的五金',
  hardware_invalid:'补齐五金规格与数量',material_missing:'补齐板件材料',
  grain_unconfirmed:'选择板件的纹理方向',assembly_note_missing:'补齐装配做法',
  reference_views_missing:'先保存一项参考',scope_unconfirmed:'先确认这版构造',
};

function jointForCheck(project,check){
  const message=String(check.message||'');
  return (project.joints||[]).find(joint=>message.startsWith(joint.id+'：')||message.startsWith(joint.id+'/'));
}

function readableMessage(project,message){
  let text=String(message||'');
  const records=[...(project.parts||[]),...(project.joints||[]),...(project.modules||[])].sort((a,b)=>b.id.length-a.id.length);
  for(const record of records)if(record.name)text=text.split(record.id).join(record.name);
  return text;
}

/**
 * Callbacks own persistence, revision checks and navigation. None of the visual
 * states here mark checks as passed or modify a project directly.
 */
export function renderReviewFlow(host,options){
  const {project,checks=[],coverage={},busy=false}=options;
  const packagePreview=options.packagePreview||{};
  const blockers=checks.filter(check=>check.severity==='blocker');
  // Geometry and missing information must be resolved before any consent step.
  const faults=blockers.filter(check=>check.code!=='joint_unconfirmed');
  const current=faults[0]||blockers[0];
  const joint=current?jointForCheck(project,current):null;
  const canAcceptJoint=current?.code==='joint_unconfirmed'&&joint&&!faults.length;
  const surface=el('section',{class:'review-flow','aria-label':'设计核对'});
  const footer=el('footer',{class:'review-flow-footer'});
  const error=el('p',{class:'review-flow-error',role:'alert'});
  const action=(label,callback,primary=false)=>{
    const button=el('button',{type:'button',class:primary?'primary review-flow-primary':'quiet review-flow-link'},label);
    button.disabled=busy||typeof callback!=='function';
    button.addEventListener('click',async()=>{
      error.textContent='';button.disabled=true;
      try{await callback();}catch(exc){error.textContent=exc?.message||String(exc);}
      finally{button.disabled=busy||typeof callback!=='function';}
    });
    return button;
  };

  const heading=el('header',{class:'review-flow-heading'},el('div',{class:'review-flow-heading-line'},el('span',{class:'eyebrow'},'做法 · 出包前核对'),el('span',{},'v'+project.revision+' · '+(project.parts||[]).length+' 个板件')));
  if(!current)heading.append(el('h2',{},'这版设计可以出包'));
  surface.append(heading);

  if(current){
    const affected=current.part_ids||joint?.part_ids||[];
    const card=el('article',{class:'review-flow-card'+(canAcceptJoint?' is-consent':' is-blocker')});
    const jointName=joint?.name||joint?.part_ids?.map(id=>project.parts.find(part=>part.id===id)?.name||id).join(' ↔ ');
    card.append(el('div',{class:'review-flow-card-top'},el('span',{},canAcceptJoint?'连接做法':'需要处理'),el('span',{},'剩余 '+blockers.length+' 项')),
      el('h3',{},canAcceptJoint?jointName:(issueTitles[current.code]||'完善这处设计')));
    if(affected.length&&!canAcceptJoint)card.append(el('p',{class:'review-flow-affected'},'涉及 '+affected.map(id=>project.parts?.find(part=>part.id===id)?.name||id).join('、')));

    if(canAcceptJoint){
      const layout=el('div',{class:'review-flow-connection'});
      const info=el('div',{class:'review-flow-connection-copy'});
      const kind={screw:'螺钉 / 螺栓',dowel:'木销',half_lap:'半搭接',mortise_tenon:'榫卯'}[joint.kind]||'当前';
      info.append(el('p',{class:'review-flow-description'},'沿用'+kind+'连接与当前孔位。'));
      if(joint.hardware?.length)info.append(el('div',{class:'review-flow-hardware'},joint.hardware.slice(0,3).map(item=>el('div',{},el('span',{},item.name),el('strong',{},'× '+item.quantity)))));
      if(joint.hardware?.length>3)info.append(el('span',{class:'review-flow-hardware-more'},'另 '+(joint.hardware.length-3)+' 种五金，见详情'));
      layout.append(info);card.append(layout);
      const assembly=el('details',{class:'review-flow-assembly'},el('summary',{},'加工说明与五金规格'));
      assembly.append(el('p',{},joint.assembly_note||'沿用当前模型中的连接位置与孔位。'));
      if(joint.hardware?.length)assembly.append(el('ul',{},joint.hardware.map(item=>el('li',{},item.name+' · '+item.spec+' × '+item.quantity))));
      card.append(assembly);
    }else{
      card.append(el('p',{class:'review-flow-description'},readableMessage(project,current.message)));
      card.append(el('p',{class:'review-flow-next-note'},'处理后重新检查，通过后继续下一项。'));
    }

    const controls=el('div',{class:'review-flow-actions'});
    if(affected.length||joint)controls.append(action('在模型中查看',options.onInspect?()=>options.onInspect({partIds:affected,jointId:joint?.id}):null));
    if(canAcceptJoint)controls.append(action('沿用这个做法',options.onAcceptJoint?()=>options.onAcceptJoint(joint.id):null,true));
    else if(current.code.startsWith('module_'))controls.append(action('返回尺寸调整',options.onReturnToFit,true));
    else if(options.onResolve)controls.append(action('让 AI 修正这项问题',()=>options.onResolve(current),true));
    if(!canAcceptJoint&&options.onRefresh)controls.append(action('重新检查',options.onRefresh));
    surface.append(card);
    footer.append(controls);
  }else{
    const ready=el('article',{class:'review-flow-ready'},el('div',{class:'review-flow-ready-mark','aria-hidden':'true'},'✓'),el('h3',{},'图纸与清单来自同一版本'),el('p',{},'生成后可预览图纸，并下载当前版本的加工包。'));
    const stats=el('div',{class:'review-flow-output'});
    for(const [count,label] of [[packagePreview.drawings?.length??0,'张图纸'],[packagePreview.cut_list?.length??project.parts?.length??0,'项下料'],[packagePreview.hardware?.length??0,'项五金']])stats.append(el('div',{},el('strong',{},count),el('span',{},label)));
    ready.append(stats);surface.append(ready);
    surface.append(el('p',{class:'review-flow-scope-note'},'当前检查覆盖模型与加工资料一致性；承载、稳定性和实际加工配合仍需核对。'));
  }

  const details=el('details',{class:'review-flow-details'},el('summary',{},current?'查看全部问题与检查范围':'查看检查范围与设计设定'));
  if(blockers.length)details.append(el('h4',{},'待处理'),el('ul',{},blockers.map(check=>el('li',{},readableMessage(project,check.message)))));
  const warnings=checks.filter(check=>check.severity==='warning');
  if(warnings.length)details.append(el('h4',{},'需了解的事项'),el('ul',{},warnings.map(check=>el('li',{},readableMessage(project,check.message)))));
  if(coverage.checked?.length)details.append(el('h4',{},'已检查'),el('ul',{},coverage.checked.map(item=>el('li',{},item))));
  if(coverage.not_checked?.length)details.append(el('h4',{},'尚未验证'),el('ul',{},coverage.not_checked.map(item=>el('li',{},item))));
  if(project.assumptions?.length)details.append(el('h4',{},'设计设定'),el('ul',{},project.assumptions.map(item=>el('li',{},item))));
  surface.append(details);
  footer.prepend(error);
  if(!current){
    footer.append(action('生成加工包 →',options.onConfirmPackage,true));
  }
  surface.append(footer);
  host.append(surface);
  return surface;
}
