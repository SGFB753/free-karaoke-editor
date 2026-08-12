// The length of a word. It could not be set at all before: a word stretched to
// the next one, and “where it ends” was not a separate value in the first place.
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

// Take a line whose words are wide enough: narrow ones get no grips drawn.
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
ok('found a line with words of decent width', true, 'line ' + (LINE+1));

// Is the edge of the block free to grab: a neighbour may be covering it.
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
// Push the next line away if it sits flush and blocks the edge.
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

// What a person sees while dragging: did the song run off, did the line change,
// did the stage scroll. That is exactly what used to break: grabbing a word
// first seeked the timeline, and the stage jumped to another line.
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
    return {x, y, cls: hit ? hit.className : 'nothing', w: r.width};
  }, j, where);
  await p.mouse.move(spot.x, spot.y);
  await p.mouse.down();
  await p.mouse.move(spot.x + dx, spot.y, {steps: 10});
  await p.mouse.up();
  await new Promise(r => setTimeout(r, 900));
  return {before, after: await line(LINE), cls: spot.cls};
}
const dur = (l, j) => l.words[j].d;

console.log('\n--- while a word is dragged nothing runs away ---');
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
  ok('the same line stayed selected', mid.selected === v0.selected,
     `${v0.selected + 1} → ${mid.selected + 1}`);
  ok('the song did not seek under the cursor', mid.time === v0.time,
     `${v0.time} → ${mid.time}`);
  ok('the stage did not jump to another line', mid.scroll === v0.scroll);
  ok('the word row is in place', mid.chips === v0.chips, `${v0.chips} → ${mid.chips}`);
  await p.mouse.move(spot.x + 40, spot.y, {steps: 6});
  const during = await view();
  ok('and during the drag the line does not change', during.selected === v0.selected,
     `${during.selected + 1}`);
  ok('and the stage stands still', during.scroll === v0.scroll);
  await p.mouse.up();
  await new Promise(r => setTimeout(r, 900));
  const after = await view();
  ok('after release it is the same line', after.selected === v0.selected,
     `${after.selected + 1}`);
}
await undoAll();

console.log("\n--- dragging the word's RIGHT edge: its length changes ---");
let r = await drag(0, 'right', 60);
ok('under the cursor — the word-end grip', /wgrip/.test(r.cls) && /right/.test(r.cls), r.cls);
ok('the word got longer', dur(r.after,0) > dur(r.before,0) + 0.05,
   `${dur(r.before,0).toFixed(3)} → ${dur(r.after,0).toFixed(3)} s`);
ok('the word start did not move',
   Math.abs(r.after.words[0].t - r.before.words[0].t) < 1e-6);
// The word was stretched until it reached its neighbour — the neighbour gives
// way, or there would be nowhere to stretch. But it gives way exactly, and stays.
const grew = r.after.words[0].t + dur(r.after,0);
ok('the neighbour moved exactly to the new end, not somewhere random',
   r.after.words[1].t >= r.before.words[1].t - 1e-6 &&
   Math.abs(r.after.words[1].t - Math.max(r.before.words[1].t, grew)) < 1e-6,
   `${r.before.words[1].t.toFixed(3)} → ${r.after.words[1].t.toFixed(3)}`);
ok('the neighbour did not collapse', dur(r.after,1) >= 0.05, dur(r.after,1).toFixed(3) + ' s');

await undoAll();   // back to the original layout
console.log('\n--- and shortening: a gap between words is allowed ---');
r = await drag(0, 'right', -80);
ok('the word got shorter', dur(r.after,0) < dur(r.before,0) - 0.05,
   `${dur(r.before,0).toFixed(3)} → ${dur(r.after,0).toFixed(3)} s`);
const gap = r.after.words[1].t - (r.after.words[0].t + dur(r.after,0));
ok('a gap appeared after it, not a stretch', gap > 0.02, `gap ${gap.toFixed(3)} s`);
ok('the length stayed positive', dur(r.after,0) > 0.05, dur(r.after,0).toFixed(3));

