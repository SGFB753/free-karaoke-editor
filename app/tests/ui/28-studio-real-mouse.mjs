// Настоящая мышь: попадание курсором jsdom не проверяет вообще, а именно там
// и пряталась беда — за левый край блока потянуть было нечем.
import puppeteer from 'puppeteer';
const API = process.env.KARAOKE_API;
const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
p.on('pageerror', e => console.log('ОШИБКА JS:', String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));

const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const srv = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json()).lines;
let fail = 0;
const ok = (n,c,e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };

// Ищем блок, у которого нужное место действительно доступно курсору: соседи
// могут налезать, и тогда клик достанется им, а не тому, что мы метили.
async function pick(where){
  return await p.evaluate((where) => {
    const blocks = [...document.querySelectorAll('.blk')];
    for (let i = 0; i < blocks.length; i++){
      const r = blocks[i].getBoundingClientRect();
      if (r.width < 30 || r.left < 4 || r.right > innerWidth - 4) continue;
      const x = where === 'left'  ? r.left + 4
              : where === 'right' ? r.right - 4
              : r.left + r.width/2;
      const hit = document.elementFromPoint(x, r.top + r.height/2);
      if (!hit) continue;
      const owner = hit.closest ? hit.closest('.blk') : null;
      if (owner !== blocks[i]) continue;
      const isGrip = hit.classList.contains('grip');
      if ((where === 'mid') !== !isGrip) continue;
      return i;
    }
    return -1;
  }, where);
}

async function grab(i, where, dx){
  const before = (await srv())[i];
  const box = await p.evaluate((i, where) => {
    const e = document.querySelectorAll('.blk')[i];
    const r = e.getBoundingClientRect();
    const x = where === 'left'  ? r.left + 4
            : where === 'right' ? r.right - 4
            : r.left + r.width/2;
    const y = r.top + r.height/2;
    const hit = document.elementFromPoint(x, y);
    return {x, y, hit: hit ? hit.className : 'ничего', w: r.width};
  }, i, where);
  await p.mouse.move(box.x, box.y);
  await p.mouse.down();
  await p.mouse.move(box.x + dx, box.y, {steps: 10});
  await p.mouse.up();
  await new Promise(r=>setTimeout(r,900));
  return {before, after: (await srv())[i], hit: box.hit};
}

console.log('--- за левый край: двигается начало ---');
let idx = await pick('left');
ok('нашёлся блок со свободным левым краем', idx >= 0, 'блок ' + (idx+1));
let r = await grab(idx, 'left', 60);
ok('под курсором у левого края — ручка', /grip/.test(r.hit), r.hit);
ok('начало строки уехало', Math.abs(r.after.start - r.before.start) > 0.05,
   `${r.before.start.toFixed(3)} → ${r.after.start.toFixed(3)}`);
ok('конец строки остался на месте', Math.abs(r.after.end - r.before.end) < 1e-6,
   `${r.before.end.toFixed(3)} → ${r.after.end.toFixed(3)}`);
ok('слова переразложены внутри новой длины',
   r.after.words[0].t >= r.after.start - 1e-6 &&
   r.after.words.at(-1).t + r.after.words.at(-1).d <= r.after.end + 1e-6);

console.log('\n--- за правый край: двигается конец ---');
idx = await pick('right');
ok('нашёлся блок со свободным правым краем', idx >= 0, 'блок ' + (idx+1));
r = await grab(idx, 'right', 70);
ok('под курсором у правого края — ручка', /grip/.test(r.hit), r.hit);
ok('конец уехал', Math.abs(r.after.end - r.before.end) > 0.05,
   `${r.before.end.toFixed(3)} → ${r.after.end.toFixed(3)}`);
ok('начало осталось', Math.abs(r.after.start - r.before.start) < 1e-6);

console.log('\n--- за середину: едет вся строка ---');
idx = await pick('mid');
ok('нашёлся блок со свободной серединой', idx >= 0, 'блок ' + (idx+1));
r = await grab(idx, 'mid', 80);
ok('под курсором — сам блок', /blk/.test(r.hit) && !/grip/.test(r.hit), r.hit);
ok('строка сдвинулась целиком',
   Math.abs(r.after.start - r.before.start) > 0.05 &&
   Math.abs((r.after.end - r.after.start) - (r.before.end - r.before.start)) < 0.01,
   `${r.before.start.toFixed(2)}–${r.before.end.toFixed(2)} → ${r.after.start.toFixed(2)}–${r.after.end.toFixed(2)}`);

console.log('\n--- первый блок у самого левого края тоже тянется ---');
await p.evaluate(() => document.getElementById('btnUndo').click());
await new Promise(r=>setTimeout(r,600));
r = await grab(0, 'mid', 50);
ok('самый первый блок двигается', Math.abs(r.after.start - r.before.start) > 0.05,
   `${r.before.start.toFixed(3)} → ${r.after.start.toFixed(3)}`);

console.log('\n--- слово тянется настоящей мышью ---');
const wr = await p.evaluate(() => {
  const c = [...document.querySelectorAll('.wrd')];
  if (!c.length) return null;
  const r = c[c.length-1].getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
  return {cls: hit ? hit.className : 'ничего',
          // важно не «какой это элемент», а достанется ли нажатие слову
          mine: !!(hit && hit.closest && hit.closest('.wrd') === c[c.length-1])};
});
ok('нажатие по слову достаётся слову', wr && wr.mine, wr ? wr.cls : 'нет слов');

await b.close();
console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
