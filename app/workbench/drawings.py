"""A3 nominal-geometry drawings; paper coordinates and model lengths are mm."""
from __future__ import annotations
from html import escape
from math import sin, cos, radians, sqrt, atan2, isfinite, acos, degrees, pi
from itertools import product

AXES={'top':(0,2,1),'bottom':(0,2,1),'front':(0,1,2),'back':(0,1,2),'left':(2,1,0),'right':(2,1,0)}
FACE_NAMES={'top':'顶面','bottom':'底面','front':'前面','back':'背面','left':'左面','right':'右面'}
POSITIVE={'top','front','right'}
SCALES=[2,1,.5,.2,.1,.05,.02,.01]

def data(value):return value.model_dump(mode='json') if hasattr(value,'model_dump') else value

def number(value):return isinstance(value,(float,int)) and not isinstance(value,bool) and isfinite(value)

def fmt(value):return f'{value:.3f}'.rstrip('0').rstrip('.') if number(value) else str(value)

def scale_name(value):return f'{fmt(value)}:1' if value>=1 else f'1:{fmt(1/value)}'

def scale_for(width,height,available_width,available_height,max_scale=1):
    return next((s for s in SCALES if s<=max_scale and width*s<=available_width and height*s<=available_height),.01)

def text(x,y,value,size=3.2,anchor='start',attrs=''):
    return f'<text x="{fmt(x)}" y="{fmt(y)}" font-size="{fmt(size)}" text-anchor="{anchor}" {attrs}>{escape(str(value))}</text>'

def line(x1,y1,x2,y2,cls='thin',attrs=''):
    return f'<line x1="{fmt(x1)}" y1="{fmt(y1)}" x2="{fmt(x2)}" y2="{fmt(y2)}" class="{cls}" {attrs}/>'

def rect(x,y,w,h,cls='outline',attrs=''):
    return f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" class="{cls}" {attrs}/>'

def polygon(points,cls='outline',attrs=''):
    return '<polygon points="'+' '.join(f'{fmt(x)},{fmt(y)}' for x,y in points)+f'" class="{cls}" {attrs}/>'

def hdim(x1,x2,y,object_y,label):
    if x1>x2:x1,x2=x2,x1
    sign=1 if y>object_y else -1
    return line(x1,object_y+sign,x1,y+sign*2)+line(x2,object_y+sign,x2,y+sign*2)+line(x1,y,x2,y,'dimension','marker-start="url(#arrow)" marker-end="url(#arrow)"')+text((x1+x2)/2,y-1.5,label,3,'middle','class="dimtext"')

def vdim(y1,y2,x,object_x,label):
    if y1>y2:y1,y2=y2,y1
    sign=1 if x>object_x else -1
    return line(object_x+sign,y1,x+sign*2,y1)+line(object_x+sign,y2,x+sign*2,y2)+line(x,y1,x,y2,'dimension','marker-start="url(#arrow)" marker-end="url(#arrow)"')+text(x-1.8,(y1+y2)/2,label,3,'middle',f'class="dimtext" transform="rotate(-90 {fmt(x-1.8)} {fmt((y1+y2)/2)})"')

def sheet(title,code,project,material='',scale='见各视图',kind='零件图'):
    return ['<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">',
    '<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="3" markerHeight="3" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M0,1 L7,4 L0,7 Z" fill="#111"/></marker><pattern id="hatch" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="3" stroke="#444" stroke-width=".18"/></pattern><pattern id="hatch2" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><line x1="0" y1="0" x2="0" y2="3" stroke="#444" stroke-width=".18"/></pattern></defs>',
    '<style>text{font-family:Arial,"Microsoft YaHei",sans-serif;fill:#111}.outline{fill:none;stroke:#111;stroke-width:.5;stroke-linejoin:round}.thin,.dimension{fill:none;stroke:#111;stroke-width:.25}.hiddenline{fill:none;stroke:#444;stroke-width:.25;stroke-dasharray:2 1}.centerline{fill:none;stroke:#555;stroke-width:.18;stroke-dasharray:5 1 1 1}.dimtext{paint-order:stroke;stroke:white;stroke-width:1.4;stroke-linejoin:round}.sectionedge{stroke:#111;stroke-width:.5;stroke-linejoin:round}.fastener{fill:#f4f4f4;stroke:#111;stroke-width:.35}</style>',
    '<rect width="420" height="297" fill="white"/>',rect(10,10,400,277),text(16,20,title[:70],5),text(404,20,kind,3.5,'end'),line(10,25,410,25),
    line(10,258,410,258),text(16,267,'单位：mm　　未注尺寸见同编号加工表',3),text(16,275,'实线：可见轮廓　虚线：隐藏轮廓　点划线：中心线',2.8),text(16,283,'打印：A3，实际大小 / 100%；尺寸标注优先。',2.8),
    rect(230,258,180,29),line(230,269,410,269),line(230,278,410,278),line(350,258,350,287),
    text(233,265,code[:38],3.3),text(353,265,'版本 '+str(project.get('revision','—')),3),text(233,275,'材料：'+(material[:37] or '见零件表'),2.8),text(353,275,'比例 '+scale,2.8),text(233,284,'JUNIOR · '+kind,2.8),text(353,284,'A3 · '+('局部剖视' if kind=='连接大样' else '局部 U/V' if kind=='加工面图' else '第一角法'),2.8)]

