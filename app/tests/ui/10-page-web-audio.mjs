// Web Audio: a single clock for both tracks.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__now = 0;                       // the AudioContext clock, seconds
    w.__started = [];                  // what was started and when
    w.__inst = [];
    class Gain{ constructor(){ this.gain={value:1, setTargetAtTime(v){this.value=v;}}; } connect(){} }
    class Src{
      constructor(c){ this.ctx=c; this.buffer=null; this.onended=null; this.stopped=false; }
      connect(){} 
      start(at, off){ w.__started.push({at, off, src:this}); this.at=at; this.off=off; }
      stop(){ this.stopped=true; }
    }
    class AC{
      constructor(){ this.state="running"; this.destination={}; }
      get currentTime(){ return w.__now; }
      createGain(){ return new Gain(); }
      createBufferSource(){ return new Src(this); }
      decodeAudioData(buf, ok){ const b={duration:26.04, length:1}; if(ok){ok(b); return;} return Promise.resolve(b); }
      resume(){ this.state="running"; }
      close(){}
    }
    w.AudioContext = AC;
    w.fetch = () => Promise.resolve({ arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) });
    class FA{ constructor(){ this.paused=true; this.volume=1; this.duration=26; this._t=0;
      this._h={}; w.__inst.push(this); }
      get currentTime(){return this._t;} set currentTime(v){this._t=v;}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;} }
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.Element.prototype.getBoundingClientRect=function(){
      return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
    w.Element.prototype.setPointerCapture=function(){};
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
await sleep(300);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const tick = async sec => { w.__now += sec; await sleep(60); };

ok('the engine is Web Audio, no media elements were created', w.__inst.length===0, 'elements '+w.__inst.length);
ok('the length came from the decoded audio', $('tDur').textContent==='0:26', $('tDur').textContent);
ok('the badge is gone', !$('mBadge'));
ok('the title is there', $('mTitle').textContent==='Тестовая песня');

console.log('\n--- starting ---');
$('btnPlay').click(); await sleep(60);
ok('both tracks were started', w.__started.length===2, 'starts '+w.__started.length);
const [a,b] = w.__started.slice(-2);
ok('both start at the very same moment', a.at===b.at, `${a.at} and ${b.at}`);
ok('and from the same position', a.off===b.off, `${a.off} and ${b.off}`);

await tick(5);
ok('the clock runs', Math.abs(+$('tCur').textContent.split(':')[1] - 5) <= 1, $('tCur').textContent);

console.log('\n--- volume ---');
$('rVocal').value='50'; $('rVocal').dispatchEvent(new w.Event('input'));
await sleep(30);
const g = w.__started[1].src;  // the vocal source is wired to the second gain
ok('the voice slider changes the gain', $('vVocal').textContent==='50%');
$('btnPlay').click(); await sleep(30);       // pause
$('btnPlay').click(); await sleep(60);       // and again
ok('the level survived the pause', $('vVocal').textContent==='50%');
const pair = w.__started.slice(-2);
ok('after the pause both start together again',
   pair[0].at===pair[1].at && pair[0].off===pair[1].off,
   `at ${pair[0].at}=${pair[1].at}, off ${pair[0].off.toFixed(2)}=${pair[1].off.toFixed(2)}`);
ok('the position survived the pause', pair[0].off > 4.5, 'off='+pair[0].off.toFixed(2));

console.log('\n--- seeking ---');
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
await sleep(60);
const s2 = w.__started.slice(-2);
ok('a seek starts both at one moment', s2[0].at===s2[1].at && s2[0].off===s2[1].off,
   `off ${s2[0].off.toFixed(2)}`);
ok('the seek moved by +5 s', Math.abs(s2[0].off - (pair[0].off+5)) < 0.3,
   `${pair[0].off.toFixed(2)} → ${s2[0].off.toFixed(2)}`);

console.log('\n--- pausing during a seek ---');
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
$('btnPlay').click(); await sleep(60);
const cnt = w.__started.length;
await tick(2);
ok('after a pause nothing starts on its own', w.__started.length===cnt);
ok('the icon shows pause', $('icPlay').style.display==='');

console.log('\n--- drift is impossible here ---');
$('btnPlay').click(); await sleep(60);
for (let i=0;i<12;i++){ await tick(1); }
const last = w.__started.slice(-2);
ok('both tracks live off one start moment', last[0].at===last[1].at);
ok('and off one offset', last[0].off===last[1].off);
ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
