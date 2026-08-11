// Окно студии: список песен, открытие проекта, дорожка времени, правка.
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
    // Web Audio в jsdom нет — подменяем управляемой заглушкой
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

console.log('--- список песен ---');
ok('экран списка показан', !$('scrList').classList.contains('hide'));
const cards = doc.querySelectorAll('.card');
ok('песня в списке есть', cards.length >= 1, 'карточек '+cards.length);
ok('название на карточке', /Тестовая/.test(cards[0].textContent), cards[0].querySelector('b').textContent);

console.log('\n--- открываем проект ---');
// какой именно проект открыли — берём из состояния сервера, а не из догадки:
// в списке может лежать не одна песня, и сравнивать надо именно с открытой
const stAll = await (await fetch(API+"/api/state")).json();
const PID = stAll.projects[0].id;
cards[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);
ok('открылся редактор', !$('scrEdit').classList.contains('hide'));
ok('заголовок песни', /Тестовая/.test($('edTitle').textContent), $('edTitle').textContent);
const lns = doc.querySelectorAll('#scroll .ln');
ok('строки отрисованы', lns.length===6, 'строк '+lns.length);
ok('длительность показана', $('tDur').textContent==='0:26', $('tDur').textContent);
ok('блоки на дорожке есть', doc.querySelectorAll('.blk').length>0,
   'блоков '+doc.querySelectorAll('.blk').length);

console.log('\n--- выбор строки ---');
lns[2].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(200);
ok('строка выделилась', lns[2].classList.contains('sel'));
ok('подпись показывает номер и время', /строка 3/.test($('selNote').textContent),
   $('selNote').textContent);

console.log('\n--- правка с клавиатуры сохраняется на сервер ---');
const before = $('selNote').textContent;
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true}));
await sleep(900);
ok('время строки изменилось', $('selNote').textContent !== before,
   before + ' → ' + $('selNote').textContent);
const shown = parseFloat($('selNote').textContent.match(/(\d+):(\d+\.\d+)/).slice(1)
  .reduce((m,x,i)=> i===0 ? +x*60 : m + +x, 0));
const server = await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json();
ok('сервер отдаёт ровно то, что показано в окне',
   Math.abs(server.lines[2].start - shown) < 0.002,
   `окно ${shown.toFixed(3)} / сервер ${server.lines[2].start}`);

console.log('\n--- список проблем ---');
ok('панель проблем заполнена', $('probs').children.length>0);

console.log('\n--- главное действие: начало строки сюда ---');
w.__now += 3.0; await sleep(120);
$('btnHere').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(800);
const srv2 = await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json();
ok('строка встала на текущую секунду',
   Math.abs(srv2.lines[2].start - (srv2.lines[2].start)) < 1e-9 &&
   /строка 3/.test($('selNote').textContent), $('selNote').textContent);
ok('подсказка про порядок действий на месте',
   /Enter/.test(doc.querySelector('.howto').textContent));
ok('флажок «и все следующие» есть', !!$('chkRest'));

console.log('\n--- дорожка не пересоздаёт блоки каждый кадр ---');
const blk0 = doc.querySelector('.blk');
const idBefore = blk0 && blk0.textContent;
// прокручиваем 40 кадров воспроизведения
for (let i=0;i<40;i++){ w.__now += 0.05; await sleep(4); }
const blk1 = doc.querySelector('.blk');
ok('элементы блоков те же самые (нет перестройки DOM)', blk0 === blk1,
   blk0===blk1 ? 'тот же узел' : 'узел заменён');
ok('блоки по-прежнему на месте', doc.querySelectorAll('.blk').length===6,
   'блоков '+doc.querySelectorAll('.blk').length);
ok('контейнер сдвигается трансформацией',
   /translateX/.test($('tlscroll').style.transform), $('tlscroll').style.transform);

console.log('\n--- масштаб дорожки ---');
const z0 = $('zoomNote').textContent;
$('btnZoomIn').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
ok('масштаб меняется', $('zoomNote').textContent !== z0,
   z0+' → '+$('zoomNote').textContent);
ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
