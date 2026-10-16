'use strict';
// 配合 build_web.py 嵌入 docs/index.html；除外链的点击跳转外，不向任何服务器请求数据。
const LESSONS = /*__LESSONS__*/;
const CATALOG = /*__CATALOG__*/;
const $ = id => document.getElementById(id);
const MAX_ITEMS = 40;
const picked = new Set(['巨无霸','中薯条','可乐']);
let selectedId = LESSONS[0].id;
let lastDoc = null;
let imageQueue = [];
let imageIndex = 0;
let toastTimer = null;

function normalizeItems(raw) {
  if (!Array.isArray(raw)) throw new Error('订单餐品必须是数组');
  const merged = new Map();
  for (const item of raw) {
    let name, quantity;
    if (typeof item === 'string') { name = item; quantity = 1; }
    else if (item && typeof item === 'object') { name = item.name; quantity = item.quantity ?? 1; }
    else throw new Error('餐品格式有误');
    if (typeof name !== 'string') throw new Error('餐品名称应为文字');
    if (/[\x00-\x1f]/.test(name)) throw new Error('餐品名称不能包含控制字符');
    name = name.trim().replace(/\s+/g, ' ');
    if (!name || [...name].length > 72 || /[\x00-\x1f]/.test(name)) throw new Error('餐品名称为空或过长');
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 99) throw new Error('份数应为 1 至 99');
    if (!merged.has(name) && merged.size >= MAX_ITEMS) throw new Error('最多支持 40 种餐品');
    merged.set(name, Math.min(99, (merged.get(name) || 0) + quantity));
  }
  if (!merged.size) throw new Error('请先选一种餐品');
  return [...merged].map(([name, quantity]) => ({ name, quantity }));
}
function parseItems(text) {
  if (text.length > 5000) throw new Error('输入不能超过 5000 字');
  const parts = text.split(/[,，、;；\n]+/).map(x => x.trim()).filter(Boolean);
  return normalizeItems(parts.map(x => {
    const m = x.match(/^(.*?)\s*[×*xX]\s*(\d{1,2})$/);
    return m ? {name:m[1].trim(),quantity:Number(m[2])} : {name:x,quantity:1};
  }));
}
function currentItems() {
  const typed = $('customInput').value.trim();
  return typed ? parseItems(typed) : normalizeItems([...picked]);
}
function classify(name) {
  for (const kind of ['main','side','drink']) if (CATALOG.exact[kind].includes(name)) return kind;
  for (const kind of ['main','side','drink']) if (CATALOG.markers[kind].some(x => name.includes(x))) return kind;
  if (/(水|茶)$/.test(name) && !/(奶茶派|抹茶派)$/.test(name)) return 'drink';
  return 'side';
}
function fields(items) {
  const group = {main:[], side:[], drink:[]};
  for (const item of items) group[classify(item.name)].push(item.name);
  const main = group.main[0] || items[0].name;
  const others = items.filter(x => x.name !== main).map(x=>x.name);
  return {
    main, side:group.side[0] || others[0] || main,
    drink:group.drink[0] || others[0] || main,
    items:items.map(x=>x.name).join('、'),
    count:String(items.reduce((s,x)=>s+x.quantity,0)),
    kinds:String(items.length),
  };
}
function stableNumber(items) {
  const b = new TextEncoder().encode(items.map(x=>`${x.name}*${x.quantity}`).join('|'));
  let h = 2166136261;
  for (const v of b) { h ^= v; h = Math.imul(h, 16777619) >>> 0; }
  return h % 999 + 1;
}
function fill(template, f) {
  return template.replace(/\{([a-z]+)\}/g, (_, key) => {
    if (!(key in f)) throw new Error('课文模板字段无效');
    return f[key];
  });
}
function compose(items, lesson) {
  const norm = normalizeItems(items), f = fields(norm);
  return {
    id:lesson.id, number:stableNumber(norm), title:lesson.title,
    genre:lesson.genre, inspired_by:lesson.inspired_by || '',
    opening:fill(lesson.opening,f), body:lesson.body.map(p=>fill(p,f)),
    ending:fill(lesson.ending,f), items:norm,
    notice:'原创文学戏仿 · 非麦当劳官方产品'
  };
}
function showToast(text) {
  $('toast').textContent = text;
  $('toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>$('toast').classList.remove('show'), 2600);
}
function showError(message) { $('error').hidden = !message; $('error').textContent = message || ''; }
function make(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function setActiveLesson(id) {
  selectedId = id;
  document.querySelectorAll('.lesson-chip').forEach(b=>b.setAttribute('aria-pressed', String(b.dataset.id === id)));
}
function renderDoc(d) {
  lastDoc = d; imageQueue = []; imageIndex = 0;
  $('imageButton').textContent = '保存课文图片 ↓';
  $('lessonNumber').textContent = `第 ${String(d.number).padStart(3,'0')} 课`;
  $('lessonTitle').textContent = d.title;
  $('lessonGenre').textContent = d.genre;
  $('lessonInspiration').textContent = d.inspired_by ? `文学灵感：${d.inspired_by}` : '';
  const box = $('lessonBody'); box.replaceChildren();
  for (const paragraph of [d.opening,...d.body,d.ending]) box.appendChild(make('p',null,paragraph));
  $('lessonItems').textContent = `本课餐品：${d.items.map(x=>x.name+(x.quantity>1?' ×'+x.quantity:'')).join('、')}`;
}
function generate() {
  try {
    const items = currentItems();
    const lesson = LESSONS.find(x=>x.id === selectedId);
    if (!lesson) throw new Error('找不到课文');
    renderDoc(compose(items,lesson));
    updateSummary(items);
    showError('');
    showToast('新课文写好了！');
  } catch(e) {showError(e.message);}
}
function updateSummary(items) {
  $('orderSummary').textContent = `本课使用：${items.map(x=>x.name+(x.quantity>1?' ×'+x.quantity:'')).join('、')}`;
}
function updateFromInputs() {
  try { updateSummary(currentItems()); showError(''); }
  catch(e) { $('orderSummary').textContent = '等待选择有效餐品'; showError(e.message); }
}
function init() {
  for (const food of CATALOG.quick_picks) {
    const b = make('button','food-chip',food);
    b.type='button'; b.setAttribute('aria-pressed',String(picked.has(food)));
    b.addEventListener('click',()=>{
      if (picked.has(food)) picked.delete(food); else picked.add(food);
      b.setAttribute('aria-pressed',String(picked.has(food)));
      updateFromInputs();
    });
    $('foodChips').appendChild(b);
  }
  LESSONS.forEach((l,i)=>{
    const b=make('button','lesson-chip'); b.type='button'; b.dataset.id=l.id;
    b.setAttribute('aria-pressed',String(l.id===selectedId));
    b.appendChild(make('span','idx',String(i+1).padStart(2,'0')));
    b.appendChild(make('span','name',l.title));
    b.addEventListener('click',()=>{ setActiveLesson(l.id); generate(); });
    $('lessonChips').appendChild(b);
  });
  $('customInput').addEventListener('input',updateFromInputs);
  $('generateButton').addEventListener('click',generate);
  $('surpriseButton').addEventListener('click',()=>{
    const i=LESSONS.findIndex(x=>x.id===selectedId);
    setActiveLesson(LESSONS[(i+1)%LESSONS.length].id); generate();
  });
  $('copyButton').addEventListener('click',copyDoc);
  $('imageButton').addEventListener('click',saveImage);
  $('importButton').addEventListener('click',()=>$('importFile').click());
  $('importFile').addEventListener('change',importFile);
  updateFromInputs(); generate();
}
function textContent(d) {
  return [`麦门语文 · 第 ${String(d.number).padStart(3,'0')} 课`,d.title,`原创文学戏仿 · ${d.genre}`,'',d.opening,...d.body,d.ending,'','— 课文完 —',`本课餐品：${d.items.map(x=>x.name).join('、')}`].join('\n\n');
}
async function copyDoc() {
  if(!lastDoc) return;
  const value = textContent(lastDoc);
  try {
    if(navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
    else {
      const area=make('textarea'); area.value=value; area.style.position='fixed'; area.style.opacity='0';
      document.body.appendChild(area); area.select();
      const ok=document.execCommand('copy'); area.remove();
      if(!ok) throw new Error('复制失败');
    }
    showToast('全文已复制，可以分享啦');
  } catch(e) {showToast('复制失败，请手动选择课文内容');}
}
async function importFile(event) {
  const file=event.target.files?.[0];
  event.target.value='';
  if(!file) return;
  if(file.size > 100_000) {showError('文件过大（最多 100KB）');return;}
  try {
    const data=JSON.parse(await file.text());
    if (!data || data.format!=='mcd-chinese-class/items-v1' || !Array.isArray(data.items))
      throw new Error('请导入由本项目 --export-web 生成的 JSON');
    const keys=Object.keys(data);
    if(keys.some(x=>!['format','items'].includes(x))) throw new Error('文件含有额外字段，请使用脱敏订单文件');
    const items=normalizeItems(data.items);
    $('customInput').value = items.map(x=>x.name+(x.quantity>1?' ×'+x.quantity:'')).join('，');
    updateFromInputs(); generate();
    showToast('真实订单餐品已导入；文件未上传到网络');
  } catch(e) {showError(`导入失败：${e.message}`);}
}

// 无第三方依赖的 Canvas 长图：每一页有相同的标题与页码，不裁剪文字。
const IMG={w:1080,maxH:3200,pad:96,font:29,leading:60};
function wrap(ctx,text,width,firstIndent=0) {
  const lines=[];let line='', indent=firstIndent;
  // 逐码点遍历，emoji 不会被拆成代理字符。
  for(const ch of text) {
    if(ctx.measureText(line+ch).width > width-indent && line) {
      lines.push({text:line,indent});line='';indent=0;
    }
    line+=ch;
  }
  if(line) lines.push({text:line,indent});
  return lines;
}
function imageLayout(d) {
  const c=document.createElement('canvas'),ctx=c.getContext('2d');
  if(!ctx) throw new Error('当前浏览器不支持 Canvas');
  ctx.font=`${IMG.font}px serif`;
  const content=[];
  for (const p of [d.opening,...d.body,d.ending]) {
    content.push(...wrap(ctx,p,IMG.w-IMG.pad*2,IMG.font*2).map(x=>({...x,blank:false})));
    content.push({blank:true});
  }
  const headerH=385,footerH=180;
  const maxLines=Math.floor((IMG.maxH-headerH-footerH)/IMG.leading);
  const pages=[];
  for(let start=0;start<content.length;start+=maxLines) pages.push(content.slice(start,start+maxLines));
  return pages;
}
function drawSheet(d,lines,pageIndex,pageCount) {
  const W=IMG.w,headerH=385,footerH=180;
  const H=Math.min(IMG.maxH,Math.max(1150,headerH+lines.length*IMG.leading+footerH));
  const c=document.createElement('canvas'); c.width=W; c.height=H;
  const ctx=c.getContext('2d');
  ctx.fillStyle='#fffaf0';ctx.fillRect(0,0,W,H);
  ctx.fillStyle='#b74135';ctx.fillRect(0,0,W,17);
  ctx.fillStyle='#a39178';ctx.font='23px sans-serif';
  ctx.fillText(`麦门语文 · 第 ${String(d.number).padStart(3,'0')} 课`,IMG.pad,97);
  ctx.textAlign='right';ctx.fillText(`文学小品  /  ${String(pageIndex+1).padStart(2,'0')}`,W-IMG.pad,97);
  ctx.textAlign='center';ctx.fillStyle='#bc4636';ctx.font='bold 23px sans-serif';ctx.fillText('原 创 文 学 戏 仿',W/2,164);
  ctx.fillStyle='#262522';ctx.font='bold 59px serif';ctx.fillText(d.title,W/2,248);
  ctx.font='24px sans-serif';ctx.fillStyle='#8b8375';ctx.fillText(d.genre,W/2,306);
  ctx.strokeStyle='#ded6c5';ctx.beginPath();ctx.moveTo(IMG.pad,343);ctx.lineTo(W-IMG.pad,343);ctx.stroke();
  ctx.font=`${IMG.font}px serif`;ctx.fillStyle='#33302b';ctx.textAlign='left';
  lines.forEach((l,i)=>{if(!l.blank)ctx.fillText(l.text,IMG.pad+(l.indent||0),headerH+i*IMG.leading);});
  ctx.strokeStyle='#ded6c5';ctx.beginPath();ctx.moveTo(IMG.pad,H-145);ctx.lineTo(W-IMG.pad,H-145);ctx.stroke();
  ctx.font='22px sans-serif';ctx.fillStyle='#827768';
  let footer=`本课餐品：${d.items.map(x=>x.name).join('、')}`;
  while(ctx.measureText(footer).width>W-IMG.pad*2 && footer.length>9) footer=footer.slice(0,-2)+'…';
  ctx.fillText(footer,IMG.pad,H-104);
  ctx.font='20px sans-serif';ctx.fillStyle='#9d9487';ctx.fillText('麦门语文课 · 非麦当劳官方产品',IMG.pad,H-64);
  ctx.textAlign='right';ctx.fillText(`${pageIndex+1} / ${pageCount}`,W-IMG.pad,H-64);
  return c;
}
function saveImage() {
  if(!lastDoc) return;
  try {
    if(!imageQueue.length){imageQueue=imageLayout(lastDoc);imageIndex=0;}
    const i=imageIndex,canvas=drawSheet(lastDoc,imageQueue[i],i,imageQueue.length);
    canvas.toBlob(blob=>{
      if(!blob){showError('图片生成失败，请尝试更新浏览器');return;}
      const url=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=url;a.download=`麦门语文_${lastDoc.title}_${i+1}of${imageQueue.length}.png`;
      document.body.appendChild(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),2000);
      if(i+1<imageQueue.length){imageIndex=i+1;$('imageButton').textContent=`继续保存第 ${imageIndex+1}/${imageQueue.length} 页 ↓`;}
      else{imageQueue=[];imageIndex=0;$('imageButton').textContent='保存课文图片 ↓';}
      showToast(imageQueue.length?`第 ${i+1} 页已保存，请继续保存下一页`:'课文图片保存成功');
    },'image/png');
  }catch(e){showError(e.message);}
}

// 提供只读测试接口；页面交互依然使用按钮而非直接修改内部状态。
window.MCD_TEST={normalizeItems,parseItems,stableNumber,compose,imageLayout,currentDoc:()=>lastDoc};
init();
