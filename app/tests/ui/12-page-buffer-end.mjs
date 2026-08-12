// A realistic Web Audio mock: a BufferSource really plays its buffer out and
// fires 'ended' itself, so a duration mismatch at the seam can be checked.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const HTML = fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8');

function mk(durs){       // durs: [instrumentalDur, vocalsDur] in virtual seconds
  return new JSDOM(HTML, { runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
    beforeParse(w){
      w.__now = 0; w.__timers = []; w.__live = new Set(); w.__errs = [];
      class Gain{ constructor(){ this.gain={value:1, setTargetAtTime(v){this.value=v;}}; } connect(){} }
      class Src{
        constructor(){ this.buffer=null; this.onended=null; this.stopped=false; w.__live.add(this); }
        connect(){}
        start(at, off){
          this.startAt = at; this.off = off;
          const remain = this.buffer.duration - off;
          w.__timers.push({ fireAt: at + remain, src: this });
        }
        stop(){ this.stopped=true; w.__live.delete(this); w.__timers = w.__timers.filter(t=>t.src!==this); }
      }
      class AC{
        constructor(){ this.state="running"; this.destination={}; }
        get currentTime(){ return w.__now; }
        createGain(){ return new Gain(); }
        createBufferSource(){ return new Src(); }
        decodeAudioData(b, ok){ const buf={ duration: durs[bi++] }; if(ok){ok(buf);return;} return Promise.resolve(buf); }
        resume(){ this.state="running"; }
        close(){}
      }
      let bi = 0;
      w.AudioContext = AC;
      w.fetch = () => Promise.resolve({ arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) });
      w.onerror = m => w.__errs.push(String(m));
      w.Element.prototype.getBoundingClientRect=function(){
        return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
      w.Element.prototype.setPointerCapture=function(){};
      // advancing virtual time: fire the timers whose moment has come
      w.__advance = sec => {
        w.__now += sec;
        const due = w.__timers.filter(t => t.fireAt <= w.__now);
        w.__timers = w.__timers.filter(t => t.fireAt > w.__now);
        due.forEach(t => { if (!t.src.stopped){ t.src.stopped=true; w.__live.delete(t.src);
          if (t.src.onended) t.src.onended(); } });
      };
    }});
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

console.log('--- the vocal is 0.3 s longer than the instrumental ---');
{
  const d = mk([26.0, 26.3]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  $('btnPlay').click(); await sleep(30);
  ok('both tracks are running', w.__live.size===2, 'live '+w.__live.size);
  w.__advance(26.05);                       // the backing track (shorter) ended
  await sleep(30);
  ok('at the end BOTH tracks are silenced, not just the first', w.__live.size===0,
     'still live '+w.__live.size);
  ok('the icon went back to “play”', $('icPlay').style.display==='');
  ok('no JS errors', w.__errs.length===0, w.__errs.join(';'));
}

console.log('\n--- the instrumental is 0.3 s longer than the vocal (the other way round) ---');
{
  const d = mk([26.3, 26.0]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  $('btnPlay').click(); await sleep(30);
  w.__advance(26.05);                       // srcs[0] (the backing) still plays — no ended yet
  ok('the second track ending early does not end the song by itself',
     w.__live.size===1, 'live '+w.__live.size);
  w.__advance(0.3);                         // now the backing track ended too
  await sleep(30);
  ok('the song ended properly on the first track', w.__live.size===0);
}

console.log('\n--- the M key under Web Audio ---');
{
  const d = mk([26,26]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  // stems open with the voice switched off (0%) by default
  ok('it starts with the voice off', $('vVocal').textContent==='0%', $('vVocal').textContent);
  w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true}));
  ok('M brings the voice up from silence', $('vVocal').textContent==='100%', $('vVocal').textContent);
  w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true}));
  ok('M mutes it again', $('vVocal').textContent==='0%', $('vVocal').textContent);
}

console.log('\n--- rapid play/pause clicks in a row ---');
{
  const d = mk([26,26]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  for (let i=0;i<6;i++){ $('btnPlay').click(); await sleep(5); }
  await sleep(60);
  ok('no errors after the rapid clicks', w.__errs.length===0, w.__errs.join(';'));
  ok('no more than one live set of sources', w.__live.size<=2, 'live '+w.__live.size);
}

console.log('\n--- “Offset” does not touch the audio ---');
{
  const d = mk([26,26]), w = d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  $('btnPlay').click(); await sleep(20);
  const before = w.__live.size;
  $('rOffset').value='500'; $('rOffset').dispatchEvent(new w.Event('input'));
  await sleep(20);
  ok('shifting the text did not recreate the sources', w.__live.size===before,
     `was ${before}, now ${w.__live.size}`);
}
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
