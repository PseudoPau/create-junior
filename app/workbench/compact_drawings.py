"""A3 fabrication sheets grouped by the physical part and connection.

Geometry is drawn afresh into sized blocks; labels keep paper-space sizes.
"""
from __future__ import annotations
from math import acos, degrees
from app.workbench.drawings import (
    AXES, FACE_NAMES, POSITIVE, data, number, fmt, scale_name, scale_for,
    text, line, rect, polygon, hdim, vdim, sheet as _base_sheet, finish, short_features,
    valid_feature, feature_label, _valid_outline, feature_segment, hole_entry_outline, drilling_note,
    convex_hull, _section_polygon, world, direction, dot, add, mul, norm,
    draw_part_sheets as legacy_part_sheets, draw_joint_sheets as joint_fragments,
)


def sheet(*args,**kwargs):
    return [entry.replace('font-size="2.8"','font-size="3"') for entry in _base_sheet(*args,**kwargs)]


def _face_block(out,part,face,rows,y,height,continuation=False):
    a,b,n=AXES[face];width,depth=part['size_mm'][a],part['size_mm'][b]
    turned=depth>width;display_w,display_h=(depth,width) if turned else (width,depth)
    sc=scale_for(display_w,display_h,220,max(12,height-34),2)
    x=30+(220-display_w*sc)/2;top=y+15+(height-34-display_h*sc)/2
    # A rotated face retains explicit local U/V axes and origin, avoiding ambiguous mirroring.
    def xy(u,v):return (x+v*sc,top+u*sc) if turned else (x+u*sc,top+(depth-v)*sc)
    label=FACE_NAMES[face]+(' · 续表' if continuation else '')
    out.append(text(17,y+7,label+'  '+scale_name(sc),3.6,attrs='font-weight="700"'))
    out.append(text(259,y+7,'孔位基准：O → U / V；深度向板内',3))
    if part.get('plane_cuts'):
        from app.workbench.solid import part_faces
        silhouette=convex_hull([(p[a]+width/2,p[b]+depth/2) for face_points in part_faces(part) for p in face_points])
        out.append(polygon([xy(u,v) for u,v in silhouette]))
    elif face in ('top','bottom') and part.get('outline_mm'):
        out.append(polygon([xy(u,v) for u,v in part['outline_mm']]))
    else:out.append(rect(x,top,display_w*sc,display_h*sc))
    out.append(hdim(x,x+display_w*sc,top+display_h*sc+7,top+display_h*sc,fmt(display_w)))
    out.append(vdim(top,top+display_h*sc,x-8,x,fmt(display_h)))
    ox,oy=xy(0,0);ud=(0,14) if turned else (14,0);vd=(14,0) if turned else (0,-14)
    out.append(line(ox,oy,ox+ud[0],oy+ud[1],'dimension','marker-end="url(#arrow)"')+text(ox+ud[0]+2,oy+ud[1]+1,'U',3))
    out.append(line(ox,oy,ox+vd[0],oy+vd[1],'dimension','marker-end="url(#arrow)"')+text(ox+vd[0]-2,oy+vd[1]-2,'V',3))
    out.append(text(ox-4,oy+4,'O',3))
    all_rows=[(label,f) for label,f in short_features(part) if f.get('face')==face]
    labels={label for label,_ in rows};seen=set()
    for label,f in all_rows:
        if not valid_feature(part,f):continue
        entry,axis,length=feature_segment(part,f,False);u,v=entry[a]+width/2,entry[b]+depth/2
        px,py=xy(u,v)
        if f['kind']=='hole':
            r=f['diameter_mm']/2*sc
            opening=hole_entry_outline(part,f)
            if opening:out.append(polygon([xy(point[a]+width/2,point[b]+depth/2) for point in opening]))
            if f.get('direction_local'):
                end=add(entry,mul(axis,length));ex,ey=xy(end[a]+width/2,end[b]+depth/2)
                out.append(line(px,py,ex,ey,'centerline','marker-end="url(#arrow)"'))
            out.append(line(px-r-1.5,py,px+r+1.5,py,'centerline')+line(px,py-r-1.5,px,py+r+1.5,'centerline'))
        else:
            out.append(polygon([xy(f['u_mm']+du,f['v_mm']+dv) for du,dv in [(0,0),(f['width_mm'],0),(f['width_mm'],f['length_mm']),(0,f['length_mm'])]]))
        key=(f['u_mm'],f['v_mm'])
        if key in seen:continue
        same=[lab for lab,item in all_rows if (item['u_mm'],item['v_mm'])==key and lab in labels]
        if not same:continue
        seen.add(key);left=px<x+display_w*sc/2;dx=6 if left else -6
        out.append(line(px,py,px+dx,py-5)+text(px+dx,py-6,'/'.join(same),3,'start' if left else 'end','class="dimtext"'))
    tx=264;out.append(text(tx,y+15,'孔',3)+text(tx+22,y+15,'U',3)+text(tx+43,y+15,'V',3)+text(tx+66,y+15,'孔径 / 深度',3))
    yy=y+23
    for label,f in rows:
        out.append(line(tx,yy-5,403,yy-5))
        spec=feature_label(part,f) if valid_feature(part,f) else '数据无效'
        out.append(text(tx,yy,label,3)+text(tx+22,yy,fmt(round(feature_segment(part,f,False)[0][a]+width/2,3)),3)+text(tx+43,yy,fmt(round(feature_segment(part,f,False)[0][b]+depth/2,3)),3)+text(tx+66,yy,spec,3))
        note=drilling_note(part,f)
        if note:out.append(text(tx,yy+4,note,3))
        yy+=12 if note else 8
    out.append(line(16,y+height-1,404,y+height-1))
    return scale_name(sc)


