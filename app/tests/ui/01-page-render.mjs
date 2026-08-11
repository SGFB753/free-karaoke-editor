const { JSDOM } = await import('jsdom');
import fs from 'fs';

const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_MIX, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true,
  beforeParse(w){
    w.__inst = [];
    class FakeAudio {
      constructor(){ this.currentTime=0; this.paused=true; this.volume=1; this.duration=26;
        this._h={}; w.__inst.push(this); setTimeout(()=>this._fire('loadedmetadata'),0); }
      addEventListener(n,f){ (this._h[n]=this._h[n]||[]).push(f); }
      _fire(n){ (this._h[n]||[]).forEach(f=>f()); }
      play(){ this.paused=false; this._fire('play'); return Promise.resolve(); }
      pause(){ this.paused=true; this._fire('pause'); }
    }
    w.Audio = FakeAudio;
    w.__errs = [];
    w.onerror = (m)=>{ w.__errs.push(String(m)); };
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r=>setTimeout(r,ms));
await sleep(200);

let fail = 0;
const ok = (name, cond, extra='') => { console.log((cond?'  ✓ ':'  ✗ ')+name+(extra?' — '+extra:'')); if(!cond) fail++; };

console.log('JS-ошибки:', w.__errs.length ? w.__errs : 'нет');
ok('ошибок при загрузке нет', w.__errs.length===0);

const lns = [...doc.querySelectorAll('.ln')];
ok('отрисовано 6 строк', lns.length===6, 'получено '+lns.length);
ok('секции показаны', doc.querySelectorAll('.sect').length===2);
ok('заголовок из мета-полей', $('mTitle').textContent==='Тестовая песня', $('mTitle').textContent);
ok('исполнитель', $('mArtist').textContent==='Проверка Связи');
ok('одна дорожка => регулятор голоса скрыт', $('grpVocal').style.display==='none');
ok('длительность в футере', $('tDur').textContent==='0:26', $('tDur').textContent);

const master = w.__inst[0];
const cur = () => lns.findIndex(e=>e.classList.contains('cur'));
console.log('--- подсветка по времени (ожидаемые старты 2/5/8/11/16/19) ---');
for (const [t, want] of [[0.5,-1],[2.5,0],[5.5,1],[8.5,2],[12,3],[17,4],[21,5]]){
  master.currentTime = t; await sleep(70);
  ok(`t=${t}с → строка ${want<0?'нет':want+1}`, cur()===want, 'подсвечена '+(cur()<0?'нет':cur()+1));
}

// прогресс заливки слова внутри строки
master.currentTime = 5.2; await sleep(70);
const hls = [...lns[1].children].map(s=>s.firstChild);
const p0 = hls[0].style.width;
master.currentTime = 6.9; await sleep(70);
const full = hls.filter(h=>h.style.width==='100%').length;
ok('слова заливаются по очереди', full>0 && full<hls.length, `спето ${full} из ${hls.length}`);
ok('первое слово имеет частичную заливку', /%$/.test(p0) && p0!=='100%' && p0!=='0%', 'ширина='+p0);
ok('яркий слой отдельным элементом (без градиента по буквам)',
   hls.every(h=>h.className==='hl'));

// сдвиг
$('rOffset').value = 500; $('rOffset').dispatchEvent(new w.Event('input'));
ok('сдвиг применился и показан до миллисекунд',
   $('vOffset').textContent==='+0.500с', $('vOffset').textContent);
ok('текущее время тоже с миллисекундами', /^\d+:\d\d\.\d{3}$/.test($('tCur').textContent),
   $('tCur').textContent);
master.currentTime = 5.2; await sleep(70);
ok('со сдвигом +0.5с строка 2 ещё не началась', cur()===0, 'строка '+(cur()+1));
$('rOffset').value = 0; $('rOffset').dispatchEvent(new w.Event('input'));

// экспорт LRC
let dl=null;
w.HTMLAnchorElement.prototype.click = function(){ dl=this.download; };
w.URL.createObjectURL = () => 'blob:x'; w.URL.revokeObjectURL = ()=>{};
$('btnSaveLrc').click(); ok('кнопка .lrc отдаёт файл', dl==='lyrics.lrc', String(dl));
$('btnSaveJson').click(); ok('кнопка .json отдаёт файл', dl==='timings.json', String(dl));

// клик по строке = перемотка
lns[4].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
ok('клик по строке перематывает', Math.abs(master.currentTime-(16.14-0.35))<0.4, 't='+master.currentTime.toFixed(2));

// play/pause
$('btnPlay').click(); await sleep(30);
ok('play запускается', !master.paused && doc.body.classList.contains('playing'));
$('btnPlay').click(); await sleep(30);
ok('pause останавливает', master.paused);

console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail?1:0);
