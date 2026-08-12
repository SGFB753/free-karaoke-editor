// The Studio window in English and the language switch.
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

console.log('--- the window built in English ---');
const dom = mk('en'); const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
w.eval(js);
await sleep(900);
ok('the title is English', $("scrList").querySelector("h1").textContent === "Karaoke Studio",
   $("scrList").querySelector("h1").textContent);
ok('the add button is translated', /Add a song/.test($("btnAdd").textContent),
   $("btnAdd").textContent);
ok('the language button offers Russian', $("btnLang").textContent.trim() === "RU",
   $("btnLang").textContent);

// the add-a-song screen — it carries the most labels
$("btnAdd").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(400);
// Language names are written in the languages themselves (“русский”, “日本語”) —
// they are not translated, so the language list is excluded from the check.
const newScreen = [...$("scrNew").querySelectorAll("label, button, option, .hint, .warn")]
  .filter(e => !e.closest("#selLang")).map(e => e.textContent).join(" ");
ok('the new-song screen carries no Cyrillic', !CYR.test(newScreen),
   (newScreen.match(/[А-Яа-яЁё][^\s]*/g)||[]).slice(0,4).join(" "));
ok('“detect from the text” is translated',
   !CYR.test([...$("selLang").options].find(o=>o.value==="auto").textContent),
   [...$("selLang").options].find(o=>o.value==="auto").textContent);
ok('the model hint is in English', !CYR.test($("modelNote").textContent),
   $("modelNote").textContent.slice(0,60));
ok('the model size is written as MB', /MB/.test($("selModel").options[0].textContent),
   $("selModel").options[0].textContent);

// the editor
$("btnBackNew").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(300);
doc.querySelectorAll('.card')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(1400);
const editUi = [...doc.querySelectorAll('.tlhead, footer, .howto, .side h3, .madefile')]
  .map(e => e.textContent).join(" ");
ok('the editor labels are English', !CYR.test(editUi),
   (editUi.match(/[А-Яа-яЁё][^\s]*/g)||[]).slice(0,4).join(" "));
ok('the keyboard hint is translated', /Space — play/.test($("hint").textContent),
   $("hint").textContent);
ok('the summary is in English', /Length|Lines/.test($("sum").textContent),
   $("sum").textContent.slice(0,60));
// the lyrics themselves are Russian, of course — that is data, not labels
ok('the lyrics themselves are untouched', CYR.test($("scroll").textContent),
   $("scroll").textContent.slice(0,40));
// The reasons in the “Check” panel come from the server — they too must be in
// the language of the window, or an English window is half Russian.
const probs = $("probs").textContent;
ok('the “Check” panel is in English',
   !CYR.test(probs.replace(/[0-9:.]/g, '').replace(/[^\S\n]+/g, ' ')
                  .split('\n').filter(l => !/^\s*\d+\./.test(l)).join(' ')) ||
   /no vocal|starts where|overlaps|syllables/i.test(probs),
   probs.replace(/\s+/g,' ').slice(0,90));

console.log('\n--- switching in place ---');
$("btnLang").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(600);
ok('the labels turned Russian', /Дорожка/.test(doc.querySelector('.tlhead').textContent),
   doc.querySelector('.tlhead').textContent.slice(0,40));
ok('the keyboard hint too', /Пробел/.test($("hint").textContent),
   $("hint").textContent.slice(0,40));
ok('the summary too', /Длина|Строк/.test($("sum").textContent), $("sum").textContent.slice(0,50));
ok('the button now offers English', $("btnLang").textContent.trim() === "EN");
ok('the choice was written to storage', w.localStorage.getItem("karaoke-studio-lang") === "ru",
   String(w.localStorage.getItem("karaoke-studio-lang")));
ok('the page language attribute was updated', doc.documentElement.lang === "ru");

console.log('\n--- and back ---');
$("btnLang").dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(600);
ok('English again', /Timeline/.test(doc.querySelector('.tlhead').textContent),
   doc.querySelector('.tlhead').textContent.slice(0,40));

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
