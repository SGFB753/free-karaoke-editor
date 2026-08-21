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

ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
