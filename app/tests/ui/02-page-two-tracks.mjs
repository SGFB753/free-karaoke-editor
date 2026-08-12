const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true,
  beforeParse(w){
    w.__inst=[];
    class FakeAudio{ constructor(){this.currentTime=0;this.paused=true;this.volume=1;this.duration=26;
      this._h={};this.src='';w.__inst.push(this);setTimeout(()=>this._fire('loadedmetadata'),0);}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} _fire(n){(this._h[n]||[]).forEach(f=>f());}
      play(){this.paused=false;this._fire('play');return Promise.resolve();} pause(){this.paused=true;this._fire('pause');}}
    w.Audio=FakeAudio; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window, doc=w.document, $=id=>doc.getElementById(id), sleep=ms=>new Promise(r=>setTimeout(r,ms));
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
ok('no errors', w.__errs.length===0, w.__errs.join(';'));
ok('two audio elements were created', w.__inst.length===2, 'created '+w.__inst.length);
const [master, voice] = w.__inst;
ok('both tracks are embedded as data:', master.src.startsWith('data:audio/mpeg;base64,') && voice.src.startsWith('data:audio/'));
ok('the tracks differ', master.src !== voice.src);
ok('the badge is gone from the header', !$('mBadge'));
ok('title and artist in the header', $('mTitle').textContent && $('mArtist').textContent,
   $('mTitle').textContent+' / '+$('mArtist').textContent);
ok('the voice slider is visible', $('grpVocal').style.display !== 'none');
ok('it starts as a clean instrumental (voice 0)', voice.volume===0, 'volume='+voice.volume);
$('rVocal').value=100; $('rVocal').dispatchEvent(new w.Event('input'));
ok('voice at 100% => the vocal is heard', voice.volume===1 && $('vVocal').textContent==='100%');
$('rVocal').value=45; $('rVocal').dispatchEvent(new w.Event('input'));
ok('an in-between value', Math.abs(voice.volume-0.45)<1e-6, 'volume='+voice.volume);
$('btnPlay').click(); await sleep(40);
ok('play starts both tracks', !master.paused && !voice.paused);
// drift between the tracks must heal itself
voice.currentTime = master.currentTime + 0.5; master.currentTime = 10; await sleep(80);
ok('drift between the tracks is corrected', Math.abs(voice.currentTime-master.currentTime)<0.09,
   'delta='+Math.abs(voice.currentTime-master.currentTime).toFixed(3));
$('btnPlay').click(); await sleep(30);
ok('pause stops both', master.paused && voice.paused);
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
