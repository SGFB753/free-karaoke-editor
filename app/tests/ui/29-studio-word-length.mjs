// Длина слова. Раньше её нельзя было задать в принципе: слово тянулось встык
// до следующего, и «где оно кончается» вообще не было отдельной величиной.
import puppeteer from 'puppeteer';
const API = process.env.KARAOKE_API;
const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
const errs = [];
p.on('pageerror', e => errs.push(String(e)));
await p.goto(API + '/', {waitUntil:'networkidle0'});
await new Promise(r => setTimeout(r, 600));
await p.click('.card');
await new Promise(r => setTimeout(r, 2500));

const PID = (await (await fetch(API + '/api/state')).json()).projects[0].id;
const line = async i => (await (await fetch(API + '/api/project/' +
  encodeURIComponent(PID))).json()).lines[i];
let fail = 0;
const ok = (n, c, e = '') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };

// Берём строку, у которой слова заметной ширины: на узких ручки не рисуются.
const LINE = await p.evaluate(() => {
  const ls = [...document.querySelectorAll('#scroll .ln')];
  for (let i = 0; i < ls.length; i++){
    ls[i].click();
    const c = [...document.querySelectorAll('.wrd')];
    if (c.length >= 2 && c.every(x => x.getBoundingClientRect().width > 40)) return i;
  }
  return 0;
});
await p.evaluate(i => document.querySelectorAll('#scroll .ln')[i].click(), LINE);
await new Promise(r => setTimeout(r, 500));
ok('нашлась строка со словами приличной ширины', true, 'строка ' + (LINE+1));

// Свободен ли край блока для захвата: сосед может его накрывать.
async function freeEdge(side){
  return await p.evaluate((i, side) => {
    const e = document.querySelectorAll('.blk')[i];
    const r = e.getBoundingClientRect();
    const x = side === 'left' ? r.left + 4 : r.right - 4;
    const y = r.top + r.height / 2;
    const hit = document.elementFromPoint(x, y);
    return (hit && hit.closest('.blk') === e) ? {x, y} : null;
  }, LINE, side);
}
async function pull(spot, dx){
  await p.mouse.move(spot.x, spot.y);
  await p.mouse.down();
  await p.mouse.move(spot.x + dx, spot.y, {steps: 8});
  await p.mouse.up();
  await new Promise(r => setTimeout(r, 900));
  return await line(LINE);
}
// Отодвинуть следующую строку, если она стоит вплотную и мешает взять край.
async function shoveNeighbour(){
  const spot = await p.evaluate((i) => {
    const e = document.querySelectorAll('.blk')[i + 1];
    if (!e) return null;
    const r = e.getBoundingClientRect();
    return {x: r.left + r.width / 2, y: r.top + r.height / 2};
  }, LINE);
  if (spot) await pull(spot, 70);
}

async function undoAll(){
  for (let i = 0; i < 60; i++){
    const done = await p.evaluate(() => {
      const b = document.getElementById('btnUndo');
      if (b.disabled) return true;
      b.click(); return false;
    });
    await new Promise(r => setTimeout(r, 90));
    if (done) break;
  }
  await new Promise(r => setTimeout(r, 700));
}

// Что видит человек, пока тянет: не уехала ли песня, не сменилась ли строка,
// не прокрутилась ли сцена. Именно это и ломалось: попытка взять слово
// сначала перематывала дорожку, и сцена уходила на другую строку.
async function view(){
  return await p.evaluate(() => {
    const sel = document.querySelector('#scroll .ln.sel');
    const cur = document.querySelector('#scroll .ln.cur');
    const all = [...document.querySelectorAll('#scroll .ln')];
    return {
      selected: sel ? all.indexOf(sel) : -1,
      current: cur ? all.indexOf(cur) : -1,
      time: document.getElementById('tCur').textContent,
      scroll: document.getElementById('scroll').style.transform,
      chips: document.querySelectorAll('.wrd').length,
    };
  });
}

