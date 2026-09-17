// Picking a model: the window must say honestly whether it is downloaded,
// and warn that a silent download comes before the timing pass.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    // Free memory is measured live and changes between two readings — the
    // test and the page each asked and sometimes got different answers, and
    // the “heavy” mark flickered with the machine's mood. Both see 1.5 GB.
    w.fetch = async (...a) => {
      const r = await fetch(typeof a[0]==="string" && a[0].startsWith("/")
          ? API + a[0] : a[0], a[1]);
      if (typeof a[0] === "string" && a[0].startsWith("/api/state")){
        const j = await r.json();
        if (j.caps) j.caps.freeGb = 1.5;
        return {ok: r.ok, json: async () => j};
      }
      return r;
    };
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

const st = await (await fetch(API+"/api/state")).json();
st.caps.freeGb = 1.5;                 // the same pinned memory the page sees
console.log('--- the server knows what is on disk ---');
ok('the server returns the list of models', st.caps && st.caps.models &&
   typeof st.caps.models === 'object', JSON.stringify(st.caps && st.caps.models));
const have = st.caps.models;
const opts = [...$('selModel').options];
const byVal = v => opts.find(o=>o.value===v);
const values = opts.map(o => o.value);

const apiModels = Object.keys(have);

ok(
  'every UI model is known to the server',
  values.every(name => name in have),
  values.filter(name => !(name in have)).join(', ') || 'all present'
);

ok(
  'every server model is offered in the UI',
  apiModels.every(name => values.includes(name)),
  apiModels.filter(name => !values.includes(name)).join(', ') || 'all present'
);
// The stand runs with a model cache of its own (see fake_model_cache in
// run_all.py): “tiny” lies there, the rest do not. So both answers are checked
// on any machine, including a CI runner with an empty cache.
ok('the downloaded ones are marked correctly', have.tiny === true && have['large-v3'] === false,
   'tiny='+have.tiny+' large-v3='+have['large-v3']);

console.log('\n--- the add-a-song window ---');
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
ok('the cover picker stays out of the link workflow',
   !!$('inCover') && $('newCoverField').classList.contains('hide'));
const described = await (await fetch(API + '/api/audio/info', {method:'POST',
  headers:{'Content-Type':'application/json'}, body:JSON.stringify({
    path:process.env.KARAOKE_SONG, name:'Local Artist - Local Track.wav'})})).json();
ok('a local file name supplies artist, track and duration when tags are absent',
   described.artist === 'Local Artist' && described.track === 'Local Track'
   && described.duration > 0, JSON.stringify(described));
const beforeLocalPick = w.fetch;
let localLyricsQuery = null;
w.fetch = async (path, opts) => {
  if (typeof path === 'string' && path.startsWith('/api/upload'))
    return {json: async () => ({path:'C:\\Music\\manual.mp3'})};
  if (typeof path === 'string' && path.startsWith('/api/audio/info'))
    return {json: async () => ({title:'Tagged Track', track:'Tagged Track',
      artist:'Tagged Artist', duration:183})};
  if (typeof path === 'string' && path.startsWith('/api/lyrics/find')){
    localLyricsQuery = JSON.parse(opts.body);
    return {json: async () => ({source:'LRCLIB / Genius', found:[{
      source:'LRCLIB', title:'Tagged Track', artist:'Tagged Artist', duration:183,
      lines:2, text:'first line\nsecond line', timed:false, textTimed:''}]})};
  }
  return beforeLocalPick(path, opts);
};
doc.querySelector('[data-pick="audio"]').dispatchEvent(
  new w.MouseEvent('click',{bubbles:true}));
Object.defineProperty($('nativeFile'), 'files', {configurable:true,
  value:[new w.File(['audio'], 'manual.mp3', {type:'audio/mpeg'})]});
$('nativeFile').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(100);
w.fetch = beforeLocalPick;
ok('selecting a local audio file reveals the local cover picker',
   !$('newCoverField').classList.contains('hide'));
ok('its embedded title and artist start the lyrics search automatically',
   $('inTitle').value === 'Tagged Track' && $('inArtist').value === 'Tagged Artist'
   && localLyricsQuery && localLyricsQuery.track === 'Tagged Track'
   && localLyricsQuery.artist === 'Tagged Artist'
   && !$('lyricsFound').classList.contains('hide'),
   JSON.stringify({title:$('inTitle').value, artist:$('inArtist').value,
                   query:localLyricsQuery}));
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
for (const [name, ready] of Object.entries(have)) {
  const text = byVal(name)?.textContent || '';

  if (ready) {
    ok(
      `"${name}" is marked downloaded`,
      /уже скачана/.test(text),
      text || 'MISSING'
    );
  } else {
    ok(
      `"${name}" is marked not downloaded`,
      /скачается/.test(text),
      text || 'MISSING'
    );
  }
}

console.log('\n--- the hint under the picker ---');
$('selAlign').value='auto';
$('selModel').value='large-v3';
$('selModel').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('it warns about a missing one', /скачается|несколько минут/.test($('modelNote').textContent),
   $('modelNote').textContent);
