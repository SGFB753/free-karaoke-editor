// Новый файл с текстом для готовой песни: разбивку по строкам правят уже
// после первой сборки, когда стало ясно, как удобнее петь. Дорожки при этом
// пересчитывать незачем — меняется только разметка.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
import path from 'path';
import os from 'os';

const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const sleep = ms => new Promise(r=>setTimeout(r,ms));

const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());
const before = await proj();

// Тот же текст, но разбитый мельче — ровно случай «сделал построчно».
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lyr_'));
const fine = path.join(tmp, 'построчно.txt');
const split = before.lines.map(l => {
  const w = l.text.split(' ');
  const half = Math.ceil(w.length / 2);
  return [w.slice(0, half).join(' '), w.slice(half).join(' ')].filter(Boolean);
}).flat();
fs.writeFileSync(fine, 'title: Тестовая песня\n\n' + split.join('\n') + '\n', 'utf8');
ok('готов файл с более мелкой разбивкой', split.length > before.lines.length,
   `${before.lines.length} → ${split.length} строк`);

console.log('\n--- разметка под новый текст ---');
const j = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/realign', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({align:'energy', lyrics: fine})
})).json();
let job = null;
for (let i = 0; i < 90; i++){
  await sleep(1000);
  job = await (await fetch(API+'/api/job?id='+j.job)).json();
  if (job.done) break;
}
ok('пересчёт прошёл', job && job.ok, job ? String(job.error) : 'не дождались');
ok('в логе сказано про смену разбивки',
   (job.log||[]).some(l => /строк/.test(l)), (job.log||[]).slice(-3).join(' | '));

const after = await proj();
ok('строк стало столько же, сколько в файле', after.lines.length === split.length,
   `${after.lines.length} против ${split.length}`);
ok('текст взят из нового файла',
   after.lines.map(l=>l.text).join('|') === split.join('|'),
   after.lines.slice(0,2).map(l=>l.text).join(' / '));
ok('у каждой строки есть время', after.lines.every(l => l.end > l.start));
ok('строки идут по порядку',
   after.lines.every((l,i) => i===0 || l.start >= after.lines[i-1].start - 1e-6));
ok('всё уложилось в песню',
   after.lines[after.lines.length-1].end <= after.duration + 0.5,
   `${after.lines[after.lines.length-1].end.toFixed(2)} при длине ${after.duration}`);
// Времена в проекте округлены до миллисекунды, поэтому допуск 2 мс, а не ноль.
const outside = after.lines.filter(l => !(l.words.length > 0 &&
     l.words[0].t >= l.start - 0.002 &&
     l.words.at(-1).t + l.words.at(-1).d <= l.end + 0.002));
ok('слова разложены внутри своих строк', outside.length === 0,
   outside.slice(0,2).map(l => `«${l.text}» ${l.start.toFixed(3)}–${l.end.toFixed(3)}, ` +
     `слова ${l.words[0]?.t.toFixed(3)}–${(l.words.at(-1)?.t + l.words.at(-1)?.d).toFixed(3)}`).join(' ; '));
ok('дорожки не тронуты',
   JSON.stringify(after.tracks) === JSON.stringify(before.tracks),
   JSON.stringify(after.tracks));
ok('новый файл запомнен как исходный', /построчно\.txt$/.test(after.source_lyrics || ''),
   String(after.source_lyrics));

console.log('\n--- тот же файл, просто отредактированный ---');
// Самый частый случай: правят исходный txt и хотят пересобрать разметку,
// ничего не выбирая заново.
fs.writeFileSync(fine, 'title: Тестовая песня\n\n' +
  split.slice(0, split.length - 1).join('\n') + '\n', 'utf8');
const jSame = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/realign', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({align:'energy'})            // файл не называем вовсе
})).json();
let jobSame = null;
for (let i = 0; i < 60; i++){
  await sleep(800);
  jobSame = await (await fetch(API+'/api/job?id='+jSame.job)).json();
  if (jobSame.done) break;
}
ok('пересчёт по прежнему пути прошёл', jobSame && jobSame.ok,
   jobSame ? String(jobSame.error) : '');
const edited = await proj();
ok('правка файла подхвачена без выбора файла',
   edited.lines.length === split.length - 1,
   `${split.length} → ${edited.lines.length} строк`);

console.log('\n--- пустой файл не портит проект ---');
const empty = path.join(tmp, 'пусто.txt');
fs.writeFileSync(empty, '\n\n\n', 'utf8');
const j2 = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/realign', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({align:'energy', lyrics: empty})
})).json();
let job2 = null;
for (let i = 0; i < 40; i++){
  await sleep(700);
  job2 = await (await fetch(API+'/api/job?id='+j2.job)).json();
  if (job2.done) break;
}
ok('пустой текст отвергнут с объяснением',
   job2 && job2.done && !job2.ok && /строк/i.test(String(job2.error)),
   job2 ? String(job2.error).slice(0,60) : '');
const still = await proj();
ok('песня осталась целой', still.lines.length === edited.lines.length);

console.log('\n--- кнопка в окне ---');
const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.__asked=[]; w.confirm = q => { w.__asked.push(q); return true; };
    w.fetch = (p2, o) => fetch(typeof p2==="string" && p2.startsWith("/") ? API+p2 : p2, o);
    w.AudioContext = class { constructor(){ this.state="running"; this.destination={}; }
      createGain(){ return {gain:{value:1, setTargetAtTime(v){this.value=v;}}, connect(){}}; }
      createBufferSource(){ return {connect(){},start(){},stop(){}}; }
      decodeAudioData(){ return Promise.resolve({duration:26}); } resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () =>
      ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
    Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{get(){return 900;}});
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
w.eval(js);
await sleep(900);
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1500);
ok('кнопка «Другой текст» есть и подписана понятно',
   !!$('btnLyrics') && /текст/i.test($('btnLyrics').textContent),
   ($('btnLyrics')||{}).textContent);
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(400);
ok('спрашивает, прежде чем заменить разметку',
   w.__asked.some(q => /правк/i.test(q)), w.__asked[0] || 'не спросила');
ok('открылся обзор файлов', !$('browser').classList.contains('hide'));
ok('и подписан по делу', /новым текстом/i.test($('brTitle').textContent),
   $('brTitle').textContent);
const shown = [...doc.querySelectorAll('#brBody .row .nm')].map(e=>e.textContent);
ok('показывает текстовые файлы, а не звук',
   shown.every(n => !/\.(mp3|wav|flac|m4a)$/i.test(n)), shown.slice(0,4).join(', '));

console.log('\n--- возвращаем прежний текст ---');
const back = path.join(tmp, 'прежний.txt');
fs.writeFileSync(back, 'title: Тестовая песня\nartist: Проверка Связи\n\n' +
  before.lines.map(l => l.text).join('\n') + '\n', 'utf8');
const j3 = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/realign', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({align:'energy', lyrics: back})
})).json();
for (let i = 0; i < 60; i++){
  await sleep(700);
  const st = await (await fetch(API+'/api/job?id='+j3.job)).json();
  if (st.done) break;
}
const restored = await proj();
ok('проект вернулся к прежнему тексту',
   restored.lines.length === before.lines.length, `${restored.lines.length}`);

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
