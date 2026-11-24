import { WorkshopViewport } from './viewport.js';

const API = '/api/workbench';
const $ = id => document.getElementById(id);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
};
const clamp = value => Math.round(Number(value) * 10) / 10;
const fmt = value => Number.isFinite(Number(value)) ? String(clamp(value)) : '—';

let project = null;
let selectedId = null;
let selectedIds = new Set();
let selectedKind = null;
let viewport = null;
let checkData = null;
let tool = 'select';
let dirty = false;
let proposal = null;
let conflict = null;
let previewParts = null;
let previewJoints = null;
let leftTab = 'objects';
let warehouseData = null;
let warehouseItems = [];
let reviewData = null;
let docsData = null;
let cutData = null;
let undoStack = [];
let redoStack = [];

async function api(path, options = {}) {
  const response = await fetch(API + path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error('无法读取服务结果。'); }
  if (!response.ok) {
    const detail = data?.detail || data;
    const message = typeof detail === 'string' ? detail : detail?.message || detail?.code || '操作未完成';
    const error = new Error(message);
    error.detail = detail; error.status = response.status;
    throw error;
  }
  return data;
}
const payload = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function showEmpty(message) {
  $('empty').hidden = false;
  if (message) $('empty-error').textContent = message;
  $('right-title').textContent = '属性';
  $('right-sub').textContent = '未选择';
  $('right-body').replaceChildren(el('p', { class: 'error' }, message || '打开一个项目，或从样例开始。'));
  $('right-foot').hidden = true;
}
function hideEmpty() { $('empty').hidden = true; }

function partDims(part) {
  const size = part.size_mm;
  const thickness = size.indexOf(Math.min(...size));
  const length = [0, 1, 2].find(index => index !== thickness);
  const width = [0, 1, 2].find(index => index !== thickness && index !== length);
  return { length, width, thickness, size };
}

function groupFor(partId) {
  return (reviewData?.board_groups || []).find(group => group.part_ids.includes(partId)) || null;
}

function semanticDims(part, group) {
  const axes = group?.dimensions?.axes || { length: 'local_z', width: 'local_x', thickness: 'local_y' };
  const index = { local_x: 0, local_y: 1, local_z: 2 };
  return {
    length: part.size_mm[index[axes.length]],
    width: part.size_mm[index[axes.width]],
    thickness: part.size_mm[index[axes.thickness]],
  };
}

function jointKindLabel(kind) {
  return ({ screw: '螺钉 / 螺栓', dowel: '木销', half_lap: '半搭接', mortise_tenon: '榫卯', cam_lock: '偏心件 cam lock' })[kind] || kind || '未指定';
}

function initViewport() {
  viewport = new WorkshopViewport($('viewport'), {
    onSelect: (id, event) => {
      if (!id) { selectedId = null; selectedIds = new Set(); selectedKind = null; return render(); }
      pickPart(id, event);
    },
    onMeasure: value => renderMeasure(value),
    onTransform: part => previewDragTransform(part),
    onError: message => showRightError(message),
  });
  window.__editorViewport = viewport;
  viewport.load(project.parts, { fit: true, hardware: [], joints: project.joints });
  viewport.setTool('select');
}

async function openProject(id) {
  project = await api('/projects/' + encodeURIComponent(id));
  try { reviewData = await api('/projects/' + encodeURIComponent(id) + '/review'); } catch { reviewData = null; }
  selectedId = null; selectedIds = new Set(); selectedKind = null; previewJoints = null; leftTab = 'objects'; warehouseData = null; checkData = null; dirty = false; undoStack = []; redoStack = [];
  if (!project.parts.length) {
    showEmpty('这个项目还没有可编辑模型。先回主线形成第一版，或者打开样例。');
    return;
  }
  hideEmpty();
  if (!viewport) initViewport();
  else viewport.load(project.parts, { fit: true, hardware: [], joints: project.joints });
  history.replaceState({}, '', '/editor?project=' + encodeURIComponent(project.id));
  render();
}

async function openSample() {
  const button = $('open-sample');
  button.disabled = true; $('empty-error').textContent = '';
  try {
    const created = await api('/demos/cafe-chair', { method: 'POST' });
    const accepted = await api('/projects/' + created.project.id + '/proposal/accept',
      payload('POST', { expected_revision: created.project.revision, proposal_id: created.proposal.id, accept_connections: false }));
    await openProject(accepted.id);
  } catch (error) {
    $('empty-error').textContent = error.message;
    $('empty-error').hidden = false;
  } finally {
    button.disabled = false;
  }
}

function render() {
  if (!project) return;
  $('project-name').textContent = project.name;
  $('project-meta').textContent = 'v' + project.revision + ' · 本机项目';
  $('save-status').textContent = dirty ? '有未采用修改' : '已保存';
  $('left-revision').textContent = project.revision;
  $('main-link').href = '/#step=R4&project=' + encodeURIComponent(project.id);
  renderTree();
  renderRight();
  updateTools();
  $('undo-button').disabled = !undoStack.length;
  $('redo-button').disabled = !redoStack.length;
}

async function showWarehouse() {
  if (!project) return;
  leftTab = 'warehouse'; selectedKind = null; selectedId = null; selectedIds = new Set(); docsData = null; cutData = null; checkData = null;
  render();
  try {
    const [pkg, wh] = await Promise.all([
      api('/projects/' + encodeURIComponent(project.id) + '/package'),
      api('/warehouse'),
    ]);
    warehouseData = pkg; warehouseItems = wh.items || [];
  } catch { warehouseData = null; }
  if (leftTab === 'warehouse') render();
}

function hardwareTotals() {
  const totals = new Map();
  for (const joint of project.joints || []) {
    for (const item of joint.hardware || []) {
      const key = item.name + '|' + item.spec;
      totals.set(key, (totals.get(key) || 0) + Number(item.quantity || 0));
    }
  }
  return [...totals.entries()].map(([key, quantity]) => { const [name, spec] = key.split('|'); return { name, spec, quantity }; });
}

