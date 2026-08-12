// The file browser must open where we were last time. Otherwise hunting for
// the same lyrics across the whole disk every time is torture.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();
import path from 'path';

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.confirm = () => true;
    w.fetch = (p2, o) => fetch(typeof p2==="string" && p2.startsWith("/") ? API+p2 : p2, o);
    w.AudioContext = class { constructor(){ this.state="running"; this.destination={}; }
      createGain(){ return {gain:{value:1, setTargetAtTime(v){this.value=v;}}, connect(){}}; }
      createBufferSource(){ return {connect(){},start(){},stop(){}}; }
      decodeAudioData(){ return Promise.resolve({duration:26}); } resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () =>
      ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
    Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{get(){return 900;}});
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r=>setTimeout(r,ms));
w.eval(js);
await sleep(900);

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const here = path.dirname(process.env.KARAOKE_SONG);   // where the test files live
const close = () => $('brCancel').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));

console.log('--- walking the folders, the window remembers it ---');
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
doc.querySelector('[data-pick="audio"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(800);
ok('the browser opened', !$('browser').classList.contains('hide'));
const first = $('brPath').value;
ok('some folder is shown', !!first, first);

// go one level up — with the real button, the way a person would
$('brUp').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(800);
const upper = $('brPath').value;
ok('we went one level up', upper !== first, `${first} → ${upper}`);
close();

console.log('\n--- closed and opened again ---');
doc.querySelector('[data-pick="audio"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(800);
ok('it opened where we left off, not from scratch',
   $('brPath').value === upper, `${$('brPath').value} against ${upper}`);
close();

console.log('\n--- the lyrics have their own memory, not shared with audio ---');
let stored = {};
try {
  stored = {audio: w.localStorage.getItem('karaoke.dir.audio'),
            text: w.localStorage.getItem('karaoke.dir.text')};
} catch(e){}
ok('the audio folder is remembered', stored.audio === upper, String(stored.audio));
doc.querySelector('[data-pick="lyrics"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(700);
ok('the lyrics browser opened', !$('browser').classList.contains('hide'));
close();
try { stored.text = w.localStorage.getItem('karaoke.dir.text'); } catch(e){}
ok('the lyrics folder is remembered separately', !!stored.text, String(stored.text));

console.log('\n--- in the editor it is not from scratch either ---');
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1500);
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(700);
ok('the browser opened from the editor', !$('browser').classList.contains('hide'));
ok('and not in a void but in the remembered folder',
   $('brPath').value && $('brPath').value !== '/',
   $('brPath').value);
close();

console.log('\n--- the remembered folder is gone ---');
try { w.localStorage.setItem('karaoke.dir.text', '/no/such/folder/vanished'); } catch(e){}
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(900);
ok('the browser still opened instead of crashing',
   !$('browser').classList.contains('hide') && !!$('brPath').value,
   $('brPath').value);
ok('and it shows a folder that exists', /^\//.test($('brPath').value) &&
   !$('brPath').value.includes('vanished'), $('brPath').value);
ok('there was no error about “the project”', !w.__errs.some(e => /проект/i.test(e)),
   w.__errs.slice(0,2).join(' | '));
close();

console.log('\n--- no memory: we take the folder of the song sources ---');
try { w.localStorage.removeItem('karaoke.dir.text'); } catch(e){}
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(700);
const p2 = $('brPath').value;
ok('it opened next to the source lyrics of the song',
   p2 && (p2 === here || here.startsWith(p2) || p2.startsWith(here)),
   `${p2} with the sources in ${here}`);
close();

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