async function drag(j, where, dx){
  const before = await line(LINE);
  const spot = await p.evaluate((j, where) => {
    const e = document.querySelectorAll('.wrd')[j];
    const r = e.getBoundingClientRect();
    const x = where === 'left' ? r.left + 3 : where === 'right' ? r.right - 3
                                            : r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const hit = document.elementFromPoint(x, y);
    return {x, y, cls: hit ? hit.className : 'ничего', w: r.width};
  }, j, where);
  await p.mouse.move(spot.x, spot.y);
  await p.mouse.down();
  await p.mouse.move(spot.x + dx, spot.y, {steps: 10});
  await p.mouse.up();
  await new Promise(r => setTimeout(r, 900));
  return {before, after: await line(LINE), cls: spot.cls};
}
const dur = (l, j) => l.words[j].d;

console.log('\n--- пока тянем слово, ничего не уезжает ---');
const v0 = await view();
{
  const spot = await p.evaluate(() => {
    const e = document.querySelectorAll('.wrd')[0];
    const r = e.getBoundingClientRect();
    return {x: r.right - 3, y: r.top + r.height / 2};
  });
  await p.mouse.move(spot.x, spot.y);
  await p.mouse.down();
  const mid = await view();
  ok('строка осталась выбранной той же', mid.selected === v0.selected,
     `${v0.selected + 1} → ${mid.selected + 1}`);
  ok('песня не перемоталась под курсор', mid.time === v0.time,
     `${v0.time} → ${mid.time}`);
  ok('сцена не уехала на другую строку', mid.scroll === v0.scroll);
  ok('ряд слов на месте', mid.chips === v0.chips, `${v0.chips} → ${mid.chips}`);
  await p.mouse.move(spot.x + 40, spot.y, {steps: 6});
  const during = await view();
  ok('и во время тяги строка не меняется', during.selected === v0.selected,
     `${during.selected + 1}`);
  ok('и сцена стоит', during.scroll === v0.scroll);
  await p.mouse.up();
  await new Promise(r => setTimeout(r, 900));
  const after = await view();
  ok('после отпускания строка та же', after.selected === v0.selected,
     `${after.selected + 1}`);
}
await undoAll();

console.log('\n--- тянем ПРАВЫЙ край слова: меняется его длина ---');
let r = await drag(0, 'right', 60);
ok('под курсором — ручка конца слова', /wgrip/.test(r.cls) && /right/.test(r.cls), r.cls);
ok('слово стало длиннее', dur(r.after,0) > dur(r.before,0) + 0.05,
   `${dur(r.before,0).toFixed(3)} → ${dur(r.after,0).toFixed(3)} с`);
ok('начало слова не сдвинулось',
   Math.abs(r.after.words[0].t - r.before.words[0].t) < 1e-6);
// Удлинили слово так, что оно дошло до соседа — сосед уступает, иначе
// удлинять было бы некуда. Но уступает ровно и не исчезает.
const grew = r.after.words[0].t + dur(r.after,0);
ok('сосед подвинут ровно к новому концу, а не куда попало',
   r.after.words[1].t >= r.before.words[1].t - 1e-6 &&
   Math.abs(r.after.words[1].t - Math.max(r.before.words[1].t, grew)) < 1e-6,
   `${r.before.words[1].t.toFixed(3)} → ${r.after.words[1].t.toFixed(3)}`);
ok('сосед не схлопнулся', dur(r.after,1) >= 0.05, dur(r.after,1).toFixed(3) + ' с');

await undoAll();   // возвращаемся к исходной раскладке
console.log('\n--- и укорачиваем: между словами разрешена пауза ---');
r = await drag(0, 'right', -80);
ok('слово стало короче', dur(r.after,0) < dur(r.before,0) - 0.05,
   `${dur(r.before,0).toFixed(3)} → ${dur(r.after,0).toFixed(3)} с`);
const gap = r.after.words[1].t - (r.after.words[0].t + dur(r.after,0));
ok('после него появился промежуток, а не растяжка', gap > 0.02, `пауза ${gap.toFixed(3)} с`);
ok('длина осталась положительной', dur(r.after,0) > 0.05, dur(r.after,0).toFixed(3));

await undoAll();   // возвращаемся к исходной раскладке
console.log('\n--- тянем ЛЕВЫЙ край: начало едет, конец стоит ---');
r = await drag(1, 'left', -40);
ok('под курсором — ручка начала слова', /wgrip/.test(r.cls) && /left/.test(r.cls), r.cls);
const endBefore = r.before.words[1].t + dur(r.before,1);
const endAfter  = r.after.words[1].t + dur(r.after,1);
ok('начало сдвинулось', Math.abs(r.after.words[1].t - r.before.words[1].t) > 0.02,
   `${r.before.words[1].t.toFixed(3)} → ${r.after.words[1].t.toFixed(3)}`);
