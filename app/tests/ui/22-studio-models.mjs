// Выбор модели: окно должно честно говорить, скачана она или нет,
// и предупреждать, что перед разметкой будет молчаливая загрузка.
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
console.log('--- сервер знает, что лежит на диске ---');
ok('сервер отдаёт список моделей', st.caps && st.caps.models &&
   typeof st.caps.models === 'object', JSON.stringify(st.caps && st.caps.models));
const have = st.caps.models;
ok('в списке все пять моделей',
   ['tiny','base','small','medium','large-v3'].every(k => k in have),
   Object.keys(have).join(', '));
ok('скачанные помечены верно', have.tiny === true && have['large-v3'] === false,
   'tiny='+have.tiny+' large-v3='+have['large-v3']);

console.log('\n--- окно добавления песни ---');
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
const opts = [...$('selModel').options];
const byVal = v => opts.find(o=>o.value===v);
ok('у скачанной модели пометка «уже скачана»',
   /уже скачана/.test(byVal('tiny').textContent), byVal('tiny').textContent);
ok('у нескачанной — «скачается при сборке»',
   /скачается при сборке/.test(byVal('large-v3').textContent),
   byVal('large-v3').textContent);
ok('размер модели никуда не делся', /75 МБ/.test(byVal('tiny').textContent),
   byVal('tiny').textContent);

console.log('\n--- подсказка под выбором ---');
$('selAlign').value='auto';
$('selModel').value='large-v3';
$('selModel').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('про нескачанную предупреждает', /скачается|несколько минут/.test($('modelNote').textContent),
   $('modelNote').textContent);
$('selModel').value='tiny';
$('selModel').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('про скачанную говорит, что начнётся сразу', /сразу/.test($('modelNote').textContent),
   $('modelNote').textContent);

$('selAlign').value='energy';
$('selAlign').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(60);
ok('без нейросети подсказка молчит', $('modelNote').textContent.trim()==='',
   '«'+$('modelNote').textContent+'»');

console.log('\n--- тяжёлые для машины модели помечены ---');
const need = st.caps.needGb || {}, free = st.caps.freeGb;
ok('сервер сообщает свободную память и запросы моделей',
   typeof free === 'number' && need.medium > 0, `свободно ${free}, medium нужно ${need.medium}`);
const tooBig = Object.keys(need).find(k => need[k] > free && k !== 'demucs');
if (tooBig){
  ok(`«${tooBig}» помечена как тяжёлая`,
     /тяжёлая для этой машины/.test(byVal(tooBig).textContent), byVal(tooBig).textContent);
  $('selAlign').value='auto';
  $('selModel').value = tooBig;
  $('selModel').dispatchEvent(new w.Event('change',{bubbles:true}));
  await sleep(60);
  ok('подсказка называет цифры, а не пугает вообще',
     /ГБ памяти/.test($('modelNote').textContent) &&
     /поменьше/.test($('modelNote').textContent), $('modelNote').textContent.slice(0,90));
} else {
  ok('на этой машине памяти хватает на все модели', true, `свободно ${free} ГБ`);
}
const fits = Object.keys(need).find(k => need[k] <= free && k !== 'demucs');
if (fits) ok(`«${fits}» лишней тревоги не вызывает`,
   !/тяжёлая/.test(byVal(fits).textContent), byVal(fits).textContent);

console.log('\n--- пометка не копится при повторном заходе ---');
$('selAlign').value='auto';
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
const t = byVal('tiny').textContent;
ok('пометка ровно одна', (t.match(/уже скачана/g)||[]).length === 1, t);
ok('и пометка про тяжесть тоже одна',
   (t.match(/тяжёлая/g)||[]).length <= 1, t);

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join('; '));

console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
