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
ok('ошибок нет', w.__errs.length===0, w.__errs.join(';'));
ok('создано 2 аудио-элемента', w.__inst.length===2, 'создано '+w.__inst.length);
const [master, voice] = w.__inst;
ok('обе дорожки встроены как data:', master.src.startsWith('data:audio/mpeg;base64,') && voice.src.startsWith('data:audio/'));
ok('дорожки разные', master.src !== voice.src);
ok('бейдж убран из шапки', !$('mBadge'));
ok('в шапке название и исполнитель', $('mTitle').textContent && $('mArtist').textContent,
   $('mTitle').textContent+' / '+$('mArtist').textContent);
ok('регулятор голоса виден', $('grpVocal').style.display !== 'none');
ok('старт = чистая минусовка (голос 0)', voice.volume===0, 'volume='+voice.volume);
$('rVocal').value=100; $('rVocal').dispatchEvent(new w.Event('input'));
ok('голос на 100% => вокал слышен', voice.volume===1 && $('vVocal').textContent==='100%');
$('rVocal').value=45; $('rVocal').dispatchEvent(new w.Event('input'));
ok('промежуточное значение', Math.abs(voice.volume-0.45)<1e-6, 'volume='+voice.volume);
$('btnPlay').click(); await sleep(40);
ok('play запускает обе дорожки', !master.paused && !voice.paused);
// расхождение дорожек должно вылечиться
voice.currentTime = master.currentTime + 0.5; master.currentTime = 10; await sleep(80);
ok('рассинхрон дорожек исправляется', Math.abs(voice.currentTime-master.currentTime)<0.09,
   'дельта='+Math.abs(voice.currentTime-master.currentTime).toFixed(3));
$('btnPlay').click(); await sleep(30);
ok('pause останавливает обе', master.paused && voice.paused);
console.log(fail?`\nПРОВАЛЕНО: ${fail}`:'\nВсе проверки пройдены');
process.exit(fail?1:0);