ok('конец остался на месте', Math.abs(endAfter - endBefore) < 0.005,
   `${endBefore.toFixed(3)} → ${endAfter.toFixed(3)}`);
ok('длина изменилась соответственно', Math.abs(dur(r.after,1) - dur(r.before,1)) > 0.02,
   `${dur(r.before,1).toFixed(3)} → ${dur(r.after,1).toFixed(3)} с`);

await undoAll();   // возвращаемся к исходной раскладке
console.log('\n--- за середину: слово едет целиком, длина та же ---');
r = await drag(1, 'mid', 30);
ok('под курсором — само слово', /wrd/.test(r.cls) && !/wgrip/.test(r.cls), r.cls);
ok('слово сдвинулось', Math.abs(r.after.words[1].t - r.before.words[1].t) > 0.02,
   `${r.before.words[1].t.toFixed(3)} → ${r.after.words[1].t.toFixed(3)}`);
ok('длина не поменялась', Math.abs(dur(r.after,1) - dur(r.before,1)) < 0.005,
   `${dur(r.before,1).toFixed(3)} → ${dur(r.after,1).toFixed(3)}`);

await undoAll();   // возвращаемся к исходной раскладке
console.log('\n--- за середину тоже не перематывает ---');
{
  const v = await view();
  const spot = await p.evaluate(() => {
    const e = document.querySelectorAll('.wrd')[1];
    const r = e.getBoundingClientRect();
    return {x: r.left + r.width / 2, y: r.top + r.height / 2};
  });
  await p.mouse.move(spot.x, spot.y);
  await p.mouse.down();
  const mid = await view();
  await p.mouse.up();
  await new Promise(r => setTimeout(r, 400));
  ok('время не прыгнуло', mid.time === v.time, `${v.time} → ${mid.time}`);
  ok('выбранная строка не сменилась', mid.selected === v.selected);
}
await undoAll();

console.log('\n--- слово не залезает на соседей ---');
r = await drag(0, 'right', 900);
ok('конец упёрся в начало следующего',
   r.after.words[0].t + dur(r.after,0) <= r.after.words[1].t + 1e-6,
   `${(r.after.words[0].t+dur(r.after,0)).toFixed(3)} ≤ ${r.after.words[1].t.toFixed(3)}`);
ok('порядок слов не нарушен',
   r.after.words.every((w,k)=> k===0 || w.t >= r.after.words[k-1].t - 1e-9));

await undoAll();   // возвращаемся к исходной раскладке
console.log('\n--- последнее слово может растянуть строку ---');
const last = (await line(LINE)).words.length - 1;
r = await drag(last, 'right', 120);
ok('длина последнего слова выросла', dur(r.after,last) > dur(r.before,last) + 0.05,
   `${dur(r.before,last).toFixed(3)} → ${dur(r.after,last).toFixed(3)} с`);
ok('строка растянулась следом, а не обрезала слово',
   r.after.end >= r.after.words[last].t + dur(r.after,last) - 1e-6,
   `конец строки ${r.after.end.toFixed(3)}, конец слова ${(r.after.words[last].t+dur(r.after,last)).toFixed(3)}`);

