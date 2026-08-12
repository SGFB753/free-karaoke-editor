// Words inside a line move one by one: the rhythm of a song is hardly ever even.
// And separately — saving: the state is visible, export waits for the disk.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m)); w.confirm=()=>true;
    w.__beacons=[]; w.navigator.sendBeacon = (u,b) => { w.__beacons.push(u); return true; };
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
const pe = (t,x) => { const e = new w.MouseEvent(t,{bubbles:true,cancelable:true,clientX:x});
                      Object.defineProperty(e,'pointerId',{value:1}); return e; };

doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);

console.log('--- the word row appears for the selected line ---');
doc.querySelectorAll('#scroll .ln')[2].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
let chips = [...doc.querySelectorAll('.wrd')];
const line = (await srv())[2];
ok('the words are shown as separate chips', chips.length === line.words.length,
   `${chips.length} against ${line.words.length} words`);
ok('the chip carries the word itself', chips[0].textContent === line.words[0].w,
   `«${chips[0].textContent}»`);
// tiny 9px strips could not be read — that was the “useless thing”
const css = w.getComputedStyle(chips[0]);
// The sizes are in rem off html{font-size:clamp(16px…)} — jsdom does not compute them.
// Take the lower bound of the clamp, 16px: pass there and it passes on a big screen.
const cssPx = v => /rem$/.test(String(v)) ? parseFloat(v) * 16 : parseFloat(v || 0);
ok('the chips are of readable size, not decorative strips',
   cssPx(css.fontSize) >= 11, css.fontSize);

console.log('\n--- the row follows the selected line ---');
doc.querySelectorAll('#scroll .ln')[3].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
const line3 = (await srv())[3];
ok('the words belong to another line now',
   [...doc.querySelectorAll('.wrd')].length === line3.words.length,
   `${doc.querySelectorAll('.wrd').length} against ${line3.words.length}`);

console.log('\n--- moving a single word ---');
doc.querySelectorAll('#scroll .ln')[2].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
const was = (await srv())[2];
chips = [...doc.querySelectorAll('.wrd')];
// Take a word with room to its right: earlier checks have already edited
// this line, and the room may have run out.
let J = 1;
for (let k = 1; k < was.words.length - 1; k++){
  const room = was.words[k+1].t - was.words[k].t;
  if (room > (was.words[J+1] ? was.words[J+1].t - was.words[J].t : 0)) J = k;
}
ok('found a word with room to move',
   was.words[J+1] && was.words[J+1].t - was.words[J].t > 0.2,
   `room ${(was.words[J+1] ? was.words[J+1].t - was.words[J].t : 0).toFixed(2)} s`);
chips[J].dispatchEvent(pe('pointerdown', 100));
w.dispatchEvent(pe('pointermove', 130));
ok('the caption shows the word, not the line', /слово «/.test($('selNote').textContent),
   $('selNote').textContent);
w.dispatchEvent(pe('pointerup', 130));
await sleep(900);

const now = (await srv())[2];
ok('the word moved right', now.words[J].t > was.words[J].t + 0.02,
   `${was.words[J].t.toFixed(3)} → ${now.words[J].t.toFixed(3)}`);
// The words are no longer glued end to end: each has its own length, and a
// gap between them is allowed. Move one — the neighbours stay put.
// Run into a neighbour and it gives way; do not, and it stays where it was.
const myEnd = now.words[J].t + now.words[J].d;
ok('the right neighbour gave way exactly, no more',
   Math.abs(now.words[J+1].t - Math.max(was.words[J+1].t, myEnd)) < 0.005,
   `${was.words[J+1].t.toFixed(3)} → ${now.words[J+1].t.toFixed(3)}`);
ok('the left neighbour stayed put',
   J < 1 || Math.abs(now.words[J-1].t - was.words[J-1].t) < 1e-6);
ok('nothing collapsed to zero', now.words.every(x => x.d >= 0.05),
   now.words.map(x=>x.d.toFixed(2)).join(' '));
ok('the length of the word itself was kept',
   Math.abs(now.words[J].d - was.words[J].d) < 0.005,
   `${was.words[J].d.toFixed(3)} → ${now.words[J].d.toFixed(3)} s`);
ok('it did not run over its neighbours',
   now.words[J].t >= now.words[J-1].t + now.words[J-1].d - 1e-6 &&
   now.words[J].t + now.words[J].d <= now.words[J+1].t + 1e-6,
   `${now.words[J].t.toFixed(3)}–${(now.words[J].t+now.words[J].d).toFixed(3)}`);
ok('the words still go in order',
   now.words.every((x,k)=> k===0 || x.t >= now.words[k-1].t - 1e-9));
ok('and none of them collapsed to zero', now.words.every(x => x.d >= 0.05),
   now.words.map(x=>x.d.toFixed(2)).join(' '));
ok('the bounds of the line are respected',
   now.words[0].t >= now.start - 1e-6 &&
   now.words[now.words.length-1].t < now.end + 1e-6);
ok('the text of the line was not harmed', now.text === was.text, now.text);

console.log('\n--- a word does not run over its neighbours ---');
chips = [...doc.querySelectorAll('.wrd')];
chips[J].dispatchEvent(pe('pointerdown', 100));
w.dispatchEvent(pe('pointermove', 900));       // drag far past the next word
w.dispatchEvent(pe('pointerup', 900));
await sleep(900);
const far = (await srv())[2];
ok('it stopped at the next word instead of jumping over',
   far.words[J].t < far.words[J+1].t &&
   far.words.every((x,k)=> k===0 || x.t >= far.words[k-1].t - 1e-9),
   far.words.map(x=>x.t.toFixed(2)).join(' '));

console.log('\n--- undo brings the word back ---');
$('btnUndo').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(900);
const undone = (await srv())[2];
ok('the word returned to where it was',
   Math.abs(undone.words[J].t - now.words[J].t) < 1e-6,
   `${far.words[J].t.toFixed(3)} → ${undone.words[J].t.toFixed(3)}`);

console.log('\n--- saving is visible and not lagging ---');
ok('after writing it says so — saved', $('savedNote').textContent === 'сохранено',
   $('savedNote').textContent);
doc.querySelectorAll('#scroll .ln')[1].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true,cancelable:true}));
ok('right after an edit it honestly says it is not saved yet',
   $('savedNote').textContent === 'не сохранено', $('savedNote').textContent);
await sleep(900);
ok('and a moment later — saved', $('savedNote').textContent === 'сохранено',
   $('savedNote').textContent);

console.log('\n--- export waits for the write to disk ---');
const marker = (await srv())[1].start;
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true,cancelable:true}));
$('btnExportHtml').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));  // at once, without waiting for the autosave
await sleep(1400);
const shipped = (await srv())[1].start;
ok('the server got the fresh edit before building the file',
   Math.abs(shipped - marker - 0.05) < 1e-6,
   `${marker.toFixed(3)} → ${shipped.toFixed(3)}`);

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
