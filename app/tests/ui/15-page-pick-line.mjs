// Явный выбор строки для правки.
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
const lns=()=>[...doc.querySelectorAll('.ln')];
const tgtIdx=()=>lns().findIndex(e=>e.classList.contains('tgt'));
const curIdx=()=>lns().findIndex(e=>e.classList.contains('cur'));

console.log('--- метка цели видна только при открытой правке ---');
m.currentTime=9.0; await sleep(80);
ok('без панели правки класс editing не стоит',
   !doc.body.classList.contains('editing'));
$('btnEdit').click(); await sleep(30);
ok('открыли правку — класс появился', doc.body.classList.contains('editing'));
$('btnEdit').click(); await sleep(30);
ok('закрыли — класс снят', !doc.body.classList.contains('editing'));
$('btnEdit').click(); await sleep(30);

console.log('\n--- по умолчанию правим ТУ строку, что подсвечена ---');
m.currentTime=14.8; await sleep(80);      // проигрыш после 4-й строки
ok('подсвечена 4-я строка', curIdx()===3, 'подсвечена '+(curIdx()+1));
ok('цель правки совпадает с подсвеченной', tgtIdx()===3, 'цель '+(tgtIdx()+1));
ok('подпись показывает её', /^4\./.test($('tgtName').textContent), $('tgtName').textContent);

const base=starts();
$('btnHere').click(); await sleep(60);
const a1=starts();
ok('переставлена именно подсвеченная 4-я', Math.abs(a1[3]-14.8)<0.05, `${base[3]} → ${a1[3]}`);
ok('пятая не тронута', a1[4]===base[4]);

console.log('\n--- ▶ переводит цель на следующую строку ---');
$('btnReset').click(); await sleep(60);
m.currentTime=14.8; await sleep(80);
$('btnTgtNext').click(); await sleep(30);
ok('цель ушла на 5-ю', tgtIdx()===4, 'цель '+(tgtIdx()+1));
ok('подсветка проигрывания не поехала', curIdx()===3, 'подсвечена '+(curIdx()+1));
ok('подпись обновилась', /^5\./.test($('tgtName').textContent), $('tgtName').textContent);
const b2=starts();
$('btnHere').click(); await sleep(60);
const a2=starts();
ok('переставлена 5-я, а не 4-я', Math.abs(a2[4]-14.8)<0.05 && a2[3]===b2[3],
   `4: ${b2[3]}→${a2[3]}, 5: ${b2[4]}→${a2[4]}`);

console.log('\n--- ◀ и края списка ---');
$('btnTgtPrev').click(); $('btnTgtPrev').click(); await sleep(30);
ok('цель ушла на две строки вверх', tgtIdx()===2, 'цель '+(tgtIdx()+1));
const pinned = tgtIdx();
m.currentTime=2.5; await sleep(80);
ok('выбранная цель держится, даже когда песня ушла дальше', tgtIdx()===pinned,
   `цель ${tgtIdx()+1}, подсвечена ${curIdx()+1}`);
$('btnUnpin').click(); await sleep(60);
ok('«не эту» возвращает цель к подсвеченной строке', tgtIdx()===curIdx(),
   `цель ${tgtIdx()+1}, подсвечена ${curIdx()+1}`);
for (let i=0;i<9;i++) $('btnTgtPrev').click();
await sleep(30);
ok('за первую строку не уходим', tgtIdx()===0, 'цель '+(tgtIdx()+1));
for (let i=0;i<20;i++) $('btnTgtNext').click();
await sleep(30);
ok('за последнюю тоже', tgtIdx()===5, 'цель '+(tgtIdx()+1));
ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
