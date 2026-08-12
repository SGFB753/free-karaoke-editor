// Scrolling the text by hand, and the highlight going out after the last line.
import puppeteer from 'puppeteer';
const API = process.env.KARAOKE_API;
const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const shift = () => p.evaluate(() => document.getElementById('scroll').style.transform);
const cur = () => p.evaluate(() => {
  const all = [...document.querySelectorAll('#scroll .ln')];
  const c = document.querySelector('#scroll .ln.cur');
  return c ? all.indexOf(c) : -1;
});

console.log('--- scrolling with the wheel ---');
const was = await shift();
const box = await p.evaluate(() => {
  const r = document.querySelector('.stage').getBoundingClientRect();
  return {x: r.left + r.width/2, y: r.top + r.height/2};
});
await p.mouse.move(box.x, box.y);
await p.mouse.wheel({deltaY: 300});
await new Promise(r=>setTimeout(r,400));
const after = await shift();
ok('the text moved under the wheel', after !== was, `${was} → ${after}`);
await p.mouse.wheel({deltaY: -300});
await new Promise(r=>setTimeout(r,400));
ok('and back', (await shift()) !== after);

console.log('\n--- Home and End ---');
await p.keyboard.press('End');
await new Promise(r=>setTimeout(r,900));
const atEnd = await p.evaluate(() => {
  const all = [...document.querySelectorAll('#scroll .ln')];
  const s = document.querySelector('#scroll .ln.sel');
  return {i: s ? all.indexOf(s) : -1, n: all.length};
});
ok('End picks the last line', atEnd.i === atEnd.n - 1,
   `${atEnd.i+1} of ${atEnd.n}`);
await p.keyboard.press('Home');
await new Promise(r=>setTimeout(r,900));
const atHome = await p.evaluate(() => {
  const all = [...document.querySelectorAll('#scroll .ln')];
  const s = document.querySelector('#scroll .ln.sel');
  return s ? all.indexOf(s) : -1;
});
ok('Home goes back to the first', atHome === 0, String(atHome + 1));

console.log('\n--- past the last line nothing stays lit ---');
const last = await p.evaluate(async () => {
  const r = await fetch('/api/state');
  return null;
});
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const lines = (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json()).lines;
const lastEnd = lines[lines.length-1].end;
// jump to the middle of the song — the highlight must be there
await p.evaluate(t => {
  const w = document.getElementById('tlwrap').getBoundingClientRect();
  return null;
}, 0);
await p.evaluate(() => document.querySelectorAll('#scroll .ln')[1].click());
await new Promise(r=>setTimeout(r,600));
ok('mid-song a line is highlighted', (await cur()) >= 0, String(await cur()));

// and now honestly wind past the end of the last line — with the arrow, like a person
await p.evaluate(() => document.getElementById('scrEdit').focus?.());
for (let i = 0; i < 40; i++){
  const t = await p.evaluate(() => document.getElementById('tCur').textContent);
  const sec = t.split(':').reduce((m, x) => m * 60 + parseFloat(x), 0);
  if (sec > lastEnd + 0.6) break;
  await p.keyboard.press('ArrowRight');
  await new Promise(r => setTimeout(r, 120));
}
await new Promise(r=>setTimeout(r,600));
const t2 = await p.evaluate(() => document.getElementById('tCur').textContent);
const sec2 = t2.split(':').reduce((m, x) => m * 60 + parseFloat(x), 0);
ok('we wound past the last line', sec2 > lastEnd,
   `${t2} with the lyrics ending at ${lastEnd.toFixed(2)} s`);
const nothing = await cur();
ok('the highlight is gone — nothing is left hanging', nothing < 0,
   nothing >= 0 ? `line ${nothing+1} is lit` : '');

ok('no JS errors', errs.length===0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
