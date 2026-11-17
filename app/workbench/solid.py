"""Convex planar cuts in centred part-local coordinates; keep n dot p <= offset."""
from itertools import combinations
from math import atan2, sqrt, isfinite

EPS = 1e-6

def dot(a,b): return sum(x*y for x,y in zip(a,b))
def cross(a,b): return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def unit(a):
    length=sqrt(dot(a,a));return [x/length for x in a]

def solid_planes(part):
    planes=[]
    for axis,size in enumerate(part["size_mm"]):
        for sign in (-1,1):
            n=[0.,0.,0.];n[axis]=sign;planes.append((n,size/2))
    planes.extend((cut["normal_local"],cut["offset_mm"]) for cut in part.get("plane_cuts",[]))
    return planes

def solid_vertices(part):
    planes=solid_planes(part);vertices=[]
    for (a,da),(b,db),(c,dc) in combinations(planes,3):
        bc,ca,ab=cross(b,c),cross(c,a),cross(a,b);det=dot(a,bc)
        if abs(det)<EPS:continue
        v=[(da*bc[i]+db*ca[i]+dc*ab[i])/det for i in range(3)]
        if any(dot(n,v)>d+EPS for n,d in planes):continue
        if not any(sum((x-y)**2 for x,y in zip(v,p))<EPS**2 for p in vertices):vertices.append(v)
    return vertices

def part_faces(part):
    vertices=solid_vertices(part);faces=[]
    for n,d in solid_planes(part):
        face=[p for p in vertices if abs(dot(n,p)-d)<EPS]
        if len(face)<3:continue
        center=[sum(p[i] for p in face)/len(face) for i in range(3)]
        base=[1,0,0] if abs(n[0])<.9 else [0,1,0]
        u=unit(cross(base,n));v=cross(n,u)
        face.sort(key=lambda p:atan2(dot([p[i]-center[i] for i in range(3)],v),dot([p[i]-center[i] for i in range(3)],u)))
        # Coplanar duplicate cuts must not emit duplicate faces.
        ids={tuple(round(x,6) for x in p) for p in face}
        if not any(ids=={tuple(round(x,6) for x in p) for p in f} for f in faces):faces.append(face)
    return faces

def cuts_error(part):
    cuts=part.get("plane_cuts",[])
    if not cuts:return None
    if part.get("outline_mm"):return "平面斜切暂不与顶面轮廓组合。"
    if not isinstance(cuts,list) or len(cuts)>8:return "平面斜切最多八个。"
    for cut in cuts:
        n,d=cut.get("normal_local"),cut.get("offset_mm")
        if not isinstance(n,(list,tuple)) or len(n)!=3 or not all(isinstance(x,(int,float)) and isfinite(x) for x in n) or abs(dot(n,n)-1)>EPS or not isinstance(d,(int,float)) or not isfinite(d):return "斜切平面须有有限偏移及单位法向。"
    vertices=solid_vertices(part)
    if len(vertices)<4:return "斜切后零件无有效体积。"
    volume=sum(dot(face[0],cross(face[i],face[i+1]))/6 for face in part_faces(part) for i in range(1,len(face)-1))
    if abs(volume)<EPS:return "斜切后零件无有效体积。"
    return None

def drill_error(part,entry,direction,depth,radius):
    planes=solid_planes(part)
    if any(dot(n,entry)>d+EPS for n,d in planes):return "孔入口不在加工后实体内。"
    entry_planes=[(n,d) for n,d in planes if abs(dot(n,entry)-d)<EPS]
    if not entry_planes:return "孔入口须位于加工后实体表面。"
    if any(dot(n,direction)>=-EPS for n,d in entry_planes):return "孔轴没有从入口朝实体内部钻入。"
    end=[entry[i]+depth*direction[i] for i in range(3)]
    if any(dot(n,end)>d+EPS for n,d in planes):return "孔深超过加工后实体边界。"
    for n,d in planes:
        nd=dot(n,direction)
        # Entry and through-exit surfaces intentionally intersect the bore.
        if abs(dot(n,entry)-d)<EPS and nd<-EPS:continue
        if abs(dot(n,end)-d)<EPS and nd>EPS:continue
        radial=radius*sqrt(max(0,1-nd*nd))
        if max(dot(n,entry),dot(n,end))+radial>d+EPS:return "孔径及轴向使孔壁穿出非入口/出口表面。"
    return None