def _cut_block(out,part,cut,index,y,height):
    normal=norm(cut['normal_local']);axes=sorted(range(3),key=lambda i:abs(normal[i]),reverse=True)[:2]
    a=max(axes,key=lambda i:part['size_mm'][i]);b=next(i for i in axes if i!=a);n=next(i for i in range(3) if i not in axes)
    u=[0.,0.,0.];v=u.copy();w=u.copy();u[a]=1;v[b]=1;w[n]=1
    section=_section_polygon(part,world(part,[0,0,0]),direction(part,u),direction(part,v),direction(part,w))
    if not section:return ''
    width,depth=part['size_mm'][a],part['size_mm'][b];sc=scale_for(width,depth,220,max(20,height-43),2)
    x=30+(220-width*sc)/2;top=y+22+(height-43-depth*sc)/2
    def xy(point):return (x+(point[0]+width/2)*sc,top+(depth/2-point[1])*sc)
    nearest=max(range(3),key=lambda i:abs(normal[i]));angle=degrees(acos(min(1,abs(normal[nearest]))))
    out.append(text(17,y+7,'C'+str(index+1)+' · 斜切剖面  '+scale_name(sc),3.6,attrs='font-weight="700"'))
    out.append(polygon([xy(point) for point in section],'sectionedge','fill="url(#hatch)"'))
    out.append(text(264,y+23,'相对 '+('+' if normal[nearest]>0 else '−')+'XYZ'[nearest]+' 端面 '+fmt(round(angle,2))+'°',3.5,attrs='font-weight="700"'))
    out.append(text(264,y+31,'剖面坐标：横 '+'XYZ'[a]+' / 竖 '+'XYZ'[b],3))
    endpoints=[]
    for point in section:
        local=[0.,0.,0.];local[a],local[b]=point
        if abs(dot(normal,local)-cut['offset_mm'])<.01:endpoints.append(point)
    if len(endpoints)>=2:
        p1,p2=endpoints[0],endpoints[-1];px,py=xy(p1);qx,qy=xy(p2)
        out.append(line(px,py,qx,qy,'outline','stroke-width=".9"'))
        out.append(line((px+qx)/2,(py+qy)/2,255,y+21))
        out.append(text(264,y+43,'斜切水平差 '+fmt(round(abs(p2[0]-p1[0]),3))+' mm',3))
    for row,sign in enumerate([1,-1]):
        values=[point[0] for point in section if abs(point[1]-sign*depth/2)<.01]
        if len(values)>1:
            length=max(values)-min(values);p1,p2=xy((min(values),sign*depth/2)),xy((max(values),sign*depth/2))
            offset=-7 if sign>0 else 7
            out.append(hdim(p1[0],p2[0],p1[1]+offset,p1[1],fmt(round(length,3))))
            out.append(text(264,y+55+row*8,('+' if sign>0 else '−')+'XYZ'[b]+' 表面长度 '+fmt(round(length,3))+' mm',3))
    out.append(vdim(top,top+depth*sc,x-8,x,fmt(depth)))
    out.append(line(16,y+height-1,404,y+height-1))
    return scale_name(sc)


