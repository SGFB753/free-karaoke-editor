// Симуляция с настоящим ходом времени и управляемыми кадрами.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__vt = 0;              // виртуальные часы, секунды
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

// прогнать N кадров по 1/60 секунды виртуального времени
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
ok('10 с игры: дорожки идут вместе', d < 0.05, `расхождение ${d.toFixed(3)}с`);
ok('скорость вокала осталась обычной', voice.playbackRate === 1, 'rate='+voice.playbackRate);
ok('жёстких перемоток вокала не было', voice.hardSeeks <= 1, 'их '+voice.hardSeeks);

console.log('\n--- вокал отстал на 0,2 с ---');
voice._t -= 0.2;
await run(6);
d = master.currentTime - voice.currentTime;
ok('подтяжка началась и идёт в нужную сторону', d > 0 && d < 0.2 && voice.playbackRate > 1,
   `осталось ${d.toFixed(3)}с, rate=${voice.playbackRate.toFixed(4)}`);
await run(20);                       // даём договорить до конца
d = master.currentTime - voice.currentTime;
ok('отставание выбрано полностью', Math.abs(d) < 0.025, `осталось ${d.toFixed(3)}с`);
ok('скорость вернулась к 1', voice.playbackRate === 1, 'rate='+voice.playbackRate);

console.log('\n--- вокал убежал вперёд на 0,2 с ---');
voice._t += 0.2;
await run(26);
d = master.currentTime - voice.currentTime;
ok('опережение выбрано', Math.abs(d) < 0.05, `осталось ${d.toFixed(3)}с`);

console.log('\n--- длинный прогон 3 минуты ---');
const seeksBefore = voice.hardSeeks;
await run(180);
d = Math.abs(master.currentTime - voice.currentTime);
const rates = voice.rates;
const mn = Math.min(...rates), mx = Math.max(...rates);
ok('за 3 минуты дорожки не разъехались', d < 0.06, `расхождение ${d.toFixed(3)}с`);
ok('скорость вокала не выходила за ±2%', mn >= 0.98 && mx <= 1.02,
   `от ${mn.toFixed(3)} до ${mx.toFixed(3)}`);
ok('вокал не ускорялся втрое и вообще заметно', mx < 1.05, 'максимум '+mx.toFixed(3));
ok('без жёстких перемоток на ровном месте', voice.hardSeeks - seeksBefore === 0,
   'их '+(voice.hardSeeks-seeksBefore));
ok('позиции совпали по абсолютной шкале',
   Math.abs(master.currentTime - voice.currentTime) < 0.06,
   `master=${master.currentTime.toFixed(2)} voice=${voice.currentTime.toFixed(2)}`);
ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
