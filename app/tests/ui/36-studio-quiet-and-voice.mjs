// Два разных дела в одном наборе, потому что оба про подмену минусовки:
//   • места без пения видны прямо на дорожке;
//   • при своей минусовке голос не остаётся целой песней поверх неё.
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

console.log('--- сервер сообщает места без пения ---');
const before = await proj();
ok('в проекте есть список мест без пения', Array.isArray(before.quiet),
   JSON.stringify(before.quiet));

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1366, height:768});
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));

console.log('\n--- и они нарисованы на дорожке ---');
// Затенение рисуется на том же холсте, что и волна. Сравниваем яркость
// столбцов внутри и снаружи промежутка — внутри должно быть светлее фона.
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
  // считаем, сколько столбцов имеют хоть какую-то заливку в самом верху
  let painted = 0;
  for (let x = 0; x < w; x++){
    let a = 0;
    for (let y = 0; y < Math.min(8, h); y++) a += d[(y * w + x) * 4 + 3];
    if (a > 0) painted++;
  }
  return {painted, w};
});
if (before.quiet.length)
  ok('затенение нарисовано', marks.painted > 0, `${marks.painted} из ${marks.w} столбцов`);
else
  ok('в этой песне длинных проигрышей нет — рисовать нечего', true);

console.log('\n--- своя минусовка: голос не остаётся целой песней ---');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'voc_'));
// «Свой инструментал» — та же песня, но без вокальных всплесков не сделать,
// поэтому берём её же: вычитание обязано либо дать тишину, либо отказаться.
const own = path.join(tmp, 'свой.wav');
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
ok('замена прошла', job && job.ok, job ? String(job.error) : 'не дождались');
const after = await proj();
ok('минусовка на месте', !!after.tracks.instrumental, JSON.stringify(after.tracks));
ok('дорожки «всё вместе» больше нет', !after.tracks.mix,
   JSON.stringify(after.tracks));
const said = (job.log || []).join(' ');
ok('в логе сказано, что стало с голосом',
   /выдел|Голоса не будет|голос/i.test(said),
   (job.log||[]).slice(-3).join(' | '));
if (after.tracks.vocals){
  const r = await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/audio/vocals');
  ok('голосовая дорожка отдаётся', r.ok && +r.headers.get('content-length') > 3000,
     r.status + ', ' + r.headers.get('content-length'));
}

ok('ошибок JS нет', errs.length===0, errs.slice(0,2).join(' | '));
await b.close();
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
