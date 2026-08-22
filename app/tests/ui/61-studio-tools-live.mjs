// Four things that used to take a person's own hands, against a running
// studio and a real browser: a found text that brings its times along, the
// quiet stretches turned into marks with one press, a frame of the clip
// without rendering a file, and a song packed to travel between computers.
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

console.log('--- a found text brings its times along ---');
// The stub library answers with a synced record, as LRCLIB does.
const found = await post('/api/lyrics/find', {track: 'Stub Song', duration: 21});
const timedOne = (found.found || []).find(f => f.timed);
ok('a record with a timing is offered', !!timedOne,
   JSON.stringify((found.found || []).map(f => f.timed)));
if (timedOne){
  ok('the words come without the stamps',
     !/^\s*\[\d+:/.test(timedOne.text || ''), (timedOne.text || '').slice(0, 24));
  const lines = (timedOne.textTimed || '').split('\n').filter(Boolean);
  const pegs = lines.filter(l => /^\s*\[\d+:\d/.test(l));
  ok('and the timed copy carries pegs', pegs.length > 0, pegs.slice(0, 2).join(' | '));
  ok('sparse ones, not a stamp on every line', pegs.length < lines.length,
     `${pegs.length} of ${lines.length}`);
}

// A song of our own to work on, with a stretch of silence in it.
const built = await finish((await post('/api/new', {
  audio: process.env.KARAOKE_SONG, lyrics: process.env.KARAOKE_TEXT,
  align: 'energy', separate: false, title: 'Packed Song', titleSet: true})).job);
ok('the song is built', built.ok, (built.log || []).slice(-1)[0]);
const pid = built.result;
ok('and it is called what was typed for it',
   (await get('/api/project/' + encodeURIComponent(pid))).title === 'Packed Song');

console.log('\n--- a frame of the clip, without rendering one ---');
const shot = await fetch(`${API}/api/project/${encodeURIComponent(pid)}/still?at=1`);
const png = Buffer.from(await shot.arrayBuffer());
ok('the frame comes back as a picture', shot.ok
   && png.slice(1, 4).toString() === 'PNG', shot.status + ' ' + png.slice(0, 8).toString('hex'));
ok('and it is a whole frame, not a thumbnail', png.length > 5000, png.length);
const card = await fetch(`${API}/api/project/${encodeURIComponent(pid)}/still?at=0&opening=1`);
const cardPng = Buffer.from(await card.arrayBuffer());
ok('the opening can be looked at too', card.ok && cardPng.length > 5000, cardPng.length);
ok('and it is not the same frame as the song',
   Buffer.compare(png, cardPng) !== 0);

console.log('\n--- the quiet stretches become marks with one press ---');
const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.dismiss());
await p.setViewport({width:1366, height:900});
// The stand's song is short and holds no five-second silence of its own; what
// is under test is the offer and the press, not the hearing — that is measured
// on real audio elsewhere. So the song's record arrives in the window with the
// stretches the program would have heard, by the same road it always takes.
await p.evaluateOnNewDocument(id => {
  const real = window.fetch;
  window.fetch = async (url, opts) => {
    const r = await real(url, opts);
    if (typeof url === 'string' && url.endsWith('/api/project/' + id)){
      const data = await r.json();
      if (!(data.quiet || []).length)
        data.quiet = [{start: 3.0, end: 9.0}, {start: 14.0, end: 20.0}];
      return new Response(JSON.stringify(data), {status: 200,
        headers: {'Content-Type': 'application/json'}});
    }
    return r;
  };
}, encodeURIComponent(pid));
await p.goto(API + '/', {waitUntil:'networkidle0'});
await sleep(700);
await p.waitForSelector('.card', {timeout:20000});
await p.evaluate(id => {
  const card = [...document.querySelectorAll('.card')].find(c => c.dataset.id === id);
  (card || document.querySelector('.card')).click();
}, pid);
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(900);

// Start from no marks at all, whatever the song came with.
await p.$eval('#edNoText', e => { e.value = ''; e.dispatchEvent(new Event('change', {bubbles:true})); });
await sleep(200);
const chips = await p.$$('#sum .qchip i');
ok('the heard stretches offer to be marked', chips.length > 0, chips.length);
if (chips.length){
  await chips[0].click();
  await sleep(400);
  const field = await p.$eval('#edNoText', e => e.value.trim());
  ok('and one press writes the mark into the field', field.length > 0, field);
  ok('the chip then shows as taken',
     await p.$eval('#sum .qchip', e => e.classList.contains('taken')));
  const before = field;
  const all = await p.$('#sum .c.wide button');
  if (all){
    await all.click();
    await sleep(500);
    const after = await p.$eval('#edNoText', e => e.value.trim());
    ok('and “mark them all” takes the rest', after.length >= before.length, after);
  }
}

console.log('\n--- and the song travels in one file ---');
const packed = await post(`/api/project/${encodeURIComponent(pid)}/pack`, {});
ok('the song packs', !!packed.path && /\.karaoke\.zip$/.test(packed.path || ''), packed.path);
const backIn = await post('/api/unpack', {path: packed.path});
ok('and unpacks back into the list', !!backIn.id, JSON.stringify(backIn));
if (backIn.id){
  const twin = await get('/api/project/' + encodeURIComponent(backIn.id));
  ok('as the same song it was', twin.title === 'Packed Song', twin.title);
  ok('with its lines in place', (twin.lines || []).length > 0, (twin.lines || []).length);
  await post(`/api/project/${encodeURIComponent(backIn.id)}/delete`, {});
}

ok('nothing in the window went wrong', errs.length === 0, errs.slice(0, 2).join(' | '));
await b.close();
await post(`/api/project/${encodeURIComponent(pid)}/delete`, {});
const fs = await import('fs');
if (packed.path) try{ fs.unlinkSync(packed.path); }catch(e){}
console.log(fail ? '\nFAILED: ' + fail : '\nAll checks passed');
process.exit(fail ? 1 : 0);
