"""Generate a machining proposal from the current CAFE design; never update live data."""
from copy import deepcopy
import argparse, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.workbench.engine import FACE_AXES, _rotation, _rotate, build_checks, build_package
from app.workbench.models import Project

def world(p,local):
    return [a+b for a,b in zip(_rotate(_rotation(p),local),p['position_mm'])]

def hole(p,fid,face,point,diameter,depth,role='connection'):
    m=_rotation(p); delta=[point[i]-p['position_mm'][i] for i in range(3)]
    local=[sum(m[i][j]*delta[i] for i in range(3)) for j in range(3)]
    a,b,n=FACE_AXES[face]
    expected=p['size_mm'][n]/2*(1 if face in ('top','right','front') else -1)
    assert abs(local[n]-expected)<1e-6,(fid,local[n],expected)
    p['features'].append({'id':fid,'kind':'hole','role':role,'face':face,'u_mm':round(local[a]+p['size_mm'][a]/2,4),'v_mm':round(local[b]+p['size_mm'][b]/2,4),'diameter_mm':diameter,'depth_mm':depth})
    return fid

def hw(name,spec,n): return {'name':name,'spec':spec,'quantity':n}
WASHER='M6，内径6.4 / 外径18 / 厚1.6 mm'
BARREL='M6 × 1，直径10 / 长14 mm，螺纹孔居中'
def build(source):
    parts=deepcopy(source['parts']); p={x['id']:x for x in parts}
    assert set(p)=={'seat','side_left','side_right','back','foot_left','foot_right'}
    for x in parts: x['features']=[]; x['material_id']='ash_x' if x['id']=='seat' else 'ash_z'
    p['seat']['size_mm'][0]=400; p['seat']['kind']='seat_board'
    joints=[]; audit=[]
    def join(jid,ids,fs,items,note):
        names={'foot_left_joint':'左底脚—侧立板','foot_right_joint':'右底脚—侧立板','back_left':'靠背—左侧立板','back_right':'靠背—右侧立板','seat_left':'座板—左侧立板','seat_right':'座板—右侧立板'}
        joints.append({'id':jid,'name':names[jid],'kind':'screw','part_ids':ids,'feature_ids':fs,'hardware':items,'assembly_note':note,'confirmed':False})
    for side,sign,cn in [('left',-1,'左'),('right',1,'右')]:
        foot,leg=p['foot_'+side],p['side_'+side];face='left' if sign<0 else 'right';fs=[]
        for i,z in enumerate((-10,70),1):
            fs.append(hole(foot,f'foot_{side}_bolt_{i}',face,[sign*133,40,z],6.5,24))
            fs.append(hole(leg,f'side_{side}_foot_{i}',face,[sign*109,40,z],6.5,24))
        join('foot_'+side+'_joint',[foot['id'],leg['id']],fs,[hw('圆头内六角螺栓','M6 × 60 mm',2),hw('平垫圈',WASHER,4),hw('尼龙锁紧螺母','M6 × 1，厚6 mm',2)],f'{cn}底脚与侧立板下边齐平。底脚两孔距底边40mm，沿300mm长边从最小端量140、220mm。Ø6.5贯穿两块24mm板；每孔穿1枚M6×60螺栓，头部与锁紧螺母下各放1片18mm垫圈。先轻拧，整椅装齐后交替收紧。')
    back=p['back']; m=_rotation(back)
    for side,sign,cn in [('left',-1,'左'),('right',1,'右')]:
        leg=p['side_'+side];face='left' if sign<0 else 'right';fs=[]
        for i,y in enumerate((140,240),1):
            lz=(y-back['position_mm'][1])/m[1][2]; z=world(back,[0,0,lz])[2]
            margin=min(z+65,105-z);assert margin>=20,(y,z,margin)
            audit.append({'joint':'back_'+side,'height_mm':y,'world_z_mm':round(z,4),'side_edge_distance_mm':round(margin,4)})
            fs.append(hole(leg,f'side_{side}_back_{i}',face,[sign*109,y,z],6.5,24))
            fs.append(hole(back,f'back_{side}_bolt_{i}',face,[sign*85,y,z],6.5,55))
            fs.append(hole(back,f'back_{side}_nut_{i}','top',world(back,[sign*45,12,lz]),10,19,'hardware_access'))
        join('back_'+side,[back['id'],leg['id']],fs,[hw('圆头内六角螺栓','M6 × 70 mm，ISO7380-1，头径10.5 / 头高3.3 mm',2),hw('横孔圆柱螺母',BARREL,2),hw('平垫圈',WASHER,2)],f'靠背{cn}侧两条螺栓轴线离地140、240mm。侧立板钻Ø6.5通孔，靠背侧边钻Ø6.5深55mm；靠背背面按图钻Ø10深19mm安装孔。放入14mm长圆柱螺母，外端沉入板面5mm，转槽对准主孔。每孔配M6×70螺栓和18mm垫圈，先手旋入螺纹，再交替收紧。')
    for side,sign,cn in [('left',-1,'左'),('right',1,'右')]:
        seat,leg=p['seat'],p['side_'+side];face='left' if sign<0 else 'right';fs=[]
        for i,z in enumerate((-15,65),1):
            fs.append(hole(seat,f'seat_{side}_bolt_{i}','top',[sign*97,450,z],6.5,24))
            fs.append(hole(seat,f'seat_{side}_recess_{i}','top',[sign*97,450,z],20,5.2,'hardware_access'))
            fs.append(hole(leg,f'side_{side}_seat_{i}','back',[sign*97,426,z],6.5,55))
            fs.append(hole(leg,f'side_{side}_seat_nut_{i}',face,[sign*109,386,z],10,19,'hardware_access'))
        join('seat_'+side,[seat['id'],leg['id']],fs,[hw('圆头内六角螺栓','M6 × 70 mm，ISO7380-1，头径10.5 / 头高3.3 mm',2),hw('横孔圆柱螺母',BARREL,2),hw('平垫圈',WASHER,2)],f'座板{cn}侧孔从局部最小X/Z边定位：U={103 if sign<0 else 297}mm，V=50、130mm。先钻Ø20深5.2mm沉孔，再钻Ø6.5通孔。侧立板从顶端钻Ø6.5深55mm，外侧顶下40mm钻Ø10深19mm；圆柱螺母外端沉入5mm并对准上孔。装入18mm垫圈与M6×70螺栓，头部收在沉孔内。座面边角打磨后，在平面上校正底脚并交替紧固。')
    materials={key:{'name':'白蜡木 · 净料24 mm','kind':'solid_wood','grain_axis':axis,'properties':{}} for key,axis in [('ash_x','x'),('ash_z','z')]}
    evidence=[deepcopy(e) for e in source['evidence'] if e['status']=='observed']
    for e in evidence:e['statement']=e['statement'].replace('；这些不是从像素测得的尺寸。','。')
    evidence += [{'statement':text,'status':status,'source_ids':[]} for text,status in [
      ('按已输入的400mm基准将座宽从350改为400mm；座高450、座深215及六板构造保持。','adopted'),
      ('六板统一白蜡木净厚24mm；座板木纹沿宽度，其余构件木纹沿长边。','adopted'),
      ('采用12枚M6螺栓连接：座板和靠背配8枚横孔圆柱螺母，底脚配4枚锁紧螺母。','adopted'),
      ('横孔螺母规格：Hafele 264.82.014，居中M6螺纹、直径10、长14mm。https://files.hafele.co.uk/catalogfiles/www/14CFC412.pdf','observed'),
      ('圆头螺栓规格：ISO7380-1 M6头径10.5、头高3.3、内六角4mm。https://www.aspenfasteners.com/content/pdf/Metric_ISO_7380_spec.pdf','observed'),
      ('锁紧螺母规格：DIN985 M6 A2-70，厚6mm、扳手10mm。https://www.accu.co.uk/hexagon-nylon-locking-nuts/7948-HNN-M6-A2','observed'),
      ('平垫圈规格：DIN9021 M6内径6.4、外径18、厚1.6mm。https://docs.rs-online.com/3cc2/A700000009608874.pdf','observed')]]
    patch={'name':'CAFE CHAIR · 白蜡木加工方案','scope':'supported','scope_reason':'六块24mm白蜡木板，直切下料，钻孔安装M6可拆装连接。','scale':{'kind':'target','confirmed':False,'note':'座宽400、座高450、座深215、底脚长300、总高约780 mm。','length_mm':400},'parts':parts,'materials':materials,'joints':joints,'evidence':evidence,'assumptions':['24mm为刨光后的净厚；先按下料表裁切，再按加工面坐标钻孔。','钻孔工具：Ø6.5钻头、Ø10木工钻、Ø20平底钻、直角钻孔导向夹具及深度挡圈。','横孔螺母安装孔深19mm；14mm长螺母外端沉入5mm，使螺纹轴处在24mm板厚中线。','装配次序：底脚与侧立板 → 靠背 → 座板 → 平台校正后交替紧固。']}
    hardware_proposal, _ = add_hardware_geometry({**source, **patch})
    patch['joints'] = hardware_proposal['patch']['joints']
    candidate=Project.model_validate({**source,**patch}).model_dump(mode='json')
    checks=build_checks(candidate)
    physical=[c for c in checks if c['severity']=='blocker' and c['code'] not in ('joint_unconfirmed','scale_unconfirmed')]
    assert not physical,json.dumps(physical,ensure_ascii=False)
    package=build_package(candidate)
    report={'source_revision':source['revision'],'part_count':len(parts),'feature_count':sum(len(x['features']) for x in parts),'connection_count':len(joints),'back_edge_distances':audit,'hardware':package['hardware'],'checks':checks,'coverage':package['coverage']}
    return {'purpose':'manufacturing','summary':'已补齐六处连接、36处加工特征（含沉孔、安装孔）和五金清单。统一24mm白蜡木，座宽400mm；采用M6可拆装螺栓，座面螺栓头收进沉孔。','patch':patch},report

