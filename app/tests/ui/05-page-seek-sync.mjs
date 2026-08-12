const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{
      constructor(){ this.paused=true; this.volume=1; this.duration=26; this.seeking=false;
        this.playbackRate=1; this.seekCount=0;
        this._t=0; this._h={}; w.__inst.push(this); setTimeout(()=>this._fire('loadedmetadata'),0); }
      get currentTime(){ return this._t; }
      set currentTime(v){                     // seeking is async, as in a browser
        this.seeking=true; this.seekCount++; const d=w.__seekDelay[w.__inst.indexOf(this)]||10;
        setTimeout(()=>{ this._t=v; this.seeking=false; this._fire('seeked'); }, d);
      }
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){ this._h[n]=(this._h[n]||[]).filter(x=>x!==f); }
      _fire(n){ (this._h[n]||[]).slice().forEach(f=>f()); }
      play(){ this.paused=false; this._fire('play'); return Promise.resolve(); }
      pause(){ this.paused=true; this._fire('pause'); }
    }
    w.Audio=FA; w.__seekDelay=[10,120];
    w.Element.prototype.setPointerCapture=function(){};
    w.Element.prototype.getBoundingClientRect=function(){return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0};};
    w.Element.prototype.releasePointerCapture=function(){};      // the second track seeks slower
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
let saved=null; w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const [master, voice] = w.__inst;

console.log('--- seeking with two tracks ---');
$('btnPlay').click(); await sleep(30);
ok('both are playing', !master.paused && !voice.paused);
$('seek').dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true, clientX:400}));
await sleep(40);
ok('during a seek both are stopped (no overlap)', master.paused && voice.paused,
   `master=${master.paused} voice=${voice.paused}`);
w.dispatchEvent(new w.MouseEvent('pointerup',{bubbles:true, clientX:400}));
await sleep(400);
ok('after the seek both play again', !master.paused && !voice.paused);
ok('the tracks landed on the same spot', Math.abs(master.currentTime-voice.currentTime)<0.001,
   `delta=${Math.abs(master.currentTime-voice.currentTime).toFixed(3)}`);

console.log('--- quick seeks in a row ---');
for (let i=0;i<4;i++){ seekBy(); await sleep(25); }
function seekBy(){ doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})); }
await sleep(400);
ok('after a burst of seeks the tracks are in sync', Math.abs(master.currentTime-voice.currentTime)<0.001,
   `delta=${Math.abs(master.currentTime-voice.currentTime).toFixed(3)}`);
ok('and both are playing', !master.paused && !voice.paused);

console.log('--- the mouse was released outside the bar ---');
$('seek').dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true, clientX:250}));
await sleep(40);
w.dispatchEvent(new w.MouseEvent('pointerup',{bubbles:true, clientX:250}));
await sleep(400);
ok('released outside the bar, the music plays', !master.paused && !voice.paused);

console.log('--- the vocal must not disappear ---');
master.currentTime=5; await sleep(300);
const seeksBefore = voice.seekCount;
// simulate a small drift between the tracks, the kind that follows a seek
voice._t = master.currentTime - 0.15;
await sleep(120);
ok('a small drift is NOT fixed by seeking (the vocal keeps sounding)',
   voice.seekCount===seeksBefore, `vocal seeks: ${voice.seekCount-seeksBefore}`);
ok('it is corrected by playback rate instead', voice.playbackRate>1 && voice.playbackRate<=1.02,
   'playbackRate='+voice.playbackRate.toFixed(3));
voice._t = master.currentTime;
await sleep(120);
ok('once aligned, the rate goes back to normal', voice.playbackRate===1);
voice._t = master.currentTime - 1.2;         // drifted for real
await sleep(120);
ok('a large drift is fixed by seeking after all', voice.seekCount>seeksBefore);

console.log('--- dragging the slider ---');
$('seek').dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true, clientX:200}));
await sleep(60);
$('seek').dispatchEvent(new w.MouseEvent('pointermove',{bubbles:true, clientX:300}));
await sleep(60);
ok('while dragging the audio is silent, no overlap', master.paused && voice.paused,
   `master=${master.paused} voice=${voice.paused}`);
$('seek').dispatchEvent(new w.MouseEvent('pointerup',{bubbles:true, clientX:300}));
await sleep(400);
ok('released — it plays again', !master.paused && !voice.paused);
ok('and the tracks are at the same spot', Math.abs(master.currentTime-voice.currentTime)<0.001);

console.log('--- a single precise edit ---');
master.currentTime=9; await sleep(200);
const lns=[...doc.querySelectorAll('.ln')];
const cur=()=>lns.findIndex(e=>e.classList.contains('cur'));
const i0=cur();
$('btnSaveJson').click(); const before=JSON.parse(saved).lines.map(l=>l.start);
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true}));
await sleep(40); $('btnSaveJson').click();
let after=JSON.parse(saved).lines.map(l=>l.start);
ok('] moves only the current line',
   Math.abs(after[i0]-before[i0]-0.05)<1e-6 && Math.abs(after[i0+1]-before[i0+1])<1e-6,
   `line ${i0+1}: ${before[i0].toFixed(2)}→${after[i0].toFixed(2)}, the next one untouched`);

$('chkRest').checked = true;
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true}));
await sleep(40); $('btnSaveJson').click();
after=JSON.parse(saved).lines.map(l=>l.start);
const restOk=after.every((v,k)=> k<i0 ? Math.abs(v-before[k])<1e-6
                                      : Math.abs(v-before[k]-(k===i0?0.10:0.05))<1e-6);
ok('with “and all after it” the whole tail moves', restOk,
   `${i0} lines before it unchanged, all the rest +0.05s`);
$('chkRest').checked = false;

master.currentTime=12.4; await sleep(200);
const j=cur();
$('btnHere').click(); await sleep(40); $('btnSaveJson').click();
const now=JSON.parse(saved).lines[j].start;
ok('“line starts here” puts it on the current second', Math.abs(now-12.4)<0.02,
   `start=${now.toFixed(2)}`);

$('btnUndo').click(); await sleep(30);
ok('undo works after the edits', true);
ok('no JS errors', w.__errs.length===0, w.__errs.join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