function warehouseIconButton(kind, title, handler) {
  return el('button', { type: 'button', class: 'mini ' + kind, title, 'aria-label': title, onclick: handler }, kind === 'add' ? '+' : '−');
}
function warehouseQty(quantity) { return el('span', { class: 'qty-badge' }, '×' + quantity); }
function renderWarehouse() {
  const tree = $('tree');
  tree.replaceChildren();
  $('left-count').textContent = '仓库';
  const plan = warehouseData?.material_plan;
  const lines = plan?.materials || [];
  tree.append(el('div', { class: 'group-title' }, '已入库'));
  if (warehouseItems.length) {
    for (const item of warehouseItems) {
      tree.append(el('div', { class: 'warehouse-item' },
        el('div', { class: 'warehouse-head' },
          el('div', { class: 'warehouse-name' }, el('b', {}, item.name), warehouseQty(item.quantity)),
          el('div', { class: 'qty-actions' },
            warehouseIconButton('remove', '出库 1 件（到 0 时删除）', () => updateWarehouseQuantity(item.id, -1)),
            warehouseIconButton('add', '入库 1 件', () => updateWarehouseQuantity(item.id, 1)))),
        el('small', {}, [item.dims, item.spec].filter(Boolean).join(' · '))));
    }
  } else {
    tree.append(el('div', { class: 'warehouse-empty' }, '还没有手动入库的余料。'));
  }
  tree.append(el('div', { class: 'group-title' }, '本项目板材'));
  if (lines.length) {
    for (const line of lines) {
      const stock = (line.stock_dimensions_mm || []).map(value => Math.round(value)).join(' × ');
      tree.append(el('div', { class: 'warehouse-item' },
        el('b', {}, line.name), warehouseQty(line.sheet_count ?? 0),
        el('small', {}, stock + ' mm · ' + (line.sheet_count ?? '—') + ' 张'),
        el('small', {}, '利用率 ' + (line.utilization == null ? '—' : Math.round(line.utilization * 100) + '%') + ' · 余料约 ' + (line.offcut == null ? '—' : Math.round(line.offcut * 100) + '%'))));
    }
  } else {
    for (const material of Object.values(project.materials || {})) {
      tree.append(el('div', { class: 'warehouse-item' }, el('b', {}, material.name), el('small', {}, '尚未生成整板排板')));
    }
  }
  tree.append(el('div', { class: 'group-title' }, '五金'));
  const hardware = warehouseData?.hardware?.length ? warehouseData.hardware : hardwareTotals();
  for (const item of hardware) {
    tree.append(el('div', { class: 'warehouse-item' },
      el('div', { class: 'warehouse-head' },
        el('div', { class: 'warehouse-name' }, el('b', {}, item.name), warehouseQty(item.quantity)),
        warehouseIconButton('add', '入库 1 组', () => addWarehouse({ name: item.name, kind: 'hardware', spec: item.spec, quantity: item.quantity, note: '来自本项目五金清单' }))),
      el('small', {}, item.spec + ' · ' + item.quantity + ' 件')));
  }
  tree.append(el('div', { class: 'group-title' }, '下料余料'));
  const offcuts = planOffcuts(lines);
  if (offcuts.length) {
    for (const item of offcuts) {
      tree.append(el('div', { class: 'warehouse-item' },
        el('div', { class: 'warehouse-head' },
          el('div', { class: 'warehouse-name' }, el('b', {}, item.name + ' ' + item.dims), warehouseQty(1)),
          warehouseIconButton('add', '入库这块余料', () => addWarehouse({ name: item.name, kind: 'sheet', dims: item.dims + ' mm', quantity: 1, note: '来自本项目第 ' + item.sheet + ' 张板' }))),
        el('small', {}, item.dims + ' mm · 第 ' + item.sheet + ' 张板')));
    }
  } else {
    tree.append(el('div', { class: 'warehouse-empty' }, '生成加工包后，这里列出整板排版留下的可用矩形。'));
  }
}

