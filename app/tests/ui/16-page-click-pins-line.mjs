// Picking a line on the standalone HTML page: click a line and that is the one
// edited, and the song no longer steals it. The target used to slide back a line.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;this.seeking=false;
      this.playbackRate=1;this._t=0;this._h={};w.__inst.push(this);setTimeout(()=>this._fire('loadedmetadata'),0);}
      get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);}
      removeEventListener(n,f){this._h[n]=(this._h[n]||[]).filter(x=>x!==f);}
      _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
      play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
let saved=null;
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(250);

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const tgtNo = () => { const m=/^(\d+)\./.exec($('tgtName').textContent.trim()); return m?+m[1]-1:-1; };
const starts = async () => { saved=null; $('btnSaveJson').click(); await sleep(20);
                             return JSON.parse(saved).lines.map(l=>l.start); };
const m = w.__inst[0];
const lineEls = [...doc.querySelectorAll('#scroll .ln')];

const __savedLabelAtStart = $('btnSavePage').textContent;
$('btnEdit').click(); await sleep(50);
ok('there are enough lines on stage for the check', lineEls.length >= 5, 'lines '+lineEls.length);

console.log('\n--- a click picks exactly that line ---');
const WANT = 4;
lineEls[WANT].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(120);
ok('the line that was clicked is the one edited', tgtNo() === WANT,
   'selected ' + (tgtNo()+1) + 'th instead of ' + (WANT+1) + 'th');
ok('and it is the one underlined on stage',
   lineEls[WANT].classList.contains('tgt'), [...lineEls[WANT].classList].join(' '));

console.log('\n--- the song plays, the choice holds ---');
const before = await starts();
m.currentTime = before[WANT] + 6;              // jumped far ahead
await sleep(150);
ok('the target did not run off with the song', tgtNo() === WANT, 'now ' + (tgtNo()+1) + 'th');

console.log('\n--- the edit lands on the chosen line ---');
m.currentTime = 12.5; await sleep(100);
$('btnHere').click(); await sleep(80);
const after = await starts();
ok('the chosen line moved to the current second', Math.abs(after[WANT]-12.5) < 0.05,
   'now ' + after[WANT]);
ok('the neighbouring line was not touched', Math.abs(after[WANT-1]-before[WANT-1]) < 1e-6,
   `${before[WANT-1]} → ${after[WANT-1]}`);

console.log('\n--- the choice is visible and can be dropped ---');
ok('the “not this one” button appeared', !$('btnUnpin').classList.contains('hide'));
$('btnUnpin').click(); await sleep(80);
ok('the button hid again', $('btnUnpin').classList.contains('hide'));
m.currentTime = 2.0; await sleep(150);
ok('the target follows the song again', tgtNo() !== WANT, 'still ' + (tgtNo()+1) + 'th');

console.log('\n--- ◀ ▶ pin the target too ---');
$('btnTgtNext').click(); await sleep(60);
const t1 = tgtNo();
ok('▶ moved the target', t1 >= 0);
ok('and pinned it', !$('btnUnpin').classList.contains('hide'));
m.currentTime = 20; await sleep(150);
ok('the target stayed put during playback', tgtNo() === t1, 'now ' + (tgtNo()+1));

console.log('\n--- nothing extra on the screen ---');
ok('the tapping hint is hidden while the mode is off',
   $('tapRow').classList.contains('hide') &&
   w.getComputedStyle($('tapRow')).display === 'none',
   'display: ' + w.getComputedStyle($('tapRow')).display);

$('btnSavePage').click(); await sleep(60);
ok('the saved page opens with no pinned target',
   /id="btnUnpin" class="hide"/.test(saved) || /class="hide"[^>]*id="btnUnpin"/.test(saved),
   (saved.match(/<button id="btnUnpin"[^>]*>/)||[''])[0]);

console.log('\n--- it is visible that the edits are not in the file yet ---');
ok('on a fresh page the save button looks ordinary',
   !/есть несохранённые/.test(__savedLabelAtStart), __savedLabelAtStart);
ok('right after saving there is no warning',
   !/есть несохранённые/.test($('btnSavePage').textContent),
   $('btnSavePage').textContent);
$('btnHere').click(); await sleep(80);          // editing after the save this time
ok('a new edit warns again',
   /есть несохранённые/.test($('btnSavePage').textContent) &&
   $('btnSavePage').classList.contains('on'),
   $('btnSavePage').textContent);

ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
