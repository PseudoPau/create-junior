"""Geometry-derived cutting and assembly overview on A3 paper."""
from __future__ import annotations
from collections import OrderedDict
from math import ceil, cos, sin, pi, isfinite
from app.workbench.drawings import world, fmt, text, line, polygon, rect


def _wrap(value, width):
    lines, row, units = [], '', 0.0
    for char in str(value):
        size = .55 if ord(char) < 128 else 1
        if units + size > width and row:
            lines.append(row); row = ''; units = 0
        row += char; units += size
    if row: lines.append(row)
    return lines


def _words(x,y,value,width,size=3,leading=4):
    return ''.join(text(x,y+i*leading,row,size) for i,row in enumerate(_wrap(value,width)))


def _project(point):
    x,y,z=point
    return (.8660254*(x-z), .42*(x+z)-y, x+.84*y+z)


def _faces(part):
    from app.workbench.solid import part_faces
    return [[world(part,point) for point in face] for face in part_faces(part)]


def _scene(parts,box,active=None,hardware=(),labels=None):
    if not parts:return ''
    faces=[]
    for part in parts:
        for face in _faces(part):
            projected=[_project(point) for point in face]
            faces.append((sum(v[2] for v in projected)/len(projected),part['id'],projected))
    points=[p for _,_,face in faces for p in face]
    left,top=min(p[0] for p in points),min(p[1] for p in points)
    width,height=max(p[0] for p in points)-left,max(p[1] for p in points)-top
    x,y,bw,bh=box;scale=min(bw/max(width,1),bh/max(height,1))
    ox,oy=x+(bw-width*scale)/2-left*scale,y+(bh-height*scale)/2-top*scale
    def point(value):
        u,v,*_=_project(value);return (ox+u*scale,oy+v*scale)
    out=[]
    for _,pid,face in sorted(faces,key=lambda item:item[0]):
        focused=active is None or pid in active
        fill='#fff' if focused else '#f4f4f4';stroke='#151515' if focused else '#c7c7c7'
        out.append(polygon([(ox+v[0]*scale,oy+v[1]*scale) for v in face],attrs=f'fill="{fill}" stroke="{stroke}" stroke-width="{.38 if focused else .2}" stroke-linejoin="round"'))
    for item in hardware:
        if item.get('kind')!='bolt':continue
        px,py=point(item['position_mm']);axis=item['direction'];origin=[c-a*65 for c,a in zip(item['position_mm'],axis)];ex,ey=point(origin)
        out.append(line(ex,ey,px,py,attrs='stroke="#111" stroke-width=".45" marker-end="url(#install-arrow)"'))
        out.append(f'<circle cx="{fmt(px)}" cy="{fmt(py)}" r="1" fill="white" stroke="#111" stroke-width=".3"/>')
    if labels:
        ordered=sorted(parts,key=lambda part:point(part['position_mm'])[1])
        for i,part in enumerate(ordered):
            px,py=point(part['position_mm']);lx=x-6 if i%2==0 else x+bw+3;ly=y+7+(i//2)*max(13,(bh-16)/max(1,ceil(len(parts)/2)-1))
            out.append(line(px,py,lx+3,ly-1,attrs='stroke="#777" stroke-width=".2"'))
            out.append(text(lx,ly,labels[part['id']],3.2,attrs='font-weight="700" class="halo"'))
    return ''.join(out)


def _hardware_key(item):return (str(item.get('name','')),str(item.get('spec','')))


def _hardware_catalog(joints):
    catalog=OrderedDict()
    for joint in joints:
        for item in joint.get('hardware',[]):
            key=_hardware_key(item)
            if key not in catalog:catalog[key]={**item,'quantity':0,'code':'H'+str(len(catalog)+1)}
            catalog[key]['quantity']+=item.get('quantity',0)
    return catalog


def _hardware_icon(item,x,y):
    kind=(item.get('geometry') or {}).get('kind');out=[];attrs='fill="white" stroke="#111" stroke-width=".4"'
    if kind=='bolt':
        out += [rect(x,y-2,17,3,attrs=attrs),rect(x-1.8,y-3.5,2.5,6,attrs=attrs)]
        for i in range(3,17,2):out.append(line(x+i,y-2,x+i-1,y+1,attrs='stroke="#111" stroke-width=".2"'))
    elif kind=='washer':out += [f'<ellipse cx="{x+7}" cy="{y}" rx="6" ry="3.4" {attrs}/>',f'<ellipse cx="{x+7}" cy="{y}" rx="2" ry="1.2" {attrs}/>']
    elif kind=='hex_nut':
        out.append(polygon([(x+7+5*cos(i*pi/3),y+4*sin(i*pi/3)) for i in range(6)],attrs=attrs));out.append(f'<ellipse cx="{x+7}" cy="{y}" rx="2" ry="1.7" {attrs}/>')
    elif kind=='barrel_nut':out += [rect(x+3,y-4,9,8,attrs=attrs),f'<ellipse cx="{x+7.5}" cy="{y-4}" rx="4.5" ry="1.4" {attrs}/>',f'<circle cx="{x+7.5}" cy="{y}" r="2" {attrs}/>']
    else:out.append(rect(x+1,y-3,14,6,attrs=attrs))
    return ''.join(out)


def _short_spec(item):
    geometry=item.get('geometry') or {};kind=geometry.get('kind')
    if kind=='bolt':return f'M{fmt(geometry["diameter_mm"])} × {fmt(geometry["length_mm"])}'
    if kind=='washer':return f'Ø{fmt(geometry["bore_diameter_mm"])} / Ø{fmt(geometry["diameter_mm"])} / 厚{fmt(geometry["length_mm"])}'
    if kind=='barrel_nut':return f'M{fmt(geometry["bore_diameter_mm"])} · Ø{fmt(geometry["diameter_mm"])} × {fmt(geometry["length_mm"])}'
    if kind=='hex_nut':return f'M{fmt(geometry["bore_diameter_mm"])} · 厚{fmt(geometry["length_mm"])}'
    return item.get('spec','')


def _step(out,joint,index,parts,used,box,part_codes,catalog,instances):
    x,y,w,h=box
    out += [rect(x,y,w,h,attrs='fill="white" stroke="#d9d9d9" stroke-width=".3" rx="2"'),f'<circle cx="{x+7}" cy="{y+8}" r="4" fill="#111"/>',text(x+7,y+9.2,index+1,3.7,'middle','style="fill:white" font-weight="700"')]
    out.append(text(x+14,y+9,joint.get('name') or '连接 '+str(index+1),3.4,attrs='font-weight="600"'))
    out.append(text(x+w-5,y+9,' + '.join(part_codes.get(pid,pid) for pid in joint.get('part_ids',[])),3.2,'end','font-weight="700"'))
    involved=set(joint.get('part_ids',[]));shown=[part for part in parts if part['id'] in used|involved]
    out.append(_scene(shown,(x+6,y+16,77,42),involved,[i for i in instances if i.get('joint_id')==joint.get('id')]))
    hardware=joint.get('hardware',[])
    for row,item in enumerate(hardware):
        iy=y+23+row*12
        out.append(_hardware_icon(item,x+89,iy-2))
        out.append(text(x+111,iy-1,catalog[_hardware_key(item)]['code'],3.2,attrs='font-weight="700"'))
        out.append(text(x+111,iy+3.5,'× '+str(item.get('quantity',0)),3.2))
    kinds={(item.get('geometry') or {}).get('kind') for item in hardware}
    note=joint.get('assembly_note','');operation='对孔 → 安装五金'
    if 'barrel_nut' in kinds:
        operation='装横孔螺母并对孔 → 垫圈入沉孔 → 穿栓' if '沉孔' in note else '装横孔螺母并对孔 → 套垫圈 → 手旋入栓'
    elif 'hex_nut' in kinds:
        operation='底边齐平 → 两端放垫圈 → 穿栓带螺母，轻拧' if '下边齐平' in note else '对孔 → 两端放垫圈 → 穿栓带螺母'
    out.append(text(x+5,y+h-9,operation,3))
    out.append(text(x+w-5,y+h-3,'J-'+str(joint.get('id','')),3,'end'))


def draw_assembly_sheets(project,hardware_instances):
    project=project.model_dump(mode='json') if hasattr(project,'model_dump') else project
    parts=[part for part in project.get('parts',[]) if len(part.get('size_mm',[]))==3 and all(isinstance(v,(int,float)) and isfinite(v) and v>0 for v in part['size_mm'])]
    if not parts:return []
    joints=project.get('joints',[]);catalog=_hardware_catalog(joints);hardware=list(catalog.values());codes={part['id']:'P'+str(i+1) for i,part in enumerate(parts)}
    pages=max(1,ceil(len(parts)/6),ceil(len(hardware)/6),ceil(len(joints)/6));result=[]
    for page in range(pages):
        code='A-overview'+('' if page==0 else '-'+str(page+1));out=['<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">','<defs><marker id="install-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="2.8" markerHeight="2.8" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8 Z" fill="#111"/></marker></defs>','<style>text{font-family:Arial,"Microsoft YaHei",sans-serif;fill:#111}.halo{paint-order:stroke;stroke:#fff;stroke-width:2;stroke-linejoin:round}</style>','<rect width="420" height="297" fill="white"/>']
        status='已确认' if project.get('revision') is not None and project.get('confirmed_revision')==project.get('revision') and project.get('acknowledged_limits') else '设计草稿'
        out += [text(12,17,'JUNIOR',6.5,attrs='font-weight="800"'),text(49,17,'开工总览',6,attrs='font-weight="700"'),text(408,16,'v'+str(project.get('revision','—'))+' · '+status+'  /  '+str(page+1)+'-'+str(pages),3.3,'end'),text(12,24,project.get('name','木作项目'),3.5),line(12,29,408,29,attrs='stroke="#111" stroke-width=".6"')]
        out.append(text(12,37,'01  认识零件',4.1,attrs='font-weight="700"'));out.append(_scene(parts,(22,43,61,62),labels=codes if len(parts)<=8 else None))
        out += [text(12,113,'P 板件 / H 五金',3.1),text(96,37,'下料 · 净料 X × Y × Z / mm',3.7,attrs='font-weight="700"')]
        page_parts=parts[page*6:page*6+6]
        material_ids=list(dict.fromkeys(part.get('material_id','') for part in page_parts))
        materials={mid:(project.get('materials',{}).get(mid) or {}).get('name',mid) for mid in material_ids}
        material_codes={mid:'M'+str(i+1) for i,mid in enumerate(material_ids)}
        if len(material_ids)==1:out.append(text(96,44,materials[material_ids[0]]+' · 全部板件',3))
        else:
            # Keep per-part material mapping without repeating long material names.
            for i,mid in enumerate(material_ids):out.append(text(96+(i%2)*91,43+(i//2)*4,material_codes[mid]+' '+materials[mid],3))
        table_y=49+max(0,ceil(len(material_ids)/2)-1)*4
        spacing=min(10,(114-table_y)/6)
        for row,part in enumerate(page_parts):
            y=table_y+row*spacing;out.append(text(96,y+4,codes[part['id']],3.3,attrs='font-weight="700"'));neutral={**part,'position_mm':[0,0,0],'rotation_deg':[0,0,0]};out.append(_scene([neutral],(107,y,18,7)))
            out.append(text(130,y+4,part.get('name',part['id']),3.2))
            out.append(text(179,y+4,' × '.join(fmt(v) for v in part['size_mm']),3.2))
            out.append(text(272,y+4,'× 1'+(' / '+material_codes[part.get('material_id','')] if len(material_ids)>1 else ''),3,'end'))
            out.append(line(96,y+8,278,y+8,attrs='stroke="#e1e1e1" stroke-width=".2"'))
        out.append(text(286,37,'02  备齐五金',4.1,attrs='font-weight="700"'))
        for row,item in enumerate(hardware[page*6:page*6+6]):
            y=48+row*11.5;out.append(text(286,y,item['code'],3.2,attrs='font-weight="700"'));out.append(_hardware_icon(item,296,y-1));out.append(text(318,y-2,item.get('name','五金')+' × '+str(item['quantity']),3.2));out.append(text(318,y+3,_short_spec(item),3))
        out += [line(12,118,408,118,attrs='stroke="#111" stroke-width=".6"'),text(12,126,'03  按顺序装配',4.1,attrs='font-weight="700"'),text(408,126,'黑线 本步 / 浅线 此前 / 箭头 穿栓方向',3,'end')]
        for offset,joint in enumerate(joints[page*6:page*6+6]):
            index=page*6+offset;used={pid for j in joints[:index] for pid in j.get('part_ids',[])};_step(out,joint,index,parts,used,(12+(offset%3)*134,132+(offset//3)*74,128,70),codes,catalog,hardware_instances)
        if not joints:out.append(text(12,151,'此版尚未定义连接顺序。',3.4))
        out += [line(12,280,408,280,attrs='stroke="#111" stroke-width=".4"'),text(12,287,'加工孔槽 → 打磨 → 装齐 → 平面校正 → 交替收紧全部螺栓',3),text(408,287,'A3 横向 · 示意图 · 尺寸以零件图为准',3,'end'),text(12,293,code+' · P 编号对应本页清单；净料未含刨削及锯缝余量。',3),'</svg>']
        result.append({'id':code,'title':'开工总览 · 下料与装配'+('' if pages==1 else ' '+str(page+1)),'sheet_type':'assembly_overview','scale':'示意图','svg':''.join(out)})
    return result
