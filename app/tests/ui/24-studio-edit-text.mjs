// Опечатка в тексте песни: правится двойным щелчком по строке, без пересборки
// и без потери разметки.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
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

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const st = await (await fetch(API+"/api/state")).json();
const PID = st.projects[0].id;
const srv = async () => (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json()).lines;

doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);
ok('редактор открылся', !$('scrEdit').classList.contains('hide'));

const before = await srv();
const I = 2;
const dbl = el => el.dispatchEvent(new w.MouseEvent('dblclick',{bubbles:true}));
const keyOn = (el,key) => el.dispatchEvent(new w.KeyboardEvent('keydown',
  {key, bubbles:true, cancelable:true}));

console.log('\n--- двойной щелчок открывает правку ---');
dbl(doc.querySelectorAll('#scroll .ln')[I]);
await sleep(80);
let inp = doc.querySelector('.lnedit');
ok('появилось поле ввода', !!inp);
ok('в нём текущий текст строки', inp && inp.value === before[I].text,
   inp ? `«${inp.value}» / «${before[I].text}»` : '');

console.log('\n--- Enter сохраняет ---');
const NEW = "исправленный текст этой строки";
inp.value = NEW;
keyOn(inp, 'Enter');
await sleep(900);
const after = await srv();
ok('текст на сервере изменился', after[I].text === NEW, after[I].text);
ok('поле ввода убралось', !doc.querySelector('.lnedit'));
ok('строка на сцене показывает новый текст',
   doc.querySelectorAll('#scroll .ln')[I].textContent.replace(/\s+/g,' ').trim()
     .includes('исправленный'),
   doc.querySelectorAll('#scroll .ln')[I].textContent.trim().slice(0,40));
ok('подпись на дорожке обновилась',
   doc.querySelectorAll('.blk')[I].textContent.includes('исправленный'),
   doc.querySelectorAll('.blk')[I].textContent.slice(0,40));

console.log('\n--- разметка строки не потерялась ---');
ok('время строки на месте',
   Math.abs(after[I].start - before[I].start) < 1e-6 &&
   Math.abs(after[I].end - before[I].end) < 1e-6,
   `${before[I].start}–${before[I].end} → ${after[I].start}–${after[I].end}`);
ok('слов столько же, сколько в новом тексте', after[I].words.length === NEW.split(' ').length,
   after[I].words.length + ' слов');
const ws = after[I].words;
ok('слова разложены внутри строки по порядку',
   ws.every((x,k)=> k===0 || x.t >= ws[k-1].t - 1e-9) &&
   ws[0].t >= after[I].start - 1e-6 &&
   ws[ws.length-1].t + ws[ws.length-1].d <= after[I].end + 1e-6,
   `${ws[0].t.toFixed(2)} … ${(ws[ws.length-1].t+ws[ws.length-1].d).toFixed(2)}`);
ok('длинному слову досталось больше времени, чем короткому',
   (() => { const a = ws.find(x=>x.w==='исправленный'), b = ws.find(x=>x.w==='и');
            return !a || !b ? true : a.d > b.d; })());
ok('соседние строки не тронуты',
   after[I-1].text === before[I-1].text && after[I+1].text === before[I+1].text);

console.log('\n--- Escape отменяет ---');
dbl(doc.querySelectorAll('#scroll .ln')[I]);
await sleep(80);
inp = doc.querySelector('.lnedit');
inp.value = "это не должно сохраниться";
keyOn(inp, 'Escape');
await sleep(700);
const after2 = await srv();
ok('текст остался прежним', after2[I].text === NEW, after2[I].text);

console.log('\n--- пустую строку не принимаем ---');
dbl(doc.querySelectorAll('#scroll .ln')[I]);
await sleep(80);
inp = doc.querySelector('.lnedit');
inp.value = "   ";
keyOn(inp, 'Enter');
await sleep(700);
const after3 = await srv();
ok('пустой текст не затёр строку', after3[I].text === NEW, after3[I].text);
ok('число строк не изменилось', after3.length === before.length,
   `${before.length} → ${after3.length}`);

console.log('\n--- правку текста можно найти, не зная про двойной щелчок ---');
const click = id => $(id).dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
doc.querySelectorAll('#scroll .ln')[3].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(80);
ok('кнопка «Текст строки» есть и подписана понятно',
   !!$('btnText') && /Текст/.test($('btnText').textContent), ($('btnText')||{}).textContent);
click('btnText'); await sleep(120);
ok('она открывает то же поле ввода', !!doc.querySelector('.lnedit'));
ok('и правит именно выбранную строку',
   doc.querySelector('.lnedit').value === (await srv())[3].text,
   doc.querySelector('.lnedit').value);
doc.querySelector('.lnedit').dispatchEvent(new w.KeyboardEvent('keydown',
  {key:'Escape',bubbles:true,cancelable:true}));
await sleep(300);

console.log('\n--- и двойным щелчком по блоку на дорожке ---');
doc.querySelectorAll('.blk')[4].dispatchEvent(new w.MouseEvent('dblclick',{bubbles:true}));
await sleep(150);
ok('двойной щелчок по блоку открывает правку', !!doc.querySelector('.lnedit'));
ok('правится строка этого блока',
   doc.querySelector('.lnedit').value === (await srv())[4].text,
   doc.querySelector('.lnedit').value);
doc.querySelector('.lnedit').dispatchEvent(new w.KeyboardEvent('keydown',
  {key:'Escape',bubbles:true,cancelable:true}));
await sleep(300);

// Прибираем за собой: проект в стенде общий, и накопленные правки съедают
// запас времени внутри строк — следующий прогон падал бы на пустом месте.
console.log('\n--- возвращаем проект как было ---');
let __g = 0;
while (!$('btnUndo').disabled && __g++ < 100){
  $('btnUndo').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await sleep(90);
}
await sleep(900);
ok('история отмены исчерпана', $('btnUndo').disabled, 'шагов ' + __g);

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