def finish(out):return ''.join(out)+'</svg>'

def rot(part):
    rx,ry,rz=map(radians,part.get('rotation_deg',[0,0,0]));cx,cy,cz,sx,sy,sz=cos(rx),cos(ry),cos(rz),sin(rx),sin(ry),sin(rz)
    return [[cy*cz,-cy*sz,sy],[cx*sz+sx*sy*cz,cx*cz-sx*sy*sz,-sx*cy],[sx*sz-cx*sy*cz,sx*cz+cx*sy*sz,cx*cy]]

def dot(a,b):return sum(x*y for x,y in zip(a,b))
def add(a,b):return [x+y for x,y in zip(a,b)]
def sub(a,b):return [x-y for x,y in zip(a,b)]
def mul(a,k):return [x*k for x in a]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def norm(a):
    length=sqrt(dot(a,a));return mul(a,1/length) if length>1e-9 else [0,0,0]
def world(part,local):return add([dot(row,local) for row in rot(part)],part.get('position_mm',[0,0,0]))
def direction(part,local):return [dot(row,local) for row in rot(part)]
def feature_segment(part,feature,world_space=True):
    from app.workbench.engine import _hole_segment
    point,axis,length=_hole_segment(part,feature)
    if world_space:return point,axis,length
    matrix=rot(part);delta=sub(point,part.get('position_mm',[0,0,0]))
    return ([sum(matrix[j][i]*delta[j] for j in range(3)) for i in range(3)],
            [sum(matrix[j][i]*axis[j] for j in range(3)) for i in range(3)],length)


def valid_feature(part,f):
    from app.workbench.engine import _feature_error
    try:return _feature_error(part,f) is None
    except (KeyError,TypeError,IndexError,ValueError):return False


def entry_surface(part,feature):
    """Outward normal of the actual material plane carrying the drill entry."""
    point,axis,_=feature_segment(part,feature,False)
    for index,cut in enumerate(part.get('plane_cuts',[])):
        normal=cut['normal_local']
        if abs(dot(normal,point)-cut['offset_mm'])<.02 and dot(normal,axis)<-1e-7:
            return norm(normal),'C'+str(index+1)
    normal=[0.,0.,0.];normal[AXES[feature['face']][2]]=1 if feature['face'] in POSITIVE else -1
    return normal,FACE_NAMES[feature['face']]


def hole_entry_outline(part,feature,steps=32):
    """True cylinder/entry-plane intersection, before projecting into a view."""
    point,axis,_=feature_segment(part,feature,False);axis=norm(axis);normal,_=entry_surface(part,feature)
    cosine=abs(dot(axis,normal));radius=feature['diameter_mm']/2
    if cosine<1e-6:return []
    tangent=sub(axis,mul(normal,dot(axis,normal)))
    if dot(tangent,tangent)<1e-10:
        seed=[1,0,0] if abs(normal[0])<.9 else [0,1,0];tangent=cross(normal,seed)
    major=norm(tangent);minor=norm(cross(normal,major))
    return [add(point,add(mul(major,radius/cosine*cos(2*pi*i/steps)),mul(minor,radius*sin(2*pi*i/steps)))) for i in range(steps)]


def drilling_note(part,feature):
    if not feature.get('direction_local') and not feature.get('entry_mm'):return ''
    _,axis,_=feature_segment(part,feature,False);normal,surface=entry_surface(part,feature)
    angle=degrees(acos(max(-1,min(1,-dot(norm(axis),normal)))))
    direction_text=', '.join(fmt(round(value,4)) for value in axis)
    return ('垂直'+surface if angle<.01 else '与'+surface+'内法线 '+fmt(round(angle,2))+'°')+'；轴 X/Y/Z = '+direction_text


def feature_label(part,f):
    n=AXES[f['face']][2];through=abs(f['depth_mm']-part['size_mm'][n])<1e-5
    if f.get('entry_mm') or f.get('direction_local') or part.get('plane_cuts'):
        from app.workbench.solid import solid_planes
        point,axis,length=feature_segment(part,f,False);end=add(point,mul(axis,length))
        through=any(abs(dot(normal,end)-offset)<.02 and dot(normal,axis)>1e-7 for normal,offset in solid_planes(part))
    depth=('通孔 · 轴长 '+fmt(f['depth_mm'])) if through and f.get('direction_local') else '通孔' if through else '深 '+fmt(f['depth_mm'])
    size='Ø'+fmt(f['diameter_mm']) if f['kind']=='hole' else fmt(f['width_mm'])+' × '+fmt(f['length_mm'])
    return size+' / '+depth


