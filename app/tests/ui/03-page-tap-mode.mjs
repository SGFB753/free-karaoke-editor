const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_MIX, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{ constructor(){this.currentTime=0;this.paused=true;this.volume=1;this.duration=26;
      this._h={};w.__inst.push(this);setTimeout(()=>this._fire('loadedmetadata'),0);}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} _fire(n){(this._h[n]||[]).forEach(f=>f());}
      play(){this.paused=false;this._fire('play');return Promise.resolve();} pause(){this.paused=true;this._fire('pause');}}
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
let saved=null;
w.Blob = class { constructor(p){ saved = String(p[0]); } };
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const master=w.__inst[0], lns=[...doc.querySelectorAll('.ln')];

console.log('--- editor: tapping the timing in ---');
$('btnTap').click();
ok('tap mode is on', doc.body.classList.contains('tapping'));
const space=()=>doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',bubbles:true}));
space(); await sleep(30);              // the first Space only starts the song
// mark the lines at 3, 7, 11, 15, 19, 23 s
for (const t of [3,7,11,15,19,23]) { master.currentTime=t; await sleep(20); space(); }
$('btnTap').click();
$('btnSaveJson').click();
const j = JSON.parse(saved);
const starts = j.lines.map(l=>+l.start.toFixed(2));
ok('the taps recorded 6 line starts', JSON.stringify(starts)===JSON.stringify([3,7,11,15,19,23]), starts.join(', '));
const w1 = j.lines[0].words;   // Раз(1) два(1) три(1) четыре(3) пять(1) = 7 syllables
ok('the words are laid out by syllable, not evenly',
   Math.abs(w1[3].d - 3*w1[0].d) < 0.02, 'four='+w1[3].d+'s, one='+w1[0].d+'s');
ok("the words fit inside the line's length",
   Math.abs((w1[4].t+w1[4].d) - j.lines[0].end) < 0.05);

console.log('--- shifting a line and undoing ---');
master.currentTime=8; await sleep(60);
const before = JSON.parse(JSON.stringify(lns.map(e=>e.className)));
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true}));
await sleep(40); $('btnSaveJson').click();
const after = JSON.parse(saved).lines[1].start;
ok('the line moved by +0.05 s with ]', Math.abs(after-7.05)<0.001, 'start='+after);
$('btnUndo').click(); $('btnSaveJson').click();
ok('undo brought the previous state back', Math.abs(JSON.parse(saved).lines[1].start-7)<0.001);

console.log('--- saving in the browser ---');
ok('the edits are written to localStorage', !!w.localStorage.getItem(Object.keys(w.localStorage).find(k=>k.startsWith('karaoke:'))||'x'));
$('btnReset').click(); $('btnSaveJson').click();
ok('reset restored the original timing', Math.abs(JSON.parse(saved).lines[0].start-2.02)<0.1,
   'start='+JSON.parse(saved).lines[0].start);
ok('no JS errors', w.__errs.length===0, w.__errs.join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
