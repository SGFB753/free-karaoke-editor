// Выбор языка перед сборкой. Раньше окно всегда молча отправляло русский,
// и на чужом языке разметка Whisper расползалась без всякого объяснения.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

let sent = null;
const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.fetch = (path, opts) => {
      if (typeof path === "string" && path.startsWith("/api/new")){
        sent = JSON.parse(opts.body);          // до сборки не доводим
        return Promise.resolve({json: async () => ({job: "нет"})});
      }
      return fetch(typeof path === "string" && path.startsWith("/") ? API + path : path, opts);
    };
    w.AudioContext = class { constructor(){ this.state="running"; this.destination={}; }
      createGain(){ return {gain:{value:1, setTargetAtTime(v){this.value=v;}}, connect(){}}; }
      createBufferSource(){ return {connect(){},start(){},stop(){}}; }
      decodeAudioData(){ return Promise.resolve({duration:1}); } resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () =>
      ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r=>setTimeout(r,ms));
w.eval(js);
await sleep(900);

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const st = await (await fetch(API+"/api/state")).json();

console.log('--- сервер и окно знают одни и те же языки ---');
ok('сервер отдаёт список языков', st.caps.langs && Object.keys(st.caps.langs).length > 5,
   Object.keys(st.caps.langs || {}).join(' '));
ok('в списке есть определение по тексту', 'auto' in (st.caps.langs || {}));

$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
const opts = [...$('selLang').options];
ok('список языков заполнен', opts.length === Object.keys(st.caps.langs).length,
   opts.length + ' против ' + Object.keys(st.caps.langs).length);
ok('по умолчанию — определить по тексту', $('selLang').value === 'auto', $('selLang').value);
ok('названия человеческие, а не коды',
   opts.some(o => o.value === 'ru' && /русск/i.test(o.textContent)),
   (opts.find(o=>o.value==='ru')||{}).textContent);

console.log('\n--- подсказка говорит, что будет с языком ---');
$('selAlign').value = 'auto';
$('selLang').value = 'auto';
$('selLang').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('при «авто» обещает назвать язык в логе',
   /определится по тексту/.test($('modelNote').textContent), $('modelNote').textContent.slice(-60));
$('selLang').value = 'en';
$('selLang').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('при ручном выборе называет язык',
   /Язык задан вручную/.test($('modelNote').textContent), $('modelNote').textContent.slice(-50));

console.log('\n--- выбор уходит на сервер и запоминается ---');
$('inAudio').value = process.env.KARAOKE_SONG;
$('inLyrics').value = process.env.KARAOKE_TEXT;
$('btnBuild').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(300);
ok('язык отправлен вместе с остальным', sent && sent.lang === 'en',
   sent ? JSON.stringify(sent.lang) : 'ничего не отправлено');
ok('остальные настройки не потерялись',
   sent && sent.model && typeof sent.separate === 'boolean' && sent.align,
   sent ? `${sent.align}/${sent.model}/${sent.separate}` : '');
let stored = null;
try { stored = w.localStorage.getItem('karaoke.lang'); } catch(e){}
ok('выбор запомнен на следующий раз', stored === 'en', String(stored));

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
