// The untested paths: slow loading, the end of the song, Web Audio refusing.
const { JSDOM } = await import('jsdom');
import fs from 'fs';
const HTML = fs.readFileSync(process.env.KARAOKE_PAGE_STEMS, 'utf8');

function mk(opts){
  return new JSDOM(HTML, { runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
    beforeParse(w){
      w.__now=0; w.__started=[]; w.__inst=[]; w.__errs=[];
      class Gain{ constructor(){ this.gain={value:1, setTargetAtTime(v){this.value=v;}}; } connect(){} }
      class Src{ constructor(){ this.onended=null; this.stopped=false; }
        connect(){} start(at,off){ this.at=at; this.off=off; w.__started.push(this); }
        stop(){ this.stopped=true; } }
      class AC{ constructor(){ this.state="suspended"; this.destination={}; }
        get currentTime(){ return w.__now; }
        createGain(){ return new Gain(); } createBufferSource(){ return new Src(); }
        decodeAudioData(b, ok, err){
          if (opts.decodeFails){ if(err){err(new Error('bad')); return;} return Promise.reject(new Error('bad')); }
          const buf={duration:26.04}; if(ok){ok(buf); return;} return Promise.resolve(buf); }
        resume(){ this.state="running"; } close(){} }
      if (!opts.noWebAudio) w.AudioContext = AC;
      w.fetch = opts.fetchFails
        ? () => Promise.reject(new Error('no access'))
        : () => new Promise(r => setTimeout(()=>r({arrayBuffer:()=>Promise.resolve(new ArrayBuffer(8))}),
                                            opts.slow ? 250 : 0));
      class FA{ constructor(){ this.paused=true; this.volume=1; this.duration=26.04; this._t=0;
        this._h={}; w.__inst.push(this); setTimeout(()=>this._fire('loadedmetadata'),0); }
        get currentTime(){return this._t;} set currentTime(v){this._t=v;}
        addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
        _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
        play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;} }
      w.Audio=FA; w.onerror=m=>w.__errs.push(String(m));
      w.Element.prototype.getBoundingClientRect=function(){
        return {left:0,top:0,width:500,height:20,right:500,bottom:20,x:0,y:0}; };
      w.Element.prototype.setPointerCapture=function(){};
    }});
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};

console.log('--- play pressed while the audio still loads ---');
{
  const d=mk({slow:true}), w=d.window, $=id=>w.document.getElementById(id);
  await sleep(30);
  $('btnPlay').click();                       // the engine is still "loading"
  ok('the icon shows playing right away', $('icPause').style.display==='');
  ok('nothing was started too early', w.__started.length===0);
  await sleep(500);
  ok('once loaded, the audio started by itself', w.__started.length===2, 'starts '+w.__started.length);
  ok('both tracks at one moment', w.__started[0].at===w.__started[1].at);
}

console.log('\n--- seeked while the audio loads ---');
{
  const d=mk({slow:true}), w=d.window, $=id=>w.document.getElementById(id);
  await sleep(30);
  w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
  await sleep(500);
  $('btnPlay').click(); await sleep(50);
  ok('the seek was not lost', w.__started.length===2 && Math.abs(w.__started[0].off-5)<0.2,
     'start at '+(w.__started[0]?w.__started[0].off.toFixed(2):'—'));
}

console.log('\n--- the end of the song ---');
{
  const d=mk({}), w=d.window, $=id=>w.document.getElementById(id);
  await sleep(200);
  $('btnPlay').click(); await sleep(40);
  w.__now += 27;                              // played to the very end
  const src=w.__started[0]; if (src.onended) src.onended();
  await sleep(40);
  ok('at the end the button went back to “play”', $('icPlay').style.display==='');
  const before=w.__started.length;
  $('btnPlay').click(); await sleep(40);
  ok('starting again begins from the top',
     w.__started.length===before+2 && w.__started[before].off===0,
     'start at '+w.__started[before].off);
}

console.log('\n--- Web Audio is unavailable ---');
{
  const d=mk({noWebAudio:true}), w=d.window, $=id=>w.document.getElementById(id);
  await sleep(200);
  ok('we switched to separate media elements', w.__inst.length===2, 'elements '+w.__inst.length);
  $('btnPlay').click(); await sleep(50);
  ok('the audio plays anyway', w.__inst.every(a=>!a.paused));
  $('rVocal').value='70'; $('rVocal').dispatchEvent(new w.Event('input')); await sleep(20);
  ok('the voice slider works here too', Math.abs(w.__inst[1].volume-0.7)<1e-9,
     'volume='+w.__inst[1].volume);
}

console.log('\n--- decoding failed ---');
{
  const d=mk({decodeFails:true}), w=d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  ok('it fell back to media elements', w.__inst.length===2, 'elements '+w.__inst.length);
  $('btnPlay').click(); await sleep(50);
  ok('it plays', w.__inst.every(a=>!a.paused));
}

console.log('\n--- the audio sits in separate files with no access ---');
{
  const d=mk({fetchFails:true}), w=d.window, $=id=>w.document.getElementById(id);
  await sleep(250);
  ok('it fell back to media elements', w.__inst.length===2, 'elements '+w.__inst.length);
  ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(';'));
}

console.log('\n--- starting from a clean instrumental ---');
{
  const d=mk({}), w=d.window, $=id=>w.document.getElementById(id);
  await sleep(200);
  ok('the voice is off on opening', $('vVocal').textContent==='0%', $('vVocal').textContent);
}
console.log(fail?`\nFAILED: ${fail}`:'\nAll checks passed');
process.exit(fail?1:0);
