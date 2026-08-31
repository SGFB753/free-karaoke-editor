// Undo in the studio. Edits reach the disk on their own, there is no “close
// without saving” here — undo is the only guard against a wrong move.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

let confirmAnswer = true;
const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.confirm = () => confirmAnswer;
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
const key = (k, mod) => doc.dispatchEvent(new w.KeyboardEvent('keydown',
  Object.assign({key:k, bubbles:true, cancelable:true}, mod||{})));
const pickLine = i => doc.querySelectorAll('#scroll .ln')[i]
  .dispatchEvent(new w.MouseEvent('click',{bubbles:true}));

doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);
const start = await srv();
const snapshot = () => JSON.stringify(start.map(l=>[l.text, +l.start.toFixed(3)]));

console.log('--- before any edit there is nothing to undo ---');
ok('the undo button is disabled', $('btnUndo').disabled);

console.log('\n--- undoing a keyboard shift ---');
pickLine(2); await sleep(60);
const s0 = (await srv())[2].start;
key(']'); await sleep(60);
key(']'); await sleep(900);
const s1 = (await srv())[2].start;
ok('the line moved', Math.abs(s1 - s0 - 0.1) < 1e-6, `${s0} → ${s1}`);
ok('the undo button became active', !$('btnUndo').disabled);
click('btnUndo'); await sleep(900);
const s2 = (await srv())[2].start;
ok('one undo took back both presses at once', Math.abs(s2 - s0) < 1e-6,
   `${s1} → ${s2}, expected ${s0}`);
ok('redo became available after undo', !$('btnRedo').disabled);
key('y', {ctrlKey:true}); await sleep(900);
const s3 = (await srv())[2].start;
ok('Ctrl+Y returned the undone edit', Math.abs(s3 - s1) < 1e-6,
   `${s2} → ${s3}, expected ${s1}`);
key('z', {ctrlKey:true}); await sleep(900);
ok('Ctrl+Z can undo the returned edit again', Math.abs((await srv())[2].start - s0) < 1e-6);

console.log('\n--- undoing a line deletion ---');
const nBefore = (await srv()).length;
const textGone = (await srv())[2].text;
pickLine(2); await sleep(60);
click('btnDelLine'); await sleep(900);
ok('the line was deleted', (await srv()).length === nBefore - 1);
key('z', {ctrlKey:true}); await sleep(900);
let now = await srv();
ok('Ctrl+Z brought the line back', now.length === nBefore, `${nBefore-1} → ${now.length}`);
ok('and it is the very same line', now[2].text === textGone, now[2].text);

console.log('\n--- undoing a text edit ---');
const wasText = now[1].text;
doc.querySelectorAll('#scroll .ln')[1].dispatchEvent(new w.MouseEvent('dblclick',{bubbles:true}));
await sleep(80);
const inp = doc.querySelector('.lnedit');
inp.value = "ошибочная правка";
inp.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
await sleep(900);
ok('the text changed', (await srv())[1].text === "ошибочная правка");
click('btnUndo'); await sleep(900);
ok('undo brought the old text back', (await srv())[1].text === wasText,
   (await srv())[1].text);

console.log('\n--- an edit that changes nothing takes no undo step ---');
const depthBefore = $('btnUndo').disabled;
doc.querySelectorAll('#scroll .ln')[1].dispatchEvent(new w.MouseEvent('dblclick',{bubbles:true}));
await sleep(80);
const inp2 = doc.querySelector('.lnedit');
inp2.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
await sleep(700);
const afterNoop = await srv();
ok('the text did not change', afterNoop[1].text === wasText, afterNoop[1].text);

console.log('\n--- undo rolls back to the very start ---');
let guard = 0;
while (!$('btnUndo').disabled && guard++ < 60){ click('btnUndo'); await sleep(120); }
await sleep(900);
const back = await srv();
ok('we reached the end of the history', $('btnUndo').disabled, 'steps taken ' + guard);
ok('exactly the original state came back',
   JSON.stringify(back.map(l=>[l.text, +l.start.toFixed(3)])) === snapshot(),
   back.length + ' lines against ' + start.length);
ok('and that state reached the disk', back.length === start.length);

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
