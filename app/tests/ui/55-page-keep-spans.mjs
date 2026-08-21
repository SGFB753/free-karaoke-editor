// A stretch with no words in it: a vocalise, a scream, a hummed intro. There is
// nothing to sing there, so the finished page must leave the original voice in
// — muting it puts a hole in the song exactly where it is loudest.
const { JSDOM } = await import('jsdom');
import fs from 'fs';

const page = process.env.KARAOKE_PAGE_KEEPS;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };

const html = fs.readFileSync(page, 'utf8');
const payload = JSON.parse(html.match(
  /<script id="payload" type="application\/json">(.*?)<\/script>/s)[1]
  .replace(/\\u003c/g, '<').replace(/\\u003e/g, '>').replace(/\\u0026/g, '&'));

console.log('--- the page carries the stretches ---');
const spans = payload.data.keepSpans || [];
ok('there is a stretch in it', spans.length === 1, JSON.stringify(spans));
ok('and it is the one that was marked',
   Math.abs(spans[0][0] - 14) < 0.05 && Math.abs(spans[0][1] - 16.5) < 0.05,
   JSON.stringify(spans[0]));

console.log('\n--- and the player leaves the original voice on it ---');
// Driven like the other page suites: a fake audio pair and hand-turned frames.
const dom = new JSDOM(html, { runScripts:'dangerously', pretendToBeVisual:true,
  url:'https://local.test/',
  beforeParse(w){
    w.__vt = 0; w.__frames = []; w.__inst = []; w.__errs = [];
    w.requestAnimationFrame = cb => w.__frames.push(cb);
    w.cancelAnimationFrame = () => {};
    class FA{
      constructor(){ this._h={}; this._t=0; this._mark=0; this.paused=true;
        this.volume=1; this.duration=26; this.playbackRate=1;
        w.__inst.push(this); setTimeout(()=>this._fire('loadedmetadata'),0); }
      get currentTime(){ if(!this.paused) this._t += (w.__vt-this._mark)*this.playbackRate;
        this._mark=w.__vt; return this._t; }
      set currentTime(v){ this._t=v; this._mark=w.__vt; this._fire('seeked'); }
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){this._h[n]=(this._h[n]||[]).filter(x=>x!==f);}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){ this.paused=false; this._mark=w.__vt; this._fire('play');
              return Promise.resolve(); }
      pause(){ this.currentTime; this.paused=true; this._fire('pause'); }
    }
    w.Audio = FA;
    w.onerror = m => w.__errs.push(String(m));
    w.Element.prototype.setPointerCapture = function(){};
    w.Element.prototype.getBoundingClientRect = function(){
      return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r => setTimeout(r, ms));
await sleep(250);
const [master, voice] = w.__inst;
async function run(sec){
  const f = Math.round(sec * 60);
  for (let i = 0; i < f; i++){
    w.__vt += 1 / 60;
    w.__frames.splice(0).forEach(cb => { try { cb(w.__vt * 1000); } catch(e){ w.__errs.push(String(e)); } });
    if (i % 20 === 0) await sleep(0);
  }
  await sleep(10);
}
ok('the page has both tracks', !!voice, w.__inst.length + ' players');

// the voice is turned right down: a person singing along wants the backing only
$('rVocal').value = '0';
$('rVocal').dispatchEvent(new w.Event('input'));
$('btnPlay').click();
await run(0.3);

async function at(t){
  master.currentTime = t;
  if (voice) voice.currentTime = t;
  await run(0.5);
  return voice ? voice.volume : -1;
}
const before = await at(11.0);
ok('before the marked stretch the original is silenced', before < 0.05, before);
const inside = await at(15.0);
ok('inside it the original is heard in full', inside > 0.95, inside);
ok('and the page says so about itself', doc.body.classList.contains('keeping'));
const after = await at(19.0);
ok('after it, silenced again', after < 0.05, after);
ok('no errors in the page', w.__errs.length === 0, w.__errs[0] || '');

console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
