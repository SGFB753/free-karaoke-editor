// Обзор файлов должен открываться там, где были в прошлый раз. Иначе каждый
// раз искать один и тот же текст по всему диску — мучение.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();
import path from 'path';

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
const here = path.dirname(process.env.KARAOKE_SONG);   // где лежат тестовые файлы
const close = () => $('brCancel').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));

console.log('--- ходим по папкам, окно это запоминает ---');
$('btnAdd').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
doc.querySelector('[data-pick="audio"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(800);
ok('обзор открылся', !$('browser').classList.contains('hide'));
const first = $('brPath').value;
ok('какая-то папка показана', !!first, first);

// поднимаемся на уровень выше — настоящей кнопкой, как человек
$('brUp').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(800);
const upper = $('brPath').value;
ok('перешли выше', upper !== first, `${first} → ${upper}`);
close();

console.log('\n--- закрыли и открыли снова ---');
doc.querySelector('[data-pick="audio"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(800);
ok('открылось там, где закончили, а не с нуля',
   $('brPath').value === upper, `${$('brPath').value} против ${upper}`);
close();

console.log('\n--- у текста своя память, не общая со звуком ---');
let stored = {};
try {
  stored = {audio: w.localStorage.getItem('karaoke.dir.audio'),
            text: w.localStorage.getItem('karaoke.dir.text')};
} catch(e){}
ok('папка для звука запомнена', stored.audio === upper, String(stored.audio));
doc.querySelector('[data-pick="lyrics"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(700);
ok('обзор текста открылся', !$('browser').classList.contains('hide'));
close();
try { stored.text = w.localStorage.getItem('karaoke.dir.text'); } catch(e){}
ok('папка для текста запомнена отдельно', !!stored.text, String(stored.text));

console.log('\n--- в редакторе тоже не с нуля ---');
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1500);
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(700);
ok('обзор открылся из редактора', !$('browser').classList.contains('hide'));
ok('и не в пустоте, а в запомненной папке',
   $('brPath').value && $('brPath').value !== '/',
   $('brPath').value);
close();

console.log('\n--- запомненная папка исчезла ---');
try { w.localStorage.setItem('karaoke.dir.text', '/такой/папки/давно/нет'); } catch(e){}
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(900);
ok('обзор всё равно открылся, а не упал',
   !$('browser').classList.contains('hide') && !!$('brPath').value,
   $('brPath').value);
ok('и показывает существующую папку', /^\//.test($('brPath').value) &&
   !$('brPath').value.includes('давно'), $('brPath').value);
ok('ошибки про «проект» не было', !w.__errs.some(e => /проект/i.test(e)),
   w.__errs.slice(0,2).join(' | '));
close();

console.log('\n--- забыли память: берём папку исходников песни ---');
try { w.localStorage.removeItem('karaoke.dir.text'); } catch(e){}
$('btnLyrics').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(700);
const p2 = $('brPath').value;
ok('открылось рядом с исходным текстом песни',
   p2 && (p2 === here || here.startsWith(p2) || p2.startsWith(here)),
   `${p2} при исходниках в ${here}`);
close();

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
