// Отчёт перед сборкой: показывается сам, как только выбраны оба файла, и
// говорит то же, что потом окажется в логе.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.fetch = (path, opts) => fetch(typeof path === "string" && path.startsWith("/")
        ? API + path : path, opts);
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
const text = () => $('report').textContent.replace(/\s+/g,' ').trim();

$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);

console.log('--- пока файлов нет, отчёта нет ---');
ok('отчёт спрятан', $('report').classList.contains('hide'));

console.log('\n--- выбрали оба файла ---');
$('inAudio').value = process.env.KARAOKE_SONG;
$('inAudio').dispatchEvent(new w.Event('input',{bubbles:true}));
$('inLyrics').value = process.env.KARAOKE_TEXT;
$('inLyrics').dispatchEvent(new w.Event('input',{bubbles:true}));
await sleep(300);
ok('отчёт показался и сначала честно ждёт', !$('report').classList.contains('hide'));
await sleep(6000);

const t = text();
ok('длина песни названа', /0:2\d/.test(t), t.slice(0, 70));
// Про темп в окне больше не пишем: для караоке важнее, где текст молчит.
ok('места без пения названы', /Без пения/.test(t), t.slice(0, 110));
ok('строки и слова посчитаны', /6\b/.test(t) && /Строк/i.test(t), t.slice(0, 120));
ok('язык назван', /русский/i.test(t), t.slice(0, 140));
ok('сказано, что программа будет делать', /Сделаю/.test(t), t.slice(-120));
ok('оценка времени есть и помечена грубой', /займёт/.test(t) && /грубо/.test(t),
   t.slice(-90));

console.log('\n--- отчёт пересчитывается при смене настроек ---');
const before = text();
$('selAlign').value = 'energy';
$('selAlign').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(5000);
const after = text();
ok('план поменялся вслед за выбором', before !== after &&
   /по энергии/.test(after), after.slice(-110));

console.log('\n--- язык из выбора попадает в отчёт ---');
$('selAlign').value = 'auto';
$('selLang').value = 'en';
$('selLang').dispatchEvent(new w.Event('change',{bubbles:true}));
await sleep(5000);
ok('выбранный вручную язык показан', /english/i.test(text()), text().slice(0, 150));

console.log('\n--- чужой файл не роняет окно ---');
$('inLyrics').value = '/такого/файла/нет.txt';
$('inLyrics').dispatchEvent(new w.Event('input',{bubbles:true}));
await sleep(3000);
ok('сказано по-человечески, а не молчанием',
   /не найден|Не вышло/i.test(text()), text().slice(0, 90));

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