def short_features(part):return [(f'H{i+1}' if f.get('kind')=='hole' else f'S{i+1}',f) for i,f in enumerate(part.get('features',[]))]

def _overview_notes(out,part):
    """Draft markers and coordinate reminders on the part overview sheet."""
    features=short_features(part)
    invalid=[label for label,f in features if not valid_feature(part,f)]
    slots=[label for label,f in features if f.get('kind')!='hole']
    access=[label for label,f in features if f.get('role')=='hardware_access']
    out.append(text(17,232,'底面 X/Z：与俯视同面、法向相反，孔槽尺寸见底面加工图。',2.8))
    notes=[]
    if invalid:notes.append('草稿无效：'+'、'.join(invalid)+' 尺寸待补')
    if slots:notes.append('槽 U/V 是最小角')
    if access:notes.append('五金安装孔：'+'、'.join(access))
    if notes:out.append(text(17,237,'；'.join(notes),2.8))

def _overview_view(out,part,axis_u,axis_v,normal,cx,cy,scale,title):
    size=part['size_mm'];u_index,u_sign=axis_u;v_index,v_sign=axis_v
    width,height=size[u_index]*scale,size[v_index]*scale;x,y=cx-width/2,cy-height/2
    out.append(text(cx,y-11,title,3.3,'middle'))
    if part.get('plane_cuts'):
        from app.workbench.solid import part_faces
        projected=[(cx+p[u_index]*u_sign*scale,cy-p[v_index]*v_sign*scale) for face in part_faces(part) for p in face]
        out.append(polygon(convex_hull(projected)))
    elif normal==1 and part.get('outline_mm'):
        points=[]
        for px,pz in part['outline_mm']:
            local=[px-size[0]/2,0,pz-size[2]/2];points.append((cx+local[u_index]*u_sign*scale,cy-local[v_index]*v_sign*scale))
        out.append(polygon(points))
        for index,(px,pz) in enumerate(part['outline_mm'],1):
            if px in (0,size[0]) and pz in (0,size[2]):continue
            out.append(text(points[index-1][0],points[index-1][1]-2,f'P{index}: X={fmt(px)}，Z={fmt(pz)} mm',2.4,'middle','class="dimtext"'))
    else:out.append(rect(x,y,width,height))
    for _,f in short_features(part):
        if not valid_feature(part,f):continue
        point,axis,length=feature_segment(part,f,False);px=cx+point[u_index]*u_sign*scale;py=cy-point[v_index]*v_sign*scale
        if AXES[f['face']][:2] in ((u_index,v_index),(v_index,u_index)):
            out.append(text(px+2.5,py-2.5,f'U={fmt(f["u_mm"])} V={fmt(f["v_mm"])}',2.4,'start','class="dimtext"'))
        if f['kind']=='hole':
            radius=f['diameter_mm']/2*scale
            if f.get('direction_local') or f.get('entry_mm'):
                opening=hole_entry_outline(part,f)
                out.append(polygon([(cx+p[u_index]*u_sign*scale,cy-p[v_index]*v_sign*scale) for p in opening],'outline' if axis[normal]<0 else 'hiddenline'))
                end=add(point,mul(axis,length));out.append(line(px,py,cx+end[u_index]*u_sign*scale,cy-end[v_index]*v_sign*scale,'centerline'))
            elif abs(axis[normal])>.99:
                cls='outline' if axis[normal]<0 else 'hiddenline';out.append(f'<circle cx="{fmt(px)}" cy="{fmt(py)}" r="{fmt(radius)}" class="{cls}"/>')
                out.append(line(px-radius-2,py,px+radius+2,py,'centerline')+line(px,py-radius-2,px,py+radius+2,'centerline'))
            else:
                dx=axis[u_index]*u_sign*length*scale;dy=-axis[v_index]*v_sign*length*scale;perp=norm([-dy,dx,0]);out.append(polygon([(px+perp[0]*radius,py+perp[1]*radius),(px+dx+perp[0]*radius,py+dy+perp[1]*radius),(px+dx-perp[0]*radius,py+dy-perp[1]*radius),(px-perp[0]*radius,py-perp[1]*radius)],'hiddenline'))
        elif AXES[f['face']][2]==normal:
            a,b,_=AXES[f['face']];points=[]
            for du,dv in [(0,0),(f['width_mm'],0),(f['width_mm'],f['length_mm']),(0,f['length_mm'])]:
                loc=point.copy();loc[a]+=du;loc[b]+=dv;points.append((cx+loc[u_index]*u_sign*scale,cy-loc[v_index]*v_sign*scale))
            out.append(polygon(points,'outline' if axis[normal]<0 else 'hiddenline'))
    out.append(hdim(x,x+width,y+height+8,y+height,fmt(size[u_index])))
    out.append(vdim(y,y+height,x-8,x,fmt(size[v_index])))