$('selModel').value='tiny';
$('selModel').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('about a downloaded one it says it starts at once', /сразу/.test($('modelNote').textContent),
   $('modelNote').textContent);

$('selAlign').value='energy';
$('selAlign').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('without the neural net the hint stays quiet', $('modelNote').textContent.trim()==='',
   '«'+$('modelNote').textContent+'»');

console.log('\n--- models heavy for this machine are marked ---');
const need = st.caps.needGb || {}, free = st.caps.freeGb;
ok('the server reports free memory and what the models need',
   typeof free === 'number' && need.medium > 0, `free ${free}, medium needs ${need.medium}`);
const tooBig = Object.keys(need).find(k => need[k] > free && k !== 'demucs');
if (tooBig){
  ok(`“${tooBig}” is marked as heavy`,
     /тяжёлая для этой машины/.test(byVal(tooBig).textContent), byVal(tooBig).textContent);
  $('selAlign').value='auto';
  $('selModel').value = tooBig;
  $('selModel').dispatchEvent(new w.Event('change',{bubbles:true}));
  await sleep(60);
  ok('the hint gives numbers instead of vague fear',
     /ГБ памяти/.test($('modelNote').textContent) &&
     /поменьше/.test($('modelNote').textContent), $('modelNote').textContent.slice(0,90));
} else {
  ok('this machine has memory for every model', true, `free ${free} GB`);
}
const fits = Object.keys(need).find(k => need[k] <= free && k !== 'demucs');
if (fits) ok(`“${fits}” raises no needless alarm`,
   !/тяжёлая/.test(byVal(fits).textContent), byVal(fits).textContent);

console.log('\n--- the mark does not pile up on a second visit ---');
$('selAlign').value='auto';
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
const t = byVal('tiny').textContent;
ok('there is exactly one mark', (t.match(/уже скачана/g)||[]).length === 1, t);
ok('and exactly one “heavy” mark too',
   (t.match(/тяжёлая/g)||[]).length <= 1, t);

console.log('\n--- model labels ---');

ok(
  'model values are unique',
  new Set(values).size === values.length,
  values.join(', ')
);

for (const name of values) {
  const opt = byVal(name);

  ok(
    `"${name}" has a label`,
    !!opt && opt.textContent.trim().length > 0,
    opt?.textContent || 'MISSING'
  );

  ok(
    `"${name}" label identifies the model`,
    opt?.textContent.includes(name),
    opt?.textContent || 'MISSING'
  );
}

// “Separate finely” has nothing to do while the instrumental is off.
ok('there is a switch for the finer separation', !!$('chkFine'));
$('chkSep').checked = false;
$('chkSep').dispatchEvent(new w.Event('change', {bubbles:true}));
await sleep(60);
ok('with no instrumental it cannot be switched on', $('chkFine').disabled);
ok('and it does not stay on from before', !$('chkFine').checked);
$('chkSep').checked = true;
$('chkSep').dispatchEvent(new w.Event('change', {bubbles:true}));
await sleep(60);
// Without Demucs there is nothing to separate finely with, and the switch has
// to stay dead — that is the whole point of it following the instrumental.
const canSeparate = ((await (await fetch(API + '/api/state')).json()).caps || {}).demucs;
ok(canSeparate ? 'with an instrumental it can be switched on'
               : 'with no Demucs installed it stays dead either way',
   $('chkFine').disabled === !canSeparate, `demucs=${canSeparate}`);

// What the window sends is what the program acts on.
let sent = null;
const realFetch = w.fetch;
// The request is read and stopped here: letting it through would start a real
// build on the stand, with a model to load and minutes to wait for nothing.
w.fetch = (path, opts) => {
  if (typeof path === "string" && path.indexOf("/api/new") === 0 && opts && opts.body){
    sent = JSON.parse(opts.body);
    return Promise.resolve({json: () => Promise.resolve({job: "not-a-real-job"})});
  }
  return realFetch(path, opts);
};
$('chkFine').checked = true;
$('inAudio').value = process.env.KARAOKE_SONG;
$('inLyrics').value = process.env.KARAOKE_TEXT;
$('inCover').value = 'C:\\Music\\local-cover.png';
const preview = $('newAudioPlayer');
let previewPaused = 0;
Object.defineProperty(preview, 'paused', {configurable:true, get:() => false});
preview.pause = () => { previewPaused++; };
$('btnBuild').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(500);
ok('starting the build stops the hidden audio preview', previewPaused === 1,
   `pause calls=${previewPaused}`);
ok('a local cover is sent into the project and enabled as its background',
   sent && sent.cover === 'C:\\Music\\local-cover.png'
   && sent.backgroundMode === 'cover' && sent.coverBg === true,
   JSON.stringify(sent && {cover:sent.cover, backgroundMode:sent.backgroundMode,
                           coverBg:sent.coverBg}));
ok('the choice is sent with the build', sent && sent.separator === 'htdemucs_ft',
   JSON.stringify(sent && {separator: sent.separator, separate: sent.separate}));
w.fetch = realFetch;

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join('; '));

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
