// New checks: button focus, the cleanliness of the saved page, the count-in dots.
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
      // Web Audio is unavailable -> the fallback path (easier to steer time in)
      w.Element.prototype.getBoundingClientRect=function(){
        return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
      w.Element.prototype.setPointerCapture=function(){};
    }});
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

console.log('--- focus does not stick to the buttons ---');
{
  const d=mk(process.env.KARAOKE_PAGE_MIX), w=d.window, doc=w.document, $=id=>doc.getElementById(id);
  await sleep(200);
  const btn=$('btnEdit');
  btn.focus();
  ok('before the click the button has focus', doc.activeElement===btn);
  btn.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  await sleep(20);
  ok('after the click the focus is dropped', doc.activeElement!==btn,
     'activeElement='+(doc.activeElement&&doc.activeElement.id||doc.activeElement.tagName));
}

console.log('\n--- the saved page is clean ---');
{
  const d=mk(process.env.KARAOKE_PAGE_STEMS), w=d.window, doc=w.document, $=id=>doc.getElementById(id);
  let saved=null;
  w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
  w.Blob=class{constructor(p){saved=String(p[0]);}};
  w.HTMLAnchorElement.prototype.click=function(){};
  await sleep(200);
  // turn on the “dirty” state: playing + tap mode
  $('btnPlay').click(); await sleep(30);
  $('btnEdit').click(); $('btnTap').click(); await sleep(30);
  $('btnSavePage').click(); await sleep(30);
  ok('the file came out', !!saved && saved.includes('<!DOCTYPE html>'));
  const dom2=new JSDOM(saved);
  const b=dom2.window.document.body;
  ok('no playing/tapping class', b.className==='', 'class="'+b.className+'"');
  ok('the tap button is in its original state',
     dom2.window.document.getElementById('btnTap').textContent==='Разметка по тапам');
  ok('the tapping hint is hidden',
     dom2.window.document.getElementById('tapRow').classList.contains('hide'));
  ok('the editor is closed',
     !dom2.window.document.getElementById('editor').classList.contains('open'));
  ok('the toast is hidden', dom2.window.document.getElementById('toast').className==='toast');
  const pl=JSON.parse(dom2.window.document.getElementById('payload').textContent);
  ok('the saved one is marked as edited', pl.edited===true);
  ok('the storage key is longer and unique', pl.id.length>16, 'id='+pl.id);
}

console.log('\n--- the countdown dots in the new layout ---');
{
  const d=mk(process.env.KARAOKE_PAGE_MIX), w=d.window, doc=w.document, $=id=>doc.getElementById(id);
  await sleep(200);
  const m=w.__inst[0];
  // line 5 starts at 16.14, with a pause of more than 2.5 s before it
  m.currentTime=14.0; await sleep(80);
  const lns=[...doc.querySelectorAll('.pips')];
  const lit=()=>lns.map(p=>[...p.children].filter(s=>s.classList.contains('on')).length)
                  .reduce((a,b)=>a+b,0);
  ok('2.1 s before a line the dots are lit', lit()>0, 'lit '+lit());
  m.currentTime=16.5; await sleep(80);
  ok('once the line starts the dots go out', lit()===0, 'lit '+lit());
  m.currentTime=3.0; await sleep(80);
  ok('in an ordinary place there are no dots', lit()===0);
  ok('no JS errors', w.__errs.length===0, w.__errs.join(';'));
}
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