await undoAll();   // back to the original layout
console.log('\n--- dragging the LEFT edge: the start moves, the end stays ---');
r = await drag(1, 'left', -40);
ok('under the cursor — the word-start grip', /wgrip/.test(r.cls) && /left/.test(r.cls), r.cls);
const endBefore = r.before.words[1].t + dur(r.before,1);
const endAfter  = r.after.words[1].t + dur(r.after,1);
ok('the start moved', Math.abs(r.after.words[1].t - r.before.words[1].t) > 0.02,
   `${r.before.words[1].t.toFixed(3)} → ${r.after.words[1].t.toFixed(3)}`);
ok('the end stayed put', Math.abs(endAfter - endBefore) < 0.005,
   `${endBefore.toFixed(3)} → ${endAfter.toFixed(3)}`);
ok('the length changed accordingly', Math.abs(dur(r.after,1) - dur(r.before,1)) > 0.02,
   `${dur(r.before,1).toFixed(3)} → ${dur(r.after,1).toFixed(3)} s`);

await undoAll();   // back to the original layout
console.log('\n--- by the middle: the word moves whole, same length ---');
r = await drag(1, 'mid', 30);
ok('under the cursor — the word itself', /wrd/.test(r.cls) && !/wgrip/.test(r.cls), r.cls);
ok('the word moved', Math.abs(r.after.words[1].t - r.before.words[1].t) > 0.02,
   `${r.before.words[1].t.toFixed(3)} → ${r.after.words[1].t.toFixed(3)}`);
ok('the length did not change', Math.abs(dur(r.after,1) - dur(r.before,1)) < 0.005,
   `${dur(r.before,1).toFixed(3)} → ${dur(r.after,1).toFixed(3)}`);

await undoAll();   // back to the original layout
console.log('\n--- the middle does not seek either ---');
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
  ok('the time did not jump', mid.time === v.time, `${v.time} → ${mid.time}`);
  ok('the selected line did not change', mid.selected === v.selected);
}
await undoAll();

console.log('\n--- a word does not climb onto its neighbours ---');
r = await drag(0, 'right', 900);
ok('the end stopped at the start of the next one',
   r.after.words[0].t + dur(r.after,0) <= r.after.words[1].t + 1e-6,
   `${(r.after.words[0].t+dur(r.after,0)).toFixed(3)} ≤ ${r.after.words[1].t.toFixed(3)}`);
ok('the word order is intact',
   r.after.words.every((w,k)=> k===0 || w.t >= r.after.words[k-1].t - 1e-9));

await undoAll();   // back to the original layout
console.log('\n--- the last word may stretch the line ---');
const last = (await line(LINE)).words.length - 1;
r = await drag(last, 'right', 120);
ok('the last word got longer', dur(r.after,last) > dur(r.before,last) + 0.05,
   `${dur(r.before,last).toFixed(3)} → ${dur(r.after,last).toFixed(3)} s`);
ok('the line stretched after it instead of cutting the word',
   r.after.end >= r.after.words[last].t + dur(r.after,last) - 1e-6,
   `line end ${r.after.end.toFixed(3)}, word end ${(r.after.words[last].t+dur(r.after,last)).toFixed(3)}`);

