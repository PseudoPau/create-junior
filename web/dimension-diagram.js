// Explanatory dimension projection, not a comfort simulation.
const svg=(tag,attrs={},...children)=>{
  const element=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,value] of Object.entries(attrs))element.setAttribute(key,String(value));
  for(const child of children.flat())element.append(child instanceof Node?child:String(child));
  return element;
};
export const dimensionDescriptions={seat_height_mm:'地面到座板上表面',seat_depth_mm:'座板后端到前缘的长度',seat_width_mm:'座板左侧到右侧的宽度',back_angle_deg:'靠背相对竖直方向的后倾角'};
export function dimensionDiagram({key,current,value,seatWidth=450,seatDepth=400,seatHeight=450,backAngle=10,body={}}){
  const angle=key==='back_angle_deg',unit=angle?'°':' mm';
  const root=svg('svg',{viewBox:'0 0 420 250',class:'module-comparison-svg',role:'img','aria-label':dimensionDescriptions[key]+'，当前 '+current+unit+'，调整为 '+value+unit});
  const accent='#d85e35',muted='#9da69c',ink='#657265';
  const line=(d,color=ink,width=2,extra={})=>svg('path',{d,fill:'none',stroke:color,'stroke-width':width,'stroke-linecap':'round','stroke-linejoin':'round',...extra});
  const text=(x,y,content,extra={})=>svg('text',{x,y,fill:ink,'font-size':11,...extra},content);
  const ghost={stroke:muted,'stroke-width':2,'stroke-dasharray':'5 4',fill:'none'};
  const measure=(x1,y1,x2,y2)=>{
    const horizontal=y1===y2;
    root.append(line(`M${x1} ${y1}L${x2} ${y2}`,accent,1.5),line(horizontal?`M${x1} ${y1-4}v8M${x2} ${y2-4}v8`:`M${x1-4} ${y1}h8M${x2-4} ${y2}h8`,accent,1.5));
  };
  if(key==='seat_width_mm'){
    const hip=Number(body.hip_breadth_mm)||360;
    const scale=Math.min(.3,210/Math.max(current,hip)),cx=210,y=154,w=value*scale,old=current*scale,h=hip*scale;
    root.append(text(28,25,'正面'),line('M55 223H365','#e1e5dc',1),svg('rect',{x:cx-old/2,y:58,width:old,height:93,rx:5,fill:'#edf0e8',stroke:'#cbd1c6'}));
    root.append(line(`M${cx-old*.32} 165V220M${cx+old*.32} 165V220`,'#aab4a5',6));
    root.append(svg('rect',{x:cx-w/2,y:y+2,width:w,height:10,rx:2,fill:'#f5dfd0',stroke:accent,'stroke-width':2}),svg('rect',{x:cx-old/2,y:y-2,width:old,height:16,...ghost}));
    root.append(svg('ellipse',{cx,cy:132,rx:h/2,ry:17,fill:'#d8dfd3'}),line(`M${cx-h*.3} 122V98Q${cx} 82 ${cx+h*.3} 98V122`,'#c0caba',12),svg('circle',{cx,cy:69,r:15,fill:'#c0caba'}));
    measure(cx-w/2,191,cx+w/2,191);
    root.append(text(cx,207,'座板宽度',{'text-anchor':'middle',fill:accent}),text(cx,241,'身体轮廓为比例示意',{'text-anchor':'middle','font-size':10,fill:muted}));
    if(w>340)root.setAttribute('viewBox',`${Math.min(0,cx-w/2-28)} 0 ${w+56} 250`);
    return root;
  }
  const sitting=Number(body.sitting_height_mm)||900;
  root.setAttribute('viewBox','70 0 280 250');
  const effectiveHeight=key==='seat_height_mm'?value:seatHeight;
  // The scale stays fixed while editing so the old size does not drift.
  const scale=Math.min(.18,185/(seatHeight+sitting));
  const floor=218,seatY=floor-effectiveHeight*scale,rear=149;
  const depth=(key==='seat_depth_mm'?value:seatDepth)*scale,oldDepth=current*scale;
  const backLength=Math.min(94,sitting*scale*.76),r=(angle?value:backAngle)*Math.PI/180;
  const topX=rear-Math.sin(r)*backLength,topY=seatY-Math.cos(r)*backLength;
  root.append(text(86,25,'侧面'),line('M78 219H342','#e1e5dc',1));
  root.append(line(`M${rear+12} ${seatY+8}V${floor}M${rear+seatDepth*scale-12} ${seatY+8}V${floor}`,'#aab4a5',5));
  if(key==='seat_height_mm'){
    const oldY=floor-current*scale;
    root.append(line(`M${rear} ${oldY}h${depth}`,muted,3,{'stroke-dasharray':'5 4'}));
    measure(101,seatY,101,floor);root.append(text(87,(seatY+floor)/2,'座高',{'text-anchor':'end',fill:accent}));
  }
  root.append(line(`M${rear} ${seatY}L${topX} ${topY}`,angle?accent:'#aab4a5',6));
  root.append(svg('rect',{x:rear,y:seatY,width:depth,height:8,rx:1,fill:angle?'#e4e9de':'#f5dfd0',stroke:angle?'#aab4a5':accent,'stroke-width':2}));
  if(key==='seat_depth_mm')root.append(svg('rect',{x:rear,y:seatY-3,width:oldDepth,height:14,...ghost}));
  // Unmeasured leg lengths are schematic; they do not assert an ergonomic fit.
  const hipX=rear+16,hipY=seatY-10,thigh=(Number(body.stature_mm)||1700)*.245*scale;
  const torso=sitting*scale*.66,shoulderX=hipX-Math.sin(r)*torso,shoulderY=hipY-Math.cos(r)*torso;
  const bodyGroup=svg('g',{opacity:.8});
  bodyGroup.append(line(`M${shoulderX} ${shoulderY}L${hipX} ${hipY}H${hipX+thigh}L${hipX+thigh+7} ${floor-5}h18`,'#b8c5b0',10),svg('circle',{cx:shoulderX-3,cy:shoulderY-19,r:11,fill:'#b8c5b0'}),line(`M${shoulderX+2} ${shoulderY+15}l16 29h25`,'#b8c5b0',5));
  root.append(bodyGroup);
  if(key==='seat_depth_mm'){
    const y=seatY+32;
    root.append(line(`M${rear} ${seatY+10}V${y+5}M${rear+depth} ${seatY+10}V${y+5}`,accent,1));
    measure(rear,y,rear+depth,y);
    root.append(text(rear-7,y+4,'后端',{'text-anchor':'end'}),text(rear+depth+7,y+4,'前缘'));
  }
  if(angle){
    const old=current*Math.PI/180;
    root.append(line(`M${rear} ${seatY}l${-Math.sin(old)*backLength} ${-Math.cos(old)*backLength}`,muted,2,{'stroke-dasharray':'5 4'}),line(`M${rear} ${seatY}v-${backLength+13}`,'#cbd1c6',1,{'stroke-dasharray':'3 3'}));
    root.append(text(topX-12,topY-10,value+'°',{'text-anchor':'end',fill:accent,'font-size':15}));
  }
  const minY=Math.min(0,shoulderY-38);
  if(minY<0)root.setAttribute('viewBox',`0 ${minY} 420 ${250-minY}`);
  root.append(text(210,241,'身体轮廓为比例示意',{'text-anchor':'middle','font-size':10,fill:muted}));
  return root;
}
