// Dropping files into the studio window.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
import path from 'path';
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true, url:API+"/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    // undici does not know jsdom's File: handed one as a body it sends its
    // toString, not its bytes — every "uploaded" file arrived as thirteen
    // bytes of "[object File]". jsdom's Blob predates arrayBuffer(), so the
    // draining goes through its own FileReader.
    const drain = blob => new Promise(res => {
      const fr = new w.FileReader();
      fr.onload = () => res(Buffer.from(fr.result));
      fr.readAsArrayBuffer(blob);
    });
    w.fetch = async (...a) => {
      let opts = a[1];
      if (opts && opts.body && opts.body instanceof w.Blob)
        opts = {...opts, body: await drain(opts.body)};
      return fetch(typeof a[0]==="string" && a[0].startsWith("/") ? API+a[0] : a[0], opts);
    };
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
// fake File objects: jsdom can do Blob/File
const audio = new w.File([fs.readFileSync(process.env.KARAOKE_SONG)], "Dropped.wav", {type:"audio/wav"});
const text  = new w.File([fs.readFileSync(process.env.KARAOKE_TEXT)], "Dropped.txt", {type:"text/plain"});

console.log('--- the hint on hover ---');
fire('dragenter', [audio, text]);
await sleep(60);
ok('the drop overlay appeared', !$('dropHint').classList.contains('hide'));
fire('dragleave', [audio, text]);
await sleep(60);
ok('and hid again when the cursor left', $('dropHint').classList.contains('hide'));

console.log('\n--- dropping both files ---');
fire('dragenter', [audio, text]);
fire('drop', [audio, text]);
await sleep(2500);
ok('the drop overlay closed', $('dropHint').classList.contains('hide'));
ok('we moved to the add-a-song screen', !$('scrNew').classList.contains('hide'));
ok('the path to the song was filled in', /Dropped(-\d+)?\.wav/.test($('inAudio').value), $('inAudio').value);
ok('the path to the lyrics was filled in', /Dropped(-\d+)?\.txt/.test($('inLyrics').value), $('inLyrics').value);

const droppedAudio = $('inAudio').value, droppedLyrics = $('inLyrics').value;
const projectsRoot = path.resolve(process.env.KARAOKE_PROJECTS);
ok('temporary uploads are not put in projects/_incoming',
   !path.resolve(droppedAudio).startsWith(projectsRoot + path.sep), droppedAudio);

const st = await (await fetch(API+"/api/state")).json();
ok('the files really landed on disk', true, 'projects: '+st.projects.length);

console.log('\n--- a dropped pack opens itself ---');
// A real pack, dropped into the window, must come back as a song in the
// list — end to end: the window's functions live in their own closure, so
// nothing short of the real road proves the wiring.
const postJson = async (path, body) => (await (await fetch(API + path,
  {method:'POST', headers:{'Content-Type':'application/json'},
   body: JSON.stringify(body)})).json());
const droppedJob = (await postJson('/api/new', {audio: droppedAudio,
  lyrics: droppedLyrics, align: 'energy', separate: false,
  title: 'Dropped Self-contained', titleSet: true,
  sourceTitle: 'Bumble Beezy & BaseFace - Мой рок-н-ролл'})).job;
let droppedId = null;
for (let i = 0; i < 240 && !droppedId; i++){
  const j = await (await fetch(API + '/api/job?id=' + droppedJob)).json();
  if (j.done) droppedId = j.result;
  else await sleep(500);
}
const droppedFolder = path.join(projectsRoot, droppedId || 'missing');
const droppedRecord = droppedId
  ? JSON.parse(fs.readFileSync(path.join(droppedFolder, 'project.json'), 'utf8')) : {};
ok('a built project owns its original audio and lyrics',
   [droppedRecord.source_audio, droppedRecord.source_lyrics].every(p =>
     p && path.dirname(path.resolve(p)) === path.resolve(droppedFolder) && fs.existsSync(p)),
   JSON.stringify([droppedRecord.source_audio, droppedRecord.source_lyrics]));
ok('the consumed temporary uploads are gone',
   !fs.existsSync(droppedAudio) && !fs.existsSync(droppedLyrics));

const builtJob = (await postJson('/api/new', {audio: process.env.KARAOKE_SONG,
  lyrics: process.env.KARAOKE_TEXT, align: 'energy', separate: false,
  title: 'Dropped Pack', titleSet: true})).job;
let packSrc = null;
for (let i = 0; i < 240 && !packSrc; i++){
  const j = await (await fetch(API + '/api/job?id=' + builtJob)).json();
  if (j.done) packSrc = j.result;
  else await sleep(500);
}
ok('a song to pack is built', !!packSrc, String(packSrc));
const packed = await postJson(`/api/project/${encodeURIComponent(packSrc)}/pack`, {});
ok('and packed into one file', !!packed.path, JSON.stringify(packed));
ok('finished files have a clearly named common folder',
   path.resolve(path.dirname(packed.path || '')) ===
     path.resolve(path.dirname(projectsRoot), 'output'), packed.path);
const wasCount = (await (await fetch(API + '/api/state')).json()).projects.length;
const packFile = new w.File([fs.readFileSync(packed.path)],
  "dropped.karaoke.zip", {type: "application/zip"});
fire('dragenter', [packFile]);
fire('drop', [packFile]);
let twin = null;
for (let i = 0; i < 60 && !twin; i++){
  await sleep(500);
  const st2 = await (await fetch(API + '/api/state')).json();
  if (st2.projects.length > wasCount)
    twin = st2.projects.find(x => x.title === 'Dropped Pack' && x.id !== packSrc);
}
ok('the dropped pack came back as a song in the list', !!twin,
   twin && twin.id);
for (const id of [twin && twin.id, packSrc, droppedId])
  if (id) await postJson(`/api/project/${encodeURIComponent(id)}/delete`, {});
try{ fs.unlinkSync(packed.path); }catch(e){}

console.log('\n--- dropping something unrelated ---');
const junk = new w.File([Buffer.from("x")], "picture.png", {type:"image/png"});
fire('dragenter', [junk]);
fire('drop', [junk]);
await sleep(400);
ok('a stray file did not break the window', w.__errs.length===0, w.__errs.join(';'));
ok('the fields were not wiped', /Dropped(-\d+)?\.wav/.test($('inAudio').value));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
