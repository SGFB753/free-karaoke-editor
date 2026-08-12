// The “this line and all the rest” shift — the cure for drift after a solo.
// Checked through the public interface of the page: the target caption, the
// .json export and saving the page. No internal player variables are touched.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;this.seeking=false;
      this.playbackRate=1;this._t=0;this._h={};w.__inst.push(this);setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){this._h[n]=(this._h[n]||[]).filter(x=>x!==f);}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
let saved=null, savedName=null;
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){ savedName=this.download; };
await sleep(200);

const fail=m=>{console.log('FAILED: '+m);process.exit(1);};
// the only way to see the timings from outside is to ask the page to export them
const starts=async()=>{ saved=null; $('btnSaveJson').click(); await sleep(20);
                        if(!saved) fail('the .json export returned nothing');
                        return JSON.parse(saved).lines.map(l=>l.start); };

const before = await starts();
if (before.length < 5) fail('the test page has too few lines');

const m=w.__inst[0];
$('btnEdit').click(); await sleep(40);
m.currentTime=9; await sleep(80);

// the page itself says which line is being edited: “N. [time] text”
const targetNo = () => {
  const mm = /^(\d+)\./.exec($('tgtName').textContent.trim());
  if (!mm) fail('the target caption shows no line number: ' + $('tgtName').textContent);
  return +mm[1] - 1;
};
const T = targetNo();
if (T < 0 || T >= before.length) fail('the target is outside the list of lines: ' + T);
console.log('  OK   the target is named and underlined (line ' + (T+1) + ')');
if (!doc.querySelectorAll('.ln.tgt').length) fail('the target line is not underlined on stage');

// ◀ ▶ move the target by exactly one line and stop at the edge
$('btnTgtNext').click(); await sleep(20);
if (targetNo() !== T+1) fail('▶ did not move the target to the next line');
$('btnTgtPrev').click(); await sleep(20);
if (targetNo() !== T) fail('◀ did not bring the target back');
console.log('  OK   ◀ ▶ move the target one line at a time');

// shift the target and all the rest to the current second
$('chkRest').checked = true;
$('btnHere').click(); await sleep(60);

const after = await starts();
const d = before[T] - 9;
if (Math.abs(after[T]-9) > 0.02) fail(`the target line did not land on 9s: ${after[T]}`);
for (let i=0;i<T;i++)
  if (Math.abs(after[i]-before[i]) > 0.002) fail(`line ${i+1} before the target moved`);
for (let i=T+1;i<after.length;i++)
  if (Math.abs((after[i]+d)-before[i]) > 0.02) fail(`line ${i+1} moved by a different amount`);
console.log('  OK   the line and the tail moved, the earlier ones did not');

for (let i=1;i<after.length;i++)
  if (after[i] < after[i-1] - 0.002) fail(`the order of lines is broken at line ${i+1}`);
console.log('  OK   the line order is intact');

$('btnUndo').click(); await sleep(60);
const undone = await starts();
for (let i=0;i<undone.length;i++)
  if (Math.abs(undone[i]-before[i]) > 0.002) fail(`Undo did not bring line ${i+1} back`);
console.log('  OK   Undo restored the original timing');

// repeat the edit and save the page — the timings must reach the file
$('btnHere').click(); await sleep(60);
const fixed = await starts();
saved=null; $('btnSavePage').click(); await sleep(60);
if (!saved) fail('the page was not saved');
if (!/\.html$/.test(savedName||'')) fail('saved not as .html: ' + savedName);
const pm = saved.match(/id="payload"[^>]*>([\s\S]*?)<\/script>/);
if (!pm) fail('the saved page carries no data');
const P2 = JSON.parse(pm[1].replace(/\\u003c/g,'<').replace(/\\u003e/g,'>').replace(/\\u0026/g,'&'));
if (!P2.edited) fail('the saved page is not marked as edited — the video would take the machine timings');
const reloaded = P2.data.lines.map(l=>l.start);
if (reloaded.length !== fixed.length) fail('the saved page has a different number of lines');
for (let i=0;i<reloaded.length;i++)
  if (Math.abs(reloaded[i]-fixed[i]) > 0.02) fail(`saved line ${i+1} does not match`);
console.log('  OK   the edits are baked into the saved page (' +
            (saved.length/1024/1024).toFixed(1) + ' MB)');

if (w.__errs.length) fail('JS errors: ' + w.__errs.slice(0,2).join('; '));
console.log('  OK   no JS errors');


console.log('\nAll checks passed');
process.exit(0);
