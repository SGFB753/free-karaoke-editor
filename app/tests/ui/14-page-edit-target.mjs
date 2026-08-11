// Правка во время проигрыша должна целиться в СЛЕДУЮЩУЮ строку.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_MIX, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[]; w.__errs=[];
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;this.seeking=false;
      this.playbackRate=1;this._t=0;this._h={};w.__inst.push(this);
      setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA; w.onerror=m=>w.__errs.push(String(m));
    w.Element.prototype.getBoundingClientRect=function(){
      return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
    w.Element.prototype.setPointerCapture=function(){};
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
let saved=null;
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const m=w.__inst[0];
const starts=()=>{ $('btnSaveJson').click(); return JSON.parse(saved).lines.map(l=>+l.start.toFixed(3)); };
const base=starts();
console.log('  исходные старты:', base.join(', '));

console.log('\n--- нажали «строка начинается здесь» ВО ВРЕМЯ ПРОИГРЫША ---');
// после строки 4 (кончается ~13.6) идёт пауза до строки 5 (16.14).
// Правится ТА строка, что видна подсвеченной, — то есть 4-я.
m.currentTime=14.8; await sleep(80);
$('btnHere').click(); await sleep(60);
const after=starts();
ok('переставлена подсвеченная, четвёртая строка', Math.abs(after[3]-14.8)<0.05,
   `${base[3]} → ${after[3]}`);
ok('пятая не тронута', after[4]===base[4], `${base[4]} → ${after[4]}`);
ok('её слова начинаются с нового начала строки', (()=>{
   const l=JSON.parse(saved).lines[3]; return Math.abs(l.words[0].t-l.start)<0.02; })());
ok('длительности слов сохранены (заливка поедет плавно)', (()=>{
   const l=JSON.parse(saved).lines[3]; return l.words.every(x=>x.d>0); })());

console.log('\n--- внутри звучащей строки цель не меняется ---');
const b2=starts();
m.currentTime=9.0; await sleep(80);     // внутри строки 3 (8.00–10.6)
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true})); await sleep(60);
const a2=starts();
ok('сдвинута именно звучащая строка 3', Math.abs(a2[2]-b2[2]-0.05)<1e-6,
   `${b2[2]} → ${a2[2]}`);
ok('соседние не тронуты', a2[3]===b2[3]);

console.log('\n--- во вступлении, до первой строки ---');
const b3=starts();
m.currentTime=0.5; await sleep(80);     // первая строка начинается на 2.0
$('btnHere').click(); await sleep(60);
const a3=starts();
ok('правится первая строка, а не «ничего»', Math.abs(a3[0]-0.5)<0.05,
   `${b3[0]} → ${a3[0]}`);

console.log('\n--- флажок «и все следующие» ---');
$('btnReset').click(); await sleep(60);
const b4=starts();
m.currentTime=14.8; await sleep(80);
$('chkRest').checked = true; $('btnHere').click(); await sleep(60); $('chkRest').checked=false;
const a4=starts();
ok('строки до подсвеченной не тронуты',
   [0,1,2].every(i=>Math.abs(a4[i]-b4[i])<1e-6));
const d4 = a4[3]-b4[3];
ok('подсвеченная и все следующие уехали одинаково',
   [4,5].every(i=>Math.abs((a4[i]-b4[i])-d4)<1e-6), `сдвиг ${d4.toFixed(2)}с`);
ok('ошибок JS нет', w.__errs.length===0, w.__errs.join(';'));
console.log(fail?`\nПРОВАЛЕНО: ${fail}`:'\nВсе проверки пройдены');
process.exit(fail?1:0);