def _valid_outline(part):
    outline=part.get('outline_mm')
    if outline is None:return True
    # Reuse the domain validator at call time; no module import cycle.
    from app.workbench.engine import _outline_error
    try:return _outline_error(part) is None
    except (KeyError,TypeError,IndexError):return False

def draw_part_sheets(part,project):
    part,project=data(part),data(project);size=part.get('size_mm',[])
    if len(size)!=3 or not all(number(x) and x>0 for x in size):return []
    material=project.get('materials',{}).get(part.get('material_id'),{}).get('name','')
    code='P-'+part.get('id','part');title=part.get('name') or part.get('id','零件')
    if not _valid_outline(part):
        out=sheet(title,code,project,material);out.append(text(20,46,'草稿无效',6));out.append(text(20,54,'斜切轮廓至少需要三个顶点，且不得自相交。未绘制加工几何。',4));return [{'id':code,'part_id':part.get('id'),'title':title,'sheet_type':'invalid','svg':finish(out)}]
    out=sheet(title+' · 零件总图',code,project,material)
    scale=scale_for(size[0]+size[2],size[1]+size[2],325,150)
    front_left=45+size[2]*scale+35;front_top=48
    front_cx=front_left+size[0]*scale/2;front_cy=front_top+size[1]*scale/2
    right_cx=45+size[2]*scale/2;top_cy=front_top+size[1]*scale+30+size[2]*scale/2
    _overview_view(out,part,(0,1),(1,1),2,front_cx,front_cy,scale,'正视 X/Y · +Z')
    _overview_view(out,part,(2,-1),(1,1),0,right_cx,front_cy,scale,'侧视 Z/Y · +X')
    _overview_view(out,part,(0,1),(2,-1),1,front_cx,top_cy,scale,'俯视 X/Z · +Y')
    _overview_notes(out,part)
    out.append(text(17,242,'第一角法：右视图在左，俯视图在下；三视图比例 '+scale_name(scale),3))
    out.append(text(17,249,'净料 X × Y × Z = '+' × '.join(fmt(x) for x in size)+'；孔槽详见各加工面图。',3))
    sheets=[{'id':code,'part_id':part.get('id'),'title':title+' · 零件总图','sheet_type':'part','scale':scale_name(scale),'svg':finish(out)}]
    features=short_features(part)
    unknown=[label for label,f in features if f.get('face') not in AXES]
    for face in AXES:
        rows=[(label,f) for label,f in features if f.get('face')==face]
        if not rows:continue
        for start in range(0,len(rows),12):
            page_rows=rows[start:start+12];a,b,n=AXES[face];width,height=size[a],size[b];sc=scale_for(width,height,242,170,2)
            page_code=f'{code}-{face}-{start//12+1}';out=sheet(title+' · '+FACE_NAMES[face]+'加工',page_code,project,material,scale_name(sc),'加工面图')
            x=30+(245-width*sc)/2;y=48+(172-height*sc)/2
            if face in ('top','bottom') and part.get('outline_mm'):out.append(polygon([(x+u*sc,y+(height-v)*sc) for u,v in part['outline_mm']]))
            else:out.append(rect(x,y,width*sc,height*sc))
            out.append(hdim(x,x+width*sc,y+height*sc+9,y+height*sc,fmt(width)))
            out.append(vdim(y,y+height*sc,x-9,x,fmt(height)))
            out.append(line(x,y+height*sc,x+16,y+height*sc,'dimension','marker-end="url(#arrow)"')+text(x+18,y+height*sc+1,'U',3))
            out.append(line(x,y+height*sc,x,y+height*sc-16,'dimension','marker-end="url(#arrow)"')+text(x-2,y+height*sc-18,'V',3))
            out.append(text(x-2,y+height*sc+4,'O',3))
            for label,f in rows:
                if not valid_feature(part,f):continue
                px,py=x+f['u_mm']*sc,y+(height-f['v_mm'])*sc
                if f['kind']=='hole':
                    r=f['diameter_mm']/2*sc;out.append(f'<circle cx="{fmt(px)}" cy="{fmt(py)}" r="{fmt(r)}" class="outline"/>');out.append(line(px-r-2,py,px+r+2,py,'centerline')+line(px,py-r-2,px,py+r+2,'centerline'))
                else:out.append(rect(px,py-f['length_mm']*sc,f['width_mm']*sc,f['length_mm']*sc))
                same=[lab for lab,other in rows if other.get('u_mm')==f['u_mm'] and other.get('v_mm')==f['v_mm']]
                if label!=same[0]:continue
                offset=5 if f['u_mm']<=width/2 else -5;endx=px+offset;endy=py-7
                out.append(line(px,py,endx,endy,'thin')+text(endx+(1 if offset>0 else -1),endy-1,'/'.join(same),2.7,'start' if offset>0 else 'end','class="dimtext"'))
            tx=288;out.append(text(tx,38,'加工定位表',3.5));out.append(text(tx,45,'U / V 从 O 沿箭头方向量取',2.7));out.append(line(tx,49,402,49));out.append(text(tx+1,55,'编号',2.8)+text(tx+17,55,'U',2.8)+text(tx+38,55,'V',2.8)+text(tx+58,55,'孔径 / 深度',2.8))
            for idx,(label,f) in enumerate(page_rows):
                yy=64+idx*12;out.append(line(tx,yy-5,402,yy-5));out.append(text(tx+1,yy,label,2.8)+text(tx+17,yy,fmt(f.get('u_mm')),2.8)+text(tx+38,yy,fmt(f.get('v_mm')),2.8));out.append(text(tx+58,yy,feature_label(part,f) if valid_feature(part,f) else '数据无效',2.6));out.append(text(tx+58,yy+4,'五金安装孔' if f.get('role')=='hardware_access' else '连接孔槽',2.3))
            out.append(text(17,242,'加工面：'+FACE_NAMES[face]+'；展开坐标 U='+('XYZ'[a])+'，V='+('XYZ'[b])+'；深度向板内。',3))
            out.append(text(17,249,'面法向 '+('+' if face in POSITIVE else '−')+'XYZ'[n]+'；孔 U/V 为圆心，槽 U/V 为最小角。可钻深度 '+fmt(size[n])+' mm。',3))
            sheets.append({'id':page_code,'part_id':part.get('id'),'title':title+' · '+FACE_NAMES[face]+'加工','sheet_type':'machining','face':face,'scale':scale_name(sc),'svg':finish(out)})
    if unknown:
        out=sheet(title+' · 特征记录',code+'-invalid',project,material);out.append(text(20,50,'加工面未定义：'+', '.join(unknown),4));sheets.append({'id':code+'-invalid','part_id':part.get('id'),'title':title+' · 无效特征','sheet_type':'invalid','svg':finish(out)})
    return sheets

