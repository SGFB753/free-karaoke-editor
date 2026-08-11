// Второй голос, цвета и одновременно звучащие строки.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
import { execFileSync } from 'child_process';
import path from 'path';
import os from 'os';

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const sleep = ms => new Promise(r=>setTimeout(r,ms));

// Своя песня: основная строка, подпевка, снова основная.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'voice_'));
const txt = path.join(tmp, 'текст.txt');
fs.writeFileSync(txt, 'title: Проба\n\nОсновная строка тут\n(подпевка звучит)\nСнова основная\n', 'utf8');
const page = path.join(tmp, 'p.html');
execFileSync('python3', ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', page,
  '--align','energy','--no-separate','--ui-lang','ru','--colors','#4de1ff,#ff5577']);

const dom = new JSDOM(fs.readFileSync(page,'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;
      this.playbackRate=1;this._t=0;this._h={};setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA;
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
await sleep(300);
const lns = () => [...doc.querySelectorAll('#scroll .ln')];

console.log('--- второй голос ---');
ok('строка в скобках помечена вторым голосом',
   lns()[1].classList.contains('v2'), [...lns()[1].classList].join(' '));
ok('обычные строки — первым', !lns()[0].classList.contains('v2') &&
   !lns()[2].classList.contains('v2'));

console.log('\n--- цвета ---');
const root = doc.documentElement.style;
ok('основной цвет взят из сборки',
   root.getPropertyValue('--accent').trim() === '#4de1ff',
   root.getPropertyValue('--accent'));
ok('второй цвет тоже', root.getPropertyValue('--accent-2').trim() === '#ff5577',
   root.getPropertyValue('--accent-2'));
ok('в стилях есть правило для второго голоса',
   /\.ln\.v2 \.w \.hl\{color:var\(--accent-2\)\}/.test(
     fs.readFileSync(page,'utf8').replace(/\s+/g,' ').replace(/ \{/g,'{')),
   'правило .ln.v2');

console.log('\n--- оформление ---');
{
  const eng = path.join(tmp,'t.html');
  execFileSync('python3', ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', eng,
    '--align','energy','--no-separate','--ui-lang','ru','--theme','#fdf6e3,#3b3a34']);
  const d = new JSDOM(fs.readFileSync(eng,'utf8'), {
    runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/t',
    beforeParse(w){ w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
      class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;this._t=0;this._h={};
        setTimeout(()=>this._fire('loadedmetadata'),0);}
        get currentTime(){return this._t;} set currentTime(v){this._t=v;}
        addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
        _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
        play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
      w.Audio=FA; }});
  await sleep(250);
  const st = d.window.document.documentElement.style;
  ok('фон страницы взят из настроек', st.getPropertyValue('--bg').trim() === '#fdf6e3',
     st.getPropertyValue('--bg'));
  ok('цвет букв тоже', st.getPropertyValue('--text').trim() === '#3b3a34',
     st.getPropertyValue('--text'));
  ok('тусклые строки не остались светлыми',
     st.getPropertyValue('--dim').trim() !== '' &&
     st.getPropertyValue('--dim').trim() !== '#5d6480',
     st.getPropertyValue('--dim'));
  ok('ошибок JS нет', d.window.__errs.length === 0, d.window.__errs.slice(0,2).join(' | '));
}

console.log('\n--- буквы не сливаются с фоном ---');
{
  const bad = path.join(tmp,'bad.html');
  execFileSync('python3', ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', bad,
    '--align','energy','--no-separate','--theme','#fdf6e3,#f5efdc']);
  const raw2 = fs.readFileSync(bad,'utf8');
  const m2 = '<script id="payload" type="application/json">';
  const a2 = raw2.indexOf(m2) + m2.length, b2 = raw2.indexOf('</scr'+'ipt>', a2);
  const th = JSON.parse(raw2.slice(a2,b2)).theme;
  ok('фон остался тем, что выбрали', th.bg === '#fdf6e3', JSON.stringify(th));
  ok('а цвет букв поправлен', th.text !== '#f5efdc', JSON.stringify(th));
}

console.log('\n--- строки звучат одновременно ---');
// Накладываем вторую строку на первую прямо в данных страницы и открываем заново:
// так проверяется настоящий разбор и отрисовка, а не внутренние переменные.
const raw = fs.readFileSync(page,'utf8');
const mark = '<script id="payload" type="application/json">';
const a = raw.indexOf(mark) + mark.length, b = raw.indexOf('</scr'+'ipt>', a);
const data = JSON.parse(raw.slice(a,b));
const L = data.data.lines;
L[1].start = L[0].start + 0.2;
L[1].end   = L[0].end   + 0.2;
L[1].words.forEach((x,i) => { x.t = L[1].start + i*0.2; x.d = 0.2; });
const page2 = path.join(tmp,'p2.html');
fs.writeFileSync(page2, raw.slice(0,a) + JSON.stringify(data) + raw.slice(b), 'utf8');

const dom2 = new JSDOM(fs.readFileSync(page2,'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__errs=[]; w.__inst=[]; w.onerror=m=>w.__errs.push(String(m));
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;
      this.playbackRate=1;this._t=0;this._h={};w.__inst.push(this);
      setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA;
  }});
const w2 = dom2.window;
await sleep(300);
const m = w2.__inst[0];
m.currentTime = L[0].start + 0.3;
await sleep(300);
const lns2 = [...w2.document.querySelectorAll('#scroll .ln')];
const cur = lns2.filter(e => e.classList.contains('cur'));
ok('подсвечены обе накладывающиеся строки', cur.length >= 2,
   cur.length + ' строк подсвечено');
ok('и это именно первая и вторая',
   cur.includes(lns2[0]) && cur.includes(lns2[1]));
const lit = lns2[1].querySelectorAll('.w .hl');
ok('у второй строки слова тоже подсвечиваются', lit.length > 0);
ok('ошибок JS на второй странице нет', w2.__errs.length===0, w2.__errs.slice(0,2).join(' | '));

console.log('\n--- разные голоса не сливаются в кашу ---');
// Строка 1 — второй голос (в скобках), строка 0 — первый. Они звучат разом.
ok('обе помечены как «поют вдвоём»',
   cur.every(e => e.classList.contains('duo')),
   cur.map(e => e.className).join(' | '));
ok('первый голос уходит влево, второй вправо',
   !lns2[0].classList.contains('v2') && lns2[1].classList.contains('v2'));
{
  const css = fs.readFileSync(page2,'utf8').replace(/\s+/g,' ');
  ok('в стилях есть развод по сторонам',
     /\.ln\.duo:not\(\.v2\)\{[^}]*text-align:left/.test(css) &&
     /\.ln\.duo\.v2\{[^}]*text-align:right/.test(css),
     'правила .ln.duo');
  ok('у каждой стороны своя метка голоса',
     /\.ln\.duo::before\{content:"1"/.test(css) && /\.ln\.duo\.v2::before\{content:"2"/.test(css));
}
// когда поёт кто-то один — никакого развода
m.currentTime = L[2] ? L[2].start + 0.2 : L[0].end + 5;
await sleep(300);
const solo = [...w2.document.querySelectorAll('#scroll .ln')].filter(e => e.classList.contains('cur'));
ok('в одиночном пении развода нет',
   solo.every(e => !e.classList.contains('duo')),
   solo.map(e => e.className).join(' | '));

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
