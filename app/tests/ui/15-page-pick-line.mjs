// Picking a line for editing explicitly.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_MIX, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[]; w.__errs=[];
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;this.seeking=false;
      this.playbackRate=1;this._t=0;this._h={};w.__inst.push(this);
      setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA; w.onerror=m=>w.__errs.push(String(m));
    w.Element.prototype.getBoundingClientRect=function(){
      return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
    w.Element.prototype.setPointerCapture=function(){};
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
let saved=null;
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const m=w.__inst[0];
const starts=()=>{ $('btnSaveJson').click(); return JSON.parse(saved).lines.map(l=>+l.start.toFixed(3)); };
const lns=()=>[...doc.querySelectorAll('.ln')];
const tgtIdx=()=>lns().findIndex(e=>e.classList.contains('tgt'));
const curIdx=()=>lns().findIndex(e=>e.classList.contains('cur'));

console.log('--- the target tag shows only while editing is open ---');
m.currentTime=9.0; await sleep(80);
ok('without the edit panel there is no editing class',
   !doc.body.classList.contains('editing'));
$('btnEdit').click(); await sleep(30);
ok('editing opened — the class appeared', doc.body.classList.contains('editing'));
$('btnEdit').click(); await sleep(30);
ok('closed — the class is gone', !doc.body.classList.contains('editing'));
$('btnEdit').click(); await sleep(30);

console.log('\n--- by default we edit the line that is HIGHLIGHTED ---');
m.currentTime=14.8; await sleep(80);      // the interlude after the 4th line
ok('line 4 is highlighted', curIdx()===3, 'lit '+(curIdx()+1));
ok('the edit target matches the highlighted line', tgtIdx()===3, 'target '+(tgtIdx()+1));
ok('the caption shows it', /^4\./.test($('tgtName').textContent), $('tgtName').textContent);

const base=starts();
$('btnHere').click(); await sleep(60);
const a1=starts();
ok('the highlighted line 4 is the one that moved', Math.abs(a1[3]-14.8)<0.05, `${base[3]} → ${a1[3]}`);
ok('the fifth was left alone', a1[4]===base[4]);

console.log('\n--- ▶ moves the target to the next line ---');
$('btnReset').click(); await sleep(60);
m.currentTime=14.8; await sleep(80);
$('btnTgtNext').click(); await sleep(30);
ok('the target went to line 5', tgtIdx()===4, 'target '+(tgtIdx()+1));
ok('the playback highlight did not move', curIdx()===3, 'lit '+(curIdx()+1));
ok('the caption updated', /^5\./.test($('tgtName').textContent), $('tgtName').textContent);
const b2=starts();
$('btnHere').click(); await sleep(60);
const a2=starts();
ok('line 5 moved, not line 4', Math.abs(a2[4]-14.8)<0.05 && a2[3]===b2[3],
   `4: ${b2[3]}→${a2[3]}, 5: ${b2[4]}→${a2[4]}`);

console.log('\n--- ◀ and the ends of the list ---');
$('btnTgtPrev').click(); $('btnTgtPrev').click(); await sleep(30);
ok('the target went two lines up', tgtIdx()===2, 'target '+(tgtIdx()+1));
const pinned = tgtIdx();
m.currentTime=2.5; await sleep(80);
ok('the chosen target holds even as the song moves on', tgtIdx()===pinned,
   `target ${tgtIdx()+1}, lit ${curIdx()+1}`);
$('btnUnpin').click(); await sleep(60);
ok('“not this one” hands the target back to the highlighted line', tgtIdx()===curIdx(),
   `target ${tgtIdx()+1}, lit ${curIdx()+1}`);
for (let i=0;i<9;i++) $('btnTgtPrev').click();
await sleep(30);
ok('we do not go past the first line', tgtIdx()===0, 'target '+(tgtIdx()+1));
for (let i=0;i<20;i++) $('btnTgtNext').click();
await sleep(30);
ok('nor past the last one', tgtIdx()===5, 'target '+(tgtIdx()+1));
ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
