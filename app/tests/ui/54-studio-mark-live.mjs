// Marking the wordless stretches with the mouse, in a real browser: press on
// the waveform, drag, let go — and the mark is there, in the field, and gone
// again on a click. Typing seconds into a field was the only way before, and
// on this kind of music it is the step people give up on.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));

const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.dismiss());
await p.setViewport({width:1366, height:900});
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(700);
// Open it the way a person does — from the list.
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(700);

const field = () => p.$eval('#edNoText', e => e.value);
// Everything is judged by what a person can see: the field is the marks.
const marksLen = async () => {
  const v = (await field()).trim();
  return v ? v.split(",").filter(x => x.trim()).length : 0;
};

console.log('--- the timeline has a way in ---');
ok('there is a button for marking', !!(await p.$('#btnMark')));
await p.$eval('#edNoText', e => { e.value = ''; e.dispatchEvent(new Event('change', {bubbles:true})); });
await sleep(150);
ok('with an empty field there are no marks', (await marksLen()) === 0, await field());

console.log('\n--- pressing and dragging makes a mark ---');
await p.click('#btnMark');
await sleep(200);
ok('marking mode shows on the button',
   await p.$eval('#btnMark', e => e.classList.contains('on')));
ok('and the window says what to do now',
   /волне|waveform/i.test(await p.$eval('#toast', e => e.textContent)),
   await p.$eval('#toast', e => e.textContent));

const box = await p.$eval('#tlwrap', e => {
  const r = e.getBoundingClientRect();
  return {x: r.left, y: r.top, w: r.width, h: r.height};
});
const y = box.y + box.h / 2;
await p.mouse.move(box.x + box.w * 0.15, y);
await p.mouse.down();
await p.mouse.move(box.x + box.w * 0.35, y, {steps: 12});
await p.mouse.up();
await sleep(300);

ok('the mark exists', (await marksLen()) === 1, await marksLen());
const written = await field();
ok('and it is written into the field', /^\d+:\d\d\.\d-\d+:\d\d\.\d$/.test(written), written);
const [a, bEnd] = written.split('-').map(v => {
  const [m, s] = v.split(':'); return parseInt(m, 10) * 60 + parseFloat(s);
});
ok('it starts where the press was and ends where it was let go', bEnd > a, `${a} → ${bEnd}`);
ok('and it is a stretch, not a point', bEnd - a > 0.5, (bEnd - a).toFixed(2));

console.log('\n--- and a click takes it off ---');
await p.mouse.click(box.x + box.w * 0.25, y);
await sleep(300);
ok('the mark is gone', (await marksLen()) === 0, await marksLen());
ok('the field is empty again', (await field()) === '', await field());

console.log('\n--- reverse marking uses timeline coordinates across its layers ---');
await p.$eval('#tlwrap', el => {
  const layer = document.createElement('div');
  layer.id = 'mark-test-layer';
  Object.assign(layer.style, {position:'absolute', left:'55%', top:'0',
    width:'25%', height:'100%', zIndex:'50'});
  el.appendChild(layer);
});
await p.mouse.move(box.x + box.w * .70, y);
await p.mouse.down();
await p.mouse.move(box.x + box.w * .40, y, {steps:12});
await p.mouse.up();
await sleep(200);
const reverse = (await field()).split('-').map(v => {
  const [m,s] = v.split(':'); return +m * 60 + +s;
});
ok('dragging left across a child layer marks the actual times',
   Math.abs(reverse[0] - 6) < .15 && Math.abs(reverse[1] - 10.5) < .15,
   await field());
await p.$eval('#mark-test-layer', el => el.remove());
await p.click('#btnUndo'); await sleep(200);
ok('undo removes the drawn mark', (await marksLen()) === 0, await field());
await p.click('#btnRedo'); await sleep(200);
ok('redo restores the drawn mark', (await marksLen()) === 1, await field());
await p.click('#btnUndo'); await sleep(200);

console.log('\n--- the wheel works while the marking button is on ---');
const clockBefore = await p.$eval('#tCur', el => el.textContent);
await p.mouse.move(box.x + box.w * .5, y);
await p.mouse.wheel({deltaY:250}); await sleep(250);
ok('the wheel moves the timeline without leaving marking mode',
   await p.$eval('#tCur', el => el.textContent) !== clockBefore &&
   await p.$eval('#btnMark', el => el.classList.contains('on')));
await p.mouse.wheel({deltaY:-250}); await sleep(250);
ok('scrolling by itself creates no mark', (await marksLen()) === 0);

console.log('\n--- two marks in a row, and touching ones become one ---');
for (const [from, to] of [[0.10, 0.20], [0.50, 0.62]]){
  await p.mouse.move(box.x + box.w * from, y);
  await p.mouse.down();
  await p.mouse.move(box.x + box.w * to, y, {steps: 10});
  await p.mouse.up();
  await sleep(200);
}
ok('both marks are kept apart', (await marksLen()) === 2, await field());
// a third one bridging the two must fold them into a single stretch
await p.mouse.move(box.x + box.w * 0.18, y);
await p.mouse.down();
await p.mouse.move(box.x + box.w * 0.55, y, {steps: 14});
await p.mouse.up();
await sleep(250);
ok('an overlapping mark folds them into one', (await marksLen()) === 1, await field());

console.log('\n--- leaving the mode leaves the marks ---');
await p.click('#btnMark');
await sleep(200);
ok('marking is off', !(await p.$eval('#btnMark', e => e.classList.contains('on'))));
ok('the marks stay in the field', (await field()).length > 0, await field());
// and the timeline stops marking: dragging over it changes nothing now
// (seeking with it is what the other browser suites already watch)
const kept = await field();
await p.mouse.move(box.x + box.w * 0.70, y);
await p.mouse.down();
await p.mouse.move(box.x + box.w * 0.85, y, {steps: 8});
await p.mouse.up();
await sleep(300);
ok('dragging no longer marks anything', (await field()) === kept, await field());
ok('and the marks made before are untouched', (await marksLen()) === 1, await field());

ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
