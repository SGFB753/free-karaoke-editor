// End to end, in a real browser: a link goes in, the sound comes out of it, the
// words are picked from what was found, Build is pressed — and the karaoke is
// on the screen with the lines on it. Nothing here is stubbed but the two
// places that would otherwise reach the internet.
import puppeteer from 'puppeteer';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));

const before = (await (await fetch(API+'/api/state')).json()).projects.map(p => p.id);

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.setViewport({width:1366, height:900});
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(600);

const val = id => p.$eval('#'+id, e => e.value);
const txt = id => p.$eval('#'+id, e => e.textContent);

console.log('--- the link is typed the way a person types it ---');
await p.click('#btnAdd');
await sleep(300);
await p.click('#inLink');
await p.type('#inLink', 'https://example.com/watch?v=zzz123');
await p.click('#btnFetch');

await p.waitForFunction("document.getElementById('inAudio').value.length > 0",
                        {timeout: 60000});
ok('the sound of the link is in the song field', (await val('inAudio')).length > 0,
   (await val('inAudio')).slice(-42));
ok('and the window says what arrived', /Звук на месте/.test(await txt('linkNote')),
   (await txt('linkNote')).slice(0, 60));

console.log('\n--- the words are offered, and one is taken ---');
await p.waitForSelector('#lyricsFound .one button', {timeout: 60000});
const offered = await p.$$eval('#lyricsFound .one', els => els.map(e => e.textContent));
ok('there is something to choose from', offered.length > 0, offered.length + ' offered');
ok('LRCLIB and Genius are both offered when both know the song',
   offered.some(t => /LRCLIB/.test(t)) && offered.some(t => /Genius/.test(t)),
   offered.join(' | '));
await p.click('#lyricsFound .one button');
await p.waitForFunction("document.getElementById('inLyrics').value.length > 0",
                        {timeout: 30000});
ok('the taken text became a file', /\.txt$/.test(await val('inLyrics')),
   (await val('inLyrics')).slice(-34));
ok('and it is on the screen to be read',
   (await val('taLyrics')).split('\n').filter(Boolean).length >= 2);

console.log('\n--- and the karaoke is built out of the two ---');
// Loudness, no separation: this is about the road from a link to a song, not
// about what the neural nets can do — and the checks must not download models.
await p.select('#selAlign', 'energy');
if (await p.$eval('#chkSep', e => e.checked)) await p.click('#chkSep');
await sleep(300);
await p.click('#btnBuild');
const built = await p.waitForFunction(
  "!document.getElementById('scrEdit').classList.contains('hide')",
  {timeout: 180000}).then(() => true).catch(() => false);
ok('the editor opened by itself when it was ready', built,
   built ? '' : (await txt('jobLog')).slice(-200));

if (built){
  await p.waitForSelector('#scroll .ln', {timeout: 30000}).catch(() => {});
  const lines = await p.$$eval('#scroll .ln', els => els.length);
  ok('the lines of the song are on the stage', lines > 0, lines + ' lines');
  const blocks = await p.$$eval('#blocks .blk', els => els.length);
  ok('and on the timeline underneath', blocks > 0, blocks + ' blocks');
  const state = await (await fetch(API+'/api/state')).json();
  const fresh = state.projects.filter(x => !before.includes(x.id));
  ok('and the song is in the list, made out of the link', fresh.length === 1,
     fresh.map(f => f.title || f.id).join(', '));

  // The file a link lands in is named so it survives every file system —
  // “Stub_Artist_-_Stub_Song_[zzz123]”. Nobody wants that as the title.
  if (fresh[0]){
    const d = await (await fetch(API+'/api/project/'+encodeURIComponent(fresh[0].id))).json();
    ok('the song is called what it is called, not what the file is',
       d.title === 'Stub Song', d.title);
    ok('no square brackets or underscores from the file name',
       !/[\[\]_]/.test(d.title), d.title);
    ok('and the artist came with it', d.artist === 'Stub Artist', d.artist);
  }
  console.log('\n--- and the journey ends in an exported page ---');
  const exp = await (await fetch(`${API}/api/project/${encodeURIComponent(fresh[0].id)}/export`,
    {method:'POST', headers:{'Content-Type':'application/json'},
     body: JSON.stringify({kind:'html'})})).json();
  let expEnd = null;
  for (let i = 0; i < 120; i++){
    const j = await (await fetch(`${API}/api/job?id=${exp.job}`)).json();
    if (j.done || j.error){ expEnd = j; break; }
    await sleep(500);
  }
  ok('the export goes through', expEnd && expEnd.ok,
     expEnd && (expEnd.error || (expEnd.log || []).slice(-1)[0]));
  if (expEnd && expEnd.ok && expEnd.result && expEnd.result.path){
    const fs = await import('fs');
    const html = fs.readFileSync(expEnd.result.path, 'utf8');
    const m = html.match(/<script id="payload" type="application\/json">(.*?)<\/script>/s);
    ok('the page carries a payload', !!m);
    if (m){
      const pay = JSON.parse(m[1].replace(/\\u003c/g, '<')
        .replace(/\\u003e/g, '>').replace(/\\u0026/g, '&'));
      ok('the song in the page is called what it is called',
         pay.data.title === 'Stub Song', pay.data.title);
      ok('with the artist that came with it', (pay.data.artist || '') === 'Stub Artist',
         pay.data.artist);
      ok('every line of the lyrics reached the page',
         (pay.data.lines || []).length >= 2, (pay.data.lines || []).length);
      ok('and the keep-spans field is there for the player',
         Array.isArray(pay.data.keepSpans), typeof pay.data.keepSpans);
      ok('the clip cover rides along as a picture, not a path',
         (pay.cover || '').startsWith('data:image'), (pay.cover || '').slice(0, 24));
    }
    fs.unlinkSync(expEnd.result.path);    // the stand stays as it was found
  }

  // The stand belongs to everyone: put it back the way it was found.
  for (const f of fresh)
    await fetch(`${API}/api/project/${encodeURIComponent(f.id)}/delete`, {method:'POST'});
}

ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