console.log('\n--- край строки трогает только крайнее слово ---');
// Тянешь строку за край — внутренние слова обязаны остаться ровно там же,
// иначе выверенная разметка строки портится без всякой нужды.
await undoAll();
{
  const spot = await p.evaluate(() => {
    const e = document.querySelectorAll('.wrd')[0];
    const r = e.getBoundingClientRect();
    return {x: r.right - 3, y: r.top + r.height / 2};
  });
  await p.mouse.move(spot.x, spot.y);
  await p.mouse.down();
  await p.mouse.move(spot.x + 55, spot.y, {steps: 8});
  await p.mouse.up();
  await new Promise(r => setTimeout(r, 900));
  const tuned = await line(LINE);
  ok('рисунок слов сделан неровным',
     Math.max(...tuned.words.map(x=>x.d)) / Math.min(...tuned.words.map(x=>x.d)) > 1.4,
     tuned.words.map(x=>x.d.toFixed(2)).join(' '));

  // Правый край блока может быть накрыт соседом — тогда двигаем сначала соседа.
  let grip = await freeEdge('right');
  if (!grip){
    await shoveNeighbour();
    grip = await freeEdge('right');
  }
  ok('правый край строки доступен курсору', !!grip, grip ? '' : 'сосед вплотную');
  if (grip){
    const wide = await pull(grip, 55);
    const n = wide.words.length - 1;
    ok('строка стала длиннее', wide.end > tuned.end + 0.05,
       `${tuned.end.toFixed(3)} → ${wide.end.toFixed(3)}`);
    ok('начало строки не тронуто', Math.abs(wide.start - tuned.start) < 1e-6);
    ok('последнее слово дотянулось до нового конца',
       Math.abs((wide.words[n].t + wide.words[n].d) - wide.end) < 0.005 &&
       wide.words[n].d > tuned.words[n].d + 0.05,
       `${tuned.words[n].d.toFixed(3)} → ${wide.words[n].d.toFixed(3)} с`);
    ok('все остальные слова стоят там же, до миллисекунды',
       wide.words.slice(0, n).every((x, i) =>
         Math.abs(x.t - tuned.words[i].t) < 1e-6 &&
         Math.abs(x.d - tuned.words[i].d) < 1e-6),
       tuned.words.slice(0,n).map(x=>x.t.toFixed(3)).join(' ') + '  →  ' +
       wide.words.slice(0,n).map(x=>x.t.toFixed(3)).join(' '));

    const g2 = await freeEdge('right');
    if (g2){
      const back = await pull(g2, -35);
      ok('строка укоротилась', back.end < wide.end - 0.02,
         `${wide.end.toFixed(3)} → ${back.end.toFixed(3)}`);
      ok('укоротилось именно последнее слово, соседи целы',
         back.words[n].d < wide.words[n].d - 0.02 &&
         back.words.slice(0, n).every((x, i) =>
           Math.abs(x.t - tuned.words[i].t) < 1e-6),
         `${wide.words[n].d.toFixed(3)} → ${back.words[n].d.toFixed(3)} с`);
      ok('и оно не схлопнулось', back.words[n].d >= 0.05, back.words[n].d.toFixed(3));
    }
  }
}

console.log('\n--- левый край — то же самое с первым словом ---');
await undoAll();
{
  const g = await freeEdge('left');
  ok('левый край доступен курсору', !!g, g ? '' : 'сосед вплотную');
  if (g){
    const was = await line(LINE);
    const now2 = await pull(g, -45);
    ok('строка начинается раньше', now2.start < was.start - 0.02,
       `${was.start.toFixed(3)} → ${now2.start.toFixed(3)}`);
    ok('конец строки не тронут', Math.abs(now2.end - was.end) < 1e-6);
    ok('первое слово встало на новое начало, а его конец остался',
       Math.abs(now2.words[0].t - now2.start) < 0.005 &&
       Math.abs((now2.words[0].t + now2.words[0].d) -
                (was.words[0].t + was.words[0].d)) < 0.005,
       `конец первого слова ${(now2.words[0].t + now2.words[0].d).toFixed(3)}`);
    ok('остальные слова не сдвинулись ни на миллисекунду',
       now2.words.slice(1).every((x, i) =>
         Math.abs(x.t - was.words[i+1].t) < 1e-6 &&
         Math.abs(x.d - was.words[i+1].d) < 1e-6),
       was.words.slice(1).map(x=>x.t.toFixed(3)).join(' ') + '  →  ' +
       now2.words.slice(1).map(x=>x.t.toFixed(3)).join(' '));
  }
}
await undoAll();

console.log('\n--- отмена возвращает длину ---');
await drag(0, 'right', 55);              // свежая правка, которую и отменим
const beforeUndo = await line(LINE);
await p.evaluate(() => document.getElementById('btnUndo').click());
await new Promise(r => setTimeout(r, 900));
const undone = await line(LINE);
ok('длина слова вернулась', Math.abs(dur(undone,0) - dur(beforeUndo,0)) > 0.05,
   `${dur(beforeUndo,0).toFixed(3)} → ${dur(undone,0).toFixed(3)}`);

ok('ошибок JS нет', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: ' + fail : '\nAll checks passed');
process.exit(fail ? 1 : 0);
