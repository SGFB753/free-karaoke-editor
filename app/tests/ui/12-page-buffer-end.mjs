// Реалистичный мок Web Audio: BufferSource реально доигрывает свой буфер и сам
// стреляет 'ended', позволяет проверить рассинхрон длительностей на стыке.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const HTML = fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8');

function mk(durs){       // durs: [instrumentalDur, vocalsDur] в виртуальных секундах
  return new JSDOM(HTML, { runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
    beforeParse(w){
      w.__now = 0; w.__timers = []; w.__live = new Set(); w.__errs = [];
      class Gain{ constructor(){ this.gain={value:1, setTargetAtTime(v){this.value=v;}}; } connect(){} }
      class Src{
        constructor(){ this.buffer=null; this.onended=null; this.stopped=false; w.__live.add(this); }
        connect(){}
        start(at, off){
          this.startAt = at; this.off = off;
          const remain = this.buffer.duration - off;
          w.__timers.push({ fireAt: at + remain, src: this });
        }
        stop(){ this.stopped=true; w.__live.delete(this); w.__timers = w.__timers.filter(t=>t.src!==this); }
      }
      class AC{
        constructor(){ this.state="running"; this.destination={}; }
        get currentTime(){ return w.__now; }
        createGain(){ return new Gain(); }
        createBufferSource(){ return new Src(); }
        decodeAudioData(b, ok){ const buf={ duration: durs[bi++] }; if(ok){ok(buf);return;} return Promise.resolve(buf); }
        resume(){ this.state="running"; }
        close(){}
      }
      let bi = 0;
      w.AudioContext = AC;
      w.fetch = () => Promise.resolve({ arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) });
      w.onerror = m => w.__errs.push(String(m));
      w.Element.prototype.getBoundingClientRect=function(){
        return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
      w.Element.prototype.setPointerCapture=function(){};
      // продвижение виртуального времени: стреляем таймеры, чей момент настал
      w.__advance = sec => {
        w.__now += sec;
        const due = w.__timers.filter(t => t.fireAt <= w.__now);
        w.__timers = w.__timers.filter(t => t.fireAt > w.__now);
        due.forEach(t => { if (!t.src.stopped){ t.src.stopped=true; w.__live.delete(t.src);
          if (t.src.onended) t.src.onended(); } });
      };
    }});
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

console.log('--- вокал на 0,3 с длиннее минусовки ---');
{
  const d = mk([26.0, 26.3]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  $('btnPlay').click(); await sleep(30);
  ok('обе дорожки запущены', w.__live.size===2, 'живых '+w.__live.size);
  w.__advance(26.05);                       // минусовка (короче) закончилась
  await sleep(30);
  ok('на конце глушатся ОБЕ дорожки, а не только первая', w.__live.size===0,
     'осталось живых '+w.__live.size);
  ok('иконка вернулась к «играть»', $('icPlay').style.display==='');
  ok('ошибок JS нет', w.__errs.length===0, w.__errs.join(';'));
}

console.log('\n--- минусовка на 0,3 с длиннее вокала (обратный случай) ---');
{
  const d = mk([26.3, 26.0]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  $('btnPlay').click(); await sleep(30);
  w.__advance(26.05);                       // srcs[0] (минусовка) ещё играет — ended не сработал
  ok('ранний конец второй дорожки сам по себе не завершает песню',
     w.__live.size===1, 'живых '+w.__live.size);
  w.__advance(0.3);                         // теперь и минусовка закончилась
  await sleep(30);
  ok('песня корректно завершилась по первой дорожке', w.__live.size===0);
}

console.log('\n--- клавиша M под Web Audio ---');
{
  const d = mk([26,26]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  // стемы по умолчанию открываются с выключенным голосом (0%)
  ok('старт с выключенным голосом', $('vVocal').textContent==='0%', $('vVocal').textContent);
  w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true}));
  ok('M включает голос из беззвучия', $('vVocal').textContent==='100%', $('vVocal').textContent);
  w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true}));
  ok('M снова глушит', $('vVocal').textContent==='0%', $('vVocal').textContent);
}

console.log('\n--- частые клики play/pause подряд ---');
{
  const d = mk([26,26]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  for (let i=0;i<6;i++){ $('btnPlay').click(); await sleep(5); }
  await sleep(60);
  ok('без ошибок после частых кликов', w.__errs.length===0, w.__errs.join(';'));
  ok('не больше одного живого набора источников', w.__live.size<=2, 'живых '+w.__live.size);
}

console.log('\n--- «Сдвиг» не трогает сам звук ---');
{
  const d = mk([26,26]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  $('btnPlay').click(); await sleep(20);
  const before = w.__live.size;
  $('rOffset').value='500'; $('rOffset').dispatchEvent(new w.Event('input'));
  await sleep(20);
  ok('источники не пересозданы сдвигом текста', w.__live.size===before,
     `было ${before}, стало ${w.__live.size}`);
}
console.log(fail?`\nПРОВАЛЕНО: ${fail}`:'\nВсе проверки пройдены');
process.exit(fail?1:0);
