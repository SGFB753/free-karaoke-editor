// Picking the language before building. The window used to send Russian in
// silence, and in another language the Whisper timing fell apart unexplained.
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
        sent = JSON.parse(opts.body);          // we stop short of the actual build
        return Promise.resolve({json: async () => ({job: "none"})});
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

console.log('--- the server and the window know the same languages ---');
ok('the server returns the list of languages', st.caps.langs && Object.keys(st.caps.langs).length > 5,
   Object.keys(st.caps.langs || {}).join(' '));
ok('the list offers detection from the text', 'auto' in (st.caps.langs || {}));

$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
const opts = [...$('selLang').options];
ok('the language list is filled in', opts.length === Object.keys(st.caps.langs).length,
   opts.length + ' against ' + Object.keys(st.caps.langs).length);
ok('the default is to detect from the text', $('selLang').value === 'auto', $('selLang').value);
ok('the names are human, not codes',
   opts.some(o => o.value === 'ru' && /русск/i.test(o.textContent)),
   (opts.find(o=>o.value==='ru')||{}).textContent);

console.log('\n--- the hint says what will happen with the language ---');
$('selAlign').value = 'auto';
$('selLang').value = 'auto';
$('selLang').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('on “auto” it promises to name the language in the log',
   /определится по тексту/.test($('modelNote').textContent), $('modelNote').textContent.slice(-60));
$('selLang').value = 'en';
$('selLang').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('on a manual pick it names the language',
   /Язык задан вручную/.test($('modelNote').textContent), $('modelNote').textContent.slice(-50));

console.log('\n--- the choice reaches the server and is remembered ---');
$('inAudio').value = process.env.KARAOKE_SONG;
$('inLyrics').value = process.env.KARAOKE_TEXT;
$('btnBuild').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(300);
ok('the language was sent along with the rest', sent && sent.lang === 'en',
   sent ? JSON.stringify(sent.lang) : 'nothing was sent');
ok('the other settings were not lost',
   sent && sent.model && typeof sent.separate === 'boolean' && sent.align,
   sent ? `${sent.align}/${sent.model}/${sent.separate}` : '');
let stored = null;
try { stored = w.localStorage.getItem('karaoke.lang'); } catch(e){}
ok('the choice is remembered for next time', stored === 'en', String(stored));

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