async function addWarehouse(item) {
  try {
    await api('/warehouse', payload('POST', item));
    const wh = await api('/warehouse');
    warehouseItems = wh.items || [];
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

async function updateWarehouseQuantity(id, delta) {
  const item = warehouseItems.find(entry => entry.id === id);
  if (!item) return;
  const quantity = Number(item.quantity) + delta;
  try {
    if (quantity <= 0) { await deleteWarehouse(id); return; }
    const wh = await api('/warehouse/' + encodeURIComponent(id), payload('PATCH', { quantity }));
    warehouseItems = wh.items || [];
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

async function deleteWarehouse(id) {
  try {
    const wh = await api('/warehouse/' + encodeURIComponent(id), { method: 'DELETE' });
    warehouseItems = wh.items || [];
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

function planOffcuts(lines) {
  const result = [];
  for (const line of lines) {
    const [length, width] = line.stock_dimensions_mm || [];
    for (const sheet of line.sheets || []) {
      let right = 0; let bottom = 0;
      for (const shelf of sheet.shelves || []) {
        for (const item of shelf.items || []) right = Math.max(right, item.x + item.width);
        bottom = Math.max(bottom, shelf.y + shelf.height);
      }
      if (length && right < length - 10) result.push({ name: '右侧余料', dims: Math.round(length - right) + ' × ' + Math.round(width), sheet: sheet.number, area: (length - right) * width });
      if (width && bottom < width - 10) result.push({ name: '底部余料', dims: Math.round(length) + ' × ' + Math.round(width - bottom), sheet: sheet.number, area: length * (width - bottom) });
    }
  }
  return result.sort((a, b) => b.area - a.area).slice(0, 5);
}

function renderTree() {
  $('objects-tab').classList.toggle('on', leftTab === 'objects');
  $('warehouse-tab').classList.toggle('on', leftTab === 'warehouse');
  if (leftTab === 'warehouse') { renderWarehouse(); return; }
  const tree = $('tree');
  tree.replaceChildren();
  const partGroup = el('div', { class: 'group-title' }, '零件 · ' + project.parts.length + ' 件');
  tree.append(partGroup);
  const parts = el('div', { class: 'tree' });
  for (const part of project.parts) {
    const dims = partDims(part);
    parts.append(el('button', {
      type: 'button', class: 'row' + (selectedIds.has(part.id) ? ' on' : ''),
      onclick: event => selectPart(part.id, event),
    }, part.name, el('small', {}, fmt(dims.size[dims.length]) + '×' + fmt(dims.size[dims.width]) + '×' + fmt(dims.size[dims.thickness]))));
  }
  tree.append(parts);
  tree.append(el('div', { class: 'group-title' }, '连接 · ' + project.joints.length + ' 处'));
  const joints = el('div', { class: 'tree' });
  for (const joint of project.joints) {
    joints.append(el('button', {
      type: 'button', class: 'row' + (selectedKind === 'joint' && selectedId === joint.id ? ' on' : ''),
      onclick: () => selectJoint(joint.id),
    }, joint.name || joint.id, el('small', {}, jointKindLabel(joint.kind))));
  }
  tree.append(joints);
  const modules = project.modules || [];
  if (modules.length) {
    tree.append(el('div', { class: 'group-title' }, '模度 · ' + modules.length));
    const list = el('div', { class: 'tree' });
    for (const module of modules) {
      list.append(el('div', { class: 'row' }, module.name || module.kind, el('small', {}, module.status || '')));
    }
    tree.append(list);
  }
  $('left-count').textContent = project.parts.length + ' 件 · ' + project.joints.length + ' 处连接';
}

function clearPreview() {
  if (!proposal && !previewParts) return;
  proposal = null; conflict = null; previewParts = null;
  if (project && viewport) viewport.load(project.parts, { fit: false, hardware: [], joints: project.joints });
}

function pickPart(id, event = null) {
  clearPreview();
  leftTab = 'objects';
  if (event?.shiftKey || event?.metaKey || event?.ctrlKey) {
    if (selectedIds.has(id)) selectedIds.delete(id); else selectedIds.add(id);
    selectedId = selectedIds.has(id) ? id : ([...selectedIds][0] || null);
    selectedKind = selectedIds.size > 1 ? 'parts' : selectedIds.size ? 'part' : null;
  } else {
    selectedIds = new Set([id]); selectedId = id; selectedKind = 'part';
  }
  checkData = null; docsData = null; cutData = null;
  viewport?.setSelection(selectedId);
  if (selectedKind === 'parts') viewport?.highlightParts([...selectedIds]);
  else if (selectedId) viewport?.focus(selectedId);
  render();
}

function selectPart(id, event = null) { pickPart(id, event); }
function selectJoint(id) {
  const joint = project.joints.find(item => item.id === id);
  if (!joint) return;
  selectedKind = 'joint'; selectedId = id; selectedIds = new Set([...joint.part_ids]); leftTab = 'objects'; checkData = null; docsData = null; cutData = null;
  viewport?.highlightParts(joint.part_ids);
  viewport?.focus(joint.part_ids[0]);
  render();
}

function showRightError(message) {
  $('right-body').replaceChildren(el('p', { class: 'error' }, message));
}

function field(label, value, attrs = {}) {
  const input = el('input', { value: fmt(value), inputmode: 'decimal', ...attrs });
  return { node: el('label', { class: 'field' }, label, input), input };
}

function svgNode(tag, attrs, text = null) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== null) node.textContent = text;
  return node;
}

function sheetSvg(sheet, stock) {
  const [length, width] = stock;
  const rects = [];
  for (const shelf of sheet.shelves || []) {
    for (const item of shelf.items || []) {
      rects.push(svgNode('rect', { x: item.x, y: item.y, width: item.width, height: item.height }));
      if (item.width > 150 && item.height > 60) {
        rects.push(svgNode('text', { x: item.x + 8, y: item.y + 22 }, item.name));
      }
    }
  }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${length} ${width}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', '第 ' + sheet.number + ' 张开料图');
  for (const node of rects) svg.append(node);
  return el('div', { class: 'sheet' }, svg);
}

function renderCut() {
  const title = $('right-title'), sub = $('right-sub'), body = $('right-body'), foot = $('right-foot');
  const plan = cutData?.material_plan;
  title.textContent = '开料'; sub.textContent = 'v' + (cutData?.revision || project.revision);
  if (!plan || !plan.materials?.length) {
    body.replaceChildren(el('p', { class: 'error' }, '这一版还没有整板开料计划。'));
    foot.hidden = true; return;
  }
  body.replaceChildren(
    el('div', { class: 'section' }, el('h3', {}, '整板'),
      el('p', {}, '共 ' + plan.sheet_total + ' 张 · 材料 ' + fmt(plan.material_subtotal) + ' ' + (plan.currency || 'CNY'))),
    ...plan.materials.map(line => el('div', { class: 'section' },
      el('h3', {}, line.name),
      el('p', {}, (line.sheet_count ?? '—') + ' 张 · 利用率 ' + (line.utilization == null ? '—' : Math.round(line.utilization * 100) + '%')),
      ...(line.sheets || []).map(sheet => sheetSvg(sheet, line.stock_dimensions_mm)))),
    el('p', { class: 'error' }, '矩形毛坯、3 mm 锯缝、10 mm 切边，货架式估算；不是最优排版。'),
  );
  foot.hidden = true;
}

function renderRight() {
  const title = $('right-title'), sub = $('right-sub'), body = $('right-body'), foot = $('right-foot');
  if (cutData) return renderCut();
  if (docsData) {
    title.textContent = '文档'; sub.textContent = project.name;
    const records = docsData.exports || [];
    const generate = el('div', { class: 'section' },
      el('h3', {}, records.length ? '生成新版本' : '还没有加工包'),
      el('p', {}, '生成会把当前版本固定成 PDF、ZIP、清单和预算；检查不过会先报问题。'),
      el('button', { type: 'button', class: 'primary', onclick: generatePackage }, '生成当前版本加工包'),
      el('a', { class: 'ghost', href: '/#step=M9&project=' + encodeURIComponent(project.id) }, '回主线核对'));
    body.replaceChildren(
      generate,
      ...(records.length ? [el('div', { class: 'section' }, el('h3', {}, '已生成版本'),
        ...records.map(record => el('div', { class: 'section' },
          el('h3', {}, 'v' + record.revision + (record.current ? ' · 当前版本' : ' · 历史')),
          el('p', {}, record.created_at || ''),
          el('a', { class: 'ghost', href: record.pdf_url, target: '_blank', rel: 'noopener' }, 'PDF'),
          el('a', { class: 'ghost', href: record.download_url }, '下载 ZIP'))))] : []),
    );
    foot.hidden = true; return;
  }
  if (checkData) {
    title.textContent = '检查'; sub.textContent = 'v' + checkData.revision;
    const list = el('div', { class: 'checks' });
    const checks = checkData.checks || [];
    if (!checks.length) list.append(el('p', { class: 'error' }, '没有返回检查结果。'));
    for (const check of checks) {
      const kind = check.severity === 'blocker' ? 'blocker' : check.severity === 'warning' ? 'warning' : 'note';
      list.append(el('div', { class: 'check ' + kind }, el('b', {}, check.code), el('span', {}, check.message)));
    }
    body.replaceChildren(list, el('button', { type: 'button', class: 'ghost', onclick: runCheck }, '重新检查'));
    foot.hidden = true;
    return;
  }
  if (proposal) {
    const selected = project.parts.find(part => part.id === selectedId) || project.joints.find(joint => joint.id === selectedId);
    title.textContent = '预览修改'; sub.textContent = (selected?.name || '未命名') + ' · 未采用';
    body.replaceChildren(
      el('div', { class: 'section' }, el('h3', {}, '修改预览'),
        el('p', {}, proposal.summary || '修改已显示在模型上。'),
        el('p', { class: 'error' }, '预览不是保存；采用后才会写入新版本，并重新跑检查。')),
    );
    foot.hidden = false;
    $('apply-edit').textContent = '采用修改';
    $('apply-edit').onclick = () => acceptPreview();
    $('cancel-edit').onclick = () => cancelPreview();
    return;
  }
  if (selectedKind === 'parts' && selectedIds.size) {
    title.textContent = '多选'; sub.textContent = selectedIds.size + ' 件';
    const chosen = project.parts.filter(part => selectedIds.has(part.id));
    const batchMaterial = el('select', {}, ...Object.entries(project.materials || {}).map(([id, item]) => el('option', { value: id }, item.name)));
    body.replaceChildren(
      el('div', { class: 'section' }, el('h3', {}, '已选'), ...chosen.map(part => el('p', {}, part.name))),
      el('div', { class: 'section' }, el('h3', {}, '批量换材料'),
        el('p', {}, '只改选中零件的材料；尺寸和孔槽不动。'),
        batchMaterial,
        el('button', { type: 'button', class: 'ghost', onclick: () => previewBatchMaterial(batchMaterial.value) }, '预览换材料')),
      el('p', { class: 'error' }, '批量尺寸、复制/粘贴还没做。'),
      el('button', { type: 'button', class: 'ghost', onclick: () => { selectedIds = new Set(); selectedId = null; selectedKind = null; render(); } }, '清除多选'),
    );
    foot.hidden = true; return;
  }
  if (selectedKind === 'part' && selectedId) {
    const part = project.parts.find(item => item.id === selectedId);
    if (!part) { selectedKind = null; return renderRight(); }
    title.textContent = '属性'; sub.textContent = part.name;
    const group = groupFor(part.id);
    const dims = semanticDims(part, group);
    const length = field('长 · mm', dims.length, { 'data-axis': 'length' });
    const width = field('宽 · mm', dims.width, { 'data-axis': 'width' });
    const thickness = field('厚 · mm', dims.thickness, { 'data-axis': 'thickness' });
    const material = el('select', {}, ...Object.entries(project.materials || {}).map(([id, item]) => el('option', { value: id, selected: id === part.material_id }, item.name)));
    const joints = (project.joints || []).filter(joint => joint.part_ids.includes(part.id));
    const jointList = el('div', { class: 'checks' }, ...joints.map(joint => el('div', { class: 'check note' }, el('b', {}, joint.name || joint.id), el('span', {}, jointKindLabel(joint.kind)))));
    if (conflict) {
      title.textContent = '需要决定'; sub.textContent = part.name;
      body.replaceChildren(
        el('div', { class: 'section' }, el('h3', {}, '这项修改改变原设计'),
          el('p', {}, conflict.message || '这会改变原椅特征。'),
          el('button', { type: 'button', class: 'ghost', onclick: () => previewPart(part.id, conflict.fields, true) }, '作为改款预览'),
          el('button', { type: 'button', class: 'ghost', onclick: () => cancelPreview() }, '保持原样')),
      );
      foot.hidden = true;
      return;
    }
    body.replaceChildren(
      el('div', { class: 'section' }, el('h3', {}, '尺寸'), el('div', { class: 'row3' }, length.node, width.node, thickness.node)),
      el('div', { class: 'section' }, el('h3', {}, '材料'),
        el('div', { class: 'material-row' }, el('span', { class: 'swatch' }), el('div', {}, el('b', {}, (project.materials?.[part.material_id]?.name) || part.material_id), el('small', {}, '材料选择在下方应用')))),
      el('div', { class: 'field' }, '更换材料', material),
      holeSection(part),
      el('div', { class: 'section' }, el('h3', {}, '位置 / 旋转'),
        el('div', { class: 'row3' },
          field('X · mm', part.position_mm?.[0], { 'data-transform': 'px' }).node,
          field('Y · mm', part.position_mm?.[1], { 'data-transform': 'py' }).node,
          field('Z · mm', part.position_mm?.[2], { 'data-transform': 'pz' }).node),
        el('div', { class: 'row3' },
          field('RX · °', part.rotation_deg?.[0], { 'data-transform': 'rx' }).node,
          field('RY · °', part.rotation_deg?.[1], { 'data-transform': 'ry' }).node,
          field('RZ · °', part.rotation_deg?.[2], { 'data-transform': 'rz' }).node),
        el('p', { class: 'error' }, '拖动或输入数值；采用后连接检查重跑。'),
        el('button', { type: 'button', class: 'ghost', onclick: () => previewTransform(part.id) }, '预览位置/旋转')),
      el('div', { class: 'section' }, el('h3', {}, '连接'), joints.length ? jointList : el('p', { class: 'error' }, '这个零件没有已定义连接。')),
    );
    foot.hidden = false;
    $('apply-edit').textContent = '预览修改';
    $('apply-edit').onclick = () => previewPart(part.id, { length: length.input, width: width.input, thickness: thickness.input, material });
    $('cancel-edit').onclick = () => cancelPreview();
    return;
  }
  if (selectedKind === 'joint' && selectedId) {
    const joint = project.joints.find(item => item.id === selectedId);
    if (!joint) return renderRight();
    title.textContent = '连接'; sub.textContent = joint.name || joint.id;
    const parts = joint.part_ids.map(id => project.parts.find(part => part.id === id)?.name || id);
    const note = el('textarea', { rows: 4, value: joint.assembly_note || '' });
    const hardware = (joint.hardware || []).map((item, index) => el('label', { class: 'field' },
      item.name + ' · ' + item.spec,
      el('input', { type: 'number', min: '1', step: '1', value: item.quantity, 'data-joint-hw': String(index) })));
    body.replaceChildren(
      el('div', { class: 'section' }, el('h3', {}, '连接方式'), el('p', {}, jointKindLabel(joint.kind))),
      el('div', { class: 'section' }, el('h3', {}, '零件'), el('p', {}, parts.join(' ↔ '))),
      el('div', { class: 'section' }, el('h3', {}, '装配说明'), note),
      el('div', { class: 'section' }, el('h3', {}, '五金数量'), ...hardware,
        el('p', { class: 'error' }, '孔位和新增五金下一步。')),
      ...(joint.kind === 'screw' || joint.kind === 'dowel' ? [
        el('button', { type: 'button', class: 'ghost', onclick: () => pairJoint(joint.id) }, '按现有孔配对'),
        el('p', { class: 'error' }, '只移动配对孔的 U/V，不改孔径、深度和加工面。'),
      ] : []),
      el('button', { type: 'button', class: 'primary', onclick: () => saveJoint(joint.id, note.value) }, '保存连接'),
    );
    foot.hidden = true;
    return;
  }
  title.textContent = '项目'; sub.textContent = 'v' + project.revision;
  const delivery = el('select', {}, ...[
    ['self', '自己做（有工具）'],
    ['kit', '下料套件（加工店下料/打孔，我装配）'],
    ['shop', '加工店制件，我装配'],
  ].map(([value, label]) => el('option', { value, selected: project.fabrication_mode === value }, label)));
  body.replaceChildren(
    el('div', { class: 'section' }, el('h3', {}, '概览'),
      el('p', {}, project.parts.length + ' 件 · ' + project.joints.length + ' 处连接'),
      el('p', {}, '材料：' + Object.values(project.materials || {}).map(item => item.name).join('、'))),
    el('div', { class: 'section' }, el('h3', {}, '交付方式'),
      el('p', {}, '谁下料、谁装配。会改变加工包章节和预算口径。'),
      delivery,
      el('button', { type: 'button', class: 'ghost', onclick: () => applyDelivery(delivery.value) }, '应用交付方式')),
    el('div', { class: 'section' }, el('h3', {}, '检查'),
      el('p', {}, '碰撞、连接性、承重草算；按需运行，修改后要重跑。'),
      el('button', { type: 'button', class: 'ghost', onclick: runCheck }, '检查整椅')),
  );
  foot.hidden = true;
}

async function applyDelivery(mode) {
  const before = project.revision;
  try {
    project = await api('/projects/' + encodeURIComponent(project.id), payload('PUT', { expected_revision: project.revision, patch: { fabrication_mode: mode } }));
    undoStack.push({ before, after: project.revision }); redoStack = [];
    dirty = false; checkData = null; render();
  } catch (error) {
    showRightError(error.message);
  }
}

async function undoRedo(redo = false) {
  const source = redo ? redoStack : undoStack;
  const target = redo ? undoStack : redoStack;
  const entry = source.pop();
  if (!entry) return;
  try {
    const restored = await api('/projects/' + encodeURIComponent(project.id) + '/restore/' + (redo ? entry.after : entry.before),
      payload('POST', { expected_revision: project.revision }));
    project = restored; proposal = null; conflict = null; previewParts = null; dirty = false; checkData = null;
    try { reviewData = await api('/projects/' + encodeURIComponent(project.id) + '/review'); } catch { reviewData = null; }
    viewport?.load(project.parts, { fit: false, hardware: [], joints: project.joints });
    if (selectedId) viewport?.setSelection(selectedId);
    target.push(entry); render();
  } catch (error) {
    showRightError(error.message);
  }
}

async function pairJoint(jointId) {
  try {
    const result = await api('/projects/' + encodeURIComponent(project.id) + '/joints/' + encodeURIComponent(jointId) + '/pair-preview',
      payload('POST', { expected_revision: project.revision }));
    previewParts = result.patch.parts;
    proposal = { kind: 'pair', summary: result.summary || '配对孔已移动。' };
    conflict = null;
    viewport?.load(previewParts, { fit: false, hardware: [], joints: project.joints });
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

async function saveJoint(jointId, note) {
  const before = project.revision;
  const next = structuredClone(project);
  const joint = next.joints.find(item => item.id === jointId);
  if (!joint) return;
  joint.assembly_note = note;
  for (const input of document.querySelectorAll('[data-joint-hw]')) {
    const index = Number(input.dataset.jointHw);
    const quantity = Number(input.value);
    if (!Number.isInteger(quantity) || quantity < 1) { showRightError('五金数量必须是正整数。'); return; }
    if (joint.hardware?.[index]) joint.hardware[index].quantity = quantity;
  }
  try {
    project = await api('/projects/' + encodeURIComponent(project.id), payload('PUT', { expected_revision: project.revision, patch: { joints: next.joints } }));
    undoStack.push({ before, after: project.revision }); redoStack = [];
    try { reviewData = await api('/projects/' + encodeURIComponent(project.id) + '/review'); } catch { reviewData = null; }
    viewport?.load(project.parts, { fit: false, hardware: [], joints: project.joints });
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

function holeSection(part) {
  const holes = (part.features || []).map((feature, index) => ({ feature, index })).filter(item => item.feature.kind === 'hole');
  const slots = (part.features || []).map((feature, index) => ({ feature, index })).filter(item => item.feature.kind === 'slot');
  const rows = [
    ...holes.map(({ feature, index }) => el('div', { class: 'feature' },
      el('div', { class: 'feature-head' },
        el('h3', {}, (feature.role === 'connection' ? '连接孔 · ' : '工艺孔 · ') + feature.id),
        el('button', { type: 'button', class: 'ghost', onclick: () => deleteHole(part.id, index) }, '删除')),
      el('p', {}, feature.face + ' · Ø' + fmt(feature.diameter_mm) + ' × ' + fmt(feature.depth_mm) + ' mm'),
      el('div', { class: 'row3' },
        field('U · mm', feature.u_mm, { 'data-hole': index, 'data-hole-field': 'u_mm' }).node,
        field('V · mm', feature.v_mm, { 'data-hole': index, 'data-hole-field': 'v_mm' }).node,
        field('Ø · mm', feature.diameter_mm, { 'data-hole': index, 'data-hole-field': 'diameter_mm' }).node),
      el('div', { class: 'row3' },
        field('深 · mm', feature.depth_mm, { 'data-hole': index, 'data-hole-field': 'depth_mm' }).node))),
    ...slots.map(({ feature, index }) => el('div', { class: 'feature' },
      el('div', { class: 'feature-head' },
        el('h3', {}, '槽 · ' + feature.id),
        el('button', { type: 'button', class: 'ghost', onclick: () => deleteSlot(part.id, index) }, '删除')),
      el('p', {}, feature.face + ' · ' + fmt(feature.width_mm) + ' × ' + fmt(feature.length_mm) + ' × ' + fmt(feature.depth_mm) + ' mm'),
      el('div', { class: 'row3' },
        field('U 角 · mm', feature.u_mm, { 'data-slot': index, 'data-slot-field': 'u_mm' }).node,
        field('V 角 · mm', feature.v_mm, { 'data-slot': index, 'data-slot-field': 'v_mm' }).node,
        field('宽 · mm', feature.width_mm, { 'data-slot': index, 'data-slot-field': 'width_mm' }).node),
      el('div', { class: 'row3' },
        field('长 · mm', feature.length_mm, { 'data-slot': index, 'data-slot-field': 'length_mm' }).node,
        field('深 · mm', feature.depth_mm, { 'data-slot': index, 'data-slot-field': 'depth_mm' }).node))),
  ];
  if (!rows.length) return el('div', { class: 'section' }, el('h3', {}, '孔位 / 槽位'), el('p', {}, '这个零件没有孔槽定义。'));
  return el('details', { class: 'section' },
    el('summary', {}, '孔位 / 槽位 · ' + (holes.length + slots.length) + ' 个'),
    ...rows,
    el('button', { type: 'button', class: 'ghost', onclick: () => previewFeatures(part.id) }, '预览孔槽参数'),
    el('button', { type: 'button', class: 'ghost', onclick: () => addHole(part.id) }, '新增孔'),
    el('button', { type: 'button', class: 'ghost', onclick: () => addSlot(part.id) }, '新增槽'),
    el('p', { class: 'error' }, '槽的 U/V 是最小角，不是中心；改动会让连接检查重跑，不自动修配对。'));
}

function commitFeatureDraft(partId, next, summary) {
  previewParts = structuredClone(project).parts;
  const target = previewParts.find(item => item.id === partId);
  target.features = next.features;
  proposal = { kind: 'features', summary };
  conflict = null;
  viewport?.load(previewParts, { fit: false, hardware: [], joints: project.joints });
  viewport?.setSelection(partId);
  render();
}

function addHole(partId) {
  const part = project.parts.find(item => item.id === partId);
  if (!part) return;
  const next = structuredClone(part);
  const thickness = part.size_mm[1];
  const id = 'user_hole_' + String(Date.now()).slice(-7);
  next.features = [...(next.features || []), {
    id, role: 'connection', kind: 'hole', face: 'top',
    u_mm: part.size_mm[0] / 2, v_mm: part.size_mm[2] / 2,
    diameter_mm: 6.5, width_mm: null, length_mm: null,
    depth_mm: Math.min(18, thickness), entry_mm: null, direction_local: null,
  }];
  commitFeatureDraft(partId, next, part.name + '：新增孔 ' + id + '（默认中心/Ø6.5，采用后再调参数）。');
}

function deleteHole(partId, index) {
  const part = project.parts.find(item => item.id === partId);
  if (!part) return;
  const feature = part.features?.[index];
  if (!feature) return;
  const next = structuredClone(part);
  next.features = next.features.filter((_, i) => i !== index);
  const used = project.joints?.some(joint => joint.feature_ids?.includes(feature.id));
  commitFeatureDraft(partId, next, part.name + '：删除孔 ' + feature.id + (used ? '（它被连接引用，采用后该连接会报缺特征）' : '') + '。');
}

function previewFeatures(partId) {
  const next = structuredClone(project);
  const part = next.parts.find(item => item.id === partId);
  if (!part) return;
  for (const input of document.querySelectorAll('[data-hole]')) {
    const feature = part.features?.[Number(input.dataset.hole)];
    const value = Number(input.value);
    if (!feature || !Number.isFinite(value) || value <= 0) { showRightError('孔位参数必须是正数。'); return; }
    feature[input.dataset.holeField] = value;
  }
  for (const input of document.querySelectorAll('[data-slot]')) {
    const feature = part.features?.[Number(input.dataset.slot)];
    const value = Number(input.value);
    if (!feature || !Number.isFinite(value) || value <= 0) { showRightError('槽位参数必须是正数。'); return; }
    feature[input.dataset.slotField] = value;
  }
  previewParts = next.parts;
  proposal = { kind: 'features', summary: part.name + '：孔槽参数已修改，采用后连接检查重跑。' };
  conflict = null;
  viewport?.load(previewParts, { fit: false, hardware: [], joints: project.joints });
  viewport?.setSelection(partId);
  render();
}

function addSlot(partId) {
  const part = project.parts.find(item => item.id === partId);
  if (!part) return;
  const next = structuredClone(part);
  const width = Math.min(10, part.size_mm[0]);
  const length = Math.min(50, part.size_mm[2]);
  next.features = [...(next.features || []), {
    id: 'user_slot_' + String(Date.now()).slice(-7), role: 'connection', kind: 'slot', face: 'top',
    u_mm: Math.max(0, part.size_mm[0] / 2 - width / 2), v_mm: Math.max(0, part.size_mm[2] / 2 - length / 2),
    diameter_mm: null, width_mm: width, length_mm: length, depth_mm: Math.min(8, part.size_mm[1]),
    entry_mm: null, direction_local: null,
  }];
  commitFeatureDraft(partId, next, part.name + '：新增槽 user_slot（默认中心 10×50×8，采用后再调参数）。');
}

function deleteSlot(partId, index) {
  const part = project.parts.find(item => item.id === partId);
  if (!part) return;
  const feature = part.features?.[index];
  if (!feature) return;
  const next = structuredClone(part);
  next.features = next.features.filter((_, i) => i !== index);
  const used = project.joints?.some(joint => joint.feature_ids?.includes(feature.id));
  commitFeatureDraft(partId, next, part.name + '：删除槽 ' + feature.id + (used ? '（它被连接引用，采用后该连接会报缺特征）' : '') + '。');
}

function transformInputs() {
  return Object.fromEntries([...document.querySelectorAll('[data-transform]')].map(input => [input.dataset.transform, Number(input.value)]));
}

function previewBatchMaterial(materialId) {
  const next = structuredClone(project);
  const count = next.parts.filter(part => selectedIds.has(part.id)).length;
  if (!count) return;
  for (const part of next.parts) if (selectedIds.has(part.id)) part.material_id = materialId;
  previewParts = next.parts;
  proposal = { kind: 'batch-material', summary: count + ' 件零件换材料为 ' + (project.materials?.[materialId]?.name || materialId) + '。' };
  conflict = null;
  viewport?.load(previewParts, { fit: false, hardware: [], joints: project.joints });
  render();
}

function previewDragTransform(part) {
  const next = structuredClone(project);
  const index = next.parts.findIndex(item => item.id === part.id);
  if (index < 0) return;
  next.parts[index] = part;
  previewParts = next.parts;
  proposal = { kind: 'transform', summary: part.name + '：拖动到 X ' + fmt(part.position_mm?.[0]) + ' / Y ' + fmt(part.position_mm?.[1]) + ' / Z ' + fmt(part.position_mm?.[2]) + ' mm；RX ' + fmt(part.rotation_deg?.[0]) + ' / RY ' + fmt(part.rotation_deg?.[1]) + ' / RZ ' + fmt(part.rotation_deg?.[2]) + '°。' };
  conflict = null;
  viewport?.load(previewParts, { fit: false, hardware: [], joints: project.joints });
  viewport?.setSelection(part.id);
  render();
}

function previewTransform(partId) {
  const part = project.parts.find(item => item.id === partId);
  if (!part) return;
  const values = transformInputs();
  for (const [key, value] of Object.entries(values)) {
    if (!Number.isFinite(value)) { showRightError('位置和旋转必须是数字。'); return; }
  }
  const next = structuredClone(project);
  const moved = next.parts.find(item => item.id === partId);
  moved.position_mm = [values.px, values.py, values.pz];
  moved.rotation_deg = [values.rx, values.ry, values.rz];
  previewParts = next.parts;
  proposal = { kind: 'transform', summary: moved.name + '：X ' + fmt(values.px) + ' / Y ' + fmt(values.py) + ' / Z ' + fmt(values.pz) + ' mm；RX ' + fmt(values.rx) + ' / RY ' + fmt(values.ry) + ' / RZ ' + fmt(values.rz) + '°。' };
  conflict = null;
  viewport?.load(previewParts, { fit: false, hardware: [], joints: project.joints });
  viewport?.setSelection(partId);
  render();
}

async function previewPart(partId, fields, allowRedesign = false) {
  const part = project.parts.find(item => item.id === partId);
  if (!part) return;
  const values = {};
  for (const key of ['length', 'width', 'thickness']) {
    const value = Number(fields[key].value);
    if (!Number.isFinite(value) || value <= 0) { showRightError('尺寸必须是正数。'); return; }
    values[key] = value;
  }
  values.material_id = fields.material.value;
  try {
    const review = await api('/projects/' + encodeURIComponent(project.id) + '/review');
    const group = (review.board_groups || []).find(item => item.part_ids.includes(partId));
    if (!group) { showRightError('这个零件不在当前板件组里，不能预览尺寸修改。'); return; }
    const preview = await api('/projects/' + encodeURIComponent(project.id) + '/review/boards/' + encodeURIComponent(group.id) + '/edit-preview',
      payload('POST', { expected_revision: project.revision, fingerprint: group.fingerprint,
        length_mm: values.length, width_mm: values.width, thickness_mm: values.thickness,
        material_id: values.material_id, allow_redesign: allowRedesign }));
    proposal = preview; conflict = null; previewParts = preview.patch?.parts || project.parts;
    viewport?.load(previewParts, { fit: false, hardware: [], joints: project.joints });
    viewport?.setSelection(partId);
    render();
  } catch (error) {
    const detail = error.detail || {};
    if (detail.code === 'preservation_decision' && !allowRedesign) {
      proposal = null; previewParts = null; conflict = { message: detail.message, fields: { ...fields }, values };
      viewport?.load(project.parts, { fit: false, hardware: [], joints: project.joints });
      viewport?.setSelection(partId); render(); return;
    }
    showRightError(error.message);
  }
}

async function acceptPreview() {
  if (!proposal) return;
  const before = project.revision;
  try {
    const accepted = proposal.kind === 'delete'
      ? await api('/projects/' + encodeURIComponent(project.id), payload('PUT', { expected_revision: project.revision, patch: { parts: previewParts, joints: previewJoints || project.joints } }))
      : (proposal.kind === 'transform' || proposal.kind === 'holes' || proposal.kind === 'features' || proposal.kind === 'pair' || proposal.kind === 'batch-material')
      ? await api('/projects/' + encodeURIComponent(project.id), payload('PUT', { expected_revision: project.revision, patch: { parts: previewParts } }))
      : await api('/projects/' + encodeURIComponent(project.id) + '/proposal/accept',
        payload('POST', { expected_revision: project.revision, proposal_id: proposal.id, accept_connections: false }));
    project = accepted; proposal = null; conflict = null; previewParts = null; previewJoints = null; dirty = false; checkData = null; selectedIds = new Set([selectedId].filter(Boolean));
    undoStack.push({ before, after: accepted.revision }); redoStack = [];
    try { reviewData = await api('/projects/' + encodeURIComponent(project.id) + '/review'); } catch { reviewData = null; }
    viewport?.load(project.parts, { fit: false, hardware: [], joints: project.joints });
    viewport?.setSelection(selectedId);
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

function cancelPreview() {
  proposal = null; conflict = null; previewParts = null; previewJoints = null;
  if (viewport && project) viewport.load(project.parts, { fit: false, hardware: [], joints: project.joints });
  if (selectedId) viewport?.setSelection(selectedId);
  render();
}

async function showCutLayout() {
  if (!project) return;
  try {
    cutData = await api('/projects/' + encodeURIComponent(project.id) + '/package');
    docsData = null; selectedKind = null; selectedId = null; checkData = null;
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

async function generatePackage() {
  if (!project) return;
  try {
    await api('/projects/' + encodeURIComponent(project.id) + '/exports', payload('POST', { expected_revision: project.revision }));
    docsData = await api('/projects/' + encodeURIComponent(project.id) + '/exports');
    render();
  } catch (error) {
    if (Array.isArray(error.detail?.checks)) {
      checkData = { revision: project.revision, checks: error.detail.checks };
      docsData = null; render();
    } else {
      showRightError(error.message);
    }
  }
}

async function showDocuments() {
  if (!project) return;
  try {
    docsData = await api('/projects/' + encodeURIComponent(project.id) + '/exports');
    cutData = null; selectedKind = null; selectedId = null; checkData = null;
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

async function runCheck() {
  if (!project) return;
  docsData = null; cutData = null;
  try {
    checkData = await api('/projects/' + encodeURIComponent(project.id) + '/checks');
    render();
  } catch (error) {
    showRightError(error.message);
  }
}

function renderMeasure(value) {
  const hud = $('measure-hud');
  if (!value) { hud.hidden = true; return; }
  hud.hidden = false;
  if (value.preview === false) { hud.replaceChildren('点选端点或中点作为起点'); return; }
  if (value.preview) { hud.replaceChildren('吸附：' + (value.snap || '面') + ' · 点击定起点'); return; }
  if (value.pending) { hud.replaceChildren('起点已定 · ' + (value.snap || '吸附') + ' · 移到终点'); return; }
  if (value.hover && value.distance_mm !== undefined) { hud.replaceChildren(el('strong', {}, fmt(value.distance_mm) + ' mm'), el('span', {}, (value.snap || '') + ' · 点击确定 · Esc 退出')); return; }
  if (value.distance_mm !== undefined) {
    hud.replaceChildren(el('strong', {}, fmt(value.distance_mm) + ' mm'), el('span', {}, (value.snap || '') + ' · 点击再测 · Esc 退出'));
  }
}

function updateTools() {
  document.querySelectorAll('[data-tool]').forEach(button => button.classList.toggle('on', button.dataset.tool === tool));
  $('status-text').textContent = tool === 'measure' ? '测量中' : tool === 'translate' ? '拖动移动' : tool === 'rotate' ? '拖动旋转' : tool === 'scale' ? '拉伸' : tool === 'advanced' ? '高级工具' : '编辑器';
}

function activeEditorIds(){return selectedIds.size?[...selectedIds]:selectedId?[selectedId]:[];}
function editorIsolate() {
  const ids = new Set(activeEditorIds());
  if (!ids.size) throw new Error('先选中至少一个部件。');
  for (const part of project.parts) viewport.setVisible(part.id, ids.has(part.id));
  renderAdvancedPanel();
}
function editorShowAll() {
  for (const part of project.parts) viewport.setVisible(part.id, true);
  renderAdvancedPanel();
}
function editorHideSelected() {
  const ids = activeEditorIds();
  if (!ids.length) throw new Error('先选中至少一个部件。');
  for (const id of ids) viewport.setVisible(id, false);
  renderAdvancedPanel();
}
function editorExplode(exploded) { viewport.setExploded(exploded); renderAdvancedPanel(); }
function editorMirror() {
  if (!selectedId) throw new Error('先选中要镜像的部件。');
  viewport.setTool('mirror');
  renderAdvancedPanel();
}
function renderAdvancedPanel() {
  const ids = activeEditorIds();
  const button = (label, handler, disabled = false) => el('button', { type: 'button', disabled, onclick: () => { try { handler(); } catch (error) { showRightError(error.message); } } }, label);
  $('right-title').textContent = '高级工具';
  $('right-sub').textContent = ids.length ? ids.length + ' 个部件' : '未选择';
  $('right-body').replaceChildren(
    el('div', { class: 'advanced-tools' },
      el('h3', {}, '显示与检查'),
      el('div', { class: 'advanced-row' },
        button('隔离选中', editorIsolate, !ids.length),
        button('显示全部', editorShowAll),
        button('隐藏选中', editorHideSelected, !ids.length)
      ),
      el('div', { class: 'advanced-row' },
        button('拆开看', () => editorExplode(true)),
        button('合上', () => editorExplode(false))
      ),
      el('h3', {}, '几何'),
      el('div', { class: 'advanced-row' },
        button('沿 X 镜像选中', editorMirror, !selectedId)
      )
    )
  );
  $('right-foot').hidden = true;
}
function deleteSelectedParts() {
  if (!project) return;
  const ids = activeEditorIds();
  if (!ids.length) { showRightError('先选中要删除的部件。'); return; }
  const next = structuredClone(project);
  next.parts = next.parts.filter(part => !ids.includes(part.id));
  next.joints = (next.joints || []).filter(joint => !(joint.part_ids || []).some(id => ids.includes(id)));
  previewParts = next.parts;
  previewJoints = next.joints;
  proposal = { kind: 'delete', summary: '删除 ' + ids.length + ' 件板件及关联连接。' };
  conflict = null; selectedId = null; selectedIds = new Set(); selectedKind = null;
  viewport?.load(previewParts, { fit: false, hardware: [], joints: previewJoints });
  render();
}
function setTool(next) {
  tool = next;
  if (next === 'advanced') {
    viewport?.setTool('select');
    $('measure-hud').hidden = true;
    renderAdvancedPanel();
    updateTools();
    return;
  }
  const viewportTool = ['measure', 'translate', 'rotate', 'scale'].includes(next) ? next : 'select';
  viewport?.setTool(viewportTool);
  if (next === 'measure') {
    $('measure-hud').hidden = false;
    $('measure-hud').replaceChildren('点选端点或中点作为起点');
  } else if (next === 'translate' || next === 'rotate') {
    $('measure-hud').hidden = false;
    $('measure-hud').replaceChildren(next === 'translate' ? '拖动轴移动零件 · 松开后预览' : '拖动圆环旋转零件 · 松开后预览');
  } else {
    $('measure-hud').hidden = true;
  }
  updateTools();
  if (next === 'select') renderRight();
}

window.addEventListener('keydown', event => {
  if ((event.key === 'Delete' || event.key === 'Backspace') && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName) && activeEditorIds().length) { event.preventDefault(); deleteSelectedParts(); return; }
  if (event.key === 'Escape' && tool === 'measure') {
    viewport?.clearMeasurement();
    $('measure-hud').hidden = true;
  }
});

$('undo-button').addEventListener('click', () => undoRedo(false));
$('redo-button').addEventListener('click', () => undoRedo(true));
document.querySelectorAll('[data-tool]').forEach(button => button.addEventListener('click', () => setTool(button.dataset.tool)));
document.querySelectorAll('[data-action="delete"]').forEach(button => button.addEventListener('click', deleteSelectedParts));
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('on', item === button));
  viewport?.setView(button.dataset.view);
}));
document.querySelectorAll('[data-action="check"]').forEach(button => button.addEventListener('click', runCheck));
$('check-top').addEventListener('click', runCheck);
$('docs-button').addEventListener('click', showDocuments);
$('cut-button').addEventListener('click', showCutLayout);
$('open-sample').addEventListener('click', openSample);
$('objects-tab').addEventListener('click', () => { leftTab = 'objects'; render(); });
$('warehouse-tab').addEventListener('click', showWarehouse);

const requested = new URLSearchParams(location.search).get('project');
if (requested) openProject(requested).catch(error => showEmpty(error.message));
else showEmpty();
