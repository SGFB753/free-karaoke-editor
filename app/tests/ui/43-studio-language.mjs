// Окно Студии по-английски и переключатель языка.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const mk = (lang) => new JSDOM(html.replace('window.KARAOKE_UI_LANG = "ru"',
                                            `window.KARAOKE_UI_LANG = "${lang}"`), {
  runScripts:"dangerously", pretendToBeVisual:true, url: API + "/",
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

const sleep = ms => new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const CYR = /[А-Яа-яЁё]/;

console.log('--- окно, собранное по-английски ---');
const dom = mk('en'); const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
w.eval(js);
await sleep(900);
ok('заголовок английский', $("scrList").querySelector("h1").textContent === "Karaoke Studio",
   $("scrList").querySelector("h1").textContent);
ok('кнопка добавления переведена', /Add a song/.test($("btnAdd").textContent),
   $("btnAdd").textContent);
ok('кнопка языка предлагает русский', $("btnLang").textContent.trim() === "RU",
   $("btnLang").textContent);

// экран добавления — там больше всего надписей
$("btnAdd").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(400);
// Названия языков написаны на них самих («русский», «日本語») — их не переводят,
// поэтому список языков из проверки исключаем.
const newScreen = [...$("scrNew").querySelectorAll("label, button, option, .hint, .warn")]
  .filter(e => !e.closest("#selLang")).map(e => e.textContent).join(" ");
ok('на экране новой песни кириллицы нет', !CYR.test(newScreen),
   (newScreen.match(/[А-Яа-яЁё][^\s]*/g)||[]).slice(0,4).join(" "));
ok('«определить по тексту» переведено',
   !CYR.test([...$("selLang").options].find(o=>o.value==="auto").textContent),
   [...$("selLang").options].find(o=>o.value==="auto").textContent);
ok('подсказка к модели по-английски', !CYR.test($("modelNote").textContent),
   $("modelNote").textContent.slice(0,60));
ok('размер модели написан как MB', /MB/.test($("selModel").options[0].textContent),
   $("selModel").options[0].textContent);

// редактор
$("btnBackNew").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(300);
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1400);
const editUi = [...doc.querySelectorAll('.tlhead, footer, .howto, .side h3, .madefile')]
  .map(e => e.textContent).join(" ");
ok('в редакторе надписи английские', !CYR.test(editUi),
   (editUi.match(/[А-Яа-яЁё][^\s]*/g)||[]).slice(0,4).join(" "));
ok('подсказка про клавиши переведена', /Space — play/.test($("hint").textContent),
   $("hint").textContent);
ok('сводка по-английски', /Length|Lines/.test($("sum").textContent),
   $("sum").textContent.slice(0,60));
// текст самой песни, конечно, русский — это данные, а не надписи
ok('текст песни не тронут', CYR.test($("scroll").textContent),
   $("scroll").textContent.slice(0,40));
// Причины в панели «Проверить» приходят с сервера — они тоже должны быть
// на языке окна, иначе английское окно наполовину русское.
const probs = $("probs").textContent;
ok('панель «Проверить» по-английски',
   !CYR.test(probs.replace(/[0-9:.]/g, '').replace(/[^\S\n]+/g, ' ')
                  .split('\n').filter(l => !/^\s*\d+\./.test(l)).join(' ')) ||
   /no vocal|starts where|overlaps|syllables/i.test(probs),
   probs.replace(/\s+/g,' ').slice(0,90));

console.log('\n--- переключение на месте ---');
$("btnLang").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(600);
ok('надписи стали русскими', /Дорожка/.test(doc.querySelector('.tlhead').textContent),
   doc.querySelector('.tlhead').textContent.slice(0,40));
ok('подсказка про клавиши тоже', /Пробел/.test($("hint").textContent),
   $("hint").textContent.slice(0,40));
ok('сводка тоже', /Длина|Строк/.test($("sum").textContent), $("sum").textContent.slice(0,50));
ok('кнопка теперь предлагает английский', $("btnLang").textContent.trim() === "EN");
ok('выбор записан в память', w.localStorage.getItem("karaoke-studio-lang") === "ru",
   String(w.localStorage.getItem("karaoke-studio-lang")));
ok('атрибут языка страницы обновлён', doc.documentElement.lang === "ru");

console.log('\n--- обратно ---');
$("btnLang").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(600);
ok('снова английский', /Timeline/.test(doc.querySelector('.tlhead').textContent),
   doc.querySelector('.tlhead').textContent.slice(0,40));

ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
