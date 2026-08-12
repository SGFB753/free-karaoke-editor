// A real mouse: jsdom never checks whether the cursor actually hits anything,
// and that is exactly where the trouble hid — the left edge had nothing to grab.
import puppeteer from 'puppeteer';
const API = process.env.KARAOKE_API;
const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
p.on('pageerror', e => console.log('JS ERROR:', String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));

const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const srv = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json()).lines;
let fail = 0;
const ok = (n,c,e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };

// Look for a block whose spot is really reachable with the cursor: neighbours
// may lie on top, and then the click goes to them, not to what we aimed at.
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
    return {x, y, hit: hit ? hit.className : 'nothing', w: r.width};
  }, i, where);
  await p.mouse.move(box.x, box.y);
  await p.mouse.down();
  await p.mouse.move(box.x + dx, box.y, {steps: 10});
  await p.mouse.up();
  await new Promise(r=>setTimeout(r,900));
  return {before, after: (await srv())[i], hit: box.hit};
}

console.log('--- by the left edge: the start moves ---');
let idx = await pick('left');
ok('found a block with a free left edge', idx >= 0, 'block ' + (idx+1));
let r = await grab(idx, 'left', 60);
ok('under the cursor at the left edge — a grip', /grip/.test(r.hit), r.hit);
ok('the line start moved', Math.abs(r.after.start - r.before.start) > 0.05,
   `${r.before.start.toFixed(3)} → ${r.after.start.toFixed(3)}`);
ok('the line end stayed put', Math.abs(r.after.end - r.before.end) < 1e-6,
   `${r.before.end.toFixed(3)} → ${r.after.end.toFixed(3)}`);
ok('the words were re-laid inside the new length',
   r.after.words[0].t >= r.after.start - 1e-6 &&
   r.after.words.at(-1).t + r.after.words.at(-1).d <= r.after.end + 1e-6);

console.log('\n--- by the right edge: the end moves ---');
idx = await pick('right');
ok('found a block with a free right edge', idx >= 0, 'block ' + (idx+1));
r = await grab(idx, 'right', 70);
ok('under the cursor at the right edge — a grip', /grip/.test(r.hit), r.hit);
ok('the end moved', Math.abs(r.after.end - r.before.end) > 0.05,
   `${r.before.end.toFixed(3)} → ${r.after.end.toFixed(3)}`);
ok('the start stayed', Math.abs(r.after.start - r.before.start) < 1e-6);

console.log('\n--- by the middle: the whole line moves ---');
idx = await pick('mid');
ok('found a block with a free middle', idx >= 0, 'block ' + (idx+1));
r = await grab(idx, 'mid', 80);
ok('under the cursor — the block itself', /blk/.test(r.hit) && !/grip/.test(r.hit), r.hit);
ok('the line moved as a whole',
   Math.abs(r.after.start - r.before.start) > 0.05 &&
   Math.abs((r.after.end - r.after.start) - (r.before.end - r.before.start)) < 0.01,
   `${r.before.start.toFixed(2)}–${r.before.end.toFixed(2)} → ${r.after.start.toFixed(2)}–${r.after.end.toFixed(2)}`);

console.log('\n--- the very first block drags too ---');
await p.evaluate(() => document.getElementById('btnUndo').click());
await new Promise(r=>setTimeout(r,600));
r = await grab(0, 'mid', 50);
ok('the very first block moves', Math.abs(r.after.start - r.before.start) > 0.05,
   `${r.before.start.toFixed(3)} → ${r.after.start.toFixed(3)}`);

console.log('\n--- a word drags with a real mouse ---');
const wr = await p.evaluate(() => {
  const c = [...document.querySelectorAll('.wrd')];
  if (!c.length) return null;
  const r = c[c.length-1].getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
  return {cls: hit ? hit.className : 'nothing',
          // what matters is not “which element” but whether the press reaches the word
          mine: !!(hit && hit.closest && hit.closest('.wrd') === c[c.length-1])};
});
ok('a press on a word reaches the word', wr && wr.mine, wr ? wr.cls : 'no words');

await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
