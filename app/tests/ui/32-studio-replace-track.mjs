// Swapping in the real backing track. The timing is already tuned by hand — it
// must survive, and if the official instrumental starts elsewhere, the shift
// has to be found and applied.
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { execFileSync } from 'child_process';

const API = process.env.KARAOKE_API;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'trk_'));
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };

// “The real backing track”: the same song, but starting 1.5 s later.
const shifted = path.join(tmp, 'real.wav');
execFileSync(process.env.KARAOKE_FFMPEG || 'ffmpeg', ['-y', '-loglevel', 'error', '-i', process.env.KARAOKE_SONG,
  '-af', 'adelay=1500|1500', shifted]);
ok('a track shifted by 1.5 s is ready', fs.existsSync(shifted));

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.goto(API + '/', {waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));

const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());
const before = await proj();
ok('the project has one track', !!before.tracks, JSON.stringify(before.tracks));

console.log('\n--- swapping the backing track ---');
const j = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/track', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({path: shifted, track: 'instrumental', shift: true})
})).json();
let job = null;
for (let i = 0; i < 90; i++){
  await new Promise(r=>setTimeout(r,1000));
  job = await (await fetch(API+'/api/job?id='+j.job)).json();
  if (job.done) break;
}
ok('the replacement went through', job && job.ok, job ? String(job.error) : 'never arrived');
const res = job.result || {};
ok('the shift was found and it is about 1.5 s', Math.abs(res.offset - 1.5) < 0.25,
   `found ${res.offset}`);
ok('the timing was shifted along', Math.abs(res.shifted - res.offset) < 1e-9,
   String(res.shifted));

const after = await proj();
ok('the backing track appeared', !!after.tracks.instrumental, JSON.stringify(after.tracks));
ok('the voice stayed, so there is something to sing to', !!after.tracks.vocals,
   JSON.stringify(after.tracks));
ok('the lines are the same ones', after.lines.length === before.lines.length);
ok('the text was not harmed',
   after.lines.map(l=>l.text).join('|') === before.lines.map(l=>l.text).join('|'));
ok('every line moved by exactly the shift',
   after.lines.every((l,i) => Math.abs((l.start - before.lines[i].start) - res.offset) < 0.01),
   `${before.lines[0].start.toFixed(2)} → ${after.lines[0].start.toFixed(2)}`);
ok('the words inside the lines moved with them',
   after.lines.every((l,i) => l.words.every((w,k) =>
     Math.abs((w.t - before.lines[i].words[k].t) - res.offset) < 0.01)));
ok('the project duration took the shift into account', after.duration > before.duration - 0.01,
   `${before.duration} → ${after.duration}`);

console.log('\n--- the voice keeps time with the new backing track ---');
// The voice was timed against the old recording. Left where it was, it sings
// out of step with the new instrumental — the most glaring bug of a swap.
const both = await fetch(API+'/api/project/'+encodeURIComponent(PID));
const withVoice = await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json();
ok('the voice is still in the project', !!withVoice.tracks.vocals, JSON.stringify(withVoice.tracks));
{
  // check the tracks themselves: download them and compare the loudness
  const get = async name => {
    const r = await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/audio/'+name);
    return Buffer.from(await r.arrayBuffer());
  };
  const inst = await get('instrumental'), voc = await get('vocals');
  ok('both tracks download', inst.length > 5000 && voc.length > 5000,
     `${inst.length} and ${voc.length} bytes`);
  fs.writeFileSync(path.join(tmp,'i.mp3'), inst);
  fs.writeFileSync(path.join(tmp,'v.mp3'), voc);
  // The self-contained Windows ffmpeg supplied by imageio has no separate
  // ffprobe binary. Decode a tiny mono stream and measure it instead.
  const dur = f => execFileSync(process.env.KARAOKE_FFMPEG || 'ffmpeg',
    ['-v','error','-i',f,'-f','s16le','-ac','1','-ar','8000','-']).length / 16000;
  const di = dur(path.join(tmp,'i.mp3')), dv = dur(path.join(tmp,'v.mp3'));
  ok('the voice is now as long as the new backing track', Math.abs(di - dv) < 0.35,
     `backing ${di.toFixed(2)} s, voice ${dv.toFixed(2)} s`);
  ok('the voice grew by exactly the shift', Math.abs(dv - (before.duration + res.offset)) < 0.35,
     `${before.duration.toFixed(2)} + ${res.offset.toFixed(2)} → ${dv.toFixed(2)}`);
}

console.log('\n--- the new track is really served ---');
const snd = await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/audio/instrumental');
ok('the backing track downloads', snd.ok && +snd.headers.get('content-length') > 10000,
   snd.status + ', ' + snd.headers.get('content-length') + ' bytes');

console.log('\n--- the button is there in the window ---');
await p.reload({waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));
const btn = await p.evaluate(() => {
  const b = document.getElementById('btnTrack');
  return b ? {text: b.textContent.trim(), visible: !!b.offsetParent} : null;
});
ok('the “Own backing track” button is in plain sight', btn && btn.visible, btn ? btn.text : 'no button');

console.log('\n--- a foreign file does not bring the server down ---');
const bad = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/track', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({path: '/no/such.wav', track: 'instrumental'})
})).json();
let bj = bad.error ? {done:true, ok:false, error:bad.error} : null;
for (let i = 0; bad.job && i < 30; i++){
  await new Promise(r=>setTimeout(r,500));
  bj = await (await fetch(API+'/api/job?id='+bad.job)).json();
  if (bj.done) break;
}
ok('a missing file gives a clear error, not a crash',
   bj && bj.done && !bj.ok && !!bj.error, bj ? String(bj.error).slice(0,60) : '');
const still = await proj();
ok('the project was not harmed by it', still.lines.length === after.lines.length &&
   !!still.tracks.instrumental);

ok('no JS errors', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
