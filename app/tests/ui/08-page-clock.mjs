// A simulation with real time running and frames under our control.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__vt = 0;              // the virtual clock, seconds
    w.__frames = [];
    w.requestAnimationFrame = cb => w.__frames.push(cb);
    w.cancelAnimationFrame = () => {};
    w.__inst = [];
    class FA{
      constructor(){ this.rates=[]; this._h={}; this._t=0; this._mark=0;
        this.paused=true; this.seeking=false; this.volume=1; this.duration=600;
        this.hardSeeks=0; this.playbackRate=1; w.__inst.push(this);
        setTimeout(()=>this._fire('loadedmetadata'),0); }
      get currentTime(){
        if(!this.paused) this._t += (w.__vt - this._mark) * this.playbackRate;
        this._mark = w.__vt; return this._t;
      }
      set currentTime(v){ this._t=v; this._mark=w.__vt; this.hardSeeks++; this._fire('seeked'); }
      set playbackRate(v){ this._pr=v; this.rates.push(v); }
      get playbackRate(){ return this._pr===undefined?1:this._pr; }
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){this._h[n]=(this._h[n]||[]).filter(x=>x!==f);}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){ this.paused=false; this._mark=w.__vt; this._fire('play'); return Promise.resolve(); }
      pause(){ this.currentTime; this.paused=true; this._fire('pause'); }
    }
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const [master, voice] = w.__inst;

// run N frames of 1/60 s of virtual time
async function run(seconds){
  const frames = Math.round(seconds*60);
  for (let i=0;i<frames;i++){
    w.__vt += 1/60;
    const q = w.__frames.splice(0);
    q.forEach(f=>{ try{ f(w.__vt*1000); }catch(e){ w.__errs.push(String(e)); } });
    if (i%20===0) await sleep(0);
  }
  await sleep(10);
}

$('btnPlay').click(); await sleep(20);
await run(10);
let d = Math.abs(master.currentTime - voice.currentTime);
ok('10 s of playback: the tracks run together', d < 0.05, `drift ${d.toFixed(3)}s`);
ok('the vocal rate stayed normal', voice.playbackRate === 1, 'rate='+voice.playbackRate);
ok('the vocal was never hard-seeked', voice.hardSeeks <= 1, 'count '+voice.hardSeeks);

console.log('\n--- the vocal fell behind by 0.2 s ---');
voice._t -= 0.2;
await run(6);
d = master.currentTime - voice.currentTime;
ok('the pull-up started and goes the right way', d > 0 && d < 0.2 && voice.playbackRate > 1,
   `left ${d.toFixed(3)}s, rate=${voice.playbackRate.toFixed(4)}`);
await run(20);                       // let it finish speaking
d = master.currentTime - voice.currentTime;
ok('the lag was taken up completely', Math.abs(d) < 0.025, `left ${d.toFixed(3)}s`);
ok('the rate went back to 1', voice.playbackRate === 1, 'rate='+voice.playbackRate);

console.log('\n--- the vocal ran ahead by 0.2 s ---');
voice._t += 0.2;
await run(26);
d = master.currentTime - voice.currentTime;
ok('the lead was taken up', Math.abs(d) < 0.05, `left ${d.toFixed(3)}s`);

console.log('\n--- a long 3-minute run ---');
const seeksBefore = voice.hardSeeks;
await run(180);
d = Math.abs(master.currentTime - voice.currentTime);
const rates = voice.rates;
const mn = Math.min(...rates), mx = Math.max(...rates);
ok('in 3 minutes the tracks did not drift apart', d < 0.06, `drift ${d.toFixed(3)}s`);
ok('the vocal rate stayed within ±2%', mn >= 0.98 && mx <= 1.02,
   `from ${mn.toFixed(3)} to ${mx.toFixed(3)}`);
ok('the vocal never sped up threefold or noticeably', mx < 1.05, 'max '+mx.toFixed(3));
ok('no hard seeks out of nowhere', voice.hardSeeks - seeksBefore === 0,
   'count '+(voice.hardSeeks-seeksBefore));
ok('the positions match on the absolute scale',
   Math.abs(master.currentTime - voice.currentTime) < 0.06,
   `master=${master.currentTime.toFixed(2)} voice=${voice.currentTime.toFixed(2)}`);
ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
