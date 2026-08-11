// Требования, которые видно только на настоящей вёрстке: ничего не наезжает
// друг на друга, надписи читаемого размера и растут вместе с окном.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
// Удаление строки спрашивает подтверждение — родное окно браузера иначе
// подвесит всю проверку.
p.on('dialog', d => d.accept());
await p.setViewport({width:1366, height:768});
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(700);

console.log('--- надписи читаемого размера ---');
const sizes = async () => p.evaluate(() => {
  const px = el => el ? parseFloat(getComputedStyle(el).fontSize) : 0;
  return {root: parseFloat(getComputedStyle(document.documentElement).fontSize),
          button: px(document.querySelector('button')),
          card: px(document.querySelector('.card .badge'))};
});
const small = await sizes();
ok('кнопки не мельче 13px', small.button >= 13, small.button + 'px');
ok('мелкие подписи не мельче 12px', small.card >= 12, small.card + 'px');

await p.setViewport({width:2560, height:1440});
await sleep(400);
const big = await sizes();
ok('на широком экране надписи крупнее', big.root > small.root + 1,
   `${small.root} → ${big.root}`);
ok('и это не бесконечный рост', big.root <= 24, big.root + 'px');

console.log('\n--- редактор: ничего не наезжает ---');
// В тестовой песне вступление 2 с, а отсчёт показывается от 5 с. Раздвигаем
// разметку на диске, открываем окно заново и в конце возвращаем как было.
const original = (await proj()).lines;
const shifted = JSON.parse(JSON.stringify(original)).map(l => {
  l.start += 14; l.end += 14; l.words.forEach(w => { w.t += 14; });
  return l;
});
const put = async ls => fetch(API+'/api/project/'+encodeURIComponent(PID)+'/timings',
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({lines: ls})});
await put(shifted);
await p.reload({waitUntil:'networkidle0'});
await sleep(700);
await p.click('.card');
await sleep(2500);
await p.evaluate(() => document.getElementById('btnPlay').click());
await sleep(600);
await p.evaluate(() => document.getElementById('btnPlay').click());

const overlap = await p.evaluate(() => {
  const wait = document.getElementById('wait');
  if (wait.classList.contains('hide')) return {hidden:true};
  const r = wait.getBoundingClientRect();
  const hits = [...document.querySelectorAll('#scroll .ln')].filter(e => {
    const t = e.getBoundingClientRect();
    return t.width && t.height && !(t.right < r.left || t.left > r.right ||
                                    t.bottom < r.top || t.top > r.bottom);
  }).map(e => e.textContent.trim().slice(0, 20));
  return {hidden:false, hits, opacity: +getComputedStyle(wait).opacity,
          num: parseFloat(getComputedStyle(document.getElementById('waitNum')).fontSize)};
});
ok('отсчёт во вступлении показан', !overlap.hidden);
if (!overlap.hidden){
  ok('он не наезжает на строки песни', overlap.hits.length === 0, overlap.hits.join(' | '));
  ok('он не затенён', overlap.opacity > 0.95, String(overlap.opacity));
  ok('число в нём крупное', overlap.num >= 18, overlap.num + 'px');
}

console.log('\n--- панель дорожки помещается и подписана ---');
const head = await p.evaluate(() => {
  const h = document.querySelector('.tlhead');
  const picks = [...document.querySelectorAll('.pick')];
  return {fits: h.scrollWidth <= h.clientWidth + 2,
          labels: picks.map(x => (x.querySelector('b')||{}).textContent || ''),
          titled: [...document.querySelectorAll('.pick input')].every(i => i.title.length > 2)};
});
ok('панель не уезжает за край', head.fits);
ok('обе пары цветов подписаны', head.labels.length === 2 && head.labels.every(t => t.length > 2),
   head.labels.join(' | '));
ok('у каждого квадратика своя подсказка', head.titled);

console.log('\n--- сводка на месте и читается ---');
const sum = await p.evaluate(() => {
  const cells = [...document.querySelectorAll('.sum .c')];
  const b = cells[0] && cells[0].querySelector('b');
  return {n: cells.length, size: b ? parseFloat(getComputedStyle(b).fontSize) : 0,
          text: cells.map(c => c.textContent).join(' | ').slice(0, 80)};
});
ok('в сводке есть клетки', sum.n >= 4, String(sum.n));
ok('числа в ней крупные', sum.size >= 16, sum.size + 'px');

console.log('\n--- Delete удаляет выбранную строку ---');
await put(original);                    // стенд обратно, дальше работаем на нём
await p.reload({waitUntil:'networkidle0'});
await sleep(700);
await p.click('.card');
await sleep(2500);
const was = (await proj()).lines.length;
await p.evaluate(() => document.querySelectorAll('#scroll .ln')[1].click());
await sleep(200);
await p.keyboard.press('Delete');
await sleep(900);
const now = (await proj()).lines.length;
ok('строк стало меньше', now === was - 1, `${was} → ${now}`);
await p.evaluate(() => document.getElementById('btnUndo').click());
await sleep(900);
ok('и Ctrl+Z всё вернул', (await proj()).lines.length === was);

ok('ошибок JS нет', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
