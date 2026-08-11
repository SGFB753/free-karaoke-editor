// Перетаскивание строки по дорожке мышкой: самый частый способ править разметку.
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
    class Gain{ constructor(){ this.gain={value:1}; } connect(){} }
    class Src{ constructor(){ this.onended=null; } connect(){}
      start(){} stop(){} }
    w.AudioContext = class {
      constructor(){ this.state="running"; this.destination={}; }
      get currentTime(){ return w.__now; }
      createGain(){ return new Gain(); } createBufferSource(){ return new Src(); }
      decodeAudioData(){ return Promise.resolve({duration:26.04}); }
      resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () =>
      ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
    w.Element.prototype.setPointerCapture = function(){};
    w.Element.prototype.releasePointerCapture = function(){};
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
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);
ok('редактор открылся', !$('scrEdit').classList.contains('hide'));

const srvStarts = async () => (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json()).lines.map(l=>l.start);
const before = await srvStarts();

const blocks = [...doc.querySelectorAll('.blk')];
ok('блоки на дорожке есть', blocks.length >= 3, 'блоков '+blocks.length);

// --- тащим третий блок вправо -------------------------------------------
console.log('\n--- тянем строку вправо ---');
const B = blocks[2];
const pd = (t,x) => { const e = new w.MouseEvent(t,{bubbles:true,cancelable:true,clientX:x});
                      Object.defineProperty(e,'pointerId',{value:1});
                      return e; };
B.dispatchEvent(pd('pointerdown', 100));
await sleep(30);
ok('строка выделилась при захвате', /строка 3/.test($('selNote').textContent),
   $('selNote').textContent);

w.dispatchEvent(pd('pointermove', 200));
await sleep(30);
const noteMid = $('selNote').textContent;
ok('подпись меняется прямо во время тяги', /строка 3/.test(noteMid), noteMid);

w.dispatchEvent(pd('pointerup', 200));
await sleep(900);

const after = await srvStarts();
ok('строка уехала вправо', after[2] > before[2] + 0.5,
   `было ${before[2].toFixed(2)} стало ${after[2].toFixed(2)}`);
ok('соседи не тронуты',
   Math.abs(after[0]-before[0])<1e-6 && Math.abs(after[1]-before[1])<1e-6,
   `${after[0]} / ${after[1]}`);
ok('сдвиг сохранился на сервере, а не только в окне', true);

// --- тащим обратно влево -------------------------------------------------
console.log('\n--- тянем обратно влево ---');
const B2 = [...doc.querySelectorAll('.blk')][2];
B2.dispatchEvent(pd('pointerdown', 200));
w.dispatchEvent(pd('pointermove', 100));
w.dispatchEvent(pd('pointerup', 100));
await sleep(900);
const back = await srvStarts();
ok('вернулась примерно на место', Math.abs(back[2]-before[2]) < 0.6,
   `было ${before[2].toFixed(2)} стало ${back[2].toFixed(2)}`);

// --- правый край растягивает длительность --------------------------------
console.log('\n--- тянем за правый край ---');
const grip = doc.querySelector('.blk [data-grip="right"]');
ok('у блока есть ручка конца строки', !!grip);
ok('и ручка начала строки тоже', !!doc.querySelector('.blk [data-grip="left"]'));
if (grip){
  const srvEnds = async () => (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json()).lines.map(l=>l.end);
  const e0 = (await srvEnds())[+grip.closest('.blk').dataset.i];
  const idx = +grip.closest('.blk').dataset.i;
  grip.dispatchEvent(pd('pointerdown', 300));
  w.dispatchEvent(pd('pointermove', 360));
  w.dispatchEvent(pd('pointerup', 360));
  await sleep(900);
  const e1 = (await srvEnds())[idx];
  ok('конец строки сдвинулся', Math.abs(e1-e0) > 0.3, `было ${e0} стало ${e1}`);
}

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,3).join(' | '));

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
