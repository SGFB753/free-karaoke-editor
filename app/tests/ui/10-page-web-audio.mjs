// Web Audio: один тактовый генератор на обе дорожки.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__now = 0;                       // часы AudioContext, секунды
    w.__started = [];                  // что и когда запускали
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

ok('движок — Web Audio, элементы не создавались', w.__inst.length===0, 'элементов '+w.__inst.length);
ok('длительность взята из декодированного звука', $('tDur').textContent==='0:26', $('tDur').textContent);
ok('бейджа больше нет', !$('mBadge'));
ok('заголовок на месте', $('mTitle').textContent==='Тестовая песня');

console.log('\n--- запуск ---');
$('btnPlay').click(); await sleep(60);
ok('запущены обе дорожки', w.__started.length===2, 'запусков '+w.__started.length);
const [a,b] = w.__started.slice(-2);
ok('обе стартуют в один и тот же момент', a.at===b.at, `${a.at} и ${b.at}`);
ok('и с одинаковой позиции', a.off===b.off, `${a.off} и ${b.off}`);

await tick(5);
ok('время идёт', Math.abs(+$('tCur').textContent.split(':')[1] - 5) <= 1, $('tCur').textContent);

console.log('\n--- громкость ---');
$('rVocal').value='50'; $('rVocal').dispatchEvent(new w.Event('input'));
await sleep(30);
const g = w.__started[1].src;  // источник вокала подключён ко второму gain
ok('регулятор голоса меняет усиление', $('vVocal').textContent==='50%');
$('btnPlay').click(); await sleep(30);       // пауза
$('btnPlay').click(); await sleep(60);       // снова
ok('после паузы уровень сохранился', $('vVocal').textContent==='50%');
const pair = w.__started.slice(-2);
ok('после паузы обе снова стартуют вместе',
   pair[0].at===pair[1].at && pair[0].off===pair[1].off,
   `at ${pair[0].at}=${pair[1].at}, off ${pair[0].off.toFixed(2)}=${pair[1].off.toFixed(2)}`);
ok('позиция после паузы не потерялась', pair[0].off > 4.5, 'off='+pair[0].off.toFixed(2));

console.log('\n--- перемотка ---');
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
await sleep(60);
const s2 = w.__started.slice(-2);
ok('перемотка стартует обе в один момент', s2[0].at===s2[1].at && s2[0].off===s2[1].off,
   `off ${s2[0].off.toFixed(2)}`);
ok('перемотка сдвинула на +5 с', Math.abs(s2[0].off - (pair[0].off+5)) < 0.3,
   `${pair[0].off.toFixed(2)} → ${s2[0].off.toFixed(2)}`);

console.log('\n--- пауза во время перемотки ---');
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
$('btnPlay').click(); await sleep(60);
const cnt = w.__started.length;
await tick(2);
ok('после паузы ничего не запускается', w.__started.length===cnt);
ok('иконка показывает паузу', $('icPlay').style.display==='');

console.log('\n--- расхождения быть не может ---');
$('btnPlay').click(); await sleep(60);
for (let i=0;i<12;i++){ await tick(1); }
const last = w.__started.slice(-2);
ok('обе дорожки живут от одного момента старта', last[0].at===last[1].at);
ok('и от одного смещения', last[0].off===last[1].off);
ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nПРОВАЛЕНО: ${fail}`:'\nВсе проверки пройдены');
process.exit(fail?1:0);
