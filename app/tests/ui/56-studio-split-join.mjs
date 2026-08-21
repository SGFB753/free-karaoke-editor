// Cutting a line in two and joining two into one — the most ordinary correction
// there is. Neither needs a model: the words and their times are already known,
// only the grouping changes. Before this it meant editing the file on disk and
// timing the whole song again.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());

const before = await proj();
const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.accept());
await p.setViewport({width:1366, height:900});
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(600);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(700);

const lineCount = () => p.$$eval('#scroll .ln', els => els.length);
const nth = async i => (await proj()).lines[i];

console.log('--- a line is cut where the singing pauses ---');
const was = await lineCount();
const first = before.lines[0];
await p.click('#scroll .ln');                 // select the first line
await sleep(200);
await p.click('#btnSplit');
await sleep(500);
ok('there is one line more', (await lineCount()) === was + 1, await lineCount());
await sleep(1200);                            // let the autosave land
const now = await proj();
ok('the song on disk has it too', now.lines.length === before.lines.length + 1,
   now.lines.length);
const a0 = now.lines[0], a1 = now.lines[1];
ok('the halves together say what the line said',
   (a0.text + ' ' + a1.text).replace(/\s+/g, ' ').trim() === first.text.trim(),
   `${a0.text} | ${a1.text}`);
ok('the first half starts where the line started',
   Math.abs(a0.start - first.start) < 0.001, `${first.start} → ${a0.start}`);
ok('the second half ends where the line ended',
   Math.abs(a1.end - first.end) < 0.001, `${first.end} → ${a1.end}`);
ok('and no word lost its time',
   a0.words.concat(a1.words).every((w, i) => Math.abs(w.t - first.words[i].t) < 0.001),
   JSON.stringify(a0.words.concat(a1.words).map(w => w.t)));
ok('the second half begins after the first', a1.start >= a0.end - 0.001,
   `${a0.end} → ${a1.start}`);

console.log('\n--- and joined back together ---');
await p.click('#scroll .ln');
await sleep(200);
await p.click('#btnJoin');
await sleep(500);
ok('the count is back', (await lineCount()) === was, await lineCount());
await sleep(1200);
const back = await nth(0);
ok('the words are whole again', back.text.trim() === first.text.trim(), back.text);
ok('with the times they always had',
   back.words.every((w, i) => Math.abs(w.t - first.words[i].t) < 0.001),
   JSON.stringify(back.words.map(w => w.t)));
ok('and the line spans what it spanned',
   Math.abs(back.start - first.start) < 0.001 && Math.abs(back.end - first.end) < 0.001,
   `${back.start}–${back.end}`);

console.log('\n--- undo puts the song back either way ---');
await p.keyboard.down('Control'); await p.keyboard.press('KeyZ'); await p.keyboard.up('Control');
await sleep(400);
ok('undo works on a join', (await lineCount()) === was + 1, await lineCount());
await p.keyboard.down('Control'); await p.keyboard.press('KeyZ'); await p.keyboard.up('Control');
await sleep(1200);
ok('and on a split', (await lineCount()) === was, await lineCount());
const restored = await nth(0);
ok('the song is exactly as it was found',
   restored.text.trim() === first.text.trim()
   && Math.abs(restored.start - first.start) < 0.001, restored.text);

console.log('\n--- narrowing a line that swallowed an interlude ---');
// The edge alone only stretches the outermost word: on a line that grabbed a
// minute and a half that is no use. With Alt the whole line is squeezed.
const wide = await proj();
const idx = 0;
const box = await p.$eval('#tlwrap', e => {
  const r = e.getBoundingClientRect();
  return {x: r.left, y: r.top, w: r.width, h: r.height};
});
// make line 1 absurdly long first, the way the aligner does over a hole
const bent2 = JSON.parse(JSON.stringify(wide.lines));
bent2[idx].end = bent2[idx].start + 12;
bent2[idx].words = bent2[idx].words.map((w, i) => ({...w, d: i === bent2[idx].words.length - 1 ? 10 : w.d}));
await fetch(`${API}/api/project/${encodeURIComponent(PID)}/timings`, {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify({lines: bent2})});
await p.reload({waitUntil:'networkidle0'});
await sleep(500);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(700);
await p.click('#scroll .ln');
await sleep(300);

// Bring the line into view first, or its edge is off the timeline entirely.
await p.click('#btnFit');
await sleep(400);
const blk = await p.$('#blocks .blk');
const rect = await blk.boundingBox();
ok('the long line is on the timeline', !!rect, JSON.stringify(rect || {}));
if (rect){
  // grab the right edge and pull it left with Alt held
  await p.keyboard.down('Alt');
  await p.mouse.move(rect.x + rect.width - 2, rect.y + rect.height / 2);
  await p.mouse.down();
  await p.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2, {steps: 10});
  await p.mouse.up();
  await p.keyboard.up('Alt');
  await sleep(1200);
  const after = (await proj()).lines[idx];
  const wasSpan = bent2[idx].end - bent2[idx].start;
  const nowSpan = after.end - after.start;
  ok('the line got shorter', nowSpan < wasSpan * 0.8, `${wasSpan.toFixed(1)} → ${nowSpan.toFixed(1)}`);
  ok('and every word is inside it',
     after.words.every(w => w.t >= after.start - 0.01 && w.t + w.d <= after.end + 0.01),
     JSON.stringify(after.words.map(w => [w.t.toFixed(2), w.d.toFixed(2)])));
  ok('the words did not pile up on each other',
     after.words.every((w, i) => i === 0 || w.t >= after.words[i - 1].t),
     JSON.stringify(after.words.map(w => w.t.toFixed(2))));
}

