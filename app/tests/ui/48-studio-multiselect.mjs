// Выделение нескольких строк и действия по всей пачке. Настоящий браузер:
// щелчок с Shift/Ctrl — это попадание курсором, jsdom его не считает.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());
const put = async ls => fetch(API+'/api/project/'+encodeURIComponent(PID)+'/timings',
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({lines: ls})});

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.accept());
await p.setViewport({width:1280, height:900});
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(700);
await p.click('.card');
await sleep(2400);

const original = (await proj()).lines;
// Кликаем только по строкам, которые и правда видно на сцене.
const spots = async () => p.evaluate(() => {
  const st = document.getElementById('stage').getBoundingClientRect();
  return [...document.querySelectorAll('#scroll .ln')].map((e, i) => {
    const r = e.getBoundingClientRect();
    return {i, x: r.left + r.width / 2, y: r.top + r.height / 2,
            ok: r.top > st.top + 4 && r.bottom < st.bottom - 4};
  }).filter(v => v.ok);
});
const marks = () => p.evaluate(() => ({
  n: document.querySelectorAll('#scroll .ln.mark').length,
  blocks: document.querySelectorAll('#blocks .blk.mark').length,
  note: document.getElementById('selNote').textContent}));
const hit = async (v, mods) => {
  if (mods) for (const m of mods) await p.keyboard.down(m);
  await p.mouse.click(v.x, v.y);
  if (mods) for (const m of mods) await p.keyboard.up(m);
  await sleep(250);
};

const vis = await spots();
ok('на сцене видно хотя бы четыре строки', vis.length >= 4, String(vis.length));

console.log('--- зажал и провёл ---');
// Самый ожидаемый способ: нажать на строке и протянуть по соседним.
await p.mouse.move(vis[0].x, vis[0].y);
await p.mouse.down();
for (let k = 1; k < 3; k++){
  await p.mouse.move(vis[k].x, vis[k].y, {steps: 4});
  await sleep(120);
}
await p.mouse.up();
await sleep(250);
let dm = await marks();
ok('протяжка по строкам выделяет их все', dm.n === 3, JSON.stringify(dm));
// Выделение должно быть видно, а не угадываться.
const seen = await p.evaluate(() => {
  const e = document.querySelector('#scroll .ln.mark');
  const cs = getComputedStyle(e);
  return {bg: cs.backgroundColor, shadow: cs.boxShadow.slice(0, 40),
          note: getComputedStyle(document.getElementById('selNote')).fontWeight};
});
ok('у выделенных строк видимая подсветка',
   seen.bg !== 'rgba(0, 0, 0, 0)' && /inset|rgb/.test(seen.shadow), JSON.stringify(seen));
ok('счётчик выделенного выделен жирным', +seen.note >= 600, seen.note);
ok('и на дорожке они тоже отмечены', dm.blocks === 3, JSON.stringify(dm));
// Дорожку перестраивают масштаб и правки — метки на блоках должны выживать.
await p.click('#btnZoomIn'); await sleep(200);
await p.click('#btnZoomOut'); await sleep(200);
dm = await marks();
ok('после перестройки дорожки блоки всё ещё отмечены', dm.blocks === 3,
   JSON.stringify(dm));
ok('и на сцене выделение никуда не делось', dm.n === 3, JSON.stringify(dm));

await p.mouse.click(vis[0].x, vis[0].y);
await sleep(250);
dm = await marks();
ok('обычный щелчок после протяжки снимает пачку', dm.n === 0, JSON.stringify(dm));
ok('и выбирает именно ту строку, по которой щёлкнули', /1/.test(dm.note), dm.note);
// протяжка вверх работает так же
await p.mouse.move(vis[2].x, vis[2].y);
await p.mouse.down();
await p.mouse.move(vis[0].x, vis[0].y, {steps: 6});
await sleep(150);
await p.mouse.up();
await sleep(250);
dm = await marks();
ok('протяжка снизу вверх тоже выделяет', dm.n === 3, JSON.stringify(dm));
await p.keyboard.press('Escape'); await sleep(200);

console.log('\n--- shift и ctrl набирают пачку ---');
await hit(vis[0]);
ok('обычный щелчок выделяет одну', (await marks()).n === 0, JSON.stringify(await marks()));
await hit(vis[2], ['Shift']);
let m = await marks();
ok('Shift+щелчок берёт подряд', m.n === 3, JSON.stringify(m));
ok('на дорожке отмечено столько же', m.blocks === 3, JSON.stringify(m));
ok('подпись говорит, сколько выделено', /3/.test(m.note), m.note);
await hit(vis[3], ['Control']);
m = await marks();
ok('Ctrl+щелчок добавляет по одной', m.n === 4, JSON.stringify(m));
// После Ctrl+щелчка опора переезжает на эту строку — так и в проводнике,
// и в редакторах: Shift дальше считает от неё.
await p.keyboard.down('Shift'); await p.keyboard.press('ArrowDown'); await p.keyboard.up('Shift');
await sleep(250);
m = await marks();
ok('Shift+стрелка считает от опоры', m.n === 2, JSON.stringify(m));
// А от обычного щелчка — растёт шаг за шагом, а не сбрасывается на каждой стрелке.
await hit(vis[0]);
await p.keyboard.down('Shift');
await p.keyboard.press('ArrowDown'); await sleep(150);
await p.keyboard.press('ArrowDown'); await sleep(150);
await p.keyboard.up('Shift');
await sleep(200);
m = await marks();
ok('Shift+стрелки набирают пачку подряд', m.n === 3, JSON.stringify(m));
await p.keyboard.press('Escape'); await sleep(200);
ok('Escape снимает пачку', (await marks()).n === 0, JSON.stringify(await marks()));

console.log('\n--- действия по всей пачке ---');
await hit(vis[0]);
await hit(vis[2], ['Shift']);
await p.click('#btnVoice'); await sleep(900);
let now = (await proj()).lines;
ok('второй голос встал сразу на три строки',
   [0,1,2].every(i => now[i].voice === 2), now.slice(0,4).map(l=>l.voice).join(' '));
ok('четвёртая строка не тронута', (now[3].voice || 1) === 1);
await p.click('#btnKeep'); await sleep(900);
now = (await proj()).lines;
ok('«оригинал» тоже лёг на всю пачку', [0,1,2].every(i => now[i].keep === true),
   now.slice(0,4).map(l => !!l.keep).join(' '));
await p.click('#btnUndo'); await sleep(700);
await p.click('#btnUndo'); await sleep(900);
now = (await proj()).lines;
ok('Ctrl+Z вернул всё как было',
   [0,1,2].every(i => (now[i].voice || 1) === (original[i].voice || 1) &&
                      !now[i].keep === !original[i].keep),
   now.slice(0,3).map(l => `${l.voice}/${!!l.keep}`).join(' '));

console.log('\n--- удаление пачкой ---');
await hit(vis[1]);
await hit(vis[2], ['Shift']);
const was = (await proj()).lines.length;
await p.keyboard.press('Delete');
await sleep(1000);
const after = (await proj()).lines.length;
ok('удалились обе выделенные', after === was - 2, `${was} → ${after}`);
await p.click('#btnUndo'); await sleep(900);
ok('и вернулись по Ctrl+Z', (await proj()).lines.length === was);

await put(original);
await sleep(300);
ok('ошибок JS нет', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
