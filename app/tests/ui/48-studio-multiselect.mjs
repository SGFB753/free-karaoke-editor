// Selecting several lines and acting on the whole batch. A real browser:
// a Shift/Ctrl click is a cursor hit, and jsdom does not compute those.
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
await p.setViewport({width:1280, height:1000});
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(700);
await p.click('.card');
await sleep(2400);

const original = (await proj()).lines;
// Click only the lines that are really visible on stage.
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
const timelineSpots = () => p.evaluate(() => [...document.querySelectorAll('#blocks .blk')]
  .map((e, i) => {
    const r = e.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const hit = document.elementFromPoint(x, y);
    return {i, x, y, ok: r.width >= 24 && x > 4 && x < innerWidth - 4 &&
      !!(hit && hit.closest && hit.closest('.blk') === e)};
  }).filter(v => v.ok));
const hit = async (v, mods) => {
  if (mods) for (const m of mods) await p.keyboard.down(m);
  await p.mouse.click(v.x, v.y);
  if (mods) for (const m of mods) await p.keyboard.up(m);
  await sleep(250);
};

const vis = await spots();
ok('at least four lines are visible on stage', vis.length >= 4, String(vis.length));

console.log('--- press and drag ---');
// The most expected way: press on a line and drag across its neighbours.
await p.mouse.move(vis[0].x, vis[0].y);
await p.mouse.down();
for (let k = 1; k < 3; k++){
  await p.mouse.move(vis[k].x, vis[k].y, {steps: 4});
  await sleep(120);
}
await p.mouse.up();
await sleep(250);
let dm = await marks();
ok('dragging across the lines selects them all', dm.n === 3, JSON.stringify(dm));
// The selection must be visible, not guessed at.
const seen = await p.evaluate(() => {
  const e = document.querySelector('#scroll .ln.mark');
  const cs = getComputedStyle(e);
  return {bg: cs.backgroundColor, shadow: cs.boxShadow.slice(0, 40),
          after: getComputedStyle(e, '::after').content,
          note: getComputedStyle(document.getElementById('selNote')).fontWeight};
});
ok('the selected lines have a visible highlight',
   seen.bg !== 'rgba(0, 0, 0, 0)' && /inset|rgb/.test(seen.shadow), JSON.stringify(seen));
ok('selection uses one clean highlight without check-mark badges',
   seen.after === 'none' || seen.after === '', seen.after);
ok('the selection counter is in bold', +seen.note >= 600, seen.note);
ok('and they are marked on the timeline too', dm.blocks === 3, JSON.stringify(dm));
// Zooming and edits rebuild the timeline — the marks on the blocks must survive.
await p.click('#btnZoomIn'); await sleep(200);
await p.click('#btnZoomOut'); await sleep(200);
dm = await marks();
ok('after the timeline is rebuilt the blocks are still marked', dm.blocks === 3,
   JSON.stringify(dm));
ok('and the selection on stage did not go anywhere', dm.n === 3, JSON.stringify(dm));

await p.mouse.click(vis[0].x, vis[0].y);
await sleep(250);
dm = await marks();
ok('a plain click after the drag clears the batch', dm.n === 0, JSON.stringify(dm));
ok('and selects exactly the line that was clicked', /1/.test(dm.note), dm.note);
// dragging upwards works the same way
await p.mouse.move(vis[2].x, vis[2].y);
await p.mouse.down();
await p.mouse.move(vis[0].x, vis[0].y, {steps: 6});
await sleep(150);
await p.mouse.up();
await sleep(250);
dm = await marks();
ok('dragging bottom-up selects as well', dm.n === 3, JSON.stringify(dm));
await p.keyboard.press('Escape'); await sleep(200);

console.log('\n--- shift and ctrl build up a batch ---');
await hit(vis[0]);
ok('a plain click selects one', (await marks()).n === 0, JSON.stringify(await marks()));
await hit(vis[2], ['Shift']);
let m = await marks();
ok('Shift+click takes a run', m.n === 3, JSON.stringify(m));
ok('the timeline marks the same number', m.blocks === 3, JSON.stringify(m));
ok('the caption says how many are selected', /3/.test(m.note), m.note);
await hit(vis[3], ['Control']);
m = await marks();
ok('Ctrl+click adds them one by one', m.n === 4, JSON.stringify(m));
// After a Ctrl+click the anchor moves to that line — the same as in a file
// manager or an editor: Shift counts from it afterwards.
await p.keyboard.down('Shift'); await p.keyboard.press('ArrowDown'); await p.keyboard.up('Shift');
await sleep(250);
m = await marks();
ok('Shift+arrow counts from the anchor', m.n === 2, JSON.stringify(m));
// And from a plain click it grows step by step instead of resetting on every arrow.
await hit(vis[0]);
await p.keyboard.down('Shift');
await p.keyboard.press('ArrowDown'); await sleep(150);
await p.keyboard.press('ArrowDown'); await sleep(150);
await p.keyboard.up('Shift');
await sleep(200);
m = await marks();
ok('Shift+arrows build a contiguous batch', m.n === 3, JSON.stringify(m));
await p.keyboard.press('Escape'); await sleep(200);
ok('Escape clears the batch', (await marks()).n === 0, JSON.stringify(await marks()));

