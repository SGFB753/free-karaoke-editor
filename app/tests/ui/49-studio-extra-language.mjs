// A new window language is a kstudio/messages/<code>.json file, with no code edits.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
import path from 'path';

const API = process.env.KARAOKE_API;
const ROOT = process.env.KARAOKE_ROOT || process.cwd();
const sleep = ms => new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

// Drop in a “translation”: half the keys, so the English fallback is checked too.
const dir = path.join(ROOT, 'kstudio', 'messages');
const file = path.join(dir, 'xx.json');
fs.writeFileSync(file, JSON.stringify({
  appTitle: "Karaoke XX", addSong: "＋ Add XX", timeline: "Timeline XX",
  summary: "", check: "Check XX"
}, null, 2), 'utf8');

try {
  const st = await (await fetch(API + '/api/state')).json();
  ok('the server saw the new language', (st.uiLangs || []).includes('xx'),
     JSON.stringify(st.uiLangs));
  const msgs = await (await fetch(API + '/api/messages?lang=xx')).json();
  ok('and it serves the file itself', msgs.appTitle === 'Karaoke XX', JSON.stringify(msgs).slice(0,60));
  const bad = await fetch(API + '/api/messages?lang=../secret');
  ok('a path outside is not served', bad.status === 400, String(bad.status));
  const none = await (await fetch(API + '/api/messages?lang=zz')).json();
  ok('a missing language gives an empty answer', Object.keys(none).length === 0);

  const html = await (await fetch(API + "/")).text();
  const js   = await (await fetch(API + "/ui.js")).text();
  const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true, url: API + "/",
    beforeParse(w){
      w.__errs=[]; w.onerror=m=>w.__errs.push(String(m)); w.confirm=()=>true;
      w.fetch = (...a) => fetch(typeof a[0]==="string" && a[0].startsWith("/") ? API + a[0] : a[0], a[1]);
      w.__now=0;
      w.AudioContext = class { constructor(){ this.state="running"; this.destination={}; }
        get currentTime(){ return w.__now; }
        createGain(){ return {gain:{value:1, setTargetAtTime(v){this.value=v;}}, connect(){}}; }
        createBufferSource(){ return {connect(){},start(){},stop(){},onended:null}; }
        decodeAudioData(){ return Promise.resolve({duration:26.04}); } resume(){} };
      w.HTMLCanvasElement.prototype.getContext = () => ({ scale(){}, clearRect(){}, fillRect(){},
        beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
      w.Element.prototype.getBoundingClientRect = () => ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
      w.Element.prototype.setPointerCapture = function(){};
      Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{get(){return 900;}});
      Object.defineProperty(w.HTMLElement.prototype,'clientHeight',{get(){return 400;}});
    }});
  const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
  w.eval(js);
  await sleep(900);

  // The stand is up in Russian: the ring is en → ru → xx, so after ru comes xx.
  ok('the button offers the new language', $("btnLang").textContent.trim() === 'XX',
     $("btnLang").textContent);
  $("btnLang").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await sleep(600);
  ok('the title came from the file', /Karaoke XX/.test($("scrList").querySelector('h1').textContent),
     $("scrList").querySelector('h1').textContent);
  ok('the add button too', /Add XX/.test($("btnAdd").textContent), $("btnAdd").textContent);
  // An empty value and a missing key — we take English, not emptiness.
  doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await sleep(1400);
  const heads = [...doc.querySelectorAll('.side h3')].map(e => e.textContent.trim());
  ok('an empty translation falls back to English', heads.includes('Summary'), heads.join(' | '));
  ok('the translated key is in place', heads.includes('Check XX'), heads.join(' | '));
  ok('and keys missing from the file are not empty either',
     /Timeline XX/.test(doc.querySelector('.tlhead').textContent),
     doc.querySelector('.tlhead').textContent.slice(0,40));
  ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
} finally {
  fs.unlinkSync(file);
}
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
