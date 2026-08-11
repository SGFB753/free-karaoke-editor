// Оставленный оригинальный голос и переключатель языка на готовой странице.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
import path from 'path';
import os from 'os';

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const sleep = ms => new Promise(r=>setTimeout(r,ms));

// Берём готовую страницу с двумя дорожками и отмечаем в ней строку как «поёт
// оригинал» — так проверяется настоящая сборка, а не выдуманные данные.
const src = process.env.KARAOKE_PAGE_STEMS;
const raw = fs.readFileSync(src, 'utf8');
const mark = '<script id="payload" type="application/json">';
const a = raw.indexOf(mark) + mark.length, b = raw.indexOf('</scr'+'ipt>', a);
const data = JSON.parse(raw.slice(a,b).replace(/\\u003c/g,'<').replace(/\\u003e/g,'>')
                                      .replace(/\\u0026/g,'&'));
data.uiLang = "ru";
const L = data.data.lines;
L[2].keep = true;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'keep_'));
const page = path.join(tmp, 'p.html');
fs.writeFileSync(page, raw.slice(0,a) + JSON.stringify(data)
  .replace(/</g,'\\u003c').replace(/>/g,'\\u003e').replace(/&/g,'\\u0026')
  + raw.slice(b), 'utf8');

const mkDom = () => new JSDOM(fs.readFileSync(page,'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/keep',
  beforeParse(w){
    w.__errs=[]; w.__inst=[]; w.__now=0; w.__gains=[];
    w.onerror=m=>w.__errs.push(String(m));
    w.fetch = () => Promise.resolve({arrayBuffer: () => Promise.resolve(new ArrayBuffer(8))});
    w.AudioContext = class {
      constructor(){ this.state="running"; this.destination={}; }
      get currentTime(){ return w.__now; }
      createGain(){ const g = {gain:{value:1, setTargetAtTime(v){ this.value = v; }},
                               connect(){}}; w.__gains.push(g); return g; }
      createBufferSource(){ return {connect(){},start(){},stop(){},onended:null}; }
      decodeAudioData(bin, res){ const buf={duration:26.04}; res && res(buf);
        return Promise.resolve(buf); }
      resume(){} };
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26.04;
      this._t=0;this._h={};w.__inst.push(this);
      setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA;
  }});

const dom = mkDom();
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
await sleep(500);
const lns = () => [...doc.querySelectorAll('#scroll .ln')];

console.log('--- строку видно заранее ---');
ok('строка помечена как оригинальная', lns()[2].classList.contains('keep'),
   [...lns()[2].classList].join(' '));
ok('на ней написано, что петь её не надо',
   /поёт оригинал/.test(lns()[2].textContent), lns()[2].textContent.slice(-40));
ok('на остальных такой надписи нет', !/поёт оригинал/.test(lns()[0].textContent));

console.log('\n--- голос возвращается именно на этом куске ---');
const vocalGain = () => {
  const g = w.__gains[1];
  return g ? g.gain.value : (w.__inst[1] ? w.__inst[1].volume : null);
};
ok('дорожки разделены (иначе проверять нечего)', w.__gains.length >= 2 || w.__inst.length >= 2,
   `gains=${w.__gains.length} el=${w.__inst.length}`);
// Играем по-настоящему: жмём кнопку и двигаем часы звукового движка.
const goto = async t => { w.__now = t; await sleep(140); };
$("btnPlay").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
await goto(L[0].start + 0.2);
const before = vocalGain();
ok('вне отмеченного куска голос приглушён', before === 0, String(before));
await goto(L[2].start + 0.3);
const during = vocalGain();
ok('на отмеченном куске голос звучит', during === 1, String(during));
await goto(L[3] ? L[3].start + 0.4 : L[2].end + 1.5);
await sleep(150);
const after = vocalGain();
ok('после куска голос снова убран', after === 0, String(after));

console.log('\n--- переключатель языка ---');
ok('кнопка языка есть', !!$("btnLang"));
ok('страница собрана по-русски', /Голос/.test($("grpVocal").textContent),
   $("grpVocal").textContent.trim());
ok('кнопка предлагает английский', $("btnLang").textContent.trim() === "EN",
   $("btnLang").textContent);
$("btnLang").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
ok('надписи стали английскими', /Voice/.test($("grpVocal").textContent),
   $("grpVocal").textContent.trim());
ok('метка на строке тоже переведена', /original sings/.test(lns()[2].textContent),
   lns()[2].textContent.slice(-40));
ok('кнопка теперь предлагает русский', $("btnLang").textContent.trim() === "RU");
ok('язык записан в атрибут страницы', doc.documentElement.lang === "en");

console.log('\n--- выбор запоминается ---');
// У каждого окна jsdom своя память, второй загрузкой это не проверить —
// смотрим саму запись, из которой страница берёт язык при открытии.
const keys = Object.keys(w.localStorage).filter(k => k.startsWith("karaoke-lang-"));
ok('выбор языка записан в память страницы', keys.length === 1, keys.join(","));
ok('и записан именно английский', w.localStorage.getItem(keys[0]) === "en",
   String(w.localStorage.getItem(keys[0])));
ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
