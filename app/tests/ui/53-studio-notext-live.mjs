// The whole road in a real browser: mark the stretches that hold no words on
// the build screen, build, and look at where the lines landed. Plus the label
// that used to print itself over the colour swatches in a narrow window.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const state = async () => (await (await fetch(API + '/api/state')).json());

const before = (await state()).projects.map(p => p.id);

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.accept());
await p.setViewport({width:1366, height:900});
await p.goto(API + '/', {waitUntil:'networkidle0'});
await sleep(600);

console.log('--- the field is there, and it is explained ---');
await p.click('#btnAdd');
await sleep(300);
ok('the build screen has a field for wordless stretches', !!(await p.$('#inNoText')));
// The explanation moved from a standing paragraph to the label's own
// tooltip: the form got shorter, the words wait under the cursor.
const hint = await p.$eval('#inNoText', e =>
  e.closest('.field').querySelector('label').title);
ok('and the label explains it claims nothing about the rest of the song',
   /остальн/i.test(hint) || /rest of the song/i.test(hint), hint.slice(0, 80));
ok('it names the way of writing it in the lyrics file too',
   /\[/.test(hint) && /3:10/.test(hint), hint.slice(-60));

console.log('\n--- a song built with the first two phrases marked ---');
// The test song sings at 2.0-4.6, 5.0-7.6, 8.0-10.6, 11.0-13.6, 16.0-18.6,
// 19.0-21.6. Marked to 0:08, nothing may be laid on the first two.
await p.$eval('#inAudio', (e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles:true})); },
              process.env.KARAOKE_SONG);
await p.$eval('#inLyrics', (e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles:true})); },
              process.env.KARAOKE_TEXT);
await p.click('#inNoText');
await p.type('#inNoText', '0:00-0:08');
await p.select('#selAlign', 'energy');
if (await p.$eval('#chkSep', e => e.checked)) await p.click('#chkSep');
await sleep(300);
await p.click('#btnBuild');
const built = await p.waitForFunction(
  "!document.getElementById('scrEdit').classList.contains('hide')",
  {timeout: 180000}).then(() => true).catch(() => false);
ok('the editor opened when it was ready', built,
   built ? '' : (await p.$eval('#jobLog', e => e.textContent)).slice(-160));

let fresh = [];
if (built){
  const now = await state();
  fresh = now.projects.filter(x => !before.includes(x.id));
  const data = await (await fetch(API + '/api/project/' + encodeURIComponent(fresh[0].id))).json();
  const first = Math.min(...data.lines.map(l => l.start));
  ok('no line was laid on the marked stretch', first >= 7.8, first.toFixed(1));
  ok('and every line of the song is there', data.lines.length === 6, data.lines.length);

  console.log('\n--- the marks come back into the editor ---');
  ok('the editor field is filled from the song',
     /0\.0-8\.0/.test(await p.$eval('#edNoText', e => e.value)),
     await p.$eval('#edNoText', e => e.value));

  console.log('\n--- and the labels keep off the colour swatches ---');
  // In a narrow window the caption used to be squeezed into the swatches next
  // to it and printed over them.
  for (const width of [1366, 1100, 900]){
    await p.setViewport({width, height:900});
    await sleep(350);
    const boxes = await p.$$eval('.pick', els => els.map(el => {
      const label = el.querySelector('b').getBoundingClientRect();
      const swatch = el.querySelector('input[type=color]').getBoundingClientRect();
      return {label: [label.left, label.right], swatch: [swatch.left, swatch.right],
              w: label.width};
    }));
    const clash = boxes.some(x => x.label[1] > x.swatch[0] + 0.5);
    ok(`at ${width}px the label does not run into the swatches`, !clash,
       JSON.stringify(boxes[0] || {}));
    ok(`at ${width}px the label is still readable`, boxes.every(x => x.w > 30),
       boxes.map(x => Math.round(x.w)).join(', '));
  }
  for (const f of fresh)
    await fetch(`${API}/api/project/${encodeURIComponent(f.id)}/delete`, {method:'POST'});
}

ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