# Cut the oriented board solid by a plane; do not substitute its AABB.
def _section_polygon(part,origin,u,v,w):
    from app.workbench.solid import part_faces
    points=[]
    for face in part_faces(part):
        vertices=[world(part,point) for point in face]
        for i,a in enumerate(vertices):
            b=vertices[(i+1)%len(vertices)];da,db=dot(sub(a,origin),w),dot(sub(b,origin),w)
            if abs(da)<1e-7:points.append(a)
            if da*db<0:points.append(add(a,mul(sub(b,a),da/(da-db))))
    uv=[]
    for point in points:
        pair=(dot(sub(point,origin),u),dot(sub(point,origin),v))
        if not any(abs(pair[0]-x)<1e-6 and abs(pair[1]-y)<1e-6 for x,y in uv):uv.append(pair)
    if len(uv)<3:return []
    cx=sum(p[0] for p in uv)/len(uv);cy=sum(p[1] for p in uv)/len(uv)
    return sorted(uv,key=lambda p:atan2(p[1]-cy,p[0]-cx))


def _clip(poly,xmin,xmax,ymin,ymax):
    for axis,limit,keep in [(0,xmin,1),(0,xmax,-1),(1,ymin,1),(1,ymax,-1)]:
        result=[]
        for i,a in enumerate(poly):
            b=poly[(i+1)%len(poly)];ina=(a[axis]-limit)*keep>=-1e-8;inb=(b[axis]-limit)*keep>=-1e-8
            if ina:result.append(a)
            if ina!=inb:
                t=(limit-a[axis])/(b[axis]-a[axis]);result.append(tuple(a[k]+t*(b[k]-a[k]) for k in (0,1)))
        poly=result
        if not poly:break
    return poly

def _rect_on_axis(point,axis,start,length,radius):
    axis=norm([axis[0],axis[1],0]);perp=(-axis[1],axis[0]);p=(point[0]+axis[0]*start,point[1]+axis[1]*start)
    return [(p[0]+perp[0]*radius,p[1]+perp[1]*radius),(p[0]+axis[0]*length+perp[0]*radius,p[1]+axis[1]*length+perp[1]*radius),(p[0]+axis[0]*length-perp[0]*radius,p[1]+axis[1]*length-perp[1]*radius),(p[0]-perp[0]*radius,p[1]-perp[1]*radius)]

def _project(point,origin,u,v):return (dot(sub(point,origin),u),dot(sub(point,origin),v))

