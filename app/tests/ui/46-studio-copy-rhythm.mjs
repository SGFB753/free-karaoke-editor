// A tuned line need not be timed again: its rhythm is copied into lines like it,
// and the line itself can be duplicated whole.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();
const sleep = ms => new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m)); w.confirm=()=>true;
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
w.eval(js);
await sleep(900);

const PID = (await (await fetch(API+"/api/state")).json()).projects[0].id;
const srv = async () => (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json()).lines;
const put = async ls => fetch(API+'/api/project/'+encodeURIComponent(PID)+'/timings',
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({lines: ls})});
const pick = i => doc.querySelectorAll('#scroll .ln')[i]
                     .dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
const click = id => $(id).dispatchEvent(new w.MouseEvent('click',{bubbles:true}));

// Our own timing for the duration of the check: two identical lines, like a chorus.
const original = await srv();
const test = JSON.parse(JSON.stringify(original));
test[1].text = test[3].text = "Раз два три";
[1, 3].forEach(i => {
  const ln = test[i];
  ln.words = ["Раз", "два", "три"].map((word, j) => ({
    w: word, t: +(ln.start + j * 0.4).toFixed(3), d: 0.4, s: 1}));
  ln.end = +(ln.start + 1.2).toFixed(3);
});
await put(test);
await sleep(300);
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1400);

console.log('--- copying the rhythm of a tuned line ---');
pick(1); await sleep(120);
// make a rhythm “of our own”: the first word short, the second long
await sleep(50);
const lines0 = await srv();
const mine = JSON.parse(JSON.stringify(lines0));
mine[1].words[0].d = 0.2;
mine[1].words[1].t = mine[1].start + 0.2; mine[1].words[1].d = 0.9;
mine[1].words[2].t = mine[1].start + 1.1; mine[1].words[2].d = 0.3;
await put(mine);
await sleep(200);
doc.querySelectorAll('.card') && click("btnBack");
await sleep(900);
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1400);

pick(1); await sleep(150);
ok('the paste button is not available yet', $("btnPaste").disabled);
click("btnRhythm"); await sleep(150);
ok('after copying, pasting is available', !$("btnPaste").disabled);
ok('the button shows how many such lines there are', /×2|2/.test($("btnPaste").textContent),
   $("btnPaste").textContent);

console.log('\n--- pasting into a line just like it ---');
pick(3); await sleep(150);
click("btnPaste"); await sleep(1000);
const after = await srv();
const src = mine[1], dst = after[3];
ok('the words fell into the same pattern',
   dst.words.every((x, j) => Math.abs((x.t - dst.start) - (src.words[j].t - src.start)) < 0.004),
   dst.words.map(x => (x.t - dst.start).toFixed(2)).join(' ') + ' vs ' +
   src.words.map(x => (x.t - src.start).toFixed(2)).join(' '));
ok('and the same lengths', dst.words.every((x, j) => Math.abs(x.d - src.words[j].d) < 0.004),
   dst.words.map(x => x.d.toFixed(2)).join(' '));
ok('the start of the line did not move', Math.abs(dst.start - mine[3].start) < 1e-6,
   `${mine[3].start} → ${dst.start}`);
ok('the line is not shorter than its words',
   dst.end >= dst.words[dst.words.length-1].t + dst.words[dst.words.length-1].d - 1e-6);

console.log('\n--- it does not fit a line with a different word count ---');
pick(0); await sleep(150);
const was0 = (await srv())[0];
click("btnPaste"); await sleep(700);
const now0 = (await srv())[0];
ok('the other line was not touched',
   now0.words.length === was0.words.length &&
   now0.words.every((x, j) => Math.abs(x.t - was0.words[j].t) < 1e-6));
ok('and it is said out loud', /слов|words/.test($("toast").textContent), $("toast").textContent);

console.log('\n--- a copy of a batch of lines ---');
// Select two lines, copy and paste — they must appear below.
pick(1); await sleep(120);
doc.querySelectorAll('#scroll .ln')[2].dispatchEvent(
  new w.MouseEvent('click',{bubbles:true, shiftKey:true}));
await sleep(150);
click("btnRhythm"); await sleep(150);
ok('it says how many lines were copied', /2/.test($("toast").textContent),
   $("toast").textContent);
const beforeBlock = await srv();
pick(4); await sleep(150);
click("btnPasteLine"); await sleep(1000);
const withBlock = await srv();
ok('there are two more lines', withBlock.length === beforeBlock.length + 2,
   `${beforeBlock.length} → ${withBlock.length}`);
ok('exactly the copied ones were pasted',
   withBlock[5].text === beforeBlock[1].text && withBlock[6].text === beforeBlock[2].text,
   `${withBlock[5].text} | ${withBlock[6].text}`);
ok('they come after the line we were standing on',
   withBlock[5].start >= withBlock[4].end - 1e-6,
   `${withBlock[4].end.toFixed(2)} → ${withBlock[5].start.toFixed(2)}`);
ok('and they do not run into the next one',
   !withBlock[7] || withBlock[6].end <= withBlock[7].start + 0.01,
   `${withBlock[6].end.toFixed(2)} vs ${withBlock[7] ? withBlock[7].start.toFixed(2) : '—'}`);
ok('the line we were standing on stayed as it was',
   withBlock[4].text === beforeBlock[4].text, `${beforeBlock[4].text} → ${withBlock[4].text}`);
ok('and all the previous text is in place',
   beforeBlock.every(l => withBlock.some(x => x.text === l.text)));
ok('the words of the copies are inside their own lines',
   [5,6].every(i => withBlock[i].words.every(x => x.t >= withBlock[i].start - 1e-6 &&
                    x.t + x.d <= withBlock[i].end + 0.01)));
click("btnUndo"); await sleep(1000);
ok('Ctrl+Z removes the pasted batch', (await srv()).length === beforeBlock.length);

console.log('\n--- duplicating a whole line ---');
pick(1); await sleep(150);
const before = (await srv()).length;
w.document.dispatchEvent(new w.KeyboardEvent('keydown',
  {key:'d', ctrlKey:true, bubbles:true, cancelable:true}));
await sleep(1000);
const dup = await srv();
ok('there is one more line', dup.length === before + 1, `${before} → ${dup.length}`);
ok('the copy sits right under the original', dup[2].text === dup[1].text, dup[2].text);
ok('the copy comes after the original in time', dup[2].start >= dup[1].end - 1e-6,
   `${dup[1].end} → ${dup[2].start}`);
ok("the copy's words are inside its own bounds",
   dup[2].words.every(x => x.t >= dup[2].start - 1e-6 &&
                           x.t + x.d <= dup[2].end + 0.001),
   `${dup[2].start.toFixed(2)}–${dup[2].end.toFixed(2)}: ` +
   dup[2].words.map(x => `${x.t.toFixed(2)}+${x.d.toFixed(2)}`).join(' '));
ok('the copy does not run into the next line',
   !dup[3] || dup[2].end <= dup[3].start + 0.001,
   `${dup[2].end.toFixed(2)} vs ${dup[3] ? dup[3].start.toFixed(2) : '—'}`);
click("btnUndo"); await sleep(900);
ok('Ctrl+Z removes the copy', (await srv()).length === before);

await put(original);                       // the stand as it was
await sleep(300);
ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
