// Слова внутри строки двигаются по одному: ритм в песне почти никогда не ровный.
// И отдельно — сохранение: состояние видно, выгрузка ждёт записи на диск.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m)); w.confirm=()=>true;
    w.__beacons=[]; w.navigator.sendBeacon = (u,b) => { w.__beacons.push(u); return true; };
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
const srv = async () => (await (await fetch(API+"/api/project/"+encodeURIComponent(PID))).json()).lines;
const pe = (t,x) => { const e = new w.MouseEvent(t,{bubbles:true,cancelable:true,clientX:x});
                      Object.defineProperty(e,'pointerId',{value:1}); return e; };

doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1200);

console.log('--- ряд слов появляется у выбранной строки ---');
doc.querySelectorAll('#scroll .ln')[2].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
let chips = [...doc.querySelectorAll('.wrd')];
const line = (await srv())[2];
ok('слова показаны отдельными кусочками', chips.length === line.words.length,
   `${chips.length} против ${line.words.length} слов`);
ok('на кусочке написано само слово', chips[0].textContent === line.words[0].w,
   `«${chips[0].textContent}»`);
// мелкие полоски по 9px разобрать было нельзя — это и была «бесполезная штука»
const css = w.getComputedStyle(chips[0]);
// Размеры заданы в rem от html{font-size:clamp(16px…)} — jsdom их не считает.
// Берём нижнюю границу clamp, 16px: если проходит на ней, пройдёт и на большом экране.
const cssPx = v => /rem$/.test(String(v)) ? parseFloat(v) * 16 : parseFloat(v || 0);
ok('кусочки читаемого размера, а не декоративные полоски',
   cssPx(css.fontSize) >= 11, css.fontSize);

console.log('\n--- ряд переключается вместе со строкой ---');
doc.querySelectorAll('#scroll .ln')[3].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
const line3 = (await srv())[3];
ok('слова уже от другой строки',
   [...doc.querySelectorAll('.wrd')].length === line3.words.length,
   `${doc.querySelectorAll('.wrd').length} против ${line3.words.length}`);

console.log('\n--- двигаем одно слово ---');
doc.querySelectorAll('#scroll .ln')[2].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(150);
const was = (await srv())[2];
chips = [...doc.querySelectorAll('.wrd')];
// Берём слово, у которого справа есть куда двигаться: строку до нас уже
// правили другие проверки, и место могло кончиться.
let J = 1;
for (let k = 1; k < was.words.length - 1; k++){
  const room = was.words[k+1].t - was.words[k].t;
  if (room > (was.words[J+1] ? was.words[J+1].t - was.words[J].t : 0)) J = k;
}
ok('нашлось слово, которое есть куда двигать',
   was.words[J+1] && was.words[J+1].t - was.words[J].t > 0.2,
   `запас ${(was.words[J+1] ? was.words[J+1].t - was.words[J].t : 0).toFixed(2)} с`);
chips[J].dispatchEvent(pe('pointerdown', 100));
w.dispatchEvent(pe('pointermove', 130));
ok('подпись показывает слово, а не строку', /слово «/.test($('selNote').textContent),
   $('selNote').textContent);
w.dispatchEvent(pe('pointerup', 130));
await sleep(900);

const now = (await srv())[2];
ok('слово уехало вправо', now.words[J].t > was.words[J].t + 0.02,
   `${was.words[J].t.toFixed(3)} → ${now.words[J].t.toFixed(3)}`);
// Слова больше не склеены встык: у каждого своя длина, между ними
// допустима пауза. Двигаем одно — соседи не срываются с места.
// Наехали на соседа — он уступает; не наехали — стоит где стоял.
const myEnd = now.words[J].t + now.words[J].d;
ok('сосед справа уступил ровно, не больше',
   Math.abs(now.words[J+1].t - Math.max(was.words[J+1].t, myEnd)) < 0.005,
   `${was.words[J+1].t.toFixed(3)} → ${now.words[J+1].t.toFixed(3)}`);