console.log('\n--- all lines, then exclude the bad piece ---');
await p.click('#btnSelectAll'); await sleep(250);
m = await marks();
ok('the button selects every line', m.n === original.length, JSON.stringify(m));
await hit(vis[1], ['Control']);
m = await marks();
ok('Ctrl+click removes one line from the full selection', m.n === original.length - 1,
   JSON.stringify(m));
await p.keyboard.press('Escape'); await sleep(150);
await p.keyboard.down('Control'); await p.keyboard.press('A'); await p.keyboard.up('Control');
await sleep(250);
m = await marks();
ok('Ctrl+A selects every line too', m.n === original.length, JSON.stringify(m));
await p.keyboard.press('Escape'); await sleep(150);

console.log('\n--- ctrl-click directly on timeline blocks ---');
const tls = await timelineSpots();
ok('at least three timeline blocks are reachable', tls.length >= 3, String(tls.length));
await hit(tls[0]);
await hit(tls[1], ['Control']);
m = await marks();
ok('the first Ctrl+click does not inherit the previously focused block',
   m.blocks === 1 && m.n === 1,
   JSON.stringify(m));
await hit(tls[2], ['Control']);
m = await marks();
ok('another Ctrl+click adds the second explicit block', m.blocks === 2 && m.n === 2,
   JSON.stringify(m));
await hit(tls[0], ['Control']);
m = await marks();
ok('the originally focused block joins only after its own Ctrl+click',
   m.blocks === 3 && m.n === 3, JSON.stringify(m));
const timelineStyles = await p.evaluate(() => [...document.querySelectorAll('#blocks .blk.mark')]
  .map(e => {
    const s = getComputedStyle(e);
    return [s.backgroundColor, s.borderColor, s.borderStyle, s.color].join('|');
  }));
ok('all selected timeline blocks look exactly alike', new Set(timelineStyles).size === 1,
   JSON.stringify(timelineStyles));
await hit(tls[1], ['Control']);
m = await marks();
ok('Ctrl+click on a selected timeline block removes only it', m.blocks === 2 && m.n === 2,
   JSON.stringify(m));
const beforeGroup = (await proj()).lines;
await p.mouse.move(tls[0].x, tls[0].y);
await p.mouse.down();
await p.mouse.move(tls[0].x + 70, tls[0].y, {steps: 8});
await p.mouse.up();
await sleep(900);
const afterGroup = (await proj()).lines;
const movedIds = [tls[0].i, tls[2].i];
const shifts = movedIds.map(i => afterGroup[i].start - beforeGroup[i].start);
ok('dragging one selected block moves the whole timeline batch',
   shifts.every(d => Math.abs(d) > .05) && Math.abs(shifts[0] - shifts[1]) < .002,
   shifts.map(d => d.toFixed(3)).join(' / '));
ok('the unselected block stays where it was',
   Math.abs(afterGroup[tls[1].i].start - beforeGroup[tls[1].i].start) < .002);
ok('line lengths stay unchanged during a batch move', movedIds.every(i =>
   Math.abs((afterGroup[i].end - afterGroup[i].start) -
            (beforeGroup[i].end - beforeGroup[i].start)) < .002));
ok('word timing moves by the very same amount', movedIds.every((i, k) =>
   afterGroup[i].words.every((w, j) =>
     Math.abs((w.t - beforeGroup[i].words[j].t) - shifts[k]) < .002)));
await p.click('#btnUndo'); await sleep(900);
await p.keyboard.press('Escape'); await sleep(150);

console.log('\n--- actions over the whole batch ---');
await hit(vis[0]);
await hit(vis[2], ['Shift']);
await p.click('#btnVoice'); await sleep(900);
let now = (await proj()).lines;
ok('the second voice landed on three lines at once',
   [0,1,2].every(i => now[i].voice === 2), now.slice(0,4).map(l=>l.voice).join(' '));
ok('the fourth line was not touched', (now[3].voice || 1) === 1);
await p.click('#btnKeep'); await sleep(900);
now = (await proj()).lines;
ok('“original” also landed on the whole batch', [0,1,2].every(i => now[i].keep === true),
   now.slice(0,4).map(l => !!l.keep).join(' '));
await p.click('#btnUndo'); await sleep(700);
await p.click('#btnUndo'); await sleep(900);
now = (await proj()).lines;
ok('Ctrl+Z put everything back',
   [0,1,2].every(i => (now[i].voice || 1) === (original[i].voice || 1) &&
                      !now[i].keep === !original[i].keep),
   now.slice(0,3).map(l => `${l.voice}/${!!l.keep}`).join(' '));

console.log('\n--- deleting as a batch ---');
await hit(vis[1]);
await hit(vis[2], ['Shift']);
const was = (await proj()).lines.length;
await p.keyboard.press('Delete');
await sleep(1000);
const after = (await proj()).lines.length;
ok('both selected lines were deleted', after === was - 2, `${was} → ${after}`);
await p.click('#btnUndo'); await sleep(900);
ok('and Ctrl+Z brought them back', (await proj()).lines.length === was);

await put(original);
await sleep(300);
ok('no JS errors', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
