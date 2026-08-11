// Два голоса разом: в настоящем браузере строки должны читаться порознь —
// не наезжать друг на друга и стоять по разным сторонам сцены.
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { execFileSync } from 'child_process';

let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));

// Своя песня: две строки, одна в скобках (второй голос), звучат внахлёст.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'duo_'));
const txt = path.join(tmp, 'текст.txt');
fs.writeFileSync(txt, 'title: Дуэт\n\nПервый голос ведёт мелодию\n(а второй ему вторит)\nПотом снова один\n', 'utf8');
const page = path.join(tmp, 'p.html');
execFileSync('python3', ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', page,
  '--align','energy','--no-separate','--ui-lang','ru','--colors','#4de1ff,#ff5577']);

// Сдвигаем вторую строку под первую — как в настоящем дуэте.
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

// Встаём на момент, когда поют оба.
await p.evaluate(t => {
  const el = document.querySelector('audio') || null;
  window.__seek = t;
}, L[0].start + 0.6);
await p.evaluate(() => {
  document.getElementById('btnPlay').click();
});
await sleep(500);
await p.evaluate(t => {
  // перематываем через ту же полосу, что и человек
  const seek = document.getElementById('seek');
  const r = seek.getBoundingClientRect();
  const dur = document.getElementById('tDur').textContent;
  return t;
}, 0);
// проще: двигаем время напрямую через клик по строке и ожидание
await p.evaluate(() => document.querySelectorAll('#scroll .ln')[0].click());
await sleep(1200);

const state = await p.evaluate(() => {
  const els = [...document.querySelectorAll('#scroll .ln')];
  const cur = els.filter(e => e.classList.contains('cur'));
  // Меряем сами слова, а не блок строки: блок во всю ширину сцены, а глаз
  // видит текст, и разводятся именно слова.
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
ok('поют двое', state.n >= 2, JSON.stringify(state.boxes.map(x=>x.text)));
if (state.n >= 2){
  const one = state.boxes.find(x => !x.v2), two = state.boxes.find(x => x.v2);
  ok('обе строки разведены', one && two && one.duo && two.duo,
     JSON.stringify(state.boxes));
  ok('строки не пересекаются по вертикали',
     one.b <= two.t + 2 || two.b <= one.t + 2,
     `${one.t}–${one.b} и ${two.t}–${two.b}`);
  ok('первый голос стоит левее второго', one.l < two.l,
     `${one.l} vs ${two.l}`);
  ok('второй прижат к правому краю', two.r > state.stage * 0.6,
     `${two.r} при ширине ${state.stage}`);
  ok('обе видны целиком на сцене',
     one.t > 0 && two.b < 720, `${one.t} … ${two.b}`);
}
ok('ошибок JS нет', errs.length === 0, errs.slice(0,2).join(' | '));
await br.close();
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
