// Vocal volume and how sturdy the track is: pauses, seeks, browser refusals.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__vt=0; w.__frames=[]; w.__inst=[]; w.__rejectPlay=false;
    w.requestAnimationFrame = cb => w.__frames.push(cb);
    w.cancelAnimationFrame = () => {};
    class FA{
      constructor(){ this.rates=[]; this._h={}; this._t=0; this._mark=0; this.paused=true;
        this.seeking=false; this.volume=1; this.duration=26; this.playRejects=0;
        this.playbackRate=1; w.__inst.push(this); setTimeout(()=>this._fire('loadedmetadata'),0); }
      get currentTime(){ if(!this.paused) this._t += (w.__vt-this._mark)*this.playbackRate;
        this._mark=w.__vt; return this._t; }
      set currentTime(v){ this._t=v; this._mark=w.__vt; this._fire('seeked'); }
      set playbackRate(v){ this._pr=v; this.rates.push(v); }
      get playbackRate(){ return this._pr===undefined?1:this._pr; }
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){this._h[n]=(this._h[n]||[]).filter(x=>x!==f);}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){
        // the second track sometimes refuses to start — browsers do that
        // when the previous start was cut off by a pause or a seek
        if (w.__rejectPlay && w.__inst.indexOf(this)===1){
          this.playRejects++; return Promise.reject(new Error('AbortError'));
        }
        this.paused=false; this._mark=w.__vt; this._fire('play'); return Promise.resolve();
      }
      pause(){ this.currentTime; this.paused=true; this._fire('pause'); }
    }
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.Element.prototype.setPointerCapture=function(){};
    w.Element.prototype.getBoundingClientRect=function(){
      return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const [master, voice] = w.__inst;
async function run(sec){ const f=Math.round(sec*60);
  for(let i=0;i<f;i++){ w.__vt+=1/60; w.__frames.splice(0).forEach(cb=>{try{cb(w.__vt*1000);}catch(e){w.__errs.push(String(e));}});
    if(i%20===0) await sleep(0); } await sleep(10); }
const setVol = pct => { $('rVocal').value=String(pct); $('rVocal').dispatchEvent(new w.Event('input')); };

console.log('--- the volume survives a pause ---');
setVol(60);
ok('the level was applied', Math.abs(voice.volume-0.6)<1e-9, 'volume='+voice.volume);
$('btnPlay').click(); await run(2);
ok('it plays at the set volume', !voice.paused && Math.abs(voice.volume-0.6)<1e-9);
$('btnPlay').click(); await sleep(20);
ok('the pause stopped both', master.paused && voice.paused);
ok('the volume survived the pause', Math.abs(voice.volume-0.6)<1e-9, 'volume='+voice.volume);
$('btnPlay').click(); await run(2);
ok('after resuming, the vocal plays', !voice.paused);
ok('and the volume is the same', Math.abs(voice.volume-0.6)<1e-9, 'volume='+voice.volume);

console.log('\n--- the browser refuses to start the vocal ---');
$('btnPlay').click(); await sleep(20);        // pause
w.__rejectPlay = true;
$('btnPlay').click(); await sleep(20);        // start: the vocal will be refused
ok('the vocal really did not start', voice.paused && voice.playRejects>0,
   'refusals '+voice.playRejects);
await run(1);
w.__rejectPlay = false;                       // the refusal is over
await sleep(350);                             // the throttling window for the revival
await run(1.5);
ok('the player brought the vocal track up itself', !voice.paused);
ok('and the volume was not lost', Math.abs(voice.volume-0.6)<1e-9, 'volume='+voice.volume);
ok('the tracks did not drift apart', Math.abs(master.currentTime-voice.currentTime)<0.1,
   `delta ${Math.abs(master.currentTime-voice.currentTime).toFixed(3)}s`);

console.log('\n--- the volume survives a seek ---');
setVol(35);
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
await sleep(60);   // the restart timer (25 ms of real time) needs time to fire
await run(1.5);
ok('after the seek both play', !master.paused && !voice.paused);
ok('the volume survived', Math.abs(voice.volume-0.35)<1e-9, 'volume='+voice.volume);

console.log('\n--- pausing during a seek ---');
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
$('btnPlay').click();                          // hit pause while the seek is running
await sleep(60);   // let the timer fire and make sure the pause held
await run(2);
ok('a seek does not cancel a pause', master.paused && voice.paused,
   `master=${master.paused} voice=${voice.paused}`);
ok('the vocal is not resurrected while paused', voice.paused);

console.log('\n--- the slider works while paused ---');
setVol(80);
ok('the level was taken while paused', Math.abs(voice.volume-0.8)<1e-9, 'volume='+voice.volume);
$('btnPlay').click(); await run(1.5);
ok('and stayed the same after starting', Math.abs(voice.volume-0.8)<1e-9 && !voice.paused);

console.log('\n--- the M key ---');
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true})); await run(0.5);
ok('M mutes the vocal', voice.volume===0, 'volume='+voice.volume);
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true})); await run(0.5);
ok('M brings the vocal back', voice.volume===1, 'volume='+voice.volume);
ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
