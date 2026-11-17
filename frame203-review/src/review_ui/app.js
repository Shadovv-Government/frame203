'use strict';
const ATTRS=['occluded','truncated','group_of','depiction','inside'];
const $=id=>document.getElementById(id);
function parseCSV(raw){
 const text=raw.replace(/^\uFEFF/,'');if(!text.trim())return {headers:[],rows:[]};
 const lines=[];let row=[],v='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){v+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(v);v='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(v);if(row.some(x=>x!==''))lines.push(row);row=[];v='';}else v+=c;}
 if(quoted)throw new Error('CSV: незакрытая кавычка.');
 if(v!==''||row.length){row.push(v);if(row.some(x=>x!==''))lines.push(row);}
 const headers=lines.shift()||[];if(new Set(headers).size!==headers.length)throw new Error('CSV: повторяющиеся столбцы.');
 return {headers,rows:lines.map((r,i)=>{if(r.length!==headers.length)throw new Error(`CSV: строка ${i+2} имеет ${r.length} полей вместо ${headers.length}.`);return Object.fromEntries(headers.map((h,j)=>[h,r[j]??'']));})};
}
function serializeCSV(t){const q=v=>'"'+String(v??'').replaceAll('"','""')+'"';return '\uFEFF'+[t.headers,...t.rows.map(r=>t.headers.map(h=>r[h]??''))].map(r=>r.map(q).join(',')).join('\r\n')+'\r\n';}
function isTrue(v){return ['1','1.0','true','yes'].includes(String(v).toLowerCase());}
function num(v){return v===''||v==null?NaN:Number(v);}
function boxOf(r,s){const b=['x1','y1','x2','y2'].map(k=>num(r[`${k}_${s}`]));return b.every(Number.isFinite)?b:null;}
function needsReview(r,k){return k==='sms'?r.label_A!==r.label_B||r.subtype_A!==r.subtype_B||isTrue(r.uncertain_A)||isTrue(r.uncertain_B):r.status!=='matched'||num(r.iou)<.8||ATTRS.some(a=>isTrue(r[a+'_A'])!==isTrue(r[a+'_B']))||isTrue(r.uncertain_A)||isTrue(r.uncertain_B);}
function keyOf(r,k){return k==='sms'?r.id:r.pair_id;}
function checkItems(t,k){const required=k==='sms'?['id','text','label_A','label_B','subtype_A','subtype_B']:['id','pair_id','status','x1_A','y1_A','x2_A','y2_A','x1_B','y1_B','x2_B','y2_B'];const miss=required.filter(h=>!t.headers.includes(h));if(miss.length)throw new Error(`${k}_items.csv: нет столбцов ${miss.join(', ')}.`);const keys=t.rows.map(r=>keyOf(r,k));if(keys.some(x=>!x)||new Set(keys).size!==keys.length)throw new Error('Пустые или повторяющиеся ID в отчёте.');if(k==='cars'&&t.rows.some(r=>!['matched','only_A','only_B'].includes(r.status)))throw new Error('Неизвестный status рамки.');}
if(typeof module!=='undefined')module.exports={parseCSV,serializeCSV,isTrue,boxOf,needsReview,checkItems};
if(typeof document!=='undefined'){
const requestedStage=new URLSearchParams(location.search).get('set');
const stage=['repeat','main'].includes(requestedStage)?requestedStage:'pilot';
const stagePrefix=stage==='pilot'?'':`${stage}/`;
const state={root:null,files:new Map(),items:{sms:[],cars:[]},tables:{},raw:{},manifest:new Map(),imageNotes:new Map(),kind:'sms',selected:null,filtered:[],draft:{},dirty:false,busy:false,unsavedDownload:false,image:null,imageUrl:null,imageToken:0};
let theme=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';document.documentElement.dataset.theme=theme;
$('theme').onclick=()=>{theme=theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;drawImages();};
function notice(m,error=false){$('notice').textContent=m;$('notice').classList.toggle('error',error);$('notice').hidden=false;}
function message(e){return e instanceof Error?e.message:String(e);}
function text(tag,value,cls=''){const el=document.createElement(tag);el.textContent=value;if(cls)el.className=cls;return el;}
async function handleAt(path,create=false){const parts=path.split('/');let dir=state.root;for(const p of parts.slice(0,-1))dir=await dir.getDirectoryHandle(p,{create});return dir.getFileHandle(parts.at(-1),{create});}
async function readFile(path){if(state.root){try{return await (await handleAt(path)).getFile();}catch(e){if(e.name==='NotFoundError')return null;throw e;}}return state.files.get(path)||null;}
async function readText(path){const f=await readFile(path);return f?await f.text():null;}
function resPath(k){return `labeling/resolution/${stagePrefix}${k}_resolution.csv`;}
function defaultTable(k){return {headers:k==='sms'?['id','text','label_A','label_B','subtype_A','subtype_B','comment_A','comment_B','gold_label','gold_subtype','exclude','note','reviewed','reviewed_at']:['pair_id','id','status','iou','keep','use','note','reviewed','reviewed_at'],rows:[]};}
async function loadProject(){
 if(state.imageUrl)URL.revokeObjectURL(state.imageUrl);state.image=null;state.imageUrl=null;state.manifest.clear();state.imageNotes.clear();state.items={sms:[],cars:[]};state.tables={};state.raw={};state.dirty=false;state.unsavedDownload=false;const errors=[];
 for(const k of ['sms','cars']){const raw=await readText(`reports/agreement/${stagePrefix}${k}_items.csv`);if(raw===null)continue;try{const t=parseCSV(raw);checkItems(t,k);state.items[k]=t.rows;const rt=await readText(resPath(k));state.raw[k]=rt;state.tables[k]=rt===null?defaultTable(k):parseCSV(rt);for(const h of defaultTable(k).headers)if(!state.tables[k].headers.includes(h))state.tables[k].headers.push(h);const keys=state.tables[k].rows.map(r=>keyOf(r,k));if(keys.some(x=>!x)||new Set(keys).size!==keys.length)throw new Error('Таблица сверки: пустые или повторяющиеся ID.');const known=new Set(t.rows.map(r=>keyOf(r,k)));if(keys.some(x=>!known.has(x)))throw new Error('Таблица сверки не соответствует отчёту: неизвестные ID.');}catch(e){state.items[k]=[];delete state.tables[k];errors.push(`${k}: ${message(e)}`);}}
 const manifest=await readText('data/interim/car_enrichment/car_enrichment_manifest.csv');if(manifest){try{for(const r of parseCSV(manifest).rows)state.manifest.set(r.id,r);}catch(e){errors.push('Манифест: '+message(e));}}
 for(const side of ['A','B']){const raw=await readText(`labeling/exports/${stage}/${side}_cars.json`);if(!raw)continue;try{const tasks=JSON.parse(raw),knownIds=new Set(tasks.map(t=>t.data?.id));if(!state.items.cars.every(r=>knownIds.has(r.id)))continue;for(const task of tasks){const anns=(task.annotations||[]).filter(a=>!a.was_cancelled).sort((a,b)=>String(b.updated_at||b.created_at||'').localeCompare(String(a.updated_at||a.created_at||'')));const results=anns[0]?.result||[],comment=results.filter(r=>r.from_name==='comment'&&r.type==='textarea').flatMap(r=>r.value?.text||[]).join(' '),uncertain=results.some(r=>r.from_name==='uncertain'&&r.value?.choices?.includes('uncertain'));state.imageNotes.set(`${task.data?.id}_${side}`,{comment,uncertain});}}catch(e){errors.push(`${side}_cars.json: ${message(e)}`);}}
 if(!state.items.sms.length&&!state.items.cars.length)throw new Error(errors.join('\n')||`Нет отчётов для этапа ${stage}. Проверьте папку и запустите agreement.py с --set ${stage}.`);
 state.kind=state.items.sms.length?'sms':'cars';state.selected=null;$('search').value='';$('filter').value='review';$('welcome').hidden=true;$('app').hidden=false;$('projectName').textContent=`${state.root?state.root.name:'Только чтение'} · ${stage}`;$('saveMode').textContent=state.root?'Запись в labeling/resolution/. Перед записью — резервная копия.':'Только чтение: решения в памяти. Скачайте CSV перед закрытием.';$('countSms').textContent=state.items.sms.length;$('countCars').textContent=new Set(state.items.cars.map(r=>r.id)).size+' фото';notice(errors.length?errors.join('\n'):state.root?'Папка подключена. Исходные JSON и отчёты agreement не изменяются.':'Нет права записи. Используйте «Скачать таблицы сверки».',errors.length>0);refresh();
}
function canLeave(){return !state.dirty||confirm('Есть несохранённое решение. Перейти без сохранения?');}
$('openFolder').onclick=async()=>{if(!canLeave()||state.unsavedDownload&&!confirm('Решения режима чтения будут сброшены. Вы уже скачали таблицы?'))return;if(!window.showDirectoryPicker){notice('Откройте Chrome/Edge для записи или воспользуйтесь режимом чтения.',true);return;}try{state.root=await window.showDirectoryPicker({mode:'readwrite',id:'frame203-review'});state.files.clear();await loadProject();}catch(e){if(e.name!=='AbortError')notice(message(e),true);}};
$('fallbackOpen').onclick=()=>{if(canLeave())$('folderInput').click();};
$('folderInput').onchange=async e=>{try{state.root=null;state.files.clear();for(const f of e.target.files){const p=f.webkitRelativePath.split('/');state.files.set(p.slice(1).join('/'),f);}await loadProject();}catch(err){notice(message(err),true);}};
function resolution(r){return state.tables[state.kind].rows.find(x=>keyOf(x,state.kind)===keyOf(r,state.kind));}
function current(){return state.items[state.kind].find(r=>keyOf(r,state.kind)===state.selected);}
function reviewed(r){return isTrue(resolution(r)?.reviewed);}
function refresh(){
 $('tabSms').classList.toggle('active',state.kind==='sms');$('tabCars').classList.toggle('active',state.kind==='cars');const q=$('search').value.toLowerCase().trim(),filter=$('filter').value,all=state.items[state.kind],required=all.filter(r=>needsReview(r,state.kind));
 state.filtered=all.filter(r=>[r.id,r.pair_id,r.text].filter(Boolean).join(' ').toLowerCase().includes(q)&&(filter==='all'||filter==='review'&&needsReview(r,state.kind)||filter==='pending'&&needsReview(r,state.kind)&&!reviewed(r)||filter==='done'&&reviewed(r)));
 if(!state.filtered.some(r=>keyOf(r,state.kind)===state.selected))state.selected=state.filtered.length?keyOf(state.filtered[0],state.kind):null;
 const done=required.filter(reviewed).length;$('progressLabel').textContent=`${done} / ${required.length} спорных проверено`;$('progress').max=required.length||1;$('progress').value=done;$('dirtyLabel').textContent=state.unsavedDownload?'Скачайте CSV':'';
 const list=$('itemList');list.replaceChildren();for(const r of state.filtered){const key=keyOf(r,state.kind),b=text('button',r.id);b.classList.toggle('active',key===state.selected);const desc=state.kind==='sms'?`${r.label_A} / ${r.label_B}`:`${r.status==='matched'?'Пара':r.status==='only_A'?'Только A':'Только B'} · #${r.pair_id.split('#').at(-1)}`;b.append(text('small',`${reviewed(r)?'Проверено · ':''}${desc}`));b.onclick=()=>{if(canLeave()){state.selected=key;refresh();}};list.append(b);}render();
}
function move(delta){if(!canLeave())return;const i=state.filtered.findIndex(r=>keyOf(r,state.kind)===state.selected),r=state.filtered[i+delta];if(r){state.selected=keyOf(r,state.kind);refresh();}}
$('prev').onclick=()=>move(-1);$('next').onclick=()=>move(1);$('defer').onclick=()=>move(1);
for(const k of ['sms','cars'])$('tab'+(k==='sms'?'Sms':'Cars')).onclick=()=>{if(canLeave()){state.kind=k;state.selected=null;refresh();}};
$('search').onchange=()=>{if(canLeave()){state.selected=null;refresh();}};$('filter').onchange=()=>{if(canLeave()){state.selected=null;refresh();}};
function render(){
 const r=current();state.dirty=false;$('empty').hidden=!!r;$('smsView').hidden=!r||state.kind!=='sms';$('carsView').hidden=!r||state.kind!=='cars';$('decisionPanel').hidden=!r;const i=state.filtered.findIndex(x=>keyOf(x,state.kind)===state.selected);$('position').textContent=`${i+1} / ${state.filtered.length}`;$('prev').disabled=i<=0;$('next').disabled=i<0||i>=state.filtered.length-1;$('defer').disabled=$('next').disabled;
 if(!r){$('itemId').textContent='Нет случаев по фильтру';$('itemKind').textContent=state.kind==='sms'?'SMS':'АВТОМОБИЛИ';return;}
 const res=resolution(r)||{};state.draft={...res};$('itemId').textContent=r.id;$('itemKind').textContent=state.kind==='sms'?'SMS / СВЕРКА МЕТОК':`АВТОМОБИЛИ / ${r.pair_id}`;$('note').value=res.note||'';$('reviewState').textContent=isTrue(res.reviewed)?'Проверено вручную':'Требует просмотра';$('saveFeedback').textContent='Выберите ответ, затем сохраните.';$('smsDecision').hidden=state.kind!=='sms';$('carsDecision').hidden=state.kind!=='cars';$('save').disabled=false;
 if(state.kind==='sms'){
  $('smsText').textContent=r.text;for(const s of ['A','B']){const el=$('sms'+s);el.replaceChildren(text('strong',`${r['label_'+s]||'Нет метки'}${r['subtype_'+s]?' / '+r['subtype_'+s]:''}`,'label'));if(isTrue(r['uncertain_'+s]))el.append(text('p','Аннотатор отметил uncertain'));el.append(text('p',r['comment_'+s]||'Комментария нет','comment'));}
  const same=r.label_A===r.label_B&&r.subtype_A===r.subtype_B;$('goldLabel').value=res.gold_label||(same?r.label_A:'');$('goldSubtype').value=res.gold_subtype||(same?r.subtype_A:'');updateSubtype();$('decisionHint').textContent='Примите A/B или укажите итоговую метку вручную. Совпавший, но сомнительный ответ тоже нужно проверить.';
 }else{
  $('boxMeta').textContent=`${r.status} · IoU: ${Number.isFinite(num(r.iou))?num(r.iou).toFixed(3):'—'} · рамок A/B на фото: ${r.boxes_A??'—'} / ${r.boxes_B??'—'}`;
  for(const s of ['A','B']){const b=boxOf(r,s),a=ATTRS.filter(x=>isTrue(r[`${x}_${s}`]));const meta=state.imageNotes.get(`${r.id}_${s}`),info=b?`${a.length?a.join(', '):'Атрибутов нет'} · [${b.map(v=>v.toFixed(3)).join(', ')}]`:'У этого аннотатора рамки нет';$('attrs'+s).textContent=info+(isTrue(r['uncertain_'+s])?' · uncertain':'')+(meta?.comment?' · Комментарий к фото: '+meta.comment:'');}
  document.querySelectorAll('[data-car]').forEach(b=>{b.disabled=b.dataset.car==='A'&&!boxOf(r,'A')||b.dataset.car==='B'&&!boxOf(r,'B');});
  $('decisionHint').textContent=r.status==='matched'?'Выберите точную рамку A или B. Пустой use в старой таблице означает усреднение: здесь нужен явный выбор.':'Корректная машина — оставьте рамку. Лишний объект или дубликат другой строки — уберите.';updateCarButtons();loadImage(r);
 }
}
function markDirty(){state.dirty=true;$('saveFeedback').textContent='Решение ещё не сохранено.';}
function updateSubtype(){const ham=$('goldLabel').value==='ham';$('goldSubtype').disabled=ham;if(ham)$('goldSubtype').value='';}
$('goldLabel').onchange=()=>{updateSubtype();markDirty();};$('goldSubtype').onchange=markDirty;$('note').oninput=markDirty;
for(const s of ['A','B'])$('acceptSms'+s).onclick=()=>{const r=current();$('goldLabel').value=r['label_'+s];$('goldSubtype').value=r['subtype_'+s];updateSubtype();markDirty();};
function updateCarButtons(){document.querySelectorAll('[data-car]').forEach(b=>{const sel=state.draft.keep==='0'?'drop':state.draft.keep==='1'?state.draft.use:'';b.classList.toggle('selected',b.dataset.car===sel);});}
document.querySelectorAll('[data-car]').forEach(b=>b.onclick=()=>{const v=b.dataset.car;state.draft.keep=v==='drop'?'0':'1';state.draft.use=v==='drop'?'':v;updateCarButtons();markDirty();});
async function imageFile(r){const m=state.manifest.get(r.id)||{},name=m.file_name||r.id.replace(/^img_new_/,'car_new_')+'.jpg';for(const p of [`data/processed/images_new_v1/${name}`,m.file_path,`data/raw/images_new/wikimedia/${name}`].filter(Boolean)){const f=await readFile(p);if(f)return f;}return null;}
async function loadImage(r){
 const token=++state.imageToken;$('imageError').hidden=true;if(state.image?.dataset.id===r.id){drawImages();return;}state.image=null;drawImages();
 try{const f=await imageFile(r);if(!f)throw new Error('Локальная фотография не найдена. Ожидается data/processed/images_new_v1/'+r.id.replace(/^img_new_/,'car_new_')+'.jpg. Выберите корень проекта целиком.');const url=URL.createObjectURL(f),img=new Image();img.dataset.id=r.id;await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(new Error('Не удалось прочитать изображение.'));img.src=url;});if(token!==state.imageToken){URL.revokeObjectURL(url);return;}if(state.imageUrl)URL.revokeObjectURL(state.imageUrl);state.imageUrl=url;state.image=img;$('zoom').value='100';drawImages();}catch(e){if(token===state.imageToken){$('imageError').textContent=message(e);$('imageError').hidden=false;}}
}
function drawImages(){
 const row=current();if(!row||state.kind!=='cars')return;const mode=$('displayMode').value,split=mode==='split';$('figureB').hidden=!split;$('imageGrid').classList.toggle('single',!split);$('captionA').textContent=split?'A / Кирилл':mode==='overlay'?'A + B / наложение':'Исходное фото';const z=Number($('zoom').value)/100;$('zoomLabel').textContent=`${Math.round(z*100)}%`;
 for(const s of ['A','B']){if(s==='B'&&!split)continue;const c=$('canvas'+s),ctx=c.getContext('2d'),view=$('scroll'+s),img=state.image,w=Math.max(200,Math.round(view.clientWidth*z)),h=img?Math.round(w*img.naturalHeight/img.naturalWidth):280;c.width=w;c.height=h;c.style.width=w+'px';c.style.height=h+'px';
  if(!img){ctx.fillStyle='#242622';ctx.fillRect(0,0,w,h);ctx.fillStyle='#fff';ctx.font='16px sans-serif';ctx.fillText('Загрузка фотографии…',20,40);continue;}ctx.drawImage(img,0,0,w,h);if(mode==='original')continue;
  const imageRows=state.items.cars.filter(r=>r.id===row.id),sides=mode==='overlay'?['A','B']:[s];
  function rect(r,side,active){const b=boxOf(r,side);if(!b)return;const [x1,y1,x2,y2]=b;ctx.strokeStyle=side==='A'?'#31b9ff':'#ffb24a';ctx.lineWidth=active?4:1.5;ctx.globalAlpha=active?1:.38;ctx.setLineDash(side==='B'&&mode==='overlay'?[8,4]:[]);ctx.strokeRect(x1*w,y1*h,(x2-x1)*w,(y2-y1)*h);ctx.setLineDash([]);if(active){const label=`${side} #${r.pair_id.split('#').at(-1)}`;ctx.font='bold 15px sans-serif';const tw=ctx.measureText(label).width+12,x=Math.max(0,Math.min(w-tw,x1*w)),y=Math.max(0,y1*h-25);ctx.globalAlpha=1;ctx.fillStyle='#141816';ctx.fillRect(x,y,tw,24);ctx.fillStyle=side==='A'?'#31b9ff':'#ffb24a';ctx.fillText(label,x+6,y+17);}}
  if($('contextBoxes').checked)for(const r of imageRows)if(r.pair_id!==row.pair_id)for(const side of sides)rect(r,side,false);for(const side of sides)rect(row,side,true);ctx.globalAlpha=1;
 }
}
for(const id of ['displayMode','zoom','contextBoxes'])$(id).oninput=drawImages;
let scrollSync=false;for(const [a,b] of [['A','B'],['B','A']])$('scroll'+a).onscroll=()=>{if(scrollSync)return;scrollSync=true;const p=$('scroll'+a),q=$('scroll'+b);q.scrollLeft=p.scrollLeft;q.scrollTop=p.scrollTop;requestAnimationFrame(()=>scrollSync=false);};
$('focusBox').onclick=()=>{const r=current(),b=boxOf(r,'A')||boxOf(r,'B');if(!b)return;$('zoom').value='300';drawImages();requestAnimationFrame(()=>{for(const s of ['A','B']){const v=$('scroll'+s),c=$('canvas'+s);v.scrollLeft=(b[0]+b[2])/2*c.width-v.clientWidth/2;v.scrollTop=(b[1]+b[3])/2*c.height-v.clientHeight/2;}});};
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(drawImages,120);});
async function writeFile(path,value){const h=await handleAt(path,true),w=await h.createWritable();try{await w.write(value);await w.close();}catch(e){await w.abort().catch(()=>{});throw e;}}
async function persist(k,table){
 if(!state.root){state.tables[k]=table;state.unsavedDownload=true;return;}
 const path=resPath(k),latest=await readText(path);if(latest!==state.raw[k])throw new Error('Таблица изменена другим приложением или вкладкой. Запись отменена. Скачайте текущие решения отдельно, затем откройте папку заново.');
 if(latest!==null){const stamp=new Date().toISOString().replace(/[:.]/g,'-')+'-'+Math.random().toString(36).slice(2,7);await writeFile(`labeling/resolution/backups/${k}_resolution.${stamp}.csv`,latest);}
 const csv=serializeCSV(table);await writeFile(path,csv);state.raw[k]=csv.replace(/^\uFEFF/,'');if((await readText(path))?.replace(/^\uFEFF/,'')!==state.raw[k])throw new Error('Проверка записи не пройдена. Проверьте файл на диске.');state.tables[k]=table;
}
$('save').onclick=async()=>{
 if(state.busy)return;const r=current();if(!r)return;const k=state.kind,key=keyOf(r,k),note=$('note').value.trim();let dec;
 if(!note){$('saveFeedback').textContent='Добавьте краткую причину решения.';$('note').focus();return;}
 if(k==='cars'&&(!state.image||state.image.dataset.id!==r.id)){$('saveFeedback').textContent='Дождитесь загрузки фотографии. Нельзя подтвердить рамку без изображения.';return;}
 if(k==='sms'){const label=$('goldLabel').value,sub=$('goldSubtype').value;if(!['ham','spam'].includes(label)||label==='spam'&&!['smishing','fraud','prize','premium','promo'].includes(sub)){$('saveFeedback').textContent='Выберите метку и подтип для spam.';return;}dec={gold_label:label,gold_subtype:label==='spam'?sub:'',note};}
 else{const {keep,use}=state.draft;if(!['0','1'].includes(keep)||keep==='1'&&!['A','B'].includes(use)){$('saveFeedback').textContent='Выберите рамку A/B или «Убрать рамку».';return;}if(keep==='1'&&!boxOf(r,use)){$('saveFeedback').textContent='Выбранной рамки нет.';return;}dec={keep,use,note};}
 const table={headers:[...state.tables[k].headers],rows:state.tables[k].rows.map(x=>({...x}))};let target=table.rows.find(x=>keyOf(x,k)===key);if(!target){target=Object.fromEntries(table.headers.map(h=>[h,r[h]??'']));table.rows.push(target);}Object.assign(target,dec,{reviewed:'1',reviewed_at:new Date().toISOString()});
 state.busy=true;$('app').inert=true;$('openFolder').disabled=true;$('save').disabled=true;const next=state.filtered[state.filtered.findIndex(x=>keyOf(x,k)===key)+1];
 try{await persist(k,table);state.dirty=false;state.selected=next?keyOf(next,k):key;refresh();notice(state.root?'Решение сохранено на диск. Если таблица уже существовала, её копия — в labeling/resolution/backups/.':'Решение в памяти. Скачайте таблицы перед закрытием страницы.');$('saveFeedback').textContent=next?'Предыдущее решение сохранено.':'Решение сохранено. Вы дошли до конца списка.';}
 catch(e){notice(message(e),true);$('saveFeedback').textContent='Сохранение не подтверждено. Не закрывайте страницу.';}
 finally{state.busy=false;$('app').inert=false;$('openFolder').disabled=false;$('save').disabled=false;}
};
function downloadBlob(value,name){const url=URL.createObjectURL(new Blob([value],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);}
$('download').onclick=()=>{if(state.dirty){notice('Сначала сохраните текущее решение кнопкой «Сохранить и дальше».',true);return;}['sms','cars'].filter(k=>state.tables[k]).forEach((k,i)=>setTimeout(()=>downloadBlob(serializeCSV(state.tables[k]),`${k}_resolution.csv`),i*350));notice('CSV подготовлены к скачиванию. Разрешите несколько загрузок. В режиме чтения положите их в каталог сверки текущего этапа, предварительно сохранив старые копии.');};
window.addEventListener('beforeunload',e=>{if(state.dirty||state.unsavedDownload||state.busy){e.preventDefault();e.returnValue='';}});
}
