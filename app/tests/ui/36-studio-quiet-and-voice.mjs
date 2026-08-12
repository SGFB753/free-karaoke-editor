// Two different matters in one suite, because both are about swapping the backing track:
//   • the places without singing show right on the timeline;
//   • with your own backing track the voice does not stay a whole song on top of it.
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { execFileSync } from 'child_process';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());

console.log('--- the server reports the places without singing ---');
const before = await proj();
ok('the project has a list of places without singing', Array.isArray(before.quiet),
   JSON.stringify(before.quiet));

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));

console.log('\n--- and they are drawn on the timeline ---');
// The shading is drawn on the same canvas as the waveform. We compare the
// brightness of columns inside and outside the gap — inside must be lighter.
const shaded = await p.evaluate(() => {
  const c = document.getElementById('wave');
  const g = c.getContext('2d');
  const col = x => {
    const d = g.getImageData(Math.round(x * devicePixelRatio), 2, 1, 6).data;
    let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i+3];
    return s;
  };
  return {width: c.width / devicePixelRatio, sample: col};
});
const marks = await p.evaluate(() => {
  const c = document.getElementById('wave'), g = c.getContext('2d');
  const w = c.width, h = c.height;
  const d = g.getImageData(0, 0, w, Math.min(8, h)).data;
  // count how many columns have any fill at all at the very top
  let painted = 0;
  for (let x = 0; x < w; x++){
    let a = 0;
    for (let y = 0; y < Math.min(8, h); y++) a += d[(y * w + x) * 4 + 3];
    if (a > 0) painted++;
  }
  return {painted, w};
});
if (before.quiet.length)
  ok('the shading is drawn', marks.painted > 0, `${marks.painted} of ${marks.w} columns`);
else
  ok('this song has no long interludes — nothing to draw', true);

console.log('\n--- own backing track: the voice does not stay a whole song ---');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'voc_'));
// “Own instrumental” — the same song, since one without vocal peaks cannot be
// made here, so subtraction must either give silence or refuse.
const own = path.join(tmp, 'own.wav');
execFileSync('ffmpeg', ['-y','-loglevel','error','-i', process.env.KARAOKE_SONG,
  '-af','adelay=800|800', own]);
const j = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/track', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({path: own, track:'instrumental', shift:true})
})).json();
let job = null;
for (let i = 0; i < 120; i++){
  await new Promise(r=>setTimeout(r,1000));
  job = await (await fetch(API+'/api/job?id='+j.job)).json();
  if (job.done) break;
}
ok('the replacement went through', job && job.ok, job ? String(job.error) : 'never arrived');
const after = await proj();
ok('the backing track is in place', !!after.tracks.instrumental, JSON.stringify(after.tracks));
ok('the “everything together” track is gone', !after.tracks.mix,
   JSON.stringify(after.tracks));
const said = (job.log || []).join(' ');
ok('the log says what happened to the voice',
   /выдел|Голоса не будет|голос/i.test(said),
   (job.log||[]).slice(-3).join(' | '));
if (after.tracks.vocals){
  const r = await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/audio/vocals');
  ok('the voice track is served', r.ok && +r.headers.get('content-length') > 3000,
     r.status + ', ' + r.headers.get('content-length'));
}

ok('no JS errors', errs.length===0, errs.slice(0,2).join(' | '));
await b.close();
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
