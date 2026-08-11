// Выбор строки в отдельной HTML-странице: щёлкнул строку — правится именно она,
// и песня её больше не уводит. Тут раньше цель уезжала на предыдущую строку.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;this.seeking=false;
      this.playbackRate=1;this._t=0;this._h={};w.__inst.push(this);setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){this._h[n]=(this._h[n]||[]).filter(x=>x!==f);}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
let saved=null;
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(250);

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const tgtNo = () => { const m=/^(\d+)\./.exec($('tgtName').textContent.trim()); return m?+m[1]-1:-1; };
const starts = async () => { saved=null; $('btnSaveJson').click(); await sleep(20);
                             return JSON.parse(saved).lines.map(l=>l.start); };
const m = w.__inst[0];
const lineEls = [...doc.querySelectorAll('#scroll .ln')];

const __savedLabelAtStart = $('btnSavePage').textContent;
$('btnEdit').click(); await sleep(50);
ok('строк на сцене хватает для проверки', lineEls.length >= 5, 'строк '+lineEls.length);

console.log('\n--- щелчок по строке выбирает именно её ---');
const WANT = 4;
lineEls[WANT].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(120);
ok('правится та строка, по которой щёлкнули', tgtNo() === WANT,
   'выбрана ' + (tgtNo()+1) + '-я вместо ' + (WANT+1) + '-й');
ok('она же подчёркнута на сцене',
   lineEls[WANT].classList.contains('tgt'), [...lineEls[WANT].classList].join(' '));

console.log('\n--- песня играет, а выбор держится ---');
const before = await starts();
m.currentTime = before[WANT] + 6;              // уехали далеко вперёд
await sleep(150);
ok('цель не убежала за песней', tgtNo() === WANT, 'стала ' + (tgtNo()+1) + '-й');

console.log('\n--- правка попадает в выбранную строку ---');
m.currentTime = 12.5; await sleep(100);
$('btnHere').click(); await sleep(80);
const after = await starts();
ok('выбранная строка встала на текущую секунду', Math.abs(after[WANT]-12.5) < 0.05,
   'стало ' + after[WANT]);
ok('соседняя строка не тронута', Math.abs(after[WANT-1]-before[WANT-1]) < 1e-6,
   `${before[WANT-1]} → ${after[WANT-1]}`);

console.log('\n--- выбор видно и его можно снять ---');
ok('кнопка «не эту» появилась', !$('btnUnpin').classList.contains('hide'));
$('btnUnpin').click(); await sleep(80);
ok('кнопка спряталась обратно', $('btnUnpin').classList.contains('hide'));
m.currentTime = 2.0; await sleep(150);
ok('цель снова идёт за песней', tgtNo() !== WANT, 'осталась ' + (tgtNo()+1) + '-й');

console.log('\n--- ◀ ▶ тоже закрепляют ---');
$('btnTgtNext').click(); await sleep(60);
const t1 = tgtNo();
ok('▶ сдвинула цель', t1 >= 0);
ok('и закрепила её', !$('btnUnpin').classList.contains('hide'));
m.currentTime = 20; await sleep(150);
ok('цель осталась на месте при проигрывании', tgtNo() === t1, 'стала ' + (tgtNo()+1));

console.log('\n--- лишнего на экране нет ---');
ok('подсказка по тапам спрятана, пока режим выключен',
   $('tapRow').classList.contains('hide') &&
   w.getComputedStyle($('tapRow')).display === 'none',
   'display: ' + w.getComputedStyle($('tapRow')).display);

$('btnSavePage').click(); await sleep(60);
ok('сохранённая страница открывается без закреплённой цели',
   /id="btnUnpin" class="hide"/.test(saved) || /class="hide"[^>]*id="btnUnpin"/.test(saved),
   (saved.match(/<button id="btnUnpin"[^>]*>/)||[''])[0]);

console.log('\n--- видно, что правки ещё не в файле ---');
ok('на свежей странице кнопка сохранения обычная',
   !/есть несохранённые/.test(__savedLabelAtStart), __savedLabelAtStart);
ok('сразу после сохранения предупреждения нет',
   !/есть несохранённые/.test($('btnSavePage').textContent),
   $('btnSavePage').textContent);
$('btnHere').click(); await sleep(80);          // правим уже после сохранения
ok('новая правка снова предупреждает',
   /есть несохранённые/.test($('btnSavePage').textContent) &&
   $('btnSavePage').classList.contains('on'),
   $('btnSavePage').textContent);

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
