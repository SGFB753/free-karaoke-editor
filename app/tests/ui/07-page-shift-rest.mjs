// Сдвиг «эта строка и весь остаток» — то, чем чинят разъезд после соло.
// Проверяем через публичный интерфейс страницы: подпись цели, экспорт .json
// и сохранение страницы. Внутренних переменных плеера тест не трогает.
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
let saved=null, savedName=null;
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){ savedName=this.download; };
await sleep(200);

const fail=m=>{console.log('ПРОВАЛ: '+m);process.exit(1);};
// единственный способ увидеть тайминги снаружи — попросить страницу их выгрузить
const starts=async()=>{ saved=null; $('btnSaveJson').click(); await sleep(20);
                        if(!saved) fail('экспорт .json ничего не отдал');
                        return JSON.parse(saved).lines.map(l=>l.start); };

const before = await starts();
if (before.length < 5) fail('в тестовой странице слишком мало строк');

const m=w.__inst[0];
$('btnEdit').click(); await sleep(40);
m.currentTime=9; await sleep(80);

// какая строка под правкой — страница пишет сама: «N. [время] текст»
const targetNo = () => {
  const mm = /^(\d+)\./.exec($('tgtName').textContent.trim());
  if (!mm) fail('подпись цели не показывает номер строки: ' + $('tgtName').textContent);
  return +mm[1] - 1;
};
const T = targetNo();
if (T < 0 || T >= before.length) fail('цель вне списка строк: ' + T);
console.log('  OK   цель подписана и подсвечена (строка ' + (T+1) + ')');
if (!doc.querySelectorAll('.ln.tgt').length) fail('целевая строка не подчёркнута на сцене');

// ◀ ▶ двигают цель ровно на одну строку и упираются в край
$('btnTgtNext').click(); await sleep(20);
if (targetNo() !== T+1) fail('▶ не сдвинула цель на следующую строку');
$('btnTgtPrev').click(); await sleep(20);
if (targetNo() !== T) fail('◀ не вернула цель обратно');
console.log('  OK   ◀ ▶ двигают цель по одной строке');

// сдвигаем цель и весь остаток на текущую секунду
$('chkRest').checked = true;
$('btnHere').click(); await sleep(60);

const after = await starts();
const d = before[T] - 9;
if (Math.abs(after[T]-9) > 0.02) fail(`целевая строка не встала на 9с: ${after[T]}`);
for (let i=0;i<T;i++)
  if (Math.abs(after[i]-before[i]) > 0.002) fail(`строка ${i+1} до целевой уехала`);
for (let i=T+1;i<after.length;i++)
  if (Math.abs((after[i]+d)-before[i]) > 0.02) fail(`строка ${i+1} сдвинулась не на ту же величину`);
console.log('  OK   строка и остаток сдвинулись, предыдущие не тронуты');

for (let i=1;i<after.length;i++)
  if (after[i] < after[i-1] - 0.002) fail(`порядок строк сломан на строке ${i+1}`);
console.log('  OK   порядок строк сохранён');

$('btnUndo').click(); await sleep(60);
const undone = await starts();
for (let i=0;i<undone.length;i++)
  if (Math.abs(undone[i]-before[i]) > 0.002) fail(`Отменить не вернуло строку ${i+1}`);
console.log('  OK   Отменить вернуло исходную разметку');

// повторяем правку и сохраняем страницу — тайминги должны уехать в файл
$('btnHere').click(); await sleep(60);
const fixed = await starts();
saved=null; $('btnSavePage').click(); await sleep(60);
if (!saved) fail('страница не сохранилась');
if (!/\.html$/.test(savedName||'')) fail('сохранилось не как .html: ' + savedName);
const pm = saved.match(/id="payload"[^>]*>([\s\S]*?)<\/script>/);
if (!pm) fail('в сохранённой странице нет данных');
const P2 = JSON.parse(pm[1].replace(/\\u003c/g,'<').replace(/\\u003e/g,'>').replace(/\\u0026/g,'&'));
if (!P2.edited) fail('сохранённая страница не помечена как правленая — видео возьмёт машинные тайминги');
const reloaded = P2.data.lines.map(l=>l.start);
if (reloaded.length !== fixed.length) fail('в сохранённой странице другое число строк');
for (let i=0;i<reloaded.length;i++)
  if (Math.abs(reloaded[i]-fixed[i]) > 0.02) fail(`сохранённая строка ${i+1} не совпала`);
console.log('  OK   правки вшиты в сохранённую страницу (' +
            (saved.length/1024/1024).toFixed(1) + ' МБ)');

if (w.__errs.length) fail('ошибки JS: ' + w.__errs.slice(0,2).join('; '));
console.log('  OK   ошибок JS нет');


console.log('\nAll checks passed');
process.exit(0);
