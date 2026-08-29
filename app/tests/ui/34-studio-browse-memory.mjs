// Ordinary files belong to the operating system's picker.  The Studio's own
// dialog remains only where it adds something: pasted/found lyrics or a URL.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.confirm = () => true;
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
const sleep = ms => new Promise(r=>setTimeout(r,ms));
w.eval(js);
await sleep(900);

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
let nativeClicks = 0;
$('nativeFile').addEventListener('click', () => nativeClicks++);

console.log('--- ordinary choices go straight to the native picker ---');
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
doc.querySelector('[data-pick="audio"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(100);
ok('the audio button clicked the native file input', nativeClicks === 1, String(nativeClicks));
ok('the home-grown directory window stayed closed', $('browser').classList.contains('hide'));
ok('the native dialog filters to audio', /\.mp3/.test($('nativeFile').accept), $('nativeFile').accept);

doc.querySelector('[data-pick="lyrics"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(100);
ok('the lyrics button uses the same native picker', nativeClicks === 2, String(nativeClicks));
ok('and filters to text files', $('nativeFile').accept === '.txt,.lrc', $('nativeFile').accept);

console.log('\n--- other lyrics keeps only its useful compact window ---');
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1500);
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(700);
ok('the compact dialog opened', !$('browser').classList.contains('hide') &&
   $('browser').querySelector('.browser').classList.contains('compact'));
ok('there is no fake path bar in the compact dialog',
   w.getComputedStyle($('brPath').parentElement).display === 'none');
ok('pasting is immediately available', !$('brPaste').classList.contains('hide'));
$('brNative').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(100);
ok('its Choose button opens the native picker too', nativeClicks === 3, String(nativeClicks));
ok('it asks for text files', $('nativeFile').accept === '.txt,.lrc', $('nativeFile').accept);

console.log('\n--- dialogs close the ordinary desktop way ---');
$('browser').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
ok('a click on the shade closes Other lyrics', $('browser').classList.contains('hide'));
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(400);
$('brPasteText').dispatchEvent(new w.KeyboardEvent('keydown',
  {key:'Escape',bubbles:true,cancelable:true}));
ok('Escape closes it even from its textarea', $('browser').classList.contains('hide'));
$('btnExportMp4').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
ok('the MP4 options opened', !$('expDlg').classList.contains('hide'));
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
ok('Escape closes the MP4 options too', $('expDlg').classList.contains('hide'));

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
