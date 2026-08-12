// A new lyrics file for a finished song: the split into lines gets fixed after
// the first build, once it is clear how it is easier to sing. The tracks need
// no recomputing — only the timing changes.
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

// The same text, split finer — exactly the “I did it line by line” case.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lyr_'));
const fine = path.join(tmp, 'per-line.txt');
const split = before.lines.map(l => {
  const w = l.text.split(' ');
  const half = Math.ceil(w.length / 2);
  return [w.slice(0, half).join(' '), w.slice(half).join(' ')].filter(Boolean);
}).flat();
fs.writeFileSync(fine, 'title: Тестовая песня\n\n' + split.join('\n') + '\n', 'utf8');
ok('a file with a finer split is ready', split.length > before.lines.length,
   `${before.lines.length} → ${split.length} lines`);

console.log('\n--- timing for the new text ---');
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
ok('the recount went through', job && job.ok, job ? String(job.error) : 'never arrived');
ok('the log mentions the changed split',
   (job.log||[]).some(l => /строк/.test(l)), (job.log||[]).slice(-3).join(' | '));

const after = await proj();
ok('there are now as many lines as in the file', after.lines.length === split.length,
   `${after.lines.length} against ${split.length}`);
ok('the text came from the new file',
   after.lines.map(l=>l.text).join('|') === split.join('|'),
   after.lines.slice(0,2).map(l=>l.text).join(' / '));
ok('every line has a time', after.lines.every(l => l.end > l.start));
ok('the lines go in order',
   after.lines.every((l,i) => i===0 || l.start >= after.lines[i-1].start - 1e-6));
ok('everything fits inside the song',
   after.lines[after.lines.length-1].end <= after.duration + 0.5,
   `${after.lines[after.lines.length-1].end.toFixed(2)} with duration ${after.duration}`);
// Times in the project are rounded to a millisecond, hence a 2 ms tolerance, not zero.
const outside = after.lines.filter(l => !(l.words.length > 0 &&
     l.words[0].t >= l.start - 0.002 &&
     l.words.at(-1).t + l.words.at(-1).d <= l.end + 0.002));
ok('the words are laid out inside their lines', outside.length === 0,
   outside.slice(0,2).map(l => `«${l.text}» ${l.start.toFixed(3)}–${l.end.toFixed(3)}, ` +
     `words ${l.words[0]?.t.toFixed(3)}–${(l.words.at(-1)?.t + l.words.at(-1)?.d).toFixed(3)}`).join(' ; '));
ok('the tracks were not touched',
   JSON.stringify(after.tracks) === JSON.stringify(before.tracks),
   JSON.stringify(after.tracks));
ok('the new file is remembered as the source', /per-line\.txt$/.test(after.source_lyrics || ''),
   String(after.source_lyrics));

console.log('\n--- the same file, just edited ---');
// The commonest case: the source txt is edited and the timing is rebuilt
// without picking anything again.
fs.writeFileSync(fine, 'title: Тестовая песня\n\n' +
  split.slice(0, split.length - 1).join('\n') + '\n', 'utf8');
const jSame = await (await fetch(API+'/api/project/'+encodeURIComponent(PID)+'/realign', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({align:'energy'})            // no file named at all
})).json();
let jobSame = null;
for (let i = 0; i < 60; i++){
  await sleep(800);
  jobSame = await (await fetch(API+'/api/job?id='+jSame.job)).json();
  if (jobSame.done) break;
}
ok('the recount along the same path went through', jobSame && jobSame.ok,
   jobSame ? String(jobSame.error) : '');
const edited = await proj();
ok('the edited file was picked up without choosing a file again',
   edited.lines.length === split.length - 1,
   `${split.length} → ${edited.lines.length} lines`);

console.log('\n--- an empty file does not spoil the project ---');
const empty = path.join(tmp, 'empty.txt');
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
ok('empty text is refused with an explanation',
   job2 && job2.done && !job2.ok && /строк/i.test(String(job2.error)),
   job2 ? String(job2.error).slice(0,60) : '');
const still = await proj();
ok('the song stayed intact', still.lines.length === edited.lines.length);

console.log('\n--- the button in the window ---');
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
ok('the “Other lyrics” button exists and is labelled plainly',
   !!$('btnLyrics') && /текст/i.test($('btnLyrics').textContent),
   ($('btnLyrics')||{}).textContent);
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(400);
ok('it asks before replacing the timing',
   w.__asked.some(q => /правк/i.test(q)), w.__asked[0] || 'it did not ask');
ok('the file browser opened', !$('browser').classList.contains('hide'));
ok('and it is labelled to the point', /новым текстом/i.test($('brTitle').textContent),
   $('brTitle').textContent);
const shown = [...doc.querySelectorAll('#brBody .row .nm')].map(e=>e.textContent);
ok('it shows text files, not audio',
   shown.every(n => !/\.(mp3|wav|flac|m4a)$/i.test(n)), shown.slice(0,4).join(', '));

console.log('\n--- putting the old text back ---');
const back = path.join(tmp, 'previous.txt');
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
ok('the project went back to the old text',
   restored.lines.length === before.lines.length, `${restored.lines.length}`);

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