def _bore_shape(part,f,origin,u,v,w):
    if f.get('kind')!='hole' or not valid_feature(part,f):return None
    entry,axis,length=feature_segment(part,f);distance=dot(sub(entry,origin),w);normal=dot(axis,w);r=f['diameter_mm']/2
    if abs(normal)<1e-6:
        if abs(distance)>=r:return None
        half=sqrt(max(0,r*r-distance*distance));return ('polygon',_rect_on_axis(_project(entry,origin,u,v),(dot(axis,u),dot(axis,v)),0,length,half))
    center=add(entry,mul(axis,-distance/normal))
    if abs(abs(normal)-1)<1e-6:
        if 0<=-distance/normal<=length:return ('circle',(_project(center,origin,u,v),r))
        return None
    major=norm(sub(axis,mul(w,normal)));minor=norm(cross(w,major))
    points=[_project(add(center,add(mul(major,r/abs(normal)*cos(2*pi*i/48)),mul(minor,r*sin(2*pi*i/48)))),origin,u,v) for i in range(48)]
    def depth(point):return dot(sub(origin,entry),axis)+point[0]*dot(u,axis)+point[1]*dot(v,axis)
    for limit,sign in [(0,1),(length,-1)]:
        clipped=[]
        for i,a in enumerate(points):
            b=points[(i+1)%len(points)];da,db=(depth(a)-limit)*sign,(depth(b)-limit)*sign
            if da>=-1e-7:clipped.append(a)
            if (da>=0)!=(db>=0):
                t=da/(da-db);clipped.append((a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])))
        points=clipped
        if not points:return None
    return ('polygon',points)


def convex_hull(points):
    points=sorted(set((round(x,7),round(y,7)) for x,y in points))
    if len(points)<3:return points
    def turn(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower=[];upper=[]
    for point in points:
        while len(lower)>1 and turn(lower[-2],lower[-1],point)<=0:lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper)>1 and turn(upper[-2],upper[-1],point)<=0:upper.pop()
        upper.append(point)
    return lower[:-1]+upper[:-1]


def _outline2d_shape(shape,xy,scale,cls='thin',attrs=''):
    kind,value=shape
    if kind=='polygon':return polygon([xy(p) for p in value],cls,attrs)
    center,r=value;cx,cy=xy(center);return f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(r*scale)}" class="{cls}" {attrs}/>'

