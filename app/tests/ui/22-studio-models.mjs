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
    w.fetch = (...a) => fetch(typeof a[0]==="string" && a[0].startsWith("/")
        ? API + a[0] : a[0], a[1]);
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
console.log('--- the server knows what is on disk ---');
ok('the server returns the list of models', st.caps && st.caps.models &&
   typeof st.caps.models === 'object', JSON.stringify(st.caps && st.caps.models));
const have = st.caps.models;
ok('all five models are in the list',
   ['tiny','base','small','medium','large-v3'].every(k => k in have),
   Object.keys(have).join(', '));
// The stand runs with a model cache of its own (see fake_model_cache in
// run_all.py): “tiny” lies there, the rest do not. So both answers are checked
// on any machine, including a CI runner with an empty cache.
ok('the downloaded ones are marked correctly', have.tiny === true && have['large-v3'] === false,
   'tiny='+have.tiny+' large-v3='+have['large-v3']);

console.log('\n--- the add-a-song window ---');
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
const opts = [...$('selModel').options];
const byVal = v => opts.find(o=>o.value===v);
ok('a downloaded model is marked “already downloaded”',
   /уже скачана/.test(byVal('tiny').textContent), byVal('tiny').textContent);
ok('a missing one — “downloads when building”',
   /скачается при сборке/.test(byVal('large-v3').textContent),
   byVal('large-v3').textContent);
ok('the model size is still there', /75 МБ/.test(byVal('tiny').textContent),
   byVal('tiny').textContent);

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

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join('; '));

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
