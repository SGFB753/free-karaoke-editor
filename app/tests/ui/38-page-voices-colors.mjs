// The second voice, the colours and lines that sound at the same time.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
import { execFileSync } from 'child_process';
import path from 'path';
import os from 'os';

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const PY = process.env.KARAOKE_PYTHON || 'python3';

// A song of our own: a main line, a backing line, a main line again.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'voice_'));
const txt = path.join(tmp, 'lyrics.txt');
fs.writeFileSync(txt, 'title: Проба\n\nОсновная строка тут\n(подпевка звучит)\nСнова основная\n', 'utf8');
const page = path.join(tmp, 'p.html');
execFileSync(PY, ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', page,
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

console.log('--- the second voice ---');
ok('a line in brackets is marked as the second voice',
   lns()[1].classList.contains('v2'), [...lns()[1].classList].join(' '));
ok('ordinary lines as the first', !lns()[0].classList.contains('v2') &&
   !lns()[2].classList.contains('v2'));

console.log('\n--- colours ---');
const root = doc.documentElement.style;
ok('the main colour came from the build',
   root.getPropertyValue('--accent').trim() === '#4de1ff',
   root.getPropertyValue('--accent'));
ok('the second colour too', root.getPropertyValue('--accent-2').trim() === '#ff5577',
   root.getPropertyValue('--accent-2'));
ok('the styles carry a rule for the second voice',
   /\.ln\.v2 \.w \.hl\{color:var\(--accent-2\)\}/.test(
     fs.readFileSync(page,'utf8').replace(/\s+/g,' ').replace(/ \{/g,'{')),
   'the .ln.v2 rule');

console.log('\n--- the look ---');
{
  const eng = path.join(tmp,'t.html');
  execFileSync(PY, ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', eng,
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
  ok('the page background came from the settings', st.getPropertyValue('--bg').trim() === '#fdf6e3',
     st.getPropertyValue('--bg'));
  ok('the text colour too', st.getPropertyValue('--text').trim() === '#3b3a34',
     st.getPropertyValue('--text'));
  ok('the dim lines did not stay light',
     st.getPropertyValue('--dim').trim() !== '' &&
     st.getPropertyValue('--dim').trim() !== '#5d6480',
     st.getPropertyValue('--dim'));
  ok('no JS errors', d.window.__errs.length === 0, d.window.__errs.slice(0,2).join(' | '));
}

console.log('\n--- the letters do not blend into the background ---');
{
  const bad = path.join(tmp,'bad.html');
  execFileSync(PY, ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', bad,
    '--align','energy','--no-separate','--theme','#fdf6e3,#f5efdc']);
  const raw2 = fs.readFileSync(bad,'utf8');
  const m2 = '<script id="payload" type="application/json">';
  const a2 = raw2.indexOf(m2) + m2.length, b2 = raw2.indexOf('</scr'+'ipt>', a2);
  const th = JSON.parse(raw2.slice(a2,b2)).theme;
  ok('the background stayed the one that was picked', th.bg === '#fdf6e3', JSON.stringify(th));
  ok('while the text colour was adjusted', th.text !== '#f5efdc', JSON.stringify(th));
}

console.log('\n--- the lines sound at the same time ---');
// We overlap the second line with the first right in the page data and reopen it:
// that checks the real parsing and drawing, not internal variables.
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
ok('both overlapping lines are highlighted', cur.length >= 2,
   cur.length + ' lines highlighted');
ok('and they are exactly the first and the second',
   cur.includes(lns2[0]) && cur.includes(lns2[1]));
const lit = lns2[1].querySelectorAll('.w .hl');
ok("the second line's words light up as well", lit.length > 0);
ok('there are no JS errors on the second page', w2.__errs.length===0, w2.__errs.slice(0,2).join(' | '));

console.log('\n--- different voices do not blur together ---');
// Line 1 is the second voice (in brackets), line 0 the first. They sound at once.
ok('both are marked as “singing together”',
   cur.every(e => e.classList.contains('duo')),
   cur.map(e => e.className).join(' | '));
ok('the first voice goes left, the second right',
   !lns2[0].classList.contains('v2') && lns2[1].classList.contains('v2'));
{
  const css = fs.readFileSync(page2,'utf8').replace(/\s+/g,' ');
  ok('the styles carry the split to the sides',
     /\.ln\.duo:not\(\.v2\)\{[^}]*text-align:left/.test(css) &&
     /\.ln\.duo\.v2\{[^}]*text-align:right/.test(css),
     'the .ln.duo rules');
  ok('each side has its own voice mark',
     /\.ln\.duo::before\{content:"1"/.test(css) && /\.ln\.duo\.v2::before\{content:"2"/.test(css));
}
// when only one is singing — no splitting apart
m.currentTime = L[2] ? L[2].start + 0.2 : L[0].end + 5;
await sleep(300);
const solo = [...w2.document.querySelectorAll('#scroll .ln')].filter(e => e.classList.contains('cur'));
ok('in solo singing there is no split',
   solo.every(e => !e.classList.contains('duo')),
   solo.map(e => e.className).join(' | '));

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
