// The report before building: it shows up by itself once both files are picked,
// and it says the same thing that later turns up in the log.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.fetch = (path, opts) => fetch(typeof path === "string" && path.startsWith("/")
        ? API + path : path, opts);
    w.AudioContext = class { constructor(){ this.state="running"; this.destination={}; }
      createGain(){ return {gain:{value:1, setTargetAtTime(v){this.value=v;}}, connect(){}}; }
      createBufferSource(){ return {connect(){},start(){},stop(){}}; }
      decodeAudioData(){ return Promise.resolve({duration:1}); } resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () =>
      ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r=>setTimeout(r,ms));
w.eval(js);
await sleep(900);

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const text = () => $('report').textContent.replace(/\s+/g,' ').trim();

$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);

console.log('--- with no files there is no report ---');
ok('the report is hidden', $('report').classList.contains('hide'));

console.log('\n--- both files picked ---');
$('inAudio').value = process.env.KARAOKE_SONG;
$('inAudio').dispatchEvent(new w.Event('input',{bubbles:true}));
$('inLyrics').value = process.env.KARAOKE_TEXT;
$('inLyrics').dispatchEvent(new w.Event('input',{bubbles:true}));
await sleep(300);
ok('the report appeared and honestly waits at first', !$('report').classList.contains('hide'));
await sleep(6000);

const t = text();
ok('the length of the song is named', /0:2\d/.test(t), t.slice(0, 70));
// We no longer print the tempo in the window: for karaoke it matters more where the text falls silent.
ok('the places without singing are named', /Без пения/.test(t), t.slice(0, 110));
ok('lines and words are counted', /6\b/.test(t) && /Строк/i.test(t), t.slice(0, 120));
ok('the language is named', /русский/i.test(t), t.slice(0, 140));
ok('it says what the program is going to do', /Сделаю/.test(t), t.slice(-120));
ok('there is a time estimate, marked as rough', /займёт/.test(t) && /грубо/.test(t),
   t.slice(-90));

console.log('\n--- the report is recomputed when settings change ---');
// Without stable-ts installed “auto” already means loudness, so the text has
// nothing to change into. The report must still name the engine that was picked.
const caps = (await (await fetch(API + "/api/state")).json()).caps || {};
const before = text();
$('selAlign').value = 'energy';
$('selAlign').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(5000);
const after = text();
ok('the plan changed along with the choice',
   /по энергии/.test(after) && (caps.whisper ? before !== after : /по энергии/.test(before)),
   after.slice(-110));

console.log('\n--- the picked language reaches the report ---');
$('selAlign').value = 'auto';
$('selLang').value = 'en';
$('selLang').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(5000);
ok('the manually picked language is shown', /english/i.test(text()), text().slice(0, 150));

console.log('\n--- a foreign file does not break the window ---');
$('inLyrics').value = '/no/such/file.txt';
$('inLyrics').dispatchEvent(new w.Event('input',{bubbles:true}));
await sleep(3000);
ok('it is said in plain words instead of silence',
   /не найден|Не вышло/i.test(text()), text().slice(0, 90));

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