console.log('\n--- a line edge touches only the outermost word ---');
// Drag a line by its edge and the words inside must stay exactly where they
// were, or a carefully tuned line is spoiled for no reason at all.
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
  ok('the word pattern was made uneven',
     Math.max(...tuned.words.map(x=>x.d)) / Math.min(...tuned.words.map(x=>x.d)) > 1.4,
     tuned.words.map(x=>x.d.toFixed(2)).join(' '));

  // The right edge of a block may be covered by a neighbour — move that one first.
  let grip = await freeEdge('right');
  if (!grip){
    await shoveNeighbour();
    grip = await freeEdge('right');
  }
  ok('the right edge of the line is reachable', !!grip, grip ? '' : 'the neighbour is flush');
  if (grip){
    const wide = await pull(grip, 55);
    const n = wide.words.length - 1;
    ok('the line got longer', wide.end > tuned.end + 0.05,
       `${tuned.end.toFixed(3)} → ${wide.end.toFixed(3)}`);
    ok('the line start is untouched', Math.abs(wide.start - tuned.start) < 1e-6);
    ok('the last word reached the new end',
       Math.abs((wide.words[n].t + wide.words[n].d) - wide.end) < 0.005 &&
       wide.words[n].d > tuned.words[n].d + 0.05,
       `${tuned.words[n].d.toFixed(3)} → ${wide.words[n].d.toFixed(3)} s`);
    ok('every other word is exactly where it was, to the millisecond',
       wide.words.slice(0, n).every((x, i) =>
         Math.abs(x.t - tuned.words[i].t) < 1e-6 &&
         Math.abs(x.d - tuned.words[i].d) < 1e-6),
       tuned.words.slice(0,n).map(x=>x.t.toFixed(3)).join(' ') + '  →  ' +
       wide.words.slice(0,n).map(x=>x.t.toFixed(3)).join(' '));

    const g2 = await freeEdge('right');
    if (g2){
      const back = await pull(g2, -35);
      ok('the line got shorter', back.end < wide.end - 0.02,
         `${wide.end.toFixed(3)} → ${back.end.toFixed(3)}`);
      ok('it is the last word that shrank, the neighbours are intact',
         back.words[n].d < wide.words[n].d - 0.02 &&
         back.words.slice(0, n).every((x, i) =>
           Math.abs(x.t - tuned.words[i].t) < 1e-6),
         `${wide.words[n].d.toFixed(3)} → ${back.words[n].d.toFixed(3)} s`);
      ok('and it did not collapse', back.words[n].d >= 0.05, back.words[n].d.toFixed(3));
    }
  }
}

console.log('\n--- the left edge — the same with the first word ---');
await undoAll();
{
  const g = await freeEdge('left');
  ok('the left edge is reachable with the cursor', !!g, g ? '' : 'the neighbour is flush');
  if (g){
    const was = await line(LINE);
    const now2 = await pull(g, -45);
    ok('the line starts earlier', now2.start < was.start - 0.02,
       `${was.start.toFixed(3)} → ${now2.start.toFixed(3)}`);
    ok('the end of the line was not touched', Math.abs(now2.end - was.end) < 1e-6);
    ok('the first word took the new start while its end stayed',
       Math.abs(now2.words[0].t - now2.start) < 0.005 &&
       Math.abs((now2.words[0].t + now2.words[0].d) -
                (was.words[0].t + was.words[0].d)) < 0.005,
       `end of the first word ${(now2.words[0].t + now2.words[0].d).toFixed(3)}`);
    ok('the other words did not move by a millisecond',
       now2.words.slice(1).every((x, i) =>
         Math.abs(x.t - was.words[i+1].t) < 1e-6 &&
         Math.abs(x.d - was.words[i+1].d) < 1e-6),
       was.words.slice(1).map(x=>x.t.toFixed(3)).join(' ') + '  →  ' +
       now2.words.slice(1).map(x=>x.t.toFixed(3)).join(' '));
  }
}
await undoAll();

console.log('\n--- undo brings the length back ---');
await drag(0, 'right', 55);              // a fresh edit, the one we will undo
const beforeUndo = await line(LINE);
await p.evaluate(() => document.getElementById('btnUndo').click());
await new Promise(r => setTimeout(r, 900));
const undone = await line(LINE);
ok('the word length came back', Math.abs(dur(undone,0) - dur(beforeUndo,0)) > 0.05,
   `${dur(beforeUndo,0).toFixed(3)} → ${dur(undone,0).toFixed(3)}`);

ok('no JS errors', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: ' + fail : '\nAll checks passed');
process.exit(fail ? 1 : 0);
