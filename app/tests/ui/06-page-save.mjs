const { JSDOM } = await import('jsdom');
import fs from 'fs';
const mk = (html, store) => new JSDOM(html, {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;this.seeking=false;
      this.playbackRate=1;this._t=0;this._h={};w.__inst.push(this);setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){this._h[n]=(this._h[n]||[]).filter(x=>x!==f);}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;this._fire('play');return Promise.resolve();} pause(){this.paused=true;this._fire('pause');}}
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

// --- 1. edit the timing in the “browser” and save the page ---
const d1 = mk(fs.readFileSync(process.env.KARAOKE_PAGE_MIX, 'utf8'));
const w1=d1.window, doc1=w1.document, $1=id=>doc1.getElementById(id);
let savedHtml=null, savedName=null;
w1.URL.createObjectURL=()=>'blob:x'; w1.URL.revokeObjectURL=()=>{};
w1.Blob=class{constructor(p){savedHtml=String(p[0]);}};
w1.HTMLAnchorElement.prototype.click=function(){ savedName=this.download; };
await sleep(200);
const m1=w1.__inst[0];
m1.currentTime=9; await sleep(80);
doc1.dispatchEvent(new w1.KeyboardEvent('keydown',{key:']',bubbles:true}));
await sleep(40);                              // move the current line
$1('chkRest').checked = true;
$1('btnHere').click(); await sleep(40);       // and the whole tail
$1('chkRest').checked = false;
$1('btnSaveJson').click();
const edited = JSON.parse(savedHtml).lines.map(l=>+l.start.toFixed(3));
$1('btnSavePage').click();
ok('the page saves as .html', /\.html$/.test(savedName||''), String(savedName));
ok('it has the audio in it', savedHtml.includes('data:audio/'));
ok('the generated markup does not bloat the file', !savedHtml.includes('class="w"'));

// --- 2. open the saved page as a new file ---
const d2 = mk(savedHtml);
const w2=d2.window, doc2=w2.document;
await sleep(200);
const P2=JSON.parse(doc2.getElementById('payload').textContent);
const reopened=P2.data.lines.map(l=>+l.start.toFixed(3));
ok('the edits are baked into the saved page', JSON.stringify(reopened)===JSON.stringify(edited),
   `was ${edited.slice(0,3)}, now ${reopened.slice(0,3)}`);
ok('the storage key is new (old edits will not be pulled in)', P2.id !== JSON.parse(doc1.getElementById('payload').textContent).id,
   `${JSON.parse(doc1.getElementById('payload').textContent).id} → ${P2.id}`);
ok('the page is alive: the lines were drawn', doc2.querySelectorAll('.ln').length===6,
   'lines '+doc2.querySelectorAll('.ln').length);
ok('no JS errors', w2.__errs.length===0 && w1.__errs.length===0,
   [...w1.__errs,...w2.__errs].join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
