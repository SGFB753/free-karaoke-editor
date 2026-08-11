// Листание текста руками и погасшая подсветка после последней строки.
import puppeteer from 'puppeteer';
const API = process.env.KARAOKE_API;
const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const shift = () => p.evaluate(() => document.getElementById('scroll').style.transform);
const cur = () => p.evaluate(() => {
  const all = [...document.querySelectorAll('#scroll .ln')];
  const c = document.querySelector('#scroll .ln.cur');
  return c ? all.indexOf(c) : -1;
});

console.log('--- листаем колесом ---');
const was = await shift();
const box = await p.evaluate(() => {
  const r = document.querySelector('.stage').getBoundingClientRect();
  return {x: r.left + r.width/2, y: r.top + r.height/2};
});
await p.mouse.move(box.x, box.y);
await p.mouse.wheel({deltaY: 300});
await new Promise(r=>setTimeout(r,400));
const after = await shift();
ok('текст поехал под колесом', after !== was, `${was} → ${after}`);
await p.mouse.wheel({deltaY: -300});
await new Promise(r=>setTimeout(r,400));
ok('и обратно', (await shift()) !== after);

console.log('\n--- Home и End ---');
await p.keyboard.press('End');
await new Promise(r=>setTimeout(r,900));
const atEnd = await p.evaluate(() => {
  const all = [...document.querySelectorAll('#scroll .ln')];
  const s = document.querySelector('#scroll .ln.sel');
  return {i: s ? all.indexOf(s) : -1, n: all.length};
});
ok('End выбирает последнюю строку', atEnd.i === atEnd.n - 1,
   `${atEnd.i+1} из ${atEnd.n}`);
await p.keyboard.press('Home');
await new Promise(r=>setTimeout(r,900));
const atHome = await p.evaluate(() => {
  const all = [...document.querySelectorAll('#scroll .ln')];
  const s = document.querySelector('#scroll .ln.sel');
  return s ? all.indexOf(s) : -1;
});
ok('Home возвращает к первой', atHome === 0, String(atHome + 1));

console.log('\n--- после последней строки ничего не горит ---');
const last = await p.evaluate(async () => {
  const r = await fetch('/api/state');
  return null;
});
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const lines = (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json()).lines;
const lastEnd = lines[lines.length-1].end;
// прыгаем на середину песни — там подсветка обязана быть
await p.evaluate(t => {
  const w = document.getElementById('tlwrap').getBoundingClientRect();
  return null;
}, 0);
await p.evaluate(() => document.querySelectorAll('#scroll .ln')[1].click());
await new Promise(r=>setTimeout(r,600));
ok('на середине песни строка подсвечена', (await cur()) >= 0, String(await cur()));

// а теперь честно доматываем за конец последней строки — стрелкой, как человек
await p.evaluate(() => document.getElementById('scrEdit').focus?.());
for (let i = 0; i < 40; i++){
  const t = await p.evaluate(() => document.getElementById('tCur').textContent);
  const sec = t.split(':').reduce((m, x) => m * 60 + parseFloat(x), 0);
  if (sec > lastEnd + 0.6) break;
  await p.keyboard.press('ArrowRight');
  await new Promise(r => setTimeout(r, 120));
}
await new Promise(r=>setTimeout(r,600));
const t2 = await p.evaluate(() => document.getElementById('tCur').textContent);
const sec2 = t2.split(':').reduce((m, x) => m * 60 + parseFloat(x), 0);
ok('домотали за последнюю строку', sec2 > lastEnd,
   `${t2} при конце текста ${lastEnd.toFixed(2)} с`);
const nothing = await cur();
ok('подсветка снята — ничего не «обвисает»', nothing < 0,
   nothing >= 0 ? `горит строка ${nothing+1}` : '');

ok('ошибок JS нет', errs.length===0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
