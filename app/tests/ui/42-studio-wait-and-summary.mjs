// Отсчёт до пения на пустой сцене и сводка по песне после сборки.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.confirm = () => true;
    w.fetch = (...a) => fetch(typeof a[0]==="string" && a[0].startsWith("/")
        ? API + a[0] : a[0], a[1]);
    w.__now=0;
    w.AudioContext = class { constructor(){ this.state="running"; this.destination={}; }
      get currentTime(){ return w.__now; }
      createGain(){ return {gain:{value:1, setTargetAtTime(v){this.value=v;}}, connect(){}}; }
      createBufferSource(){ return {connect(){},start(){},stop(){},onended:null}; }
      decodeAudioData(){ return Promise.resolve({duration:26.04}); } resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () =>
      ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
    w.Element.prototype.setPointerCapture = function(){};
    Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{get(){return 900;}});
    Object.defineProperty(w.HTMLElement.prototype,'clientHeight',{get(){return 400;}});
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r=>setTimeout(r,ms));
w.eval(js);
await sleep(900);

// Размеры заданы в rem от html{font-size:clamp(16px…)} — jsdom их не считает.
// Берём нижнюю границу clamp, 16px: если проходит на ней, пройдёт и на большом экране.
const cssPx = v => /rem$/.test(String(v)) ? parseFloat(v) * 16 : parseFloat(v || 0);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const PID = (await (await fetch(API+"/api/state")).json()).projects[0].id;
const proj = await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json();
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1400);

console.log('--- сводка после сборки ---');
const sum = $("sum").textContent;
ok('сводка не пустая', $("sum").children.length >= 4, `${$("sum").children.length} клеток`);
{
  const c = $("sum").querySelector(".c");
  const size = el => cssPx(w.getComputedStyle(el).fontSize);
  ok('числа в сводке крупные', size(c.querySelector("b")) >= 16,
     w.getComputedStyle(c.querySelector("b")).fontSize);
  ok('подписи в сводке не мельче 12px', size(c.querySelector("span")) >= 12,
     w.getComputedStyle(c.querySelector("span")).fontSize);
}
const cells = [...$("sum").querySelectorAll('.c')].map(c => c.textContent);
ok('в ней есть число строк',
   cells.some(c => c.startsWith(String(proj.lines.length)) && /Строк/.test(c)),
   cells.join(" | "));
ok('и длина песни', /Длина/.test(sum));
ok('и места без пения', /Без пения/.test(sum));

console.log('\n--- отсчёт, пока не поют ---');
const last = proj.lines[proj.lines.length - 1];
$("btnPlay").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(120);
w.__now = last.end + 0.4; await sleep(260);
ok('после последней строки видно, сколько осталось',
   !$("wait").classList.contains('hide'), $("wait").textContent);
const n1 = $("waitNum").textContent, f1 = parseFloat($("waitFill").style.width);
ok('отсчёт стоит наверху сцены, а не посреди текста',
   (w.getComputedStyle($("wait")).top || "") !== "50%",
   w.getComputedStyle($("wait")).top);
// Мелкий шрифт на большом экране не читается — держим размеры под контролем.
const px = (el, prop) => cssPx(w.getComputedStyle(el)[prop]);
ok('число в отсчёте крупное', px($("waitNum"), "fontSize") >= 18,
   w.getComputedStyle($("waitNum")).fontSize);
ok('подпись при нём не мельче 12px', px($("waitTtl"), "fontSize") >= 12,
   w.getComputedStyle($("waitTtl")).fontSize);
ok('строка, которую ждём, читается', px($("waitTxt"), "fontSize") >= 14,
   w.getComputedStyle($("waitTxt")).fontSize);
w.__now = last.end + 1.4; await sleep(260);
const n2 = $("waitNum").textContent, f2 = parseFloat($("waitFill").style.width);
ok('отсчёт идёт', n1 !== n2, `${n1} → ${n2}`);
ok('полоска движется', f2 > f1, `${f1}% → ${f2}%`);

console.log('\n--- мелкий перерыв не отсчитывается ---');
// в тестовой песне паузы между строками — доли секунды
const gaps = [];
for (let i = 1; i < proj.lines.length; i++)
  gaps.push({at: proj.lines[i-1].end, gap: proj.lines[i].start - proj.lines[i-1].end});
const small = gaps.filter(g => g.gap > 0.2 && g.gap < 5).sort((a,b)=>a.gap-b.gap)[0];
ok('короткие паузы в песне есть', !!small, JSON.stringify(gaps.map(g=>+g.gap.toFixed(2))));
w.__now = small.at + small.gap/2; await sleep(260);
ok(`пауза в ${small.gap.toFixed(1)} с ничего не показывает`,
   $("wait").classList.contains('hide'), $("wait").textContent);
