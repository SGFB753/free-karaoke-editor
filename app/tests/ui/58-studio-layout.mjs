// The window at many sizes: nothing overlaps anything, nothing runs off the
// edge, no control is squeezed into a sliver. Two layout bugs got out to a
// person before this existed — a caption printed over the colour swatches, and
// the side panel drawn across the toolbar — and both were invisible to every
// other check we had.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.dismiss());

// What a person actually resizes to: a laptop, a half-screen window, a small
// one. The last is deliberately cramped — that is where things used to break.
const SIZES = [[1600, 900], [1366, 820], [1180, 760], [1024, 700], [900, 640]];

async function overflows(){
  return p.evaluate(() => {
    const d = document.documentElement;
    return {page: d.scrollWidth - d.clientWidth,
            body: document.body.scrollWidth - d.clientWidth};
  });
}

// Two boxes in the same visual row must not lie on top of each other. Rows are
// found by their tops: a wrapped flex row starts a new one.
async function collisions(sel){
  return p.evaluate(container => {
    const box = document.querySelector(container);
    if (!box) return [];
    const kids = [...box.children].filter(e => {
      const s = getComputedStyle(e);
      const r = e.getBoundingClientRect();
      return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
    }).map(e => ({tag: (e.id || e.className || e.tagName).toString().slice(0, 24),
                  r: e.getBoundingClientRect()}));
    const bad = [];
    for (let i = 0; i < kids.length; i++)
      for (let j = i + 1; j < kids.length; j++){
        const a = kids[i].r, c = kids[j].r;
        const sameRow = Math.abs(a.top - c.top) < 4;
        const over = Math.min(a.right, c.right) - Math.max(a.left, c.left);
        if (sameRow && over > 1) bad.push(`${kids[i].tag} × ${kids[j].tag} (${over.toFixed(0)}px)`);
      }
    return bad;
  }, sel);
}

async function tinyControls(sel){
  return p.evaluate(container => {
    const box = document.querySelector(container);
    if (!box) return [];
    return [...box.querySelectorAll("button, input, select")].filter(e => {
      const s = getComputedStyle(e);
      if (s.display === "none" || s.visibility === "hidden") return false;
      // A tick box and a colour swatch are small by their nature — a dozen
      // pixels each is exactly what they are meant to be.
      if (e.type === "checkbox" || e.type === "color" || e.type === "radio") return false;
      const r = e.getBoundingClientRect();
      return r.width > 0 && (r.width < 16 || r.height < 12);
    }).map(e => `${e.id || e.textContent.trim().slice(0, 14)}: ` +
                `${Math.round(e.getBoundingClientRect().width)}×` +
                `${Math.round(e.getBoundingClientRect().height)}`);
  }, sel);
}

async function panelOverToolbar(){
  return p.evaluate(() => {
    const side = document.querySelector(".side");
    const tl = document.querySelector(".timeline");
    if (!side || !tl) return 0;
    const a = side.getBoundingClientRect(), c = tl.getBoundingClientRect();
    const w = Math.min(a.right, c.right) - Math.max(a.left, c.left);
    const h = Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top);
    return (w > 1 && h > 1) ? Math.round(w * h) : 0;
  });
}

await p.goto(API + '/', {waitUntil:'networkidle0'});
await sleep(600);

console.log('--- the list of songs ---');
for (const [w, h] of SIZES){
  await p.setViewport({width: w, height: h});
  await sleep(300);
  const o = await overflows();
  ok(`${w}×${h}: nothing runs off sideways`, o.page <= 1 && o.body <= 1, JSON.stringify(o));
}

console.log('\n--- the screen for a new song ---');
await p.setViewport({width: 1366, height: 820});
await sleep(200);
await p.click('#btnAdd');
await sleep(300);
for (const [w, h] of SIZES){
  await p.setViewport({width: w, height: h});
  await sleep(300);
  const o = await overflows();
  ok(`${w}×${h}: nothing runs off sideways`, o.page <= 1 && o.body <= 1, JSON.stringify(o));
  const clash = await collisions('.form .opts');
  ok(`${w}×${h}: the options do not lie on each other`, clash.length === 0, clash.join('; '));
  const tiny = await tinyControls('#scrNew');
  ok(`${w}×${h}: nothing is squeezed to a sliver`, tiny.length === 0, tiny.join('; '));
}

console.log('\n--- the editor, where both bugs happened ---');
await p.setViewport({width: 1366, height: 820});
await sleep(200);
await p.click('#btnBackNew');
await sleep(400);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(800);

for (const [w, h] of SIZES){
  await p.setViewport({width: w, height: h});
  await sleep(400);
  const o = await overflows();
  ok(`${w}×${h}: nothing runs off sideways`, o.page <= 1 && o.body <= 1, JSON.stringify(o));

  const head = await collisions('#scrEdit > header');
  ok(`${w}×${h}: the top bar does not lie on itself`, head.length === 0, head.join('; '));

  const tools = await collisions('.tlhead');
  ok(`${w}×${h}: the toolbar does not lie on itself`, tools.length === 0, tools.join('; '));

  const over = await panelOverToolbar();
  ok(`${w}×${h}: the side panel keeps off the timeline`, over === 0, over + 'px²');

  // the caption inside a swatch pair must not run into the swatches
  const pick = await p.$$eval('.pick', els => els.map(el => {
    const b = el.querySelector('b'), i = el.querySelector('input[type=color]');
    if (!b || !i) return 0;
    return b.getBoundingClientRect().right - i.getBoundingClientRect().left;
  }));
  ok(`${w}×${h}: the colour captions keep off the swatches`,
     pick.every(v => v <= 0.5), JSON.stringify(pick.map(v => Math.round(v))));

  const tiny = await tinyControls('#scrEdit');
  ok(`${w}×${h}: nothing is squeezed to a sliver`, tiny.length === 0, tiny.join('; '));
}

ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
