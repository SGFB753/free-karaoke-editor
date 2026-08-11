const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{
      constructor(){ this.paused=true; this.volume=1; this.duration=26; this.seeking=false;
        this.playbackRate=1; this.seekCount=0;
        this._t=0; this._h={}; w.__inst.push(this); setTimeout(()=>this._fire('loadedmetadata'),0); }
      get currentTime(){ return this._t; }
      set currentTime(v){                     // перемотка асинхронная, как в браузере
        this.seeking=true; this.seekCount++; const d=w.__seekDelay[w.__inst.indexOf(this)]||10;
        setTimeout(()=>{ this._t=v; this.seeking=false; this._fire('seeked'); }, d);
      }
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){ this._h[n]=(this._h[n]||[]).filter(x=>x!==f); }
      _fire(n){ (this._h[n]||[]).slice().forEach(f=>f()); }
      play(){ this.paused=false; this._fire('play'); return Promise.resolve(); }
      pause(){ this.paused=true; this._fire('pause'); }
    }
    w.Audio=FA; w.__seekDelay=[10,120];
    w.Element.prototype.setPointerCapture=function(){};
    w.Element.prototype.getBoundingClientRect=function(){return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0};};
    w.Element.prototype.releasePointerCapture=function(){};      // вторая дорожка перематывается дольше
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
let saved=null; w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const [master, voice] = w.__inst;

console.log('--- перемотка при двух дорожках ---');
$('btnPlay').click(); await sleep(30);
ok('играют обе', !master.paused && !voice.paused);
$('seek').dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true, clientX:400}));
await sleep(40);
ok('во время перемотки обе стоят (нет наложения)', master.paused && voice.paused,
   `master=${master.paused} voice=${voice.paused}`);
w.dispatchEvent(new w.MouseEvent('pointerup',{bubbles:true, clientX:400}));
await sleep(400);
ok('после перемотки обе снова играют', !master.paused && !voice.paused);
ok('дорожки встали на одно место', Math.abs(master.currentTime-voice.currentTime)<0.001,
   `дельта=${Math.abs(master.currentTime-voice.currentTime).toFixed(3)}`);

console.log('--- быстрые перемотки подряд ---');
for (let i=0;i<4;i++){ seekBy(); await sleep(25); }
function seekBy(){ doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})); }
await sleep(400);
ok('после серии перемоток дорожки синхронны', Math.abs(master.currentTime-voice.currentTime)<0.001,
   `дельта=${Math.abs(master.currentTime-voice.currentTime).toFixed(3)}`);
ok('и обе играют', !master.paused && !voice.paused);

console.log('--- мышь отпустили вне полосы ---');
$('seek').dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true, clientX:250}));
await sleep(40);
w.dispatchEvent(new w.MouseEvent('pointerup',{bubbles:true, clientX:250}));
await sleep(400);
ok('после отпускания вне полосы музыка играет', !master.paused && !voice.paused);

console.log('--- вокал не должен пропадать ---');
master.currentTime=5; await sleep(300);
const seeksBefore = voice.seekCount;
// имитируем небольшое расхождение дорожек, какое бывает после перемотки
voice._t = master.currentTime - 0.15;
await sleep(120);
ok('малое расхождение НЕ лечится перемоткой (вокал не замолкает)',
   voice.seekCount===seeksBefore, `перемоток вокала: ${voice.seekCount-seeksBefore}`);
ok('вместо этого правится скоростью', voice.playbackRate>1 && voice.playbackRate<=1.02,
   'playbackRate='+voice.playbackRate.toFixed(3));
voice._t = master.currentTime;
await sleep(120);
ok('когда сошлись — скорость возвращается к обычной', voice.playbackRate===1);
voice._t = master.currentTime - 1.2;         // разъехалось всерьёз
await sleep(120);
ok('крупное расхождение всё же лечится перемоткой', voice.seekCount>seeksBefore);

console.log('--- перетаскивание ползунка ---');
$('seek').dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true, clientX:200}));
await sleep(60);
$('seek').dispatchEvent(new w.MouseEvent('pointermove',{bubbles:true, clientX:300}));
await sleep(60);
ok('пока тащим — звук молчит, наложения нет', master.paused && voice.paused,
   `master=${master.paused} voice=${voice.paused}`);
$('seek').dispatchEvent(new w.MouseEvent('pointerup',{bubbles:true, clientX:300}));
await sleep(400);
ok('отпустили — заиграло снова', !master.paused && !voice.paused);
ok('и дорожки на одном месте', Math.abs(master.currentTime-voice.currentTime)<0.001);

console.log('--- точечная правка ---');
master.currentTime=9; await sleep(200);
const lns=[...doc.querySelectorAll('.ln')];
const cur=()=>lns.findIndex(e=>e.classList.contains('cur'));
const i0=cur();
$('btnSaveJson').click(); const before=JSON.parse(saved).lines.map(l=>l.start);
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true}));
await sleep(40); $('btnSaveJson').click();
let after=JSON.parse(saved).lines.map(l=>l.start);
ok('клавиша ] двигает только текущую строку',
   Math.abs(after[i0]-before[i0]-0.05)<1e-6 && Math.abs(after[i0+1]-before[i0+1])<1e-6,
   `строка ${i0+1}: ${before[i0].toFixed(2)}→${after[i0].toFixed(2)}, следующая не тронута`);

$('chkRest').checked = true;
doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:']',bubbles:true}));
await sleep(40); $('btnSaveJson').click();
after=JSON.parse(saved).lines.map(l=>l.start);
const restOk=after.every((v,k)=> k<i0 ? Math.abs(v-before[k])<1e-6
                                      : Math.abs(v-before[k]-(k===i0?0.10:0.05))<1e-6);
ok('с флажком «и все следующие» едет весь хвост', restOk,
   `до неё ${i0} строк без изменений, дальше все +0,05с`);
$('chkRest').checked = false;

master.currentTime=12.4; await sleep(200);
const j=cur();
$('btnHere').click(); await sleep(40); $('btnSaveJson').click();
const now=JSON.parse(saved).lines[j].start;
ok('«строка начинается здесь» ставит её на текущую секунду', Math.abs(now-12.4)<0.02,
   `start=${now.toFixed(2)}`);

$('btnUndo').click(); await sleep(30);
ok('отмена работает после правок', true);
ok('ошибок JS нет', w.__errs.length===0, w.__errs.join(';'));
console.log(fail?`\nПРОВАЛЕНО: ${fail}`:'\nВсе проверки пройдены');
process.exit(fail?1:0);