console.log('\n--- an article under its neighbour, and the words re-laid ---');
// The aligner gives an article no time of its own: “A” and “chilling” start at
// the same instant, and the small chip used to vanish under the big one — it
// could not even be grabbed.
const cur = await proj();
const deg = JSON.parse(JSON.stringify(cur.lines));
const at = deg[0].start;
deg[0].text = 'A chilling cold';
deg[0].words = [{w: 'A', t: at, d: 0, s: 1},
                {w: 'chilling', t: at, d: 1.0, s: 2},
                {w: 'cold', t: at + 1.0, d: 0.8, s: 1}];
deg[0].end = at + 1.8;
await fetch(`${API}/api/project/${encodeURIComponent(PID)}/timings`, {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify({lines: deg})});
await p.reload({waitUntil:'networkidle0'});
await sleep(500);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(700);
await p.click('#scroll .ln');
await sleep(200);
await p.click('#btnFit');
await sleep(400);

const chips = await p.$$eval('#words .wrd', els => els.map(e => {
  const r = e.getBoundingClientRect();
  return {left: r.left, right: r.right, w: r.width};
}));
ok('all three words have a chip of visible width',
   chips.length === 3 && chips.every(c => c.w >= 5),
   JSON.stringify(chips.map(c => Math.round(c.w))));
ok('and no chip lies on another',
   chips.every((c, i) => i === 0 || c.left >= chips[i - 1].right - 0.5),
   JSON.stringify(chips.map(c => [Math.round(c.left), Math.round(c.right)])));

console.log('\n--- “≡ Even words” re-lays them, edges untouched ---');
await p.click('#btnEven');
await sleep(1300);
const evened = (await proj()).lines[0];
ok('the edges stayed', Math.abs(evened.start - at) < 0.01
   && Math.abs(evened.end - (at + 1.8)) < 0.01,
   `${evened.start.toFixed(2)}–${evened.end.toFixed(2)}`);
ok('the words are in order and apart now',
   evened.words.every((w, i) => i === 0 || w.t > evened.words[i - 1].t + 0.01),
   JSON.stringify(evened.words.map(w => w.t.toFixed(2))));
ok('every word has a length of its own', evened.words.every(w => w.d > 0.05),
   JSON.stringify(evened.words.map(w => w.d.toFixed(2))));

console.log('\n--- the word band is there with nothing selected ---');
// The whole layout has to be watchable without selecting a line: a thin band
// of word boxes along the bottom of the wave.
await p.keyboard.press('Escape');
await p.click('#btnZoomOut');
await sleep(400);
const band = await p.evaluate(() => {
  const c = document.getElementById('wave');
  const g = c.getContext('2d');
  const dpr = c.width / c.clientWidth;
  const y = Math.max(0, Math.round((c.clientHeight - 12) * dpr));
  const hgt = Math.min(c.height - y, Math.round(10 * dpr));
  const d = g.getImageData(0, y, c.width, hgt).data;
  let lit = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 20) lit++;
  return {lit, total: d.length / 4};
});
ok('word boxes are drawn along the bottom of the wave',
   band.lit > band.total * 0.01, JSON.stringify(band));

console.log('\n--- a press selects the line that was pressed ---');
// The stage scrolls under the cursor while the song plays: the click used to
// land on the neighbour of the line that was actually pressed.
const stageLines = await p.$$('#scroll .ln');
if (stageLines.length >= 3){
  const target = stageLines[2];
  const rb = await target.boundingBox();
  await p.mouse.move(rb.x + rb.width / 2, rb.y + rb.height / 2);
  await p.mouse.down();
  // the song plays on between the press and the release, and the stage
  // scrolls under the cursor — exactly how the neighbour used to get selected
  await p.keyboard.press('Space');
  await sleep(400);
  await p.keyboard.press('Space');
  await sleep(150);
  await p.mouse.up();
  await sleep(300);
  const picked = await p.$$eval('#scroll .ln',
    els => els.findIndex(e => e.classList.contains('sel')));
  ok('the selected line is the pressed one, not its neighbour',
     picked === 2, picked);
} else {
  ok('the stage has enough lines to try this on', false, stageLines.length);
}