def draw_part_sheets(part,project):
    part,project=data(part),data(project)
    if not _valid_outline(part) or len(part.get('size_mm',[]))!=3 or not all(number(x) and x>0 for x in part['size_mm']):
        return legacy_part_sheets(part,project)
    features=short_features(part)
    if not features and not part.get('plane_cuts'):return legacy_part_sheets(part,project)
    if any(f.get('face') not in AXES for _,f in features):return legacy_part_sheets(part,project)
    blocks=[]
    faces=sorted(AXES,key=lambda face:part['size_mm'][AXES[face][0]]*part['size_mm'][AXES[face][1]],reverse=True)
    for face in faces:
        rows=[item for item in features if item[1].get('face')==face]
        chunks=[];chunk=[];used_height=0
        for item in rows:
            row_height=12 if drilling_note(part,item[1]) else 8
            if chunk and used_height+row_height>174:chunks.append(chunk);chunk=[];used_height=0
            chunk.append(item);used_height+=row_height
        if chunk:chunks.append(chunk)
        for chunk_index,chunk in enumerate(chunks):
            a,b,_=AXES[face];u,v=part['size_mm'][a],part['size_mm'][b]
            blocks.append({'kind':'face','face':face,'rows':chunk,'continuation':chunk_index>0,'minimum':max(50,min(80,34+min(u,v)/5),22+sum(12 if drilling_note(part,f) else 8 for _,f in chunk)),'weight':max(.1,min(u,v)/max(u,v))})
    for index,cut in enumerate(part.get('plane_cuts',[])):
        blocks.append({'kind':'cut','cut':cut,'index':index,'minimum':70,'weight':.25})
    if part.get('plane_cuts'):
        regular=[b for b in blocks if b['kind']=='face' and not any(drilling_note(part,f) for _,f in b['rows'])]
        special=[b for b in blocks if b['kind']=='cut']+[b for b in blocks if b['kind']=='face' and any(drilling_note(part,f) for _,f in b['rows'])]
        for b in regular:b['setup']='normal'
        for b in special:b['setup']='angled'
        blocks=regular+special
    pages=[];pending=[];used=0
    for block in blocks:
        if pending and (len(pending)==3 or used+block['minimum']>210 or pending[-1].get('setup')!=block.get('setup')):pages.append(pending);pending=[];used=0
        pending.append(block);used+=block['minimum']
    if pending:pages.append(pending)
    results=[];code='P-'+part['id'];name=part.get('name') or part['id'];material=project.get('materials',{}).get(part.get('material_id'),{}).get('name','')
    part_number=next((i for i,p in enumerate(project.get('parts',[]),1) if p['id']==part['id']),None)
    for page_index,blocks in enumerate(pages):
        suffix='' if len(pages)==1 else ' · '+str(page_index+1)+'/'+str(len(pages))
        out=sheet(name+' · 加工图'+suffix,code,project,material,kind='零件加工图')
        out.append(text(17,34,('P'+str(part_number)+'  ' if part_number else '')+'净料 X × Y × Z = '+' × '.join(fmt(v) for v in part['size_mm'])+' mm',3.5,attrs='font-weight="700"'))
        invalid=[label for label,f in features if not valid_feature(part,f)]
        if invalid:out.append(text(17,39,'草稿无效：'+'、'.join(invalid)+' 尺寸待补；未按有效孔槽绘制。',3,attrs='font-weight="700"' if False else ''))
        out.append(text(404,34,'视图方向：'+ ' / '.join(FACE_NAMES[b['face']] if b['kind']=='face' else 'C'+str(b['index']+1) for b in blocks),3,'end'))
        remaining=210-sum(b['minimum'] for b in blocks);weights=sum(b['weight'] for b in blocks);y=41;scales=[]
        for block in blocks:
            height=block['minimum']+remaining*block['weight']/weights
            if block['kind']=='face':scales.append(_face_block(out,part,block['face'],block['rows'],y,height,block['continuation']))
            else:scales.append(_cut_block(out,part,block['cut'],block['index'],y,height))
            y+=height
        ids=[code]+[code+'-'+face+'-'+str(i//12+1) for face in dict.fromkeys(b['face'] for b in blocks if b['kind']=='face') for i in range(0,sum(f.get('face')==face for _,f in features),12)]
        results.append({'id':code if page_index==0 else code+'-continued-'+str(page_index+1),'part_id':part['id'],'title':name+' · 加工图'+suffix,'sheet_type':'part','faces':list(dict.fromkeys(b['face'] for b in blocks if b['kind']=='face')),'source_sheet_ids':ids,'scale':' / '.join(dict.fromkeys(scales)),'svg':finish(out)})
    return results


def draw_joint_sheets(project,resolved_hardware):
    project=data(project);fragments=joint_fragments(project,resolved_hardware,compact=True)
    parts={p['id']:p for p in project.get('parts',[])};joints={j['id']:j for j in project.get('joints',[])}
    grouped={}
    for fragment in fragments:
        joint=joints[fragment['joint_id']]
        key=tuple(sorted(tuple(round(v,3) for v in parts[pid]['size_mm']) for pid in joint.get('part_ids',[]) if pid in parts))
        fragment['layout_group']=key;grouped.setdefault(key,[]).append(fragment)
    fragments=[f for group in grouped.values() for f in group]
    pages=[];pending=[];used=0
    for fragment in fragments:
        height=fragment['height_mm']
        if pending and (len(pending)==2 or used+height>228 or pending[-1]['layout_group']!=fragment['layout_group']):pages.append(pending);pending=[];used=0
        if height>228:
            if pending:pages.append(pending);pending=[];used=0
            # Preserve unusually long hardware records with their original full-page drawing.
            original=next((s for s in joint_fragments(project,resolved_hardware) if s['joint_id']==fragment['joint_id']),None)
            if original:pages.append([original])
            continue
        pending.append(fragment);used+=height
    if pending:pages.append(pending)
    results=[]
    for page_index,items in enumerate(pages):
        if 'fragment' not in items[0]:results.extend(items);continue
        if len(items)==1:
            full=next((s for s in joint_fragments(project,resolved_hardware) if s['joint_id']==items[0]['joint_id']),None)
            if full:
                full['svg']=full['svg'].replace('font-size="2.6"','font-size="3"').replace('font-size="2.7"','font-size="3"').replace('font-size="2.8"','font-size="3"')
                full['joint_ids']=[full['joint_id']];full['source_sheet_ids']=[full['id']];full['joint_regions']=[{'id':full['joint_id'],'title':full['title'],'bounds_mm':[10,25,400,233]}]
                results.append(full);continue
        code='J-sheet-'+str(page_index+1);out=sheet('连接大样 · '+str(page_index+1)+' / '+str(len(pages)),code,project,scale='见各局部',kind='连接大样')
        y=28;regions=[]
        for item in items:
            out.append('<g transform="translate(0 '+fmt(y)+')">'+item['fragment']+'</g>')
            regions.append({'id':item['joint_id'],'title':item['title'],'bounds_mm':[10,y,400,item['height_mm']]})
            y+=item['height_mm'];out.append(line(15,y,405,y))
        results.append({'id':code,'title':' / '.join(item['title'] for item in items)+' · 大样','sheet_type':'joint','joint_id':items[0]['joint_id'],'joint_ids':[item['joint_id'] for item in items],'joint_regions':regions,'source_sheet_ids':[item['id'] for item in items],'scale':' / '.join(dict.fromkeys(item['scale'] for item in items)),'svg':finish(out)})
    return results
