// Новые проверки: фокус кнопок, чистота сохранённой страницы, точки отсчёта.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
function mk(file){
  return new JSDOM(fs.readFileSync(file,'utf8'), {
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
      // Web Audio недоступен -> запасной путь (для простоты управления временем)
      w.Element.prototype.getBoundingClientRect=function(){
        return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
      w.Element.prototype.setPointerCapture=function(){};
    }});
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

console.log('--- фокус не липнет к кнопкам ---');
{
  const d=mk(process.env.KARAOKE_PAGE_MIX), w=d.window, doc=w.document, $=id=>doc.getElementById(id);
  await sleep(200);
  const btn=$('btnEdit');
  btn.focus();
  ok('до клика фокус на кнопке', doc.activeElement===btn);
  btn.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await sleep(20);
  ok('после клика фокус снят', doc.activeElement!==btn,
     'activeElement='+(doc.activeElement&&doc.activeElement.id||doc.activeElement.tagName));
}

console.log('\n--- сохранённая страница чистая ---');
{
  const d=mk(process.env.KARAOKE_PAGE_STEMS), w=d.window, doc=w.document, $=id=>doc.getElementById(id);
  let saved=null;
  w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
  w.Blob=class{constructor(p){saved=String(p[0]);}};
  w.HTMLAnchorElement.prototype.click=function(){};
  await sleep(200);
  // включаем «грязное» состояние: играем + режим тапов
  $('btnPlay').click(); await sleep(30);
  $('btnEdit').click(); $('btnTap').click(); await sleep(30);
  $('btnSavePage').click(); await sleep(30);
  ok('файл получен', !!saved && saved.includes('<!DOCTYPE html>'));
  const dom2=new JSDOM(saved);
  const b=dom2.window.document.body;
  ok('нет класса playing/tapping', b.className==='', 'class="'+b.className+'"');
  ok('кнопка тапов в исходном виде',
     dom2.window.document.getElementById('btnTap').textContent==='Разметка по тапам');
  ok('подсказка по тапам скрыта',
     dom2.window.document.getElementById('tapRow').classList.contains('hide'));
  ok('редактор закрыт',
     !dom2.window.document.getElementById('editor').classList.contains('open'));
  ok('тост скрыт', dom2.window.document.getElementById('toast').className==='toast');
  const pl=JSON.parse(dom2.window.document.getElementById('payload').textContent);
  ok('в сохранённой отметка edited', pl.edited===true);
  ok('ключ хранения длиннее и уникальнее', pl.id.length>16, 'id='+pl.id);
}

console.log('\n--- точки отсчёта на новой схеме ---');
{
  const d=mk(process.env.KARAOKE_PAGE_MIX), w=d.window, doc=w.document, $=id=>doc.getElementById(id);
  await sleep(200);
  const m=w.__inst[0];
  // строка 5 начинается на 16.14, перед ней пауза > 2.5с
  m.currentTime=14.0; await sleep(80);
  const lns=[...doc.querySelectorAll('.pips')];
  const lit=()=>lns.map(p=>[...p.children].filter(s=>s.classList.contains('on')).length)
                  .reduce((a,b)=>a+b,0);
  ok('за 2.1с до строки горят точки', lit()>0, 'горит '+lit());
  m.currentTime=16.5; await sleep(80);
  ok('после начала строки точки погашены', lit()===0, 'горит '+lit());
  m.currentTime=3.0; await sleep(80);
  ok('в обычном месте точек нет', lit()===0);
  ok('ошибок JS нет', w.__errs.length===0, w.__errs.join(';'));
}
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