def add_hardware_geometry(source):
    """Add placements to this sample's existing joints, preserving its design."""
    from app.workbench.hardware import resolve_hardware, hardware_checks
    joints = deepcopy(source['joints'])
    part_map = {part['id']: part for part in source['parts']}
    expected = {'foot_left_joint', 'foot_right_joint', 'back_left', 'back_right', 'seat_left', 'seat_right'}
    if {joint['id'] for joint in joints} != expected:
        raise ValueError('此样例补充器需要现有 CAFE CHAIR 六处连接。')
    def instance(joint, kind, index, part_id, feature_id, offset, **extra):
        return {'id': f"{joint['id']}_{kind}_{index}", 'part_id': part_id,
                'feature_id': feature_id, 'offset_mm': offset, **extra}
    washer_geometry = {'kind': 'washer', 'diameter_mm': 18, 'bore_diameter_mm': 6.4, 'length_mm': 1.6}
    barrel_geometry = {'kind': 'barrel_nut', 'diameter_mm': 10, 'length_mm': 14, 'bore_diameter_mm': 6}
    locknut_geometry = {'kind': 'hex_nut', 'diameter_mm': 20 / (3 ** .5), 'length_mm': 6,
                        'bore_diameter_mm': 6, 'across_flats_mm': 10}
    for joint in joints:
        side = 'left' if 'left' in joint['id'] else 'right'
        foot = joint['id'].startswith('foot_')
        seat = joint['id'].startswith('seat_')
        bolt_geometry = {'kind': 'bolt', 'diameter_mm': 6, 'length_mm': 60 if foot else 70,
                         'head_diameter_mm': 10.5, 'head_height_mm': 3.3}
        bolts, washers, nuts = [], [], []
        for index in (1, 2):
            if foot:
                pid, fid = 'foot_' + side, f'foot_{side}_bolt_{index}'
                thickness = part_map[pid]['size_mm'][0] + part_map['side_' + side]['size_mm'][0]
                bolts.append(instance(joint, 'bolt', index, pid, fid, -1.6))
                washers.append(instance(joint, 'outer_washer', index, pid, fid, -1.6))
                washers.append(instance(joint, 'inner_washer', index, pid, fid, thickness))
                nuts.append(instance(joint, 'locknut', index, pid, fid, thickness + 1.6))
            elif seat:
                pid, fid = 'seat', f'seat_{side}_bolt_{index}'
                recess = next(f for f in part_map[pid]['features'] if f['id'] == f'seat_{side}_recess_{index}')
                offset = recess['depth_mm'] - 1.6
                bolts.append(instance(joint, 'bolt', index, pid, fid, offset))
                washers.append(instance(joint, 'washer', index, pid, fid, offset))
                nuts.append(instance(joint, 'barrel', index, 'side_' + side, f'side_{side}_seat_nut_{index}', 5,
                                     bore_part_id='side_' + side, bore_feature_id=f'side_{side}_seat_{index}'))
            else:
                pid, fid = 'side_' + side, f'side_{side}_back_{index}'
                bolts.append(instance(joint, 'bolt', index, pid, fid, -1.6))
                washers.append(instance(joint, 'washer', index, pid, fid, -1.6))
                nuts.append(instance(joint, 'barrel', index, 'back', f'back_{side}_nut_{index}', 5,
                                     bore_part_id='back', bore_feature_id=f'back_{side}_bolt_{index}'))
        # Rows are matched to the sample's explicit existing procurement names.
        additions = {'圆头内六角螺栓': (bolt_geometry, bolts), '平垫圈': (washer_geometry, washers),
                     '尼龙锁紧螺母': (locknut_geometry, nuts), '横孔圆柱螺母': (barrel_geometry, nuts)}
        for item in joint['hardware']:
            if item['name'] not in additions:
                raise ValueError('样例出现新的五金类型：' + item['name'])
            geometry, instances = additions[item['name']]
            if item['quantity'] != len(instances):
                raise ValueError('五金数量已变更，请先更新样例布置规则：' + item['name'])
            item.update(geometry=deepcopy(geometry), instances=instances)
        joint['confirmed'] = False
    candidate = Project.model_validate({**source, 'joints': joints}).model_dump(mode='json')
    checks = hardware_checks(candidate)
    if any(c['severity'] == 'blocker' for c in checks):
        raise ValueError(json.dumps(checks, ensure_ascii=False))
    solids = resolve_hardware(candidate)
    report = {'source_revision': source['revision'], 'part_count': len(source['parts']),
              'connection_count': len(joints), 'hardware_instances': len(solids), 'checks': checks}
    return {'purpose': 'manufacturing', 'summary': '已为当前连接补齐40件五金实体：12枚螺栓、16片垫圈、8枚横孔螺母和4枚锁紧螺母；实体锚定现有孔位。',
            'patch': {'joints': joints}}, report

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project-id',default='c0643d3f-3deb-4221-97f9-4619215c460c');ap.add_argument('--output',type=Path,default=Path('examples/cafe-chair-manufacturing-proposal.json'));ap.add_argument('--hardware-only',action='store_true');a=ap.parse_args()
    source=json.loads((Path('.data/workbench')/a.project_id/'project.json').read_text(encoding='utf-8'))
    proposal,report=(add_hardware_geometry(source) if a.hardware_only else build(source));a.output.write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    Path('.data/cafe-chair-reference/' + ('hardware-audit.json' if a.hardware_only else 'manufacturing-audit.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report if a.hardware_only else {k:report[k] for k in ['source_revision','part_count','feature_count','connection_count','hardware']},ensure_ascii=True))
    print('Geometry blockers: 0; live project unchanged; confirmation flags remain false.')
if __name__=='__main__':main()