ok('сосед слева не сорвался с места',
   J < 1 || Math.abs(now.words[J-1].t - was.words[J-1].t) < 1e-6);
ok('никто не схлопнулся', now.words.every(x => x.d >= 0.05),
   now.words.map(x=>x.d.toFixed(2)).join(' '));
ok('длина самого слова сохранилась',
   Math.abs(now.words[J].d - was.words[J].d) < 0.005,
   `${was.words[J].d.toFixed(3)} → ${now.words[J].d.toFixed(3)} с`);
ok('на соседей не наехало',
   now.words[J].t >= now.words[J-1].t + now.words[J-1].d - 1e-6 &&
   now.words[J].t + now.words[J].d <= now.words[J+1].t + 1e-6,
   `${now.words[J].t.toFixed(3)}–${(now.words[J].t+now.words[J].d).toFixed(3)}`);
ok('слова по-прежнему идут по порядку',
   now.words.every((x,k)=> k===0 || x.t >= now.words[k-1].t - 1e-9));
ok('и ни одно не схлопнулось в ноль', now.words.every(x => x.d >= 0.05),
   now.words.map(x=>x.d.toFixed(2)).join(' '));
ok('границы строки не нарушены',
   now.words[0].t >= now.start - 1e-6 &&
   now.words[now.words.length-1].t < now.end + 1e-6);
ok('текст строки не пострадал', now.text === was.text, now.text);

console.log('\n--- слово не заезжает на соседей ---');
chips = [...doc.querySelectorAll('.wrd')];
chips[J].dispatchEvent(pe('pointerdown', 100));
w.dispatchEvent(pe('pointermove', 900));       // тянем далеко за следующее слово
w.dispatchEvent(pe('pointerup', 900));
await sleep(900);
const far = (await srv())[2];
ok('уперлось в следующее слово, а не перескочило',
   far.words[J].t < far.words[J+1].t &&
   far.words.every((x,k)=> k===0 || x.t >= far.words[k-1].t - 1e-9),
   far.words.map(x=>x.t.toFixed(2)).join(' '));

console.log('\n--- отмена возвращает слово ---');
$('btnUndo').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(900);
const undone = (await srv())[2];
ok('слово вернулось на прежнее место',
   Math.abs(undone.words[J].t - now.words[J].t) < 1e-6,
   `${far.words[J].t.toFixed(3)} → ${undone.words[J].t.toFixed(3)}`);

console.log('\n--- сохранение видно и не отстаёт ---');
ok('после записи так и написано — сохранено', $('savedNote').textContent === 'сохранено',
   $('savedNote').textContent);
doc.querySelectorAll('#scroll .ln')[1].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true,cancelable:true}));
ok('сразу после правки честно сказано, что ещё не сохранено',
   $('savedNote').textContent === 'не сохранено', $('savedNote').textContent);
await sleep(900);
ok('и через мгновение — сохранено', $('savedNote').textContent === 'сохранено',
   $('savedNote').textContent);

console.log('\n--- выгрузка ждёт записи на диск ---');
const marker = (await srv())[1].start;
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true,cancelable:true}));
$('btnExportHtml').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));  // сразу, не ожидая автосохранения
await sleep(1400);
const shipped = (await srv())[1].start;
ok('сервер получил свежую правку до сборки файла',
   Math.abs(shipped - marker - 0.05) < 1e-6,
   `${marker.toFixed(3)} → ${shipped.toFixed(3)}`);

// Прибираем за собой: проект в стенде общий, и накопленные правки съедают
// запас времени внутри строк — следующий прогон падал бы на пустом месте.
console.log('\n--- возвращаем проект как было ---');
let __g = 0;
while (!$('btnUndo').disabled && __g++ < 100){
  $('btnUndo').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await sleep(90);
}
await sleep(900);
ok('история отмены исчерпана', $('btnUndo').disabled, 'шагов ' + __g);

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));

console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
