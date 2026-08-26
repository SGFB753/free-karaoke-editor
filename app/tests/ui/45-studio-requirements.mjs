// The requirements only a real layout can show: nothing overlaps anything else,
// the labels are of a readable size and grow along with the window.
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
// Deleting a line asks for confirmation — the browser's own dialog would
// otherwise hang the whole check.
p.on('dialog', d => d.accept());
await p.setViewport({width:1366, height:768});
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(700);

console.log('--- labels of a readable size ---');
const sizes = async () => p.evaluate(() => {
  const px = el => el ? parseFloat(getComputedStyle(el).fontSize) : 0;
  return {root: parseFloat(getComputedStyle(document.documentElement).fontSize),
          button: px(document.querySelector('button')),
          card: px(document.querySelector('.card .badge'))};
});
const small = await sizes();
ok('the buttons are no smaller than 13px', small.button >= 13, small.button + 'px');
ok('the small labels are no smaller than 12px', small.card >= 12, small.card + 'px');

await p.setViewport({width:2560, height:1440});
await sleep(400);
const big = await sizes();
ok('on a wide screen the labels are bigger', big.root > small.root + 1,
   `${small.root} → ${big.root}`);
ok('and the growth is not endless', big.root <= 24, big.root + 'px');

console.log('\n--- the editor: nothing overlaps ---');
// In the test song the intro is 2 s, while the countdown shows from 5 s. We
// stretch the timing on disk, reopen the window and put it all back at the end.
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
ok('the intro countdown is shown', !overlap.hidden);
if (!overlap.hidden){
  ok('it does not overlap the lines of the song', overlap.hits.length === 0, overlap.hits.join(' | '));
  ok('it is not dimmed', overlap.opacity > 0.95, String(overlap.opacity));
  ok('the number in it is large', overlap.num >= 18, overlap.num + 'px');
}

console.log('\n--- the timeline panel fits and is labelled ---');
const head = await p.evaluate(() => {
  const h = document.querySelector('.tlhead');
  const picks = [...document.querySelectorAll('.pick')];
  return {fits: h.scrollWidth <= h.clientWidth + 2,
          labels: picks.map(x => (x.querySelector('b')||{}).textContent || ''),
          // the swatches are buttons of the program's own now
          titled: [...document.querySelectorAll('.pick .sw')].every(i => i.title.length > 2)};
});
ok('the panel does not run off the edge', head.fits);
ok('both colour pairs are labelled', head.labels.length === 2 && head.labels.every(t => t.length > 2),
   head.labels.join(' | '));
ok('each swatch has its own tooltip', head.titled);

console.log('\n--- the summary is in place and readable ---');
const sum = await p.evaluate(() => {
  const cells = [...document.querySelectorAll('.sum .c')];
  const b = cells[0] && cells[0].querySelector('b');
  return {n: cells.length, size: b ? parseFloat(getComputedStyle(b).fontSize) : 0,
          text: cells.map(c => c.textContent).join(' | ').slice(0, 80)};
});
ok('the summary has cells', sum.n >= 4, String(sum.n));
ok('the numbers in it are large', sum.size >= 16, sum.size + 'px');

console.log('\n--- Delete removes the selected line ---');
await put(original);                    // the stand back, we work on it from here
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
ok('there are fewer lines', now === was - 1, `${was} → ${now}`);
await p.evaluate(() => document.getElementById('btnUndo').click());
await sleep(900);
ok('and Ctrl+Z brought it all back', (await proj()).lines.length === was);

ok('no JS errors', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
