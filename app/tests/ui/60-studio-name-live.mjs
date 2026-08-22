// The song's name, given by hand. It stands in the corner of the video, on
// its opening card and on the finished page, and it used to be whatever the
// file was called or whatever stood in the lyrics header — with no way to say
// otherwise. Here it is typed in a real browser and then looked for on disk,
// in the exported page, and after a re-timing that would once have undone it.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const post = async (path, body) => (await (await fetch(API + path, {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})).json());
const get = async path => (await (await fetch(API + path)).json());

async function finish(jid, seconds = 180){
  for (let i = 0; i < seconds * 2; i++){
    const j = await get('/api/job?id=' + jid);
    if (j.done || j.error) return j;
    await sleep(500);
  }
  return {done:false, ok:false, log:['timed out']};
}

// A song of its own, so the renaming does not disturb the shared one.
const built = await finish((await post('/api/new', {
  audio: process.env.KARAOKE_SONG, lyrics: process.env.KARAOKE_TEXT,
  align: 'energy', separate: false})).job);
ok('a song to rename is built', built.ok, (built.log || []).slice(-1)[0]);
const pid = built.result;

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.dismiss());
await p.setViewport({width:1366, height:900});
await p.goto(API + '/', {waitUntil:'networkidle0'});
await sleep(700);
await p.waitForSelector('.card', {timeout:20000});
// Open our own song, not whichever card happens to be first.
await p.evaluate(id => {
  const card = [...document.querySelectorAll('.card')]
    .find(c => (c.dataset.id || '') === id);
  (card || document.querySelector('.card')).click();
}, pid);
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(700);

console.log('--- the name in the corner opens to be typed in ---');
const shown = () => p.$eval('#edTitle', e => e.textContent.trim());
ok('the editor shows a name to begin with', (await shown()).length > 0, await shown());
await p.click('#edTitle');
await sleep(200);
ok('a click turns it into two fields',
   await p.$eval('#edTitle', e => e.querySelectorAll('input').length) === 2);

await p.$$eval('#edTitle input', els => { els[0].value = ''; els[1].value = ''; });
await p.type('#edTitle input.t', 'Forevermore');
await p.type('#edTitle input.a', 'Lorna Shore');
await p.keyboard.press('Enter');
await sleep(900);
ok('and the corner carries what was typed',
   (await shown()) === 'Forevermore — Lorna Shore', await shown());

console.log('\n--- and it is on the disk, not only on the screen ---');
let data = await get('/api/project/' + encodeURIComponent(pid));
ok('the song is called that in its own file',
   data.title === 'Forevermore' && data.artist === 'Lorna Shore',
   `${data.title} / ${data.artist}`);
ok('and it is remembered as chosen by hand', data.titleSet === true, data.titleSet);

console.log('\n--- a re-timing does not rename it back ---');
// The lyrics file carries a “title:” header of its own; before, re-reading it
// quietly renamed the song and the name in the corner of the video with it.
const again = await finish((await post(
  `/api/project/${encodeURIComponent(pid)}/realign`, {align: 'energy'})).job);
ok('the re-timing goes through', again.ok, (again.log || []).slice(-1)[0]);
data = await get('/api/project/' + encodeURIComponent(pid));
ok('the name given by hand survived it',
   data.title === 'Forevermore' && data.artist === 'Lorna Shore',
   `${data.title} / ${data.artist}`);

console.log('\n--- and it reaches the exported page ---');
const exp = await finish((await post(
  `/api/project/${encodeURIComponent(pid)}/export`, {kind: 'html'})).job);
ok('the export goes through', exp.ok, (exp.log || []).slice(-1)[0]);
if (exp.ok && exp.result && exp.result.path){
  const fs = await import('fs');
  const html = fs.readFileSync(exp.result.path, 'utf8');
  const m = html.match(/<script id="payload" type="application\/json">(.*?)<\/script>/s);
  if (m){
    const pay = JSON.parse(m[1].replace(/\\u003c/g, '<')
      .replace(/\\u003e/g, '>').replace(/\\u0026/g, '&'));
    ok('the page is the song we named',
       pay.data.title === 'Forevermore' && pay.data.artist === 'Lorna Shore',
       `${pay.data.title} / ${pay.data.artist}`);
  } else ok('the page carries a payload', false);
  fs.unlinkSync(exp.result.path);
}

ok('nothing in the window went wrong', errs.length === 0, errs.slice(0, 2).join(' | '));

await b.close();
await post(`/api/project/${encodeURIComponent(pid)}/delete`, {});
console.log(fail ? '\nFAILED: ' + fail : '\nAll checks passed');
process.exit(fail ? 1 : 0);
