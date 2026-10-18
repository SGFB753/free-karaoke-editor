// A forgotten or a stray line: added and removed right inside the studio.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

let confirmAnswer = true;
const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.__asked=[]; w.confirm = q => { w.__asked.push(q); return confirmAnswer; };
    w.fetch = (...a) => fetch(typeof a[0]==="string" && a[0].startsWith("/")
        ? API + a[0] : a[0], a[1]);
    w.__now=0;
    w.AudioContext = class { constructor(){ this.state="running"; this.destination={}; }
      get currentTime(){ return w.__now; }
      createGain(){ return {gain:{value:1, setTargetAtTime(v){this.value=v;}}, connect(){}}; }
      createBufferSource(){ return {connect(){},start(){},stop(){},onended:null}; }
      decodeAudioData(){ return Promise.resolve({duration:26.04}); } resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () =>
      ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
    w.Element.prototype.setPointerCapture = function(){};
    Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{get(){return 900;}});
    Object.defineProperty(w.HTMLElement.prototype,'clientHeight',{get(){return 400;}});
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r=>setTimeout(r,ms));
w.eval(js);
await sleep(900);

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const st = await (await fetch(API+"/api/state")).json();
const PID = st.projects[0].id;
const srv = async () => (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json()).lines;
const click = id => $(id).dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
const seek = time => {
  const options = {clientX:time / 26.04 * 900,bubbles:true};
  $('mmap').dispatchEvent(new w.MouseEvent('pointerdown',options));
  $('mmap').dispatchEvent(new w.MouseEvent('pointerup',options));
};
const reopen = async () => {
  doc.querySelector('.card').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await sleep(1200);
};

doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);
const before = await srv();

console.log('--- inserting before the first line without a selection ---');
seek(0);
click('btnAddLine');
await sleep(100);
let firstInput = doc.querySelector('.lnedit');
ok('a selection is not required to insert at the beginning', !!firstInput);
if (firstInput){
  firstInput.value = 'первое вступление';
  firstInput.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
}
await sleep(700);
let inserted = await srv();
ok('the inserted opening is first and starts at the playhead',
   inserted[0].text === 'первое вступление' && inserted[0].start === 0);
ok('existing lines retain all their timings, words and properties',
   JSON.stringify(inserted.slice(1)) === JSON.stringify(before));
ok('preview and timeline both place the new line first',
   doc.querySelector('#scroll .ln .hl')?.textContent.trim() === 'первое' &&
   doc.querySelector('.blk[data-i="0"]')?.textContent.startsWith('1. первое вступление'));
click('btnUndo'); click('btnUndo');
await sleep(600);
ok('undo restores the original list and timing', JSON.stringify(await srv()) === JSON.stringify(before));
click('btnRedo'); click('btnRedo');
await sleep(600);
ok('redo restores the inserted opening and its place', (await srv())[0].text === 'первое вступление');
await reopen();
await sleep(100);
ok('saving and reopening retains the opening as line one',
   doc.querySelector('#scroll .ln .hl')?.textContent.trim() === 'первое' &&
   doc.querySelector('.blk[data-i="0"]')?.textContent.startsWith('1. первое вступление'));
doc.querySelector('#scroll .ln').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
click('btnDelLine');
await sleep(700);
ok('deleting the new opening leaves the original song unchanged',
   JSON.stringify(await srv()) === JSON.stringify(before));
await reopen(); // clear fixture-only undo history before the next case

console.log('--- inserting a forgotten line ---');
doc.querySelectorAll('#scroll .ln')[before.length - 1].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(80);
seek(before[1].end);
click('btnAddLine');
await sleep(120);
const inp = doc.querySelector('.lnedit');
ok('the text field opened right away', !!inp);
inp.value = "забытая строка припева";
inp.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
await sleep(900);

const after = await srv();
ok('there is one more line', after.length === before.length + 1,
   `${before.length} → ${after.length}`);
ok('the new line went at the playhead between its neighbours', after[2].text === "забытая строка припева",
   after[2].text);
ok('the neighbouring lines did not move',
   after[1].text === before[1].text && after[3].text === before[2].text);
ok('it starts where the previous one ended',
   Math.abs(after[2].start - after[1].end) < 1e-6,
   `${after[1].end.toFixed(2)} / ${after[2].start.toFixed(2)}`);
const room = after[3].start - after[2].start;
ok('it lasts sensibly and does not run into the next one when there is room',
   after[2].end > after[2].start &&
   after[2].end - after[2].start <= 2 + 1e-6 &&
   (room <= 0.4 || after[2].end <= after[3].start + 1e-6),
   `room ${room.toFixed(2)} s, line ${(after[2].end-after[2].start).toFixed(2)} s`);
ok('the words are laid out inside it', after[2].words.length === 3 &&
   after[2].words[0].t >= after[2].start - 1e-6,
   after[2].words.length + ' words');
ok('the section heading was not duplicated', !after[2].section, String(after[2].section));
ok('a block appeared on the timeline', doc.querySelectorAll('.blk').length === after.length,
   doc.querySelectorAll('.blk').length + ' blocks');

console.log('\n--- deleting a stray line ---');
doc.querySelectorAll('#scroll .ln')[2].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(80);
confirmAnswer = false;
click('btnDelLine');
await sleep(700);
let now = await srv();
ok('nothing is deleted without confirmation', now.length === after.length,
   `${after.length} → ${now.length}`);
ok('and it asks in plain words', /Удалить строку/.test(w.__asked.join(' ')),
   w.__asked[w.__asked.length-1]);

confirmAnswer = true;
click('btnDelLine');
await sleep(900);
now = await srv();
ok('the line was deleted', now.length === before.length, `${after.length} → ${now.length}`);
ok('that is the one that went', !now.some(l => l.text === "забытая строка припева"));
ok('the rest of the text is intact',
   now.map(l=>l.text).join('|') === before.map(l=>l.text).join('|'));
ok('the timeline has as many blocks as there are lines',
   doc.querySelectorAll('.blk').length === now.length,
   doc.querySelectorAll('.blk').length + ' / ' + now.length);

console.log('\n--- insertion near the end stays within the audio ---');
seek(25.04);
click('btnAddLine');
await sleep(100);
const lastInput = doc.querySelector('.lnedit');
ok('the final gap can receive a new line', !!lastInput);
if (lastInput){
  lastInput.value = 'последняя фраза';
  lastInput.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
}
await sleep(700);
const appended = await srv();
ok('the new final line starts at the playhead and does not exceed the audio',
   appended.at(-1).text === 'последняя фраза' && Math.abs(appended.at(-1).start - 25.04) < .001 &&
   appended.at(-1).end <= 26.04);
click('btnUndo'); click('btnUndo');
await sleep(600);
seek(26.04);
click('btnAddLine');
await sleep(100);
ok('at the audio endpoint no impossible line is created',
   !doc.querySelector('.lnedit') && (await srv()).length === before.length);
// Cleaning up after ourselves: the project on the stand is shared, and the
// edits eat the slack inside the lines — the next run would fail for nothing.
console.log('\n--- putting the project back ---');
let __g = 0;
while (!$('btnUndo').disabled && __g++ < 100){
  $('btnUndo').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await sleep(90);
}
await sleep(900);
ok('the undo history is used up', $('btnUndo').disabled, 'steps ' + __g);

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
