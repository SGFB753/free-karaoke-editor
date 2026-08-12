const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_MIX, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{ constructor(){this.currentTime=0;this.paused=true;this.volume=1;this.duration=26;
      this._h={};w.__inst.push(this);setTimeout(()=>this._fire('loadedmetadata'),0);}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} _fire(n){(this._h[n]||[]).forEach(f=>f());}
      play(){this.paused=false;this._fire('play');return Promise.resolve();} pause(){this.paused=true;this._fire('pause');}}
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
let saved=null; w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const master=w.__inst[0];
const cur=()=>[...doc.querySelectorAll('.ln')].findIndex(e=>e.classList.contains('cur'));
const space=()=>doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',bubbles:true}));

// run the song to the middle so we can check the rewind to the start
master.currentTime=12; await sleep(60);
ok('before tapping the lyrics scroll by themselves', cur()===3, 'line '+(cur()+1));

$('btnTap').click(); await sleep(60);
ok('the mode is on, rewound to the start', master.currentTime===0, 't='+master.currentTime);
ok('playback stopped', master.paused);
ok('we are standing on the first line', cur()===0, 'line '+(cur()+1));
ok('the counter shows the progress', /строка 1 из 6/.test($('btnTap').textContent), $('btnTap').textContent);
ok('the tapping hint appeared', !$('tapRow').classList.contains('hide'));

// THE POINT: time runs on, the text must stand still
master.currentTime=9; await sleep(80);
ok('the lyrics did NOT scroll away, though 9 s passed', cur()===0, 'line '+(cur()+1));

space(); await sleep(40);
ok('the first Space starts the song, it does not mark', !master.paused && cur()===0);

master.currentTime=3.0; await sleep(40); space(); await sleep(40);
ok('the second Space marked line 1 and moved to 2', cur()===1, 'line '+(cur()+1));
master.currentTime=7.0; await sleep(40); space(); await sleep(40);
master.currentTime=11.0; await sleep(40); space(); await sleep(40);
ok('after three taps we are on line 4', cur()===3, 'line '+(cur()+1));
ok('the counter updated', /строка 4 из 6/.test($('btnTap').textContent), $('btnTap').textContent);

// time runs between taps — the line must not change
master.currentTime=20; await sleep(80);
ok('and between taps the lyrics stay put', cur()===3, 'line '+(cur()+1));

doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Backspace',bubbles:true})); await sleep(60);
ok('Backspace went one line back', cur()===2, 'line '+(cur()+1));
ok('the counter rolled back', /строка 3 из 6/.test($('btnTap').textContent), $('btnTap').textContent);

// picking the line to go on marking from
[...doc.querySelectorAll('.ln')][4].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
ok('in tap mode clicking a line selects it', cur()===4, 'line '+(cur()+1));
ok('the counter jumped', /строка 5 из 6/.test($('btnTap').textContent), $('btnTap').textContent);
ok('the audio seeked to that line', master.currentTime < 16.2, 't='+master.currentTime.toFixed(2));
master.currentTime=17.0; await sleep(40); space(); await sleep(40);
ok('the mark landed on the chosen line', cur()===5, 'line '+(cur()+1));

$('btnTap').click(); await sleep(60);
ok('the mode is off, the hint is hidden', $('tapRow').classList.contains('hide'));
master.currentTime=12; await sleep(80);
ok('after leaving, the lyrics follow the clock again', cur()>=0);

$('btnSaveJson').click();
const j=JSON.parse(saved);
ok('the tapped lines got my times',
   Math.abs(j.lines[0].start-3.0)<0.01 && Math.abs(j.lines[1].start-7.0)<0.01,
   `${j.lines[0].start}, ${j.lines[1].start}`);
ok('no JS errors', w.__errs.length===0, w.__errs.join(';'));
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