w.__now = proj.lines[1].start + 0.2; await sleep(260);
ok('и на самой строке отсчёта нет', $("wait").classList.contains('hide'));

console.log('\n--- пустая дорожка объясняет, что впереди ---');
// Приближаем дорожку, чтобы в окно и правда не попадала ни одна строка.
const ZOOMS = 5;
for (let i = 0; i < ZOOMS; i++)
  $("btnZoomIn").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
// самый широкий промежуток между строками
let hole = {gap: 0};
for (let i = 1; i < proj.lines.length; i++){
  const g = proj.lines[i].start - proj.lines[i-1].end;
  if (g > hole.gap) hole = {gap: g, at: proj.lines[i-1].end + g/2, next: proj.lines[i]};
}
w.__now = hole.at; await sleep(300);

w.__now = last.end + 2.5; await sleep(300);
ok('после песни подсказка смотрит назад', $("tlnext").classList.contains('back'),
   $("tlnext").textContent);

w.__now = proj.lines[0].start + 0.2; await sleep(300);
ok('когда строка в окне — подсказки нет', $("tlnext").classList.contains('hide'),
   $("tlnext").textContent);
console.log('\n--- длинный проигрыш: и отсчёт, и подсказка ---');
// Длинных пауз в тестовой песне нет — делаем её сами теми же событиями мыши,
// какими двигает строку человек. Ctrl+Z потом всё вернёт.
const pd = (t,x) => { const e = new w.MouseEvent(t,{bubbles:true,cancelable:true,clientX:x});
                      Object.defineProperty(e,'pointerId',{value:1}); return e; };
$("btnPlay").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));   // стоп
for (let i = 0; i < ZOOMS; i++)                 // возвращаем обычный масштаб
  $("btnZoomOut").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
const LAST = proj.lines.length - 1;
const blk = doc.querySelectorAll('#blocks .blk')[LAST];
blk.dispatchEvent(pd('pointerdown', 200));
w.dispatchEvent(pd('pointermove', 560));       // +360 px при 60 px/с = +6 с
w.dispatchEvent(pd('pointerup', 560));
await sleep(1000);                              // ждём автосохранение
const now = (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json()).lines[LAST];
ok('последняя строка отодвинута — получился долгий проигрыш',
   now.start > proj.lines[LAST].start + 3,
   `${proj.lines[LAST].start.toFixed(2)} → ${now.start.toFixed(2)}`);

const mid = proj.lines[LAST - 1].end + (now.start - proj.lines[LAST - 1].end) / 2;
$("btnPlay").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(120);
w.__now = mid; await sleep(300);
ok('в долгом проигрыше отсчёт есть', !$("wait").classList.contains('hide'),
   $("wait").textContent);
ok('названа строка, которая будет дальше',
   $("waitTxt").textContent.includes(now.text.slice(0, 12)), $("waitTxt").textContent);
// На обычном масштабе в окно попадают соседние строки — подсказка не нужна.
ok('пока строки видны, подсказки на дорожке нет',
   $("tlnext").classList.contains('hide'), $("tlnext").textContent);
for (let i = 0; i < ZOOMS; i++)                 // приближаем: окно внутри проигрыша
  $("btnZoomIn").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(300);
ok('в пустом окне подсказка показывает строку впереди',
   !$("tlnext").classList.contains('hide') &&
   !$("tlnext").classList.contains('back') &&
   $("tlnext").textContent.includes(now.text.slice(0, 12)),
   $("tlnext").textContent);
for (let i = 0; i < ZOOMS; i++)
  $("btnZoomOut").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);

$("btnPlay").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
$("btnUndo").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1000);
const back2 = (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json()).lines[LAST];
ok('стенд возвращён в исходное состояние',
   Math.abs(back2.start - proj.lines[LAST].start) < 0.01,
   `${back2.start} vs ${proj.lines[LAST].start}`);

console.log('\n--- пары цветов подписаны ---');
const picks = [...doc.querySelectorAll('.pick')];
ok('пар две', picks.length === 2, String(picks.length));
ok('у каждой своя подпись', picks.every(p => p.querySelector('b') &&
   p.querySelector('b').textContent.trim().length > 2),
   picks.map(p => p.querySelector('b') && p.querySelector('b').textContent).join(" | "));
ok('квадратики подписаны по отдельности',
   ["col1","col2","colBg","colTx"].every(id => ($(id).title||"").length > 2),
   ["col1","col2","colBg","colTx"].map(id => $(id).title).join(" | "));

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
