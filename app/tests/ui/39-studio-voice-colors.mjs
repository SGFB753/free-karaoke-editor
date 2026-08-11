// Второй голос строки и цвета подсветки: переключаются и доживают до диска.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.confirm = () => true;
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
const proj = async () => (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json());
const click = id => $(id).dispatchEvent(new w.MouseEvent('click',{bubbles:true}));

doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);

console.log('--- второй голос ---');
doc.querySelectorAll('#scroll .ln')[1].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(120);
ok('кнопка показывает голос выбранной строки',
   /Голос 1/.test($("btnVoice").textContent), $("btnVoice").textContent);
click("btnVoice"); await sleep(120);
ok('строка стала вторым голосом', /Голос 2/.test($("btnVoice").textContent),
   $("btnVoice").textContent);
ok('на сцене появился класс второго голоса',
   doc.querySelectorAll('#scroll .ln')[1].classList.contains('v2'));
ok('и на дорожке тоже',
   doc.querySelectorAll('#blocks .blk')[1].classList.contains('v2'));

console.log('\n--- цвета ---');
$("col2").value = "#ff5577";
$("col2").dispatchEvent(new w.Event('input',{bubbles:true}));
await sleep(120);
ok('второй цвет применён к странице',
   doc.documentElement.style.getPropertyValue('--accent-2').trim() === '#ff5577',
   doc.documentElement.style.getPropertyValue('--accent-2'));

console.log('\n--- оформление ---');
$("colBg").value = "#101820";
$("colBg").dispatchEvent(new w.Event('input',{bubbles:true}));
await sleep(150);
ok('фон окна поменялся',
   doc.documentElement.style.getPropertyValue('--bg').trim() === '#101820',
   doc.documentElement.style.getPropertyValue('--bg'));
// нарочно нечитаемая пара: тёмные буквы на тёмном фоне
$("colTx").value = "#151d26";
$("colTx").dispatchEvent(new w.Event('input',{bubbles:true}));
await sleep(150);
const tx = doc.documentElement.style.getPropertyValue('--text').trim();
ok('буквы, слившиеся с фоном, высветлены', tx !== '#151d26', tx);

console.log('\n--- всё это доживает до диска ---');
await sleep(900);                        // ждём автосохранение
const d = await proj();
ok('голос строки записан', d.lines[1].voice === 2, 'voice=' + d.lines[1].voice);
ok('цвета записаны', Array.isArray(d.colors) && d.colors[1] === '#ff5577',
   JSON.stringify(d.colors));
ok('оформление записано', Array.isArray(d.theme) && d.theme[0] === '#101820',
   JSON.stringify(d.theme));

console.log('\n--- кусок, который поёт оригинал ---');
ok('кнопка есть и выключена', !$("btnKeep").classList.contains('on'));
click("btnKeep"); await sleep(150);
ok('строка помечена', doc.querySelectorAll('#scroll .ln')[1].classList.contains('keep'));
ok('на дорожке это тоже видно',
   doc.querySelectorAll('#blocks .blk')[1].classList.contains('keep'));
ok('в тексте появилась пометка',
   /поёт оригинал/.test(doc.querySelectorAll('#scroll .ln')[1].textContent),
   doc.querySelectorAll('#scroll .ln')[1].textContent.slice(-30));
await sleep(900);
ok('пометка записана на диск', (await proj()).lines[1].keep === true);
click("btnKeep"); await sleep(900);
ok('и снимается', !(await proj()).lines[1].keep);
ok('пометка из текста ушла',
   !/поёт оригинал/.test(doc.querySelectorAll('#scroll .ln')[1].textContent));

console.log('\n--- возврат к основному голосу ---');
click("btnVoice"); await sleep(900);
const d2 = await proj();
ok('голос вернулся к первому', (d2.lines[1].voice || 1) === 1, 'voice=' + d2.lines[1].voice);
// возвращаем цвет, чтобы не мешать другим наборам
$("col2").value = "#ff8ad1";
$("col2").dispatchEvent(new w.Event('input',{bubbles:true}));
await sleep(900);

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
