// Two voices at once: in a real browser the lines must read apart — they must
// not overlap and must stand on different sides of the stage.
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { execFileSync } from 'child_process';

let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));

// A song of our own: two lines, one in brackets (the second voice), overlapping.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'duo_'));
const txt = path.join(tmp, 'lyrics.txt');
fs.writeFileSync(txt, 'title: Дуэт\n\nПервый голос ведёт мелодию\n(а второй ему вторит)\nПотом снова один\n', 'utf8');
const page = path.join(tmp, 'p.html');
execFileSync('python3', ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', page,
  '--align','energy','--no-separate','--ui-lang','ru','--colors','#4de1ff,#ff5577']);

// Shift the second line under the first — as in a real duet.
const raw = fs.readFileSync(page,'utf8');
const mark = '<script id="payload" type="application/json">';
const a = raw.indexOf(mark) + mark.length, b = raw.indexOf('</scr'+'ipt>', a);
const data = JSON.parse(raw.slice(a,b).replace(/\\u003c/g,'<').replace(/\\u003e/g,'>')
                                      .replace(/\\u0026/g,'&'));
const L = data.data.lines;
L[1].start = L[0].start + 0.3; L[1].end = L[0].end;
L[1].words.forEach((w,i) => { w.t = L[1].start + i*0.3; w.d = 0.3; });
const page2 = path.join(tmp,'duo.html');
fs.writeFileSync(page2, raw.slice(0,a) + JSON.stringify(data)
  .replace(/</g,'\\u003c').replace(/>/g,'\\u003e').replace(/&/g,'\\u0026') + raw.slice(b), 'utf8');

const br = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage','--autoplay-policy=no-user-gesture-required']});
const p = await br.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.setViewport({width:1280, height:720});
await p.goto('file://' + page2, {waitUntil:'networkidle0'});
await sleep(800);

// Stand at the moment when both are singing.
await p.evaluate(t => {
  const el = document.querySelector('audio') || null;
  window.__seek = t;
}, L[0].start + 0.6);
await p.evaluate(() => {
  document.getElementById('btnPlay').click();
});
await sleep(500);
await p.evaluate(t => {
  // seek through the same bar a person would use
  const seek = document.getElementById('seek');
  const r = seek.getBoundingClientRect();
  const dur = document.getElementById('tDur').textContent;
  return t;
}, 0);
// simpler: move the time directly with a click on a line and a wait
await p.evaluate(() => document.querySelectorAll('#scroll .ln')[0].click());
await sleep(1200);

const state = await p.evaluate(() => {
  const els = [...document.querySelectorAll('#scroll .ln')];
  const cur = els.filter(e => e.classList.contains('cur'));
  // Measure the words themselves, not the line block: the block spans the whole
  // stage while the eye sees the text, and it is the words that are split apart.
  const box = e => {
    const ws = [...e.querySelectorAll('.w')].map(w => w.getBoundingClientRect());
    const r = e.getBoundingClientRect();
    return {l: Math.round(Math.min(...ws.map(x => x.left))),
            r: Math.round(Math.max(...ws.map(x => x.right))),
            t: Math.round(Math.min(...ws.map(x => x.top))),
            b: Math.round(Math.max(...ws.map(x => x.bottom))),
            row: Math.round(r.top), text: e.textContent.trim().slice(0,20),
            duo: e.classList.contains('duo'), v2: e.classList.contains('v2')}; };
  return {n: cur.length, boxes: cur.map(box), stage: document.getElementById('stage').getBoundingClientRect().width};
});
ok('two are singing', state.n >= 2, JSON.stringify(state.boxes.map(x=>x.text)));
if (state.n >= 2){
  const one = state.boxes.find(x => !x.v2), two = state.boxes.find(x => x.v2);
  ok('both lines are split apart', one && two && one.duo && two.duo,
     JSON.stringify(state.boxes));
  ok('the lines do not overlap vertically',
     one.b <= two.t + 2 || two.b <= one.t + 2,
     `${one.t}–${one.b} and ${two.t}–${two.b}`);
  ok('the first voice sits to the left of the second', one.l < two.l,
     `${one.l} vs ${two.l}`);
  ok('the second hugs the right edge', two.r > state.stage * 0.6,
     `${two.r} with a width of ${state.stage}`);
  ok('both are fully visible on stage',
     one.t > 0 && two.b < 720, `${one.t} … ${two.b}`);
}
ok('no JS errors', errs.length === 0, errs.slice(0,2).join(' | '));
await br.close();
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