def draw_joint_sheets(project,resolved_hardware,*,compact=False):
    project=data(project);parts={p['id']:p for p in project.get('parts',[])};sheets=[]
    for joint in project.get('joints',[]):
        items=[h for h in resolved_hardware if h.get('joint_id')==joint['id']];bolts=[h for h in items if h.get('kind',h.get('geometry',{}).get('kind'))=='bolt']
        if not bolts:continue
        involved=[parts[pid] for pid in joint.get('part_ids',[]) if pid in parts]
        if not involved or any(p.get('outline_mm') or not all(number(x) and x>0 for x in p.get('size_mm',[])) for p in involved):continue
        bolt=bolts[0];origin=bolt['position_mm'];u=norm(bolt['direction']);length=bolt['geometry']['length_mm']
        barrels=[h for h in items if h.get('kind',h.get('geometry',{}).get('kind'))=='barrel_nut' and h.get('bore_direction')]
        if barrels:
            # Match a barrel to the chosen bolt by its explicit bore axis and geometric centre.
            def barrel_distance(h):
                center=add(h['position_mm'],mul(h['direction'],h['geometry']['length_mm']/2));delta=sub(center,origin)
                return sqrt(dot(cross(delta,u),cross(delta,u))) if abs(dot(norm(h['bore_direction']),u))>.999 else 1e9
            nearest=min(barrels,key=barrel_distance)
            if barrel_distance(nearest)>.5:continue
            v=norm(sub(nearest['direction'],mul(u,dot(nearest['direction'],u))))
        else:
            candidate=[0,1,0] if abs(u[1])<.9 else [0,0,1];v=norm(sub(candidate,mul(u,dot(candidate,u))))
        if dot(v,v)<.5:continue
        w=norm(cross(u,v));xmin,xmax,ymin,ymax=-14,length+12,-32,32
        scale=scale_for(xmax-xmin,ymax-ymin,240,64 if compact else 150,1 if compact else 2);ox,oy=28-xmin*scale,56 if compact else 138
        xy=lambda point:(ox+point[0]*scale,oy-point[1]*scale)
        code='J-'+joint['id'];title=joint.get('name') or joint['id'];material=' / '.join(dict.fromkeys(project.get('materials',{}).get(p.get('material_id'),{}).get('name','') for p in involved))
        if compact:
            out=[text(17,10,title,4,attrs='font-weight="700"'),text(17,17,code+' · 比例 '+scale_name(scale),3)]
        else:
            out=sheet(title+' · 连接剖视大样',code,project,material,scale_name(scale),'连接大样')
            out.append(text(17,36,'局部剖面 · 通过首枚螺栓轴线',3.8));out.append(text(17,43,'同组其他孔位见零件图；图示为实装位置，螺纹按简化轮廓表示。',2.8))
        hole_specs=[]
        for index,part in enumerate(involved):
            full=_section_polygon(part,origin,u,v,w);poly=_clip(full,xmin,xmax,ymin,ymax)
            if len(poly)<3:continue
            holes=[]
            for f in part.get('features',[]):
                shape=_bore_shape(part,f,origin,u,v,w)
                if shape:holes.append((shape,f['depth_mm']<part['size_mm'][AXES[f['face']][2]]-1e-6));hole_specs.append(feature_label(part,f))
            mask_id='cut-'+joint['id']+'-'+str(index);mask=[f'<mask id="{mask_id}" maskUnits="userSpaceOnUse"><rect x="10" y="{0 if compact else 30}" width="275" height="220" fill="white"/>']
            mask += [_outline2d_shape(shape,xy,scale,'','fill="black"') for shape,_ in holes]
            mask.append('</mask>');out.append('<defs>'+''.join(mask)+'</defs>')
            clip_id='partclip-'+joint['id']+'-'+str(index);out.append('<defs><clipPath id="'+clip_id+'">'+polygon([xy(p) for p in poly],'')+'</clipPath></defs>')
            hatch='hatch' if index%2==0 else 'hatch2'
            out.append(polygon([xy(p) for p in poly],'sectionedge',f'fill="url(#{hatch})" mask="url(#{mask_id})"'))
            boundaries=[]
            for shape,blind in holes:
                if shape[0]=='polygon':
                    pts=[xy(p) for p in shape[1]]
                    if len(pts)==4:
                        boundaries.append(line(*pts[0],*pts[1])+line(*pts[2],*pts[3]))
                        if blind:boundaries.append(line(*pts[1],*pts[2]))
                    else:boundaries.append(polygon(pts,'thin'))
                else:boundaries.append(_outline2d_shape(shape,xy,scale))
            out.append(f'<g clip-path="url(#{clip_id})">'+''.join(boundaries)+'</g>')
            # Zigzag marks on section limits distinguish cropped board from its physical edge.
            for boundary in (ymin,ymax):
                crossings=[p[0] for p in poly if abs(p[1]-boundary)<1e-6]
                if len(crossings)>1 and max(crossings)-min(crossings)>8:
                    mid=(min(crossings)+max(crossings))/2;zig=[xy((mid-4,boundary)),xy((mid-1.5,boundary)),xy((mid-.5,boundary+1.5)),xy((mid+.5,boundary-1.5)),xy((mid+1.5,boundary)),xy((mid+4,boundary))]
                    out.append('<polyline points="'+' '.join(f'{fmt(x)},{fmt(y)}' for x,y in zig)+'" fill="none" stroke="white" stroke-width="1.3"/>');out.append('<polyline points="'+' '.join(f'{fmt(x)},{fmt(y)}' for x,y in zig)+'" class="thin"/>')
            centroid=(sum(x for x,y in poly)/len(poly),sum(y for x,y in poly)/len(poly));px,py=xy(centroid);lx=20+index*120;ly=24 if compact else 59
            out.append(line(px,py,lx+20,ly+3)+text(lx,ly,'P'+str(next(i for i,p in enumerate(project.get('parts',[]),1) if p['id']==part['id']))+' '+part.get('name',part['id'])+' · 净厚 '+fmt(min(part['size_mm'])),3))
        drawn=[]
        # Nuts and washers first; the unsectioned bolt remains visible across their bores.
        for hardware in sorted(items,key=lambda h:h.get('kind',h.get('geometry',{}).get('kind'))=='bolt'):
            g=hardware['geometry'];kind=hardware.get('kind',g.get('kind'));pos=hardware['position_mm'];axis=norm(hardware['direction']);offset=dot(sub(pos,origin),w);radius=g['diameter_mm']/2
            if abs(offset)>radius+1e-5:continue
            axis2=(dot(axis,u),dot(axis,v));normal=dot(axis,w);point=_project(pos,origin,u,v)
            if abs(normal)>1e-5:continue
            if kind=='bolt':
                out.append(polygon([xy(p) for p in _rect_on_axis(point,axis2,0,g['length_mm'],radius)],'fastener'))
                out.append(polygon([xy(p) for p in _rect_on_axis(point,axis2,-g.get('head_height_mm',0),g.get('head_height_mm',0),g.get('head_diameter_mm',g['diameter_mm'])/2)],'fastener'))
                core=radius*.8
                for sign in (-1,1):
                    a=xy((point[0]+axis2[0]*2-axis2[1]*core*sign,point[1]+axis2[1]*2+axis2[0]*core*sign));b=xy((point[0]+axis2[0]*g['length_mm']-axis2[1]*core*sign,point[1]+axis2[1]*g['length_mm']+axis2[0]*core*sign));out.append(line(*a,*b,'thin'))
            else:
                r=(g.get('across_flats_mm') or g['diameter_mm'])/2
                out.append(polygon([xy(p) for p in _rect_on_axis(point,axis2,0,g['length_mm'],r)],'fastener'))
                if kind in ('washer','hex_nut'):
                    bore=(g.get('bore_diameter_mm') or 6)/2;out.append(polygon([xy(p) for p in _rect_on_axis(point,axis2,0,g['length_mm'],bore)],'','fill="white"'))
                elif kind=='barrel_nut':
                    bore_axis=norm(hardware.get('bore_direction',u));bore2=(dot(bore_axis,u),dot(bore_axis,v));center=(point[0]+axis2[0]*g['length_mm']/2,point[1]+axis2[1]*g['length_mm']/2);bore=(g.get('bore_diameter_mm') or 6)/2
                    out.append(polygon([xy(p) for p in _rect_on_axis(center,bore2,-radius,2*radius,bore)],'','fill="white"'))
            drawn.append(hardware)
        out.append(line(*xy((xmin,0)),*xy((xmax,0)),'centerline'))
        if compact:
            from app.workbench.assembly_sheet import _hardware_catalog, _hardware_key, _short_spec, _wrap
            out.append(hdim(ox,ox+length*scale,97,oy+bolt['geometry']['diameter_mm']/2*scale,'头下长度 '+fmt(length)))
            catalog=_hardware_catalog(project.get('joints',[]));unique=[item for item in joint.get('hardware',[]) if item.get('name')]
            tx=282;yy=31
            for item in unique:
                entry=catalog[_hardware_key(item)];label=entry['code']+' '+item['name']+' × '+str(item['quantity'])
                name_rows=_wrap(label,37);spec_rows=_wrap(_short_spec(item),37)
                for row in name_rows:out.append(text(tx,yy,row,3));yy+=4
                for row in spec_rows:out.append(text(tx,yy,row,3));yy+=4
                inst=next((h for h in drawn if h.get('name')==item['name'] and h.get('spec')==item.get('spec')),None)
                if inst:
                    px,py=xy(_project(inst['position_mm'],origin,u,v));out.append(line(px,py,274,yy-4)+text(275,yy-5,entry['code'],3))
                yy+=8
            out.append(text(17,107,'局部剖面通过首枚螺栓；其余孔位见零件加工图。五金编号对应首页采购清单。',3))
            sheets.append({'id':code,'joint_id':joint['id'],'title':title,'sheet_type':'joint','scale':scale_name(scale),'representative_hardware_id':bolt.get('id'),'fragment':''.join(out),'height_mm':max(112,yy+4)})
            continue
        out.append(hdim(ox,ox+length*scale,218,oy+bolt['geometry']['diameter_mm']/2*scale,'L='+fmt(length)))
        out.append(text(17,232,'L 从螺栓头下承压面量取；板件斜线为剖切材料，五金纵剖不画剖面线。',2.8))
        out.append(text(17,240,'孔加工：'+'；'.join(dict.fromkeys(hole_specs))[:105],2.8))
        out.append(text(17,248,'局部范围：垂直螺栓轴方向两侧各 32 mm；板件截断用折断线表示。',2.7))
        tx=290;out.append(text(tx,37,'本连接五金',3.5))
        unique=[item for item in joint.get('hardware',[]) if item.get('name')]
        for i,item in enumerate(unique,1):
            yy=50+(i-1)*34;out.append(text(tx,yy,f'{i:02}  '+item['name']+' × '+str(item['quantity']),3));spec=item.get('spec','')
            for k in range(0,len(spec),26):out.append(text(tx,yy+6+(k//26)*4,spec[k:k+26],2.6))
            inst=next((h for h in drawn if h.get('name')==item['name'] and h.get('spec')==item.get('spec')),None)
            if inst:
                target=_project(inst['position_mm'],origin,u,v);px,py=xy(target);out.append(line(px,py,280,yy-1,'thin')+line(280,yy-1,286,yy-1,'thin')+text(282,yy-2,str(i),2.6))
        from app.workbench.assembly_sheet import _wrap
        out.append(text(tx,190,'装配顺序',3.5))
        note=joint.get('assembly_note') or '对齐孔位，安装螺栓与配套五金。'
        for index,row in enumerate(_wrap(note,34)):
            out.append(text(tx,198+index*4,row,3))
        sheets.append({'id':code,'joint_id':joint['id'],'title':title+' · 剖视大样','sheet_type':'joint','scale':scale_name(scale),'representative_hardware_id':bolt.get('id'),'svg':finish(out)})
    return sheets
