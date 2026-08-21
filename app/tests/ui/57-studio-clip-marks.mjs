// Lines that sit inside a marked stretch, and lines that reach across one.
// Both are what a screamed song leaves behind, and neither could be put right
// in the editor before: trimming an edge only moves the outermost word, and a
// line wholly inside a hole could not be trimmed at all.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());
const save = async lines => fetch(`${API}/api/project/${encodeURIComponent(PID)}/timings`,
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({lines})});

const original = await proj();
// The test song sings at 2.0-4.6, 5.0-7.6, 8.0-10.6, 11.0-13.6, 16.0-18.6,
// 19.0-21.6. Put lines 1 and 2 into a hole we are about to mark, and make
// line 3 reach across it.
const bent = JSON.parse(JSON.stringify(original.lines));
const put = (i, a, b) => {
  const span = (b - a) / Math.max(1, bent[i].words.length);
  bent[i].start = a; bent[i].end = b;
  bent[i].words = bent[i].words.map((w, k) => ({...w, t: a + span * k, d: span * 0.9}));
};
// The lines keep their order in time — anything else is a different bug, and
// this check is about the marks. The hole to be marked is 0:12–0:15.
put(2, 8.0, 14.0);           // reaches into the hole from before it
put(3, 12.4, 13.2);          // wholly inside
put(4, 13.4, 14.2);          // and this one too
await save(bent);

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.accept());
await p.setViewport({width:1366, height:900});
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(500);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(700);

console.log('--- with nothing marked, there is nothing to do ---');
await p.$eval('#edNoText', e => { e.value = ''; e.dispatchEvent(new Event('change', {bubbles:true})); });
await sleep(200);
await p.click('#btnClip');
await sleep(300);
ok('it says so instead of moving anything',
   /Пока ничего не отмечено|Nothing is marked/.test(await p.$eval('#toast', e => e.textContent)),
   await p.$eval('#toast', e => e.textContent));

console.log('\n--- with a hole marked ---');
await p.$eval('#edNoText', e => { e.value = '0:12-0:15';
  e.dispatchEvent(new Event('change', {bubbles:true})); });
await sleep(300);
await p.click('#btnClip');
await sleep(1500);
const after = await proj();
const inHole = ln => ln.start >= 11.75 && ln.end <= 15.25;
ok('no line is left sitting inside it', !after.lines.some(inHole),
   after.lines.filter(inHole).map(l => `${l.start.toFixed(1)}–${l.end.toFixed(1)}`).join(', '));
ok('the line reaching into it now ends where it begins',
   after.lines[2].end <= 12.05, after.lines[2].end.toFixed(2));
ok('the lines that were moved are still in order',
   after.lines.every((l, i) => i === 0 || l.start >= after.lines[i - 1].start - 0.001),
   after.lines.map(l => l.start.toFixed(1)).join(', '));
ok('every word sits inside its own line',
   after.lines.every(l => l.words.every(w => w.t >= l.start - 0.01 && w.t + w.d <= l.end + 0.01)));
ok('and the song still has all its lines',
   after.lines.length === original.lines.length, after.lines.length);
ok('the window says what it did',
   /Подрезано|Trimmed/.test(await p.$eval('#toast', e => e.textContent)),
   await p.$eval('#toast', e => e.textContent));

console.log('\n--- and it can be undone ---');
await p.keyboard.down('Control'); await p.keyboard.press('KeyZ'); await p.keyboard.up('Control');
await sleep(1200);
const back = await proj();
ok('the lines are where they were before the press',
   Math.abs(back.lines[3].start - 12.4) < 0.05, back.lines[3].start.toFixed(2));

console.log('\n--- a warning can be dismissed, and it stays dismissed ---');
// Bend a line to an impossible pace so the Check panel has something to say,
// then dismiss it with the ✕ the way a spell-checker ignores a word.
const fast = JSON.parse(JSON.stringify(original.lines));
fast[0].end = fast[0].start + 0.15;
fast[0].words = fast[0].words.map(w => ({...w, t: fast[0].start, d: 0.05}));
await save(fast);
await p.reload({waitUntil:'networkidle0'});
await sleep(500);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(800);
const probRows = await p.$$('#probs .prob');
ok('the panel flags the impossible line', probRows.length >= 1, probRows.length);
// the stand is shared: earlier suites may have left warnings of their own —
// dismiss them all, the way a person cleans the list
let guard = 8;
while (guard-- > 0 && (await p.$('#probs .prob .ign'))){
  await p.click('#probs .prob .ign');
  await sleep(600);
}
await sleep(1200);
const left = await p.$$eval('#probs .prob', els =>
  els.map(e => e.textContent.replace(/\s+/g, ' ').slice(0, 90)));
ok('every dismissed warning is gone from the panel', left.length === 0,
   left.join(' || ') + ' /// saved=' + JSON.stringify((await proj()).checkOff));
ok('and the way back is offered', !!(await p.$('#probs .ignored-note, .ignored-note')));
const saved = await proj();
ok('the dismissal is saved with the song',
   Array.isArray(saved.checkOff) && saved.checkOff.length >= 1,
   JSON.stringify(saved.checkOff));
await p.reload({waitUntil:'networkidle0'});
await sleep(500);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(800);
ok('and it survives reopening the song',
   (await p.$$('#probs .prob')).length === 0, (await p.$$('#probs .prob')).length);
await p.click('.ignored-note');
await sleep(1500);
ok('the link brings the warning back',
   (await p.$$('#probs .prob')).length >= 1, (await p.$$('#probs .prob')).length);

await save(original.lines);        // leave the stand as it was found
ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
