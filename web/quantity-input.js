// A deliberately small dimensional expression parser. No eval or executable input.
export function parseQuantity(input, defaultUnit='mm') {
  const text=String(input).trim().toLowerCase().replace(/厘米/g,'cm').replace(/毫米/g,'mm').replace(/度/g,'deg').replace(/°/g,'deg').replace(/\s+/g,'');
  if(!text)throw new Error('请输入数值。');
  const terms=[...text.matchAll(/([+-]?)(\d+(?:\.\d+)?|\.\d+)(mm|cm|m|deg)?/g)];
  if(!terms.length||terms.map(t=>t[0]).join('')!==text||terms.slice(1).some(t=>!t[1]))throw new Error('支持数值、单位及加减，例如 42cm 或 400+20mm。');
  const angular=defaultUnit==='deg';
  const value=terms.reduce((sum,t)=>{const u=t[3]||defaultUnit;if((u==='deg')!==angular)throw new Error('角度和长度不能混合计算。');return sum+(t[1]==='-'?-1:1)*Number(t[2])*({mm:1,cm:10,m:1000,deg:1}[u]);},0);
  if(!Number.isFinite(value)||(!angular&&value<=0))throw new Error('请输入有效的正尺寸。');
  return Math.round(value*1000)/1000;
}
