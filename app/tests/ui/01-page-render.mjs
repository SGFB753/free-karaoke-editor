const { JSDOM } = await import('jsdom');
import fs from 'fs';

const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_MIX, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true,
  beforeParse(w){
    w.__inst = [];
    class FakeAudio {
      constructor(){ this.currentTime=0; this.paused=true; this.volume=1; this.duration=26;
        this._h={}; w.__inst.push(this); setTimeout(()=>this._fire('loadedmetadata'),0); }
      addEventListener(n,f){ (this._h[n]=this._h[n]||[]).push(f); }
      _fire(n){ (this._h[n]||[]).forEach(f=>f()); }
      play(){ this.paused=false; this._fire('play'); return Promise.resolve(); }
      pause(){ this.paused=true; this._fire('pause'); }
    }
    w.Audio = FakeAudio;
    w.__errs = [];
    w.onerror = (m)=>{ w.__errs.push(String(m)); };
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r=>setTimeout(r,ms));
await sleep(200);

let fail = 0;
const ok = (name, cond, extra='') => { console.log((cond?'  ✓ ':'  ✗ ')+name+(extra?' — '+extra:'')); if(!cond) fail++; };

console.log('JS errors:', w.__errs.length ? w.__errs : 'none');
ok('no errors while loading', w.__errs.length===0);

const lns = [...doc.querySelectorAll('.ln')];
ok('6 lines drawn', lns.length===6, 'got '+lns.length);
ok('the sections are shown', doc.querySelectorAll('.sect').length===2);
ok('the title comes from the meta fields', $('mTitle').textContent==='Тестовая песня', $('mTitle').textContent);
ok('the artist', $('mArtist').textContent==='Проверка Связи');
ok('one track => the voice slider is hidden', $('grpVocal').style.display==='none');
ok('the length in the footer', $('tDur').textContent==='0:26', $('tDur').textContent);

const master = w.__inst[0];
const cur = () => lns.findIndex(e=>e.classList.contains('cur'));
console.log('--- highlight by time (expected starts 2/5/8/11/16/19) ---');
for (const [t, want] of [[0.5,-1],[2.5,0],[5.5,1],[8.5,2],[12,3],[17,4],[21,5]]){
  master.currentTime = t; await sleep(70);
  ok(`t=${t}s → line ${want<0?'none':want+1}`, cur()===want, 'lit '+(cur()<0?'none':cur()+1));
}

// how far a word is filled inside a line
master.currentTime = 5.2; await sleep(70);
const hls = [...lns[1].children].map(s=>s.firstChild);
const p0 = hls[0].style.width;
master.currentTime = 6.9; await sleep(70);
const full = hls.filter(h=>h.style.width==='100%').length;
ok('the words fill in one after another', full>0 && full<hls.length, `sung ${full} of ${hls.length}`);
ok('the first word is partly filled', /%$/.test(p0) && p0!=='100%' && p0!=='0%', 'width='+p0);
ok('the lit layer is a separate element (no per-letter gradient)',
   hls.every(h=>h.className==='hl'));

// the offset
$('rOffset').value = 500; $('rOffset').dispatchEvent(new w.Event('input'));
ok('the offset applied and shows to the millisecond',
   $('vOffset').textContent==='+0.500с', $('vOffset').textContent);
ok('the current time is in milliseconds too', /^\d+:\d\d\.\d{3}$/.test($('tCur').textContent),
   $('tCur').textContent);
master.currentTime = 5.2; await sleep(70);
ok('with a +0.5 s offset line 2 has not started', cur()===0, 'line '+(cur()+1));
$('rOffset').value = 0; $('rOffset').dispatchEvent(new w.Event('input'));

// LRC export
let dl=null;
w.HTMLAnchorElement.prototype.click = function(){ dl=this.download; };
w.URL.createObjectURL = () => 'blob:x'; w.URL.revokeObjectURL = ()=>{};
$('btnSaveLrc').click(); ok('the .lrc button hands over a file', dl==='lyrics.lrc', String(dl));
$('btnSaveJson').click(); ok('the .json button hands over a file', dl==='timings.json', String(dl));

// a click on a line = a seek
lns[4].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
ok('clicking a line seeks', Math.abs(master.currentTime-(16.14-0.35))<0.4, 't='+master.currentTime.toFixed(2));

// play/pause
$('btnPlay').click(); await sleep(30);
ok('play starts', !master.paused && doc.body.classList.contains('playing'));
$('btnPlay').click(); await sleep(30);
ok('pause stops', master.paused);

console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail?1:0);
