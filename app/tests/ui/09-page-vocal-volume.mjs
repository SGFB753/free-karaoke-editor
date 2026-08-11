// Громкость вокала и живучесть дорожки: паузы, перемотки, отказы браузера.
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
        // вторая дорожка иногда отказывается стартовать — так делают браузеры,
        // когда предыдущий запуск прервали паузой или перемоткой
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

console.log('--- громкость держится через паузу ---');
setVol(60);
ok('уровень применился', Math.abs(voice.volume-0.6)<1e-9, 'volume='+voice.volume);
$('btnPlay').click(); await run(2);
ok('играет с заданной громкостью', !voice.paused && Math.abs(voice.volume-0.6)<1e-9);
$('btnPlay').click(); await sleep(20);
ok('пауза остановила обе', master.paused && voice.paused);
ok('громкость после паузы сохранилась', Math.abs(voice.volume-0.6)<1e-9, 'volume='+voice.volume);
$('btnPlay').click(); await run(2);
ok('после возобновления вокал играет', !voice.paused);
ok('и громкость та же', Math.abs(voice.volume-0.6)<1e-9, 'volume='+voice.volume);

console.log('\n--- браузер отказывается запускать вокал ---');
$('btnPlay').click(); await sleep(20);        // пауза
w.__rejectPlay = true;
$('btnPlay').click(); await sleep(20);        // запуск: вокал будет отклонён
ok('вокал действительно не стартовал', voice.paused && voice.playRejects>0,
   'отказов '+voice.playRejects);
await run(1);
w.__rejectPlay = false;                       // отказ прошёл
await sleep(350);                             // окно троттлинга воскрешения
await run(1.5);
ok('плеер сам поднял вокальную дорожку', !voice.paused);
ok('громкость при этом не потерялась', Math.abs(voice.volume-0.6)<1e-9, 'volume='+voice.volume);
ok('дорожки не разъехались', Math.abs(master.currentTime-voice.currentTime)<0.1,
   `дельта ${Math.abs(master.currentTime-voice.currentTime).toFixed(3)}с`);

console.log('\n--- громкость держится через перемотку ---');
setVol(35);
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
await sleep(60);   // таймеру перезапуска (25мс реального времени) надо успеть сработать
await run(1.5);
ok('после перемотки играют обе', !master.paused && !voice.paused);
ok('громкость сохранилась', Math.abs(voice.volume-0.35)<1e-9, 'volume='+voice.volume);

console.log('\n--- пауза во время перемотки ---');
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
$('btnPlay').click();                          // жмём паузу, пока перемотка идёт
await sleep(60);   // дать таймеру сработать и убедиться, что пауза устояла
await run(2);
ok('пауза не отменяется перемоткой', master.paused && voice.paused,
   `master=${master.paused} voice=${voice.paused}`);
ok('вокал не воскрешается на паузе', voice.paused);

console.log('\n--- ползунок работает на паузе ---');
setVol(80);
ok('уровень принят на паузе', Math.abs(voice.volume-0.8)<1e-9, 'volume='+voice.volume);
$('btnPlay').click(); await run(1.5);
ok('после запуска он же и остался', Math.abs(voice.volume-0.8)<1e-9 && !voice.paused);

console.log('\n--- клавиша M ---');
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true})); await run(0.5);
ok('M глушит вокал', voice.volume===0, 'volume='+voice.volume);
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true})); await run(0.5);
ok('M возвращает вокал', voice.volume===1, 'volume='+voice.volume);
ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nПРОВАЛЕНО: ${fail}`:'\nВсе проверки пройдены');
process.exit(fail?1:0);
