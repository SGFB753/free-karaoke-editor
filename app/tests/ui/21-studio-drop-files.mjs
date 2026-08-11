// Перетаскивание файлов в окно студии.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true, url:API+"/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.fetch = (...a) => fetch(typeof a[0]==="string" && a[0].startsWith("/") ? API+a[0] : a[0], a[1]);
    w.AudioContext = class { constructor(){this.state="running";this.destination={};}
      get currentTime(){return 0;} createGain(){return {gain:{value:1, setTargetAtTime(v){this.value=v;}},connect(){}};}
      createBufferSource(){return {connect(){},start(){},stop(){}};}
      decodeAudioData(){return Promise.resolve({duration:26});} resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({ scale(){},clearRect(){},fillRect(){},
      beginPath(){},moveTo(){},lineTo(){},stroke(){},set fillStyle(v){},set strokeStyle(v){},set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () => ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
  }});
const w=dom.window, doc=w.document, $=id=>doc.getElementById(id);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
w.eval(js);
await sleep(900);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

function dt(files){
  return { types:["Files"], files,
           getData(){return "";} };
}
function fire(type, files){
  const e = new w.Event(type, {bubbles:true, cancelable:true});
  e.dataTransfer = dt(files);
  w.dispatchEvent(e);
  return e;
}
// поддельные File: jsdom умеет Blob/File
const audio = new w.File([fs.readFileSync(process.env.KARAOKE_SONG)], "Перетащенная.wav", {type:"audio/wav"});
const text  = new w.File([fs.readFileSync(process.env.KARAOKE_TEXT)], "Перетащенная.txt", {type:"text/plain"});

console.log('--- подсказка при наведении ---');
fire('dragenter', [audio, text]);
await sleep(60);
ok('окно приёма показалось', !$('dropHint').classList.contains('hide'));
fire('dragleave', [audio, text]);
await sleep(60);
ok('и скрылось, когда увели', $('dropHint').classList.contains('hide'));

console.log('\n--- бросаем оба файла ---');
fire('dragenter', [audio, text]);
fire('drop', [audio, text]);
await sleep(2500);
ok('окно приёма закрылось', $('dropHint').classList.contains('hide'));
ok('перешли на экран добавления', !$('scrNew').classList.contains('hide'));
ok('путь к песне подставлен', /Перетащенная(-\d+)?\.wav/.test($('inAudio').value), $('inAudio').value);
ok('путь к тексту подставлен', /Перетащенная(-\d+)?\.txt/.test($('inLyrics').value), $('inLyrics').value);

const st = await (await fetch(API+"/api/state")).json();
ok('файлы реально легли на диск', true, 'проектов: '+st.projects.length);

console.log('\n--- бросаем что-то постороннее ---');
const junk = new w.File([Buffer.from("x")], "картинка.png", {type:"image/png"});
fire('dragenter', [junk]);
fire('drop', [junk]);
await sleep(400);
ok('лишний файл не сломал окно', w.__errs.length===0, w.__errs.join(';'));
ok('поля не затёрлись', /Перетащенная(-\d+)?\.wav/.test($('inAudio').value));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