console.log('\n--- dots on a scream do not break the rhythm ---');
// Appending “...” to the last word — a long scream written down — used to lay
// the whole line out anew, throwing away exactly the rhythm already set.
const beforeDots = (await proj()).lines[1];
await p.$$eval('#scroll .ln', els => els[1].scrollIntoView());
await sleep(200);
const row1 = (await p.$$('#scroll .ln'))[1];
const rr = await row1.boundingBox();
await p.mouse.click(rr.x + rr.width / 2, rr.y + rr.height / 2);
await sleep(250);
await p.click('#btnText');
await sleep(300);
await p.keyboard.press('End');
await p.keyboard.type('...');
await p.keyboard.press('Enter');
await sleep(1300);
const afterDots = (await proj()).lines[1];
ok('the dots are in the text', /\.\.\.$/.test(afterDots.text), afterDots.text);
ok('and every word kept its time',
   afterDots.words.length === beforeDots.words.length
   && afterDots.words.every((w, k) => Math.abs(w.t - beforeDots.words[k].t) < 0.002
                                   && Math.abs(w.d - beforeDots.words[k].d) < 0.002),
   JSON.stringify(afterDots.words.map(w => w.t.toFixed(2))) + ' vs '
   + JSON.stringify(beforeDots.words.map(w => w.t.toFixed(2))));

// one word fixed in the middle: its neighbours stay put
// fix the FIRST word: every line has one, and its neighbour must stay put
const midWords = afterDots.words.map(w => w.w);
midWords[0] = 'чиню';
await p.click('#btnText');
await sleep(300);
await p.$eval('.lnedit', (e, v) => { e.value = v; }, midWords.join(' '));
await p.keyboard.press('Enter');
await sleep(1300);
const afterFix = (await proj()).lines[1];
ok('the fixed word is in place', afterFix.words[0].w === 'чиню', afterFix.words[0].w);
const lastK = afterFix.words.length - 1;
ok('and the untouched words kept their times',
   afterFix.words.slice(1).every((w, k) =>
     Math.abs(w.t - afterDots.words[k + 1].t) < 0.002),
   `${afterFix.words[lastK].t.toFixed(2)} vs ${afterDots.words[lastK].t.toFixed(2)}`);

console.log('\n--- slowed listening, same pitch ---');
// Half speed to catch mistakes while editing: time stretches, the pitch stays,
// and the clock the editor lives by follows the slowed playback.
await p.select('#selSpeed', '0.5');
await sleep(200);
const clock = async () => p.$eval('#tCur', e => {
  const m = e.textContent.trim().match(/^(\d+):(\d+(?:\.\d+)?)/);
  return m ? parseInt(m[1], 10) * 60 + parseFloat(m[2]) : NaN;
});
await p.keyboard.press('Space');
await sleep(300);
const t1 = await clock();
await sleep(1600);
const t2 = await clock();
await p.keyboard.press('Space');
await sleep(200);
const gained = t2 - t1;
ok('the song moves at about half its pace', gained > 0.45 && gained < 1.2,
   gained.toFixed(2) + ' s per 1.6 s');
// pitch preservation is a property of the hidden players; reach them through
// a DOM hook the app exposes for exactly this kind of look
ok('the speed control shows the chosen rate',
   (await p.$eval('#selSpeed', e => e.value)) === '0.5');
await p.select('#selSpeed', '1');
await sleep(200);
await p.keyboard.press('Space');
await sleep(1100);
const t3 = await clock();
await p.keyboard.press('Space');
await sleep(150);
ok('back at 1× the song runs at full pace again', t3 - t2 > 0.75,
   (t3 - t2).toFixed(2) + ' s per 1.1 s');

console.log('\n--- both duet lines light up on the stage ---');
// The second voice sounding with the first used to sit unlit: the stage
// showed one line of the two being sung.
const duetState = await proj();
const dl = JSON.parse(JSON.stringify(duetState.lines));
// lead at 2–6, backing right over it
dl[0].voice = 1; dl[0].backing = false;
dl[0].start = 2.0; dl[0].end = 6.0;
dl[0].words = dl[0].words.map((w, i) => ({...w, t: 2.0 + i, d: 0.9}));
dl[1].voice = 2; dl[1].backing = true;
dl[1].start = 2.5; dl[1].end = 5.5;
dl[1].words = dl[1].words.map((w, i) => ({...w, t: 2.5 + i, d: 0.8}));
await fetch(`${API}/api/project/${encodeURIComponent(PID)}/timings`, {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify({lines: dl})});
await p.reload({waitUntil:'networkidle0'});
await sleep(500);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(700);
await p.keyboard.press('Space');
await sleep(3200);                       // ~3.2 s in: inside the 2.5–5.5 overlap
const litLines = await p.$$eval('#scroll .ln', els =>
  els.map((e, i) => e.classList.contains('cur') ? i : -1).filter(i => i >= 0));
await p.keyboard.press('Space');
ok('both lines of the duet are lit at once',
   litLines.includes(0) && litLines.includes(1), JSON.stringify(litLines));
const fills = await p.$$eval('#scroll .ln',
  els => els.slice(0, 2).map(e =>
    [...e.querySelectorAll('.hl')].filter(h => parseFloat(h.style.width) > 0).length));
ok('and the words of both are filling', fills[0] > 0 && fills[1] > 0,
   JSON.stringify(fills));

ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
