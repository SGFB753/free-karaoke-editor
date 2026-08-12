// Overlapping vocals: a second-voice line moves to the second lane of the
// timeline and stays grabbable. A real browser — jsdom does not do layout.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());
const sleep = ms => new Promise(r=>setTimeout(r,ms));

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(600);
await p.click('.card');
await sleep(2500);

const lane = i => p.evaluate(k => {
  const e = document.querySelectorAll('#blocks .blk')[k];
  return e ? e.getBoundingClientRect().top : null;
}, i);
const wrapH = () => p.evaluate(() =>
  document.getElementById('tlwrap').getBoundingClientRect().height);

console.log('--- while there is no second voice ---');
const h0 = await wrapH();
const top0 = await lane(1);
ok('the timeline is a single lane', !(await p.evaluate(() =>
   document.getElementById('tlwrap').classList.contains('twolane'))));

console.log('\n--- giving a line the second voice ---');
await p.evaluate(() => document.querySelectorAll('#scroll .ln')[1].click());
await sleep(200);
await p.click('#btnVoice');
await sleep(400);

const h1 = await wrapH();
const top1 = await lane(1);
const topMain = await lane(0);
ok('the timeline got taller', h1 > h0, `${h0} → ${h1}`);
// The timeline grew and shifted the layout, so we compare the blocks with each
// other, not with their own former coordinates on screen.
ok('the second-voice block sits below the main ones', top1 > topMain + 20,
   `main ${topMain}, second ${top1}`);
ok('before the second voice the blocks ran in one lane', Math.abs(top0 - topMain) < 40,
   `${top0} vs ${topMain}`);

console.log('\n--- the second-voice block can still be grabbed with the mouse ---');
const box = await p.evaluate(() => {
  const e = document.querySelectorAll('#blocks .blk')[1];
  const r = e.getBoundingClientRect();
  return {x: r.left + r.width/2, y: r.top + r.height/2};
});
const hit = await p.evaluate(({x,y}) => {
  const e = document.elementFromPoint(x, y);
  return !!(e && e.closest('.blk') === document.querySelectorAll('#blocks .blk')[1]);
}, box);
ok('that very block is under the cursor', hit);
const was = (await proj()).lines[1].start;
await p.mouse.move(box.x, box.y);
await p.mouse.down();
await p.mouse.move(box.x + 60, box.y, {steps: 8});
await p.mouse.up();
await sleep(900);
const now = (await proj()).lines[1].start;
ok('the second-voice line could be moved', now > was + 0.05,
   `${was.toFixed(2)} → ${now.toFixed(2)}`);

console.log('\n--- and the words of that line show under the timeline ---');
const wordsBelow = await p.evaluate(() => {
  const w = document.querySelector('#words .wrd');
  const blk = document.querySelectorAll('#blocks .blk')[1];
  if (!w || !blk) return null;
  return w.getBoundingClientRect().top - blk.getBoundingClientRect().bottom;
});
ok('the word row is below the second lane, not on top of it', wordsBelow !== null && wordsBelow > 0,
   String(wordsBelow));

// put it back so the stand stays clean for the neighbouring suites
await p.click('#btnVoice');
await sleep(200);
await p.evaluate(t => {
  const b = document.querySelectorAll('#blocks .blk')[1];
  b.click();
}, 0);
await sleep(600);

ok('no JS errors', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
