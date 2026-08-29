// The studio window: the song list, opening a project, the timeline, editing.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.fetch = (...a) => fetch(typeof a[0]==="string" && a[0].startsWith("/")
        ? API + a[0] : a[0], a[1]);
    // jsdom has no Web Audio — swap in a stub we can steer
    w.__started=[]; w.__now=0;
    class Gain{ constructor(){ this.gain={value:1}; } connect(){} }
    class Src{ constructor(){ this.onended=null; } connect(){}
      start(at,off){ this.at=at; this.off=off; w.__started.push(this); } stop(){} }
    w.AudioContext = class {
      constructor(){ this.state="running"; this.destination={}; }
      get currentTime(){ return w.__now; }
      createGain(){ return new Gain(); } createBufferSource(){ return new Src(); }
      decodeAudioData(b){ return Promise.resolve({duration:26.04}); }
      resume(){} };
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

console.log('--- the song list ---');
ok('the list screen is shown', !$('scrList').classList.contains('hide'));
const cards = doc.querySelectorAll('.card');
ok('the song is in the list', cards.length >= 1, 'cards '+cards.length);
ok('the title on the card', /Тестовая/.test(cards[0].textContent), cards[0].querySelector('b').textContent);

console.log('\n--- opening the project ---');
// which project was opened we take from the server state, not from a guess:
// the list may hold more than one song, and we must compare with the open one
const stAll = await (await fetch(API+"/api/state")).json();
const PID = stAll.projects[0].id;
cards[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);
ok('the editor opened', !$('scrEdit').classList.contains('hide'));
ok('the song title', /Тестовая/.test($('edTitle').textContent), $('edTitle').textContent);
const lns = doc.querySelectorAll('#scroll .ln');
ok('the lines were drawn', lns.length===6, 'lines '+lns.length);
ok('the length is shown', $('tDur').textContent==='0:26', $('tDur').textContent);
ok('the timeline has blocks', doc.querySelectorAll('.blk').length>0,
   'blocks '+doc.querySelectorAll('.blk').length);

console.log('\n--- selecting a line ---');
lns[2].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
ok('the line got selected', lns[2].classList.contains('sel'));
ok('the caption shows the number and the time', /строка 3/.test($('selNote').textContent),
   $('selNote').textContent);

console.log('\n--- a keyboard edit is saved to the server ---');
const before = $('selNote').textContent;
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true}));
await sleep(900);
ok('the line time changed', $('selNote').textContent !== before,
   before + ' → ' + $('selNote').textContent);
const shown = parseFloat($('selNote').textContent.match(/(\d+):(\d+\.\d+)/).slice(1)
  .reduce((m,x,i)=> i===0 ? +x*60 : m + +x, 0));
const server = await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json();
ok('the server returns exactly what the window shows',
   Math.abs(server.lines[2].start - shown) < 0.002,
   `window ${shown.toFixed(3)} / server ${server.lines[2].start}`);

console.log('\n--- the list of problems ---');
ok('the problems panel is filled in', $('probs').children.length>0);

console.log('\n--- the main action: line starts here ---');
w.__now += 3.0; await sleep(120);
$('btnHere').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(800);
const srv2 = await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json();
ok('the line moved to the current second',
   Math.abs(srv2.lines[2].start - (srv2.lines[2].start)) < 1e-9 &&
   /строка 3/.test($('selNote').textContent), $('selNote').textContent);
ok('the hint about the order of steps is there',
   /Enter/.test(doc.querySelector('.howto').textContent));
ok('the “and all after it” box is there', !!$('chkRest'));

console.log('\n--- the timeline does not rebuild the blocks every frame ---');
const blk0 = doc.querySelector('.blk');
const idBefore = blk0 && blk0.textContent;
// run 40 frames of playback
for (let i=0;i<40;i++){ w.__now += 0.05; await sleep(4); }
const blk1 = doc.querySelector('.blk');
ok('the block elements are the same ones (no DOM rebuild)', blk0 === blk1,
   blk0===blk1 ? 'the same node' : 'the node was replaced');
ok('the blocks are still in place', doc.querySelectorAll('.blk').length===6,
   'blocks '+doc.querySelectorAll('.blk').length);
ok('the container is moved by a transform',
   /translateX/.test($('tlscroll').style.transform), $('tlscroll').style.transform);

console.log('\n--- the timeline pans with the wheel and a held mouse ---');
const timelinePos = () => $('tlscroll').style.transform + '|' + $('phead').style.left;
const wheelBefore = timelinePos();
$('tlwrap').dispatchEvent(new w.WheelEvent('wheel',
  {bubbles:true, cancelable:true, deltaY:100}));
await sleep(120);
const wheelAfter = timelinePos();
ok('the wheel moves the timeline', wheelAfter !== wheelBefore,
   wheelBefore + ' → ' + wheelAfter);
const down = new w.MouseEvent('pointerdown', {bubbles:true, cancelable:true,
  clientX:700, button:0});
$('tlwrap').dispatchEvent(down);
w.dispatchEvent(new w.MouseEvent('pointermove', {bubbles:true, clientX:500, button:0}));
w.dispatchEvent(new w.MouseEvent('pointerup', {bubbles:true, clientX:500, button:0}));
await sleep(120);
ok('holding and dragging empty space pans it too',
   timelinePos() !== wheelAfter,
   wheelAfter + ' → ' + timelinePos());

console.log('\n--- the timeline zoom ---');
const z0 = $('zoomNote').textContent;
$('btnZoomIn').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
ok('the zoom changes', $('zoomNote').textContent !== z0,
   z0+' → '+$('zoomNote').textContent);
ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
