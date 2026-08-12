// The kept original voice and the language switch on the finished page.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
import path from 'path';
import os from 'os';

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const sleep = ms => new Promise(r=>setTimeout(r,ms));

// We take a finished page with two tracks and mark a line in it as “the original
// sings” — that checks the real build, not made-up data.
const src = process.env.KARAOKE_PAGE_STEMS;
const raw = fs.readFileSync(src, 'utf8');
const mark = '<script id="payload" type="application/json">';
const a = raw.indexOf(mark) + mark.length, b = raw.indexOf('</scr'+'ipt>', a);
const data = JSON.parse(raw.slice(a,b).replace(/\\u003c/g,'<').replace(/\\u003e/g,'>')
                                      .replace(/\\u0026/g,'&'));
data.uiLang = "ru";
const L = data.data.lines;
L[2].keep = true;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'keep_'));
const page = path.join(tmp, 'p.html');
fs.writeFileSync(page, raw.slice(0,a) + JSON.stringify(data)
  .replace(/</g,'\\u003c').replace(/>/g,'\\u003e').replace(/&/g,'\\u0026')
  + raw.slice(b), 'utf8');

const mkDom = () => new JSDOM(fs.readFileSync(page,'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/keep',
  beforeParse(w){
    w.__errs=[]; w.__inst=[]; w.__now=0; w.__gains=[];
    w.onerror=m=>w.__errs.push(String(m));
    w.fetch = () => Promise.resolve({arrayBuffer: () => Promise.resolve(new ArrayBuffer(8))});
    w.AudioContext = class {
      constructor(){ this.state="running"; this.destination={}; }
      get currentTime(){ return w.__now; }
      createGain(){ const g = {gain:{value:1, setTargetAtTime(v){ this.value = v; }},
                               connect(){}}; w.__gains.push(g); return g; }
      createBufferSource(){ return {connect(){},start(){},stop(){},onended:null}; }
      decodeAudioData(bin, res){ const buf={duration:26.04}; res && res(buf);
        return Promise.resolve(buf); }
      resume(){} };
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26.04;
      this._t=0;this._h={};w.__inst.push(this);
      setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA;
  }});

const dom = mkDom();
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
await sleep(500);
const lns = () => [...doc.querySelectorAll('#scroll .ln')];

console.log('--- the line can be seen in advance ---');
ok('the line is marked as the original', lns()[2].classList.contains('keep'),
   [...lns()[2].classList].join(' '));
ok('it says on it that there is no need to sing',
   /поёт оригинал/.test(lns()[2].textContent), lns()[2].textContent.slice(-40));
ok('the others carry no such note', !/поёт оригинал/.test(lns()[0].textContent));

console.log('\n--- the voice comes back exactly on that span ---');
const vocalGain = () => {
  const g = w.__gains[1];
  return g ? g.gain.value : (w.__inst[1] ? w.__inst[1].volume : null);
};
ok('the tracks are separated (otherwise there is nothing to check)', w.__gains.length >= 2 || w.__inst.length >= 2,
   `gains=${w.__gains.length} el=${w.__inst.length}`);
// Playing for real: press the button and move the clock of the audio engine.
const goto = async t => { w.__now = t; await sleep(140); };
$("btnPlay").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
await goto(L[0].start + 0.2);
const before = vocalGain();
ok('outside the marked span the voice is muted', before === 0, String(before));
await goto(L[2].start + 0.3);
const during = vocalGain();
ok('on the marked span the voice sounds', during === 1, String(during));
await goto(L[3] ? L[3].start + 0.4 : L[2].end + 1.5);
await sleep(150);
const after = vocalGain();
ok('after the span the voice is removed again', after === 0, String(after));

console.log('\n--- the language switch ---');
ok('the language button is there', !!$("btnLang"));
ok('the page was built in Russian', /Голос/.test($("grpVocal").textContent),
   $("grpVocal").textContent.trim());
ok('the button offers English', $("btnLang").textContent.trim() === "EN",
   $("btnLang").textContent);
$("btnLang").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
ok('the labels turned English', /Voice/.test($("grpVocal").textContent),
   $("grpVocal").textContent.trim());
ok('the mark on the line is translated too', /original sings/.test(lns()[2].textContent),
   lns()[2].textContent.slice(-40));
ok('the button now offers Russian', $("btnLang").textContent.trim() === "RU");
ok('the language is written into the page attribute', doc.documentElement.lang === "en");

console.log('\n--- the choice is remembered ---');
// Every jsdom window has its own storage, a second load cannot check this —
// we look at the record the page takes the language from when it opens.
const keys = Object.keys(w.localStorage).filter(k => k.startsWith("karaoke-lang-"));
ok('the language choice was written to the page storage', keys.length === 1, keys.join(","));
ok('and it is English that was written', w.localStorage.getItem(keys[0]) === "en",
   String(w.localStorage.getItem(keys[0])));
ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
