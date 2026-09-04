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

const b = await puppeteer.launch({headless:'new',
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  args:['--no-sandbox','--disable-dev-shm-usage']});
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

async function formCentering(){
  return p.evaluate(() => {
    const list = document.querySelector('.screen:not(.hide) .list');
    if (!list) return null;
    const form = list.querySelector('.form');
    const cards = list.querySelector('.cards');
    const container = form || cards;
    if (!container) return null;
    const viewportCenter = document.documentElement.clientWidth / 2;
    // Measure visible children, not the wrapper
    const children = [...container.children].filter(e => {
      const s = getComputedStyle(e);
      return s.display !== 'none' && s.visibility !== 'hidden' &&
             e.getBoundingClientRect().width > 0;
    });
    if (children.length === 0) return null;
    let minX = Infinity, maxX = -Infinity;
    for (const el of children) {
      const r = el.getBoundingClientRect();
      minX = Math.min(minX, r.left);
      maxX = Math.max(maxX, r.right);
    }
    const contentCenter = (minX + maxX) / 2;
    return Math.abs(contentCenter - viewportCenter);
  });
}

// Inside .field: do the children start at the same left edge as .field itself?
async function fieldInternals(){
  return p.evaluate(() => {
    const fields = document.querySelectorAll('.screen:not(.hide) .form .field');
    const issues = [];
    for (const field of fields) {
      const fr = field.getBoundingClientRect();
      const fieldCs = getComputedStyle(field);
      const label = (field.querySelector('label') || {}).textContent || '';
      const fieldLeft = fr.left;
      for (const child of field.children) {
        const r = child.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const drift = Math.abs(r.left - fieldLeft);
        if (drift > 1) {
          issues.push(label.trim().slice(0,20) + ' child ' + (child.className || child.tagName).toString().slice(0,15) +
                     ': field.left=' + fieldLeft.toFixed(1) +
                     ' child.left=' + r.left.toFixed(1) +
                     ' drift=' + drift.toFixed(1));
        }
      }
    }
    return {issues, fieldCount: fields.length};
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
  const center = await formCentering();
  ok(`${w}×${h}: the cards are centered in the viewport`, center !== null && center <= 1,
     center !== null ? `offset ${center.toFixed(1)}px` : 'elements not found');
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
  const center = await formCentering();
  ok(`${w}×${h}: the form is centered in the viewport`, center !== null && center <= 1,
     center !== null ? `offset ${center.toFixed(1)}px` : 'elements not found');
  const fi = await fieldInternals();
  ok(`${w}×${h}: field children align to field left edge`,
     fi.issues.length === 0,
     fi.issues.length > 0 ? fi.issues.join('; ') : `${fi.fieldCount} fields OK`);
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
    const b = el.querySelector('b'), i = el.querySelector('.sw');
    if (!b || !i) return 0;
    return b.getBoundingClientRect().right - i.getBoundingClientRect().left;
  }));
  ok(`${w}×${h}: the colour captions keep off the swatches`,
     pick.every(v => v <= 0.5), JSON.stringify(pick.map(v => Math.round(v))));

  // The Check list must keep visible room whatever the summary holds: it used
  // to be squeezed to nothing and read as “the scrolling is broken”.
  const panel = await p.evaluate(() => {
    const probs = document.querySelector('.probs');
    const side = document.querySelector('.side');
    if (!probs || !side) return null;
    const a = probs.getBoundingClientRect(), b = side.getBoundingClientRect();
    return {h: a.height, inside: a.bottom <= b.bottom + 1 && a.top >= b.top - 1,
            scrollable: getComputedStyle(probs).overflowY};
  });
  ok(`${w}×${h}: the Check list keeps visible room`,
     panel && panel.h >= 40 && panel.inside, JSON.stringify(panel));
  ok(`${w}×${h}: and it is allowed to scroll`,
     panel && (panel.scrollable === 'auto' || panel.scrollable === 'scroll'),
     panel && panel.scrollable);

  const tiny = await tinyControls('#scrEdit');
  ok(`${w}×${h}: nothing is squeezed to a sliver`, tiny.length === 0, tiny.join('; '));
}

console.log('\n--- background survives entering and leaving a project ---');
await p.setViewport({width: 1366, height: 820});
await sleep(200);
// Go back to list
await p.evaluate(() => {
  const back = document.querySelector('#btnBack');
  if (back) back.click();
});
await sleep(500);
await p.waitForSelector('.card', {timeout:20000});
const bgBase = await p.evaluate(() => {
  const cs = getComputedStyle(document.body);
  return {
    background: cs.background,
    backgroundColor: cs.backgroundColor,
    backgroundImage: cs.backgroundImage,
  };
});
// The list screen must have a gradient, not a flat colour
ok('the list background is a gradient (not flat)',
   bgBase.backgroundImage.includes('linear-gradient'),
   `backgroundImage: ${bgBase.backgroundImage}`);
ok('the list background uses the default CSS values',
   bgBase.background.includes('10, 11, 20') && bgBase.background.includes('20, 24, 48'),
   `background: ${bgBase.background}`);
const bgBefore = bgBase;
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(800);
await p.evaluate(() => {
  const back = document.querySelector('#btnBack');
  if (back) back.click();
});
await sleep(500);
await p.waitForSelector('#scrList:not(.hide)', {timeout:20000});
const bgAfter = await p.evaluate(() => {
  const cs = getComputedStyle(document.body);
  return {
    background: cs.background,
    backgroundColor: cs.backgroundColor,
    backgroundImage: cs.backgroundImage,
  };
});
ok('the background is the same after leaving the project',
   bgBefore.background === bgAfter.background,
   `before: ${bgBefore.backgroundColor} ${bgBefore.backgroundImage}, after: ${bgAfter.backgroundColor} ${bgAfter.backgroundImage}`);

ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
