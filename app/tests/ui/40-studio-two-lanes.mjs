// Вокалы внахлёст: строка второго голоса уходит на вторую полосу дорожки и
// остаётся хватаемой мышью. Настоящий браузер — jsdom верстку не считает.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());
const sleep = ms => new Promise(r=>setTimeout(r,ms));

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(600);
await p.click('.card');
await sleep(2500);

const lane = i => p.evaluate(k => {
  const e = document.querySelectorAll('#blocks .blk')[k];
  return e ? e.getBoundingClientRect().top : null;
}, i);
const wrapH = () => p.evaluate(() =>
  document.getElementById('tlwrap').getBoundingClientRect().height);

console.log('--- пока второго голоса нет ---');
const h0 = await wrapH();
const top0 = await lane(1);
ok('дорожка в одну полосу', !(await p.evaluate(() =>
   document.getElementById('tlwrap').classList.contains('twolane'))));

console.log('\n--- назначаем строке второй голос ---');
await p.evaluate(() => document.querySelectorAll('#scroll .ln')[1].click());
await sleep(200);
await p.click('#btnVoice');
await sleep(400);

const h1 = await wrapH();
const top1 = await lane(1);
const topMain = await lane(0);
ok('дорожка стала выше', h1 > h0, `${h0} → ${h1}`);
// Дорожка выросла и сдвинула вёрстку, поэтому сравниваем блоки между собой,
// а не с их же прежними координатами на экране.
ok('блок второго голоса ниже блоков основного', top1 > topMain + 20,
   `основной ${topMain}, второй ${top1}`);
ok('до второго голоса блоки шли одной полосой', Math.abs(top0 - topMain) < 40,
   `${top0} vs ${topMain}`);

console.log('\n--- блок второго голоса по-прежнему хватается мышью ---');
const box = await p.evaluate(() => {
  const e = document.querySelectorAll('#blocks .blk')[1];
  const r = e.getBoundingClientRect();
  return {x: r.left + r.width/2, y: r.top + r.height/2};
});
const hit = await p.evaluate(({x,y}) => {
  const e = document.elementFromPoint(x, y);
  return !!(e && e.closest('.blk') === document.querySelectorAll('#blocks .blk')[1]);
}, box);
ok('под курсором именно этот блок', hit);
const was = (await proj()).lines[1].start;
await p.mouse.move(box.x, box.y);
await p.mouse.down();
await p.mouse.move(box.x + 60, box.y, {steps: 8});
await p.mouse.up();
await sleep(900);
const now = (await proj()).lines[1].start;
ok('строку второго голоса удалось подвинуть', now > was + 0.05,
   `${was.toFixed(2)} → ${now.toFixed(2)}`);

console.log('\n--- и слова этой строки видны под дорожкой ---');
const wordsBelow = await p.evaluate(() => {
  const w = document.querySelector('#words .wrd');
  const blk = document.querySelectorAll('#blocks .blk')[1];
  if (!w || !blk) return null;
  return w.getBoundingClientRect().top - blk.getBoundingClientRect().bottom;
});
ok('ряд слов ниже второй полосы, а не поверх неё', wordsBelow !== null && wordsBelow > 0,
   String(wordsBelow));

// возвращаем как было, чтобы стенд остался чистым для соседних наборов
await p.click('#btnVoice');
await sleep(200);
await p.evaluate(t => {
  const b = document.querySelectorAll('#blocks .blk')[1];
  b.click();
}, 0);
await sleep(600);

ok('ошибок JS нет', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
