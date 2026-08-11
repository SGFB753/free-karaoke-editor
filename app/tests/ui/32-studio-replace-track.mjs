// Подмена минусовки на настоящую. Разметка уже выверена руками — она должна
// остаться, а если официальный инструментал начинается не там же, сдвиг
// нужно найти и применить.
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { execFileSync } from 'child_process';

const API = process.env.KARAOKE_API;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'trk_'));
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };

// «Настоящая минусовка»: та же песня, но начатая на 1,5 с позже.
const shifted = path.join(tmp, 'настоящая.wav');
execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', process.env.KARAOKE_SONG,
  '-af', 'adelay=1500|1500', shifted]);
ok('подготовлена дорожка со сдвигом 1,5 с', fs.existsSync(shifted));

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
ok('в проекте одна дорожка', !!before.tracks, JSON.stringify(before.tracks));

console.log('\n--- меняем минусовку ---');
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
ok('замена прошла', job && job.ok, job ? String(job.error) : 'не дождались');
const res = job.result || {};
ok('сдвиг найден и он около 1,5 с', Math.abs(res.offset - 1.5) < 0.25,
   `нашлось ${res.offset}`);
ok('разметка сдвинута следом', Math.abs(res.shifted - res.offset) < 1e-9,
   String(res.shifted));

const after = await proj();
ok('минусовка появилась', !!after.tracks.instrumental, JSON.stringify(after.tracks));
ok('голос остался, чтобы было подо что петь', !!after.tracks.vocals,
   JSON.stringify(after.tracks));
ok('строки те же самые', after.lines.length === before.lines.length);
ok('текст не пострадал',
   after.lines.map(l=>l.text).join('|') === before.lines.map(l=>l.text).join('|'));
ok('все строки уехали ровно на сдвиг',
   after.lines.every((l,i) => Math.abs((l.start - before.lines[i].start) - res.offset) < 0.01),
   `${before.lines[0].start.toFixed(2)} → ${after.lines[0].start.toFixed(2)}`);
ok('слова внутри строк уехали вместе с ними',
   after.lines.every((l,i) => l.words.every((w,k) =>
     Math.abs((w.t - before.lines[i].words[k].t) - res.offset) < 0.01)));
ok('длительность проекта учла сдвиг', after.duration > before.duration - 0.01,
   `${before.duration} → ${after.duration}`);

console.log('\n--- голос звучит в такт с новой минусовкой ---');
// Голос был размечен под старую запись. Если его не подвинуть, он поёт
// невпопад с новым инструменталом — самая заметная беда при подмене.
const both = await fetch(API+'/api/project/'+encodeURIComponent(PID));
const withVoice = await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json();
ok('голос в проекте остался', !!withVoice.tracks.vocals, JSON.stringify(withVoice.tracks));
{
  // сверяем сами дорожки: скачиваем и сравниваем громкости
  const get = async name => {
    const r = await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/audio/'+name);
    return Buffer.from(await r.arrayBuffer());
  };
  const inst = await get('instrumental'), voc = await get('vocals');
  ok('обе дорожки скачиваются', inst.length > 5000 && voc.length > 5000,
     `${inst.length} и ${voc.length} байт`);
  fs.writeFileSync(path.join(tmp,'i.mp3'), inst);
  fs.writeFileSync(path.join(tmp,'v.mp3'), voc);
  const dur = f => parseFloat(execFileSync('ffprobe',
    ['-v','error','-show_entries','format=duration','-of','csv=p=0', f]).toString());
  const di = dur(path.join(tmp,'i.mp3')), dv = dur(path.join(tmp,'v.mp3'));
  ok('голос стал такой же длины, как новая минусовка', Math.abs(di - dv) < 0.35,
     `минус ${di.toFixed(2)} с, голос ${dv.toFixed(2)} с`);
  ok('голос удлинился ровно на сдвиг', Math.abs(dv - (before.duration + res.offset)) < 0.35,
     `${before.duration.toFixed(2)} + ${res.offset.toFixed(2)} → ${dv.toFixed(2)}`);
}

console.log('\n--- новая дорожка реально отдаётся ---');
const snd = await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/audio/instrumental');
ok('минусовка скачивается', snd.ok && +snd.headers.get('content-length') > 10000,
   snd.status + ', ' + snd.headers.get('content-length') + ' байт');

console.log('\n--- кнопка есть в окне ---');
await p.reload({waitUntil:'networkidle0'});
await new Promise(r=>setTimeout(r,600));
await p.click('.card');
await new Promise(r=>setTimeout(r,2500));
const btn = await p.evaluate(() => {
  const b = document.getElementById('btnTrack');
  return b ? {text: b.textContent.trim(), visible: !!b.offsetParent} : null;
});
ok('кнопка «Своя минусовка» на виду', btn && btn.visible, btn ? btn.text : 'нет кнопки');

console.log('\n--- чужой файл не роняет сервер ---');
const bad = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/track', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({path: '/нет/такого.wav', track: 'instrumental'})
})).json();
let bj = null;
for (let i = 0; i < 30; i++){
  await new Promise(r=>setTimeout(r,500));
  bj = await (await fetch(API+'/api/job?id='+bad.job)).json();
  if (bj.done) break;
}
ok('несуществующий файл — понятная ошибка, а не падение',
   bj && bj.done && !bj.ok && !!bj.error, bj ? String(bj.error).slice(0,60) : '');
const still = await proj();
ok('проект от этого не пострадал', still.lines.length === after.lines.length &&
   !!still.tracks.instrumental);

ok('ошибок JS нет', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
